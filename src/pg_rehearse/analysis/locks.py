"""Interpret sampled waits without turning absent observations into lock freedom."""

from pg_rehearse.models import ContentionResult, Coverage


def observed_wait(result: ContentionResult, actor: str, blocker: str) -> bool:
    pid, blocking = result.actor_pids.get(actor), result.actor_pids.get(blocker)
    return bool(
        pid
        and blocking
        and any(
            any(
                a.pid == pid and a.wait_event_type == "Lock" and blocking in a.blockers
                for a in sample.activity
            )
            and any(lock.pid == pid and not lock.granted for lock in sample.locks)
            for sample in result.samples
        )
    )


def lock_coverage(result: ContentionResult | None) -> Coverage:
    required = [
        "contention/blocker",
        "contention/observation",
        "contention/migration_wait",
        "contention/probe",
        "contention/released",
    ]
    completed = []
    if result:
        if result.blocker and result.blocker.success:
            completed.append("contention/blocker")
        if result.samples and not result.observer_error:
            completed.append("contention/observation")
        if observed_wait(result, "migrator", "blocker"):
            completed.append("contention/migration_wait")
        if result.probe:
            completed.append("contention/probe")
        if result.blocker_released:
            completed.append("contention/released")
    return Coverage(required=required, completed=completed)


def lock_summary(result: ContentionResult) -> dict[str, object]:
    waiting = [
        s.elapsed_ms for s in result.samples if any(a.wait_event_type == "Lock" for a in s.activity)
    ]
    return {
        "migration_wait_observed": observed_wait(result, "migrator", "blocker"),
        "probe_waits_behind_migration": observed_wait(result, "probe", "migrator"),
        "sample_count": len(result.samples),
        "missed_polls": result.missed_polls,
        "first_wait_ms": min(waiting) if waiting else None,
        "last_wait_ms": max(waiting) if waiting else None,
        "sampled_span_ms": max(waiting) - min(waiting) if waiting else None,
        "hold_ms": result.hold_ms,
        "poll_ms": result.poll_ms,
        "observer_overhead_ms": sum(s.overhead_ms for s in result.samples),
        "scope": (
            "Deliberately held transaction; sampled span is not exact wait time "
            "or production outage."
        ),
    }
