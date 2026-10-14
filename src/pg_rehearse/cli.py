"""Thin CLI for the implemented foundation and explicit future run boundary."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from pg_rehearse import __version__
from pg_rehearse.config import load_config
from pg_rehearse.doctor import check_environment
from pg_rehearse.errors import ConfigurationError, ExitCode

app = typer.Typer(no_args_is_help=True, help="Rehearse PostgreSQL migrations. Foundation stage.")
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
    """Validate YAML, paths and query contracts. Does not execute or preflight SQL."""
    try:
        loaded = load_config(config)
    except ConfigurationError as exc:
        error_console.print(f"Invalid configuration: {exc}", markup=False)
        raise typer.Exit(ExitCode.INVALID_INPUT) from exc
    console.print(f"Configuration valid: {loaded.spec.name}", markup=False)
    console.print(f"Migration steps: {len(loaded.migration_paths)}")
    console.print(f"Deployed operations: {len(loaded.deployed_contract.operations)}")
    if loaded.candidate_contract:
        console.print(f"Candidate operations: {len(loaded.candidate_contract.operations)}")
    console.print("SQL support and database behavior remain unverified at this foundation stage.")


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to the rehearsal YAML file."),
    ] = Path("examples/orders/rehearsal.yml"),
) -> None:
    """Reserved for the database pipeline. Currently returns an inconclusive exit code."""
    try:
        load_config(config)
    except ConfigurationError as exc:
        error_console.print(f"Invalid configuration: {exc}", markup=False)
        raise typer.Exit(ExitCode.INVALID_INPUT) from exc
    error_console.print(
        "Database rehearsal is not implemented yet. Follow features 1–7 in IMPLEMENTATION_ORDER.md."
    )
    raise typer.Exit(ExitCode.INCONCLUSIVE)
