"""Fixed expectations compared with real evidence, never a verdict source."""

from dataclasses import dataclass
from typing import Literal

from pg_rehearse.models import RunResult


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    config: str
    label: Literal["compatible", "incompatible", "unsupported", "inconclusive"]
    exit_code: int
    completion: str | None
    verdict: str | None
    missing_coverage: bool = False
    rule: str | None = None
    sqlstate: str | None = None


CASES = (
    EvaluationCase("index-create", "control.yml", "compatible", 0, "complete", "pass"),
    EvaluationCase("index-drop", "index-drop.yml", "compatible", 0, "complete", "pass"),
    EvaluationCase("check-add", "check-compatible.yml", "compatible", 0, "complete", "pass"),
    EvaluationCase(
        "rename",
        "rehearsal.yml",
        "incompatible",
        1,
        "complete",
        "fail",
        rule="DEPLOYED_SQL_ERROR",
        sqlstate="42703",
    ),
    EvaluationCase(
        "check-write",
        "check-tightening.yml",
        "incompatible",
        1,
        "complete",
        "fail",
        rule="DEPLOYED_SQL_ERROR",
        sqlstate="23514",
    ),
    EvaluationCase("unsupported-add-column", "unsupported.yml", "unsupported", 4, None, None),
    EvaluationCase(
        "lock-deadline",
        "contention-timeout.yml",
        "inconclusive",
        4,
        "complete",
        "inconclusive",
        rule="EXECUTION_INCONCLUSIVE",
        sqlstate="55P03",
    ),
)


def case_errors(case: EvaluationCase, result: RunResult | None, exit_code: int) -> list[str]:
    errors = []
    if exit_code != case.exit_code:
        errors.append(f"exit: expected {case.exit_code}, observed {exit_code}")
    if result is None:
        if case.label != "unsupported":
            errors.append("required run evidence is missing")
        return errors
    if case.label == "unsupported":
        errors.append("unsupported input produced a run result")
    for field, expected, observed in (
        ("completion", case.completion, result.completion.value),
        ("verdict", case.verdict, result.verdict.value),
        ("cleanup", "complete", result.cleanup.value),
        ("missing coverage", case.missing_coverage, bool(result.coverage.missing)),
    ):
        if observed != expected:
            errors.append(f"{field}: expected {expected}, observed {observed}")
    if case.rule and not any(f.rule_id == case.rule for f in result.findings):
        errors.append(f"required finding missing: {case.rule}")
    sqlstates = {op.sqlstate for op in result.operations} | {m.sqlstate for m in result.migrations}
    if case.sqlstate and case.sqlstate not in sqlstates:
        errors.append(f"required SQLSTATE missing: {case.sqlstate}")
    return errors
