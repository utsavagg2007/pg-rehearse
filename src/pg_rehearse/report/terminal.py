"""Concise terminal rendering of the final, post-cleanup result."""

from rich.console import Console

from pg_rehearse.models import RunResult


def render_terminal(result: RunResult, console: Console) -> None:
    console.print(
        f"Rehearsal {result.run_id}: {result.verdict.value}",
        markup=False,
    )
    console.print(f"Completion: {result.completion.value}; cleanup {result.cleanup.value}")
    console.print(
        f"Required checks: {len(result.coverage.required)}; missing: {len(result.coverage.missing)}"
    )
    console.print("Evidence: " + ", ".join(result.evidence_levels), markup=False)
    if result.contention:
        console.print(
            f"Contention: {len(result.contention.samples)} samples; "
            f"blocker released {result.contention.blocker_released}"
        )
    for outcome in result.performance:
        console.print(
            f"Performance {outcome.get('operation_id', 'Not recorded')}: "
            f"{outcome.get('status', 'Not recorded')} (advisory)",
            markup=False,
        )
    for plan in result.plans:
        console.print(
            f"Plan {plan.get('operation_id', 'Not recorded')}: "
            f"{plan.get('status', 'Not recorded')}; "
            f"structure changed {plan.get('structure_changed', 'Not recorded')}",
            markup=False,
        )
    for phase in result.phases:
        console.print(
            f"Phase {phase.id}: {phase.completion}; barrier {phase.barrier}", markup=False
        )
    for app in result.applications:
        console.print(
            f"HTTP {app.phase}/{app.actor}/{app.probe_id}: "
            f"{'OK' if app.success else app.error_kind}; status {app.http_status}; "
            f"SQLSTATE {app.sqlstate or 'none'}",
            markup=False,
        )
    for step in result.migrations:
        console.print(
            f"{step.phase}/{step.step_id}: "
            f"{'committed' if step.committed else step.error_kind}; "
            f"SQLSTATE {step.sqlstate or 'none'}",
            markup=False,
        )
    for op in result.operations:
        failed = ", ".join(a.name for a in op.assertions if not a.passed)
        console.print(
            f"{op.phase}/{op.version}/{op.operation_id}: "
            f"{'OK' if op.success else op.error_kind}"
            f"{'; SQLSTATE ' + op.sqlstate if op.sqlstate else ''}"
            f"{'; ' + failed if failed else ''}",
            markup=False,
        )
    for finding in result.findings:
        console.print(f"{finding.rule_id}:", markup=False)
        console.print(finding.explanation, markup=False)
