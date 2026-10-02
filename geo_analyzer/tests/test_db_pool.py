"""
Phase 2.5b — async asyncpg pool boundary tests.

Validates the analyzer's ``src/core/database.py`` lifecycle helpers and the
new async pipeline boundaries (Phase 0 / Phase 3) without spinning up a real
DB. Uses the same ``FakeConn`` / ``FakePool`` pattern as
``geo_common/tests/conftest.py`` so the tests are deterministic and run in
under a millisecond.

Why this exists
---------------
After flipping every DB call from sync SQLAlchemy ``conn.execute(text(...))``
to ``await conn.fetch("..." , $1, ...)``, we need integration-shaped tests
that catch the worst regression mode: a future change reverting a phase to
sync I/O without the test suite noticing. Each test here asserts that the
target function is a coroutine AND that it actually issues the expected
asyncpg call shape (``$``-placeholders, positional args, ``await fetch /
fetchrow / execute``).
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import asyncpg
import pytest

import src.core.database as db
from src.pipeline.phase0_load_config import load_client_config
from src.pipeline.phase3_write import write_batch, WriteCounts
from src.pipeline.phase1_per_result_parse import BatchParseResult


# ---------------------------------------------------------------------------
# Local FakeConn / FakePool (mirrors geo_common/tests/conftest.py shape but
# kept module-local so analyzer tests don't depend on geo_common's fixtures
# being importable from here).
# ---------------------------------------------------------------------------


class FakeConn:
    """Async DB connection stand-in. Records calls and returns canned rows."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []
        # Default queue can be overridden per test by setting one of these:
        self.fetch_rows_queue: list[list[dict]] = []
        self.fetchrow_row: dict | None = None
        self.fetchval_value: Any = 0
        self.execute_result: str = "INSERT 0 1"

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        self.calls.append(("fetch", sql, args))
        if self.fetch_rows_queue:
            return self.fetch_rows_queue.pop(0)
        return []

    async def fetchrow(self, sql: str, *args: Any) -> dict | None:
        self.calls.append(("fetchrow", sql, args))
        return self.fetchrow_row

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetchval", sql, args))
        return self.fetchval_value

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
    """asyncpg.Pool stand-in. ``acquire()`` always yields the same FakeConn."""

    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.closed = False

    def acquire(self):
        return _AsyncCtxYielding(self.conn)

    async def close(self) -> None:
        self.closed = True


class _AsyncCtxYielding:
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


# ---------------------------------------------------------------------------
# Test 1 — Pool lifecycle: connect → get_pool → disconnect is idempotent and
# uses the shared geo_common factory with the JSONB init callback.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pool_lifecycle_uses_shared_factory_and_init_codec():
    """``db.connect()`` must call ``geo_common.create_asyncpg_pool`` with the
    JSONB ``init`` callback wired in, and ``disconnect()`` must close+null the
    module-level pool."""
    fake_pool = FakePool(FakeConn())
    captured_kwargs: dict = {}

    async def fake_create_pool(settings, **kwargs):
        captured_kwargs.update(kwargs)
        return fake_pool

    # Reset the module-level pool to ensure connect() actually creates one.
    db._pool = None  # type: ignore[attr-defined]

    with patch("src.core.database.create_asyncpg_pool", side_effect=fake_create_pool):
        pool = await db.connect()
        assert pool is fake_pool
        # Same pool returned on subsequent connect() (idempotent).
        pool2 = await db.connect()
        assert pool2 is fake_pool
        # The shared factory was called with init=_init_connection so the
        # JSONB codec is registered for every pooled connection.
        assert "init" in captured_kwargs
        assert captured_kwargs["init"] is db._init_connection
        # Default min/max sizes preserve the analyzer's small-job profile.
        assert captured_kwargs["min_size"] == 1
        assert captured_kwargs["max_size"] == 5

        # get_pool() returns the live pool now that connect() has run.
        assert db.get_pool() is fake_pool

        await db.disconnect()
        assert fake_pool.closed is True
        # Pool reset to None so a fresh connect() builds a new one.
        assert db._pool is None  # type: ignore[attr-defined]

        # Calling get_pool() after disconnect must raise — caller must
        # connect() first.
        with pytest.raises(RuntimeError, match="Database pool not initialized"):
            db.get_pool()


