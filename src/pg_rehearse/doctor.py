"""Read-only environment checks; never create or remove Docker resources."""

import importlib.metadata
import platform
import sys
from dataclasses import dataclass

import docker
from docker.errors import DockerException


@dataclass(frozen=True)
class Diagnostic:
    name: str
    passed: bool
    detail: str


def check_environment(*, skip_docker: bool = False) -> list[Diagnostic]:
    checks = [
        Diagnostic("Python", sys.version_info >= (3, 12), platform.python_version()),
    ]
    for dependency in ("typer", "rich", "pydantic", "PyYAML", "psycopg", "docker"):
        try:
            version = importlib.metadata.version(dependency)
            checks.append(Diagnostic(dependency, True, version))
        except importlib.metadata.PackageNotFoundError:
            checks.append(Diagnostic(dependency, False, "Not installed in the active environment"))
    if not skip_docker:
        client = None
        try:
            client = docker.from_env(timeout=5)
            client.ping()
            version = client.version().get("Version", "unknown")
            checks.append(Diagnostic("Docker daemon", True, f"Reachable; server {version}"))
        except (DockerException, OSError) as exc:
            checks.append(
                Diagnostic("Docker daemon", False, f"Unavailable. Start Docker Desktop. {exc}")
            )
        finally:
            if client is not None:
                client.close()
    return checks
