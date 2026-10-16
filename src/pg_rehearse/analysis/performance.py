"""Pure, advisory trial comparisons with explicit sample and A/A quality gates."""

from statistics import median
from typing import Any

from pg_rehearse.benchmarks.controls import effect
from pg_rehearse.benchmarks.statistics import summarize
from pg_rehearse.config import LoadedConfig
from pg_rehearse.worker_protocol import WorkerEvidence


def compare_performance(
    loaded: LoadedConfig, receipts: list[WorkerEvidence]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    spec = loaded.spec.benchmark
    if spec is None:
        return [], []
    arms = []
    for receipt in receipts:
        if receipt.task != "benchmark" or receipt.benchmark is None:
            continue
        arms.append(
            {
                "trial": receipt.trial,
                "arm": receipt.arm,
                "database": receipt.database,
                "baseline_sha256": receipt.baseline.data_sha256 if receipt.baseline else None,
                **receipt.benchmark.model_dump(mode="json"),
                "summaries": {
                    name: summarize(
                        [s for s in receipt.benchmark.samples if s.operation_id == name]
                    )
                    for name in spec.operations
                },
            }
        )
    outcomes = []
    for name in spec.operations:
        pairs: list[dict[str, Any]] = []
        sufficient = spec.trials == 5 and spec.samples >= 200 and spec.warmups > 0
        for trial in range(1, spec.trials + 1):
            group = {a["arm"]: a for a in arms if a["trial"] == trial}
            if set(group) != {"baseline", "candidate", "control_a", "control_b"}:
                sufficient = False
                continue
            summaries = {key: arm["summaries"][name] for key, arm in group.items()}
            quality = all(
                s["successful"] == spec.samples and s["warmups"] == spec.warmups
                for s in summaries.values()
            )
            quality &= all(
                all(s["success"] for s in a["samples"] if s["operation_id"] == name)
                for a in group.values()
            )
            quality &= all(
                a["environment"] == group["baseline"]["environment"] for a in group.values()
            )
            sufficient &= quality
            if any(s["p95_ms"] is None for s in summaries.values()):
                continue
            sufficient &= all(s["p95_ms"] > 0 for s in summaries.values())
            pairs.append(
                {
                    "trial": trial,
                    "candidate": effect(
                        summaries["baseline"]["p95_ms"], summaries["candidate"]["p95_ms"], spec
                    ),
                    "control": effect(
                        summaries["control_a"]["p95_ms"], summaries["control_b"]["p95_ms"], spec
                    ),
                    "reverse_control": effect(
                        summaries["control_b"]["p95_ms"], summaries["control_a"]["p95_ms"], spec
                    ),
                }
            )
        deltas = [p["candidate"]["delta_ms"] for p in pairs]
        ratios = [p["candidate"]["ratio"] for p in pairs if p["candidate"]["ratio"] is not None]
        control_noise = any(
            p["control"]["flagged"] or p["reverse_control"]["flagged"] for p in pairs
        )
        # shortcut: conservative spread heuristic; calibrate trial blocks before strict gates.
        spread = max(deltas) - min(deltas) if deltas else None
        noisy = control_noise or bool(
            deltas and spread > max(spec.absolute_ms, abs(median(deltas)) * 2)
        )
        regression = (
            sufficient
            and not noisy
            and len(ratios) == 5
            and median(deltas) >= spec.absolute_ms
            and median(ratios) >= spec.ratio
            and sum(p["candidate"]["flagged"] for p in pairs) >= 4
        )
        outcomes.append(
            {
                "operation_id": name,
                "policy": "advisory-v1",
                "status": "insufficient"
                if not sufficient
                else "noisy"
                if noisy
                else "regression_warning"
                if regression
                else "no_regression_observed",
                "absolute_ms": spec.absolute_ms,
                "ratio": spec.ratio,
                "median_delta_ms": median(deltas) if deltas else None,
                "median_ratio": median(ratios) if ratios else None,
                "between_trial_spread_ms": spread,
                "control_noise": control_noise,
                "trials": pairs,
                "limitations": (
                    "Sequential warm-cache closed-loop harness timings include assertions; "
                    "synthetic fixtures, not production capacity or statistical confidence."
                ),
            }
        )
    return arms, outcomes
