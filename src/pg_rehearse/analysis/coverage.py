"""Coverage is derived from accepted inputs and observed receipts, never claimed flags."""

from pg_rehearse.analysis.locks import lock_coverage
from pg_rehearse.config import LoadedConfig
from pg_rehearse.migration.catalog import catalog_verifications
from pg_rehearse.models import ContractSpec, Coverage
from pg_rehearse.rollout.apps import application_plan
from pg_rehearse.rollout.phases import rollout_plan
from pg_rehearse.worker_protocol import RehearsalEvidence
from pg_rehearse.workload.contracts import check_id


def contract_phases(loaded: LoadedConfig) -> list[tuple[str, ContractSpec]]:
    result: list[tuple[str, ContractSpec]] = [
        ("baseline", loaded.deployed_contract),
        ("post_deployed", loaded.deployed_contract),
    ]
    if loaded.candidate_contract:
        result.append(("post_candidate", loaded.candidate_contract))
    return result


def coverage_for(loaded: LoadedConfig, evidence: RehearsalEvidence) -> Coverage:
    required = ["setup/baseline", "template/sealed"]
    for phase, contract in contract_phases(loaded):
        required.append(f"clone/{phase}")
        if phase != "baseline":
            required.extend(f"migration/{phase}/{step.id}" for step in loaded.spec.migrations)
        required.extend(
            check_id(phase, contract.version, op.id) for op in contract.operations if op.required
        )
    if loaded.spec.rollout:
        for task in ("rollout", "rollback"):
            required.append(f"clone/{task}")
            required.extend(f"migration/{task}/{step.id}" for step in loaded.spec.migrations)
            plan = rollout_plan(loaded, task)
            required.extend(item.check for item in plan if item.operation.required)
            required.extend(
                f"phase/{phase}" for phase in dict.fromkeys(item.phase for item in plan)
            )
            if loaded.spec.applications:
                required.extend(
                    item.check for item in application_plan(loaded.spec.applications, task)
                )
    migration_tasks = ["post_deployed"] + (["post_candidate"] if loaded.candidate_contract else [])
    if loaded.spec.rollout:
        migration_tasks += ["rollout", "rollback"]
    if loaded.spec.contention:
        required.append("clone/contention")
        migration_tasks.append("contention")
        required.extend(f"migration/contention/{step.id}" for step in loaded.spec.migrations)
        required.extend(lock_coverage(None).required)
    required.extend(
        f"catalog/{task}/{step.id}" for task in migration_tasks for step in loaded.spec.migrations
    )
    completed = []
    if evidence.seed and evidence.seed.baseline and evidence.seed.baseline.success:
        completed.append("setup/baseline")
    if evidence.template and evidence.template.sealed:
        completed.append("template/sealed")
    for experiment in evidence.experiments:
        if experiment.task in {"benchmark", "plan_baseline", "plan_candidate"}:
            continue  # Advisory experiments report their own sample/plan coverage.
        phase = "baseline" if experiment.task == "baseline_probe" else experiment.task
        if experiment.baseline and experiment.baseline.success:
            completed.append(f"clone/{phase}")
        if experiment.task == "contention":
            completed.extend(lock_coverage(experiment.contention).completed)
        completed.extend(f"migration/{phase}/{step.step_id}" for step in experiment.migrations)
        completed.extend(
            f"catalog/{phase}/{step_id}"
            for step_id, verified in catalog_verifications(loaded, experiment.migrations).items()
            if verified
        )
        completed.extend(
            f"phase/{result.id}" for result in experiment.phases if result.completion == "complete"
        )
        completed.extend(
            f"application/{r.phase}/{r.actor}/{r.probe_id}" for r in experiment.applications
        )
        completed.extend(
            check_id(op.phase, op.version, op.operation_id) for op in experiment.operations
        )
    return Coverage(required=required, completed=completed)
