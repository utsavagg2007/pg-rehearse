from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from pg_rehearse.config import load_config, load_worker_config
from pg_rehearse.errors import UnsupportedInputError
from pg_rehearse.fixtures.validate import validate_fixtures
from pg_rehearse.migration.classify import baseline_catalog
from pg_rehearse.migration.preflight import parse_document
from pg_rehearse.models import FixtureSpec, SemanticAssertions
from pg_rehearse.orchestrator import worker_inputs
from pg_rehearse.workload.assertions import compare_results, normalize, summarize
from pg_rehearse.workload.runner import ResultLimitError, collect_rows


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("12.50"), "12.50"),
        (date(2026, 10, 16), "2026-10-16"),
        (datetime(2026, 10, 16, tzinfo=UTC), "2026-10-16T00:00:00+00:00"),
        (
            datetime(2026, 10, 16, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            "2026-10-16T00:00:00+00:00",
        ),
        (UUID("12345678-1234-1234-1234-123456789abc"), "12345678-1234-1234-1234-123456789abc"),
    ],
)
def test_result_scalars_have_stable_json_representations(value: object, expected: str) -> None:
    assert normalize(value) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), b"bytes", [1]])
def test_unsupported_results_cannot_become_passes(value: object) -> None:
    with pytest.raises(ValueError):
        normalize(value)


def test_all_assertions_are_checked_and_types_and_order_matter() -> None:
    expected = SemanticAssertions(
        columns=["id", "active"], rows=[[1, True], [2, False]], row_count=2
    )
    result = compare_results(expected, ["active", "id"], [[1, 1], [2, 0]], 3)
    assert [item.name for item in result if not item.passed] == ["columns", "rows", "row_count"]
    assert not compare_results(expected, ["id", "active"], [[2, False], [1, True]], 2)[1].passed


def test_large_assertions_keep_hashes_without_hiding_differences() -> None:
    expected = SemanticAssertions(rows=[["x" * 2000]])
    result = compare_results(expected, ["text"], [["x" * 1999 + "y"]], 1)[0]
    assert not result.passed
    assert result.expected == summarize(expected.rows)
    assert result.expected["sha256"] != result.actual["sha256"]


@pytest.mark.parametrize("limit", ["rows", "bytes"])
def test_result_consumption_enforces_budgets(monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    cursor = MagicMock()
    cursor.description = [SimpleNamespace(name="value")]
    cursor.__iter__.return_value = iter([(1,), (2,), (3,)])
    monkeypatch.setattr(
        "pg_rehearse.workload.runner.MAX_RESULT_ROWS", 2 if limit == "rows" else 100
    )
    monkeypatch.setattr(
        "pg_rehearse.workload.runner.MAX_RESULT_BYTES", 100 if limit == "rows" else 1
    )
    with pytest.raises(ResultLimitError):
        collect_rows(cursor)


def test_copied_preflight_supports_contained_symlink_aliases(rehearsal_project: Path) -> None:
    path = rehearsal_project / "schema/base.sql"
    path.rename(path.with_name("actual.sql"))
    path.symlink_to("actual.sql")
    loaded = load_config(rehearsal_project / "rehearsal.yml")
    copied = worker_inputs(loaded)
    path.unlink()
    worker = load_worker_config(copied)
    assert worker.schema_sql.text == loaded.schema_sql.text
    assert worker.deployed_contract == loaded.deployed_contract


def test_fixture_dependencies_are_ordered_without_mutating_declarations() -> None:
    schema = parse_document(
        "CREATE TABLE child (id int PRIMARY KEY, parent_id int REFERENCES parent(id));"
        "CREATE TABLE parent (id int PRIMARY KEY, manager int REFERENCES parent(id));",
        "test",
    )
    fixtures = FixtureSpec(
        tables={
            "child": [{"id": 3, "parent_id": 2}],
            "parent": [{"id": 2, "manager": 1}, {"id": 1, "manager": None}],
        }
    )
    ordered = validate_fixtures(fixtures, baseline_catalog(schema), "test")
    assert list(ordered) == ["parent", "child"]
    assert [row["id"] for row in ordered["parent"]] == [1, 2]
    assert fixtures.tables["parent"][0]["id"] == 2


@pytest.mark.parametrize(
    "schema,rows",
    [
        (
            "CREATE TABLE t (id int PRIMARY KEY, parent int REFERENCES t(id));",
            {"t": [{"id": 1, "parent": 2}, {"id": 2, "parent": 1}]},
        ),
        (
            "CREATE TABLE a (id int PRIMARY KEY, b int REFERENCES b(id));"
            "CREATE TABLE b (id int PRIMARY KEY, a int REFERENCES a(id));",
            {},
        ),
    ],
)
def test_cyclic_dependencies_are_explicitly_unsupported(schema: str, rows: dict) -> None:
    with pytest.raises(UnsupportedInputError, match="cyclic"):
        validate_fixtures(
            FixtureSpec(tables=rows), baseline_catalog(parse_document(schema, "test")), "test"
        )


def test_identity_support_is_narrow_and_requires_explicit_fixture_ids() -> None:
    from pg_rehearse.errors import ConfigurationError

    catalog = baseline_catalog(
        parse_document(
            "CREATE TABLE t (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY);", "test"
        )
    )
    assert catalog.tables["t"].columns["id"].identity
    with pytest.raises(ConfigurationError, match="missing required"):
        validate_fixtures(FixtureSpec(tables={"t": [{}]}), catalog, "test")
    with pytest.raises(UnsupportedInputError):
        baseline_catalog(
            parse_document(
                "CREATE TABLE t (id bigint GENERATED BY DEFAULT AS IDENTITY (START 10));", "test"
            )
        )
