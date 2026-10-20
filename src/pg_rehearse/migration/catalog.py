"""Worker catalog capture and pure checks for the bounded migration families."""

from typing import TYPE_CHECKING, Any

import psycopg

from pg_rehearse.migration.classify import baseline_catalog
from pg_rehearse.migration.preflight import SQLDocument
from pg_rehearse.models import CatalogState, CheckFact, IndexFact, MigrationResult

if TYPE_CHECKING:
    from pg_rehearse.config import LoadedConfig


def capture_catalog(connection: psycopg.Connection[tuple[object, ...]]) -> CatalogState:
    columns: dict[str, list[str]] = {}
    for table, column in connection.execute("""
        SELECT c.relname, a.attname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid WHERE n.nspname='public' AND c.relkind='r'
        AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum
    """):
        columns.setdefault(str(table), []).append(str(column))
    indexes = [
        IndexFact.model_validate(
            dict(
                zip(
                    (
                        "name",
                        "table",
                        "valid",
                        "ready",
                        "method",
                        "unique",
                        "columns",
                        "options",
                        "definition",
                    ),
                    row,
                    strict=True,
                )
            )
        )
        for row in connection.execute("""
        SELECT i.relname,t.relname,x.indisvalid,x.indisready,am.amname,x.indisunique,
            ARRAY(SELECT a.attname::text FROM unnest(x.indkey) WITH ORDINALITY k(num,pos)
                  JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.num ORDER BY k.pos),
            x.indoption::smallint[],pg_get_indexdef(i.oid)
        FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid
        JOIN pg_class t ON t.oid=x.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace
        JOIN pg_am am ON am.oid=i.relam WHERE n.nspname='public' ORDER BY i.relname
    """)
    ]
    checks = [
        CheckFact.model_validate(
            dict(
                zip(
                    ("name", "table", "validated", "definition"),
                    row,
                    strict=True,
                )
            )
        )
        for row in connection.execute("""
        SELECT c.conname,t.relname,c.convalidated,pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname='public' AND c.contype='c' ORDER BY t.relname,c.conname
    """)
    ]
    return CatalogState(columns=columns, indexes=indexes, checks=checks)


def drop_index_name(node: dict[str, Any]) -> str:
    return str(node["objects"][0]["List"]["items"][-1]["String"]["sval"])


def catalog_verifications(
    loaded: "LoadedConfig", results: list[MigrationResult]
) -> dict[str, bool]:
    columns = {
        name: list(table.columns)
        for name, table in baseline_catalog(loaded.schema_sql).tables.items()
    }
    verified = {}
    previous = None
    for position, (result, document) in enumerate(zip(results, loaded.migration_sql, strict=False)):
        verified[result.step_id] = catalog_verified(result, document, columns) and (
            position == 0 or (previous is not None and result.catalog_before == previous)
        )
        previous = result.catalog_after
        if result.committed:
            for statement in document.statements:
                if statement.kind == "RenameStmt":
                    node = statement.node
                    table = node["relation"]["relname"]
                    columns[table] = [
                        node["newname"] if name == node["subname"] else name
                        for name in columns[table]
                    ]
    return verified


def catalog_verified(
    result: MigrationResult, document: SQLDocument, expected_columns: dict[str, list[str]]
) -> bool:
    before, after = result.catalog_before, result.catalog_after
    if before is None or after is None:
        return False
    try:
        for state in (before, after):
            CatalogState.model_validate(state.model_dump())
    except ValueError:
        return False
    if before.columns != expected_columns:
        return False
    if not result.committed:
        return True  # Observed failure remnants, not evidence of successful DDL.
    # Check the final effect of the whole step, including multiple changes to one object.
    columns = {table: names.copy() for table, names in before.columns.items()}
    indexes = {index.name: index for index in before.indexes}
    checks = {(check.table, check.name): check.validated for check in before.checks}
    for statement in document.statements:
        node = statement.node
        if statement.kind == "DropStmt":
            name = drop_index_name(node)
            indexes.pop(name, None)
            continue
        table = node["relation"]["relname"]
        if statement.kind == "RenameStmt":
            if node["subname"] not in columns.get(table, []):
                return False
            columns[table] = [
                node["newname"] if c == node["subname"] else c for c in columns[table]
            ]
            for name, index in indexes.items():
                if index.table == table:
                    indexes[name] = index.model_copy(
                        update={
                            "columns": [
                                node["newname"] if c == node["subname"] else c
                                for c in index.columns
                            ]
                        }
                    )
        elif statement.kind == "IndexStmt":
            elements = [item["IndexElem"] for item in node["indexParams"]]
            options = []
            for element in elements:
                desc = element.get("ordering") == "SORTBY_DESC"
                nulls = element.get("nulls_ordering", "SORTBY_NULLS_DEFAULT")
                first = nulls == "SORTBY_NULLS_FIRST" or (nulls == "SORTBY_NULLS_DEFAULT" and desc)
                options.append(int(desc) + 2 * int(first))
            indexes[node["idxname"]] = IndexFact(
                name=node["idxname"],
                table=table,
                columns=[e["name"] for e in elements],
                options=options,
                method="btree",
                unique=False,
                valid=True,
                ready=True,
                definition=statement.sql,
            )
        else:
            for item in node["cmds"]:
                command = item["AlterTableCmd"]
                kind = command["subtype"]
                if kind == "AT_AddConstraint":
                    constraint = command["def"]["Constraint"]
                    checks[(table, constraint["conname"])] = not constraint.get(
                        "skip_validation", False
                    )
                elif kind == "AT_DropConstraint":
                    checks.pop((table, command["name"]), None)
                else:
                    checks[(table, command["name"])] = True
    return (
        columns == after.columns
        and {name: index.model_dump(exclude={"definition"}) for name, index in indexes.items()}
        == {index.name: index.model_dump(exclude={"definition"}) for index in after.indexes}
        and checks == {(check.table, check.name): check.validated for check in after.checks}
    )
