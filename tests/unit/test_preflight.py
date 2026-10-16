from pathlib import Path

import pytest

from pg_rehearse.config import load_config
from pg_rehearse.errors import ConfigurationError, UnsupportedInputError
from pg_rehearse.migration.classify import baseline_catalog, classify_migration, validate_contract
from pg_rehearse.migration.preflight import bound_sql_for_parse, parse_document
from pg_rehearse.models import TransactionMode

BASE = "CREATE TABLE users (id bigint PRIMARY KEY, name text NOT NULL);"


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE users (id integer) ON COMMIT DROP;",
        "CREATE TEMP TABLE users (id integer);",
        "CREATE TABLE users (id integer) PARTITION BY HASH (id);",
        "CREATE TABLE users (id serial);",
        "CREATE TABLE users (id bigint GENERATED ALWAYS AS IDENTITY);",
        "DO $$ BEGIN RAISE NOTICE 'x'; END $$;",
    ],
)
def test_baseline_rejects_unmodeled_setup_behavior(sql: str) -> None:
    with pytest.raises(UnsupportedInputError):
        baseline_catalog(parse_document(sql, "base.sql"))


@pytest.mark.parametrize(
    "sql,family",
    [
        ("ALTER TABLE users RENAME COLUMN name TO full_name;", "rename_column"),
        ("CREATE INDEX ix ON users (name);", "create_index"),
        ("ALTER TABLE users ADD CONSTRAINT good CHECK (id > 0);", "add_check"),
        ("ALTER TABLE users ADD CONSTRAINT good CHECK (id > 0) NOT VALID;", "add_check"),
    ],
)
def test_supported_migrations_are_ast_classified(sql: str, family: str) -> None:
    result = classify_migration(
        parse_document(sql, "migration.sql"),
        TransactionMode.TRANSACTION,
        baseline_catalog(parse_document(BASE, "base.sql")),
    )
    assert result[0].family == family
    assert result[0].statement.sql == sql.rstrip(";")


def test_named_check_can_be_added_validated_and_replaced() -> None:
    sql = """ALTER TABLE users ADD CONSTRAINT good CHECK (id > 0) NOT VALID;
ALTER TABLE users VALIDATE CONSTRAINT good;
ALTER TABLE users DROP CONSTRAINT good, ADD CONSTRAINT good CHECK (id >= 0);"""
    result = classify_migration(
        parse_document(sql, "m.sql"),
        TransactionMode.TRANSACTION,
        baseline_catalog(parse_document(BASE, "b.sql")),
    )
    assert [item.family for item in result] == [
        "add_check",
        "validate_check",
        "drop_check",
        "add_check",
    ]


@pytest.mark.parametrize(
    "sql",
    [
        "BEGIN;",
        "COMMIT;",
        "SET ROLE postgres;",
        "CREATE EXTENSION dblink;",
        "DO $$ BEGIN RAISE NOTICE 'x'; END $$;",
        "DROP TABLE users;",
        "ALTER TABLE users ADD COLUMN age integer;",
        "ALTER TABLE users ALTER COLUMN name TYPE varchar;",
        "CREATE UNIQUE INDEX ix ON users (name);",
        "CREATE INDEX ix ON users USING hash (name);",
        "CREATE INDEX ix ON users (lower(name));",
        "CREATE INDEX ix ON users (name) WHERE id > 0;",
        "CREATE INDEX ix ON users (name) INCLUDE (id);",
        "CREATE INDEX IF NOT EXISTS ix ON users (name);",
        "ALTER TABLE users ADD CONSTRAINT key UNIQUE (name);",
        "ALTER TABLE users ADD CONSTRAINT aggregate_check CHECK (count(id) > 0);",
        "ALTER TABLE users DROP CONSTRAINT users_pkey;",
        "ALTER TABLE users RENAME TO people;",
        "ALTER DATABASE postgres RENAME TO pwn;",
        "ALTER TABLE pg_catalog.pg_class RENAME COLUMN relname TO x;",
        "COPY users TO PROGRAM 'id';",
        "SELECT 1;",
    ],
)
def test_unsupported_sql_cannot_become_supported(sql: str) -> None:
    with pytest.raises(UnsupportedInputError):
        classify_migration(
            parse_document(sql, "bad.sql"),
            TransactionMode.TRANSACTION,
            baseline_catalog(parse_document(BASE, "b.sql")),
        )


