"""Maintained reference HTTP orders application; two fixed application revisions."""

import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Literal

import psycopg

Version = Literal["deployed", "candidate"]


def revision(version: str) -> str:
    return f"orders-{version}-" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def serve(version: Version) -> int:
    # Only workload connection settings arrive via stdin, never argv or the environment.
    settings = json.loads(sys.stdin.buffer.readline(16384))
    if set(settings) != {
        "host",
        "port",
        "dbname",
        "user",
        "password",
        "options",
        "connect_timeout",
    }:
        return 3
    if settings["user"] != "rehearse_workload":
        return 3
    with psycopg.connect(
        **settings,
        autocommit=True,
        prepare_threshold=0,
        application_name=f"orders/{version}",
        sslmode="disable",
        passfile="/dev/null",
    ) as connection:
        name_column = "name" if version == "deployed" else "full_name"
        statuses = {"pending", "complete", "cancelled"}
        if version == "candidate":
            statuses.add("processing")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def respond(self, status: int, body: dict[str, Any]) -> None:
                payload = json.dumps(body, allow_nan=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("X-Rehearse-Revision", revision(version))
                self.send_header("X-Rehearse-Process", str(os.getpid()))
                self.send_header("X-Rehearse-Backend", str(connection.info.backend_pid))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                try:
                    parts = self.path.strip("/").split("/")
                    if len(parts) != 2 or parts[0] not in {"users", "orders"}:
                        self.respond(404, {"error": "not_found"})
                        return
                    identifier = int(parts[1])
                    if parts[0] == "users":
                        # These are fixed revision-specific queries; user input is always bound.
                        query = (
                            "SELECT id,name FROM users WHERE id=%s"
                            if version == "deployed"
                            else "SELECT id,full_name FROM users WHERE id=%s"
                        )
                        row = connection.execute(query, [identifier]).fetchone()
                        self.respond(
                            200, {"id": row[0], name_column: row[1]}
                        ) if row else self.respond(404, {"error": "not_found"})
                    else:
                        row = connection.execute(
                            "SELECT id,user_id,status,amount_cents FROM orders WHERE id=%s",
                            [identifier],
                        ).fetchone()
                        if row is None:
                            self.respond(404, {"error": "not_found"})
                        elif row[2] not in statuses or not isinstance(row[3], int) or row[3] < 0:
                            self.respond(422, {"error": "domain_error"})
                        else:
                            self.respond(
                                200,
                                dict(
                                    zip(
                                        ("id", "user_id", "status", "amount_cents"),
                                        row,
                                        strict=True,
                                    )
                                ),
                            )
                except ValueError:
                    self.respond(400, {"error": "invalid_request"})
                except psycopg.Error as exc:
                    self.respond(500, {"error": "sql_error", "sqlstate": exc.sqlstate})

            def do_POST(self) -> None:
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if self.path != "/orders" or not 0 < size <= 4096:
                        self.respond(400, {"error": "invalid_request"})
                        return
                    value = json.loads(self.rfile.read(size))
                    fields = {"id", "user_id", "status", "amount_cents"}
                    if (
                        not isinstance(value, dict)
                        or set(value) != fields
                        or any(type(value[key]) is not int for key in fields - {"status"})
                        or value["status"] not in statuses
                        or value["amount_cents"] < 0
                    ):
                        self.respond(422, {"error": "domain_error"})
                        return
                    connection.execute(
                        "INSERT INTO orders (id,user_id,status,amount_cents) VALUES (%s,%s,%s,%s)",
                        [value[key] for key in ("id", "user_id", "status", "amount_cents")],
                    )
                    self.respond(201, value)  # Autocommit completes before the response is sent.
                except (ValueError, TypeError):
                    self.respond(400, {"error": "invalid_request"})
                except psycopg.Error as exc:
                    self.respond(500, {"error": "sql_error", "sqlstate": exc.sqlstate})

        server = HTTPServer(("127.0.0.1", 0), Handler)
        print(
            json.dumps(
                {
                    "port": server.server_port,
                    "revision": revision(version),
                    "process_id": os.getpid(),
                    "backend_pid": connection.info.backend_pid,
                }
            ),
            flush=True,
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    try:
        selected = sys.argv[1]
        if selected not in {"deployed", "candidate"}:
            raise ValueError("Unknown revision")
        raise SystemExit(serve("deployed" if selected == "deployed" else "candidate"))
    except Exception:
        raise SystemExit(3) from None
