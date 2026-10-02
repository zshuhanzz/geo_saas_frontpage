"""
Tests for ``db.py`` — the asyncpg-backed compatibility surface (admin side).

Mirror of ``geo_saas/tests/test_db_adapter.py``: the admin and saas modules
each carry an independent copy of the named-parameter shim, so a regression
in one will not be caught by the other's test suite. This file exercises the
admin copy explicitly.

What the tests guarantee:
    * ``:name`` → ``$N`` rewriting is positional-correct, deduped, and order-stable.
    * Repeated occurrences of the same name reuse the first slot.
    * Missing param names raise a clear ``KeyError`` instead of silently
      passing the wrong arg count to asyncpg.
    * PostgreSQL ``::TYPE`` casts (date / uuid / jsonb) are NOT mistaken for
      named params — guarded by the ``(?<!:)`` lookbehind in the regex.
    * ``database.fetch_all`` / ``fetch_one`` / ``fetch_val`` / ``execute`` go
      through the shim and forward positional args to the underlying connection.
"""
from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def anyio_backend():
    """Restrict anyio-backed async tests to asyncio only — trio isn't installed."""
    return "asyncio"


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []
        self.fetch_rows: list[Any] = []
        self.fetchrow_row: Any = None
        self.fetchval_value: Any = None
        self.execute_result: str = "INSERT 0 1"

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return list(self.fetch_rows)

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.fetchrow_row

    async def fetchval(self, sql, *args, column=0):
        self.calls.append(("fetchval", sql, args))
        return self.fetchval_value

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return self.execute_result


class _AcquireCM:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AcquireCM(self.conn)

    async def close(self):
        return None


# ---------------------------------------------------------------------------
# _named_to_positional
# ---------------------------------------------------------------------------


def test_named_to_positional_basic():
    """Single-name substitution: ``:client_id`` → ``$1`` with one arg."""
    from db import _named_to_positional

    sql, args = _named_to_positional(
        "SELECT * FROM geo_clients WHERE id = :client_id",
        {"client_id": "abc-123"},
    )
    assert sql == "SELECT * FROM geo_clients WHERE id = $1"
    assert args == ["abc-123"]


def test_named_to_positional_multiple_distinct():
    """Distinct names are assigned positional slots in first-seen order."""
    from db import _named_to_positional

    sql, args = _named_to_positional(
        "SELECT * FROM t WHERE a = :a AND b = :b AND c = :c",
        {"a": 1, "b": 2, "c": 3},
    )
    assert sql == "SELECT * FROM t WHERE a = $1 AND b = $2 AND c = $3"
    assert args == [1, 2, 3]


def test_named_to_positional_repeated_name_reuses_slot():
    """Repeating ``:client_id`` reuses ``$1`` instead of allocating a fresh
    slot — matches asyncpg's "two refs to $1 mean the same value" semantics
    and keeps the args list compact.
    """
    from db import _named_to_positional

    sql, args = _named_to_positional(
        "UPDATE t SET a = :v, b = :v WHERE id = :id",
        {"v": 99, "id": "abc"},
    )
    assert sql == "UPDATE t SET a = $1, b = $1 WHERE id = $2"
    assert args == [99, "abc"]


def test_named_to_positional_missing_param_raises():
    """SQL referencing a name not present in params dict is a programmer
    error — surface a KeyError instead of letting asyncpg fail with an
    inscrutable "expected N args, got M" message.
    """
    from db import _named_to_positional

    with pytest.raises(KeyError):
        _named_to_positional(
            "SELECT * FROM t WHERE id = :missing",
            {"present": 1},
        )


def test_named_to_positional_no_params_returns_sql_unchanged():
    """When values is None / empty, the SQL is returned untouched and args
    is empty. Lets call sites pass positional ``$1`` SQL through the same
    helper without rewriting.
    """
    from db import _named_to_positional

    sql, args = _named_to_positional("SELECT NOW()", None)
    assert sql == "SELECT NOW()"
    assert args == []


