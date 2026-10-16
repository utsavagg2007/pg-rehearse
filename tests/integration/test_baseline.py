from pathlib import Path
from typing import Any

import pytest
import yaml
from docker import DockerClient
from docker.errors import NotFound
from docker.models.containers import ContainerCollection

from pg_rehearse.config import load_config
from pg_rehearse.models import CleanupStatus
from pg_rehearse.orchestrator import worker_inputs
from pg_rehearse.runtime.docker import DockerRuntime
from pg_rehearse.runtime.manifest import KIND_LABEL, ManifestStore
from pg_rehearse.worker_protocol import WORKER_IMAGE, WorkerEvidence

pytestmark = pytest.mark.integration


def run_project(project: Path, directory: Path, client: DockerClient) -> WorkerEvidence:
    client.images.get(WORKER_IMAGE)
    loaded = load_config(project / "rehearsal.yml")
    runtime = DockerRuntime(state_dir=directory, client=client)
    with runtime.provision() as environment:
        evidence = runtime.execute_worker(environment, worker_inputs(loaded), loaded.spec.timeouts)
    manifest = ManifestStore(environment.manifest_path).load()
    assert manifest.cleanup == CleanupStatus.COMPLETE
    for resource in manifest.resources:
        collection = client.networks if resource.kind == "network" else client.containers
        with pytest.raises(NotFound):
            collection.get(resource.resource_id or resource.name)
    return evidence


def contracts(project: Path, operations: list[dict]) -> None:
    (project / "contracts/deployed-v1.yml").write_text(
        yaml.safe_dump(
            {
                "version": "deployed-v1",
                "operations": operations,
            }
        )
    )


def operation(identifier: str, query: str, expect: dict, parameters: Any = None) -> dict:
    return {"id": identifier, "sql": query, "parameters": parameters or [], "expect": expect}


