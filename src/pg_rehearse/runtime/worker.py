"""Host-only trusted bootstrap and bounded supervision of an owned worker container."""

import os
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal, cast

from docker import DockerClient
from docker.errors import DockerException, ImageNotFound
from docker.types import LogConfig
from pydantic import SecretStr
from requests.exceptions import RequestException

from pg_rehearse.errors import WorkerDeadline, WorkerError
from pg_rehearse.models import Timeouts
from pg_rehearse.runtime.manifest import ManifestStore, ResourceRecord, RunManifest, resource_name
from pg_rehearse.runtime.roles import Role, bootstrap_sql, new_credentials
from pg_rehearse.worker_protocol import (
    MAX_RESPONSE_BYTES,
    WORKER_IMAGE,
    BenchmarkArm,
    RehearsalEvidence,
    WorkerEvidence,
    WorkerFailure,
    WorkerInputs,
    WorkerRequest,
    WorkerTask,
    experiment_id,
    experiment_tasks,
    task_database,
)

if TYPE_CHECKING:
    from pg_rehearse.runtime.docker import RunEnvironment


@contextmanager
def attached_socket(stream: Any) -> Iterator[socket.socket]:
    """Close the HTTP response before its SocketIO to avoid Python 3.14 finalizer errors."""
    try:
        yield cast(socket.socket, getattr(stream, "_sock", stream))
    finally:
        response = getattr(stream, "_response", None)
        if response is not None:
            response.close()
        else:
            stream.close()


def bootstrap_roles(
    client: DockerClient,
    container_id: str,
    payload: str,
    *,
    database: Literal["rehearsal", "postgres"] = "rehearsal",
    timeout_seconds: float = 10,
) -> None:
    """Fixed trusted SQL over local psql stdin, never user SQL or credentials in argv."""
    deadline = time.monotonic() + timeout_seconds

    def budget() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WorkerError("Trusted role bootstrap deadline exceeded")
        cast(Any, client.api).timeout = min(5.0, remaining)
        return remaining

    budget()
    execution = client.api.exec_create(
        container_id,
        ["psql", "-X", "-q", "-U", "rehearse_admin", "-d", database, "-v", "ON_ERROR_STOP=1"],
        stdin=True,
    )
    budget()
    with attached_socket(client.api.exec_start(execution["Id"], socket=True)) as transport:
        transport.settimeout(budget())
        transport.sendall(payload.encode())
        transport.shutdown(socket.SHUT_WR)
        received = 0
        while True:
            transport.settimeout(budget())
            chunk = transport.recv(4096)
            if not chunk:
                break
            received += len(chunk)
            if received > 65_536 or time.monotonic() >= deadline:
                raise WorkerError("Trusted role bootstrap exceeded its output or time budget")
    budget()
    if client.api.exec_inspect(execution["Id"])["ExitCode"] != 0:
        raise WorkerError("Trusted role bootstrap failed")


