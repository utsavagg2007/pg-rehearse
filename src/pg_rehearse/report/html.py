"""Self-contained, script-free HTML over the canonical saved result."""

import html
import json
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from pg_rehearse.models import RunResult
from pg_rehearse.report.json_report import atomic_text


def text(value: object) -> str:
    return html.escape(str(value) if value is not None else "Not recorded", quote=True)


def details(label: str, value: Any) -> str:
    return (
        f"<details><summary>{text(label)}</summary><pre>"
        + text(json.dumps(value, ensure_ascii=True, indent=2))
        + "</pre></details>"
    )


def table(caption: str, headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return '<p class="note">Not evaluated in this run.</p>'
    return (
        '<div class="table-wrap" tabindex="0" role="region" aria-label="'
        + text(caption)
        + '"><table><caption>'
        + text(caption)
        + "</caption><thead><tr>"
        + "".join(f'<th scope="col">{text(h)}</th>' for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{text(c)}</td>" for c in row) + "</tr>" for row in rows)
        + "</tbody></table></div>"
    )


def render_html(result: RunResult) -> str:
    sections: list[tuple[str, str, str]] = []
    headings = {
        "pass": "Declared compatibility checks passed",
        "fail": "Compatibility failure observed",
        "inconclusive": "Required evidence is inconclusive",
    }
    cards = (
        '<dl class="cards">'
        + "".join(
            f'<div class="card"><dt>{text(label)}</dt><dd>{value}</dd></div>'
            for label, value in (
                (
                    "Verdict",
                    f'<span class="badge {result.verdict.value}">'
                    f"{text(result.verdict.value)}</span>",
                ),
                ("Completion", text(result.completion.value)),
                ("Cleanup", text(result.cleanup.value)),
                (
                    "Required coverage",
                    f"{len(set(result.coverage.required) & set(result.coverage.completed))} / "
                    f"{len(result.coverage.required)}",
                ),
            )
        )
        + "</dl>"
    )
    findings = (
        table(
            "Findings",
            ["Severity", "Rule", "Phase / operation", "Observed outcome"],
            [
                [
                    f.severity.value,
                    f.rule_id,
                    f"{f.phase or '—'} / {f.operation_id or '—'}",
                    f.explanation,
                ]
                for f in result.findings
            ],
        )
        if result.findings
        else "<p>No findings recorded. Check required coverage and completion separately.</p>"
    )
    findings += "".join(details(f.rule_id + " evidence", f.evidence) for f in result.findings)
    sections.append(("findings", "Findings", findings))
    coverage = "<p>Evidence levels: " + text(", ".join(result.evidence_levels)) + "</p>"
    coverage += (
        "<p><strong>Missing required checks:</strong></p><ul>"
        + "".join("<li>" + text(c) + "</li>" for c in result.coverage.missing)
        + "</ul>"
        if result.coverage.missing
        else "<p>No required checks are missing.</p>"
    )
    coverage += details("Required and completed check IDs", result.coverage.model_dump(mode="json"))
    sections.append(("coverage", "Coverage and uncertainty", coverage))
    phases = table(
        "Deployment phases",
        ["Phase", "Completion", "Observed barrier"],
        [[p.id, p.completion, p.barrier] for p in result.phases],
    )
    phases += table(
        "SQL probes",
        ["Phase", "Version / actor", "Operation", "Result", "SQLSTATE", "Committed"],
        [
            [
                o.phase,
                f"{o.version} / {o.actor or '—'}",
                o.operation_id,
                "passed" if o.success else o.error_kind,
                o.sqlstate or "—",
                o.committed,
            ]
            for o in result.operations
        ],
    )
    phases += table(
        "HTTP application probes",
        ["Phase", "Version / actor", "Probe", "Result", "HTTP", "SQLSTATE"],
        [
            [
                a.phase,
                f"{a.version} / {a.actor}",
                a.probe_id,
                "passed" if a.success else a.error_kind,
                a.http_status,
                a.sqlstate or "—",
            ]
            for a in result.applications
        ],
    )
    phases += details(
        "SQL assertions and application observations",
        {
            "operations": [o.model_dump(mode="json") for o in result.operations],
            "applications": [a.model_dump(mode="json") for a in result.applications],
        },
    )
    sections.append(("phases", "Phases and probes", phases))
    migrations = table(
        "Migration execution",
        ["Phase", "Step", "Mode", "Result", "Executed", "SQLSTATE"],
        [
            [
                m.phase,
                m.step_id,
                m.transaction.value,
                "committed" if m.committed else m.error_kind,
                f"{m.executed}/{m.statements}",
                m.sqlstate or "—",
            ]
            for m in result.migrations
        ],
    )
    migrations += details(
        "Migration identities and catalog snapshots",
        [m.model_dump(mode="json") for m in result.migrations],
    )
    sections.append(("migrations", "Migrations", migrations))
    locks = (
        "<p>Controlled sampling; missing samples do not prove absence of waits.</p>"
        + details(
            "Actor timeline, samples, deadlines and release",
            result.contention.model_dump(mode="json"),
        )
        if result.contention
        else "<p>Controlled contention was not evaluated.</p>"
    )
    sections.append(("locks", "Lock observations", locks))
    timings = table(
        "Advisory performance",
        ["Operation", "Status", "Median p95 delta (ms)", "Median ratio"],
        [
            [
                p.get("operation_id"),
                p.get("status"),
                p.get("median_delta_ms"),
                p.get("median_ratio"),
            ]
            for p in result.performance
        ],
    )
    timings += (
        '<p class="note">Advisory only. Insufficient or noisy samples '
        "are not a performance pass.</p>"
    )
    timings += details("Quality gates, trial effects and unchanged controls", result.performance)
    timings += details("Benchmark arms, environment, summaries and raw timings", result.benchmarks)
    sections.append(("performance", "Performance (advisory)", timings))
    plans = table(
        "Diagnostic plans",
        ["Operation", "Availability", "Structure changed"],
        [
            [p.get("operation_id"), p.get("status"), p.get("structure_changed")]
            for p in result.plans
        ],
    )
    plans += (
        '<p class="note">Plan changes are informational. '
        "Raw private plan receipts are not embedded.</p>"
    )
    plans += details("Normalized plan structure and metrics", result.plans)
    sections.append(("plans", "Query plans", plans))
    sections.append(
        (
            "environment",
            "Environment and baseline",
            details(
                "Recorded environment and clone identities",
                {
                    "environment": result.environment,
                    "baseline": result.baseline.model_dump(mode="json")
                    if result.baseline
                    else None,
                    "template": result.template.model_dump(mode="json")
                    if result.template
                    else None,
                    "branches": [b.model_dump(mode="json") for b in result.branches],
                },
            ),
        )
    )
    template = Template(
        files("pg_rehearse.report").joinpath("templates/report.html").read_text(encoding="utf-8")
    )
    return template.substitute(
        title=text(f"pg-rehearse {result.run_id} — {result.verdict.value}"),
        heading=text(headings[result.verdict.value]),
        run_id=text(result.run_id),
        scope=(
            "Evidence for the declared SQL contracts and any enabled rollout, "
            "application or observation experiments."
        ),
        navigation="".join(f'<a href="#{key}">{text(label)}</a>' for key, label, _ in sections),
        content=cards
        + "".join(
            f'<section id="{key}" aria-labelledby="{key}-title">'
            f'<h2 id="{key}-title">{text(label)}</h2>{body}</section>'
            for key, label, body in sections
        ),
    )


def write_html(path: Path, result: RunResult) -> None:
    atomic_text(path, render_html(result))