def test_orders_baseline_is_verified_and_reproduced(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    first = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    second = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert first.baseline is not None and second.baseline is not None
    assert first.baseline.success and first.baseline.table_rows == {"users": 2, "orders": 2}
    assert first.baseline.data_sha256 == second.baseline.data_sha256
    assert first.baseline.seed == 42 and first.baseline.schema_statements == 2
    assert all(result.success for result in first.operations)
    assert first.operations[0].assertions[1].actual == [[7, "Ada"]]
    assert first.operations[1].assertions[1].actual == [[101, "pending", 12500]]
    assert first.coverage.required == [
        "baseline/deployed-v1/get-user",
        "baseline/deployed-v1/list-orders",
    ]
    assert not first.coverage.missing


@pytest.mark.parametrize("kind,sqlstate", [("schema", "42883"), ("fixture", "23514")])
def test_setup_failures_are_preserved_and_skip_contracts(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path, kind: str, sqlstate: str
) -> None:
    if kind == "schema":
        path = rehearsal_project / "schema/base.sql"
        path.write_text(
            path.read_text().replace("name TEXT NOT NULL", "name TEXT NOT NULL CHECK (name > 0)")
        )
    else:
        path = rehearsal_project / "fixtures/orders.yml"
        data = yaml.safe_load(path.read_text())
        data["tables"]["orders"][0]["amount_cents"] = -1
        path.write_text(yaml.safe_dump(data))
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert evidence.baseline is not None and not evidence.baseline.success
    assert evidence.baseline.error_kind == f"{kind}_error"
    assert evidence.baseline.sqlstate == sqlstate
    assert evidence.completion == "partial" and evidence.operations == []
    assert len(evidence.coverage.missing) == 2


def test_assertions_sqlstate_and_transaction_recovery(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    query = "SELECT id, name FROM users WHERE id = %s"
    contracts(
        rehearsal_project,
        [
            operation("bad-columns", query, {"columns": ["id", "other"]}, [7]),
            operation("bad-rows", query, {"rows": [[7, "Wrong"]]}, [7]),
            operation("bad-count", query, {"row_count": 2}, [7]),
            operation("sql-failure", "SELECT missing FROM users", {"row_count": 1}),
            operation(
                "good-after-failure", query, {"columns": ["id", "name"], "rows": [[7, "Ada"]]}, [7]
            ),
        ],
    )
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert [result.error_kind for result in evidence.operations] == [
        "assertion_error",
        "assertion_error",
        "assertion_error",
        "sql_error",
        None,
    ]
    assert evidence.operations[3].sqlstate == "42703" and not evidence.operations[3].assertions
    assert evidence.operations[-1].success
    assert evidence.completion == "complete" and not evidence.coverage.missing


def test_bindings_literal_percent_and_empty_result_columns(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    contracts(
        rehearsal_project,
        [
            operation(
                "named", "SELECT name FROM users WHERE id = %(id)s", {"rows": [["Ada"]]}, {"id": 7}
            ),
            operation("literal-percent", "SELECT '100%' AS status", {"rows": [["100%"]]}),
            operation(
                "empty",
                "SELECT id, name FROM users WHERE id=%s",
                {"columns": ["id", "name"], "rows": [], "row_count": 0},
                [999],
            ),
        ],
    )
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert all(result.success for result in evidence.operations)


def test_write_probes_rollback_and_bound_values_remain_data(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    hostile = "x'); DROP TABLE users; --"
    contracts(
        rehearsal_project,
        [
            operation(
                "insert",
                "INSERT INTO users(id,name,email) VALUES(%s,%s,%s) RETURNING id,name",
                {"rows": [[9, hostile]], "row_count": 1},
                [9, hostile, "new@example.test"],
            ),
            operation("insert-rolled-back", "SELECT id FROM users WHERE id=9", {"row_count": 0}),
            operation(
                "update", "UPDATE users SET name=%s WHERE id=7", {"row_count": 1}, ["Changed"]
            ),
            operation("delete", "DELETE FROM orders WHERE id=101", {"row_count": 1}),
            operation("data-preserved", "SELECT name FROM users WHERE id=7", {"rows": [["Ada"]]}),
            operation("orders-preserved", "SELECT count(*) FROM orders", {"rows": [[2]]}),
        ],
    )
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert all(result.success for result in evidence.operations)


def test_parent_tables_and_self_referencing_rows_load_first(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    schema = rehearsal_project / "schema/base.sql"
    users, orders = schema.read_text().split("CREATE TABLE orders", 1)
    users = users.replace(
        "email TEXT NOT NULL UNIQUE",
        "email TEXT NOT NULL UNIQUE, manager BIGINT REFERENCES users(id)",
    )
    schema.write_text("CREATE TABLE orders" + orders + "\n" + users)
    fixture = rehearsal_project / "fixtures/orders.yml"
    data = yaml.safe_load(fixture.read_text())
    data["tables"]["users"][0]["manager"] = 8
    fixture.write_text(yaml.safe_dump(data))
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert evidence.baseline is not None and evidence.baseline.success
    assert all(result.success for result in evidence.operations)


@pytest.mark.parametrize("ids,next_id", [([7, 8], 9), ([], 1), ([-5, -2], 1)])
def test_identity_sequences_follow_explicit_fixture_ids(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    ids: list[int],
    next_id: int,
) -> None:
    schema = rehearsal_project / "schema/base.sql"
    schema.write_text(
        schema.read_text().replace(
            "id BIGINT PRIMARY KEY", "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
        )
    )
    fixture = rehearsal_project / "fixtures/orders.yml"
    fixture.write_text(
        yaml.safe_dump(
            {
                "tables": {
                    "users": [
                        {"id": value, "name": "User", "email": f"{value}@example.test"}
                        for value in ids
                    ]
                }
            }
        )
    )
    contracts(
        rehearsal_project,
        [
            operation(
                "generated-id",
                "INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id",
                {"rows": [[next_id]]},
                ["New", "new@example.test"],
            )
        ],
    )
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert evidence.baseline is not None and evidence.baseline.success
    assert evidence.operations[0].success


def test_result_limit_and_nonfinite_results_do_not_poison_next_probe(
    docker_client: DockerClient,
    rehearsal_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts(
        rehearsal_project,
        [
            operation("too-many", "SELECT users.id FROM users CROSS JOIN orders", {"row_count": 4}),
            operation("nonfinite", "SELECT 'NaN'::double precision", {"row_count": 1}),
            operation("good", "SELECT 1", {"rows": [[1]]}),
        ],
    )
    original = ContainerCollection.create
    script = """
import sys
import pg_rehearse.workload.runner as runner
from pg_rehearse.worker import execute_baseline
from pg_rehearse.worker_protocol import WorkerRequest
runner.MAX_RESULT_ROWS = 2
request = WorkerRequest.model_validate_json(sys.stdin.buffer.readline())
print(execute_baseline(request).model_dump_json())
"""

    def create(self: ContainerCollection, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("labels", {}).get(KIND_LABEL) == "worker":
            kwargs["entrypoint"] = ["/app/.venv/bin/python", "-c", script]
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ContainerCollection, "create", create)
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert [result.error_kind for result in evidence.operations] == [
        "result_limit",
        "unsupported_result",
        None,
    ]


def test_cli_reports_baseline_failure_without_a_compatibility_verdict(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from pg_rehearse.cli import app

    contracts(rehearsal_project, [operation("wrong", "SELECT 1", {"rows": [[2]]})])
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--config",
            str(rehearsal_project / "rehearsal.yml"),
            "--state-dir",
            str(tmp_path / "runs"),
        ],
    )
    assert result.exit_code == 3, result.output
    assert "assertion_error" in result.output and "cleanup complete" in result.output
    assert "no migration compatibility result" in result.output
    receipt = next((tmp_path / "runs").glob("*/worker-evidence.json"))
    assert not WorkerEvidence.model_validate_json(receipt.read_bytes()).operations[0].success


def test_typed_fixtures_roundtrip_through_postgres(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    schema = rehearsal_project / "schema/base.sql"
    schema.write_text(
        schema.read_text()
        + """
CREATE TABLE typed_values (
    id integer PRIMARY KEY, amount numeric, ratio double precision,
    day date, moment timestamptz, token uuid, optional text
);
"""
    )
    fixture = rehearsal_project / "fixtures/orders.yml"
    data = yaml.safe_load(fixture.read_text())
    data["tables"]["typed_values"] = [
        {
            "id": 1,
            "amount": "12.50",
            "ratio": 1.25,
            "day": "2026-10-16",
            "moment": "2026-10-16T05:30:00+05:30",
            "token": "12345678-1234-1234-1234-123456789abc",
            "optional": None,
        }
    ]
    fixture.write_text(yaml.safe_dump(data))
    contracts(
        rehearsal_project,
        [
            operation(
                "typed",
                "SELECT amount,ratio,day,moment,token,optional FROM typed_values",
                {
                    "rows": [
                        [
                            "12.50",
                            1.25,
                            "2026-10-16",
                            "2026-10-16T00:00:00+00:00",
                            "12345678-1234-1234-1234-123456789abc",
                            None,
                        ]
                    ],
                    "row_count": 1,
                },
            )
        ],
    )
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert evidence.baseline is not None and evidence.baseline.success
    assert evidence.operations[0].success


def test_operation_deadline_recovers_before_next_probe(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    path = rehearsal_project / "rehearsal.yml"
    data = yaml.safe_load(path.read_text())
    data["timeouts"] = {"statement_ms": 150, "lock_ms": 75}
    path.write_text(yaml.safe_dump(data))
    sources = ",".join(f"users u{index}" for index in range(30))
    contracts(
        rehearsal_project,
        [
            operation("bounded", f"SELECT count(*) FROM {sources}", {"row_count": 1}),
            operation("after-timeout", "SELECT 1", {"rows": [[1]]}),
        ],
    )
    evidence = run_project(rehearsal_project, tmp_path / "runs", docker_client)
    assert evidence.operations[0].error_kind in {"sql_error", "operation_deadline"}
    assert evidence.operations[0].sqlstate in {None, "57014"}
    assert evidence.operations[1].success
