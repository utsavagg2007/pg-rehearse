import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from typer.testing import CliRunner

from pg_rehearse.cli import app
from pg_rehearse.config import load_config, load_yaml, parse_yaml, read_snapshot, resolve_input
from pg_rehearse.errors import ConfigurationError, UnsupportedInputError
from pg_rehearse.orchestrator import validated_environment


@pytest.mark.parametrize(
    "update",
    [
        {"schema_version": True},
        {"seed": "42"},
        {"seed": -1},
        {"seed": 2**32},
        {"name": "   "},
        {"postgres_image": "postgres:16"},
        {"postgres_image": "evil/image:17"},
        {"timeouts": {"statement_ms": 1, "lock_ms": 10}},
        {"timeouts": {"unknown": 1}},
        {"timeouts": {"worker_seconds": 0}},
        {"timeouts": {"worker_seconds": "60"}},
    ],
)
def test_strict_manifest_fields(rehearsal_project: Path, update: dict[str, object]) -> None:
    path = rehearsal_project / "rehearsal.yml"
    data = yaml.safe_load(path.read_text())
    data.update(update)
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigurationError):
        load_config(path)


@pytest.mark.parametrize(
    "table,row",
    [
        ("missing", {"id": 1}),
        ("users", {"id": True, "name": "Ada", "email": "a"}),
        ("users", {"id": "7", "name": "Ada", "email": "a"}),
        ("users", {"id": 2**63, "name": "Ada", "email": "a"}),
        ("users", {"id": 7, "name": None, "email": "a"}),
        ("users", {"id": 7, "email": "a"}),
        ("users", {"id": 7, "name": "Ada", "email": "a", "unknown": 1}),
        ("orders", {"id": 1, "user_id": 999, "status": "pending", "amount_cents": 0}),
    ],
)
def test_fixture_rows_are_checked_against_baseline(
    rehearsal_project: Path, table: str, row: dict[str, object]
) -> None:
    path = rehearsal_project / "fixtures/orders.yml"
    path.write_text(yaml.safe_dump({"tables": {table: [row]}}))
    with pytest.raises(ConfigurationError):
        load_config(rehearsal_project / "rehearsal.yml")


def test_duplicate_fixture_keys_are_rejected(rehearsal_project: Path) -> None:
    path = rehearsal_project / "fixtures/orders.yml"
    data = yaml.safe_load(path.read_text())
    data["tables"]["users"].append(dict(data["tables"]["users"][0]))
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigurationError, match="duplicate"):
        load_config(rehearsal_project / "rehearsal.yml")


@pytest.mark.parametrize(
    "content", ["x: &x [*x]", "x: {<<: {a: 1}}", "x: " + "[" * 50 + "0" + "]" * 50]
)
def test_alias_merge_and_nesting_are_bounded(tmp_path: Path, content: str) -> None:
    path = tmp_path / "bad.yml"
    path.write_text(content)
    with pytest.raises(ConfigurationError):
        load_yaml(path)


@pytest.mark.parametrize("error_type", [ConfigurationError, UnsupportedInputError])
def test_yaml_keeps_existing_input_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[ConfigurationError]
) -> None:
    error = error_type("Specific input explanation")
    monkeypatch.setattr("pg_rehearse.config.yaml.load", MagicMock(side_effect=error))
    with pytest.raises(error_type) as raised:
        parse_yaml("name: example", tmp_path / "input.yml")
    assert raised.value is error


def test_duplicate_yaml_key_explanation_is_preserved(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Duplicate YAML key: 'name'"):
        parse_yaml("name: first\nname: second\n", tmp_path / "input.yml")


@pytest.mark.parametrize("command", ["validate", "run"])
def test_oversized_yaml_integer_is_invalid_before_allocation(
    rehearsal_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    path = rehearsal_project / "rehearsal.yml"
    number = "9" * 5000
    path.write_text(path.read_text().replace("seed: 42", f"seed: {number}"))
    allocator = MagicMock(side_effect=AssertionError("Docker must not be reached"))
    monkeypatch.setattr("pg_rehearse.orchestrator.DockerRuntime", allocator)
    state = tmp_path / "runs"
    arguments = [command, "--config", str(path)]
    if command == "run":
        arguments.extend(["--state-dir", str(state)])
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 2, result.output
    assert "invalid YAML value" in " ".join(result.output.split())
    assert number[:100] not in result.output
    allocator.assert_not_called()
    assert not state.exists()


@pytest.mark.parametrize(
    "value", ["C:\\outside.sql", "\\\\server\\share\\x.sql", "schema/../base.sql", "a\x00b"]
)
def test_ambiguous_or_traversing_paths_are_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigurationError):
        resolve_input(tmp_path, Path(value))


def test_special_files_and_oversized_inputs_do_not_block(tmp_path: Path) -> None:
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ConfigurationError, match="regular file"):
        read_snapshot(fifo)
    large = tmp_path / "large.sql"
    large.write_bytes(b"x" * (1_048_576 + 1))
    with pytest.raises(ConfigurationError, match="1 MiB"):
        read_snapshot(large)


