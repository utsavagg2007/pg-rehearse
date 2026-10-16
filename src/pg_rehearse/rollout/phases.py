"""Explicit schema-first plan shared by execution, validation, coverage and analysis."""

from dataclasses import dataclass
from itertools import groupby
from typing import TYPE_CHECKING

from pg_rehearse.migration.preflight import bound_sql_for_parse, parse_document
from pg_rehearse.models import OperationResult, OperationSpec, PhaseResult
from pg_rehearse.workload.contracts import check_id

if TYPE_CHECKING:
    from pg_rehearse.config import LoadedConfig


@dataclass(frozen=True)
class PlannedOperation:
    operation: OperationSpec
    version: str
    phase: str
    actor: str
    commit: bool = False

    @property
    def check(self) -> str:
        return check_id(self.phase, self.version, self.operation.id)


def write_operation(operation: OperationSpec) -> bool:
    parsed = parse_document(
        bound_sql_for_parse(operation.sql, operation.parameters, operation.id), operation.id
    )
    return parsed.statements[0].kind != "SelectStmt"


def rollout_plan(loaded: "LoadedConfig", task: str) -> list[PlannedOperation]:
    rollout = loaded.spec.rollout
    candidate = loaded.candidate_contract
    if rollout is None or candidate is None or task not in {"rollout", "rollback"}:
        raise ValueError("Missing rollout declaration")
    plan: list[PlannedOperation] = []
    if task == "rollout":
        for kind in ("rollout_baseline", "persistent_old"):
            for index in range(rollout.persistent_old_sessions):
                actor = f"old_{index + 1}"
                plan.extend(
                    PlannedOperation(op, loaded.deployed_contract.version, f"{kind}/{actor}", actor)
                    for op in loaded.deployed_contract.operations
                )
        plan.extend(
            PlannedOperation(op, loaded.deployed_contract.version, "fresh_old", "fresh_old")
            for op in loaded.deployed_contract.operations
        )
    for phase in rollout.phases:
        if (task == "rollback") != (phase.id == "app_rollback"):
            continue
        for operation in phase.operations:
            contract = loaded.deployed_contract if operation.actor == "deployed" else candidate
            plan.append(
                PlannedOperation(
                    operation,
                    contract.version,
                    phase.id,
                    operation.actor,
                    write_operation(operation),
                )
            )
    return plan


def phase_results(
    plan: list[PlannedOperation], results: list[OperationResult]
) -> list[PhaseResult]:
    phases = []
    for phase, group in groupby(plan, key=lambda item: item.phase):
        expected = list(group)
        observed = [result for result in results if result.phase == phase]
        if not observed:
            continue
        complete = len(observed) == len(expected)
        committed = complete and all(
            result.success and result.committed == item.commit
            for item, result in zip(expected, observed, strict=False)
        )
        phases.append(
            PhaseResult(
                id=phase,
                checks=[check_id(r.phase, r.version, r.operation_id) for r in observed],
                completion="complete" if complete else "partial",
                barrier=(
                    "baseline_verified"
                    if phase.startswith("rollout_baseline/")
                    else "committed_writes"
                    if committed and phase in {"mixed_versions", "candidate_only", "app_rollback"}
                    else "migration_committed"
                ),
            )
        )
    return phases
