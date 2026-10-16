"""Ordered, committed migration steps on a scoped worker connection."""

from contextlib import nullcontext

import psycopg

from pg_rehearse.config import LoadedConfig
from pg_rehearse.errors import WorkerDeadline
from pg_rehearse.migration.catalog import capture_catalog
from pg_rehearse.models import MigrationResult, TransactionMode
from pg_rehearse.workload.runner import execution_deadline


def execute_migrations(
    connection: psycopg.Connection[tuple[object, ...]], loaded: LoadedConfig, *, phase: str
) -> list[MigrationResult]:
    if not connection.autocommit:
        raise ValueError("Migration executor requires an autocommit worker connection")
    results = []
    for step, document in zip(loaded.spec.migrations, loaded.migration_sql, strict=True):
        result = MigrationResult(
            step_id=step.id,
            phase=phase,
            transaction=step.transaction,
            source_sha256=document.sha256,
            statements=len(document.statements),
            executed=0,
            committed=False,
        )
        try:
            result.catalog_before = capture_catalog(connection)
            boundary = (
                connection.transaction()
                if step.transaction == TransactionMode.TRANSACTION
                else nullcontext()
            )
            with boundary:
                for statement in document.statements:
                    with execution_deadline(loaded.spec.timeouts.statement_ms / 1000):
                        connection.execute(statement.sql)
                    result.executed += 1
            result.committed = True
        except psycopg.Error as exc:
            result.sqlstate = exc.sqlstate
            result.error_kind = (
                "connection_error" if connection.broken or connection.closed else "sql_error"
            )
        except WorkerDeadline:
            result.error_kind = "migration_deadline"
        try:
            result.catalog_after = capture_catalog(connection)
        except (psycopg.Error, ValueError):
            pass  # Missing catalog observations remain missing coverage, never a passing check.
        results.append(result)
        if not result.committed:
            break
    return results
