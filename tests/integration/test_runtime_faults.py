from pathlib import Path
from typing import Any

import pytest
from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import ContainerCollection

from pg_rehearse.errors import ManifestError, RuntimeLifecycleError
from pg_rehearse.models import CleanupStatus
from pg_rehearse.runtime.docker import DockerRuntime
from pg_rehearse.runtime.manifest import ManifestStore, RunManifest

pytestmark = pytest.mark.integration


def test_lost_create_response_is_cleaned_by_intent(
    docker_client: DockerClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create = ContainerCollection.create

    def ambiguous_create(self: ContainerCollection, *args: Any, **kwargs: Any) -> None:
        create(self, *args, **kwargs)
        raise APIError("Response lost after Docker created the container")

    monkeypatch.setattr(ContainerCollection, "create", ambiguous_create)
    with pytest.raises(RuntimeLifecycleError):
        with DockerRuntime(state_dir=tmp_path, client=docker_client).provision():
            pytest.fail("An ambiguous allocation must not return an environment")
    manifest = ManifestStore(next(tmp_path.glob("*/manifest.json"))).load()
    assert manifest.cleanup == CleanupStatus.COMPLETE
    for record in manifest.resources:
        collection = (
            docker_client.containers if record.kind == "container" else docker_client.networks
        )
        with pytest.raises(NotFound):
            collection.get(record.resource_id or record.name)


def test_manifest_write_failure_after_allocation_still_cleans(
    docker_client: DockerClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save = ManifestStore.save

    def disk_failure(self: ManifestStore, manifest: RunManifest) -> None:
        if manifest.state == "provisioning" and any(
            record.kind == "container" and record.resource_id for record in manifest.resources
        ):
            raise ManifestError("Injected disk failure after container allocation")
        save(self, manifest)

    monkeypatch.setattr(ManifestStore, "save", disk_failure)
    with pytest.raises(ManifestError):
        with DockerRuntime(state_dir=tmp_path, client=docker_client).provision():
            pytest.fail("An unrecorded allocation must not return an environment")
    manifest = ManifestStore(next(tmp_path.glob("*/manifest.json"))).load()
    assert manifest.cleanup == CleanupStatus.COMPLETE
    assert manifest.failure == "ManifestError"
    assert all(record.removed for record in manifest.resources)
