"""Select exactly one run; ownership validation remains in the host runtime."""

import re
from pathlib import Path

from pg_rehearse.errors import ConfigurationError
from pg_rehearse.runtime.cleanup import recover_run
from pg_rehearse.runtime.manifest import RunManifest


def clean_run(run_id: str, state_dir: Path) -> RunManifest:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ConfigurationError("run-id must be exactly 32 lowercase hexadecimal characters")
    try:
        directory = state_dir.resolve(strict=True) / run_id
        manifest = directory / "manifest.json"
        if directory.is_symlink() or manifest.is_symlink() or not manifest.is_file():
            raise ConfigurationError("Selected run must have a real run directory and manifest")
    except OSError as exc:
        raise ConfigurationError("Cannot locate the selected run") from exc
    return recover_run(manifest)
