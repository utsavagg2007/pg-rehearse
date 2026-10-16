"""Template identity and fixed administrative SQL, executed only by the host helper."""

import hashlib

from psycopg import sql

from pg_rehearse.config import LoadedConfig
from pg_rehearse.models import BaselineEvidence, TemplateEvidence
from pg_rehearse.workload.assertions import encoded


def template_identity(loaded: LoadedConfig, image_id: str) -> str:
    fixture_hash = next(
        (
            snapshot.sha256
            for snapshot in loaded.input_snapshots
            if snapshot.path == loaded.fixtures_path
        ),
        None,
    )
    return hashlib.sha256(
        encoded(
            [
                1,
                image_id,
                loaded.schema_sql.sha256,
                fixture_hash,
                loaded.spec.seed,
            ]
        ).encode()
    ).hexdigest()


def template_marker(run_id: str, ownership_token: str, identity: str) -> str:
    return f"pg-rehearse/{run_id}/{ownership_token}/{identity}"


def seal_template_sql(
    run_id: str,
    ownership_token: str,
    identity: str,
    baseline: BaselineEvidence,
) -> tuple[str, TemplateEvidence]:
    if not baseline.success or baseline.data_sha256 is None:
        raise ValueError("Only a verified baseline can become a template")
    marker = template_marker(run_id, ownership_token, identity)
    statements = sql.SQL("""
        SET statement_timeout = '5000ms';
        COMMENT ON DATABASE rehearsal IS {};
        ALTER DATABASE rehearsal ALLOW_CONNECTIONS false;
        SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE datname = 'rehearsal' AND pid <> pg_backend_pid();
    """).format(sql.Literal(marker))
    return statements.as_string(), TemplateEvidence(
        identity=identity,
        data_sha256=baseline.data_sha256,
        sealed=True,
    )
