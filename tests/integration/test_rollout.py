import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from docker import DockerClient
from docker.errors import NotFound
from docker.models.containers import ContainerCollection
from pydantic import SecretStr

from pg_rehearse.analysis.compatibility import analyze
from pg_rehearse.config import load_config
from pg_rehearse.models import CleanupStatus
from pg_rehearse.orchestrator import run_rehearsal, worker_inputs
from pg_rehearse.rollout.phases import phase_results, rollout_plan
from pg_rehearse.rollout.validation import rollout_coverage
from pg_rehearse.runtime.manifest import KIND_LABEL, ManifestStore
from pg_rehearse.runtime.roles import ROLE_NAMES
from pg_rehearse.worker_protocol import RehearsalEvidence, WorkerEvidence, WorkerRequest

pytestmark = pytest.mark.integration
PRELUDE = """
import sys, os, signal
from pg_rehearse.worker import execute_baseline, connect_as
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


@pytest.mark.parametrize(
    "filename,code",
    [
        ("rollout.yml", 0),
        ("rollout-rename.yml", 1),
        ("applications.yml", 0),
        ("applications-rename.yml", 1),
        ("applications-status-failure.yml", 1),
        ("check-tightening.yml", 1),
        ("index-drop.yml", 0),
    ],
)
def test_labeled_rollout_application_and_ddl_cases(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    filename: str,
    code: int,
) -> None:
    result, directory = run_rehearsal(rehearsal_project / filename, state_dir=tmp_path / "runs")
    assert result.exit_code == code
    if filename == "applications-status-failure.yml":
        assert all(op.success for op in result.operations)
        failed = [app for app in result.applications if not app.success]
        assert {app.phase for app in failed} == {"app_mixed_versions", "app_rollback"}
        assert all(app.http_status == 422 and app.error_kind == "domain_error" for app in failed)
        assert any(f.rule_id == "APPLICATION_DOMAIN_ERROR" for f in result.findings)
        assert any(
            app.phase == "app_rollback" and app.probe_id.startswith("order.write") and app.success
            for app in result.applications
        )
    elif filename == "applications-rename.yml":
        old = [
            app
            for app in result.applications
            if app.phase in {"app_persistent_old", "app_fresh_old"}
        ]
        assert len(old) == 2 and all(app.sqlstate == "42703" for app in old)
        assert next(app for app in result.applications if app.phase == "app_candidate").success
        assert any(f.rule_id == "APPLICATION_SQL_ERROR" for f in result.findings)
    elif filename == "applications.yml":
        assert len(result.applications) == 13 and all(app.success for app in result.applications)
        assert result.evidence_levels == ["sql_contract", "reference_application"]
        old = next(app for app in result.applications if app.phase == "app_baseline")
        persistent = next(app for app in result.applications if app.phase == "app_persistent_old")
        fresh = next(app for app in result.applications if app.phase == "app_fresh_old")
        assert old.backend_pid == persistent.backend_pid != fresh.backend_pid
        assert old.process_id == persistent.process_id != fresh.process_id
    elif filename == "check-tightening.yml":
        step = result.migrations[0]
        check = next(c for c in step.catalog_after.checks if c.name == "positive_amount")
        assert not check.validated and "> 0" in check.definition
        assert (
            next(
                op
                for op in result.operations
                if op.phase == "post_deployed" and op.operation_id == "write-zero-order"
            ).sqlstate
            == "23514"
        )
    elif filename == "index-drop.yml":
        assert all(step.committed for step in result.migrations)
        assert any(
            i.name == "orders_user_id_idx" for i in result.migrations[1].catalog_before.indexes
        )
        assert not any(
            i.name == "orders_user_id_idx" for i in result.migrations[1].catalog_after.indexes
        )
    if filename in {"rollout.yml", "rollout-rename.yml"}:
        for actor in ("old_1", "old_2"):
            before = next(op for op in result.operations if op.phase == f"rollout_baseline/{actor}")
            after = next(op for op in result.operations if op.phase == f"persistent_old/{actor}")
            assert before.backend_pid == after.backend_pid
            if filename == "rollout-rename.yml":
                assert after.sqlstate == "42703"
                assert any(
                    f.phase == after.phase and f.rule_id == "DEPLOYED_SQL_ERROR"
                    for f in result.findings
                )
        writes = [op for op in result.operations if op.committed]
        assert len(writes) == 3
        assert {op.phase for op in writes} == {"mixed_versions", "app_rollback"}
        assert len({branch.data_sha256 for branch in result.branches}) == 1
    assert json.loads((directory / "report.json").read_text())["cleanup"] == "complete"
    clean(docker_client, directory)


def test_real_receipts_reject_forged_session_commit_app_and_phase_claims(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
) -> None:
    path = rehearsal_project / "applications.yml"
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    loaded = load_config(path)
    inputs = worker_inputs(loaded)
    manifest = ManifestStore(directory / "manifest.json").load()
    receipt = WorkerEvidence.model_validate_json((directory / "rollout-evidence.json").read_bytes())
    request = WorkerRequest(
        run_id=manifest.run_id,
        database_host=f"pgr-{manifest.run_id}-postgres",
        credentials={role: SecretStr("test-only") for role in ROLE_NAMES},
        inputs=inputs,
        timeouts=loaded.spec.timeouts,
        task="rollout",
        database=receipt.database,
    )
    receipt.verify(request)
    for change in ("session", "commit", "revision", "assertion", "phase", "coverage"):
        forged = receipt.model_copy(deep=True)
        if change == "session":
            next(
                op for op in forged.operations if op.phase == "persistent_old/old_1"
            ).backend_pid += 1
        elif change == "commit":
            next(op for op in forged.operations if op.committed).committed = False
        elif change == "revision":
            forged.applications[0].revision = "forged"
        elif change == "assertion":
            forged.applications[0].assertions[0].expected = {"id": 7, "name": "invented"}
        elif change == "phase":
            forged.phases.pop()
        else:
            forged.coverage.completed = forged.coverage.required.copy() + ["invented"]
        with pytest.raises(ValueError):
            forged.verify(request)
    partial = receipt.model_copy(deep=True)
    partial.operations = [op for op in partial.operations if op.phase != "candidate_only"]
    partial.phases = phase_results(rollout_plan(loaded, "rollout"), partial.operations)
    partial.coverage = rollout_coverage(loaded, partial)
    partial.completion = "partial"
    partial.verify(request)
    evidence = RehearsalEvidence(
        seed=WorkerEvidence.model_validate_json((directory / "seed-evidence.json").read_bytes()),
        template=result.template,
        experiments=[
            WorkerEvidence.model_validate_json((directory / name).read_bytes())
            for name in (
                "worker-evidence.json",
                "post_deployed-evidence.json",
                "post_candidate-evidence.json",
                "rollback-evidence.json",
            )
        ]
        + [partial],
    )
    incomplete = analyze(loaded, inputs, evidence, manifest)
    assert incomplete.exit_code == 4 and incomplete.coverage.missing
    clean(docker_client, directory)


def test_failed_write_assertion_rolls_back_and_skips_dependent_reads(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = rehearsal_project / "rollout.yml"
    data = yaml.safe_load(path.read_text())
    data["rollout"]["phases"][0]["operations"][0]["expect"]["rows"] = [[101, 999]]
    path.write_text(yaml.safe_dump(data))
    inject(
        monkeypatch,
        """
