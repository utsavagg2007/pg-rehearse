"""Fresh branch declarations; database administration stays in the trusted host helper."""

from psycopg import sql

from pg_rehearse.fixtures.template import template_marker
from pg_rehearse.models import TemplateEvidence
from pg_rehearse.worker_protocol import BenchmarkArm, WorkerTask, task_database


def clone_sql(
    run_id: str,
    ownership_token: str,
    template: TemplateEvidence,
    expected_identity: str,
    task: WorkerTask,
    trial: int | None = None,
    arm: BenchmarkArm | None = None,
) -> str:
    if not template.sealed or template.identity != expected_identity:
        raise ValueError("Stale or unsealed template identity")
    if task in {"baseline", "seed"}:
        raise ValueError("Only independent experiments receive a clone")
    marker = template_marker(run_id, ownership_token, expected_identity)
    database = sql.Identifier(task_database(run_id, task, trial, arm))
    # The catalog assertion also rejects a stale receipt after the database changed.
    return (
        sql.SQL("""
        SET statement_timeout = '5000ms';
        DO $check$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_database
                WHERE datname = 'rehearsal' AND NOT datallowconn
                  AND datdba = (SELECT oid FROM pg_roles WHERE rolname = 'rehearse_admin')
                  AND shobj_description(oid, 'pg_database') = {marker}
            ) THEN RAISE EXCEPTION 'Unverified template'; END IF;
        END $check$;
        CREATE DATABASE {database} TEMPLATE rehearsal;
        COMMENT ON DATABASE {database} IS {branch_marker};
        REVOKE ALL ON DATABASE {database} FROM PUBLIC;
        GRANT CONNECT ON DATABASE {database} TO
            rehearse_setup, rehearse_migration, rehearse_workload, rehearse_observer;
    """)
        .format(
            marker=sql.Literal(marker),
            database=database,
            branch_marker=sql.Literal(marker + ":" + task_database(run_id, task, trial, arm)),
        )
        .as_string()
    )


def drop_clone_sql(
    run_id: str,
    ownership_token: str,
    identity: str,
    task: WorkerTask,
    trial: int,
    arm: BenchmarkArm,
) -> str:
    """Release a finished benchmark clone without accumulating twenty database copies."""
    if task != "benchmark":
        raise ValueError("Only finished benchmark branches are released early")
    name = task_database(run_id, task, trial, arm)
    marker = template_marker(run_id, ownership_token, identity) + ":" + name
    return (
        sql.SQL("""
        SET statement_timeout = '5000ms';
        DO $check$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_database WHERE datname = {name}
                  AND datdba = (SELECT oid FROM pg_roles WHERE rolname = 'rehearse_admin')
                  AND shobj_description(oid, 'pg_database') = {marker}
            ) THEN RAISE EXCEPTION 'Unowned benchmark branch'; END IF;
        END $check$;
        DROP DATABASE {database};
    """)
        .format(name=sql.Literal(name), marker=sql.Literal(marker), database=sql.Identifier(name))
        .as_string()
    )
