"""pytest fixtures shared across geo_common tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class FakeConn:
    """Async DB connection that records calls and returns canned rows.

    Lightweight stand-in for ``asyncpg.Connection``. The repository tests use
    this to assert that the right SQL was sent (parameterized, scoped by
    ``client_id``, etc.) without spinning up a real DB.

    Behaviour:
        - ``fetch``       → returns ``self.fetch_rows`` (list of dicts).
        - ``fetchrow``    → returns ``self.fetchrow_row`` (single dict / None).
        - ``execute``     → returns ``self.execute_result`` (str like ``'DELETE 1'``).
        - ``transaction`` → no-op async context manager.

    All calls are recorded on ``self.calls`` as ``(method, sql, args)`` tuples.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []
        self.fetch_rows: list[dict[str, Any]] = []
        self.fetchrow_row: dict[str, Any] | None = None
        self.execute_result: str = "INSERT 0 1"

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append(("fetch", sql, args))
        return list(self.fetch_rows)

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append(("fetchrow", sql, args))
        return self.fetchrow_row

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", sql, args))
        return self.execute_result

    def transaction(self):
        return _AsyncNoopCtx()


class _AsyncNoopCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    """asyncpg.Pool stand-in. ``acquire()`` returns the same FakeConn every
    call so tests can inspect ``conn.calls`` to assert SQL behaviour."""

    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def acquire(self):
        return _AsyncCtxYielding(self.conn)


class _AsyncCtxYielding:
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.fixture
def fake_conn() -> FakeConn:
    return FakeConn()


@pytest.fixture
def fake_pool(fake_conn: FakeConn) -> FakePool:
    return FakePool(fake_conn)
