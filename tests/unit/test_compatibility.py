import io
import json
import stat
from pathlib import Path

import pytest
from pydantic import SecretStr
from rich.console import Console

from pg_rehearse.analysis.compatibility import analyze
from pg_rehearse.config import load_config
from pg_rehearse.fixtures.clone import clone_sql
from pg_rehearse.fixtures.template import template_identity
from pg_rehearse.models import (
    BaselineEvidence,
    CatalogState,
    CheckFact,
    CleanupStatus,
    Coverage,
    IndexFact,
    MigrationResult,
    OperationResult,
    RunResult,
    TemplateEvidence,
)
from pg_rehearse.orchestrator import worker_inputs
from pg_rehearse.report.json_report import write_json
from pg_rehearse.report.markdown import render_markdown, write_markdown
from pg_rehearse.report.terminal import render_terminal
from pg_rehearse.runtime.manifest import RunManifest
from pg_rehearse.runtime.roles import ROLE_NAMES
from pg_rehearse.worker_protocol import (
    RehearsalEvidence,
    RoleEvidence,
    WorkerEvidence,
    WorkerRequest,
    task_database,
)
from pg_rehearse.workload.assertions import compare_results
from pg_rehearse.workload.contracts import contract_coverage


@pytest.fixture
def recorded(rehearsal_project: Path):
    loaded = load_config(rehearsal_project / "control.yml")
    inputs = worker_inputs(loaded)
    manifest = RunManifest(
        run_id="a" * 32,
        ownership_token="b" * 32,
        image_requested="postgres:17",
        image_id="sha256:" + "c" * 64,
        cleanup=CleanupStatus.COMPLETE,
        state="cleaned",
    )
    baseline = BaselineEvidence(
        success=True,
        seed=42,
        schema_statements=2,
        table_rows={"users": 2, "orders": 2},
        data_sha256="d" * 64,
    )
    roles = [
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
    ]
    evidence = RehearsalEvidence(
        template=TemplateEvidence(
            identity=template_identity(loaded, manifest.image_id),
            data_sha256="d" * 64,
            sealed=True,
        )
    )
    for task in ["seed", "baseline_probe", "post_deployed"]:
        phase = "baseline" if task == "baseline_probe" else task
        contract = loaded.deployed_contract
        operations = (
            []
            if task == "seed"
            else [
                OperationResult(
                    operation_id=op.id,
                    version=contract.version,
                    phase=phase,
                    success=True,
                    assertions=compare_results(
                        op.expect,
                        op.expect.columns or [],
                        op.expect.rows or [],
                        op.expect.row_count or 0,
                    ),
                )
                for op in contract.operations
            ]
        )
        migrations = (
            []
            if task != "post_deployed"
            else [
                MigrationResult(
                    step_id=step.id,
                    phase=phase,
                    transaction=step.transaction,
                    source_sha256=document.sha256,
                    statements=len(document.statements),
                    executed=len(document.statements),
                    committed=True,
                    catalog_before=CatalogState(
                        columns={
                            "users": ["id", "name", "email"],
                            "orders": ["id", "user_id", "status", "amount_cents"],
                        },
                        indexes=[],
                        checks=[],
                    ),
                    catalog_after=CatalogState(
                        columns={
                            "users": ["id", "name", "email"],
                            "orders": ["id", "user_id", "status", "amount_cents"],
                        },
                        checks=[],
                        indexes=[
                            IndexFact(
                                name="orders_user_id_idx",
                                table="orders",
                                valid=True,
                                ready=True,
                                method="btree",
                                unique=False,
                                columns=["user_id"],
                                options=[0],
                                definition="CREATE INDEX orders_user_id_idx ON orders (user_id)",
                            )
                        ],
                    ),
                )
                for step, document in zip(loaded.spec.migrations, loaded.migration_sql, strict=True)
            ]
        )
        receipt = WorkerEvidence(
            run_id=manifest.run_id,
            input_hashes=inputs.hashes,
            roles=roles,
            baseline=baseline.model_copy(deep=True),
            operations=operations,
            completion="complete",
            task=task,
            database=task_database(manifest.run_id, task),
            coverage=Coverage()
            if task == "seed"
            else contract_coverage(contract, phase, operations),
            migrations=migrations,
        )
        request = WorkerRequest(
            run_id=manifest.run_id,
            database_host=f"pgr-{manifest.run_id}-postgres",
            credentials={role: SecretStr("unit-test") for role in ROLE_NAMES},
            inputs=inputs,
            timeouts=loaded.spec.timeouts,
            task=task,
            database=receipt.database,
        )
        receipt.verify(request)
        if task == "seed":
            evidence.seed = receipt
        else:
            evidence.experiments.append(receipt)
    return loaded, inputs, evidence, manifest


