from pathlib import Path

import pytest

from pg_rehearse.config import load_config, load_yaml, resolve_input
from pg_rehearse.errors import ConfigurationError

EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "orders"


@pytest.mark.parametrize("name", ["rehearsal.yml", "control.yml"])
def test_example_configuration_resolves_files(name: str) -> None:
    loaded = load_config(EXAMPLE_ROOT / name)
    assert loaded.schema_path.is_file()
    assert loaded.fixtures_path is not None and loaded.fixtures_path.is_file()
    assert all(path.is_file() for path in loaded.migration_paths)
    assert loaded.deployed_contract.version == "deployed-v1"


def test_rename_example_contains_old_and_new_column_contracts() -> None:
    loaded = load_config(EXAMPLE_ROOT / "rehearsal.yml")
    assert loaded.candidate_contract is not None
    assert loaded.deployed_contract.operations[0].expect.columns == ["id", "name"]
    assert loaded.candidate_contract.operations[0].expect.columns == ["id", "full_name"]


@pytest.mark.parametrize("content", ["name: one\nname: two\n", "[]", "x: [", "42"])
def test_rejects_ambiguous_or_invalid_yaml(tmp_path: Path, content: str) -> None:
    path = tmp_path / "config.yml"
    path.write_text(content)
    with pytest.raises(ConfigurationError):
        load_yaml(path)


def test_safe_loader_rejects_python_object_tags(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("x: !!python/object:builtins.object {}\n")
    with pytest.raises(ConfigurationError):
        load_yaml(path)


def test_rejects_unknown_configuration_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("name: test\nunexpected: true\n")
    with pytest.raises(ConfigurationError, match="unexpected"):
        load_config(path)


def test_rejects_parent_path_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.sql").write_text("SELECT 1;")
    with pytest.raises(ConfigurationError, match="escapes"):
        resolve_input(project, Path("../outside.sql"))


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.sql"
    outside.write_text("SELECT 1;")
    (project / "linked.sql").symlink_to(outside)
    with pytest.raises(ConfigurationError, match="escapes"):
        resolve_input(project, Path("linked.sql"))


def test_rejects_absolute_paths(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="relative"):
        resolve_input(tmp_path, tmp_path / "input.sql")


def test_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        resolve_input(tmp_path, Path("missing.sql"))


def test_rejects_directory_input(tmp_path: Path) -> None:
    (tmp_path / "directory").mkdir()
    with pytest.raises(ConfigurationError, match="regular file"):
        resolve_input(tmp_path, Path("directory"))
