from pathlib import Path

import pytest
from docker import DockerClient
from docker.errors import NotFound

from pg_rehearse.errors import UnsupportedInputError
from pg_rehearse.evaluation.cases import CASES, EvaluationCase, case_errors
from pg_rehearse.orchestrator import run_rehearsal
from pg_rehearse.report.json_report import read_report
from pg_rehearse.runtime.manifest import ManifestStore

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_real_labeled_case(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path, case: EvaluationCase
) -> None:
    state = tmp_path / "runs"
    if case.label == "unsupported":
        with pytest.raises(UnsupportedInputError) as caught:
            run_rehearsal(rehearsal_project / case.config, state_dir=state)
        assert not state.exists()
        assert not case_errors(case, None, caught.value.exit_code)
        return
    result, directory = run_rehearsal(rehearsal_project / case.config, state_dir=state)
    assert not case_errors(case, result, result.exit_code)
    assert read_report(directory / "report.json") == result
    assert all((directory / name).is_file() for name in ("report.md", "report.html"))
    manifest = ManifestStore(directory / "manifest.json").load()
    for resource in manifest.resources:
        collection = (
            docker_client.networks if resource.kind == "network" else docker_client.containers
        )
        with pytest.raises(NotFound):
            collection.get(resource.resource_id or resource.name)
