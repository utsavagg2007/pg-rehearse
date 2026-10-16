"""Portable Markdown containing the same final status and evidence as JSON."""

import html
import json
import re
from pathlib import Path

from pg_rehearse.models import RunResult
from pg_rehearse.report.json_report import atomic_text


def plain(value: str) -> str:
    value = html.escape(value.replace("\n", " "))
    return re.sub(r"([\\`*_\[\]~])", r"\\\1", value)


def block(value: str, language: str = "") -> str:
    fence = "`" * max(3, 1 + max((len(s) for s in re.findall(r"`+", value)), default=0))
    return f"{fence}{language}\n{value}\n{fence}"


def render_markdown(result: RunResult) -> str:
    lines = [
        f"# Rehearsal {plain(result.run_id)}",
        "",
        f"Verdict: **{result.verdict.value}**; completion: {result.completion.value}; "
        f"cleanup: {result.cleanup.value}; exit: {result.exit_code}.",
        "",
        f"Required checks: {len(result.coverage.required)}; "
        f"missing: {len(result.coverage.missing)}.",
        "",
    ]
    if result.coverage.missing:
        lines += ["Missing: " + ", ".join(plain(s) for s in result.coverage.missing), ""]
    lines += ["Evidence: " + ", ".join(plain(level) for level in result.evidence_levels), ""]
    for phase in result.phases:
        lines += [f"- Phase {plain(phase.id)}: {phase.completion}; barrier {phase.barrier}."]
    for app in result.applications:
        lines += ["", block(app.model_dump_json(indent=2), "json"), ""]
    for step in result.migrations:
        lines += [
            f"- Migration {plain(step.phase)}/{plain(step.step_id)}: "
            f"{'committed' if step.committed else 'failed'} ({step.transaction.value}); "
            f"SQLSTATE {step.sqlstate or 'none'}; "
            f"executed {step.executed}/{step.statements}."
        ]
        lines += [
            "",
            block(
                json.dumps(
                    {
                        "before": step.catalog_before.model_dump(mode="json")
                        if step.catalog_before
                        else None,
                        "after": step.catalog_after.model_dump(mode="json")
                        if step.catalog_after
                        else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "json",
            ),
            "",
        ]
    for op in result.operations:
        lines += [
            f"- {plain(op.phase)}/{plain(op.version)}/{plain(op.operation_id)}: "
            f"{'OK' if op.success else op.error_kind}; SQLSTATE {op.sqlstate or 'none'}."
        ]
        if op.assertions:
            lines += [
                "",
                block(
                    json.dumps(
                        [a.model_dump(mode="json") for a in op.assertions],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "json",
                ),
                "",
            ]
    for finding in result.findings:
        lines += [
            "",
            f"## {plain(finding.rule_id)}",
            "",
            plain(finding.explanation),
            "",
            block(json.dumps(finding.evidence, ensure_ascii=False, indent=2), "json"),
        ]
    lines += [
        "",
        "Scope: declared SQL contracts, optional schema-first rollout and optional reference HTTP "
        "application probes on disposable PostgreSQL 17. In-migration traffic, contention, "
        "performance and production equivalence are not covered.",
        "",
    ]
    return "\n".join(lines)


def write_markdown(path: Path, result: RunResult) -> None:
    atomic_text(path, render_markdown(result))
