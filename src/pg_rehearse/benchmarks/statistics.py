"""Descriptive summaries; no confidence claim from correlated request samples."""

import math
from statistics import median
from typing import Any

from pg_rehearse.models import TimingSample


def summarize(samples: list[TimingSample]) -> dict[str, Any]:
    measured = [s for s in samples if not s.warmup]
    values = sorted(s.elapsed_ms for s in measured if s.success)
    total = sum(s.elapsed_ms for s in measured)
    center = median(values) if values else None
    errors = sum(not s.success for s in measured)
    timeouts = sum(
        s.sqlstate in {"57014", "55P03"} or s.error_kind == "operation_deadline" for s in measured
    )
    return {
        "attempted": len(measured),
        "successful": len(values),
        "warmups": sum(s.warmup for s in samples),
        "errors": errors,
        "timeouts": timeouts,
        "error_rate": errors / len(measured) if measured else None,
        "timeout_rate": timeouts / len(measured) if measured else None,
        "median_ms": center,
        "p95_ms": values[max(0, math.ceil(len(values) * 0.95) - 1)] if values else None,
        "min_ms": min(values) if values else None,
        "max_ms": max(values) if values else None,
        "mad_ms": median(abs(v - center) for v in values) if center is not None else None,
        "throughput_per_second": len(values) * 1000 / total if total else None,
    }
