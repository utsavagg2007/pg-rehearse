import pytest
from pydantic import ValidationError

from pg_rehearse.migration.catalog import catalog_verified
from pg_rehearse.migration.preflight import SQLDocument, parse_document
from pg_rehearse.models import CatalogState, CheckFact, IndexFact, MigrationResult


@pytest.fixture
def renamed_index() -> tuple[MigrationResult, SQLDocument]:
    document = parse_document("ALTER TABLE users RENAME COLUMN name TO full_name", "rename.sql")
    before = CatalogState(
        columns={"users": ["id", "name"]},
        indexes=[
            IndexFact(
                name="users_name_idx",
                table="users",
                columns=["name"],
                options=[0],
                method="btree",
                unique=False,
                valid=True,
                ready=True,
                definition="CREATE INDEX users_name_idx ON users (name)",
            )
        ],
        checks=[],
    )
    after = before.model_copy(deep=True)
    after.columns["users"] = ["id", "full_name"]
    after.indexes[0].columns = ["full_name"]
    after.indexes[0].definition = "CREATE INDEX users_name_idx ON users (full_name)"
    return (
        MigrationResult(
            step_id="rename",
            phase="post_deployed",
            transaction="transaction",
            source_sha256=document.sha256,
            statements=1,
            executed=1,
            committed=True,
            catalog_before=before,
            catalog_after=after,
        ),
        document,
    )


def test_rename_preserves_existing_index_facts_without_mutating_receipts(renamed_index) -> None:
    result, document = renamed_index
    original = result.model_dump_json()
    assert catalog_verified(result, document, {"users": ["id", "name"]})
    assert result.model_dump_json() == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("table", "orders"),
        ("columns", ["id"]),
        ("options", [1]),
        ("method", "hash"),
        ("unique", True),
        ("valid", False),
        ("ready", False),
    ],
)
def test_surviving_index_changes_cannot_satisfy_catalog_coverage(
    renamed_index, field: str, value: object
) -> None:
    result, document = renamed_index
    setattr(result.catalog_after.indexes[0], field, value)
    assert not catalog_verified(result, document, {"users": ["id", "name"]})


@pytest.mark.parametrize("duplicate", ["index", "check", "column"])
def test_catalog_rejects_duplicate_identities_at_load_and_after_mutation(
    renamed_index, duplicate: str
) -> None:
    result, document = renamed_index
    after = result.catalog_after
    if duplicate == "index":
        after.indexes.insert(0, after.indexes[0].model_copy(update={"valid": False}))
    elif duplicate == "check":
        after.checks = [
            CheckFact(name="positive", table="users", validated=value, definition="CHECK(id>0)")
            for value in (False, True)
        ]
    else:
        after.columns["users"].append("id")
    with pytest.raises(ValidationError, match="Duplicate catalog identities"):
        CatalogState.model_validate(after.model_dump())
    assert not catalog_verified(result, document, {"users": ["id", "name"]})
