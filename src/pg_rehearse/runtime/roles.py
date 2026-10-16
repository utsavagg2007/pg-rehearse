"""Trusted bootstrap declarations; user SQL never runs in this administrative context."""

import secrets
from typing import Literal

from psycopg import sql
from pydantic import SecretStr

from pg_rehearse.models import Timeouts

Role = Literal["setup", "migration", "workload", "observer"]
ROLE_NAMES: dict[Role, str] = {
    "setup": "rehearse_setup",
    "migration": "rehearse_migration",
    "workload": "rehearse_workload",
    "observer": "rehearse_observer",
}


def new_credentials() -> dict[Role, SecretStr]:
    return {role: SecretStr(secrets.token_urlsafe(32)) for role in ROLE_NAMES}


def bootstrap_sql(credentials: dict[Role, SecretStr], timeouts: Timeouts) -> str:
    """Only fixed identifiers, generated passwords and validated integer settings."""
    statements: list[sql.Composable] = [sql.SQL("BEGIN; SET LOCAL statement_timeout = '5000ms';")]
    for role, name in ROLE_NAMES.items():
        identifier = sql.Identifier(name)
        statements.append(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 16 PASSWORD {};"
            ).format(identifier, sql.Literal(credentials[role].get_secret_value()))
        )
        for setting, value in {
            "statement_timeout": f"{timeouts.statement_ms}ms",
            "lock_timeout": f"{timeouts.lock_ms}ms",
            "idle_in_transaction_session_timeout": f"{timeouts.statement_ms}ms",
        }.items():
            statements.append(
                sql.SQL("ALTER ROLE {} SET {} = {};").format(
                    identifier, sql.Identifier(setting), sql.Literal(value)
                )
            )
    statements.append(
        sql.SQL("""
        REVOKE ALL ON DATABASE rehearsal FROM PUBLIC;
        REVOKE CONNECT ON DATABASE postgres, template1 FROM PUBLIC;
        GRANT CONNECT ON DATABASE rehearsal TO
            rehearse_setup, rehearse_migration, rehearse_workload, rehearse_observer;
        REVOKE ALL ON SCHEMA public FROM PUBLIC;
        ALTER SCHEMA public OWNER TO rehearse_migration;
        GRANT USAGE ON SCHEMA public TO rehearse_workload, rehearse_observer;
        GRANT rehearse_migration TO rehearse_setup WITH INHERIT FALSE, SET TRUE;
        GRANT pg_read_all_stats TO rehearse_observer WITH INHERIT TRUE, SET FALSE;
        ALTER DEFAULT PRIVILEGES FOR ROLE rehearse_migration IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rehearse_workload;
        ALTER DEFAULT PRIVILEGES FOR ROLE rehearse_migration IN SCHEMA public
            GRANT USAGE ON SEQUENCES TO rehearse_workload;
        ALTER ROLE rehearse_observer SET default_transaction_read_only = on;
        COMMIT;
    """)
    )
    return "\n".join(statement.as_string() for statement in statements)
