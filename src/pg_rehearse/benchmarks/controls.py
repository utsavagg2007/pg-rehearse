"""Unchanged-schema control checks use the same effect rule as the candidate pair."""

from pg_rehearse.models import BenchmarkSpec


def effect(before: float, after: float, spec: BenchmarkSpec) -> dict[str, float | bool | None]:
    ratio = after / before if before > 0 else None
    delta = after - before
    return {
        "delta_ms": delta,
        "ratio": ratio,
        "flagged": delta >= spec.absolute_ms and ratio is not None and ratio >= spec.ratio,
    }
