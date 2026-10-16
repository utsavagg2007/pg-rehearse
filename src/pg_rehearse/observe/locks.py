"""Four scoped actors with observed barriers, bounded holds and guaranteed release."""

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime

import psycopg

from pg_rehearse.analysis.locks import observed_wait
from pg_rehearse.config import LoadedConfig
from pg_rehearse.migration.executor import execute_migrations
from pg_rehearse.models import ActivitySample, ClientEvent, ContentionResult, LockFact, LockSample
from pg_rehearse.runtime.roles import Role
from pg_rehearse.worker_protocol import WorkerEvidence, WorkerRequest
from pg_rehearse.workload.runner import run_operation


def sample_locks(
    connection: psycopg.Connection[tuple[object, ...]], pids: list[int], started: float
) -> LockSample:
    tick = time.monotonic()
    activity = connection.execute(
        """
        SELECT pid, application_name, state, wait_event_type, wait_event, pg_blocking_pids(pid)
        FROM pg_stat_activity WHERE datname = current_database() AND pid = ANY(%s)
        ORDER BY pid
    """,
        [pids],
    ).fetchall()
    locks = connection.execute(
        """
        SELECT pid, locktype, mode, granted, waitstart::text, relation::bigint, transactionid::text
        FROM pg_locks WHERE pid = ANY(%s) ORDER BY pid, locktype, mode, granted
    """,
        [pids],
    ).fetchall()
    return LockSample(
        elapsed_ms=(tick - started) * 1000,
        observed_at=datetime.now(UTC).isoformat(),
        overhead_ms=(time.monotonic() - tick) * 1000,
        activity=[
            ActivitySample.model_validate(
                dict(
                    zip(
                        (
                            "pid",
                            "application_name",
                            "state",
                            "wait_event_type",
                            "wait_event",
                            "blockers",
                        ),
                        row,
                        strict=True,
                    )
                )
            )
            for row in activity
        ],
        locks=[
            LockFact.model_validate(
                dict(
                    zip(
                        (
                            "pid",
                            "locktype",
                            "mode",
                            "granted",
                            "waitstart",
                            "relation",
                            "transactionid",
                        ),
                        row,
                        strict=True,
                    )
                )
            )
            for row in locks
        ],
    )


def execute_contention(
    request: WorkerRequest, loaded: LoadedConfig, evidence: WorkerEvidence
) -> None:
    from pg_rehearse.worker import connect_as

    spec = loaded.spec.contention
    if spec is None:
        raise ValueError("Missing contention declaration")
    started = time.monotonic()
    with ExitStack() as stack:
        actors: list[tuple[str, Role]] = [
            ("blocker", "workload"),
            ("migrator", "migration"),
            ("probe", "workload"),
            ("observer", "observer"),
        ]
        connections = {
            actor: stack.enter_context(connect_as(request, role, actor=actor))
            for actor, role in actors
        }
        result = ContentionResult(
            actor_pids={actor: conn.info.backend_pid for actor, conn in connections.items()},
            poll_ms=spec.poll_ms,
        )
        evidence.contention = result
        last_poll: float | None = None

        def event(name: str) -> None:
            result.events.append(
                ClientEvent(name=name, elapsed_ms=(time.monotonic() - started) * 1000)
            )

        def poll() -> bool:
            nonlocal last_poll
            tick = time.monotonic()
            if last_poll is not None:
                result.missed_polls += max(0, int((tick - last_poll) * 1000 // spec.poll_ms) - 1)
            last_poll = tick
            if len(result.samples) >= 1000:
                result.missed_polls += 1
                return False
            try:
                result.samples.append(
                    sample_locks(connections["observer"], list(result.actor_pids.values()), started)
                )
            except psycopg.Error:
                result.observer_error = "database_error"
                return False
            elapsed = (time.monotonic() - tick) * 1000
            time.sleep(max(0, (spec.poll_ms - elapsed) / 1000))
            return True

        migration = probe = None
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                with connections["blocker"].transaction(force_rollback=True):
                    result.blocker = run_operation(
                        connections["blocker"],
                        spec.blocker,
                        version="deployed",
                        phase="contention_blocker",
                        actor="blocker",
                        statement_ms=request.timeouts.statement_ms,
                        commit=True,
                    )
                    # RELEASE SAVEPOINT preserves locks until the outer transaction rolls back.
                    result.blocker.committed = False
                    if not result.blocker.success:
                        return
                    held = time.monotonic()
                    event("blocker_acquired")
                    migration = pool.submit(
                        execute_migrations, connections["migrator"], loaded, phase="contention"
                    )
                    event("migration_submitted")
                    until = time.monotonic() + spec.observe_ms / 1000
                    while time.monotonic() < until and not migration.done():
                        if not poll():
                            break
                        if observed_wait(result, "migrator", "blocker"):
                            event("migration_wait_observed")
                            probe = pool.submit(
                                run_operation,
                                connections["probe"],
                                spec.probe,
                                version="deployed",
                                phase="contention_probe",
                                actor="probe",
                                statement_ms=request.timeouts.statement_ms,
                            )
                            event("probe_submitted")
                            break
                    until = time.monotonic() + (
                        request.timeouts.statement_ms / 1000 + 1
                        if spec.release == "migration_timeout"
                        else spec.observe_ms / 1000
                    )
                    while time.monotonic() < until and not migration.done():
                        if not poll():
                            break
                        if (
                            spec.release == "after_observation"
                            and probe is not None
                            and (probe.done() or observed_wait(result, "probe", "migrator"))
                        ):
                            break
                    result.hold_ms = (time.monotonic() - held) * 1000
                result.blocker_released = True
                event("blocker_released")
                if migration is not None:
                    evidence.migrations = migration.result(
                        timeout=request.timeouts.statement_ms / 1000 + 2
                    )
                    event("migration_finished")
                if probe is not None:
                    result.probe = probe.result(timeout=request.timeouts.statement_ms / 1000 + 2)
                    event("probe_finished")
                poll()
            finally:
                if (
                    connections["blocker"].info.transaction_status
                    == psycopg.pq.TransactionStatus.IDLE
                    and not result.blocker_released
                ):
                    result.blocker_released = True
                    event("blocker_released")
                for actor, future in (("migrator", migration), ("probe", probe)):
                    if future is not None and not future.done():
                        connections[actor].cancel_safe(timeout=1)
                # The blocker context rolls back before thread shutdown on all exits.
