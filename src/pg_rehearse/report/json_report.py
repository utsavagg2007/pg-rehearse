"""Private, atomic report files from the final RunResult."""

import os
import tempfile
from pathlib import Path

from pg_rehearse.models import RunResult


def atomic_text(path: Path, content: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".report-", delete=False
        ) as stream:
            temporary = stream.name
            os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, result: RunResult) -> None:
    atomic_text(path, result.model_dump_json(indent=2) + "\n")
