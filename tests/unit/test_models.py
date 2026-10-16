import pytest
from pydantic import ValidationError

from pg_rehearse.errors import ExitCode
from pg_rehearse.models import (
    AssertionResult,
    CleanupStatus,
    Completion,
    ContractSpec,
    Coverage,
    Finding,
    OperationResult,
    RunResult,
    SemanticAssertions,
    Severity,
    Timeouts,
    Verdict,
)


def test_default_result_is_inconclusive() -> None:
    result = RunResult(run_id="example")
    assert result.verdict == Verdict.INCONCLUSIVE
    assert result.exit_code == ExitCode.INCONCLUSIVE


def test_missing_required_checks_cannot_pass() -> None:
    with pytest.raises(ValidationError, match="every required check"):
        RunResult(
            run_id="example",
            completion=Completion.COMPLETE,
            verdict=Verdict.PASS,
            coverage=Coverage(required=["baseline", "post-migration"], completed=["baseline"]),
            cleanup=CleanupStatus.COMPLETE,
        )


def test_empty_coverage_cannot_pass() -> None:
    with pytest.raises(ValidationError, match="every required check"):
        RunResult(
            run_id="example",
            completion=Completion.COMPLETE,
            verdict=Verdict.PASS,
            cleanup=CleanupStatus.COMPLETE,
        )


def test_cleanup_failure_cannot_pass() -> None:
    with pytest.raises(ValidationError, match="successful cleanup"):
        RunResult(
            run_id="example",
            completion=Completion.COMPLETE,
            verdict=Verdict.PASS,
            coverage=Coverage(required=["baseline"], completed=["baseline"]),
            cleanup=CleanupStatus.FAILED,
        )


def test_failed_assertion_cannot_pass() -> None:
    with pytest.raises(ValidationError, match="failed operations or assertions"):
        RunResult(
            run_id="example",
            completion=Completion.COMPLETE,
            verdict=Verdict.PASS,
            coverage=Coverage(required=["baseline"], completed=["baseline"]),
            cleanup=CleanupStatus.COMPLETE,
            operations=[
                OperationResult(
                    operation_id="get-user",
                    version="v1",
                    phase="baseline",
                    success=True,
                    assertions=[AssertionResult(name="rows", passed=False)],
                )
            ],
        )


def test_partial_run_can_still_confirm_failure() -> None:
    result = RunResult(
        run_id="example",
        completion=Completion.PARTIAL,
        verdict=Verdict.FAIL,
        findings=[
            Finding(
                rule_id="removed-column",
                severity=Severity.ERROR,
                explanation="The deployed query references the removed column.",
                evidence={"sqlstate": "42703"},
            )
        ],
    )
    assert result.exit_code == ExitCode.COMPATIBILITY_FAILURE
    restored = RunResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_infrastructure_failure_is_separate_from_verdict() -> None:
    result = RunResult(run_id="example", completion=Completion.INFRASTRUCTURE_ERROR)
    assert result.verdict == Verdict.INCONCLUSIVE
    assert result.exit_code == ExitCode.INFRASTRUCTURE_ERROR


def test_complete_passing_result_returns_success() -> None:
    result = RunResult(
        run_id="example",
        completion=Completion.COMPLETE,
        verdict=Verdict.PASS,
        coverage=Coverage(required=["baseline"], completed=["baseline"]),
        cleanup=CleanupStatus.COMPLETE,
        operations=[
            OperationResult(
                operation_id="get-user",
                version="v1",
                phase="baseline",
                success=True,
                assertions=[AssertionResult(name="rows", passed=True)],
            )
        ],
    )
    assert result.exit_code == ExitCode.SUCCESS


@pytest.mark.parametrize("value", [0, -1, "5000", True])
def test_statement_timeout_is_a_positive_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        Timeouts.model_validate({"statement_ms": value})


def test_contract_operation_ids_are_unique() -> None:
    operation = {"id": "query", "sql": "SELECT 1;", "expect": {"row_count": 1}}
    with pytest.raises(ValidationError, match="unique"):
        ContractSpec.model_validate({"version": "v1", "operations": [operation, operation]})


@pytest.mark.parametrize(
    "expectations",
    [{}, {"rows": [[1]], "row_count": 2}, {"columns": ["id", "name"], "rows": [[1]]}],
)
def test_result_expectations_are_consistent(expectations: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SemanticAssertions.model_validate(expectations)


def test_failed_application_probe_cannot_be_wrapped_in_a_pass() -> None:
    from pg_rehearse.models import ApplicationResult

    with pytest.raises(ValidationError, match="failed application probes"):
        RunResult(
            run_id="example",
            completion=Completion.COMPLETE,
            verdict=Verdict.PASS,
            coverage=Coverage(required=["application"], completed=["application"]),
            cleanup=CleanupStatus.COMPLETE,
            applications=[
                ApplicationResult(
                    probe_id="user.get",
                    phase="app_candidate",
                    version="candidate",
                    actor="candidate",
                    revision="test",
                    success=False,
                )
            ],
        )


@pytest.mark.parametrize(
    "claim", [{"committed": "true"}, {"backend_pid": "123"}, {"backend_pid": True}]
)
def test_session_and_commit_wire_facts_are_strict(claim: dict) -> None:
    with pytest.raises(ValidationError):
        OperationResult(
            operation_id="query", version="v1", phase="mixed_versions", success=True, **claim
        )
