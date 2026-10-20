from pathlib import Path

import pytest
import yaml
from docker import DockerClient
from docker.errors import NotFound

from pg_rehearse.models import CleanupStatus
from pg_rehearse.orchestrator import run_rehearsal
from pg_rehearse.runtime.manifest import ManifestStore

pytestmark = pytest.mark.integration


def test_numeric_fixtures_and_defaults_survive_seed_clones_and_contracts(
    docker_client: DockerClient, rehearsal_project: Path, tmp_path: Path
) -> None:
    exact = "12345678901234567890.123456789012345678900"
    (rehearsal_project / "schema/base.sql").write_text(
        f"""CREATE TABLE numbers (
    id bigint PRIMARY KEY,
    exponent numeric NOT NULL,
    signed_zero numeric NOT NULL,
    precise numeric NOT NULL,
    tiny numeric NOT NULL,
    wide bigint NOT NULL DEFAULT 2147483648,
    negative bigint NOT NULL DEFAULT -2147483649,
    fractional double precision NOT NULL DEFAULT 1.5,
    scientific double precision NOT NULL DEFAULT 1e2,
    exact_default numeric NOT NULL DEFAULT {exact}
);"""
    )
    (rehearsal_project / "fixtures/orders.yml").write_text(
        yaml.safe_dump(
            {
                "tables": {
                    "numbers": [
                        {
                            "id": 1,
                            "exponent": "1e2",
                            "signed_zero": "-0.00",
                            "precise": exact,
                            "tiny": "1e-200",
                        }
                    ]
                }
            }
        )
    )
    default_values = [2147483648, -2147483649, 1.5, 100.0, exact]
    operations = [
        {
            "id": "read-numerics",
            "sql": "SELECT * FROM numbers ORDER BY id",
            "expect": {"rows": [[1, "100", "0.00", exact, "1E-200", *default_values]]},
        },
        {
            "id": "postgres-defaults",
            "sql": (
                "INSERT INTO numbers(id,exponent,signed_zero,precise,tiny) "
                "VALUES(2,1e2,-0.00,1.0,1e-200) "
                "RETURNING wide,negative,fractional,scientific,exact_default"
            ),
            "expect": {"rows": [default_values], "row_count": 1},
        },
    ]
    (rehearsal_project / "contracts/deployed-v1.yml").write_text(
        yaml.safe_dump({"version": "deployed-v1", "operations": operations})
    )
    (rehearsal_project / "migrations/create_order_user_index.sql").write_text(
        "CREATE INDEX numbers_exponent_idx ON numbers (exponent);"
    )
    result, directory = run_rehearsal(
        rehearsal_project / "control.yml", state_dir=tmp_path / "runs"
    )
    assert result.exit_code == 0
    assert result.completion.value == "complete" and result.verdict.value == "pass"
    assert result.cleanup == CleanupStatus.COMPLETE and not result.coverage.missing
    assert result.baseline is not None and result.baseline.success
    assert result.baseline.table_rows == {"numbers": 1}
    assert result.template.sealed and len(result.branches) >= 2
    assert {branch.data_sha256 for branch in result.branches} == {result.baseline.data_sha256}
    assert result.migrations and all(step.committed for step in result.migrations)
    assert {operation.phase for operation in result.operations} == {"baseline", "post_deployed"}
    assert len(result.operations) == 4 and all(operation.success for operation in result.operations)
    manifest = ManifestStore(directory / "manifest.json").load()
    assert manifest.cleanup == CleanupStatus.COMPLETE
    for resource in manifest.resources:
        collection = (
            docker_client.networks if resource.kind == "network" else docker_client.containers
        )
        with pytest.raises(NotFound):
            collection.get(resource.resource_id or resource.name)
