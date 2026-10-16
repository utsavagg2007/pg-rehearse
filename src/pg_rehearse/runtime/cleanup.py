"""Remove only individually verified run resources; never scan or prune globally."""

import time
from pathlib import Path
from typing import Any, cast

import docker
from docker import DockerClient
from docker.errors import DockerException, NotFound
from docker.models.containers import Container
from requests.exceptions import RequestException

from pg_rehearse.errors import ManifestError, RuntimeLifecycleError
from pg_rehearse.models import CleanupStatus
from pg_rehearse.runtime.manifest import ManifestStore, RunManifest


def cleanup_resources(
    client: DockerClient | None,
    store: ManifestStore,
    manifest: RunManifest,
    *,
    timeout_seconds: float = 30,
) -> CleanupStatus:
    """Caller holds the manifest lock. Continue teardown even if persistence fails."""
    deadline = time.monotonic() + timeout_seconds
    errors: list[str] = []
    previous_timeout = client.api.timeout if client is not None else None

    def persist() -> None:
        try:
            store.save(manifest)
        except ManifestError:
            if "manifest_write_failed" not in errors:
                errors.append("manifest_write_failed")

    manifest.state = "cleaning"
    persist()
    try:
        for resource in sorted(
            manifest.resources,
            key=lambda item: {"worker": 0, "container": 1, "network": 2}[item.kind],
        ):
            if resource.removed:
                continue
            remaining = deadline - time.monotonic()
            if client is None or remaining <= 0:
                errors.append(f"{resource.kind}:cleanup_deadline_or_daemon_unavailable")
                continue
            # Requests accepts fractional timeouts; Docker's stubs annotate only int.
            cast(Any, client.api).timeout = min(5.0, remaining)
            try:
                is_container = resource.kind in {"container", "worker"}
                collection = client.containers if is_container else client.networks
                # The intent covers a crash between create() and saving the ID.
                target = collection.get(resource.resource_id or resource.name)
                if resource.resource_id and target.id != resource.resource_id:
                    errors.append(f"{resource.kind}:id_mismatch")
                    continue
                labels = (
                    target.attrs.get("Config", {}).get("Labels", {})
                    if is_container
                    else target.attrs.get("Labels", {})
                ) or {}
                if any(
                    labels.get(key) != value
                    for key, value in manifest.labels(resource.kind).items()
                ):
                    errors.append(f"{resource.kind}:ownership_mismatch")
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    errors.append(f"{resource.kind}:cleanup_deadline_exceeded")
                    continue
                cast(Any, client.api).timeout = min(5.0, remaining)
                if is_container:
                    # Data is in tmpfs; never delete attached volumes.
                    cast(Container, target).remove(force=True, v=False)
                else:
                    # Do not disconnect foreign endpoints or force network removal.
                    target.remove()
                resource.removed = True
                persist()
            except NotFound:
                resource.removed = True
                persist()
            except (DockerException, RequestException, OSError):
                errors.append(f"{resource.kind}:docker_api_error")
    finally:
        if client is not None and previous_timeout is not None:
            client.api.timeout = previous_timeout
    manifest.cleanup_errors = errors
    manifest.cleanup = CleanupStatus.FAILED if errors else CleanupStatus.COMPLETE
    manifest.state = "cleanup_failed" if errors else "cleaned"
    persist()
    if errors:
        manifest.cleanup = CleanupStatus.FAILED
        manifest.state = "cleanup_failed"
        manifest.cleanup_errors = errors
    return manifest.cleanup


def recover_run(path: Path) -> RunManifest:
    """Recover one explicitly selected, inactive run using manifest IDs and labels."""
    store = ManifestStore(path)
    with store.lock():
        manifest = store.load()
        client = None
        try:
            if any(not resource.removed for resource in manifest.resources):
                client = docker.from_env(timeout=5)
            cleanup_resources(client, store, manifest)
        except (DockerException, RequestException, OSError) as exc:
            raise RuntimeLifecycleError("Docker is unavailable; the manifest was retained") from exc
        finally:
            if client is not None:
                client.close()
        return manifest
