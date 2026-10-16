"""Application rollback keeps the migrated schema and committed candidate data."""

from pg_rehearse.models import OperationResult
from pg_rehearse.rollout.phases import PlannedOperation
from pg_rehearse.workload.contracts import check_id


def committed_pairs_complete(plan: list[PlannedOperation], results: list[OperationResult]) -> bool:
    return len(plan) == len(results) and all(
        check_id(result.phase, result.version, result.operation_id) == item.check
        and result.success
        and result.committed == item.commit
        for item, result in zip(plan, results, strict=True)
    )