evidence = execute_baseline(request)
with connect_as(request, 'workload') as conn:
    assert conn.execute('SELECT amount_cents FROM orders WHERE id=101').fetchone() == (12500,)
print(evidence.model_dump_json())
""",
        "rollout",
    )
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == 1 and result.completion.value == "partial"
    attempted = [op for op in result.operations if op.phase == "mixed_versions"]
    assert len(attempted) == 1 and not attempted[0].committed
    assert not any(op.phase == "candidate_only" for op in result.operations)
    assert any(op.phase == "app_rollback" and op.committed for op in result.operations)
    clean(docker_client, directory)


def test_committed_candidate_write_survives_a_failing_old_read(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = rehearsal_project / "rollout.yml"
    data = yaml.safe_load(path.read_text())
    data["rollout"]["phases"][0]["operations"][3]["expect"]["rows"] = [[101, 999]]
    path.write_text(yaml.safe_dump(data))
    inject(
        monkeypatch,
        """
evidence = execute_baseline(request)
with connect_as(request, 'workload') as conn:
    assert conn.execute('SELECT amount_cents FROM orders WHERE id=101').fetchone() == (12502,)
print(evidence.model_dump_json())
""",
        "rollout",
    )
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == 1
    mixed = [op for op in result.operations if op.phase == "mixed_versions"]
    assert len(mixed) == 4 and mixed[2].committed and not mixed[3].success
    clean(docker_client, directory)


def test_failed_concurrent_build_retains_invalid_index_evidence(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = rehearsal_project / "control.yml"
    data = yaml.safe_load(path.read_text())
    data["timeouts"] = {"statement_ms": 1000, "lock_ms": 100}
    data["migrations"][0]["transaction"] = "autocommit"
    path.write_text(yaml.safe_dump(data))
    migration = rehearsal_project / data["migrations"][0]["path"]
    migration.write_text(migration.read_text().replace("CREATE INDEX", "CREATE INDEX CONCURRENTLY"))
    inject(
        monkeypatch,
        """
with connect_as(request, 'workload') as blocker:
    with blocker.transaction():
        blocker.execute('UPDATE orders SET amount_cents=amount_cents WHERE id=101')
        evidence = execute_baseline(request)
