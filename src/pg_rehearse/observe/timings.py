"""Closed-loop client samples, including consumption, assertions and commit."""

import time

import psycopg

from pg_rehearse.models import OperationSpec, TimingSample
from pg_rehearse.workload.runner import run_operation


def measure(
    connection: psycopg.Connection[tuple[object, ...]],
    operations: list[OperationSpec],
    *,
    warmups: int,
    samples: int,
    statement_ms: int,
) -> list[TimingSample]:
    results = []
    connection.prepare_threshold = 0
    for warmup, count in ((True, warmups), (False, samples)):
        for iteration in range(count):
            for operation in operations:
                started = time.perf_counter_ns()
                result = run_operation(
                    connection,
                    operation,
                    version="benchmark",
                    phase="benchmark",
                    statement_ms=statement_ms,
                    commit=True,
                )
                results.append(
                    TimingSample(
                        operation_id=operation.id,
                        iteration=iteration,
                        warmup=warmup,
                        elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
                        success=result.success,
                        error_kind=result.error_kind,
                        sqlstate=result.sqlstate,
                    )
                )
                if connection.closed or connection.broken:
                    return results
    return results
