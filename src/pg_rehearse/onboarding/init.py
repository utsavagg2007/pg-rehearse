"""A small packaged orders starter, created exclusively in a new directory."""

from importlib.resources import files
from pathlib import Path

from pg_rehearse.config import load_config
from pg_rehearse.errors import ConfigurationError

STARTER_FILES = (
    "rehearsal.yml",
    "control.yml",
    "schema/base.sql",
    "fixtures/orders.yml",
    "contracts/deployed-v1.yml",
    "contracts/candidate-v2.yml",
    "migrations/rename_user_name.sql",
    "migrations/create_order_user_index.sql",
    "README.md",
)


def initialize(directory: Path) -> Path:
    directory = directory.absolute()
    try:
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        raise ConfigurationError(
            "Destination already exists; choose a new directory. Existing files were not changed."
        ) from exc
    except OSError as exc:
        raise ConfigurationError("Cannot create the starter directory") from exc
    try:
        source = files("pg_rehearse.onboarding").joinpath("examples/orders")
        for name in STARTER_FILES:
            destination = directory / name
            destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(source.joinpath(name).read_bytes())
            destination.chmod(0o600)
        load_config(directory / "rehearsal.yml")
        load_config(directory / "control.yml")
    except (OSError, ConfigurationError) as exc:
        # Keep partial output for inspection; never recursively remove concurrently added files.
        raise ConfigurationError(
            f"Starter creation failed; partial files remain at {directory}"
        ) from exc
    return directory
