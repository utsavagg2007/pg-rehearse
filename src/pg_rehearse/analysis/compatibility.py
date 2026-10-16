"""Pure compatibility analysis: no Docker calls or database connections."""

from pydantic import SecretStr

from pg_rehearse.analysis.coverage import contract_phases, coverage_for
from pg_rehearse.config import LoadedConfig
from pg_rehearse.fixtures.template import template_identity
from pg_rehearse.migration.catalog import catalog_verified
from pg_rehearse.models import (
    BranchEvidence,
    CleanupStatus,
    Completion,
    Finding,
    RunResult,
    Severity,
    Verdict,
)
from pg_rehearse.rollout.phases import rollout_plan
from pg_rehearse.runtime.manifest import RunManifest
from pg_rehearse.runtime.roles import ROLE_NAMES
from pg_rehearse.worker_protocol import RehearsalEvidence, WorkerInputs, WorkerRequest
from pg_rehearse.workload.contracts import check_id


def analyze(
    loaded: LoadedConfig,
    inputs: WorkerInputs,
    evidence: RehearsalEvidence,
    manifest: RunManifest,
    *,
    infrastructure_error: bool = False,
) -> RunResult:
    findings: list[Finding] = []
    confirmed = False
    invalid = False

    def finding(rule: str, explanation: str, **details: object) -> None:
        findings.append(
            Finding(
                rule_id=rule, severity=Severity.ERROR, explanation=explanation, evidence=details
            )
        )

    # Validate receipts again before deriving coverage, including on saved/partial runs.
    accepted = RehearsalEvidence()
    for receipt in ([evidence.seed] if evidence.seed else []) + evidence.experiments:
        try:
            expected_task = "seed" if receipt is evidence.seed else receipt.task
            if expected_task not in {
                "seed",
                "baseline_probe",
                "post_deployed",
                "post_candidate",
                "rollout",
                "rollback",
            }:
                raise ValueError("Unexpected task")
            if receipt is not evidence.seed and any(
                old.task == receipt.task for old in accepted.experiments
            ):
                raise ValueError("Duplicate experiment")
            receipt.verify(
                WorkerRequest(
                    run_id=manifest.run_id,
                    database_host=f"pgr-{manifest.run_id}-postgres",
                    credentials={role: SecretStr("analysis-only") for role in ROLE_NAMES},
                    inputs=inputs,
                    timeouts=loaded.spec.timeouts,
                    task=expected_task,
                    database=receipt.database,
                )
            )
            if receipt is evidence.seed:
                accepted.seed = receipt
            else:
                accepted.experiments.append(receipt)
        except ValueError:
            invalid = True
            finding("EVIDENCE_INVALID", "A receipt disagrees with the accepted inputs.")
    seed = accepted.seed.baseline if accepted.seed else None
    if evidence.template:
        template = evidence.template
        if (
            seed
            and seed.success
            and template.sealed
            and template.identity == template_identity(loaded, manifest.image_id or "")
            and template.data_sha256 == seed.data_sha256
        ):
            accepted.template = template
        else:
            invalid = True
            finding("EVIDENCE_INVALID", "Template identity or fixture digest does not match.")
    experiments = []
    for receipt in accepted.experiments:
        if (
            accepted.template is None
            or receipt.baseline is None
            or not receipt.baseline.success
            or receipt.baseline.data_sha256 != accepted.template.data_sha256
        ):
            invalid = True
            finding("EVIDENCE_INVALID", "A branch did not begin with the verified fixture data.")
        else:
            experiments.append(receipt)
    accepted.experiments = experiments
    coverage = coverage_for(loaded, accepted)
    baseline = next((r for r in experiments if r.task == "baseline_probe"), None)
    baseline_good = bool(
        baseline
        and baseline.completion == "complete"
        and all(op.success for op in baseline.operations)
    )
    if seed is not None and not seed.success:
        infrastructure_error = True
        finding(
            "BASELINE_SETUP_FAILED",
            "Baseline setup failed; no migration compatibility result.",
            error_kind=seed.error_kind,
            sqlstate=seed.sqlstate,
        )
    if baseline and not baseline_good:
        infrastructure_error = True
        finding(
            "BASELINE_CONTRACT_FAILED",
            "Deployed baseline is unverified; no migration compatibility result.",
        )
    operations = [op for receipt in experiments for op in receipt.operations]
    migrations = [step for receipt in experiments for step in receipt.migrations]
    declared_operations = {
        check_id(phase, contract.version, op.id): op
        for phase, contract in contract_phases(loaded)
        for op in contract.operations
    }
    if loaded.spec.rollout:
        for task in ("rollout", "rollback"):
            declared_operations.update(
                {item.check: item.operation for item in rollout_plan(loaded, task)}
            )
    applications = [result for receipt in experiments for result in receipt.applications]
    for receipt in experiments:
        for step, document in zip(receipt.migrations, loaded.migration_sql, strict=False):
            if not catalog_verified(step, document):
                finding(
                    "CATALOG_EVIDENCE_MISSING",
                    "Migration catalog facts are missing or disagree with the declared DDL.",
                    step_id=step.step_id,
                    phase=step.phase,
                )
            if step.catalog_after:
                for index in step.catalog_after.indexes:
                    if not index.valid:
                        findings.append(
                            Finding(
                                rule_id="INVALID_INDEX_REMAINS",
                                severity=Severity.WARNING,
                                explanation=(
                                    f"Invalid index {index.name} remains after {step.step_id}."
                                ),
                                phase=step.phase,
                                evidence=index.model_dump(mode="json"),
                            )
                        )
    for step in migrations:
        if step.committed:
            continue
        deterministic = bool(step.sqlstate and step.sqlstate[:2] in {"22", "23", "42"})
        confirmed |= baseline_good and deterministic
        infrastructure_error |= step.error_kind == "connection_error"
        finding(
            "MIGRATION_FAILED" if deterministic else "EXECUTION_INCONCLUSIVE",
            f"Migration {step.step_id} did not commit on {step.phase}.",
            step_id=step.step_id,
            phase=step.phase,
            transaction=step.transaction.value,
            executed=step.executed,
            statements=step.statements,
            sqlstate=step.sqlstate,
            error_kind=step.error_kind,
        )
    for op in operations:
        if op.success:
            continue
        declared = declared_operations[check_id(op.phase, op.version, op.operation_id)]
        deterministic = op.error_kind == "assertion_error" or bool(
            op.error_kind == "sql_error" and op.sqlstate and op.sqlstate[:2] in {"22", "23", "42"}
        )
        is_post = op.phase != "baseline" and not op.phase.startswith("rollout_baseline/")
        if not is_post:
            infrastructure_error = True
        confirmed |= baseline_good and is_post and declared.required and deterministic
        infrastructure_error |= op.error_kind == "connection_error"
        rule = (
            "BASELINE_CONTRACT_FAILED"
            if not is_post
            else "SEMANTIC_ASSERTION_FAILED"
            if op.error_kind == "assertion_error"
            else "DEPLOYED_SQL_ERROR"
            if deterministic and op.version == loaded.deployed_contract.version
            else "CANDIDATE_SQL_ERROR"
            if deterministic
            else "EXECUTION_INCONCLUSIVE"
        )
        findings.append(
            Finding(
                rule_id=rule,
                severity=Severity.ERROR if declared.required else Severity.WARNING,
                explanation=f"{op.phase}/{op.version}/{op.operation_id}: {op.error_kind}.",
                phase=op.phase,
                operation_id=op.operation_id,
                evidence={
                    "sql": declared.sql,
                    "sqlstate": op.sqlstate,
                    "assertions": [a.model_dump(mode="json") for a in op.assertions],
                },
            )
        )
    for receipt in experiments:
        app_baseline = next(
            (
                app
                for app in receipt.applications
                if app.phase in {"app_baseline", "app_rollback_baseline"}
            ),
            None,
        )
        for app in receipt.applications:
            if app.success:
                continue
            is_baseline = app.phase in {"app_baseline", "app_rollback_baseline"}
            deterministic = app.error_kind in {"assertion_error", "domain_error"} or bool(
                app.error_kind == "sql_error"
                and app.sqlstate
                and app.sqlstate[:2] in {"22", "23", "42"}
            )
            confirmed |= bool(
                baseline_good
                and app_baseline
                and app_baseline.success
                and not is_baseline
                and deterministic
            )
            infrastructure_error |= is_baseline or app.error_kind in {
                "process_error",
                "connection_error",
                "invalid_response",
            }
            rule = (
                "APPLICATION_BASELINE_FAILED"
                if is_baseline
                else "APPLICATION_DOMAIN_ERROR"
                if app.error_kind == "domain_error"
                else "APPLICATION_ASSERTION_FAILED"
                if app.error_kind == "assertion_error"
                else "APPLICATION_SQL_ERROR"
                if app.error_kind == "sql_error"
                else "APPLICATION_EXECUTION_ERROR"
            )
            findings.append(
                Finding(
                    rule_id=rule,
                    severity=Severity.ERROR,
                    phase=app.phase,
                    operation_id=app.probe_id,
                    explanation=f"{app.phase}/{app.version}/{app.probe_id}: {app.error_kind}.",
                    evidence=app.model_dump(mode="json"),
                )
            )
    if coverage.missing:
        finding(
            "EVIDENCE_MISSING",
            "Required checks have no recorded evidence.",
            missing=coverage.missing,
        )
    if infrastructure_error:
        finding(
            "INFRASTRUCTURE_ERROR", "The execution environment or baseline could not be verified."
        )
    if manifest.cleanup == CleanupStatus.FAILED:
        finding(
            "CLEANUP_FAILED",
            "Owned resources or cleanup bookkeeping remain unresolved.",
            errors=manifest.cleanup_errors,
        )
    complete = (
        not coverage.missing
        and not invalid
        and all(r.completion == "complete" for r in experiments)
    )
    completion = (
        Completion.INFRASTRUCTURE_ERROR
        if infrastructure_error
        else Completion.COMPLETE
        if complete
        else Completion.PARTIAL
    )
    verdict = Verdict.FAIL if confirmed else Verdict.INCONCLUSIVE
    if (
        complete
        and not infrastructure_error
        and not findings
        and all(op.success for op in operations)
        and manifest.cleanup == CleanupStatus.COMPLETE
    ):
        verdict = Verdict.PASS
    return RunResult(
        run_id=manifest.run_id,
        completion=completion,
        verdict=verdict,
        coverage=coverage,
        operations=operations,
        migrations=migrations,
        baseline=seed,
        template=accepted.template,
        branches=[
            BranchEvidence(
                database=r.database,
                phase="baseline" if r.task == "baseline_probe" else r.task,
                data_sha256=r.baseline.data_sha256,
            )
            for r in experiments
            if r.baseline and r.baseline.data_sha256
        ],
        findings=findings,
        phases=[phase for receipt in experiments for phase in receipt.phases],
        applications=applications,
        evidence_levels=["sql_contract"]
        + (["reference_application"] if any(app.http_status for app in applications) else []),
        cleanup=manifest.cleanup,
    )
