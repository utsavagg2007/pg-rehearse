import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from docker import DockerClient
from docker.errors import NotFound
from docker.models.containers import ContainerCollection
from typer.testing import CliRunner

from pg_rehearse.cli import app
from pg_rehearse.config import load_config
from pg_rehearse.errors import RuntimeLifecycleError, WorkerError
from pg_rehearse.fixtures.clone import clone_sql
from pg_rehearse.fixtures.template import seal_template_sql, template_identity
from pg_rehearse.models import CleanupStatus, RunResult
from pg_rehearse.orchestrator import run_rehearsal, worker_inputs
from pg_rehearse.runtime.docker import DockerRuntime
from pg_rehearse.runtime.manifest import KIND_LABEL, ManifestStore
from pg_rehearse.runtime.roles import bootstrap_sql, new_credentials
from pg_rehearse.runtime.worker import bootstrap_roles, execute_worker

pytestmark = pytest.mark.integration
PRELUDE = """
import sys
from pg_rehearse.worker import connect_as, execute_baseline
from pg_rehearse.worker_protocol import WorkerRequest
request = WorkerRequest.model_validate_json(sys.stdin.buffer.readline())
"""


def inject(monkeypatch: pytest.MonkeyPatch, script: str, slot: str) -> None:
    original = ContainerCollection.create

    def create(self: ContainerCollection, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("labels", {}).get(KIND_LABEL) == "worker" and kwargs["name"].endswith(slot):
            kwargs["entrypoint"] = ["/app/.venv/bin/python", "-c", PRELUDE + script]
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ContainerCollection, "create", create)


def clean(client: DockerClient, directory: Path) -> None:
    manifest = ManifestStore(directory / "manifest.json").load()
    assert manifest.cleanup == CleanupStatus.COMPLETE
    for record in manifest.resources:
        collection = client.networks if record.kind == "network" else client.containers
        with pytest.raises(NotFound):
            collection.get(record.resource_id or record.name)


def config(project: Path, **changes: Any) -> None:
    path = project / "rehearsal.yml"
    data = yaml.safe_load(path.read_text())
    data.update(changes)
    path.write_text(yaml.safe_dump(data))


@pytest.mark.parametrize("filename,exit_code", [("rehearsal.yml", 1), ("control.yml", 0)])
def test_complete_cli_rehearsals_and_final_reports(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    filename: str,
    exit_code: int,
) -> None:
    output = CliRunner().invoke(
        app,
        [
            "run",
            "--config",
            str(rehearsal_project / filename),
            "--state-dir",
            str(tmp_path / "runs"),
        ],
    )
    assert output.exit_code == exit_code, output.output
    path = next((tmp_path / "runs").glob("*/report.json"))
    result = RunResult.model_validate_json(path.read_bytes())
    assert result.exit_code == exit_code and result.completion.value == "complete"
    assert not result.coverage.missing
    assert result.template.sealed
    assert len({branch.data_sha256 for branch in result.branches}) == 1
    assert result.baseline.data_sha256 == result.branches[0].data_sha256
    assert "cleanup: complete" in path.with_suffix(".md").read_text()
    assert all(step.committed for step in result.migrations)
    if exit_code == 1:
        old = next(
            op
            for op in result.operations
            if op.phase == "post_deployed" and op.operation_id == "get-user"
        )
        assert old.sqlstate == "42703"
        new = next(
            op
            for op in result.operations
            if op.phase == "post_candidate" and op.operation_id == "get-user"
        )
        assert new.success and new.assertions[1].actual == [[7, "Ada"]]
        assert any(f.rule_id == "DEPLOYED_SQL_ERROR" for f in result.findings)
    clean(docker_client, path.parent)