# ---------------------------------------------------------------------------
# Test 2 — JSONB codec function is registered correctly.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_connection_registers_json_and_jsonb_codecs():
    """``_init_connection`` must register a Python-dict ↔ jsonb codec on every
    pooled connection so reads return Python objects (not raw text) and
    writes accept dicts directly. Both ``json`` and ``jsonb`` typenames are
    registered so tests + production behave the same regardless of column
    declaration."""
    registered: list[tuple[str, str]] = []

    class FakeRegConn:
        async def set_type_codec(self, typename, *, encoder, decoder, schema):
            registered.append((typename, schema))
            # Sanity-check the codec round-trips: encoder(decoder(x)) == x.
            sample = {"a": 1, "b": [2, 3]}
            encoded = encoder(sample)
            decoded = decoder(encoded)
            assert decoded == sample

    await db._init_connection(FakeRegConn())  # type: ignore[arg-type]
    assert ("json", "pg_catalog") in registered
    assert ("jsonb", "pg_catalog") in registered


# ---------------------------------------------------------------------------
# Test 3 — Phase 0 loaders are async + emit positional asyncpg queries scoped
# by client_id.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_client_config_uses_async_asyncpg_with_positional_client_id():
    """Phase 0 must hit asyncpg with ``$1 = client_id`` for every loader, and
    must be a coroutine (regression guard against accidentally re-syncing
    the loader by removing ``await``)."""
    assert inspect.iscoroutinefunction(load_client_config), (
        "load_client_config must remain async — Phase 2.5b boundary"
    )

    conn = FakeConn()
    # Five empty result sets, one for each loader (brands, peers, products,
    # domains, tracked_urls). Order matches load_client_config().
    conn.fetch_rows_queue = [[], [], [], [], []]
    client_id = "client-uuid-aaa"

    config = await load_client_config(conn, client_id)

    # Every fetch call must be parameterized with the client_id positional.
    fetch_calls = [c for c in conn.calls if c[0] == "fetch"]
    assert len(fetch_calls) == 5, "Expected 5 loaders, one per related table"
    for kind, sql, args in fetch_calls:
        assert "$1" in sql, f"Phase 0 loader SQL missing $-placeholder: {sql[:120]}"
        assert args == (client_id,), (
            f"Phase 0 loader must scope to client_id positional arg, got {args}"
        )

    # Empty config still emits valid empty lists / set.
    assert config.brands == []
    assert config.peers == []
    assert config.tracked_products == []
    assert config.domains == []
    assert config.tracked_urls == []
    assert config.owned_domain_strs == []


@pytest.mark.asyncio
async def test_tracked_product_owner_joins_are_tenant_scoped_and_role_scoped():
    conn = FakeConn()
    conn.fetch_rows_queue = [[], [], [], [], []]

    await load_client_config(conn, "client-uuid-aaa")

    product_sql = next(
        sql for kind, sql, _args in conn.calls
        if kind == "fetch" and "FROM geo_client_topic_products tp" in sql
    )
    assert "cb.client_id = tp.client_id" in product_sql
    assert "cp.client_id = tp.client_id" in product_sql
    assert "cb.is_active = true" in product_sql
    assert "cb.is_shadow = false" in product_sql
    assert "cb.is_shadow = true" in product_sql
    assert "cb.id AS owner_brand_id" in product_sql
    assert "cp.id AS owner_peer_id" in product_sql
    assert "tp.product_role = 'peer' OR tp.shadow_sub_role = 'resale'" in product_sql

    tracked_url_sql = next(
        sql for kind, sql, _args in conn.calls
        if kind == "fetch" and "FROM geo_product_tracked_urls ptu" in sql
    )
    assert "tp.client_id = ptu.client_id" in tracked_url_sql
    assert "tp.is_active = true" in tracked_url_sql
    assert "cb.client_id = ptu.client_id" in tracked_url_sql
    assert "cp.client_id = ptu.client_id" in tracked_url_sql
    assert "cb.id AS brand_id" in tracked_url_sql
    assert "cp.id AS peer_id" in tracked_url_sql

    domain_sql = next(
        sql for kind, sql, _args in conn.calls
        if kind == "fetch" and "FROM geo_client_domains d" in sql
    )
    assert "cb.client_id = d.client_id" in domain_sql
    assert "cp.client_id = d.client_id" in domain_sql
    assert "cb.id AS brand_id" in domain_sql
    assert "cp.id AS peer_id" in domain_sql