@pytest.mark.parametrize(
    "sql,code", [("DROP TABLE users;", 4), ("ALTER TABLE ;", 2), ("BEGIN;", 4)]
)
def test_invalid_rehearsal_cannot_reach_allocation(
    rehearsal_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sql: str, code: int
) -> None:
    (rehearsal_project / "migrations/rename_user_name.sql").write_text(sql)
    allocator = MagicMock(side_effect=AssertionError("Docker must not be reached"))
    monkeypatch.setattr("pg_rehearse.orchestrator.DockerRuntime", allocator)
    state = tmp_path / "state"
    with pytest.raises(ConfigurationError):
        with validated_environment(rehearsal_project / "rehearsal.yml", state_dir=state):
            pytest.fail("Invalid input produced a runtime")
    allocator.assert_not_called()
    assert not state.exists()
    for command in ("validate", "run"):
        result = CliRunner().invoke(
            app, [command, "--config", str(rehearsal_project / "rehearsal.yml")]
        )
        assert result.exit_code == code, result.output


def test_symlinked_input_cannot_escape_root(rehearsal_project: Path, tmp_path: Path) -> None:
    path = rehearsal_project / "schema/base.sql"
    outside = tmp_path / "outside.sql"
    outside.write_text(path.read_text())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ConfigurationError, match="escapes"):
        load_config(rehearsal_project / "rehearsal.yml")


@pytest.mark.parametrize(
    "datatype,value,valid",
    [
        ("smallint", 32767, True),
        ("smallint", 32768, False),
        ("boolean", True, True),
        ("boolean", 1, False),
        ("varchar(3)", "Ada", True),
        ("varchar(3)", "Grace", False),
        ("numeric", "12.50", True),
        ("numeric", "NaN", False),
        ("uuid", "12345678-1234-1234-1234-123456789abc", True),
        ("uuid", "invalid", False),
        ("date", "2026-10-15", True),
        ("date", "2026-02-31", False),
        ("timestamptz", "2026-10-15T12:00:00Z", True),
        ("timestamptz", "2026-10-15T12:00:00", False),
    ],
)
def test_fixture_values_respect_declared_column_types(
    rehearsal_project: Path, datatype: str, value: object, valid: bool
) -> None:
    schema = rehearsal_project / "schema/base.sql"
    schema.write_text(schema.read_text().replace("name TEXT NOT NULL", f"name {datatype} NOT NULL"))
    fixture = rehearsal_project / "fixtures/orders.yml"
    fixture.write_text(
        yaml.safe_dump(
            {"tables": {"users": [{"id": 7, "name": value, "email": "ada@example.test"}]}}
        )
    )
    if valid:
        load_config(rehearsal_project / "rehearsal.yml")
    else:
        with pytest.raises(ConfigurationError):
            load_config(rehearsal_project / "rehearsal.yml")


@pytest.mark.parametrize("kind", ["path", "fixture", "yaml"])
def test_non_sql_validation_also_precedes_docker(
    rehearsal_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path = rehearsal_project / "rehearsal.yml"
    if kind == "fixture":
        (rehearsal_project / "fixtures/orders.yml").write_text("tables: {unknown: [{id: 1}]}")
    elif kind == "yaml":
        path.write_text("name: first\nname: second\n")
    else:
        data = yaml.safe_load(path.read_text())
        data["schema_path"] = "../outside.sql"
        path.write_text(yaml.safe_dump(data))
    allocator = MagicMock(side_effect=AssertionError("Docker must not be reached"))
    monkeypatch.setattr("pg_rehearse.orchestrator.DockerRuntime", allocator)
    with pytest.raises(ConfigurationError):
        with validated_environment(path, state_dir=tmp_path / "runs"):
            pytest.fail("Invalid input produced a runtime")
    allocator.assert_not_called()
