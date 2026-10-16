from dataclasses import replace

import pytest

from pg_rehearse.evaluation.cases import CASES, case_errors
from pg_rehearse.models import CleanupStatus, RunResult, Verdict


def passing_result() -> RunResult:
    return RunResult(
        run_id="a" * 32,
        completion="complete",
        verdict="pass",
        cleanup="complete",
        coverage={"required": ["check"], "completed": ["check"]},
    )


def test_case_labels_cover_supported_families_and_uncertainty() -> None:
    assert len({case.id for case in CASES}) == len(CASES)
    assert {case.label for case in CASES} == {
        "compatible",
        "incompatible",
        "unsupported",
        "inconclusive",
    }
    assert not case_errors(CASES[0], passing_result(), 0)
    unsupported = next(c for c in CASES if c.label == "unsupported")
    assert not case_errors(unsupported, None, 4)
    assert case_errors(unsupported, passing_result(), 0)
    assert case_errors(unsupported, None, 3)


@pytest.mark.parametrize(
    "change", ["missing", "false_pass", "false_failure", "cleanup", "coverage", "rule", "sqlstate"]
)
def test_evaluation_never_counts_wrong_or_incomplete_evidence_as_correct(change: str) -> None:
    case = CASES[0]
    result = passing_result()
    if change == "missing":
        assert case_errors(case, None, 0)
        return
    if change == "false_pass":
        case = next(c for c in CASES if c.label == "incompatible")
    elif change == "false_failure":
        result.verdict = Verdict.INCONCLUSIVE
    elif change == "cleanup":
        result.cleanup = CleanupStatus.FAILED
    elif change == "coverage":
        result.coverage.completed = []
    elif change == "rule":
        case = replace(case, rule="MISSING_RULE")
    else:
        case = replace(case, sqlstate="42703")
    assert case_errors(case, result, result.exit_code)
