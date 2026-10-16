from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from pg_rehearse import __version__
from pg_rehearse.cli import app
from pg_rehearse.errors import ExitCode
from pg_rehearse.models import CleanupStatus, RunResult

runner = CliRunner()
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "orders" / "rehearsal.yml"


def test_help_lists_foundation_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "doctor" in result.output
    assert "validate" in result.output


def test_version_does_not_require_a_command() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert __version__ in result.output


def test_validate_example_is_explicit_about_scope() -> None:
    result = runner.invoke(app, ["validate", "--config", str(EXAMPLE)])
    assert result.exit_code == ExitCode.SUCCESS
    assert "Configuration valid" in result.output
    assert "unverified" in result.output


def test_invalid_config_has_input_exit_code(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "--config", str(tmp_path / "missing.yml")])
    assert result.exit_code == ExitCode.INVALID_INPUT
    assert "Invalid configuration" in result.output


def test_missing_run_evidence_never_claims_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pg_rehearse.cli.run_rehearsal",
        Mock(
            return_value=(
                RunResult(run_id="a" * 32, cleanup=CleanupStatus.COMPLETE),
                Path("/tmp/run"),
            )
        ),
    )
    result = runner.invoke(app, ["run", "--config", str(EXAMPLE)])
    assert result.exit_code == ExitCode.INCONCLUSIVE
    assert "inconclusive" in result.output
    assert "cleanup complete" in result.output
    assert "report.json" in result.output


def test_python_environment_check_can_skip_docker() -> None:
    result = runner.invoke(app, ["doctor", "--skip-docker"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "Docker check skipped" in result.output


def test_full_run_invalid_input_precedes_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allocator = Mock(side_effect=AssertionError("must not allocate"))
    monkeypatch.setattr("pg_rehearse.orchestrator.DockerRuntime", allocator)
    result = runner.invoke(app, ["run", "--config", str(tmp_path / "missing.yml")])
    assert result.exit_code == 2
    allocator.assert_not_called()