def test_named_to_positional_skips_postgres_double_colon_cast():
    """Regression: ``::TYPE`` casts are PostgreSQL syntax, NOT named params.

    Before the ``(?<!:)`` lookbehind, a query like
    ``WHERE created_at >= '2026-04-20'::date`` would be parsed as referencing
    a named param ``date`` and blow up with KeyError. Many admin endpoints
    (analysis metrics, prompts list, token usage) rely on date / uuid / jsonb
    casts — without this guard the entire admin surface 500s on every call.
    """
    from db import _named_to_positional

    sql, args = _named_to_positional(
        "SELECT * FROM geo_results WHERE created_at >= :date_from::date "
        "AND created_at < :date_to::date AND id = :rid::uuid",
        {"date_from": "2026-04-20", "date_to": "2026-04-26", "rid": "abc-uuid"},
    )
    # The ``::date`` / ``::uuid`` casts MUST be preserved verbatim — they
    # are PG type cast operators, not parameter references.
    assert "::date" in sql
    assert "::uuid" in sql
    # The actual named params (single colon) ARE rewritten in order.
    assert sql == (
        "SELECT * FROM geo_results WHERE created_at >= $1::date "
        "AND created_at < $2::date AND id = $3::uuid"
    )
    assert args == ["2026-04-20", "2026-04-26", "abc-uuid"]


def test_named_to_positional_handles_jsonb_cast():
    """``::jsonb`` is heavily used in admin's geo_workflow_config and
    geo_brand_profiles routers — guard explicitly.
    """
    from db import _named_to_positional

    sql, args = _named_to_positional(
        "SELECT * FROM t WHERE meta @> :needle::jsonb",
        {"needle": '{"k":"v"}'},
    )
    assert sql == "SELECT * FROM t WHERE meta @> $1::jsonb"
    assert args == ['{"k":"v"}']


# ---------------------------------------------------------------------------
# database.fetch_*/execute integration with FakePool
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_database_fetch_all_routes_through_shim(monkeypatch):
    """``database.fetch_all`` should rewrite ``:name`` → ``$N`` and forward
    the ordered args to ``conn.fetch``.
    """
    from db import database

    fake_conn = FakeConn()
    fake_conn.fetch_rows = [{"id": "abc", "brand_name": "Acme"}]
    pool = FakePool(fake_conn)

    monkeypatch.setattr(database, "_pool", pool)

    rows = await database.fetch_all(
        "SELECT id, brand_name FROM geo_client_brands WHERE client_id = :cid",
        {"cid": "tenant-1"},
    )
    assert rows == [{"id": "abc", "brand_name": "Acme"}]
    assert fake_conn.calls == [(
        "fetch",
        "SELECT id, brand_name FROM geo_client_brands WHERE client_id = $1",
        ("tenant-1",),
    )]


@pytest.mark.anyio
async def test_database_fetch_one_routes_through_shim(monkeypatch):
    """admin uses ``fetch_one`` (which maps to ``conn.fetchrow``) — verify
    the shim is on this path too.
    """
    from db import database

    fake_conn = FakeConn()
    fake_conn.fetchrow_row = {"id": "abc"}
    pool = FakePool(fake_conn)
    monkeypatch.setattr(database, "_pool", pool)

    row = await database.fetch_one(
        "SELECT id FROM geo_clients WHERE id = :cid",
        {"cid": "tenant-1"},
    )
    assert row == {"id": "abc"}
    assert fake_conn.calls[0][0] == "fetchrow"
    assert fake_conn.calls[0][1] == "SELECT id FROM geo_clients WHERE id = $1"
    assert fake_conn.calls[0][2] == ("tenant-1",)


@pytest.mark.anyio
async def test_database_fetch_val_routes_through_shim(monkeypatch):
    from db import database

    fake_conn = FakeConn()
    fake_conn.fetchval_value = 42
    pool = FakePool(fake_conn)
    monkeypatch.setattr(database, "_pool", pool)

    val = await database.fetch_val(
        "SELECT COUNT(*) FROM geo_client_prompts WHERE client_id = :cid",
        {"cid": "tenant-1"},
    )
    assert val == 42
    assert fake_conn.calls[0][0] == "fetchval"
    assert "$1" in fake_conn.calls[0][1]
    assert fake_conn.calls[0][2] == ("tenant-1",)


@pytest.mark.anyio
async def test_database_execute_routes_through_shim(monkeypatch):
    from db import database

    fake_conn = FakeConn()
    pool = FakePool(fake_conn)
    monkeypatch.setattr(database, "_pool", pool)

    result = await database.execute(
        "DELETE FROM geo_client_prompts WHERE id = :id AND client_id = :cid",
        {"id": "p1", "cid": "tenant-1"},
    )
    assert result == "INSERT 0 1"  # FakeConn's stubbed default
    assert fake_conn.calls[0][2] == ("p1", "tenant-1")
