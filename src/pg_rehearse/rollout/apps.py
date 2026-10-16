"""Supervise fixed reference HTTP applications inside the isolated worker container."""

import json
import os
import select
import signal
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pg_rehearse.models import ApplicationResult, ApplicationsSpec, AssertionResult
from pg_rehearse.rollout.orders_app import Version, revision
from pg_rehearse.runtime.roles import ROLE_NAMES
from pg_rehearse.workload.assertions import encoded, summarize

if TYPE_CHECKING:
    from pg_rehearse.worker_protocol import WorkerRequest


@dataclass
class Application:
    process: subprocess.Popen[bytes]
    version: Version
    port: int
    backend_pid: int
    timeout_seconds: float


def stop(app: Application) -> None:
    if app.process.poll() is None:
        try:
            os.killpg(app.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            app.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            os.killpg(app.process.pid, signal.SIGKILL)
            app.process.wait(timeout=1)
    for stream in (app.process.stdin, app.process.stdout):
        if stream:
            stream.close()


def start(stack: ExitStack, request: "WorkerRequest", version: Version) -> Application:
    process = subprocess.Popen(
        [sys.executable, "-m", "pg_rehearse.rollout.orders_app", version],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    app = Application(process, version, 0, 0, request.timeouts.application_ms / 1000)
    stack.callback(stop, app)
    if process.stdin is None or process.stdout is None:
        raise ValueError("Missing application pipes")
    settings = {
        "host": request.database_host,
        "port": 5432,
        "dbname": request.database,
        "user": ROLE_NAMES["workload"],
        "password": request.credentials["workload"].get_secret_value(),
        "connect_timeout": 3,
        "options": f"-c statement_timeout={request.timeouts.statement_ms} "
        f"-c lock_timeout={request.timeouts.lock_ms} -c search_path=public,pg_catalog",
    }
    process.stdin.write(json.dumps(settings).encode() + b"\n")
    process.stdin.close()
    if not select.select([process.stdout], [], [], 5)[0]:
        raise TimeoutError("Application readiness deadline")
    ready = json.loads(process.stdout.readline(4097))
    if (
        set(ready) != {"port", "revision", "process_id", "backend_pid"}
        or ready["revision"] != revision(version)
        or ready["process_id"] != process.pid
        or type(ready["port"]) is not int
        or not 0 < ready["port"] < 65536
        or type(ready["backend_pid"]) is not int
        or ready["backend_pid"] <= 0
    ):
        raise ValueError("Invalid application readiness")
    app.port, app.backend_pid = ready["port"], ready["backend_pid"]
    return app


def probe(
    app: Application,
    *,
    phase: str,
    actor: str,
    probe_id: str,
    path: str,
    expected: dict[str, Any],
    data: dict[str, Any] | None = None,
) -> ApplicationResult:
    result = ApplicationResult(
        probe_id=probe_id,
        phase=phase,
        version=app.version,
        actor=actor,
        revision=revision(app.version),
        success=False,
        process_id=app.process.pid,
        backend_pid=app.backend_pid,
    )
    try:
        request = Request(
            f"http://127.0.0.1:{app.port}{path}",
            data=json.dumps(data).encode() if data else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urlopen(request, timeout=app.timeout_seconds)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read(65537)
            if len(body) > 65536:
                raise ValueError("Oversized HTTP response")
            value = json.loads(body)
            result.http_status = response.code
            if (
                response.headers.get("X-Rehearse-Revision") != result.revision
                or response.headers.get("X-Rehearse-Process") != str(result.process_id)
                or response.headers.get("X-Rehearse-Backend") != str(result.backend_pid)
            ):
                raise ValueError("Mismatched application identity")
            if response.code not in {200, 201}:
                if value.get("error") == "sql_error":
                    result.error_kind, result.sqlstate = "sql_error", value.get("sqlstate")
                elif value.get("error") == "domain_error":
                    result.error_kind = "domain_error"
                else:
                    result.error_kind = "invalid_response"
                return result
            result.assertions = [
                AssertionResult(
                    name="response",
                    expected=summarize(expected),
                    actual=summarize(value),
                    passed=encoded(expected) == encoded(value),
                )
            ]
            result.success = result.assertions[0].passed
            result.error_kind = None if result.success else "assertion_error"
    except TimeoutError:
        result.error_kind = "application_deadline"
    except (URLError, OSError):
        result.error_kind = (
            "process_error" if app.process.poll() is not None else "connection_error"
        )
    except (ValueError, TypeError, AttributeError):
        result.error_kind = "invalid_response"
    finally:
        result.exit_code = app.process.poll()
    return result


def user_probe(
    app: Application, spec: ApplicationsSpec, phase: str, actor: str
) -> ApplicationResult:
    key = "name" if app.version == "deployed" else "full_name"
    return probe(
        app,
        phase=phase,
        actor=actor,
        probe_id="user.get",
        path=f"/users/{spec.user_id}",
        expected={"id": spec.user_id, key: spec.expected_name},
    )


def order_pair(
    writer: Application,
    reader: Application,
    spec: ApplicationsSpec,
    phase: str,
    offset: int,
    status: str,
) -> list[ApplicationResult]:
    order = {
        "id": spec.order_id_base + offset,
        "user_id": spec.user_id,
        "status": status,
        "amount_cents": 100,
    }
    written = probe(
        writer,
        phase=phase,
        actor=writer.version,
        probe_id=f"order.write.{offset}",
        path="/orders",
        expected=order,
        data=order,
    )
    if not written.success:
        return [written]
    return [
        written,
        probe(
            reader,
            phase=phase,
            actor=reader.version,
            probe_id=f"order.read.{offset}",
            path=f"/orders/{order['id']}",
            expected=order,
        ),
    ]


@dataclass(frozen=True)
class ApplicationCheck:
    phase: str
    actor: str
    version: Version
    probe_id: str
    expected: dict[str, Any]
    status: int = 200

    @property
    def check(self) -> str:
        return f"application/{self.phase}/{self.actor}/{self.probe_id}"


def application_plan(spec: ApplicationsSpec, task: str) -> list[ApplicationCheck]:
    def user(phase: str, actor: str, version: Version) -> ApplicationCheck:
        key = "name" if version == "deployed" else "full_name"
        return ApplicationCheck(
            phase, actor, version, "user.get", {"id": spec.user_id, key: spec.expected_name}
        )

    def pair(
        phase: str, offset: int, status: str, writer: Version, reader: Version
    ) -> list[ApplicationCheck]:
        order = {
            "id": spec.order_id_base + offset,
            "user_id": spec.user_id,
            "status": status,
            "amount_cents": 100,
        }
        return [
            ApplicationCheck(phase, writer, writer, f"order.write.{offset}", order, 201),
            ApplicationCheck(phase, reader, reader, f"order.read.{offset}", order),
        ]

    if task == "rollback":
        return [
            user("app_rollback_baseline", "old", "deployed"),
            user("app_rollback_candidate", "candidate", "candidate"),
            *pair("app_rollback", 3, spec.candidate_status, "candidate", "deployed"),
        ]
    if task != "rollout":
        raise ValueError("Unknown application experiment")
    paired = pair("app_mixed_versions", 1, "pending", "deployed", "candidate")
    paired += pair("app_mixed_versions", 2, spec.candidate_status, "candidate", "deployed")
    return [
        user("app_baseline", "old", "deployed"),
        user("app_persistent_old", "old", "deployed"),
        user("app_fresh_old", "fresh_old", "deployed"),
        user("app_candidate", "candidate", "candidate"),
        *paired,
        ApplicationCheck(
            "app_candidate_only", "candidate", "candidate", "order.get", paired[-1].expected
        ),
    ]
