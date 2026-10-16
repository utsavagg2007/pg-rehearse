"""Run the bundled rename example against the real disposable pipeline."""

from pathlib import Path
from tempfile import TemporaryDirectory

from pg_rehearse.models import RunResult
from pg_rehearse.onboarding.init import initialize
from pg_rehearse.orchestrator import run_rehearsal


def run_demo(state_dir: Path) -> tuple[RunResult, Path]:
    with TemporaryDirectory(prefix="pg-rehearse-demo-") as temporary:
        project = initialize(Path(temporary) / "orders")
        return run_rehearsal(project / "rehearsal.yml", state_dir=state_dir)