def execute_worker(
    client: DockerClient,
    store: ManifestStore,
    manifest: RunManifest,
    environment: "RunEnvironment",
    inputs: WorkerInputs,
    timeouts: Timeouts,
    *,
    task: WorkerTask = "baseline",
    trial: int | None = None,
    arm: BenchmarkArm | None = None,
    credentials: dict[Role, SecretStr] | None = None,
    deadline_at: float | None = None,
) -> WorkerEvidence:
    """Caller holds the run lock and guarantees ownership-checked cleanup on every exit."""
    slot = None if task == "baseline" else experiment_id(task, trial, arm)
    if any(resource.kind == "worker" and resource.slot == slot for resource in manifest.resources):
        raise WorkerError("This run already allocated its worker")
    previous_timeout = client.api.timeout
    deadline = None
    try:
        cast(Any, client.api).timeout = 5
        try:
            image = client.images.get(manifest.worker_image_id or WORKER_IMAGE)
        except ImageNotFound:
            raise WorkerError(
                "Worker image is missing. Build docker/worker.Dockerfile as " + WORKER_IMAGE
            ) from None
        if not image.id:
            raise WorkerError("Docker did not return the worker image content ID")
        manifest.worker_image_id = image.id
        store.save(manifest)
        if credentials is None:
            credentials = new_credentials()
            bootstrap_roles(client, environment.container_id, bootstrap_sql(credentials, timeouts))
        request = WorkerRequest(
            run_id=environment.run_id,
            database_host=environment.database_host,
            credentials=credentials,
            inputs=inputs,
            timeouts=timeouts,
            task=task,
            database=task_database(environment.run_id, task, trial, arm),
            trial=trial,
            arm=arm,
        )
        deadline = min(
            time.monotonic() + timeouts.worker_seconds,
            deadline_at if deadline_at is not None else float("inf"),
        )

        def budget() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkerDeadline("Worker execution deadline exceeded")
            cast(Any, client.api).timeout = min(5.0, remaining)
            return remaining

        record = ResourceRecord(
            kind="worker", name=resource_name(manifest.run_id, "worker", slot), slot=slot
        )
        manifest.resources.append(record)
        store.save(manifest)
        budget()
        worker = client.containers.create(
            image.id,
            name=record.name,
            network=environment.network_id,
            labels=manifest.labels("worker"),
            stdin_open=True,
            user="10001:10001",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            tmpfs={"/tmp": "rw,noexec,nosuid,nodev,size=16777216,mode=1777"},
            mem_limit="256m",
            nano_cpus=1_000_000_000,
            pids_limit=64,
            use_config_proxy=False,
            log_config=LogConfig(type="json-file", config={"max-size": "16m", "max-file": "1"}),
        )
        record.resource_id = worker.id
        store.save(manifest)
        budget()
        with attached_socket(worker.attach_socket(params={"stdin": 1, "stream": 1})) as transport:
            budget()
            worker.start()
            transport.settimeout(budget())
            transport.sendall(request.to_wire())
        while True:
            budget()
            worker.reload()
            state = worker.attrs.get("State", {})
            if state.get("Status") == "exited":
                break
            if state.get("Status") in {"dead", "removing"}:
                raise WorkerError("Worker crashed before producing evidence")
            time.sleep(min(0.1, budget()))
        budget()
        # Streaming logs disable SDK socket deadlines; read the stopped, rotated log instead.
        output = worker.logs(stdout=True, stderr=False, stream=False)
        if len(output) > MAX_RESPONSE_BYTES:
            raise WorkerError("Worker output exceeded 8 MiB")
        budget()
        if any(secret.get_secret_value().encode() in output for secret in credentials.values()):
            raise WorkerError("Worker output contained credentials; response discarded")
        if state.get("ExitCode") != 0 or state.get("OOMKilled"):
            try:
                failure = WorkerFailure.model_validate_json(output)
                if failure.run_id != request.run_id:
                    raise ValueError("Mismatched failure receipt")
            except ValueError:
                raise WorkerError("Worker crashed or exited without valid evidence") from None
            if failure.error == "worker_deadline":
                raise WorkerDeadline("Worker execution deadline exceeded")
            raise WorkerError(
                f"Worker failed: {failure.error}; SQLSTATE {failure.sqlstate or 'unavailable'}"
            )
        try:
            evidence = WorkerEvidence.model_validate_json(output)
            evidence.verify(request)
        except ValueError:
            raise WorkerError("Worker returned missing, malformed or incomplete evidence") from None
        # Separate receipt; compatibility verdict and final cleanup remain separate concerns.
        receipt_name = (
            "worker-evidence.json"
            if task in {"baseline", "baseline_probe"}
            else f"{experiment_id(task, trial, arm)}-evidence.json"
        )
        path = store.path.parent / receipt_name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as receipt:
            receipt.write(evidence.model_dump_json(indent=2) + "\n")
        return evidence
    except (DockerException, RequestException, OSError):
        if deadline is not None and time.monotonic() >= deadline:
            raise WorkerDeadline("Worker execution deadline exceeded") from None
        raise WorkerError(
            "Worker infrastructure operation failed; sensitive details omitted"
        ) from None
    finally:
        client.api.timeout = previous_timeout


def rehearse(
    client: DockerClient,
    store: ManifestStore,
    manifest: RunManifest,
    environment: "RunEnvironment",
    inputs: WorkerInputs,
    timeouts: Timeouts,
    evidence: "RehearsalEvidence",
) -> None:
    """Seed once, seal, then run independent baseline and post-migration branches."""
    from pg_rehearse.config import load_worker_config
    from pg_rehearse.fixtures.clone import clone_sql, drop_clone_sql
    from pg_rehearse.fixtures.template import seal_template_sql, template_identity

    loaded = load_worker_config(inputs)
    deadline = time.monotonic() + timeouts.worker_seconds

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise WorkerDeadline("Rehearsal execution deadline exceeded")
        return min(10, value)

    credentials = new_credentials()
    bootstrap_roles(
        client,
        environment.container_id,
        bootstrap_sql(credentials, timeouts),
        timeout_seconds=remaining(),
    )
    evidence.seed = execute_worker(
        client,
        store,
        manifest,
        environment,
        inputs,
        timeouts,
        task="seed",
        credentials=credentials,
        deadline_at=deadline,
    )
    baseline = evidence.seed.baseline
    if baseline is None or not baseline.success:
        return
    identity = template_identity(loaded, environment.image_id)
    statement, template = seal_template_sql(
        manifest.run_id,
        manifest.ownership_token,
        identity,
        baseline,
    )
    bootstrap_roles(
        client,
        environment.container_id,
        statement,
        database="postgres",
        timeout_seconds=remaining(),
    )
    evidence.template = template
    for task, trial, arm in experiment_tasks(loaded):
        bootstrap_roles(
            client,
            environment.container_id,
            clone_sql(
                manifest.run_id, manifest.ownership_token, template, identity, task, trial, arm
            ),
            database="postgres",
            timeout_seconds=remaining(),
        )
        experiment = execute_worker(
            client,
            store,
            manifest,
            environment,
            inputs,
            timeouts,
            task=task,
            trial=trial,
            arm=arm,
            credentials=credentials,
            deadline_at=deadline,
        )
        evidence.experiments.append(experiment)
        if task == "benchmark" and trial is not None and arm is not None:
            bootstrap_roles(
                client,
                environment.container_id,
                drop_clone_sql(
                    manifest.run_id, manifest.ownership_token, identity, task, trial, arm
                ),
                database="postgres",
                timeout_seconds=remaining(),
            )
        if experiment.baseline is None or (
            not experiment.baseline.success
            or experiment.baseline.data_sha256 != template.data_sha256
        ):
            raise WorkerError("Fresh branch does not match its verified template")
        if task == "baseline_probe" and (
            experiment.completion != "complete"
            or any(not result.success for result in experiment.operations)
        ):
            return
