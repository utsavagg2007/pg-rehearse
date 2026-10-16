"""Versioned structural fingerprints and metrics, independent of live connections."""

import hashlib
import json
import math
from typing import Any

from pg_rehearse.migration.preflight import parse_document
from pg_rehearse.models import PlanEvidence

STRUCTURAL = {
    "Node Type",
    "Join Type",
    "Relation Name",
    "Schema",
    "Index Name",
    "Scan Direction",
    "Strategy",
    "Partial Mode",
    "Parallel Aware",
    "Async Capable",
    "Parent Relationship",
}
METRICS = {
    "Startup Cost",
    "Total Cost",
    "Plan Rows",
    "Plan Width",
    "Actual Rows",
    "Actual Loops",
    "Rows Removed by Filter",
    "Rows Removed by Join Filter",
    "Shared Hit Blocks",
    "Shared Read Blocks",
    "Shared Dirtied Blocks",
    "Shared Written Blocks",
    "Local Hit Blocks",
    "Local Read Blocks",
    "Temp Read Blocks",
    "Temp Written Blocks",
    "Sort Space Used",
    "Sort Space Type",
    "Hash Batches",
}


def expression_shape(expression: str, *, sort: bool = False) -> Any:
    """Keep operators/column identities; remove literal values and parser positions."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            if "A_Const" in value or "ParamRef" in value:
                return {"value": "?"}
            return {
                k: clean(v)
                for k, v in value.items()
                if k not in {"location", "stmt_location", "stmt_len"}
            }
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    try:
        query = "SELECT 1 ORDER BY " if sort else "SELECT "
        return clean(parse_document(query + expression, "plan expression").statements[0].node)
    except ValueError:
        return {"unavailable": True}


def normalize_plan(raw: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(raw, ensure_ascii=True).encode()) > 262_144:
        raise ValueError("Plan exceeds 256 KiB")
    metrics = {}
    count = 0

    def walk(node: Any, path: str, depth: int) -> dict[str, Any]:
        nonlocal count
        count += 1
        if (
            depth > 64
            or count > 2000
            or not isinstance(node, dict)
            or not isinstance(node.get("Node Type"), str)
        ):
            raise ValueError("Invalid or excessive plan tree")
        structure: dict[str, Any] = {key: node[key] for key in sorted(STRUCTURAL) if key in node}
        if any(not isinstance(v, (str, bool)) for v in structure.values()):
            raise ValueError("Invalid structural field")
        for key in (
            "Sort Key",
            "Group Key",
            "Hash Key",
            "Filter",
            "Index Cond",
            "Hash Cond",
            "Join Filter",
            "Merge Cond",
        ):
            if key in node:
                expressions = node[key] if isinstance(node[key], list) else [node[key]]
                if any(not isinstance(e, str) for e in expressions):
                    raise ValueError("Invalid expression field")
                structure[key] = [expression_shape(e, sort=key == "Sort Key") for e in expressions]
        metrics[path] = {key: node[key] for key in sorted(METRICS) if key in node}
        if any(
            not isinstance(v, str)
            if key == "Sort Space Type"
            else type(v) not in (int, float) or not math.isfinite(v) or v < 0
            for key, v in metrics[path].items()
        ):
            raise ValueError("Invalid plan metric")
        children = node.get("Plans", [])
        if not isinstance(children, list):
            raise ValueError("Invalid plan children")
        if children:
            structure["Plans"] = [
                walk(child, f"{path}/{i}", depth + 1) for i, child in enumerate(children)
            ]
        return structure

    structure = walk(raw.get("Plan"), "0", 0)
    for key in ("Planning Time", "Execution Time"):
        if key in raw and (
            type(raw[key]) not in (int, float) or not math.isfinite(raw[key]) or raw[key] < 0
        ):
            raise ValueError("Invalid plan timing")
    return {
        "normalizer_version": 1,
        "structure": structure,
        "sha256": hashlib.sha256(
            json.dumps(structure, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "metrics": metrics,
        "planning_ms": raw.get("Planning Time"),
        "execution_ms": raw.get("Execution Time"),
    }


def compare_plans(
    before: list[PlanEvidence], after: list[PlanEvidence], ids: list[str]
) -> list[dict[str, Any]]:
    comparisons = []
    for name in ids:
        arms = []
        for results in (before, after):
            result = next((p for p in results if p.operation_id == name), None)
            arms.append(
                {
                    "status": "captured",
                    "analyze": result.analyze,
                    "committed": result.committed,
                    "settings": result.settings,
                    **normalize_plan(result.raw),
                }
                if result and result.success and result.raw
                else {
                    "status": "unavailable",
                    "error_kind": result.error_kind if result else "missing",
                    "sqlstate": result.sqlstate if result else None,
                }
            )
        available = all(a["status"] == "captured" for a in arms)
        comparisons.append(
            {
                "operation_id": name,
                "status": "compared" if available else "unavailable",
                "structure_changed": arms[0]["sha256"] != arms[1]["sha256"] if available else None,
                "baseline": arms[0],
                "candidate": arms[1],
                "raw_receipts": ["plan_baseline-evidence.json", "plan_candidate-evidence.json"],
                "limitations": (
                    "Literal diagnostic plans on fresh connections; literal values omitted "
                    "from shared summaries. Plan changes are informational; "
                    "costs are not milliseconds."
                ),
            }
        )
    return comparisons
