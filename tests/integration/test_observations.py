import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from docker import DockerClient
from docker.errors import NotFound
from docker.models.containers import ContainerCollection
from pydantic import SecretStr

from pg_rehearse.analysis.locks import observed_wait
from pg_rehearse.config import load_config
from pg_rehearse.models import CleanupStatus
from pg_rehearse.orchestrator import run_rehearsal, worker_inputs
from pg_rehearse.runtime.manifest import KIND_LABEL, ManifestStore
from pg_rehearse.runtime.roles import ROLE_NAMES
from pg_rehearse.worker_protocol import WorkerEvidence, WorkerRequest

pytestmark = pytest.mark.integration
PRELUDE = """
import sys, psycopg
from pg_rehearse.worker import execute_baseline, connect_as
from pg_rehearse.worker_protocol import WorkerRequest
request = WorkerRequest.model_validate_json(sys.stdin.buffer.readline())
"""


def inject(monkeypatch: pytest.MonkeyPatch, slot: str, script: str) -> None:
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


@pytest.mark.parametrize("filename,code", [("contention.yml", 0), ("contention-timeout.yml", 4)])
def test_real_blockers_wait_graph_deadline_and_release(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path, filename: str, code: int
) -> None:
    result, directory = run_rehearsal(rehearsal_project / filename, state_dir=tmp_path / "runs")
    assert result.exit_code == code
    lock = result.contention
    assert lock and lock.blocker_released and observed_wait(lock, "migrator", "blocker")
    assert lock.probe and lock.samples and lock.hold_ms < 5000
    assert observed_wait(lock, "probe", "migrator")
    if code == 0:
        assert all(m.committed for m in result.migrations) and lock.probe.success
        assert not result.coverage.missing
    else:
        assert next(m for m in result.migrations if m.phase == "contention").sqlstate == "55P03"
    loaded = load_config(rehearsal_project / filename)
    manifest = ManifestStore(directory / "manifest.json").load()
    receipt = WorkerEvidence.model_validate_json(
        (directory / "contention-evidence.json").read_bytes()
    )
    request = WorkerRequest(
        run_id=manifest.run_id,
        database_host=f"pgr-{manifest.run_id}-postgres",
        credentials={r: SecretStr("analysis-only") for r in ROLE_NAMES},
        inputs=worker_inputs(loaded),
        timeouts=loaded.spec.timeouts,
        task="contention",
        database=receipt.database,
    )
    receipt.verify(request)
    for change in ("actor", "samples", "release", "barrier", "missing_barrier"):
        forged = receipt.model_copy(deep=True)
        if change == "actor":
            forged.contention.actor_pids["migrator"] += 1
        elif change == "samples":
            forged.contention.samples = []
        elif change == "release":
            forged.contention.blocker_released = False
        elif change == "missing_barrier":
            forged.contention.events = [
                e for e in forged.contention.events if e.name != "migration_submitted"
            ]
        else:
            forged.contention.events.reverse()
        with pytest.raises(ValueError):
            forged.verify(request)
    clean(docker_client, directory)