print(evidence.model_dump_json())
""",
        "post_deployed",
    )
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == 4 and not result.migrations[0].committed
    index = next(
        i for i in result.migrations[0].catalog_after.indexes if i.name == "orders_user_id_idx"
    )
    assert not index.valid
    assert any(f.rule_id == "INVALID_INDEX_REMAINS" for f in result.findings)
    clean(docker_client, directory)


@pytest.mark.parametrize("fail_validation", [False, True])
def test_check_validation_and_drop_readd_boundaries(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    fail_validation: bool,
) -> None:
    path = rehearsal_project / "check-tightening.yml"
    data = yaml.safe_load(path.read_text())
    contract = rehearsal_project / data["contracts"]["deployed"]
    old = yaml.safe_load(contract.read_text())
    old["operations"] = old["operations"][:1]
    contract.write_text(yaml.safe_dump(old))
    (rehearsal_project / "migrations/validate.sql").write_text(
        "ALTER TABLE orders VALIDATE CONSTRAINT positive_amount;"
    )
    data["migrations"].append({"id": "validate", "path": "migrations/validate.sql"})
    if fail_validation:
        fixture = rehearsal_project / data["fixtures_path"]
        rows = yaml.safe_load(fixture.read_text())
        rows["tables"]["orders"][0]["amount_cents"] = 0
        fixture.write_text(yaml.safe_dump(rows))
    else:
        (rehearsal_project / "migrations/replace.sql").write_text(
            "ALTER TABLE orders DROP CONSTRAINT positive_amount; "
            "ALTER TABLE orders ADD CONSTRAINT positive_amount CHECK (amount_cents >= 0);"
        )
        data["migrations"].append({"id": "replace", "path": "migrations/replace.sql"})
    path.write_text(yaml.safe_dump(data))
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == (1 if fail_validation else 0)
    if fail_validation:
        assert result.migrations[-1].sqlstate == "23514"
        assert not next(
            c for c in result.migrations[-1].catalog_after.checks if c.name == "positive_amount"
        ).validated
    else:
        after = result.migrations[-1].catalog_after
        assert next(c for c in after.checks if c.name == "positive_amount").validated
        assert ">= 0" in next(c for c in after.checks if c.name == "positive_amount").definition
    clean(docker_client, directory)


@pytest.mark.parametrize("failure,code", [("crash", 3), ("malformed", 3), ("timeout", 4)])
def test_application_failures_are_not_compatibility_passes(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    code: int,
) -> None:
    path = rehearsal_project / "applications.yml"
    data = yaml.safe_load(path.read_text())
    data["timeouts"] = {"application_ms": 100}
    path.write_text(yaml.safe_dump(data))
    if failure == "crash":
        script = """
from pg_rehearse.rollout import apps
original = apps.start
def start(stack, request, version):
    app = original(stack, request, version)
    if version == 'candidate':
        os.killpg(app.process.pid, signal.SIGKILL)
        app.process.wait(timeout=2)
    return app
apps.start = start
print(execute_baseline(request).model_dump_json())
"""
    else:
        # A real test HTTP process with a real scoped DB connection and a bad response.
        server = """
import json, os, sys, time
import psycopg
from http.server import HTTPServer, BaseHTTPRequestHandler
from pg_rehearse.rollout.orders_app import revision
settings = json.loads(sys.stdin.buffer.readline())
connection = psycopg.connect(**settings, autocommit=True)
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        TIMEOUT
        self.send_response(200)
        self.end_headers()
        try: self.wfile.write(b'not-json')
        except BrokenPipeError: pass
server = HTTPServer(('127.0.0.1', 0), Handler)
print(json.dumps({'port': server.server_port, 'revision': revision('candidate'),
                  'process_id': os.getpid(),
                  'backend_pid': connection.info.backend_pid}), flush=True)
server.serve_forever()
""".replace("TIMEOUT", "time.sleep(1)" if failure == "timeout" else "pass")
        script = f"""
from pg_rehearse.rollout import apps
original = apps.subprocess.Popen
def popen(args, **kwargs):
    if args[-1] == 'candidate':
        args = [sys.executable, '-c', {server!r}]
    return original(args, **kwargs)
apps.subprocess.Popen = popen
print(execute_baseline(request).model_dump_json())
"""
    inject(monkeypatch, script, "rollout")
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == code and result.verdict.value == "inconclusive"
    failed = [app for app in result.applications if not app.success]
    assert failed
    assert (
        failed[0].error_kind
        == {
            "crash": "process_error",
            "malformed": "invalid_response",
            "timeout": "application_deadline",
        }[failure]
    )
    if failure == "crash":
        assert failed[0].exit_code == -9
    clean(docker_client, directory)


def test_index_and_rename_in_one_step_have_verified_final_catalog(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
) -> None:
    path = rehearsal_project / "migrations/rename_user_name.sql"
    path.write_text("CREATE INDEX users_name_idx ON users(name);\n" + path.read_text())
    result, directory = run_rehearsal(
        rehearsal_project / "rehearsal.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 1 and not result.coverage.missing
    index = next(
        i for i in result.migrations[0].catalog_after.indexes if i.name == "users_name_idx"
    )
    assert index.columns == ["full_name"] and index.valid
    clean(docker_client, directory)
