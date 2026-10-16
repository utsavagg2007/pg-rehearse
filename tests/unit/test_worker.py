import hashlib
import io
import json
import signal
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from pg_rehearse.config import load_config, load_worker_config
from pg_rehearse.errors import ConfigurationError, WorkerDeadline
from pg_rehearse.models import BaselineEvidence, OperationResult, Timeouts
from pg_rehearse.orchestrator import check_isolated_worker, worker_inputs
from pg_rehearse.runtime.roles import ROLE_NAMES, new_credentials
from pg_rehearse.worker import execution_deadline, main
from pg_rehearse.worker_protocol import (
    InputFile,
    RoleEvidence,
    WorkerEvidence,
    WorkerRequest,
)
from pg_rehearse.workload.assertions import compare_results
from pg_rehearse.workload.contracts import contract_coverage


@pytest.fixture
def worker_request(rehearsal_project: Path) -> WorkerRequest:
    return WorkerRequest(
        run_id="a" * 32,
        database_host=f"pgr-{'a' * 32}-postgres",
        credentials=new_credentials(),
        timeouts=Timeouts(),
        inputs=worker_inputs(load_config(rehearsal_project / "rehearsal.yml")),
    )


def valid_evidence(request: WorkerRequest) -> WorkerEvidence:
    loaded = load_worker_config(request.inputs)
    contract = loaded.deployed_contract
    operations = [
        OperationResult(
            operation_id=op.id,
            version=contract.version,
            phase="baseline",
            success=True,
            assertions=compare_results(
                op.expect, op.expect.columns or [], op.expect.rows or [], op.expect.row_count or 0
            ),
        )
        for op in contract.operations
    ]
    return WorkerEvidence(
        baseline=BaselineEvidence(
            success=True,
            seed=42,
            schema_statements=2,
            table_rows={"users": 2, "orders": 2},
            data_sha256="a" * 64,
        ),
        operations=operations,
        coverage=contract_coverage(contract, "baseline", operations),
        run_id=request.run_id,
        completion="complete",
        input_hashes=request.inputs.hashes,
        roles=[
            RoleEvidence(
                role=role,
                session_user=name,
                current_user=ROLE_NAMES["migration"] if role == "setup" else name,
                server_major=17,
                statement_ms=5000,
                lock_ms=1000,
                elevated=False,
                schema_create=role in {"setup", "migration"},
                database_create=False,
                database_temp=False,
                read_all_stats=role == "observer",
            )
            for role, name in ROLE_NAMES.items()
        ],
    )


def test_wire_masks_secrets_except_explicit_stdin_payload(worker_request: WorkerRequest) -> None:
    for secret in worker_request.credentials.values():
        assert secret.get_secret_value() not in repr(worker_request)
        assert secret.get_secret_value() not in worker_request.model_dump_json()
    decoded = WorkerRequest.model_validate_json(worker_request.to_wire())
    assert decoded == worker_request
    evidence = valid_evidence(worker_request)
    evidence.verify(decoded)
    for secret in worker_request.credentials.values():
        assert secret.get_secret_value() not in evidence.model_dump_json()


@pytest.mark.parametrize("name", ["../schema.sql", "/schema.sql", "dir\\schema.sql"])
def test_worker_rejects_escaping_input_names(name: str) -> None:
    with pytest.raises(ValidationError):
        InputFile(name=name, text="x", sha256=hashlib.sha256(b"x").hexdigest())


def test_worker_rejects_modified_snapshot_bytes(worker_request: WorkerRequest) -> None:
    payload = json.loads(worker_request.to_wire())
    payload["inputs"]["files"][0]["text"] = "DROP DATABASE rehearsal"
    with pytest.raises(ValidationError, match="hash mismatch"):
        WorkerRequest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("field", ["run_id", "database_host", "credentials", "schema_version"])
