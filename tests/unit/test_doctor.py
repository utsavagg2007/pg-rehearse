from typing import Any

import pytest
from docker.errors import DockerException

from pg_rehearse.doctor import check_environment


def test_unavailable_daemon_is_a_failed_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(**kwargs: Any) -> None:
        raise DockerException("test daemon is unavailable")

    monkeypatch.setattr("pg_rehearse.doctor.docker.from_env", unavailable)
    checks = check_environment()
    assert not checks[-1].passed
    assert "Start Docker Desktop" in checks[-1].detail


def test_docker_client_is_closed_on_probe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        closed = False

        def ping(self) -> None:
            raise DockerException("readiness failed")

        def close(self) -> None:
            self.closed = True

    client = Client()
    monkeypatch.setattr("pg_rehearse.doctor.docker.from_env", lambda **kwargs: client)
    checks = check_environment()
    assert not checks[-1].passed
    assert client.closed


def test_skipping_docker_does_not_contact_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**kwargs: Any) -> None:
        raise AssertionError("Docker must not be contacted when skipped")

    monkeypatch.setattr("pg_rehearse.doctor.docker.from_env", forbidden)
    assert all(check.passed for check in check_environment(skip_docker=True))
