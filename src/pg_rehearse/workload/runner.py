"""Bound contract probes in independent rollback-only transactions."""

import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

import psycopg

from pg_rehearse.errors import WorkerDeadline
from pg_rehearse.migration.classify import validate_contract
from pg_rehearse.migration.preflight import bound_sql_for_parse, parse_document
from pg_rehearse.models import ContractSpec, OperationResult, OperationSpec, Scalar
from pg_rehearse.workload.assertions import (
    MAX_RESULT_BYTES,
    MAX_RESULT_ROWS,
    compare_results,
    encoded,
    normalize,
)


class _DeadlineInterrupt(KeyboardInterrupt):
    """Use Psycopg's interrupt path to cancel and drain an active command."""


@contextmanager
def execution_deadline(seconds: float) -> Iterator[None]:
    """Linux worker main thread; nested budgets cannot extend an existing deadline."""

    def expired(signum: int, frame: FrameType | None) -> None:
        raise _DeadlineInterrupt()

    started = time.monotonic()
    handler = signal.getsignal(signal.SIGALRM)
    previous = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, previous[0]) if previous[0] else seconds)
    try:
        yield
    except _DeadlineInterrupt:
        raise WorkerDeadline("Worker execution deadline exceeded") from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, handler)
        remaining = previous[0] - (time.monotonic() - started)
        if previous[0] and remaining > 0:
            signal.setitimer(signal.ITIMER_REAL, remaining, previous[1])


class ResultLimitError(ValueError):
    """Result consumption exceeded the declared bounded probe envelope."""


def collect_rows(
    cursor: psycopg.Cursor[tuple[object, ...]],
) -> tuple[list[str], list[list[Scalar]]]:
    columns = [column.name for column in cursor.description or []]
    used = len(encoded(columns).encode())
    rows: list[list[Scalar]] = []
    for record in cursor:
        row = [normalize(value) for value in record]
        used += len(encoded(row).encode())
        if len(rows) >= MAX_RESULT_ROWS or used > MAX_RESULT_BYTES:
            raise ResultLimitError("Probe result exceeded row or byte budget")
        rows.append(row)
    if used > MAX_RESULT_BYTES:
        raise ResultLimitError("Probe columns exceeded byte budget")
    return columns, rows


def run_operation(
    connection: psycopg.Connection[tuple[object, ...]],
    operation: OperationSpec,
    *,
    version: str,
    phase: str,
    statement_ms: int,
    actor: str | None = None,
    commit: bool = False,
) -> OperationResult:
    result = OperationResult(operation_id=operation.id, version=version, phase=phase, success=False)
    result.actor = actor
    result.backend_pid = connection.info.backend_pid if actor else None
    parsed = parse_document(
        bound_sql_for_parse(operation.sql, operation.parameters, operation.id), operation.id
    )
    validate_contract(parsed)
    is_select = parsed.statements[0].kind == "SelectStmt"
    columns: list[str]
    rows: list[list[Scalar]]
    try:
        with (
            execution_deadline(statement_ms / 1000),
            connection.transaction(force_rollback=not commit),
        ):
            with (
                connection.cursor(name="rehearse_probe")
                if is_select
                else connection.cursor() as cursor
            ):
                if isinstance(cursor, psycopg.ServerCursor):
                    cursor.itersize = 1
                # shortcut: libpq buffers DML RETURNING; stream before supporting large writes.
                cursor.execute(operation.sql, operation.parameters or None)
                if cursor.description is None:
                    columns, rows, count = [], [], cursor.rowcount
                else:
                    columns, rows = collect_rows(cursor)
                    count = len(rows)
                result.assertions = compare_results(operation.expect, columns, rows, count)
                result.success = all(assertion.passed for assertion in result.assertions)
                if not result.success:
                    result.error_kind = "assertion_error"
            if commit and not result.success:
                raise psycopg.Rollback()
        result.committed = commit and result.success
    except psycopg.Error as exc:
        result.sqlstate = exc.sqlstate
        result.error_kind = (
            "connection_error" if connection.broken or connection.closed else "sql_error"
        )
    except WorkerDeadline:
        result.error_kind = "operation_deadline"
    except ResultLimitError:
        result.error_kind = "result_limit"
    except ValueError:
        result.error_kind = "unsupported_result"
    if result.error_kind not in (None, "assertion_error"):
        result.success = False
        result.assertions = []
    return result


def run_contract(
    connection: psycopg.Connection[tuple[object, ...]],
    contract: ContractSpec,
    *,
    phase: str,
    statement_ms: int,
) -> list[OperationResult]:
    results = []
    for operation in contract.operations:
        results.append(
            run_operation(
                connection,
                operation,
                version=contract.version,
                phase=phase,
                statement_ms=statement_ms,
            )
        )
        if connection.broken or connection.closed:
            break
    return results
