import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import ContainerCollection

from pg_rehearse.errors import CleanupError, ManifestError, RuntimeLifecycleError
from pg_rehearse.models import CleanupStatus
from pg_rehearse.runtime.cleanup import recover_run
from pg_rehearse.runtime.docker import DockerRuntime, RunEnvironment, RuntimeOptions
from pg_rehearse.runtime.manifest import ManifestStore, ResourceRecord, resource_name

pytestmark = pytest.mark.integration


def assert_removed(client: DockerClient, environment: RunEnvironment) -> None:
    with pytest.raises(NotFound):
        client.containers.get(environment.container_id)
    with pytest.raises(NotFound):
        client.networks.get(environment.network_id)


def test_real_postgres_is_ready_isolated_and_removed(
    docker_client: DockerClient, tmp_path: Path
) -> None:
    with DockerRuntime(state_dir=tmp_path, client=docker_client).provision() as environment:
        container = docker_client.containers.get(environment.container_id)
        resolution = container.exec_run(["getent", "hosts", environment.database_host])
        assert resolution.exit_code == 0  # Future workers can use the actual Docker DNS name.
        result = container.exec_run(
            [
                "psql",
                "-U",
                "rehearse_admin",
                "-d",
                "rehearsal",
                "-Atc",
                "SELECT current_setting('server_version_num')::int / 10000;",
            ]
        )
        assert result.exit_code == 0 and result.output.strip() == b"17"
        assert not container.attrs["HostConfig"]["PortBindings"]
        assert container.attrs["HostConfig"]["Memory"] == 512 * 1024 * 1024
        assert container.attrs["HostConfig"]["NanoCpus"] == 1_000_000_000
        assert container.attrs["HostConfig"]["PidsLimit"] == 128
        assert container.attrs["HostConfig"]["Tmpfs"]["/var/lib/postgresql/data"]
        assert all(mount["Type"] != "volume" for mount in container.attrs["Mounts"])
        assert docker_client.networks.get(environment.network_id).attrs["Internal"]
        assert environment.image_digest.startswith("postgres@sha256:")
        content = environment.manifest_path.read_text()
        secret = next(
            item.split("=", 1)[1]
            for item in container.attrs["Config"]["Env"]
            if item.startswith("POSTGRES_PASSWORD=")
        )
        assert secret not in content
    assert_removed(docker_client, environment)
    assert ManifestStore(environment.manifest_path).load().cleanup == CleanupStatus.COMPLETE


def test_real_sql_exception_still_removes_resources(
    docker_client: DockerClient, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match="workload failed"):
        with DockerRuntime(state_dir=tmp_path, client=docker_client).provision() as environment:
            result = docker_client.containers.get(environment.container_id).exec_run(
                [
                    "psql",
                    "-U",
                    "rehearse_admin",
                    "-d",
                    "rehearsal",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    "SELECT nonexistent_column FROM nonexistent_table;",
                ]
            )
            assert result.exit_code != 0
            raise RuntimeError("workload failed")
    assert_removed(docker_client, environment)
    assert ManifestStore(environment.manifest_path).load().failure == "RuntimeError"


def test_readiness_timeout_removes_resources(docker_client: DockerClient, tmp_path: Path) -> None:
    with pytest.raises(RuntimeLifecycleError):
        with DockerRuntime(
            state_dir=tmp_path, client=docker_client, options=RuntimeOptions(startup_seconds=0.01)
        ).provision():
            pytest.fail("A fresh database cannot meet this startup deadline")
    manifest = ManifestStore(next(tmp_path.glob("*/manifest.json"))).load()
    assert manifest.cleanup == CleanupStatus.COMPLETE
    assert all(resource.removed for resource in manifest.resources)


