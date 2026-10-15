"""PostgreSQL 17 parsing, original SQL snapshots, locations, and parameter checks."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, NoReturn

from pglast import parser

from pg_rehearse.errors import ConfigurationError, UnsupportedInputError
from pg_rehearse.models import Scalar

MAX_INPUT_BYTES = 1_048_576


@dataclass(frozen=True)
class SQLStatement:
    source: str
    sql: str
    kind: str
    node: dict[str, Any]
    start: int
    end: int
    line: int
    column: int

    def reject(self, reason: str, *, unsupported: bool = True) -> NoReturn:
        error = UnsupportedInputError if unsupported else ConfigurationError
        raise error(f"{self.source}:{self.line}:{self.column}: {reason}")


@dataclass(frozen=True)
class SQLDocument:
    source: str
    text: str
    sha256: str
    statements: tuple[SQLStatement, ...]


def parse_document(text: str, source: str) -> SQLDocument:
    raw = text.encode("utf-8")
    if len(raw) > MAX_INPUT_BYTES or "\x00" in text:
        raise ConfigurationError(f"{source}: SQL must be NUL-free and at most 1 MiB")
    if parser.get_postgresql_version()[0] != 17:
        raise ConfigurationError("Installed parser must target PostgreSQL 17")
    try:
        tree = json.loads(parser.parse_sql_json(text))
        tokens = parser.scan(text)
    except RecursionError as exc:
        raise ConfigurationError(f"{source}: SQL nesting exceeds the supported limit") from exc
    except parser.ParseError as exc:
        position = exc.args[1] if len(exc.args) > 1 and isinstance(exc.args[1], int) else 0
        position = max(0, min(len(text), position))
        line = text.count("\n", 0, position) + 1
        column = position - text.rfind("\n", 0, position)
        raise ConfigurationError(
            f"{source}:{line}:{column}: SQL syntax error: {exc.args[0]}"
        ) from exc
    statements = []
    for item in tree.get("stmts", []):
        byte_start = item.get("stmt_location", 0)
        byte_end = byte_start + item["stmt_len"] if item.get("stmt_len") else len(raw)
        start, end = len(raw[:byte_start].decode()), len(raw[:byte_end].decode())
        keyword = next(
            (t.start for t in tokens if start <= t.start < end and "COMMENT" not in t.name), start
        )
        kind, node = next(iter(item["stmt"].items()))
        statements.append(
            SQLStatement(
                source,
                text[start:end],
                kind,
                node,
                start,
                end,
                text.count("\n", 0, keyword) + 1,
                keyword - text.rfind("\n", 0, keyword),
            )
        )
    if not statements:
        raise ConfigurationError(f"{source}: SQL must contain at least one statement")
    return SQLDocument(source, text, hashlib.sha256(raw).hexdigest(), tuple(statements))


def bound_sql_for_parse(sql: str, parameters: list[Scalar] | dict[str, Scalar], source: str) -> str:
    """Normalize bindings only for parsing; preserve the original SQL for execution."""
    try:
        tokens = parser.scan(sql)
    except parser.ParseError as exc:
        raise ConfigurationError(f"{source}: invalid SQL token: {exc.args[0]}") from exc
    if any(token.name == "PARAM" for token in tokens):
        raise ConfigurationError(f"{source}: use Psycopg %s or %(name)s bindings, not $n")
    if not parameters:
        return sql  # The worker must execute empty bindings as None; literal % stays literal.
    protected = [
        (t.start, t.end + 1)
        for t in tokens
        if "CONST" in t.name or "COMMENT" in t.name or t.name in {"IDENT", "UIDENT"}
    ]
    marker = re.compile(r"%%|%s|%\(([A-Za-z_][A-Za-z0-9_]*)\)s")
    names: list[str] = []
    count = 0
    position = 0
    parts: list[str] = []
    while (offset := sql.find("%", position)) >= 0:
        parts.append(sql[position:offset])
        match = marker.match(sql, offset)
        if match is None:
            raise ConfigurationError(f"{source}: invalid binding; use %s, %(name)s, or %%")
        if match.group() == "%%":
            parts.append("%")
        else:
            if any(start <= offset < end for start, end in protected):
                raise ConfigurationError(
                    f"{source}: a binding cannot appear in a literal, identifier, or comment"
                )
            name = match.group(1)
            if isinstance(parameters, dict):
                if name is None or name not in parameters:
                    raise ConfigurationError(f"{source}: named binding does not match parameters")
                if name not in names:
                    names.append(name)
                number = names.index(name) + 1
            else:
                if name is not None:
                    raise ConfigurationError(f"{source}: cannot mix positional and named bindings")
                count += 1
                number = count
            parts.append(f"${number}")
        position = match.end()
    parts.append(sql[position:])
    if (isinstance(parameters, list) and count != len(parameters)) or (
        isinstance(parameters, dict) and set(names) != set(parameters)
    ):
        raise ConfigurationError(f"{source}: bindings must use every parameter and match its count")
    return "".join(parts)