def test_concurrent_index_requires_one_autocommit_statement() -> None:
    document = parse_document("CREATE INDEX CONCURRENTLY ix ON users (name);", "m.sql")
    with pytest.raises(ConfigurationError, match="autocommit"):
        classify_migration(
            document, TransactionMode.TRANSACTION, baseline_catalog(parse_document(BASE, "b.sql"))
        )
    result = classify_migration(
        document, TransactionMode.AUTOCOMMIT, baseline_catalog(parse_document(BASE, "b.sql"))
    )
    assert result[0].concurrent
    with pytest.raises(ConfigurationError, match="exactly one"):
        classify_migration(
            parse_document(document.text + " CREATE INDEX other ON users (id);", "m.sql"),
            TransactionMode.AUTOCOMMIT,
            baseline_catalog(parse_document(BASE, "b.sql")),
        )


@pytest.mark.parametrize("sql", ["", "-- comment", "ALTER TABLE ;", "SELECT (", "SELECT '\x00';"])
def test_invalid_sql_is_not_a_valid_preflight(sql: str) -> None:
    with pytest.raises(ConfigurationError):
        parse_document(sql, "bad.sql")


def test_unicode_comments_and_semicolons_preserve_statement_spans() -> None:
    sql = "-- é;\nALTER TABLE users RENAME COLUMN name TO full_name;\nSELECT ';';"
    doc = parse_document(sql, "m.sql")
    assert len(doc.statements) == 2
    assert doc.statements[0].line == 2
    assert doc.statements[0].column == 1
    assert doc.statements[1].line == 3
    assert doc.text == sql
    assert "SELECT ';'" in doc.statements[1].sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(1);",
        "SELECT * INTO stolen FROM users;",
        "SELECT * FROM pg_catalog.pg_authid;",
        "WITH changed AS (DELETE FROM users RETURNING *) SELECT * FROM changed;",
        "SELECT 1; SELECT 2;",
        "COPY users FROM STDIN;",
        "SET session_authorization postgres;",
    ],
)
def test_contracts_reject_unmodeled_side_effects(sql: str) -> None:
    with pytest.raises(ConfigurationError):
        validate_contract(parse_document(sql, "contract.yml"))


def test_named_and_positional_parameters_are_parsed_without_rewriting_inputs() -> None:
    assert (
        bound_sql_for_parse("SELECT %s::bigint, %s;", [7, "Ada"], "x") == "SELECT $1::bigint, $2;"
    )
    sql = "SELECT %(id)s WHERE %(id)s > 0 AND '100%%' <> '';"
    normalized = bound_sql_for_parse(sql, {"id": 7}, "x")
    assert normalized == "SELECT $1 WHERE $1 > 0 AND '100%' <> '';"
    validate_contract(parse_document(normalized, "x"))
    assert "%(id)s" in sql
    assert bound_sql_for_parse("SELECT '100%';", [], "x") == "SELECT '100%';"


@pytest.mark.parametrize(
    "sql,params",
    [
        ("SELECT %s;", [1, 2]),
        ("SELECT %s, %s;", [1]),
        ("SELECT 1;", [1]),
        ("SELECT $1;", [1]),
        ("SELECT %(id)s;", {"other": 1}),
        ("SELECT %s;", {"id": 1}),
        ("SELECT %(id)s;", [1]),
        ("SELECT %b;", [1]),
        ("SELECT '%s', %s;", [1, 2]),
        ("SELECT %s -- %s\n;", [1, 2]),
        ("SELECT $$%s$$, %s;", [1, 2]),
        ('SELECT U&"col%s", %s;', [1, 2]),
    ],
)
def test_binding_mismatches_fail_before_execution(sql: str, params: object) -> None:
    with pytest.raises(ConfigurationError):
        bound_sql_for_parse(sql, params, "contract")


def test_snapshots_do_not_change_when_files_are_edited_later(rehearsal_project: Path) -> None:
    loaded = load_config(rehearsal_project / "rehearsal.yml")
    original = loaded.migration_sql[0].text
    loaded.migration_paths[0].write_text("DROP TABLE users;")
    assert loaded.migration_sql[0].text == original
    assert loaded.classifications[0].family == "rename_column"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users(id,name) VALUES(1,'Ada') RETURNING id,name",
        "INSERT INTO users(id,name) VALUES(1,'Ada'),(2,'Grace')",
        "UPDATE users SET name='Grace' WHERE id=1 RETURNING name",
        "DELETE FROM users WHERE id=1 RETURNING id",
    ],
)
def test_ordinary_dml_is_supported(sql: str) -> None:
    validate_contract(parse_document(sql, "contract"))


@pytest.mark.parametrize("mode", ["SYSTEM", "USER"])
def test_explicit_identity_override_is_not_silently_accepted(mode: str) -> None:
    with pytest.raises(UnsupportedInputError):
        validate_contract(
            parse_document(f"INSERT INTO users OVERRIDING {mode} VALUE VALUES(1,'Ada')", "contract")
        )
