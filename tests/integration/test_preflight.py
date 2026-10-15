from pathlib import Path

import pytest
import yaml
from docker import DockerClient
from docker.errors import NotFound

from pg_rehearse.orchestrator import validated_environment

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "migration,mode,families",
    [
        ("ALTER TABLE users RENAME COLUMN name TO full_name;", "transaction", ["rename_column"]),
        ("CREATE INDEX verified_orders_idx ON orders (user_id);", "transaction", ["create_index"]),
        (
            "CREATE INDEX CONCURRENTLY verified_orders_idx ON orders (user_id);",
            "autocommit",
            ["create_index"],
        ),
        (
            "ALTER TABLE orders ADD CONSTRAINT valid_amount CHECK (amount_cents >= 0) NOT VALID;\n"
            "ALTER TABLE orders VALIDATE CONSTRAINT valid_amount;\n"
            "ALTER TABLE orders DROP CONSTRAINT valid_amount, "
            "ADD CONSTRAINT valid_amount CHECK (amount_cents > -1);",
            "transaction",
            ["add_check", "validate_check", "drop_check", "add_check"],
        ),
    ],
)
def test_preflight_shapes_execute_on_pg17(
    rehearsal_project: Path,
    tmp_path: Path,
    docker_client: DockerClient,
    migration: str,
    mode: str,
    families: list[str],
) -> None:
    path = rehearsal_project / "rehearsal.yml"
    spec = yaml.safe_load(path.read_text())
    spec["migrations"][0]["transaction"] = mode
    path.write_text(yaml.safe_dump(spec))
    (rehearsal_project / "migrations/rename_user_name.sql").write_text(migration)
    with validated_environment(path, state_dir=tmp_path / "runs") as (loaded, environment):
        assert [item.family for item in loaded.classifications] == families
        container = docker_client.containers.get(environment.container_id)
        # Fixed reviewed SQL only: production user-SQL execution remains the future worker's job.
        for sql in (loaded.schema_sql.text, loaded.migration_sql[0].text):
            result = container.exec_run(
                [
                    "psql",
                    "-U",
                    "rehearse_admin",
                    "-d",
                    "rehearsal",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    sql,
                ]
            )
            assert result.exit_code == 0, result.output.decode()
    with pytest.raises(NotFound):
        docker_client.containers.get(environment.container_id)
