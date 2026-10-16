import os
import signal
from pathlib import Path
from typing import Any

import pytest
from docker import DockerClient
from docker.errors import NotFound
from docker.models.containers import Container
from typer.testing import CliRunner

from pg_rehearse.cli import app
from pg_rehearse.report.json_report import read_report
from pg_rehearse.runtime.manifest import ManifestStore

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_during_rehearsal_cleanup_preserves_reports_and_exit(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signum: int,
) -> None:
    original = Container.remove
    sent = False

    def interrupt_once(self: Container, *args: Any, **kwargs: Any) -> Any:
        nonlocal sent
        if self.name.endswith("-post_deployed") and not sent:
            sent = True
            os.kill(os.getpid(), signum)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Container, "remove", interrupt_once)
    response = CliRunner().invoke(
        app,
        [
            "run",
            "--config",
            str(rehearsal_project / "control.yml"),
            "--state-dir",
            str(tmp_path / "runs"),
        ],
    )
    assert sent and response.exit_code == 128 + signum, response.output
    (report,) = (tmp_path / "runs").glob("*/report.json")
    result = read_report(report)
    assert result.operations and result.completion.value == "infrastructure_error"
    assert result.verdict.value == "inconclusive" and result.cleanup.value == "complete"
    assert report.with_suffix(".html").is_file() and report.with_suffix(".md").is_file()
    for record in ManifestStore(report.parent / "manifest.json").load().resources:
        collection = (
            docker_client.networks if record.kind == "network" else docker_client.containers
        )
        with pytest.raises(NotFound):
            collection.get(record.resource_id or record.name)
