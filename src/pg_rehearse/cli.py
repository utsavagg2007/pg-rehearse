"""Thin CLI for validation, owned runtime management and evidence-backed rehearsals."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from pg_rehearse import __version__
from pg_rehearse.config import load_config
from pg_rehearse.doctor import check_environment
from pg_rehearse.errors import ConfigurationError, ExitCode, RunInterrupted, RuntimeLifecycleError
from pg_rehearse.models import CleanupStatus
from pg_rehearse.onboarding.clean import clean_run
from pg_rehearse.onboarding.demo import run_demo
from pg_rehearse.onboarding.init import initialize
from pg_rehearse.orchestrator import (
    check_disposable_postgres,
    run_rehearsal,
    termination_signals,
)
from pg_rehearse.report.html import write_html
from pg_rehearse.report.json_report import read_report
from pg_rehearse.report.markdown import write_markdown
from pg_rehearse.report.terminal import render_terminal
from pg_rehearse.runtime.cleanup import recover_run
from pg_rehearse.runtime.docker import RunEnvironment, RuntimeOptions

app = typer.Typer(
    no_args_is_help=True, help="Rehearse PostgreSQL migrations in disposable databases."
)
console = Console()
error_console = Console(stderr=True)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"pg-rehearse {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Check the environment and validate rehearsal inputs."""


@app.command()
def doctor(
    skip_docker: Annotated[
        bool, typer.Option("--skip-docker", help="Check Python dependencies only.")
    ] = False,
) -> None:
    """Check installed dependencies and Docker availability without changing anything."""
    checks = check_environment(skip_docker=skip_docker)
    table = Table(title="pg-rehearse environment")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details", overflow="fold")
    for check in checks:
        table.add_row(check.name, "OK" if check.passed else "FAIL", check.detail)
    console.print(table)
    if skip_docker:
        console.print("Docker check skipped; database readiness has not been verified.")
    if not all(check.passed for check in checks):
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR)


@app.command()
def validate(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to the rehearsal YAML file."),
    ] = Path("examples/orders/rehearsal.yml"),
) -> None:
    """Validate all inputs and PostgreSQL 17 SQL support without allocating resources."""
    try:
        loaded = load_config(config)
    except ConfigurationError as exc:
        error_console.print(f"Invalid configuration: {exc}", markup=False)
        raise typer.Exit(exc.exit_code) from exc
    console.print(f"Configuration valid: {loaded.spec.name}", markup=False)
    console.print(f"Migration steps: {len(loaded.migration_paths)}")
    console.print(f"Deployed operations: {len(loaded.deployed_contract.operations)}")
    if loaded.candidate_contract:
        console.print(f"Candidate operations: {len(loaded.candidate_contract.operations)}")
    for classification in loaded.classifications:
        statement = classification.statement
        console.print(
            f"{classification.family}: {statement.source}:{statement.line}:{statement.column}",
            markup=False,
        )
    console.print(
        f"Input snapshots: {len(loaded.input_snapshots)}; PostgreSQL 17 preflight passed."
    )
    console.print("Database execution and application compatibility remain unverified.")


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to the rehearsal YAML file."),
    ] = Path("examples/orders/rehearsal.yml"),
    state_dir: Annotated[Path, typer.Option(help="Directory for durable run manifests.")] = Path(
        ".pg-rehearse/runs"
    ),
) -> None:
    """Rehearse migrations on fresh branches and save JSON, Markdown and HTML reports."""
    try:
        with termination_signals():
            result, directory = run_rehearsal(config, state_dir=state_dir)
    except ConfigurationError as exc:
        error_console.print(f"Invalid configuration: {exc}", markup=False)
        raise typer.Exit(exc.exit_code) from exc
    except RunInterrupted as exc:
        _show_runtime_error(exc)
        raise typer.Exit(128 + exc.signum) from exc
    except RuntimeLifecycleError as exc:
        _show_runtime_error(exc)
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR) from exc
    render_terminal(result, console)
    console.print(
        f"Reports: {directory / 'report.json'}, "
        f"{directory / 'report.md'}, {directory / 'report.html'}",
        markup=False,
    )
    raise typer.Exit(result.exit_code)


def _show_runtime_error(exc: BaseException) -> None:
    error_console.print(str(exc), markup=False)
    for note in getattr(exc, "__notes__", []):
        error_console.print(note, markup=False)


@app.command()
def sandbox(
    state_dir: Annotated[Path, typer.Option(help="Directory for durable run manifests.")] = Path(
        ".pg-rehearse/runs"
    ),
    startup_seconds: Annotated[float, typer.Option(min=0.01, max=600)] = 60,
    hold_seconds: Annotated[float, typer.Option(min=0, max=3600)] = 0,
    image: Annotated[
        str, typer.Option(help="Installed official PostgreSQL 17 tag, optionally pinned.")
    ] = "postgres:17",
) -> None:
    """Create disposable PostgreSQL, verify readiness, and remove it. No migration verdict."""
    try:
        options = RuntimeOptions(image=image, startup_seconds=startup_seconds)
    except ValidationError as exc:
        error_console.print(
            "Invalid runtime options. Use an official postgres:17 tag or tag@digest."
        )
        raise typer.Exit(ExitCode.INVALID_INPUT) from exc

    def ready(environment: RunEnvironment) -> None:
        console.print(f"PostgreSQL ready. Run: {environment.run_id}", markup=False)
        console.print(f"Manifest: {environment.manifest_path}", markup=False)

    try:
        with termination_signals():
            manifest = check_disposable_postgres(
                state_dir=state_dir, options=options, hold_seconds=hold_seconds, on_ready=ready
            )
    except RunInterrupted as exc:
        _show_runtime_error(exc)
        raise typer.Exit(128 + exc.signum) from exc
    except RuntimeLifecycleError as exc:
        _show_runtime_error(exc)
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR) from exc
    console.print(f"Cleanup: {manifest.cleanup.value}")
    console.print(f"Image: {manifest.image_digest}", markup=False)
    console.print(
        "Disposable runtime check completed. Application compatibility was not evaluated."
    )


