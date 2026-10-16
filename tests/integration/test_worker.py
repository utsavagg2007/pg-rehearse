import json
import time
from pathlib import Path
from typing import Any

import pytest
from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import ContainerCollection

from pg_rehearse.config import LoadedConfig, load_config
from pg_rehearse.errors import WorkerDeadline, WorkerError
from pg_rehearse.models import CleanupStatus, Timeouts
from pg_rehearse.orchestrator import worker_inputs
from pg_rehearse.runtime.cleanup import recover_run
from pg_rehearse.runtime.docker import DockerRuntime
from pg_rehearse.runtime.manifest import (
    KIND_LABEL,
    ManifestStore,
    ResourceRecord,
    resource_name,
)
from pg_rehearse.runtime.roles import new_credentials
from pg_rehearse.worker_protocol import WORKER_IMAGE, WorkerRequest

pytestmark = pytest.mark.integration
PRELUDE = """
import json, os, signal, sys, time
import psycopg
from pg_rehearse.worker import check_roles, connect_as, execution_deadline, execute_baseline
from pg_rehearse.worker_protocol import WorkerRequest
request = WorkerRequest.model_validate_json(sys.stdin.buffer.readline())
"""
FINISH = "\nprint(execute_baseline(request).model_dump_json())\n"


@pytest.fixture
def loaded(rehearsal_project: Path, docker_client: DockerClient) -> LoadedConfig:
    docker_client.images.get(WORKER_IMAGE)  # Fail rather than skip an unprepared integration run.
    return load_config(rehearsal_project / "rehearsal.yml")