def test_request_identity_and_roles(worker_request: WorkerRequest, field: str) -> None:
    payload = json.loads(worker_request.to_wire())
    payload[field] = {
        "run_id": "b" * 32,
        "database_host": "example.com",
        "credentials": {},
        "schema_version": True,
    }[field]
    with pytest.raises(ValidationError):
        WorkerRequest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "change", ["run", "hashes", "missing", "duplicate", "elevated", "deadline"]
)
def test_incomplete_evidence_cannot_pass(worker_request: WorkerRequest, change: str) -> None:
    evidence = valid_evidence(worker_request)
    if change == "run":
        evidence.run_id = "b" * 32
    elif change == "hashes":
        evidence.input_hashes = []
    elif change == "missing":
        evidence.roles.pop()
    elif change == "duplicate":
        evidence.roles.append(evidence.roles[0])
    elif change == "elevated":
        evidence.roles[0].elevated = True
    else:
        evidence.roles[0].statement_ms = 0
    with pytest.raises(ValueError):
        evidence.verify(worker_request)


def test_snapshots_are_copied_without_rereading_host_files(rehearsal_project: Path) -> None:
    loaded = load_config(rehearsal_project / "rehearsal.yml")
    old = loaded.schema_sql.text
    loaded.schema_path.write_text("unsupported replacement")
    inputs = worker_inputs(loaded)
    assert next(file.text for file in inputs.files if file.name == "schema/base.sql") == old
    assert str(rehearsal_project) not in inputs.model_dump_json()


def test_aggregate_budget_precedes_allocation(
    rehearsal_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pg_rehearse.config.MAX_INPUT_TOTAL", 100)
    allocator = MagicMock(side_effect=AssertionError("must not allocate"))
    monkeypatch.setattr("pg_rehearse.orchestrator.DockerRuntime", allocator)
    with pytest.raises(ConfigurationError, match="8 MiB"):
        check_isolated_worker(rehearsal_project / "rehearsal.yml", state_dir=tmp_path / "runs")
    allocator.assert_not_called()
    assert not (tmp_path / "runs").exists()


def test_execution_deadline_restores_handler() -> None:
    handler = signal.getsignal(signal.SIGALRM)
    with pytest.raises(WorkerDeadline):
        with execution_deadline(0.02):
            time.sleep(1)
    assert signal.getsignal(signal.SIGALRM) == handler
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_nested_deadline_cannot_extend_budget() -> None:
    with pytest.raises(WorkerDeadline):
        with execution_deadline(0.02), execution_deadline(10):
            time.sleep(1)
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_outer_deadline_survives_a_completed_inner_scope() -> None:
    with pytest.raises(WorkerDeadline):
        with execution_deadline(0.05):
            with execution_deadline(1):
                time.sleep(0.005)
            time.sleep(1)
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_invalid_request_never_echoes_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "do-not-echo-this-password"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps({"credentials": secret}).encode() + b"\n")),
    )
    assert main() == 3
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert json.loads(captured.out) == {
        "schema_version": 1,
        "run_id": None,
        "error": "invalid_request",
        "sqlstate": None,
    }


@pytest.mark.parametrize(
    "change", ["setup", "counts", "operation", "assertion", "coverage", "flag", "expected"]
)
def test_baseline_and_contract_evidence_cannot_be_fabricated(
    worker_request: WorkerRequest, change: str
) -> None:
    evidence = valid_evidence(worker_request)
    if change == "setup":
        evidence.baseline = None
    elif change == "counts":
        assert evidence.baseline is not None
        evidence.baseline.table_rows = {}
    elif change == "operation":
        evidence.operations.pop()
    elif change == "assertion":
        evidence.operations[0].assertions.pop()
    elif change == "coverage":
        evidence.coverage.completed = []
    elif change == "flag":
        evidence.operations[0].assertions[0].passed = False
    else:
        evidence.operations[0].assertions[1].expected = [[7, "invented"]]
    with pytest.raises(ValueError):
        evidence.verify(worker_request)
