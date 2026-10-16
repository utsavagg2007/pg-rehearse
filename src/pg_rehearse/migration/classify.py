"""Fail-closed AST classification for the documented PG17 SQL subset."""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from pg_rehearse.errors import ConfigurationError
from pg_rehearse.migration.preflight import SQLDocument, SQLStatement
from pg_rehearse.models import Scalar, TransactionMode

TYPES = {
    "int2",
    "int4",
    "int8",
    "text",
    "varchar",
    "bool",
    "numeric",
    "float8",
    "uuid",
    "date",
    "timestamp",
    "timestamptz",
}
FUNCTIONS = {"count", "sum", "min", "max", "avg", "lower", "upper", "length", "abs"}
SCALAR_FUNCTIONS = {"lower", "upper", "length", "abs"}
OPERATORS = {
    "+",
    "-",
    "*",
    "/",
    "%",
    "=",
    "<>",
    "!=",
    ">",
    "<",
    ">=",
    "<=",
    "||",
    "~~",
    "!~~",
    "~~*",
    "!~~*",
}
EXPRESSION_NODES = {
    "A_Expr",
    "A_Const",
    "ColumnRef",
    "A_Star",
    "String",
    "Integer",
    "Float",
    "Boolean",
    "BoolExpr",
    "NullTest",
    "BooleanTest",
    "TypeCast",
    "TypeName",
    "FuncCall",
    "CoalesceExpr",
    "MinMaxExpr",
}
QUERY_NODES = EXPRESSION_NODES | {
    "List",
    "SelectStmt",
    "InsertStmt",
    "UpdateStmt",
    "DeleteStmt",
    "ResTarget",
    "RangeVar",
    "Alias",
    "JoinExpr",
    "SortBy",
    "ParamRef",
    "RangeSubselect",
}


