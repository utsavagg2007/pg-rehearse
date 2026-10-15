"""Validate explicit fixture rows against the accepted baseline before provisioning."""

import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pg_rehearse.errors import ConfigurationError
from pg_rehearse.migration.classify import ColumnDefinition, SchemaCatalog
from pg_rehearse.models import FixtureSpec, Scalar


def column_value(column: ColumnDefinition, value: Scalar, context: str) -> Any:
    if value is None:
        if not column.nullable:
            raise ConfigurationError(f"{context}: NULL is not allowed")
        return None
    kind = column.data_type
    try:
        if kind in {"int2", "int4", "int8"}:
            bits = {"int2": 16, "int4": 32, "int8": 64}[kind]
            if type(value) is not int or not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
                raise ValueError
        elif kind in {"text", "varchar"}:
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError
            if column.max_length and len(value) > column.max_length:
                raise ValueError
        elif kind == "bool":
            if type(value) is not bool:
                raise ValueError
        elif kind == "numeric":
            if type(value) not in (str, int) or not Decimal(value).is_finite():
                raise ValueError
            return Decimal(value)
        elif kind == "float8":
            if type(value) not in (float, int) or not math.isfinite(float(value)):
                raise ValueError
        elif kind in {"uuid", "date", "timestamp", "timestamptz"}:
            if not isinstance(value, str):
                raise ValueError
            if kind == "uuid":
                return UUID(value)
            if kind == "date":
                return date.fromisoformat(value)
            parsed = datetime.fromisoformat(value)
            if (parsed.tzinfo is not None) != (kind == "timestamptz"):
                raise ValueError
            return parsed
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        raise ConfigurationError(
            f"{context}: value does not match {kind} or its supported bounds"
        ) from exc
    return value


def validate_fixtures(fixtures: FixtureSpec | None, catalog: SchemaCatalog, source: str) -> None:
    rows_by_table = fixtures.tables if fixtures else {}
    if set(rows_by_table) - set(catalog.tables):
        raise ConfigurationError(f"{source}: fixture references an unknown baseline table")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for name, table in catalog.tables.items():
        normalized[name] = []
        unique: dict[tuple[str, ...], set[tuple[Any, ...]]] = {
            keys: set() for keys in table.unique_keys
        }
        for index, row in enumerate(rows_by_table.get(name, []), 1):
            context = f"{source}: {name} row {index}"
            if set(row) - set(table.columns):
                raise ConfigurationError(f"{context}: unknown column")
            values: dict[str, Any] = {}
            for key, column in table.columns.items():
                if key not in row and not column.nullable and not column.has_default:
                    raise ConfigurationError(f"{context}: missing required column {key}")
                value = row.get(key, column.default if column.has_default else None)
                values[key] = column_value(column, value, f"{context}, column {key}")
            for keys, seen in unique.items():
                key_values = tuple(values[key] for key in keys)
                if None not in key_values:
                    if key_values in seen:
                        raise ConfigurationError(f"{context}: duplicate primary/unique fixture key")
                    seen.add(key_values)
            normalized[name].append(values)
    for name, table in catalog.tables.items():
        for foreign in table.foreign_keys:
            target = catalog.tables[foreign.target]
            keys = foreign.target_columns or target.primary_key
            allowed = {tuple(row[key] for key in keys) for row in normalized[foreign.target]}
            for row in normalized[name]:
                foreign_values = tuple(row[key] for key in foreign.columns)
                if None not in foreign_values and foreign_values not in allowed:
                    raise ConfigurationError(
                        f"{source}: {name} has a fixture foreign key without a parent row"
                    )
