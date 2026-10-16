"""Pure result normalization and semantic assertions; no database connections."""

import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from pg_rehearse.models import AssertionResult, Scalar, SemanticAssertions

MAX_RESULT_ROWS = 10_000
MAX_RESULT_BYTES = 1_048_576


def normalize(value: object) -> Scalar:
    if value is None or type(value) in (str, bool, int):
        return cast(Scalar, value)
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, Decimal) and value.is_finite():
        return str(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise ValueError("Unsupported or nonfinite database result")


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def summarize(value: Any) -> Any:
    data = encoded(value).encode()
    if len(data) <= 1024:
        return value
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def compare_results(
    expect: SemanticAssertions, columns: list[str], rows: list[list[Scalar]], row_count: int
) -> list[AssertionResult]:
    assertions = []
    for name, expected, actual in (
        ("columns", expect.columns, columns),
        ("rows", expect.rows, rows),
        ("row_count", expect.row_count, row_count),
    ):
        if expected is not None:
            assertions.append(
                AssertionResult(
                    name=name,
                    passed=encoded(expected) == encoded(actual),
                    expected=summarize(expected),
                    actual=summarize(actual),
                )
            )
    return assertions
