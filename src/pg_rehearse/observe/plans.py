"""Bounded diagnostic EXPLAIN on its own clone, outside timed workloads."""

import json

import psycopg
from psycopg import sql

from pg_rehearse.analysis.plans import normalize_plan
from pg_rehearse.models import OperationSpec, PlanEvidence, Scalar
from pg_rehearse.rollout.phases import write_operation


def capture_plan(
    connection: psycopg.Connection[tuple[object, ...]], operation: OperationSpec, *, analyze: bool
) -> PlanEvidence:
    setting = connection.execute("SHOW plan_cache_mode").fetchone()
    settings: dict[str, Scalar] = {
        "prepare_threshold": None,
        "prepared_history": "fresh diagnostic connection",
        "plan_cache_mode": str(setting[0]) if setting else None,
    }
    result = PlanEvidence(
        operation_id=operation.id, analyze=analyze, success=False, settings=settings
    )
    connection.prepare_threshold = None
    try:
        options = "ANALYZE, BUFFERS, TIMING OFF, FORMAT JSON" if analyze else "FORMAT JSON"
        with connection.transaction():
            row = connection.execute(
                sql.SQL("EXPLAIN (" + options + ") ") + sql.SQL(operation.sql),
                operation.parameters or None,
                prepare=False,
            ).fetchone()
            if (
                not row
                or not isinstance(row[0], list)
                or len(row[0]) != 1
                or not isinstance(row[0][0], dict)
            ):
                raise ValueError("Malformed plan")
            raw = row[0][0]
            if len(json.dumps(raw).encode()) > 262_144:
                result.error_kind = "plan_limit"
                raise ValueError("Plan limit")
            normalize_plan(raw)
        result.raw = raw
        result.success = True
        result.committed = analyze and write_operation(operation)
    except psycopg.Error as exc:
        result.error_kind = "sql_error"
        result.sqlstate = exc.sqlstate
    except ValueError:
        result.error_kind = result.error_kind or "invalid_plan"
    return result