def test_complete_recorded_control_passes_and_reports_agree(recorded, tmp_path: Path) -> None:
    result = analyze(*recorded)
    assert result.exit_code == 0 and not result.coverage.missing
    write_json(tmp_path / "report.json", result)
    write_markdown(tmp_path / "report.md", result)
    assert RunResult.model_validate_json((tmp_path / "report.json").read_bytes()) == result
    assert stat.S_IMODE((tmp_path / "report.json").stat().st_mode) == 0o600
    output = io.StringIO()
    render_terminal(result, Console(file=output, width=150))
    assert "pass" in output.getvalue() and "cleanup complete" in output.getvalue()
    markdown = (tmp_path / "report.md").read_text()
    assert "**pass**" in markdown and "cleanup: complete" in markdown


@pytest.mark.parametrize(
    "change",
    [
        "missing_stage",
        "seed",
        "template",
        "digest",
        "roles",
        "duplicate",
        "identity",
        "claimed_coverage",
        "assertion",
        "migration_hash",
        "commit_flag",
        "missing_operation",
    ],
)
def test_missing_or_forged_evidence_never_passes(recorded, change: str) -> None:
    loaded, inputs, evidence, manifest = recorded
    post = evidence.experiments[-1]
    if change == "missing_stage":
        evidence.experiments.pop()
    elif change == "seed":
        evidence.seed = None
    elif change == "template":
        evidence.template.identity = "e" * 64
    elif change == "digest":
        post.baseline.data_sha256 = "e" * 64
    elif change == "roles":
        post.roles = []
    elif change == "duplicate":
        evidence.experiments.append(post.model_copy(deep=True))
    elif change == "identity":
        post.database = "foreign_database"
    elif change == "claimed_coverage":
        post.coverage.completed = []
    elif change == "assertion":
        post.operations[0].assertions[0].passed = False
    elif change == "migration_hash":
        post.migrations[0].source_sha256 = "e" * 64
    elif change == "commit_flag":
        post.migrations[0].committed = False
    else:
        post.operations.pop()
        post.completion = "partial"
        post.coverage = contract_coverage(
            loaded.deployed_contract, "post_deployed", post.operations
        )
    result = analyze(loaded, inputs, evidence, manifest)
    assert result.verdict.value == "inconclusive" and result.exit_code == 4
    assert result.completion.value == "partial"


@pytest.mark.parametrize(
    "error,sqlstate,exit_code",
    [
        ("sql_error", "42703", 1),
        ("sql_error", "57014", 4),
        ("operation_deadline", None, 4),
        ("connection_error", "08006", 3),
    ],
)
def test_deterministic_failures_deadlines_and_connection_errors_are_distinct(
    recorded,
    error,
    sqlstate,
    exit_code,
) -> None:
    loaded, inputs, evidence, manifest = recorded
    operation = evidence.experiments[-1].operations[0]
    operation.success = False
    operation.assertions = []
    operation.error_kind = error
    operation.sqlstate = sqlstate
    result = analyze(loaded, inputs, evidence, manifest)
    assert result.exit_code == exit_code
    assert not result.coverage.missing
    if exit_code == 1:
        finding = next(f for f in result.findings if f.rule_id == "DEPLOYED_SQL_ERROR")
        assert finding.evidence["sql"] == loaded.deployed_contract.operations[0].sql
        assert finding.evidence["sqlstate"] == "42703"
        manifest.cleanup = CleanupStatus.FAILED
        failed_cleanup = analyze(loaded, inputs, evidence, manifest)
        assert failed_cleanup.exit_code == 1 and failed_cleanup.cleanup == CleanupStatus.FAILED
    else:
        assert result.verdict.value == "inconclusive"


def test_broken_baseline_is_not_migration_incompatibility(recorded) -> None:
    loaded, inputs, evidence, manifest = recorded
    evidence.experiments.pop()
    operation = evidence.experiments[0].operations[0]
    operation.success = False
    operation.assertions = []
    operation.error_kind = "sql_error"
    operation.sqlstate = "42703"
    result = analyze(loaded, inputs, evidence, manifest)
    assert result.exit_code == 3 and result.verdict.value == "inconclusive"
    assert any(f.rule_id == "BASELINE_CONTRACT_FAILED" for f in result.findings)
    assert not result.migrations


