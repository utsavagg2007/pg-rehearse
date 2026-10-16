"""Atomic, credential-free allocation intents and run ownership records."""

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import Field, model_validator

from pg_rehearse.errors import ManifestError
from pg_rehearse.models import CleanupStatus, StrictModel

MANAGED_LABEL = "io.pg-rehearse.managed"
RUN_LABEL = "io.pg-rehearse.run-id"
OWNER_LABEL = "io.pg-rehearse.owner"
KIND_LABEL = "io.pg-rehearse.kind"
ResourceKind = Literal["container", "worker", "network"]


WorkerSlot = Literal[
    "seed", "baseline_probe", "post_deployed", "post_candidate", "rollout", "rollback"
]


def resource_name(run_id: str, kind: ResourceKind, slot: WorkerSlot | None = None) -> str:
    suffix = f"-{slot}" if slot else ""
    return f"pgr-{run_id}-{'postgres' if kind == 'container' else kind}{suffix}"


class ResourceRecord(StrictModel):
    kind: ResourceKind
    name: str
    resource_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    removed: bool = False
    slot: WorkerSlot | None = None


class RunManifest(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    ownership_token: str = Field(pattern=r"^[a-f0-9]{32}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    coordinator_pid: int = Field(default_factory=os.getpid)
    image_requested: str
    image_id: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    image_digest: str | None = None
    worker_image_id: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    architecture: str | None = None
    operating_system: str | None = None
    state: Literal["provisioning", "ready", "cleaning", "cleaned", "cleanup_failed"] = (
        "provisioning"
    )
    cleanup: CleanupStatus = CleanupStatus.PENDING
    failure: str | None = None
    cleanup_errors: list[str] = Field(default_factory=list)
    resources: list[ResourceRecord] = Field(default_factory=list)

    def labels(self, kind: ResourceKind) -> dict[str, str]:
        return {
            MANAGED_LABEL: "true",
            RUN_LABEL: self.run_id,
            OWNER_LABEL: self.ownership_token,
            KIND_LABEL: kind,
        }

    @model_validator(mode="after")
    def validate_resources(self) -> Self:
        kinds = [(resource.kind, resource.slot) for resource in self.resources]
        if len(kinds) != len(set(kinds)):
            raise ValueError("Only one resource of each kind and worker slot is allowed")
        for resource in self.resources:
            if resource.slot is not None and resource.kind != "worker":
                raise ValueError("Only workers have experiment slots")
            if resource.name != resource_name(self.run_id, resource.kind, resource.slot):
                raise ValueError("Resource name does not match its run and kind")
        return self


class ManifestStore:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()

    @classmethod
    def create(cls, state_dir: Path, image: str) -> tuple["ManifestStore", RunManifest]:
        run_id = uuid4().hex
        directory = state_dir / run_id
        try:
            directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        except OSError as exc:
            raise ManifestError("Cannot create the run directory") from exc
        manifest = RunManifest(run_id=run_id, ownership_token=uuid4().hex, image_requested=image)
        return cls(directory / "manifest.json"), manifest

    @contextmanager
    def lock(self) -> Iterator[None]:
        """The OS releases this advisory lock even after SIGKILL. Linux/macOS only."""
        try:
            import fcntl
        except ImportError as exc:
            raise ManifestError("The disposable runtime currently requires Linux or macOS") from exc
        descriptor = None
        try:
            descriptor = os.open(
                self.path.parent / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise ManifestError("Run is active, locked, or its directory is inaccessible") from exc
        try:
            yield
        finally:
            os.close(descriptor)

    def load(self) -> RunManifest:
        try:
            manifest = RunManifest.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ManifestError(
                "Invalid or unreadable manifest; no resources were removed"
            ) from exc
        if self.path.name != "manifest.json" or self.path.parent.name != manifest.run_id:
            raise ManifestError("Manifest path does not match its run ID")
        return manifest

    def save(self, manifest: RunManifest) -> None:
        """Replace a complete JSON record and fsync both file and parent directory."""
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, prefix=".manifest-", delete=False
            ) as stream:
                temporary = stream.name
                os.chmod(temporary, 0o600)
                stream.write(manifest.model_dump_json(indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise ManifestError("Cannot persist run manifest") from exc
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass  # Never let a leftover temporary file prevent Docker teardown.