@pytest.mark.parametrize("failure", ["observer", "no_conflict"])
def test_absent_wait_evidence_is_inconclusive_and_releases_blocker(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    path = rehearsal_project / "contention.yml"
    if failure == "observer":
        inject(
            monkeypatch,
            "contention",
            """
from pg_rehearse.observe import locks
def fail(*args): raise psycopg.OperationalError('sensitive fake observer detail')
locks.sample_locks = fail
print(execute_baseline(request).model_dump_json())
""",
        )
    else:
        data = yaml.safe_load(path.read_text())
        data["contention"]["blocker"] = {
            "id": "unrelated-table",
            "sql": "UPDATE users SET name=name WHERE id=7",
            "expect": {"row_count": 1},
        }
        path.write_text(yaml.safe_dump(data))
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == 4 and "contention/migration_wait" in result.coverage.missing
    assert result.contention.blocker_released
    if failure == "observer":
        assert result.contention.observer_error == "database_error"
        assert "sensitive fake" not in (directory / "report.json").read_text()
    clean(docker_client, directory)


def test_index_changes_real_plan_without_planner_overrides(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    result, directory = run_rehearsal(rehearsal_project / "plans.yml", state_dir=tmp_path / "runs")
    assert result.exit_code == 0
    plan = result.plans[0]
    assert plan["status"] == "compared" and plan["structure_changed"]
    assert "Seq Scan" in json.dumps(plan["baseline"]["structure"])
    assert "orders_user_id_idx" in json.dumps(plan["candidate"]["structure"])
    assert plan["baseline"]["execution_ms"] is not None
    raw = json.loads((directory / "plan_candidate-evidence.json").read_text())
    assert raw["plans"][0]["raw"]["Plan"]
    assert "raw" not in json.loads((directory / "report.json").read_text())["plans"][0]
    assert len({b.data_sha256 for b in result.branches}) == 1
    loaded = load_config(rehearsal_project / "plans.yml")
    manifest = ManifestStore(directory / "manifest.json").load()
    receipt = WorkerEvidence.model_validate_json(
        (directory / "plan_candidate-evidence.json").read_bytes()
    )
    request = WorkerRequest(
        run_id=manifest.run_id,
        database_host=f"pgr-{manifest.run_id}-postgres",
        credentials={r: SecretStr("analysis-only") for r in ROLE_NAMES},
        inputs=worker_inputs(loaded),
        timeouts=loaded.spec.timeouts,
        task="plan_candidate",
        database=receipt.database,
    )
    for change in ("consent", "raw", "commit", "settings"):
        forged = receipt.model_copy(deep=True)
        if change == "consent":
            forged.plans[0].analyze = False
        elif change == "raw":
            forged.plans[0].raw = {"Plan": {}}
        elif change == "commit":
            forged.plans[0].committed = True
        else:
            forged.plans[0].settings = {}
        with pytest.raises(ValueError):
            forged.verify(request)
    clean(docker_client, directory)


@pytest.mark.parametrize("analyze", [False, True])
def test_mutating_explain_requires_consent_and_changes_only_its_clone(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    analyze: bool,
) -> None:
    path = rehearsal_project / "control.yml"
    data = yaml.safe_load(path.read_text())
    data["plans"] = {"operations": ["set-amount"], "analyze": analyze}
    path.write_text(yaml.safe_dump(data))
    contract = rehearsal_project / data["contracts"]["deployed"]
    contents = yaml.safe_load(contract.read_text())
    contents["operations"].append(
        {
            "id": "set-amount",
            "sql": "UPDATE orders SET amount_cents=12501 WHERE id=101 RETURNING amount_cents",
            "expect": {"rows": [[12501]]},
        }
    )
    contract.write_text(yaml.safe_dump(contents))
    for slot in ("plan_baseline", "plan_candidate"):
        inject(
            monkeypatch,
            slot,
            f"""
evidence=execute_baseline(request)
with connect_as(request,'workload') as conn:
    row = conn.execute('SELECT amount_cents FROM orders WHERE id=101').fetchone()
    assert row == ({12501 if analyze else 12500},)
print(evidence.model_dump_json())
""",
        )
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == 0
    assert result.plans[0]["baseline"]["committed"] == analyze
    assert len({b.data_sha256 for b in result.branches}) == 1
    clean(docker_client, directory)


def test_five_paired_trials_with_raw_samples_controls_and_owned_early_cleanup(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inject(
        monkeypatch,
        "benchmark_5_candidate",
        """
from pg_rehearse.fixtures.clone import drop_clone_sql
from pg_rehearse.runtime.manifest import RunManifest
# SQL role may not administer databases; the host alone releases finished clones.
with connect_as(request,'workload') as conn:
    try: conn.execute('CREATE DATABASE forbidden')
    except psycopg.errors.InsufficientPrivilege: pass
    else: raise AssertionError('workload created database')
print(execute_baseline(request).model_dump_json())
""",
    )
    result, directory = run_rehearsal(
        rehearsal_project / "benchmark.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 0 and len(result.benchmarks) == 20
    assert result.performance[0]["status"] in {
        "no_regression_observed",
        "noisy",
        "regression_warning",
    }
    assert len(result.performance[0]["trials"]) == 5
    for arm in result.benchmarks:
        assert len(arm["samples"]) == 250
        assert arm["summaries"]["list-orders"]["successful"] == 200
    assert len({arm["schedule_sha256"] for arm in result.benchmarks}) == 1
    assert len({arm["baseline_sha256"] for arm in result.benchmarks}) == 1
    assert result.environment["postgres_image_id"] and result.environment["worker_image_id"]
    loaded = load_config(rehearsal_project / "benchmark.yml")
    manifest = ManifestStore(directory / "manifest.json").load()
    receipt = WorkerEvidence.model_validate_json(
        (directory / "benchmark_1_baseline-evidence.json").read_bytes()
    )
    request = WorkerRequest(
        run_id=manifest.run_id,
        database_host=f"pgr-{manifest.run_id}-postgres",
        credentials={r: SecretStr("analysis-only") for r in ROLE_NAMES},
        inputs=worker_inputs(loaded),
        timeouts=loaded.spec.timeouts,
        task="benchmark",
        trial=1,
        arm="baseline",
        database=receipt.database,
    )
    for change in ("samples", "schedule", "environment", "arm"):
        forged = receipt.model_copy(deep=True)
        if change == "samples":
            forged.benchmark.samples.pop()
        elif change == "schedule":
            forged.benchmark.schedule_sha256 = "0" * 64
        elif change == "environment":
            forged.benchmark.environment = {}
        else:
            forged.arm = "candidate"
        with pytest.raises(ValueError):
            forged.verify(request)
    clean(docker_client, directory)


@pytest.mark.parametrize("timeout", [False, True])
def test_stateful_benchmark_resets_writes_and_retains_timeouts(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timeout: bool,
) -> None:
    path = rehearsal_project / "benchmark.yml"
    data = yaml.safe_load(path.read_text())
    data["benchmark"] = {"operations": ["bump"], "trials": 1, "warmups": 2, "samples": 3}
    data["timeouts"] = {"statement_ms": 2000, "lock_ms": 100, "worker_seconds": 90}
    path.write_text(yaml.safe_dump(data))
    contract = rehearsal_project / data["contracts"]["deployed"]
    contents = yaml.safe_load(contract.read_text())
    contents["operations"].append(
        {
            "id": "bump",
            "sql": "UPDATE orders SET amount_cents=amount_cents+1 WHERE id=101",
            "expect": {"row_count": 1},
        }
    )
    contract.write_text(yaml.safe_dump(contents))
    for arm in ("baseline", "candidate", "control_a", "control_b"):
        if timeout and arm == "baseline":
            script = """
with connect_as(request,'workload') as blocker, blocker.transaction(force_rollback=True):
    blocker.execute('UPDATE orders SET amount_cents=amount_cents WHERE id=101')
    evidence=execute_baseline(request)
print(evidence.model_dump_json())
"""
        else:
            script = """
evidence=execute_baseline(request)
with connect_as(request,'workload') as conn:
    assert conn.execute('SELECT amount_cents FROM orders WHERE id=101').fetchone()==(12505,)
    query = "SELECT datname FROM pg_database WHERE datname LIKE '%benchmark_%'"
    databases=conn.execute(query).fetchall()
    assert databases==[(request.database,)]
print(evidence.model_dump_json())
"""
        inject(monkeypatch, f"benchmark_1_{arm}", script)
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == 0 and result.performance[0]["status"] == "insufficient"
    assert len(result.benchmarks) == 4
    if timeout:
        baseline = next(b for b in result.benchmarks if b["arm"] == "baseline")
        assert all(not s["success"] and s["sqlstate"] == "55P03" for s in baseline["samples"])
        assert baseline["summaries"]["bump"]["timeouts"] == 3
    clean(docker_client, directory)


def test_finished_benchmark_clone_requires_its_ownership_marker_before_drop(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pg_rehearse.errors import WorkerError
    from pg_rehearse.runtime import worker

    original = worker.bootstrap_roles
    refused = []

    def bootstrap(client: DockerClient, container_id: str, payload: str, **kwargs: Any) -> None:
        if "DROP DATABASE" in payload and not refused:
            name = next(
                line.split('"')[1] for line in payload.splitlines() if "DROP DATABASE" in line
            )
            original(
                client,
                container_id,
                f"COMMENT ON DATABASE \"{name}\" IS 'changed-marker';",
                **kwargs,
            )
            with pytest.raises(WorkerError):
                original(client, container_id, payload, **kwargs)
            check = client.containers.get(container_id).exec_run(
                [
                    "psql",
                    "-X",
                    "-At",
                    "-U",
                    "rehearse_admin",
                    "-d",
                    "postgres",
                    "-c",
                    f"SELECT datname FROM pg_database WHERE datname='{name}'",
                ]
            )
            assert check.exit_code == 0 and check.output.strip().decode() == name
            refused.append(name)
            raise WorkerError("Refused unowned clone")
        original(client, container_id, payload, **kwargs)

    monkeypatch.setattr(worker, "bootstrap_roles", bootstrap)
    result, directory = run_rehearsal(
        rehearsal_project / "benchmark.yml", state_dir=tmp_path / "runs"
    )
    assert refused and result.exit_code == 3
    clean(docker_client, directory)


def test_observations_compose_with_existing_http_rollout_pipeline(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    path = rehearsal_project / "applications.yml"
    data = yaml.safe_load(path.read_text())
    data["contention"] = yaml.safe_load((rehearsal_project / "contention.yml").read_text())[
        "contention"
    ]
    data["benchmark"] = {"operations": ["list-orders"], "trials": 1, "warmups": 1, "samples": 2}
    data["plans"] = {"operations": ["list-orders"]}
    data["timeouts"] = {"worker_seconds": 150}
    path.write_text(yaml.safe_dump(data))
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == 0 and not result.coverage.missing
    assert len(result.applications) == 13 and len(result.benchmarks) == 4
    assert (
        result.performance[0]["status"] == "insufficient"
        and result.plans[0]["status"] == "compared"
    )
    assert result.contention.blocker_released
    assert result.evidence_levels == [
        "sql_contract",
        "reference_application",
        "controlled_contention",
        "advisory_performance",
        "diagnostic_plans",
    ]
    assert len({b.data_sha256 for b in result.branches}) == 1
    assert len({b.phase for b in result.branches}) == len(result.branches)
    html = (directory / "report.html").read_text()
    for section in (
        "findings",
        "coverage",
        "phases",
        "migrations",
        "locks",
        "performance",
        "plans",
    ):
        assert f'id="{section}"' in html
    assert "insufficient" in html and "compared" in html and "observed_at" in html
    assert "HTTP application probes" in html and result.run_id in html
    clean(docker_client, directory)


def test_lost_benchmark_connection_retains_partial_samples_and_infrastructure_outcome(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = rehearsal_project / "benchmark.yml"
    data = yaml.safe_load(path.read_text())
    data["benchmark"] = {"operations": ["list-orders"], "trials": 1, "warmups": 1, "samples": 2}
    path.write_text(yaml.safe_dump(data))
    inject(
        monkeypatch,
        "benchmark_1_baseline",
        """
from pg_rehearse.observe import timings
original=timings.run_operation
def close(connection, *args, **kwargs):
    connection.close()
    return original(connection,*args,**kwargs)
timings.run_operation=close
print(execute_baseline(request).model_dump_json())
""",
    )
    result, directory = run_rehearsal(path, state_dir=tmp_path / "runs")
    assert result.exit_code == 3 and result.performance[0]["status"] == "insufficient"
    receipt = WorkerEvidence.model_validate_json(
        (directory / "benchmark_1_baseline-evidence.json").read_bytes()
    )
    assert receipt.completion == "partial" and len(receipt.benchmark.samples) == 1
    assert receipt.benchmark.samples[0].error_kind == "connection_error"
    clean(docker_client, directory)
