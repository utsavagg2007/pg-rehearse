"""Persistent scoped connections, held without an open transaction across DDL."""

from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack

import psycopg


def persistent_sessions(
    stack: ExitStack,
    connect: Callable[[], AbstractContextManager[psycopg.Connection[tuple[object, ...]]]],
    count: int,
) -> dict[str, psycopg.Connection[tuple[object, ...]]]:
    sessions = {f"old_{index + 1}": stack.enter_context(connect()) for index in range(count)}
    for connection in sessions.values():
        connection.prepare_threshold = 0
    return sessions