def inject_worker(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    original = ContainerCollection.create

    def create(self: ContainerCollection, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("labels", {}).get(KIND_LABEL) == "worker":
            kwargs["entrypoint"] = ["/app/.venv/bin/python", "-c", PRELUDE + script]
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ContainerCollection, "create", create)


def assert_clean(client: DockerClient, directory: Path) -> None:
    for path in directory.glob("*/manifest.json"):
        manifest = ManifestStore(path).load()
        assert manifest.cleanup == CleanupStatus.COMPLETE
        for resource in manifest.resources:
            collection = client.networks if resource.kind == "network" else client.containers
            with pytest.raises(NotFound):
                collection.get(resource.resource_id or resource.name)


def test_production_worker_is_scoped_isolated_and_removed(
    docker_client: DockerClient,
    tmp_path: Path,
    loaded: LoadedConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = new_credentials()
    monkeypatch.setattr("pg_rehearse.runtime.worker.new_credentials", lambda: credentials)
    runtime = DockerRuntime(state_dir=tmp_path, client=docker_client)
    with runtime.provision() as environment:
        postgres = docker_client.containers.get(environment.container_id)
        admin_secret = next(
            value.split("=", 1)[1]
            for value in postgres.attrs["Config"]["Env"]
            if value.startswith("POSTGRES_PASSWORD=")
        )
        evidence = runtime.execute_worker(environment, worker_inputs(loaded), loaded.spec.timeouts)
        manifest = ManifestStore(environment.manifest_path).load()
        worker = docker_client.containers.get(
            next(item.resource_id for item in manifest.resources if item.kind == "worker")
        )
        assert evidence.input_hashes == [snapshot.sha256 for snapshot in loaded.input_snapshots]
        assert len(evidence.roles) == 4
        assert worker.attrs["Image"] == manifest.worker_image_id
        assert worker.attrs["Config"]["User"] == "10001:10001"
        host = worker.attrs["HostConfig"]
        assert host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"]
        assert "no-new-privileges:true" in host["SecurityOpt"]
        assert host["Memory"] == 256 * 1024 * 1024
        assert host["PidsLimit"] == 64
        assert not host["Privileged"] and not host["PortBindings"]
        assert host["PidMode"] != "host" and host["NetworkMode"] == environment.network_id
        assert not host["Binds"] and all(
            mount["Type"] == "tmpfs" for mount in worker.attrs["Mounts"]
        )
        assert list(worker.attrs["NetworkSettings"]["Networks"]) == [
            resource_name(environment.run_id, "network")
        ]
        assert not any(
            "PASSWORD=" in value or "DOCKER_HOST=" in value
            for value in worker.attrs["Config"]["Env"]
        )
        receipt = environment.manifest_path.parent / "worker-evidence.json"
        assert receipt.stat().st_mode & 0o777 == 0o600
        assert json.loads(receipt.read_text())["completion"] == "complete"
        inspection = json.dumps(worker.attrs) + worker.logs().decode()
        saved = receipt.read_text() + environment.manifest_path.read_text()
        for secret in [admin_secret, *(item.get_secret_value() for item in credentials.values())]:
            assert secret not in inspection + saved
    assert_clean(docker_client, tmp_path)


def test_real_authentication_failure_is_redacted_and_never_completes(
    docker_client: DockerClient,
    tmp_path: Path,
    loaded: LoadedConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = new_credentials()
    monkeypatch.setattr("pg_rehearse.runtime.worker.new_credentials", lambda: credentials)
    original = WorkerRequest.to_wire

    def wrong_password(request: WorkerRequest) -> bytes:
        payload = json.loads(original(request))
        payload["credentials"]["workload"] = "injected-invalid-password"
        return json.dumps(payload).encode() + b"\n"

    monkeypatch.setattr(WorkerRequest, "to_wire", wrong_password)
    runtime = DockerRuntime(state_dir=tmp_path, client=docker_client)
    with pytest.raises(WorkerError, match="database_error") as error:
        with runtime.provision() as environment:
            runtime.execute_worker(environment, worker_inputs(loaded), loaded.spec.timeouts)
    saved = environment.manifest_path.read_text() + str(error.value)
    assert all(secret.get_secret_value() not in saved for secret in credentials.values())
    assert "injected-invalid-password" not in saved
    assert not list(tmp_path.glob("*/worker-evidence.json"))
    assert_clean(docker_client, tmp_path)


PERMISSION_PROBES = """
assert os.getuid() == 10001
assert not os.path.exists('/var/run/docker.sock')
assert not os.path.exists('/run/docker.sock')
assert not os.path.exists('/root/.aws/credentials')
assert not any(key in os.environ for key in (
    'SSH_AUTH_SOCK', 'AWS_SECRET_ACCESS_KEY', 'DOCKER_HOST'))
try:
    open('/app/host-write', 'w')
except OSError:
    pass
else:
    raise AssertionError('worker root filesystem is writable')
def denied(connection, sql):
    try:
        connection.execute(sql)
    except psycopg.Error as exc:
        assert exc.sqlstate in ('42501', '25006'), exc.sqlstate
    else:
        raise AssertionError('forbidden permission succeeded')
with connect_as(request, 'setup') as setup:
    setup.execute('CREATE TABLE permissions_probe(id int PRIMARY KEY, value text)')
    setup.execute("INSERT INTO permissions_probe VALUES (1, 'original')")
    owner = setup.execute(
        "SELECT tableowner FROM pg_tables WHERE tablename='permissions_probe'").fetchone()[0]
    assert owner == 'rehearse_migration'
with connect_as(request, 'migration') as migration:
    migration.execute('ALTER TABLE permissions_probe RENAME COLUMN value TO content')
    migration.execute('CREATE INDEX permissions_idx ON permissions_probe(content)')
with connect_as(request, 'workload') as workload:
    workload.execute("INSERT INTO permissions_probe VALUES (2, 'second')")
    workload.execute("UPDATE permissions_probe SET content='changed' WHERE id=1")
    row = workload.execute('SELECT content FROM permissions_probe WHERE id=1').fetchone()
    assert row == ('changed',)
    workload.execute('DELETE FROM permissions_probe WHERE id=2')
    for sql in ('CREATE TABLE forbidden(id int)', 'ALTER TABLE permissions_probe ADD COLUMN x int',
                'TRUNCATE permissions_probe', 'DROP TABLE permissions_probe',
                'SET ROLE rehearse_migration'):
        denied(workload, sql)
    with connect_as(request, 'observer') as observer:
        actors = observer.execute("SELECT count(*) FROM pg_stat_activity "
            "WHERE application_name LIKE 'pg-rehearse/%/workload'").fetchone()[0]
        assert actors >= 1
        for sql in ('SELECT * FROM permissions_probe',
                    'INSERT INTO permissions_probe VALUES (3, NULL)',
                    'CREATE TABLE forbidden(id int)', 'SET ROLE rehearse_migration'):
            denied(observer, sql)
for role in ('setup', 'migration', 'workload', 'observer'):
    with connect_as(request, role) as connection:
        for sql in ('CREATE DATABASE forbidden', 'CREATE ROLE forbidden', 'SET ROLE rehearse_admin',
                    "SELECT pg_read_file('/etc/passwd')", "COPY (SELECT 1) TO PROGRAM 'true'"):
            denied(connection, sql)
"""


def test_real_role_grants_denials_and_nonroot_execution(
    docker_client: DockerClient,
    tmp_path: Path,
    loaded: LoadedConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inject_worker(monkeypatch, PERMISSION_PROBES + FINISH)
    runtime = DockerRuntime(state_dir=tmp_path, client=docker_client)
    with runtime.provision() as environment:
        runtime.execute_worker(environment, worker_inputs(loaded), loaded.spec.timeouts)
    assert_clean(docker_client, tmp_path)


def test_real_statement_lock_and_python_deadlines(
    docker_client: DockerClient,
    tmp_path: Path,
    loaded: LoadedConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inject_worker(
        monkeypatch,
        """
from pg_rehearse.errors import WorkerDeadline
with connect_as(request, 'setup') as setup:
    setup.execute('CREATE TABLE deadline_probe(id int)')
with connect_as(request, 'workload') as workload:
    start = time.monotonic()
    try:
        workload.execute('SELECT pg_sleep(5)')
    except psycopg.errors.QueryCanceled as exc:
        assert exc.sqlstate == '57014' and time.monotonic() - start < 3
    else:
        raise AssertionError('statement deadline did not fire')
    assert workload.execute('SELECT 1').fetchone() == (1,)
    with connect_as(request, 'migration') as migration, migration.transaction():
        migration.execute('LOCK TABLE deadline_probe IN ACCESS EXCLUSIVE MODE')
        start = time.monotonic()
        try:
            workload.execute('SELECT * FROM deadline_probe')
        except psycopg.errors.LockNotAvailable as exc:
            assert exc.sqlstate == '55P03' and time.monotonic() - start < 2
        else:
            raise AssertionError('lock deadline did not fire')
    assert workload.execute('SELECT 1').fetchone() == (1,)
try:
    with execution_deadline(0.02):
        time.sleep(5)
except WorkerDeadline:
    pass
else:
    raise AssertionError('Python execution deadline did not fire')
"""
        + FINISH,
    )
    runtime = DockerRuntime(state_dir=tmp_path, client=docker_client)
    with runtime.provision() as environment:
        runtime.execute_worker(
            environment, worker_inputs(loaded), Timeouts(statement_ms=700, lock_ms=150)
        )
    assert_clean(docker_client, tmp_path)


@pytest.mark.parametrize(
    "script,expected",
    [
        ("os._exit(17)", WorkerError),
        ("print('not-json')", WorkerError),
        ("print('{}')", WorkerError),
        ("print('x' * (8 * 1024 * 1024 + 1))", WorkerError),
        ("print(request.credentials['migration'].get_secret_value())", WorkerError),
        ("signal.signal(signal.SIGALRM, signal.SIG_IGN); time.sleep(60)", WorkerDeadline),
        ("e = check_roles(request); e.roles.pop(); print(e.model_dump_json())", WorkerError),
        ("e = check_roles(request); e.run_id = 'b' * 32; print(e.model_dump_json())", WorkerError),
    ],
)
def test_worker_crash_bad_evidence_and_host_deadline_clean_every_resource(
    docker_client: DockerClient,
    tmp_path: Path,
    loaded: LoadedConfig,
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    expected: type[WorkerError],
) -> None:
    inject_worker(monkeypatch, script)
    runtime = DockerRuntime(state_dir=tmp_path, client=docker_client)
    start = time.monotonic()
    with pytest.raises(expected):
        with runtime.provision() as environment:
            runtime.execute_worker(environment, worker_inputs(loaded), Timeouts(worker_seconds=2))
    assert time.monotonic() - start < 15
    assert not list(tmp_path.glob("*/worker-evidence.json"))
    assert_clean(docker_client, tmp_path)


def test_lost_worker_create_response_is_cleaned_from_intent(
    docker_client: DockerClient,
    tmp_path: Path,
    loaded: LoadedConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ContainerCollection.create

    def lost(self: ContainerCollection, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        if kwargs.get("labels", {}).get(KIND_LABEL) == "worker":
            raise APIError("lost worker create response")
        return result

    monkeypatch.setattr(ContainerCollection, "create", lost)
    runtime = DockerRuntime(state_dir=tmp_path, client=docker_client)
    with pytest.raises(WorkerError):
        with runtime.provision() as environment:
            runtime.execute_worker(environment, worker_inputs(loaded), loaded.spec.timeouts)
    assert_clean(docker_client, tmp_path)


def test_recover_worker_intent_and_refuse_another_runs_worker(
    docker_client: DockerClient, tmp_path: Path, loaded: LoadedConfig
) -> None:
    runtime = DockerRuntime(state_dir=tmp_path, client=docker_client)
    with runtime.provision() as environment:
        runtime.execute_worker(environment, worker_inputs(loaded), loaded.spec.timeouts)
        manifest = ManifestStore(environment.manifest_path).load()
        worker_id = next(item.resource_id for item in manifest.resources if item.kind == "worker")
        store, forged = ManifestStore.create(tmp_path, "postgres:17")
        forged.resources.append(
            ResourceRecord(
                kind="worker", name=resource_name(forged.run_id, "worker"), resource_id=worker_id
            )
        )
        store.save(forged)
        outcome = recover_run(store.path)
        assert outcome.cleanup == CleanupStatus.FAILED
        assert "worker:ownership_mismatch" in outcome.cleanup_errors
        assert docker_client.containers.get(worker_id).id == worker_id
    assert recover_run(store.path).cleanup == CleanupStatus.COMPLETE
    store, manifest = ManifestStore.create(tmp_path, "postgres:17")
    name = resource_name(manifest.run_id, "worker")
    manifest.resources.append(ResourceRecord(kind="worker", name=name))
    store.save(manifest)
    worker = docker_client.containers.create(
        WORKER_IMAGE, name=name, labels=manifest.labels("worker")
    )
    try:
        assert recover_run(store.path).cleanup == CleanupStatus.COMPLETE
        with pytest.raises(NotFound):
            docker_client.containers.get(worker.id)
    finally:
        try:
            worker.remove(force=True, v=False)
        except NotFound:
            pass