@pytest.mark.parametrize("concurrent", [False, True])
def test_index_is_committed_and_valid_on_a_separate_connection(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    concurrent: bool,
) -> None:
    path = rehearsal_project / "control.yml"
    data = yaml.safe_load(path.read_text())
    if concurrent:
        migration = rehearsal_project / data["migrations"][0]["path"]
        migration.write_text(
            migration.read_text().replace("CREATE INDEX", "CREATE INDEX CONCURRENTLY")
        )
        data["migrations"][0]["transaction"] = "autocommit"
    config(rehearsal_project, contracts=data["contracts"], migrations=data["migrations"])
    inject(
        monkeypatch,
        """
evidence = execute_baseline(request)
with connect_as(request, 'migration') as conn:
    row = conn.execute("SELECT indisvalid, indisready FROM pg_index "
                       "WHERE indexrelid = 'orders_user_id_idx'::regclass").fetchone()
    assert row == (True, True)
print(evidence.model_dump_json())
""",
        "post_deployed",
    )
    result, directory = run_rehearsal(
        rehearsal_project / "rehearsal.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 0
    clean(docker_client, directory)


@pytest.mark.parametrize("mode,renamed", [("transaction", False), ("autocommit", True)])
def test_failed_step_rolls_back_only_its_declared_transaction(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    renamed: bool,
) -> None:
    path = rehearsal_project / "migrations/rename_user_name.sql"
    failing_sql = "ALTER TABLE orders ADD CONSTRAINT never_valid CHECK (amount_cents < 0);"
    if mode == "transaction":
        path.write_text(path.read_text() + "\n" + failing_sql)
        steps = [{"id": "failing", "path": "migrations/rename_user_name.sql"}]
    else:
        (rehearsal_project / "migrations/fail.sql").write_text(failing_sql)
        steps = [
            {"id": "rename", "path": "migrations/rename_user_name.sql", "transaction": mode},
            {"id": "failing", "path": "migrations/fail.sql", "transaction": mode},
        ]
    config(
        rehearsal_project,
        contracts={"deployed": "contracts/deployed-v1.yml"},
        migrations=steps
        + [{"id": "must-not-run", "path": "migrations/create_order_user_index.sql"}],
    )
    inject(
        monkeypatch,
        f"""
evidence = execute_baseline(request)
assert evidence.migrations[-1].sqlstate == '23514'
with connect_as(request, 'migration') as conn:
    names = [r[0] for r in conn.execute("SELECT attname FROM pg_attribute "
             "WHERE attrelid = 'users'::regclass AND attnum > 0 AND NOT attisdropped")]
    assert ('full_name' in names) == {renamed!r}
    assert conn.execute("SELECT to_regclass('orders_user_id_idx')").fetchone() == (None,)
print(evidence.model_dump_json())
""",
        "post_deployed",
    )
    result, directory = run_rehearsal(
        rehearsal_project / "rehearsal.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 1 and result.completion.value == "partial"
    assert len(result.migrations) == (1 if mode == "transaction" else 2)
    step = result.migrations[-1]
    assert step.executed == (1 if mode == "transaction" else 0)
    assert not step.committed and step.sqlstate == "23514"
    if mode == "autocommit":
        assert result.migrations[0].committed
    assert all(op.phase == "baseline" for op in result.operations)
    assert result.coverage.missing
    clean(docker_client, directory)


def test_ordered_steps_commit_before_the_next_step(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
) -> None:
    config(
        rehearsal_project,
        migrations=[
            {"id": "index", "path": "migrations/create_order_user_index.sql"},
            {"id": "rename", "path": "migrations/rename_user_name.sql"},
        ],
    )
    result, directory = run_rehearsal(
        rehearsal_project / "rehearsal.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 1
    assert [step.step_id for step in result.migrations] == ["index", "rename", "index", "rename"]
    assert all(step.committed for step in result.migrations)
    clean(docker_client, directory)


def test_fresh_clones_isolate_committed_writes_and_identity_sequences(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = rehearsal_project / "schema/base.sql"
    schema.write_text(
        schema.read_text().replace(
            "id BIGINT PRIMARY KEY", "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
        )
    )
    # Deliberately commit mutations after the baseline receipt: the next clone must be pristine.
    inject(
        monkeypatch,
        """
evidence = execute_baseline(request)
with connect_as(request, 'workload') as conn:
    row = conn.execute("INSERT INTO users (name,email) "
                       "VALUES ('extra','extra@example.test') RETURNING id").fetchone()
    assert row == (9,)
    conn.execute("UPDATE users SET name = 'changed' WHERE id = 7")
print(evidence.model_dump_json())
""",
        "baseline_probe",
    )
    inject(
        monkeypatch,
        """
evidence = execute_baseline(request)
with connect_as(request, 'workload') as conn:
    row = conn.execute("INSERT INTO users (full_name,email) "
                       "VALUES ('candidate','candidate@example.test') RETURNING id").fetchone()
    assert row == (9,)
print(evidence.model_dump_json())
""",
        "post_candidate",
    )
    result, directory = run_rehearsal(
        rehearsal_project / "rehearsal.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 1
    candidate = next(
        op
        for op in result.operations
        if op.phase == "post_candidate" and op.operation_id == "get-user"
    )
    assert candidate.assertions[1].actual == [[7, "Ada"]]
    assert len({b.data_sha256 for b in result.branches}) == 1
    clean(docker_client, directory)


def test_sealed_template_blocks_connections_and_rejects_stale_catalog_identity(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
) -> None:
    loaded = load_config(rehearsal_project / "rehearsal.yml")
    inputs = worker_inputs(loaded)
    runtime = DockerRuntime(state_dir=tmp_path / "runs", client=docker_client)
    with runtime.provision() as environment:
        active_client, store, manifest, _ = runtime._active
        credentials = new_credentials()
        bootstrap_roles(
            active_client,
            environment.container_id,
            bootstrap_sql(credentials, loaded.spec.timeouts),
        )
        seeded = execute_worker(
            active_client,
            store,
            manifest,
            environment,
            inputs,
            loaded.spec.timeouts,
            task="seed",
            credentials=credentials,
        )
        identity = template_identity(loaded, environment.image_id)
        statement, template = seal_template_sql(
            manifest.run_id, manifest.ownership_token, identity, seeded.baseline
        )
        bootstrap_roles(active_client, environment.container_id, statement, database="postgres")
        pg = docker_client.containers.get(environment.container_id)
        denied = pg.exec_run(
            ["psql", "-X", "-U", "rehearse_admin", "-d", "rehearsal", "-c", "SELECT 1"]
        )
        assert denied.exit_code != 0 and b"not currently accepting connections" in denied.output
        bootstrap_roles(
            active_client,
            environment.container_id,
            "COMMENT ON DATABASE rehearsal IS 'stale';",
            database="postgres",
        )
        with pytest.raises(WorkerError):
            bootstrap_roles(
                active_client,
                environment.container_id,
                clone_sql(
                    manifest.run_id, manifest.ownership_token, template, identity, "baseline_probe"
                ),
                database="postgres",
            )
        absent = pg.exec_run(
            [
                "psql",
                "-X",
                "-At",
                "-U",
                "rehearse_admin",
                "-d",
                "postgres",
                "-c",
                "SELECT datname FROM pg_database WHERE datname LIKE 'pgr_%'",
            ]
        )
        assert absent.exit_code == 0 and not absent.output.strip()
    clean(docker_client, environment.manifest_path.parent)


def test_worker_crash_preserves_partial_reports_and_cleans_all_branches(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inject(monkeypatch, "raise SystemExit(17)", "post_deployed")
    result, directory = run_rehearsal(
        rehearsal_project / "rehearsal.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 3 and result.verdict.value == "inconclusive"
    assert result.coverage.missing and result.operations
    assert (directory / "report.json").exists() and (directory / "report.md").exists()
    assert (directory / "worker-evidence.json").exists()
    clean(docker_client, directory)


def test_report_write_failure_still_finishes_cleanup(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any) -> None:
        raise OSError("injected report failure")

    monkeypatch.setattr("pg_rehearse.orchestrator.write_markdown", fail)
    with pytest.raises(RuntimeLifecycleError, match="Cannot save final reports"):
        run_rehearsal(rehearsal_project / "control.yml", state_dir=tmp_path / "runs")
    directory = next((tmp_path / "runs").iterdir())
    saved = json.loads((directory / "report.json").read_text())
    assert saved["cleanup"] == "complete" and saved["verdict"] == "inconclusive"
    clean(docker_client, directory)


def test_migration_lock_deadline_is_inconclusive_and_preserves_evidence(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config(rehearsal_project, timeouts={"statement_ms": 1000, "lock_ms": 100})
    inject(
        monkeypatch,
        """
with connect_as(request, 'workload') as blocker:
    with blocker.transaction():
        blocker.execute('SELECT id FROM users FOR UPDATE')
        evidence = execute_baseline(request)
print(evidence.model_dump_json())
""",
        "post_deployed",
    )
    result, directory = run_rehearsal(
        rehearsal_project / "rehearsal.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 4 and result.verdict.value == "inconclusive"
    assert result.migrations[0].sqlstate == "55P03"
    assert not result.migrations[0].committed and result.coverage.missing
    assert all(op.success for op in result.operations)
    clean(docker_client, directory)


def test_cleanup_failure_is_in_final_reports_and_recoverable(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docker.errors import APIError
    from docker.models.containers import Container

    from pg_rehearse.runtime.cleanup import recover_run

    original = Container.remove

    def refuse(self: Container, *args: Any, **kwargs: Any) -> Any:
        if self.name.endswith("post_deployed"):
            raise APIError("injected cleanup failure")
        return original(self, *args, **kwargs)

    directory = None
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Container, "remove", refuse)
            result, directory = run_rehearsal(
                rehearsal_project / "control.yml", state_dir=tmp_path / "runs"
            )
        assert result.exit_code == 3 and result.cleanup == CleanupStatus.FAILED
        assert result.verdict.value == "inconclusive"
        assert json.loads((directory / "report.json").read_text())["cleanup"] == "failed"
        assert "cleanup: failed" in (directory / "report.md").read_text()
    finally:
        if directory:
            assert recover_run(directory / "manifest.json").cleanup == CleanupStatus.COMPLETE
    clean(docker_client, directory)
