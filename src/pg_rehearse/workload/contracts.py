"""Stable, phase-qualified contract identities and expected assertion coverage."""

from pg_rehearse.models import (
    ContractSpec,
    Coverage,
    OperationResult,
    OperationSpec,
    SemanticAssertions,
)


def check_id(phase: str, version: str, operation_id: str) -> str:
    return f"{phase}/{version}/{operation_id}"


def assertion_names(expect: SemanticAssertions) -> list[str]:
    return [name for name in ("columns", "rows", "row_count") if getattr(expect, name) is not None]


def contract_coverage(
    contract: ContractSpec, phase: str, results: list[OperationResult]
) -> Coverage:
    return Coverage(
        required=[
            check_id(phase, contract.version, op.id) for op in contract.operations if op.required
        ],
        completed=[
            check_id(result.phase, result.version, result.operation_id) for result in results
        ],
    )


def verify_operation(expected: OperationSpec, result: OperationResult) -> None:
    """Validate semantic receipt facts against the accepted operation declaration."""
    from pg_rehearse.workload.assertions import encoded, summarize

    if result.error is not None:
        raise ValueError("Unsafe error text")
    if result.error_kind not in (None, "assertion_error"):
        if result.success or result.assertions or result.committed:
            raise ValueError("Failed execution cannot claim assertions or a commit")
        return
    if result.sqlstate or [a.name for a in result.assertions] != assertion_names(expected.expect):
        raise ValueError("Missing or duplicate semantic assertions")
    for assertion in result.assertions:
        if encoded(assertion.expected) != encoded(
            summarize(getattr(expected.expect, assertion.name))
        ) or assertion.passed != (encoded(assertion.expected) == encoded(assertion.actual)):
            raise ValueError("Inconsistent semantic assertion evidence")
    passed = all(a.passed for a in result.assertions)
    if result.success != passed or result.error_kind != (None if passed else "assertion_error"):
        raise ValueError("Operation success disagrees with assertions")