@app.command()
def recover(
    manifest: Annotated[Path, typer.Option("--manifest", help="Manifest of one inactive run.")],
) -> None:
    """Recover an interrupted run after verifying ownership; refuse active runs."""
    try:
        result = recover_run(manifest)
    except RuntimeLifecycleError as exc:
        _show_runtime_error(exc)
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR) from exc
    console.print(f"Run {result.run_id}: cleanup {result.cleanup.value}", markup=False)
    if result.cleanup != CleanupStatus.COMPLETE:
        for issue in result.cleanup_errors:
            error_console.print(issue, markup=False)
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR)


@app.command("init")
def init_project(
    directory: Annotated[Path, typer.Argument(help="New starter directory.")] = Path(
        "pg-rehearse-demo"
    ),
    example: Annotated[str, typer.Option(help="Bundled example: orders.")] = "orders",
) -> None:
    """Create validated starter inputs without overwriting existing files."""
    try:
        if example != "orders":
            raise ConfigurationError("Only --example orders is supported")
        project = initialize(directory)
    except ConfigurationError as exc:
        error_console.print(str(exc), markup=False)
        raise typer.Exit(exc.exit_code) from exc
    console.print(f"Created orders starter: {project}", markup=False)
    console.print(f"Next: pg-rehearse validate --config {project / 'rehearsal.yml'}", markup=False)
    console.print("The rename run intentionally returns 1; control.yml should return 0.")


@app.command()
def demo(
    state_dir: Annotated[Path, typer.Option(help="Retained reports and run manifests.")] = Path(
        ".pg-rehearse/runs"
    ),
) -> None:
    """Run the real rename demo; expected exit 1 demonstrates incompatibility."""
    console.print(
        "Running the real orders rename demo; expected exit 1 with deployed SQLSTATE 42703."
    )
    try:
        with termination_signals():
            result, directory = run_demo(state_dir)
    except ConfigurationError as exc:
        error_console.print(str(exc), markup=False)
        raise typer.Exit(exc.exit_code) from exc
    except RunInterrupted as exc:
        _show_runtime_error(exc)
        raise typer.Exit(128 + exc.signum) from exc
    except RuntimeLifecycleError as exc:
        _show_runtime_error(exc)
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR) from exc
    render_terminal(result, console)
    console.print(
        f"Reports: {directory / 'report.json'}, "
        f"{directory / 'report.md'}, {directory / 'report.html'}",
        markup=False,
    )
    raise typer.Exit(result.exit_code)


class ReportFormat(StrEnum):
    TERMINAL = "terminal"
    HTML = "html"
    MARKDOWN = "markdown"


@app.command()
def report(
    result_file: Annotated[Path, typer.Argument(help="Saved report.json; no database connection.")],
    format: Annotated[ReportFormat, typer.Option("--format")] = ReportFormat.TERMINAL,
    output: Annotated[Path | None, typer.Option(help="Destination for HTML or Markdown.")] = None,
) -> None:
    """View or render existing evidence, retaining the saved rehearsal exit code."""
    try:
        result = read_report(result_file)
        if format == ReportFormat.TERMINAL:
            if output is not None:
                raise ConfigurationError("--output requires --format html or markdown")
            render_terminal(result, console)
        else:
            destination = output or result_file.with_suffix(
                ".html" if format == ReportFormat.HTML else ".md"
            )
            if destination.resolve() == result_file.resolve():
                raise ConfigurationError("Output cannot replace the source result JSON")
            (write_html if format == ReportFormat.HTML else write_markdown)(destination, result)
            console.print(f"Saved {destination}", markup=False)
    except ConfigurationError as exc:
        error_console.print(str(exc), markup=False)
        raise typer.Exit(exc.exit_code) from exc
    except OSError as exc:
        error_console.print("Cannot write the report; source JSON retained.")
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR) from exc
    raise typer.Exit(result.exit_code)


@app.command()
def clean(
    run_id: Annotated[str, typer.Option("--run-id", help="Exactly one inactive owned run.")],
    state_dir: Annotated[Path, typer.Option()] = Path(".pg-rehearse/runs"),
) -> None:
    """Recover selected owned resources; retain input and report files."""
    try:
        result = clean_run(run_id, state_dir)
    except ConfigurationError as exc:
        error_console.print(str(exc), markup=False)
        raise typer.Exit(exc.exit_code) from exc
    except RuntimeLifecycleError as exc:
        _show_runtime_error(exc)
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR) from exc
    console.print(f"Run {result.run_id}: cleanup {result.cleanup.value}", markup=False)
    if result.cleanup != CleanupStatus.COMPLETE:
        for issue in result.cleanup_errors:
            error_console.print(issue, markup=False)
        raise typer.Exit(ExitCode.INFRASTRUCTURE_ERROR)
