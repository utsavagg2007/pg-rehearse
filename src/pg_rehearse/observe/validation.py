"""Pure validation of diagnostic identities, schedules, barriers and original plans."""

from typing import TYPE_CHECKING

from pg_rehearse.analysis.locks import lock_coverage, observed_wait
from pg_rehearse.analysis.plans import normalize_plan
from pg_rehearse.benchmarks.runner import schedule_hash
from pg_rehearse.models import Coverage
from pg_rehearse.rollout.phases import write_operation
from pg_rehearse.worker_protocol import experiment_id, verify_migrations
from pg_rehearse.workload.contracts import verify_operation

if TYPE_CHECKING:
    from pg_rehearse.config import LoadedConfig
    from pg_rehearse.worker_protocol import WorkerEvidence, WorkerRequest


def verify_diagnostics(
    loaded: "LoadedConfig", request: "WorkerRequest", evidence: "WorkerEvidence"
) -> None:
    task = request.task
    if evidence.operations or evidence.phases or evidence.applications:
        raise ValueError("Unexpected contract or application claims in diagnostic task")
    migrating = task in {"contention", "plan_candidate"} or request.arm == "candidate"
    ready = (
        verify_migrations(
            loaded, evidence.migrations, experiment_id(task, request.trial, request.arm)
        )
        if migrating
        else True
    )
    if not migrating and evidence.migrations:
        raise ValueError("Unchanged arm cannot execute migrations")
    if task != "contention" and evidence.contention or task != "benchmark" and evidence.benchmark:
        raise ValueError("Wrong diagnostic evidence kind")
    if not task.startswith("plan_") and evidence.plans:
        raise ValueError("Undeclared plan evidence")
    if task == "contention":
        spec = loaded.spec.contention
        result = evidence.contention
        if spec is None or result is None or result.poll_ms != spec.poll_ms:
            raise ValueError("Missing contention declaration or result")
        pids = result.actor_pids
        if (
            set(pids) != {"blocker", "migrator", "probe", "observer"}
            or len(set(pids.values())) != 4
            or any(type(pid) is not int or pid <= 0 for pid in pids.values())
        ):
            raise ValueError("Wrong contention actor identities")
        for declared, actual, actor in (
            (spec.blocker, result.blocker, "blocker"),
            (spec.probe, result.probe, "probe"),
        ):
            if actual:
                if (
                    actual.operation_id,
                    actual.version,
                    actual.phase,
                    actual.actor,
                    actual.backend_pid,
                    actual.committed,
                ) != (declared.id, "deployed", f"contention_{actor}", actor, pids[actor], False):
                    raise ValueError("Wrong contention operation identity")
                verify_operation(declared, actual)
        for sample in result.samples:
            if any(a.pid not in pids.values() for a in sample.activity) or any(
                lock.pid not in pids.values() for lock in sample.locks
            ):
                raise ValueError("Observation includes an unrelated backend")
            for actor, pid in pids.items():
                if any(
                    a.application_name != f"pgr/{request.run_id[:12]}/contention/{actor}"
                    for a in sample.activity
                    if a.pid == pid
                ):
                    raise ValueError("Observer actor identity mismatch")
        for times in (
            [s.elapsed_ms for s in result.samples],
            [e.elapsed_ms for e in result.events],
        ):
            if times != sorted(times):
                raise ValueError("Non-monotonic observation timeline")
        names = [e.name for e in result.events]
        allowed = [
            "blocker_acquired",
            "migration_submitted",
            "migration_wait_observed",
            "probe_submitted",
            "blocker_released",
            "migration_finished",
            "probe_finished",
        ]
        if len(names) != len(set(names)) or names != [name for name in allowed if name in names]:
            raise ValueError("Invalid contention barrier sequence")
        waiting = observed_wait(result, "migrator", "blocker")
        if (
            ("migration_wait_observed" in names) != waiting
            or ("probe_submitted" in names) != waiting
            or result.blocker_released != ("blocker_released" in names)
        ):
            raise ValueError("Claimed contention barriers lack sampled evidence")
        if result.probe and not waiting or evidence.migrations and not result.blocker:
            raise ValueError("Dependent actor ran before its barrier")
        if evidence.migrations and not {
            "blocker_acquired",
            "migration_submitted",
            "migration_finished",
        } <= set(names):
            raise ValueError("Missing migration actor barriers")
        if result.probe and "probe_finished" not in names:
            raise ValueError("Missing probe completion barrier")
        if evidence.coverage != lock_coverage(result):
            raise ValueError("Contention coverage disagrees with observations")
        complete = not evidence.coverage.missing and len(evidence.migrations) == len(
            loaded.spec.migrations
        )
    elif task == "benchmark":
        spec_b = loaded.spec.benchmark
        if spec_b is None or request.trial is None or request.trial > spec_b.trials:
            raise ValueError("Undeclared benchmark trial")
        measured = evidence.benchmark
        expected = [
            (name, iteration, warmup)
            for warmup, count in ((True, spec_b.warmups), (False, spec_b.samples))
            for iteration in range(count)
            for name in spec_b.operations
        ]
        actual_schedule = (
            [(s.operation_id, s.iteration, s.warmup) for s in measured.samples] if measured else []
        )
        if actual_schedule != expected[: len(actual_schedule)] or len(actual_schedule) > len(
            expected
        ):
            raise ValueError("Benchmark sample schedule mismatch")
        if measured:
            if not ready or measured.schedule_sha256 != schedule_hash(loaded):
                raise ValueError("Benchmark identity or migration barrier mismatch")
            required_settings = {
                "server_version",
                "machine",
                "python",
                "prepare_threshold",
                "concurrency",
                "timer_resolution_seconds",
                "shared_buffers",
                "work_mem",
                "effective_cache_size",
                "plan_cache_mode",
                "jit",
                "statement_ms",
                "lock_ms",
            }
            if (
                set(measured.environment) != required_settings
                or measured.environment["prepare_threshold"] != 0
                or measured.environment["concurrency"] != 1
                or measured.environment["statement_ms"] != request.timeouts.statement_ms
                or measured.environment["lock_ms"] != request.timeouts.lock_ms
            ):
                raise ValueError("Missing measurement environment")
            for timing in measured.samples:
                if (
                    timing.success != (timing.error_kind is None and timing.sqlstate is None)
                    or timing.elapsed_ms > request.timeouts.worker_seconds * 1000
                ):
                    raise ValueError("Inconsistent timing outcome")
        complete = ready and len(actual_schedule) == len(expected)
    else:
        spec_p = loaded.spec.plans
        if spec_p is None or len(evidence.plans) > len(spec_p.operations):
            raise ValueError("Undeclared plan capture")
        operations = {op.id: op for op in loaded.deployed_contract.operations}
        for name, plan in zip(spec_p.operations, evidence.plans, strict=False):
            if (
                not ready
                or plan.operation_id != name
                or plan.analyze != spec_p.analyze
                or plan.committed
                != (plan.success and spec_p.analyze and write_operation(operations[name]))
            ):
                raise ValueError("Plan identity, execution consent or commit mismatch")
            if plan.settings != {
                "prepare_threshold": None,
                "prepared_history": "fresh diagnostic connection",
                "plan_cache_mode": "auto",
            }:
                raise ValueError("Unexpected plan preparation settings")
            if plan.success:
                if plan.error_kind or plan.sqlstate or plan.raw is None:
                    raise ValueError("Incomplete plan result")
                normalize_plan(plan.raw)
                if plan.analyze and "Execution Time" not in plan.raw:
                    raise ValueError("Missing execution-capable plan metrics")
            elif plan.raw is not None or not plan.error_kind:
                raise ValueError("Failed plan cannot claim raw evidence")
        complete = ready and len(evidence.plans) == len(spec_p.operations)
    if task != "contention" and evidence.coverage != Coverage():
        raise ValueError("Advisory diagnostics cannot claim compatibility coverage")
    if (evidence.completion == "complete") != complete:
        raise ValueError("Incomplete diagnostic evidence cannot complete a task")