def strings(items: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(item["String"]["sval"] for item in items)


def walk_nodes(value: object) -> Iterator[tuple[str, dict[str, Any]]]:
    stack = [value]
    visited = 0
    while stack:
        current = stack.pop()
        visited += 1
        if visited > 100_000:
            raise ConfigurationError("SQL expression exceeds the 100000-node preflight budget")
        if isinstance(current, dict):
            if len(current) == 1:
                key, child = next(iter(current.items()))
                if isinstance(key, str) and key[:1].isupper() and isinstance(child, dict):
                    yield key, child
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def identifier(name: str, statement: SQLStatement) -> str:
    if not name or len(name.encode()) > 63 or name.startswith("pg_"):
        statement.reject("Identifiers must be 1–63 UTF-8 bytes and cannot start with pg_")
    return name


def relation(node: dict[str, Any], statement: SQLStatement) -> str:
    if (
        node.get("catalogname")
        or node.get("schemaname") not in (None, "public")
        or node.get("relpersistence", "p") != "p"
    ):
        statement.reject("Only ordinary persistent tables in public are supported")
    return identifier(node["relname"], statement)


def only_fields(node: dict[str, Any], allowed: set[str], statement: SQLStatement) -> None:
    if any(key not in allowed and value for key, value in node.items()):
        statement.reject("Unsupported SQL options or AST shape")


def type_name(node: dict[str, Any], statement: SQLStatement) -> tuple[str, int | None]:
    names = strings(node.get("names", []))
    if not names or (len(names) > 1 and names[:-1] != ("pg_catalog",)) or names[-1] not in TYPES:
        statement.reject("Unsupported column or cast type")
    only_fields(node, {"names", "typemod", "location", "typmods"}, statement)
    modifiers = node.get("typmods", [])
    length = None
    if modifiers:
        if names[-1] != "varchar" or len(modifiers) != 1 or "A_Const" not in modifiers[0]:
            statement.reject("Only varchar(n) type modifiers are supported")
        length = modifiers[0]["A_Const"].get("ival", {}).get("ival", 0)
        if type(length) is not int or length <= 0:
            statement.reject("varchar length must be positive", unsupported=False)
    return names[-1], length


def validate_expression(value: object, statement: SQLStatement, *, query: bool = False) -> None:
    for kind, node in walk_nodes(value):
        if kind not in (QUERY_NODES if query else EXPRESSION_NODES):
            statement.reject(f"Unsupported expression node {kind}")
        query_fields = {
            "SelectStmt": {
                "distinctClause",
                "targetList",
                "fromClause",
                "whereClause",
                "groupClause",
                "havingClause",
                "sortClause",
                "limitOffset",
                "limitCount",
                "limitOption",
                "op",
                "all",
                "larg",
                "rarg",
                "valuesLists",
            },
            "InsertStmt": {"relation", "cols", "selectStmt", "returningList", "override"},
            "UpdateStmt": {"relation", "targetList", "whereClause", "fromClause", "returningList"},
            "DeleteStmt": {"relation", "usingClause", "whereClause", "returningList"},
        }
        if kind in query_fields:
            only_fields(node, query_fields[kind], statement)
        if (
            kind == "InsertStmt"
            and node.get("override", "OVERRIDING_NOT_SET") != "OVERRIDING_NOT_SET"
        ):
            statement.reject("INSERT identity override modes are not supported")
        if kind == "RangeVar":
            relation(node, statement)
        elif kind == "TypeName":
            type_name(node, statement)
        elif kind == "A_Expr" and any(
            name not in OPERATORS for name in strings(node.get("name", []))
        ):
            statement.reject("Unsupported operator")
        elif kind == "FuncCall":
            names = strings(node.get("funcname", []))
            if (
                not names
                or names[-1] not in (FUNCTIONS if query else SCALAR_FUNCTIONS)
                or (len(names) > 1 and names[:-1] != ("pg_catalog",))
            ):
                statement.reject("Unsupported function")
            if node.get("over") or node.get("agg_within_group"):
                statement.reject("Window and ordered-set functions are not supported")


@dataclass(frozen=True)
class ColumnDefinition:
    name: str
    data_type: str
    nullable: bool = True
    has_default: bool = False
    default: Scalar = None
    max_length: int | None = None
    identity: bool = False


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    target: str
    target_columns: tuple[str, ...]


@dataclass
class TableDefinition:
    name: str
    columns: dict[str, ColumnDefinition] = field(default_factory=dict)
    unique_keys: list[tuple[str, ...]] = field(default_factory=list)
    primary_key: tuple[str, ...] = ()
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    checks: set[str] = field(default_factory=set)


@dataclass
class SchemaCatalog:
    tables: dict[str, TableDefinition] = field(default_factory=dict)
    indexes: set[str] = field(default_factory=set)


def literal(node: dict[str, Any], statement: SQLStatement) -> Scalar:
    if set(node) != {"A_Const"}:
        statement.reject("Baseline defaults must be scalar literals")
    value = node["A_Const"]
    if value.get("isnull"):
        return None
    for key, field_name, default in (
        ("ival", "ival", 0),
        ("sval", "sval", ""),
        ("fval", "fval", "0"),
        ("boolval", "boolval", False),
    ):
        if key in value:
            result: Scalar = value[key].get(field_name, default)
            return result
    statement.reject("Unsupported default literal")
    return None


def _constraint(
    constraint: dict[str, Any], table: TableDefinition, column: str | None, statement: SQLStatement
) -> None:
    only_fields(
        constraint,
        {
            "contype",
            "conname",
            "location",
            "keys",
            "raw_expr",
            "pktable",
            "pk_attrs",
            "fk_attrs",
            "fk_matchtype",
            "fk_upd_action",
            "fk_del_action",
            "initially_valid",
            "generated_when",
        },
        statement,
    )
    kind = constraint["contype"]
    keys = (column,) if column else strings(constraint.get("keys", []))
    if kind in ("CONSTR_NOTNULL", "CONSTR_NULL", "CONSTR_DEFAULT") and column:
        definition = table.columns[column]
        if kind == "CONSTR_DEFAULT":
            table.columns[column] = replace(
                definition, has_default=True, default=literal(constraint["raw_expr"], statement)
            )
        else:
            table.columns[column] = replace(definition, nullable=kind == "CONSTR_NULL")
    elif kind == "CONSTR_IDENTITY" and column:
        definition = table.columns[column]
        if (
            constraint.get("generated_when") != "d"
            or definition.data_type not in {"int2", "int4", "int8"}
            or definition.has_default
            or definition.identity
        ):
            statement.reject(
                "Only integer BY DEFAULT identity with default sequence options is supported"
            )
        table.columns[column] = replace(definition, nullable=False, identity=True)
    elif kind in ("CONSTR_PRIMARY", "CONSTR_UNIQUE"):
        if not keys or any(key not in table.columns for key in keys):
            statement.reject("Constraint references unknown columns", unsupported=False)
        table.unique_keys.append(keys)
        if kind == "CONSTR_PRIMARY":
            if table.primary_key:
                statement.reject("A table cannot declare multiple primary keys", unsupported=False)
            table.primary_key = keys
            for key in keys:
                table.columns[key] = replace(table.columns[key], nullable=False)
    elif kind == "CONSTR_CHECK":
        validate_expression(constraint["raw_expr"], statement)
        if constraint.get("conname"):
            name = identifier(constraint["conname"], statement)
            if name in table.checks:
                statement.reject("Duplicate named CHECK constraint", unsupported=False)
            table.checks.add(name)
    elif kind == "CONSTR_FOREIGN":
        if constraint.get("fk_matchtype", "s") != "s" or any(
            constraint.get(key, "a") != "a" for key in ("fk_upd_action", "fk_del_action")
        ):
            statement.reject(
                "Only immediate MATCH SIMPLE, NO ACTION fixture foreign keys are supported"
            )
        table.foreign_keys.append(
            ForeignKey(
                (column,) if column else strings(constraint.get("fk_attrs", [])),
                relation(constraint["pktable"], statement),
                strings(constraint.get("pk_attrs", [])),
            )
        )
    else:
        statement.reject("Unsupported baseline constraint")


def baseline_catalog(document: SQLDocument) -> SchemaCatalog:
    catalog = SchemaCatalog()
    for statement in document.statements:
        node = statement.node
        if statement.kind != "CreateStmt":
            statement.reject("Baseline supports CREATE TABLE only; seed data belongs in fixtures")
        only_fields(node, {"relation", "tableElts", "oncommit"}, statement)
        if node.get("oncommit", "ONCOMMIT_NOOP") != "ONCOMMIT_NOOP":
            statement.reject("Baseline tables cannot declare ON COMMIT behavior")
        name = relation(node["relation"], statement)
        if name in catalog.tables:
            statement.reject("Duplicate baseline table", unsupported=False)
        table = TableDefinition(name)
        pending: list[tuple[dict[str, Any], str | None]] = []
        for element in node.get("tableElts", []):
            if "ColumnDef" in element:
                definition = element["ColumnDef"]
                only_fields(
                    definition,
                    {"colname", "typeName", "is_local", "constraints", "location"},
                    statement,
                )
                column = identifier(definition["colname"], statement)
                if column in table.columns:
                    statement.reject("Duplicate baseline column", unsupported=False)
                data_type, length = type_name(definition["typeName"], statement)
                table.columns[column] = ColumnDefinition(column, data_type, max_length=length)
                pending.extend(
                    (item["Constraint"], column) for item in definition.get("constraints", [])
                )
            elif "Constraint" in element:
                pending.append((element["Constraint"], None))
            else:
                statement.reject("Unsupported baseline table element")
        if not table.columns:
            statement.reject("Tables must declare columns", unsupported=False)
        for constraint, constraint_column in pending:
            _constraint(constraint, table, constraint_column, statement)
        catalog.tables[name] = table
    for table in catalog.tables.values():
        for foreign in table.foreign_keys:
            target = catalog.tables.get(foreign.target)
            if target is None:
                document.statements[0].reject(
                    "Foreign key references an unknown table", unsupported=False
                )
            target_keys = foreign.target_columns or target.primary_key
            if (
                not foreign.columns
                or len(foreign.columns) != len(target_keys)
                or any(key not in table.columns for key in foreign.columns)
                or target_keys not in target.unique_keys
            ):
                document.statements[0].reject(
                    "Foreign key must reference a declared primary/unique key", unsupported=False
                )
    return catalog


@dataclass(frozen=True)
class MigrationClassification:
    family: str
    statement: SQLStatement
    concurrent: bool = False


def classify_migration(
    document: SQLDocument, mode: TransactionMode, catalog: SchemaCatalog
) -> tuple[MigrationClassification, ...]:
    if mode == TransactionMode.AUTOCOMMIT and len(document.statements) != 1:
        document.statements[0].reject(
            "Autocommit steps require exactly one statement", unsupported=False
        )
    findings = []
    for statement in document.statements:
        node = statement.node
        if statement.kind == "DropStmt":
            only_fields(node, {"objects", "removeType", "behavior", "concurrent"}, statement)
            if (
                node.get("removeType") != "OBJECT_INDEX"
                or node.get("behavior") != "DROP_RESTRICT"
                or len(node["objects"]) != 1
            ):
                statement.reject("Only one explicitly created index can be dropped with RESTRICT")
            names = strings(node["objects"][0]["List"]["items"])
            if len(names) not in (1, 2) or (len(names) == 2 and names[0] != "public"):
                statement.reject("Only indexes in public are supported")
            index = identifier(names[-1], statement)
            if index not in catalog.indexes:
                statement.reject("DROP INDEX must reference an index created by an earlier step")
            concurrent = node.get("concurrent", False)
            if concurrent and mode != TransactionMode.AUTOCOMMIT:
                statement.reject("DROP INDEX CONCURRENTLY requires autocommit", unsupported=False)
            catalog.indexes.remove(index)
            findings.append(MigrationClassification("drop_index", statement, concurrent))
            continue
        if statement.kind not in {"RenameStmt", "IndexStmt", "AlterTableStmt"}:
            statement.reject(f"Unsupported migration statement {statement.kind}")
        if not isinstance(node.get("relation"), dict):
            statement.reject("Only supported table migrations are allowed")
        name = relation(node["relation"], statement)
        if name not in catalog.tables:
            statement.reject("Migration references an unknown baseline table", unsupported=False)
        table = catalog.tables[name]
        if statement.kind == "RenameStmt":
            only_fields(
                node,
                {"renameType", "relationType", "relation", "subname", "newname", "behavior"},
                statement,
            )
            if (
                node.get("renameType") != "OBJECT_COLUMN"
                or node.get("relationType") != "OBJECT_TABLE"
                or node.get("behavior") != "DROP_RESTRICT"
            ):
                statement.reject("Only direct table-column rename is supported")
            old, new = node["subname"], identifier(node["newname"], statement)
            if old not in table.columns or new in table.columns:
                statement.reject(
                    "Rename source must exist and destination must be new", unsupported=False
                )
            table.columns[new] = replace(table.columns.pop(old), name=new)
            findings.append(MigrationClassification("rename_column", statement))
        elif statement.kind == "IndexStmt":
            only_fields(
                node,
                {"idxname", "relation", "accessMethod", "indexParams", "concurrent"},
                statement,
            )
            if node.get("accessMethod") != "btree" or not node.get("idxname"):
                statement.reject("Only named non-unique B-tree indexes are supported")
            index = identifier(node["idxname"], statement)
            if index in catalog.indexes or index in catalog.tables:
                statement.reject("Index name is already declared", unsupported=False)
            for item in node.get("indexParams", []):
                element = item["IndexElem"]
                only_fields(element, {"name", "ordering", "nulls_ordering"}, statement)
                if element.get("name") not in table.columns:
                    statement.reject(
                        "Index must reference existing plain columns", unsupported=False
                    )
            concurrent = node.get("concurrent", False)
            if concurrent and mode != TransactionMode.AUTOCOMMIT:
                statement.reject("CREATE INDEX CONCURRENTLY requires autocommit", unsupported=False)
            catalog.indexes.add(index)
            findings.append(MigrationClassification("create_index", statement, concurrent))
        else:
            only_fields(node, {"relation", "cmds", "objtype"}, statement)
            if node.get("objtype") != "OBJECT_TABLE":
                statement.reject("Only table CHECK alterations are supported")
            for item in node.get("cmds", []):
                command = item["AlterTableCmd"]
                only_fields(command, {"subtype", "def", "name", "behavior"}, statement)
                if command.get("behavior") != "DROP_RESTRICT":
                    statement.reject("CASCADE alterations are not supported")
                subtype = command["subtype"]
                if subtype == "AT_AddConstraint":
                    constraint = command.get("def", {}).get("Constraint", {})
                    only_fields(
                        constraint,
                        {
                            "contype",
                            "conname",
                            "raw_expr",
                            "location",
                            "skip_validation",
                            "initially_valid",
                        },
                        statement,
                    )
                    if constraint.get("contype") != "CONSTR_CHECK" or not constraint.get("conname"):
                        statement.reject("Only named CHECK additions are supported")
                    check = identifier(constraint["conname"], statement)
                    if check in table.checks:
                        statement.reject("CHECK name already exists", unsupported=False)
                    validate_expression(constraint["raw_expr"], statement)
                    table.checks.add(check)
                    family = "add_check"
                elif subtype in ("AT_DropConstraint", "AT_ValidateConstraint"):
                    check = command["name"]
                    if check not in table.checks:
                        statement.reject(
                            "CHECK must be explicitly named in baseline or an earlier step"
                        )
                    if subtype == "AT_DropConstraint":
                        table.checks.remove(check)
                    family = "drop_check" if subtype == "AT_DropConstraint" else "validate_check"
                else:
                    statement.reject(f"Unsupported ALTER TABLE action {subtype}")
                    family = "unsupported"
                findings.append(MigrationClassification(family, statement))
    return tuple(findings)


def validate_contract(document: SQLDocument) -> None:
    if len(document.statements) != 1:
        document.statements[0].reject(
            "Each contract operation must contain exactly one statement", unsupported=False
        )
    statement = document.statements[0]
    if statement.kind not in {"SelectStmt", "InsertStmt", "UpdateStmt", "DeleteStmt"}:
        statement.reject("Contracts support SELECT/INSERT/UPDATE/DELETE only")
    validate_expression({statement.kind: statement.node}, statement, query=True)
