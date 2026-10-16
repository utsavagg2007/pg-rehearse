import json
from pathlib import Path
from uuid import uuid4

import pytest
from docker import DockerClient
from typer.testing import CliRunner

from pg_rehearse.cli import app
from pg_rehearse.models import RunResult
from pg_rehearse.runtime.docker import DockerRuntime

pytestmark = pytest.mark.integration
runner = CliRunner()


def test_initialized_control_and_real_demo_keep_reports_after_clean(
    docker_client: DockerClient, tmp_path: Path
) -> None:
    project = tmp_path / "starter"
    assert runner.invoke(app, ["init", str(project)]).exit_code == 0
    config = project / "control.yml"
    assert runner.invoke(app, ["validate", "--config", str(config)]).exit_code == 0
    for name, command, code in (
        ("control", ["run", "--config", str(config)], 0),
        ("demo", ["demo"], 1),
    ):
        state = tmp_path / name
        response = runner.invoke(app, [*command, "--state-dir", str(state)])
        assert response.exit_code == code, response.output
        (report,) = state.glob("*/report.json")
        saved = report.read_bytes()
        result = RunResult.model_validate_json(saved)
        assert result.exit_code == code and result.cleanup.value == "complete"
        assert not result.coverage.missing and result.completion.value == "complete"
        if code:
            assert any(
                o.phase == "post_deployed" and o.sqlstate == "42703" for o in result.operations
            )
            assert any(
                o.phase == "post_candidate"
                and o.success
                and any(a.actual == [[7, "Ada"]] for a in o.assertions)
                for o in result.operations
            )
        assert result.run_id in report.with_suffix(".html").read_text()
        assert "cleanup: complete" in report.with_suffix(".md").read_text()
        rendered = tmp_path / f"{name}.html"
        viewed = runner.invoke(
            app, ["report", str(report), "--format", "html", "--output", str(rendered)]
        )
        assert (
            viewed.exit_code == code
            and rendered.read_bytes() == report.with_suffix(".html").read_bytes()
        )
        for _ in range(2):
            cleaned = runner.invoke(
                app, ["clean", "--run-id", result.run_id, "--state-dir", str(state)]
            )
            assert cleaned.exit_code == 0, cleaned.output
        assert report.read_bytes() == saved
        manifest = json.loads((report.parent / "manifest.json").read_text())
        assert manifest["cleanup"] == "complete"


def test_clean_refuses_active_run_and_leaves_unrelated_network(
    docker_client: DockerClient, tmp_path: Path
) -> None:
    foreign = docker_client.networks.create(f"pg-rehearse-test-unrelated-{uuid4().hex}")
    try:
        with DockerRuntime(state_dir=tmp_path, client=docker_client).provision() as environment:
            args = ["clean", "--run-id", environment.run_id, "--state-dir", str(tmp_path)]
            refused = runner.invoke(app, args)
            assert refused.exit_code == 3 and "active" in refused.output
            assert docker_client.containers.get(environment.container_id).status == "running"
            assert docker_client.networks.get(foreign.id).id == foreign.id
        assert runner.invoke(app, args).exit_code == 0
        assert docker_client.networks.get(foreign.id).id == foreign.id
    finally:
        foreign.remove()