def test_cleanup_failure_prevents_passing_control(recorded) -> None:
    loaded, inputs, evidence, manifest = recorded
    manifest.cleanup = CleanupStatus.FAILED
    result = analyze(loaded, inputs, evidence, manifest)
    assert result.exit_code == 3 and result.verdict.value == "inconclusive"


def test_template_identity_and_stale_clone_gate(recorded, rehearsal_project: Path) -> None:
    loaded, _, evidence, manifest = recorded
    template = evidence.template
    with pytest.raises(ValueError, match="Stale"):
        clone_sql(manifest.run_id, manifest.ownership_token, template, "e" * 64, "post_deployed")
    assert template_identity(loaded, "different-image") != template.identity
    path = rehearsal_project / "contracts/deployed-v1.yml"
    path.write_text(path.read_text() + "\n# contract-only edit\n")
    assert (
        template_identity(load_config(rehearsal_project / "control.yml"), manifest.image_id)
        == template.identity
    )
    path = rehearsal_project / "fixtures/orders.yml"
    path.write_text(path.read_text() + "\n# fixture input edit\n")
    assert (
        template_identity(load_config(rehearsal_project / "control.yml"), manifest.image_id)
        != template.identity
    )


def test_markdown_fences_contain_hostile_text(recorded) -> None:
    result = analyze(*recorded)
    result.operations[0].version = "<img src=x> [click](https://example.org)"
    from pg_rehearse.models import Finding, Severity

    result.findings.append(
        Finding(
            rule_id="TEST",
            severity=Severity.INFO,
            explanation="<script>alert(1)</script>",
            evidence={"sql": "```\n<script>evil</script>\n```"},
        )
    )
    rendered = render_markdown(result)
    assert "&lt;img" in rendered and "&lt;script&gt;alert" in rendered
    assert "````json" in rendered
    assert json.loads(result.model_dump_json())["cleanup"] == "complete"


def test_seed_preserves_readback_sqlstate(recorded, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from pg_rehearse.fixtures.seed import seed_baseline

    loaded = recorded[0]
    monkeypatch.setattr(
        "pg_rehearse.fixtures.seed.verify_baseline",
        lambda *args: BaselineEvidence(
            success=False,
            seed=42,
            schema_statements=0,
            error_kind="verification_error",
            sqlstate="57014",
        ),
    )
    result = seed_baseline(MagicMock(), loaded.schema_sql, loaded.fixtures, loaded.spec.seed)
    assert not result.success and result.error_kind == "verification_error"
    assert result.sqlstate == "57014"


@pytest.mark.parametrize("change", ["before", "after", "invalid", "column"])
def test_missing_or_wrong_catalog_cannot_pass(recorded, change: str) -> None:
    step = recorded[2].experiments[-1].migrations[0]
    if change == "before":
        step.catalog_before = None
    elif change == "after":
        step.catalog_after = None
    elif change == "invalid":
        step.catalog_after.indexes[0].valid = False
    else:
        step.catalog_after.indexes[0].columns = ["wrong_column"]
    result = analyze(*recorded)
    assert result.exit_code == 4
    assert any(check.startswith("catalog/") for check in result.coverage.missing)


@pytest.mark.parametrize(
    "change", ["empty", "table", "column", "order", "extra", "duplicate_index", "duplicate_check"]
)
def test_incomplete_or_conflicting_catalog_inventory_cannot_pass(recorded, change: str) -> None:
    step = recorded[2].experiments[-1].migrations[0]
    for state in (step.catalog_before, step.catalog_after):
        if change == "empty":
            state.columns = {}
        elif change == "table":
            del state.columns["users"]
        elif change == "column":
            state.columns["users"].remove("email")
        elif change == "order":
            state.columns["users"].reverse()
        elif change == "extra":
            state.columns["extra"] = ["id"]
        elif change == "duplicate_check":
            state.checks = [
                CheckFact(
                    name="positive", table="orders", validated=value, definition="CHECK(id>0)"
                )
                for value in (False, True)
            ]
    if change == "duplicate_index":
        step.catalog_after.indexes.insert(
            0, step.catalog_after.indexes[0].model_copy(update={"valid": False})
        )
    result = analyze(*recorded)
    assert result.exit_code == 4 and result.verdict.value == "inconclusive"
    assert any(check.startswith("catalog/") for check in result.coverage.missing)
    assert any(finding.rule_id == "CATALOG_EVIDENCE_MISSING" for finding in result.findings)
