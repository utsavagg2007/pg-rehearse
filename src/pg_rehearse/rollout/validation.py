"""Pure rollout and application receipt validation; no live connections."""

from typing import TYPE_CHECKING

from pg_rehearse.models import Coverage
from pg_rehearse.rollout.apps import application_plan
from pg_rehearse.rollout.orders_app import revision
from pg_rehearse.rollout.phases import phase_results, rollout_plan
from pg_rehearse.worker_protocol import verify_migrations
from pg_rehearse.workload.assertions import encoded, summarize
from pg_rehearse.workload.contracts import check_id, verify_operation

if TYPE_CHECKING:
    from pg_rehearse.config import LoadedConfig
    from pg_rehearse.worker_protocol import WorkerEvidence, WorkerRequest


def rollout_coverage(loaded: "LoadedConfig", evidence: "WorkerEvidence") -> Coverage:
    plan = rollout_plan(loaded, evidence.task)
    required = [item.check for item in plan if item.operation.required]
    required += [f"phase/{phase}" for phase in dict.fromkeys(item.phase for item in plan)]
    completed = [check_id(op.phase, op.version, op.operation_id) for op in evidence.operations]
    completed += [
        f"phase/{phase.id}" for phase in evidence.phases if phase.completion == "complete"
    ]
    if loaded.spec.applications:
        required += [
            item.check for item in application_plan(loaded.spec.applications, evidence.task)
        ]
        completed += [
            f"application/{r.phase}/{r.actor}/{r.probe_id}" for r in evidence.applications
        ]
    return Coverage(required=required, completed=completed)


def verify_rollout(
    loaded: "LoadedConfig", request: "WorkerRequest", evidence: "WorkerEvidence"
) -> None:
    plan = rollout_plan(loaded, request.task)
    ready = verify_migrations(loaded, evidence.migrations, request.task)
    if len(evidence.operations) > len(plan):
        raise ValueError("Unexpected rollout operations")
    actors: dict[str, int] = {}
    for item, result in zip(plan, evidence.operations, strict=False):
        if (result.phase, result.version, result.operation_id, result.actor) != (
            item.phase,
            item.version,
            item.operation.id,
            item.actor,
        ) or not result.backend_pid:
            raise ValueError("Wrong rollout operation or session identity")
        if not ready and not item.phase.startswith("rollout_baseline/"):
            raise ValueError("Post-migration probes require committed migrations")
        verify_operation(item.operation, result)
        if result.committed != (item.commit and result.success):
            raise ValueError("Rollout writes require confirmed commit evidence")
        if item.actor.startswith("old_"):
            if item.actor in actors and actors[item.actor] != result.backend_pid:
                raise ValueError("Persistent old session was replaced across DDL")
            actors[item.actor] = result.backend_pid
        if item.actor == "fresh_old" and result.backend_pid in actors.values():
            raise ValueError("Fresh old session reused a persistent backend")
    if evidence.phases != phase_results(plan, evidence.operations):
        raise ValueError("Phase barriers disagree with observed operations")
    if evidence.applications and not loaded.spec.applications:
        raise ValueError("Undeclared application evidence")
    if loaded.spec.applications:
        expected_apps = application_plan(loaded.spec.applications, request.task)
        if len(evidence.applications) > len(expected_apps):
            raise ValueError("Unexpected application probes")
        sessions: dict[str, tuple[int, int]] = {}
        for expected, app_result in zip(expected_apps, evidence.applications, strict=False):
            if (
                app_result.probe_id,
                app_result.phase,
                app_result.version,
                app_result.actor,
                app_result.revision,
            ) != (
                expected.probe_id,
                expected.phase,
                expected.version,
                expected.actor,
                revision(expected.version),
            ):
                raise ValueError("Wrong application identity or revision")
            if not ready and app_result.phase not in {"app_baseline", "app_rollback_baseline"}:
                raise ValueError("Application post-probe preceded migration commit")
            if app_result.process_id and app_result.backend_pid:
                identity = (app_result.process_id, app_result.backend_pid)
                if app_result.actor in sessions and sessions[app_result.actor] != identity:
                    raise ValueError("Application process or pool changed during the experiment")
                if (
                    app_result.actor == "fresh_old"
                    and "old" in sessions
                    and (identity[0] == sessions["old"][0] or identity[1] == sessions["old"][1])
                ):
                    raise ValueError("Fresh application reused the old process or pool")
                sessions[app_result.actor] = identity
            if app_result.error_kind not in (None, "assertion_error"):
                if app_result.success or app_result.assertions:
                    raise ValueError("Application error cannot claim assertions")
                continue
            if (
                not app_result.process_id
                or not app_result.backend_pid
                or app_result.http_status != expected.status
                or app_result.sqlstate
                or len(app_result.assertions) != 1
            ):
                raise ValueError("Missing successful application evidence")
            assertion = app_result.assertions[0]
            passed = encoded(assertion.expected) == encoded(assertion.actual)
            if (
                assertion.name != "response"
                or encoded(assertion.expected) != encoded(summarize(expected.expected))
                or assertion.passed != passed
                or app_result.success != passed
                or app_result.error_kind != (None if passed else "assertion_error")
            ):
                raise ValueError("Inconsistent application semantic assertion")
    if evidence.coverage != rollout_coverage(loaded, evidence):
        raise ValueError("Rollout coverage disagrees with recorded evidence")
    complete = ready and len(evidence.operations) == len(plan) and not evidence.coverage.missing
    if (evidence.completion == "complete") != complete:
        raise ValueError("Missing rollout evidence cannot complete an experiment")
