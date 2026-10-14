from pathlib import Path

from typer.testing import CliRunner

from pg_rehearse import __version__
from pg_rehearse.cli import app
from pg_rehearse.errors import ExitCode

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


def test_pending_run_never_claims_success() -> None:
    result = runner.invoke(app, ["run", "--config", str(EXAMPLE)])
    assert result.exit_code == ExitCode.INCONCLUSIVE
    assert "not implemented" in result.output


def test_python_environment_check_can_skip_docker() -> None:
    result = runner.invoke(app, ["doctor", "--skip-docker"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "Docker check skipped" in result.output
