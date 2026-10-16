"""Private, atomic report files from the final RunResult."""

import os
import stat
import tempfile
from pathlib import Path

from pg_rehearse.errors import ConfigurationError
from pg_rehearse.models import RunResult

MAX_REPORT_BYTES = 64 * 1_048_576


def read_report(path: Path) -> RunResult:
    """Validate saved JSON without Docker, unbounded reads or special-file blocking."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Not a regular file")
            payload = stream.read(MAX_REPORT_BYTES + 1)
        if len(payload) > MAX_REPORT_BYTES:
            raise ValueError("Report too large")
        return RunResult.model_validate_json(payload)
    except (OSError, ValueError, RecursionError) as exc:
        raise ConfigurationError(
            "Invalid or unreadable result JSON (regular file, at most 64 MiB)"
        ) from exc


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
