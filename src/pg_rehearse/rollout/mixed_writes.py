"""Committed rollout operations: assertions must pass before writes can commit."""

from collections.abc import Callable
from contextlib import AbstractContextManager

import psycopg

from pg_rehearse.models import OperationResult
from pg_rehearse.rollout.phases import PlannedOperation
from pg_rehearse.workload.runner import run_operation


def run_actions(
    plan: list[PlannedOperation],
    connect: Callable[[], AbstractContextManager[psycopg.Connection[tuple[object, ...]]]],
    statement_ms: int,
) -> list[OperationResult]:
    results = []
    for item in plan:
        with connect() as connection:
            result = run_operation(
                connection,
                item.operation,
                version=item.version,
                phase=item.phase,
                statement_ms=statement_ms,
                actor=item.actor,
                commit=item.commit,
            )
        results.append(result)
        if not result.success:
            break  # A dependent read must not claim coverage after its write failed.
    return results
