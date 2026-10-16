"""Fresh branch declarations; database administration stays in the trusted host helper."""

from psycopg import sql

from pg_rehearse.fixtures.template import template_marker
from pg_rehearse.models import TemplateEvidence
from pg_rehearse.worker_protocol import WorkerTask, task_database


def clone_sql(
    run_id: str,
    ownership_token: str,
    template: TemplateEvidence,
    expected_identity: str,
    task: WorkerTask,
) -> str:
    if not template.sealed or template.identity != expected_identity:
        raise ValueError("Stale or unsealed template identity")
    if task not in {"baseline_probe", "post_deployed", "post_candidate", "rollout", "rollback"}:
        raise ValueError("Only independent experiments receive a clone")
    marker = template_marker(run_id, ownership_token, expected_identity)
    database = sql.Identifier(task_database(run_id, task))
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
        REVOKE ALL ON DATABASE {database} FROM PUBLIC;
        GRANT CONNECT ON DATABASE {database} TO
            rehearse_setup, rehearse_migration, rehearse_workload, rehearse_observer;
    """)
        .format(marker=sql.Literal(marker), database=database)
        .as_string()
    )
