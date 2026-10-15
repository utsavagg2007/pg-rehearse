"""Owned PostgreSQL 17 runtime with private networking and guaranteed teardown."""

import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import docker
from docker import DockerClient
from docker.errors import DockerException, ImageNotFound
from docker.models.containers import Container
from docker.types import LogConfig
from pydantic import Field
from requests.exceptions import RequestException

from pg_rehearse.errors import CleanupError, ReadinessTimeout, RuntimeLifecycleError
from pg_rehearse.models import POSTGRES_IMAGE_PATTERN, CleanupStatus, StrictModel
from pg_rehearse.runtime.cleanup import cleanup_resources
from pg_rehearse.runtime.manifest import ManifestStore, ResourceRecord, resource_name


class RuntimeOptions(StrictModel):
    image: str = Field(
        default="postgres:17",
        pattern=POSTGRES_IMAGE_PATTERN,
    )
    startup_seconds: float = Field(default=60, gt=0, le=600)
    cleanup_seconds: float = Field(default=30, gt=0, le=120)


@dataclass(frozen=True)
class RunEnvironment:
    run_id: str
    manifest_path: Path
    container_id: str
    network_id: str
    image_id: str
    image_digest: str
    database_host: str
    database_port: int = 5432


class DockerRuntime:
    def __init__(
        self,
        *,
        state_dir: Path = Path(".pg-rehearse/runs"),
        options: RuntimeOptions | None = None,
        client: DockerClient | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.options = options or RuntimeOptions()
        self._client = client

    def _wait_ready(self, client: DockerClient, container: Container) -> None:
        deadline = time.monotonic() + self.options.startup_seconds
        previous_timeout = client.api.timeout
        try:
            while (remaining := deadline - time.monotonic()) > 0:
                # Requests supports fractions, unlike Docker's int-only type stub.
                cast(Any, client.api).timeout = min(5.0, remaining)
                container.reload()
                state = container.attrs.get("State", {})
                if state.get("Status") in ("exited", "dead", "removing"):
                    raise RuntimeLifecycleError("PostgreSQL exited before becoming ready")
                if state.get("Health", {}).get("Status") == "healthy":
                    return
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))
            raise ReadinessTimeout("PostgreSQL readiness deadline exceeded")
        except RequestException as exc:
            if time.monotonic() >= deadline:
                raise ReadinessTimeout("PostgreSQL readiness deadline exceeded") from exc
            raise
        finally:
            client.api.timeout = previous_timeout

    @contextmanager
    def provision(self) -> Iterator[RunEnvironment]:
        store, manifest = ManifestStore.create(self.state_dir, self.options.image)
        client = self._client
        failure: BaseException | None = None
        with store.lock():
            store.save(manifest)
            try:
                if client is None:
                    client = docker.from_env(timeout=5)
                try:
                    image = client.images.get(self.options.image)
                except ImageNotFound as exc:
                    raise RuntimeLifecycleError(
                        f"Image is not installed. Run docker pull {self.options.image} first."
                    ) from exc
                digest = next(
                    (
                        value
                        for value in image.attrs.get("RepoDigests", [])
                        if value.startswith(
                            ("postgres@sha256:", "docker.io/library/postgres@sha256:")
                        )
                    ),
                    None,
                )
                if not digest:
                    raise RuntimeLifecycleError(
                        "The PostgreSQL image has no official repository digest"
                    )
                image_id = image.id
                if not image_id:
                    raise RuntimeLifecycleError("Docker did not return the image content ID")
                manifest.image_id = image_id
                manifest.image_digest = digest
                manifest.architecture = image.attrs.get("Architecture")
                manifest.operating_system = image.attrs.get("Os")

                network_record = ResourceRecord(
                    kind="network", name=resource_name(manifest.run_id, "network")
                )
                manifest.resources.append(network_record)
                store.save(manifest)
                network = client.networks.create(
                    network_record.name,
                    driver="bridge",
                    internal=True,
                    labels=manifest.labels("network"),
                )
                network_record.resource_id = network.id
                store.save(manifest)

                container_record = ResourceRecord(
                    kind="container", name=resource_name(manifest.run_id, "container")
                )
                manifest.resources.append(container_record)
                store.save(manifest)
                # Pin creation to the resolved content ID, even if a floating tag changes.
                # The ephemeral password is never written to the manifest.
                container = client.containers.create(
                    image_id,
                    name=container_record.name,
                    hostname="postgres",
                    network=network.id,
                    labels=manifest.labels("container"),
                    environment={
                        "POSTGRES_USER": "rehearse_admin",
                        "POSTGRES_DB": "rehearsal",
                        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
                        "POSTGRES_INITDB_ARGS": "--auth-host=scram-sha-256",
                    },
                    tmpfs={"/var/lib/postgresql/data": "rw,noexec,nosuid,size=268435456"},
                    mem_limit="512m",
                    nano_cpus=1_000_000_000,
                    pids_limit=128,
                    security_opt=["no-new-privileges:true"],
                    log_config=LogConfig(
                        type="json-file", config={"max-size": "1m", "max-file": "1"}
                    ),
                    healthcheck={
                        "test": [
                            "CMD",
                            "pg_isready",
                            "-h",
                            "127.0.0.1",
                            "-U",
                            "rehearse_admin",
                            "-d",
                            "rehearsal",
                            "-t",
                            "1",
                        ],
                        "interval": 1_000_000_000,
                        "timeout": 2_000_000_000,
                        "retries": 600,
                    },
                )
                container_record.resource_id = container.id
                store.save(manifest)
                container.start()
                self._wait_ready(client, container)
                manifest.state = "ready"
                store.save(manifest)
                container_id, network_id = container.id, network.id
                if not container_id or not network_id:
                    raise RuntimeLifecycleError("Docker did not return allocated resource IDs")
                yield RunEnvironment(
                    manifest.run_id,
                    store.path,
                    container_id,
                    network_id,
                    image_id,
                    digest,
                    container_record.name,
                )
            except BaseException as exc:
                failure = exc
                exc.add_note(f"Run manifest: {store.path}")
                # Class names only: never persist request bodies, logs, or callback text.
                manifest.failure = type(exc).__name__
                if isinstance(exc, (DockerException, RequestException, OSError)):
                    raise RuntimeLifecycleError(
                        f"Docker operation failed; inspect the daemon. Manifest: {store.path}"
                    ) from exc
                raise
            finally:
                try:
                    status = cleanup_resources(
                        client, store, manifest, timeout_seconds=self.options.cleanup_seconds
                    )
                    if status == CleanupStatus.FAILED:
                        message = f"Cleanup incomplete; recover using {store.path}"
                        if failure is not None:
                            failure.add_note(message)
                        else:
                            raise CleanupError(message)
                except BaseException as cleanup_failure:
                    if failure is None:
                        raise
                    failure.add_note(f"Cleanup could not finish; recover using {store.path}")
                    if isinstance(cleanup_failure, (KeyboardInterrupt, SystemExit)):
                        raise
                finally:
                    if client is not None and self._client is None:
                        client.close()
