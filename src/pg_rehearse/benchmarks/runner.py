"""One fresh, sequential benchmark arm; cloning belongs to the host runtime."""

import hashlib
import platform

import psycopg

from pg_rehearse.config import LoadedConfig
from pg_rehearse.models import BenchmarkEvidence, OperationSpec, Scalar
from pg_rehearse.observe.timings import measure
from pg_rehearse.workload.assertions import encoded


def selected_operations(loaded: LoadedConfig, ids: list[str]) -> list[OperationSpec]:
    operations = {op.id: op for op in loaded.deployed_contract.operations}
    return [operations[name] for name in ids]


def schedule_hash(loaded: LoadedConfig) -> str:
    spec = loaded.spec.benchmark
    if spec is None:
        raise ValueError("Missing benchmark declaration")
    schedule = [op.model_dump(mode="json") for op in selected_operations(loaded, spec.operations)]
    return hashlib.sha256(encoded([schedule, spec.warmups, spec.samples]).encode()).hexdigest()


def measure_arm(
    connection: psycopg.Connection[tuple[object, ...]], loaded: LoadedConfig
) -> BenchmarkEvidence:
    spec = loaded.spec.benchmark
    if spec is None:
        raise ValueError("Missing benchmark declaration")
    settings: dict[str, Scalar] = {
        "machine": platform.machine(),
        "python": platform.python_version(),
        "prepare_threshold": 0,
        "concurrency": 1,
        "timer_resolution_seconds": time_resolution(),
        "statement_ms": loaded.spec.timeouts.statement_ms,
        "lock_ms": loaded.spec.timeouts.lock_ms,
    }
    for setting in (
        "server_version",
        "shared_buffers",
        "work_mem",
        "effective_cache_size",
        "plan_cache_mode",
        "jit",
    ):
        row = connection.execute("SELECT current_setting(%s)", [setting]).fetchone()
        settings[setting] = str(row[0]) if row else None
    return BenchmarkEvidence(
        samples=measure(
            connection,
            selected_operations(loaded, spec.operations),
            warmups=spec.warmups,
            samples=spec.samples,
            statement_ms=loaded.spec.timeouts.statement_ms,
        ),
        environment=settings,
        schedule_sha256=schedule_hash(loaded),
    )


def time_resolution() -> float:
    import time

    return time.get_clock_info("perf_counter").resolution
