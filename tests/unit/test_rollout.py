from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from pg_rehearse.config import load_config
from pg_rehearse.errors import ConfigurationError
from pg_rehearse.migration.classify import baseline_catalog, classify_migration
from pg_rehearse.migration.preflight import parse_document
from pg_rehearse.models import TransactionMode
from pg_rehearse.orchestrator import run_rehearsal
from pg_rehearse.rollout.phases import rollout_plan


@pytest.mark.parametrize(
    "change",
    [
        "order",
        "missing",
        "actor",
        "sql",
        "write_pair",
        "optional",
        "candidate",
        "apps_without_rollout",
        "timeout",
        "collision",
    ],
)
def test_invalid_rollout_precedes_allocation(
    rehearsal_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    path = rehearsal_project / "rollout.yml"
    data = yaml.safe_load(path.read_text())
    if change == "order":
        data["rollout"]["phases"].reverse()
    elif change == "missing":
        data["rollout"]["phases"].pop()
    elif change == "actor":
        data["rollout"]["phases"][1]["operations"][0]["actor"] = "deployed"
    elif change == "sql":
        data["rollout"]["phases"][0]["operations"][0]["sql"] = "SET ROLE rehearse_admin"
    elif change == "write_pair":
        data["rollout"]["phases"][0]["operations"][0]["sql"] = "SELECT 1"
    elif change == "optional":
        data["rollout"]["phases"][0]["operations"][0]["required"] = False
    elif change == "candidate":
        data["contracts"].pop("candidate")
    elif change == "collision":
        data["applications"] = {
            "adapter": "orders",
            "user_id": 7,
            "expected_name": "Ada",
            "order_id_base": 100,
        }
    elif change == "timeout":
        data["timeouts"] = {"application_ms": 0}
    else:
        data.pop("rollout")
        data["applications"] = {"adapter": "orders", "user_id": 7, "expected_name": "Ada"}
    path.write_text(yaml.safe_dump(data))
    allocator = Mock(side_effect=AssertionError("must not allocate"))
    monkeypatch.setattr("pg_rehearse.orchestrator.DockerRuntime", allocator)
    with pytest.raises(ConfigurationError):
        run_rehearsal(path)
    allocator.assert_not_called()


def test_rollout_and_rollback_have_distinct_ordered_coverage(rehearsal_project: Path) -> None:
    loaded = load_config(rehearsal_project / "rollout.yml")
    rollout = rollout_plan(loaded, "rollout")
    rollback = rollout_plan(loaded, "rollback")
    assert len({item.check for item in rollout + rollback}) == len(rollout + rollback)
    assert rollout[0].phase == "rollout_baseline/old_1"
    assert [item.actor for item in rollout if item.phase == "mixed_versions"] == [
        "deployed",
        "candidate",
        "candidate",
        "deployed",
    ]
    assert [item.commit for item in rollback] == [True, False]
    assert all(item.phase == "app_rollback" for item in rollback)


@pytest.mark.parametrize(
    "statement,mode",
    [
        ("DROP INDEX missing", "transaction"),
        ("DROP INDEX orders_user_id_idx CASCADE", "transaction"),
        ("DROP INDEX IF EXISTS orders_user_id_idx", "transaction"),
        ("DROP INDEX orders_user_id_idx, other", "transaction"),
        ("DROP INDEX CONCURRENTLY orders_user_id_idx", "transaction"),
        ("DROP INDEX private.orders_user_id_idx", "autocommit"),
        ("CREATE UNIQUE INDEX bad ON orders(user_id)", "autocommit"),
    ],
)
def test_index_support_stays_bounded(rehearsal_project: Path, statement: str, mode: str) -> None:
    loaded = load_config(rehearsal_project / "control.yml")
    catalog = baseline_catalog(loaded.schema_sql)
    classify_migration(loaded.migration_sql[0], TransactionMode.TRANSACTION, catalog)
    with pytest.raises(ConfigurationError):
        classify_migration(parse_document(statement, "test"), TransactionMode(mode), catalog)
