"""Atomic baseline setup from accepted snapshots and explicit deterministic fixtures."""

import hashlib
from collections import Counter
from typing import Literal

import psycopg
from psycopg import sql

from pg_rehearse.fixtures.validate import validate_fixtures
from pg_rehearse.migration.classify import baseline_catalog
from pg_rehearse.migration.preflight import SQLDocument
from pg_rehearse.models import BaselineEvidence, FixtureSpec
from pg_rehearse.workload.assertions import encoded, normalize
from pg_rehearse.workload.runner import collect_rows


def seed_baseline(
    connection: psycopg.Connection[tuple[object, ...]],
    schema: SQLDocument,
    fixtures: FixtureSpec | None,
    seed: int,
) -> BaselineEvidence:
    catalog = baseline_catalog(schema)
    tables = validate_fixtures(fixtures, catalog, schema.source)
    statements = {stmt.node["relation"]["relname"]: stmt.sql for stmt in schema.statements}
    evidence = BaselineEvidence(success=False, seed=seed, schema_statements=0)
    stage: Literal["schema_error", "fixture_error", "verification_error"] = "schema_error"
    try:
        with connection.transaction():
            for name in tables:
                connection.execute(statements[name])
            stage = "fixture_error"
            for name, rows in tables.items():
                columns = list(catalog.tables[name].columns)
                relation = sql.Identifier("public", name)
                query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    relation,
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                )
                if rows:
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            query, [[row[column] for column in columns] for row in rows]
                        )
                for column in catalog.tables[name].columns.values():
                    if not column.identity:
                        continue
                    sequence = connection.execute(
                        "SELECT pg_get_serial_sequence(%s,%s)", [relation.as_string(), column.name]
                    ).fetchone()
                    maximum = connection.execute(
                        sql.SQL("SELECT max({}) FROM {}").format(
                            sql.Identifier(column.name), relation
                        )
                    ).fetchone()
                    if not sequence or not sequence[0] or not maximum:
                        raise ValueError("Missing identity sequence")
                    value = maximum[0]
                    connection.execute(
                        "SELECT setval(%s::regclass,%s,%s)",
                        [
                            sequence[0],
                            max(1, value) if isinstance(value, int) else 1,
                            isinstance(value, int) and value >= 1,
                        ],
                    )
            stage = "verification_error"
            verified = verify_baseline(connection, schema, fixtures, seed)
            if not verified.success:
                evidence.sqlstate = verified.sqlstate
                raise ValueError("Loaded fixture verification failed")
            for name in tables:
                connection.execute(sql.SQL("ANALYZE {}").format(sql.Identifier("public", name)))
        evidence.success = True
        evidence.schema_statements = len(schema.statements)
        evidence.table_rows = verified.table_rows
        evidence.data_sha256 = verified.data_sha256
    except (psycopg.Error, ValueError) as exc:
        evidence.error_kind = stage
        evidence.sqlstate = exc.sqlstate if isinstance(exc, psycopg.Error) else evidence.sqlstate
    return evidence


def verify_baseline(
    connection: psycopg.Connection[tuple[object, ...]],
    schema: SQLDocument,
    fixtures: FixtureSpec | None,
    seed: int,
) -> BaselineEvidence:
    """Read a fresh branch before any probe or migration can mutate its state."""
    catalog = baseline_catalog(schema)
    tables = validate_fixtures(fixtures, catalog, schema.source)
    evidence = BaselineEvidence(success=False, seed=seed, schema_statements=0)
    try:
        with connection.transaction():
            digest = hashlib.sha256()
            counts = {}
            for name, expected in tables.items():
                columns = list(catalog.tables[name].columns)
                with connection.cursor(name="verify_fixture") as cursor:
                    cursor.itersize = 1
                    cursor.execute(
                        sql.SQL("SELECT {} FROM {}").format(
                            sql.SQL(",").join(map(sql.Identifier, columns)),
                            sql.Identifier("public", name),
                        )
                    )
                    _, actual = collect_rows(cursor)
                expected_rows = [
                    encoded([normalize(row[column]) for column in columns]) for row in expected
                ]
                actual_rows = [encoded(row) for row in actual]
                if Counter(expected_rows) != Counter(actual_rows):
                    raise ValueError("Loaded fixture data does not match accepted rows")
                counts[name] = len(actual)
                digest.update(encoded([name, columns, sorted(actual_rows)]).encode())
        evidence.success = True
        evidence.schema_statements = len(schema.statements)
        evidence.table_rows = counts
        evidence.data_sha256 = digest.hexdigest()
    except (psycopg.Error, ValueError) as exc:
        evidence.error_kind = "verification_error"
        evidence.sqlstate = exc.sqlstate if isinstance(exc, psycopg.Error) else None
    return evidence
