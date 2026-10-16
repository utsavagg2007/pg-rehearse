"""Worker-side schema-first timeline, with explicit SQL and HTTP phase barriers."""

from contextlib import AbstractContextManager, ExitStack
from itertools import groupby
from typing import TYPE_CHECKING

import psycopg

from pg_rehearse.migration.executor import execute_migrations
from pg_rehearse.models import ApplicationResult
from pg_rehearse.rollout import apps
from pg_rehearse.rollout.mixed_writes import run_actions
from pg_rehearse.rollout.orders_app import Version, revision
from pg_rehearse.rollout.phases import phase_results, rollout_plan
from pg_rehearse.rollout.rollback import committed_pairs_complete
from pg_rehearse.rollout.validation import rollout_coverage
from pg_rehearse.workload.runner import run_operation
from pg_rehearse.workload.sessions import persistent_sessions

if TYPE_CHECKING:
    from pg_rehearse.config import LoadedConfig
    from pg_rehearse.worker_protocol import WorkerEvidence, WorkerRequest


def execute_rollout(
    request: "WorkerRequest", loaded: "LoadedConfig", evidence: "WorkerEvidence"
) -> None:
    from pg_rehearse.worker import connect_as

    plan = rollout_plan(loaded, request.task)
    groups = [(phase, list(items)) for phase, items in groupby(plan, key=lambda item: item.phase)]
    rollout, app_spec = loaded.spec.rollout, loaded.spec.applications
    if rollout is None:
        raise ValueError("Missing rollout")

    def connect() -> AbstractContextManager[psycopg.Connection[tuple[object, ...]]]:
        return connect_as(request, "workload")

    with ExitStack() as stack:
        old_sessions = (
            persistent_sessions(stack, connect, rollout.persistent_old_sessions)
            if request.task == "rollout"
            else {}
        )
        for phase, items in groups:
            if not phase.startswith("rollout_baseline/"):
                continue
            connection = old_sessions[items[0].actor]
            for item in items:
                evidence.operations.append(
                    run_operation(
                        connection,
                        item.operation,
                        version=item.version,
                        phase=item.phase,
                        statement_ms=request.timeouts.statement_ms,
                        actor=item.actor,
                    )
                )
        if any(not result.success for result in evidence.operations):
            _finish(loaded, evidence)
            return

        def start_app(version: Version, phase: str, actor: str) -> apps.Application | None:
            try:
                return apps.start(stack, request, version)
            except (OSError, ValueError, TimeoutError):
                evidence.applications.append(
                    ApplicationResult(
                        probe_id="user.get",
                        phase=phase,
                        actor=actor,
                        version=version,
                        revision=revision(version),
                        success=False,
                        error_kind="process_error",
                    )
                )
                return None

        old_app = None
        if app_spec:
            phase = "app_baseline" if request.task == "rollout" else "app_rollback_baseline"
            old_app = start_app("deployed", phase, "old")
            if old_app:
                evidence.applications.append(apps.user_probe(old_app, app_spec, phase, "old"))
            if old_app is None or not evidence.applications[-1].success:
                _finish(loaded, evidence)
                return
        with connect_as(request, "migration") as migration:
            evidence.migrations = execute_migrations(migration, loaded, phase=request.task)
        if len(evidence.migrations) != len(loaded.spec.migrations) or not all(
            step.committed for step in evidence.migrations
        ):
            _finish(loaded, evidence)
            return
        candidate_app = None
        if app_spec and old_app:
            if request.task == "rollout":
                evidence.applications.append(
                    apps.user_probe(old_app, app_spec, "app_persistent_old", "old")
                )
                fresh = start_app("deployed", "app_fresh_old", "fresh_old")
                if fresh:
                    evidence.applications.append(
                        apps.user_probe(fresh, app_spec, "app_fresh_old", "fresh_old")
                    )
                else:
                    _finish(loaded, evidence)
                    return
            phase = "app_candidate" if request.task == "rollout" else "app_rollback_candidate"
            candidate_app = start_app("candidate", phase, "candidate")
            if candidate_app:
                evidence.applications.append(
                    apps.user_probe(candidate_app, app_spec, phase, "candidate")
                )
            else:
                _finish(loaded, evidence)
                return
        for phase, items in groups:
            if phase.startswith("rollout_baseline/"):
                continue
            if phase.startswith("persistent_old/"):
                connection = old_sessions[items[0].actor]
                for item in items:
                    evidence.operations.append(
                        run_operation(
                            connection,
                            item.operation,
                            version=item.version,
                            phase=item.phase,
                            statement_ms=request.timeouts.statement_ms,
                            actor=item.actor,
                        )
                    )
            elif phase == "fresh_old":
                with connect() as connection:
                    for item in items:
                        evidence.operations.append(
                            run_operation(
                                connection,
                                item.operation,
                                version=item.version,
                                phase=item.phase,
                                statement_ms=request.timeouts.statement_ms,
                                actor=item.actor,
                            )
                        )
            else:
                if phase == "candidate_only":
                    for connection in old_sessions.values():
                        connection.close()
                observed = run_actions(items, connect, request.timeouts.statement_ms)
                evidence.operations.extend(observed)
                if not committed_pairs_complete(items, observed):
                    break
        # Stop old traffic for the target phase; application rollback has its own branch.
        for connection in old_sessions.values():
            connection.close()
        if app_spec and old_app and candidate_app:
            phase = "app_mixed_versions" if request.task == "rollout" else "app_rollback"
            if request.task == "rollout":
                pair = apps.order_pair(old_app, candidate_app, app_spec, phase, 1, "pending")
                evidence.applications.extend(pair)
                if not all(result.success for result in pair):
                    _finish(loaded, evidence)
                    return
            pair = apps.order_pair(
                candidate_app,
                old_app,
                app_spec,
                phase,
                2 if request.task == "rollout" else 3,
                app_spec.candidate_status,
            )
            evidence.applications.extend(pair)
            if request.task == "rollout" and all(result.success for result in pair):
                apps.stop(old_app)
                order = {
                    "id": app_spec.order_id_base + 2,
                    "user_id": app_spec.user_id,
                    "status": app_spec.candidate_status,
                    "amount_cents": 100,
                }
                evidence.applications.append(
                    apps.probe(
                        candidate_app,
                        phase="app_candidate_only",
                        actor="candidate",
                        probe_id="order.get",
                        path=f"/orders/{order['id']}",
                        expected=order,
                    )
                )
        _finish(loaded, evidence)


def _finish(loaded: "LoadedConfig", evidence: "WorkerEvidence") -> None:
    plan = rollout_plan(loaded, evidence.task)
    evidence.phases = phase_results(plan, evidence.operations)
    evidence.coverage = rollout_coverage(loaded, evidence)
    ready = len(evidence.migrations) == len(loaded.spec.migrations) and all(
        step.committed for step in evidence.migrations
    )
    evidence.completion = "complete" if ready and not evidence.coverage.missing else "partial"
