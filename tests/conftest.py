import shutil
from pathlib import Path

import docker
import pytest
from docker import DockerClient


@pytest.fixture
def rehearsal_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/orders", project)
    return project


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-docker", action="store_true", help="Run real PostgreSQL lifecycle tests"
    )


@pytest.fixture(scope="session")
def docker_client(request: pytest.FixtureRequest) -> DockerClient:
    if not request.config.getoption("--run-docker"):
        pytest.skip("Use --run-docker for real PostgreSQL lifecycle tests")
    client = docker.from_env(timeout=5)
    client.ping()
    # Deliberately fail if the requested integration environment is not prepared.
    client.images.get("postgres:17")
    request.addfinalizer(client.close)
    return client
