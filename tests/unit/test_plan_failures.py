from unittest.mock import MagicMock

import psycopg
import pytest

from pg_rehearse.models import OperationSpec
from pg_rehearse.observe.plans import capture_plan


@pytest.mark.parametrize(
    "error,closed,broken",
    [
        (psycopg.OperationalError("connection lost"), True, True),
        (psycopg.InterfaceError("connection is closed"), True, False),
        (psycopg.errors.AdminShutdown("backend terminated"), True, True),
    ],
)
def test_plan_connection_loss_reaches_worker_failure(
    error: psycopg.Error, closed: bool, broken: bool
) -> None:
    connection = MagicMock(spec=psycopg.Connection)
    connection.closed = closed
    connection.broken = broken
    settings = MagicMock()
    settings.fetchone.return_value = ("auto",)
    connection.execute.side_effect = [settings, error]
    operation = OperationSpec(id="query", sql="SELECT 1", expect={"rows": [[1]]})

    with pytest.raises(type(error)) as raised:
        capture_plan(connection, operation, analyze=False)

    assert raised.value is error
    assert connection.execute.call_args_list[0].args == ("SHOW plan_cache_mode",)
    assert len(connection.execute.call_args_list) == 2


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.UndefinedColumn("missing column"),
        psycopg.errors.QueryCanceled("statement timeout"),
        psycopg.errors.LockNotAvailable("lock timeout"),
    ],
)
def test_plan_sql_error_remains_unavailable_without_connection_loss(error: psycopg.Error) -> None:
    connection = MagicMock(spec=psycopg.Connection)
    connection.closed = False
    connection.broken = False
    settings = MagicMock()
    settings.fetchone.return_value = ("auto",)
    connection.execute.side_effect = [settings, error]
    operation = OperationSpec(id="query", sql="SELECT 1", expect={"rows": [[1]]})

    result = capture_plan(connection, operation, analyze=False)

    assert not result.success and result.raw is None and not result.committed
    assert result.error_kind == "sql_error" and result.sqlstate == error.sqlstate
    assert result.settings["plan_cache_mode"] == "auto"