# ---------------------------------------------------------------------------
# Test 4 — Phase 3 write_batch is async + issues raw asyncpg INSERTs with
# $-placeholders (no SQLAlchemy text() wrappers, no :name colon-binds).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_batch_uses_async_asyncpg_dollar_placeholders():
    """Phase 3 INSERTs must use ``$N`` placeholders (asyncpg) and pass row
    fields positionally. Catches the bug class where someone leaves a stray
    SQLAlchemy ``:name`` colon-bind in the SQL."""
    assert inspect.iscoroutinefunction(write_batch), (
        "write_batch must be async — Phase 2.5b boundary"
    )

    conn = FakeConn()
    # The production writer now protects against analyzer jobs racing a
    # prompt deletion. This test exercises the live-prompt write path, so the
    # existence check must succeed instead of inheriting FakeConn's default 0.
    conn.fetchval_value = 1

    fake_result = {
        "client_prompt_id": uuid4(),
        "task_id": uuid4(),
        "result_id": 42,
        "client_id": uuid4(),
        "ingested_at": "2026-04-26T12:00:00Z",
    }
    parse_result = BatchParseResult()
    parse_result.per_result.append((
        fake_result,
        # one brand mention, one product mention, one citation
        [{"brand_name": "Roborock", "brand_role": "own", "mention_position": 1}],
        [{
            "product_id": uuid4(),
            "product_name": "S8 MaxV",
            "product_role": "own",
            "shadow_sub_role": None,
            "owner_brand_id": None,
            "owner_brand_name": None,
            "owner_peer_id": None,
            "owner_peer_name": None,
            "mention_position": 1,
        }],
        [{
            "source_url": "https://example.com/a",
            "source_domain": "example.com",
            "source_position": 1,
            "source_label": None,
            "is_citation_pill": False,
            "citation_role": None,
            "matched_brand_id": None,
            "matched_product_id": None,
            "matched_peer_id": None,
        }],
    ))

    counts = await write_batch(conn, parse_result, {"example.com": "Earned Media"})

    prompt_guard_calls = [c for c in conn.calls if c[0] == "fetchval"]
    assert len(prompt_guard_calls) == 1
    _, guard_sql, guard_args = prompt_guard_calls[0]
    assert "client_id = $1::uuid" in guard_sql
    assert "id = $2::uuid" in guard_sql
    assert guard_args == (
        str(fake_result["client_id"]),
        str(fake_result["client_prompt_id"]),
    )

    # One brand insert + one product insert + one citation insert + one
    # results UPDATE = 4 execute() calls.
    execute_calls = [c for c in conn.calls if c[0] == "execute"]
    assert len(execute_calls) == 4

    # Every SQL must use $-placeholders, NEVER SQLAlchemy ``:name`` style.
    for kind, sql, args in execute_calls:
        assert "$1" in sql, f"asyncpg SQL must use $-placeholders: {sql[:120]}"
        assert ":client_id" not in sql, (
            f"Stray SQLAlchemy ``:name`` colon-bind found in asyncpg SQL: {sql[:120]}"
        )
        assert ":result_id" not in sql, (
            f"Stray SQLAlchemy ``:name`` colon-bind found: {sql[:120]}"
        )
        assert "text(" not in sql, (
            f"SQL still wrapped in SQLAlchemy text(): {sql[:120]}"
        )

    # WriteCounts arithmetic intact.
    assert counts.brand_mentions == 1
    assert counts.product_mentions == 1
    assert counts.citations == 1


# ---------------------------------------------------------------------------
# Test 5 — parse_affected matches collector's command-tag parsing (regression
# guard for the ``"UPDATE 7"`` → 7 contract).
# ---------------------------------------------------------------------------

def test_parse_affected_handles_command_tags_and_garbage():
    assert db.parse_affected("UPDATE 7") == 7
    assert db.parse_affected("DELETE 0") == 0
    assert db.parse_affected("INSERT 0 1") == 1
    assert db.parse_affected("") == 0
    assert db.parse_affected("garbage") == 0
    # Empty / None → 0, never raises.
    assert db.parse_affected(None) == 0  # type: ignore[arg-type]
