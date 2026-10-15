import json
from pathlib import Path

import pytest

from pg_rehearse.errors import ManifestError
from pg_rehearse.runtime.manifest import ManifestStore, ResourceRecord, resource_name


def test_manifest_roundtrip_is_private_and_contains_no_credentials(tmp_path: Path) -> None:
    store, manifest = ManifestStore.create(tmp_path, "postgres:17")
    with store.lock():
        store.save(manifest)
        assert store.load() == manifest
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert "password" not in store.path.read_text().lower()


def test_active_run_cannot_be_recovered_concurrently(tmp_path: Path) -> None:
    store, manifest = ManifestStore.create(tmp_path, "postgres:17")
    store.save(manifest)
    with store.lock(), pytest.raises(ManifestError, match="active"):
        with ManifestStore(store.path).lock():
            pytest.fail("A second coordinator obtained the run lock")


def test_manifest_rejects_forged_resource_names(tmp_path: Path) -> None:
    store, manifest = ManifestStore.create(tmp_path, "postgres:17")
    manifest.resources.append(ResourceRecord(kind="container", name="unrelated-postgres"))
    store.save(manifest)
    with pytest.raises(ManifestError, match="Invalid"):
        store.load()


def test_manifest_rejects_mismatched_run_directory(tmp_path: Path) -> None:
    store, manifest = ManifestStore.create(tmp_path, "postgres:17")
    data = manifest.model_dump(mode="json")
    data["run_id"] = "a" * 32
    store.path.write_text(json.dumps(data))
    with pytest.raises(ManifestError, match="path"):
        store.load()


def test_manifest_rejects_duplicate_resource_kinds(tmp_path: Path) -> None:
    store, manifest = ManifestStore.create(tmp_path, "postgres:17")
    record = ResourceRecord(kind="network", name=resource_name(manifest.run_id, "network"))
    manifest.resources = [record, record]
    store.save(manifest)
    with pytest.raises(ManifestError, match="Invalid"):
        store.load()
