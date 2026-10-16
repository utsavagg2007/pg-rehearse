"""Worker-only diagnostic dispatch; Docker and clone administration stay on the host."""

from pg_rehearse.analysis.locks import lock_coverage
from pg_rehearse.benchmarks.runner import measure_arm, selected_operations
from pg_rehearse.config import LoadedConfig
from pg_rehearse.migration.executor import execute_migrations
from pg_rehearse.observe.locks import execute_contention
from pg_rehearse.observe.plans import capture_plan
from pg_rehearse.worker_protocol import WorkerEvidence, WorkerRequest, experiment_id


def execute_diagnostics(
    request: WorkerRequest, loaded: LoadedConfig, evidence: WorkerEvidence
) -> None:
    from pg_rehearse.worker import connect_as

    if request.task == "contention":
        execute_contention(request, loaded, evidence)
        evidence.coverage = lock_coverage(evidence.contention)
        evidence.completion = (
            "complete"
            if not evidence.coverage.missing
            and len(evidence.migrations) == len(loaded.spec.migrations)
            else "partial"
        )
        return
    migrating = request.task == "plan_candidate" or request.arm == "candidate"
    if migrating:
        with connect_as(request, "migration") as connection:
            evidence.migrations = execute_migrations(
                connection, loaded, phase=experiment_id(request.task, request.trial, request.arm)
            )
        if len(evidence.migrations) != len(loaded.spec.migrations) or not all(
            m.committed for m in evidence.migrations
        ):
            evidence.completion = "partial"
            return
    # Apply the same statistics preparation to every arm after its schema is finalized.
    with connect_as(request, "migration") as connection:
        connection.execute("ANALYZE")
    with connect_as(request, "workload") as connection:
        if request.task == "benchmark":
            evidence.benchmark = measure_arm(connection, loaded)
            benchmark = loaded.spec.benchmark
            if benchmark and len(evidence.benchmark.samples) != (
                benchmark.warmups + benchmark.samples
            ) * len(benchmark.operations):
                evidence.completion = "partial"
                return
        else:
            spec = loaded.spec.plans
            if spec is None:
                raise ValueError("Missing plan declaration")
            for operation in selected_operations(loaded, spec.operations):
                evidence.plans.append(capture_plan(connection, operation, analyze=spec.analyze))
    evidence.completion = "complete"