def test_partial_allocation_is_cleaned(
    docker_client: DockerClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_create(*args: object, **kwargs: object) -> None:
        raise APIError("injected create failure")

    monkeypatch.setattr(ContainerCollection, "create", fail_create)
    with pytest.raises(RuntimeLifecycleError):
        with DockerRuntime(state_dir=tmp_path, client=docker_client).provision():
            pytest.fail("Container allocation must fail")
    manifest = ManifestStore(next(tmp_path.glob("*/manifest.json"))).load()
    assert manifest.cleanup == CleanupStatus.COMPLETE
    network = next(item for item in manifest.resources if item.kind == "network")
    with pytest.raises(NotFound):
        docker_client.networks.get(network.resource_id)


def test_recover_creation_intent_without_saved_id(
    docker_client: DockerClient, tmp_path: Path
) -> None:
    store, manifest = ManifestStore.create(tmp_path, "postgres:17")
    name = resource_name(manifest.run_id, "network")
    manifest.resources.append(ResourceRecord(kind="network", name=name))
    store.save(manifest)
    network = docker_client.networks.create(name, internal=True, labels=manifest.labels("network"))
    try:
        assert recover_run(store.path).cleanup == CleanupStatus.COMPLETE
        with pytest.raises(NotFound):
            docker_client.networks.get(network.id)
        assert recover_run(store.path).cleanup == CleanupStatus.COMPLETE
    finally:
        try:
            network.remove()
        except NotFound:
            pass


def test_forged_manifest_cannot_delete_another_run(
    docker_client: DockerClient, tmp_path: Path
) -> None:
    with DockerRuntime(state_dir=tmp_path, client=docker_client).provision() as environment:
        store, forged = ManifestStore.create(tmp_path, "postgres:17")
        forged.resources.append(
            ResourceRecord(
                kind="container",
                name=resource_name(forged.run_id, "container"),
                resource_id=environment.container_id,
            )
        )
        store.save(forged)
        outcome = recover_run(store.path)
        assert outcome.cleanup == CleanupStatus.FAILED
        assert "container:ownership_mismatch" in outcome.cleanup_errors
        assert docker_client.containers.get(environment.container_id).status == "running"
        with pytest.raises(ManifestError, match="active"):
            recover_run(environment.manifest_path)
    assert recover_run(store.path).cleanup == CleanupStatus.COMPLETE


def test_two_runs_cannot_remove_each_other(docker_client: DockerClient, tmp_path: Path) -> None:
    with DockerRuntime(state_dir=tmp_path, client=docker_client).provision() as first:
        with DockerRuntime(state_dir=tmp_path, client=docker_client).provision() as second:
            assert first.network_id != second.network_id
            assert first.container_id != second.container_id
        assert_removed(docker_client, second)
        assert docker_client.containers.get(first.container_id).status == "running"
    assert_removed(docker_client, first)


def test_cleanup_failure_is_visible_and_recoverable(
    docker_client: DockerClient, tmp_path: Path
) -> None:
    foreign = None
    try:
        with pytest.raises(CleanupError):
            with DockerRuntime(state_dir=tmp_path, client=docker_client).provision() as environment:
                foreign = docker_client.containers.run(
                    "postgres:17",
                    ["sleep", "60"],
                    detach=True,
                    network=environment.network_id,
                    tmpfs={"/var/lib/postgresql/data": "size=268435456"},
                )
        outcome = ManifestStore(environment.manifest_path).load()
        assert outcome.cleanup == CleanupStatus.FAILED
        assert foreign is not None
        assert docker_client.containers.get(foreign.id).status == "running"
    finally:
        if foreign is not None:
            foreign.remove(force=True, v=False)
        if "environment" in locals():
            assert recover_run(environment.manifest_path).cleanup == CleanupStatus.COMPLETE


@contextmanager
def running_cli(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[bytes], Path]]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pg_rehearse",
            "sandbox",
            "--hold-seconds",
            "60",
            "--state-dir",
            str(tmp_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            paths = list(tmp_path.glob("*/manifest.json"))
            if paths and json.loads(paths[0].read_text())["state"] == "ready":
                yield process, paths[0]
                return
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"CLI exited early: {stdout!r} {stderr!r}")
            time.sleep(0.1)
        pytest.fail("CLI did not reach PostgreSQL readiness")
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
        for path in tmp_path.glob("*/manifest.json"):
            assert recover_run(path).cleanup == CleanupStatus.COMPLETE


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_cli_interrupt_cleans_resources(
    docker_client: DockerClient, tmp_path: Path, signum: int
) -> None:
    with running_cli(tmp_path) as (process, path):
        os.kill(process.pid, signum)
        process.communicate(timeout=15)
        assert process.returncode == 128 + signum
        manifest = ManifestStore(path).load()
        assert manifest.cleanup == CleanupStatus.COMPLETE
        assert all(resource.removed for resource in manifest.resources)


def test_sigkill_leaves_a_recoverable_manifest(docker_client: DockerClient, tmp_path: Path) -> None:
    with running_cli(tmp_path) as (process, path):
        process.kill()
        process.communicate(timeout=10)
        assert ManifestStore(path).load().state == "ready"
        result = subprocess.run(
            [sys.executable, "-m", "pg_rehearse", "recover", "--manifest", str(path)],
            capture_output=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr.decode()
        assert ManifestStore(path).load().cleanup == CleanupStatus.COMPLETE
