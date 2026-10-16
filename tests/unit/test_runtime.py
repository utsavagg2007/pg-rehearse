from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docker import DockerClient
from docker.models.containers import Container

from pg_rehearse.errors import ManifestError, ReadinessTimeout, RunInterrupted
from pg_rehearse.models import CleanupStatus
from pg_rehearse.runtime.cleanup import cleanup_resources
from pg_rehearse.runtime.docker import DockerRuntime, RuntimeOptions
from pg_rehearse.runtime.manifest import ManifestStore, ResourceRecord, resource_name


def test_cleanup_continues_if_manifest_writes_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, manifest = ManifestStore.create(tmp_path, "postgres:17")
    manifest.resources = [
        ResourceRecord(
            kind="container", name=resource_name(manifest.run_id, "container"), resource_id="a" * 64
        )
    ]
    container = MagicMock(spec=Container)
    container.id = "a" * 64
    container.attrs = {"Config": {"Labels": manifest.labels("container")}}
    client = MagicMock(spec=DockerClient)
    client.api = MagicMock()
    client.containers.get.return_value = container

    def unwritable(*args: object) -> None:
        raise ManifestError("write failed")

    monkeypatch.setattr(store, "save", unwritable)
    assert cleanup_resources(client, store, manifest) == CleanupStatus.FAILED
    container.remove.assert_called_once_with(force=True, v=False)
    assert "manifest_write_failed" in manifest.cleanup_errors


def test_lifecycle_api_output_cannot_store_passwords(tmp_path: Path) -> None:
    client = MagicMock(spec=DockerClient)
    client.api = MagicMock()
    client.images.get.side_effect = OSError("sensitive-request-payload")
    runtime = DockerRuntime(state_dir=tmp_path, client=client)
    with pytest.raises(Exception, match="Docker operation failed"):
        with runtime.provision():
            pytest.fail("An unavailable image must not produce an environment")
    content = next(tmp_path.glob("*/manifest.json")).read_text()
    assert "sensitive-request-payload" not in content
    assert "OSError" in content


def test_readiness_has_a_deadline(tmp_path: Path) -> None:
    client = MagicMock(spec=DockerClient)
    client.api = MagicMock()
    container = MagicMock(spec=Container)
    container.attrs = {"State": {"Status": "running", "Health": {"Status": "starting"}}}
    runtime = DockerRuntime(state_dir=tmp_path, options=RuntimeOptions(startup_seconds=0.01))
    with pytest.raises(ReadinessTimeout):
        runtime._wait_ready(client, container)


@pytest.mark.parametrize("outcome", ["complete", "failed", "error"])
def test_first_cleanup_interrupt_retries_within_budget_and_preserves_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    client = MagicMock(spec=DockerClient)
    client.api = MagicMock()
    image = client.images.get.return_value
    image.id = "sha256:" + "a" * 64
    image.attrs = {"RepoDigests": ["postgres@sha256:" + "b" * 64]}
    client.networks.create.return_value.id = "c" * 64
    client.containers.create.return_value.id = "d" * 64
    runtime = DockerRuntime(state_dir=tmp_path, client=client)
    monkeypatch.setattr(runtime, "_wait_ready", lambda *args: None)
    interruption = RunInterrupted(15)
    budgets = []

    def interrupted_cleanup(client, store, manifest, *, timeout_seconds):
        budgets.append(timeout_seconds)
        if len(budgets) == 1:
            raise interruption
        if outcome == "error":
            raise ManifestError("Cleanup retry failed")
        manifest.cleanup = CleanupStatus(outcome)
        manifest.state = "cleaned" if outcome == "complete" else "cleanup_failed"
        manifest.cleanup_errors = [] if outcome == "complete" else ["container:docker_api_error"]
        store.save(manifest)
        return manifest.cleanup

    monkeypatch.setattr("pg_rehearse.runtime.docker.cleanup_resources", interrupted_cleanup)
    with pytest.raises(RunInterrupted) as error:
        with runtime.provision():
            pass
    assert error.value is interruption
    assert len(budgets) == 2 and 0 <= budgets[1] <= budgets[0] == 30
    if outcome == "complete":
        assert ManifestStore(runtime.manifest_path).load().cleanup == CleanupStatus.COMPLETE
    else:
        assert any("recover using" in note for note in interruption.__notes__)
        if outcome == "failed":
            assert ManifestStore(runtime.manifest_path).load().cleanup_errors == [
                "container:docker_api_error"
            ]
