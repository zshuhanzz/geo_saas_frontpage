"""Contract tests for canonical brand Alias persistence."""

from __future__ import annotations

import pytest

from geo_common.services import BrandRepository


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_list_for_client_returns_active_own_and_shadow_brands(fake_conn, fake_pool):
    fake_conn.fetch_rows = [
        {
            "id": "brand-own",
            "client_id": "client-12345678",
            "brand_name": "Acme",
            "aliases": ["ACME"],
            "is_shadow": False,
            "is_active": True,
        },
        {
            "id": "brand-shadow",
            "client_id": "client-12345678",
            "brand_name": "Retailer",
            "aliases": [],
            "is_shadow": True,
            "is_active": True,
        },
    ]

    rows = await BrandRepository(fake_pool).list_for_client(
        "client-12345678",
        include_shadow=True,
        only_active=True,
    )

    assert [row["id"] for row in rows] == ["brand-own", "brand-shadow"]
    method, sql, args = fake_conn.calls[-1]
    assert method == "fetch"
    assert "client_id = $1" in sql
    assert "is_active = true" in sql
    assert "is_shadow = false" not in sql
    assert args == ("client-12345678",)


@pytest.mark.anyio
async def test_update_aliases_normalizes_and_preserves_first_spelling(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": "brand-12345678",
        "client_id": "client-12345678",
        "brand_name": "Acme",
        "aliases": ["Alpha", "Beta"],
        "is_shadow": False,
        "is_active": True,
    }

    await BrandRepository(fake_pool).update_aliases(
        "client-12345678",
        "brand-12345678",
        ["  Alpha  ", "", "alpha", " BETA ", "beta", "   "],
    )

    method, sql, args = fake_conn.calls[-1]
    assert method == "fetchrow"
    assert "UPDATE geo_client_brands" in sql
    assert "WHERE client_id = $1 AND id = $2" in sql
    assert "geo_clients" not in sql.replace("geo_client_brands", "")
    assert args == ("client-12345678", "brand-12345678", ["Alpha", "BETA"])


@pytest.mark.anyio
async def test_update_aliases_accepts_empty_array_as_clear(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": "brand-12345678",
        "client_id": "client-12345678",
        "brand_name": "Acme",
        "aliases": [],
        "is_shadow": False,
        "is_active": True,
    }

    row = await BrandRepository(fake_pool).update_aliases(
        "client-12345678",
        "brand-12345678",
        [],
    )

    assert row is not None
    assert fake_conn.calls[-1][2][2] == []


@pytest.mark.anyio
async def test_update_aliases_on_connection_reuses_caller_transaction(fake_conn):
    fake_conn.fetchrow_row = {
        "id": "brand-12345678",
        "client_id": "client-12345678",
        "brand_name": "Acme",
        "aliases": ["Alpha"],
        "is_shadow": False,
        "is_active": True,
    }

    class PoolThatMustNotBeUsed:
        def acquire(self):
            raise AssertionError("connection-aware update must not acquire the pool")

    row = await BrandRepository(PoolThatMustNotBeUsed()).update_aliases_on_connection(
        "client-12345678",
        "brand-12345678",
        [" Alpha ", "alpha"],
        conn=fake_conn,
    )

    assert row is not None
    assert fake_conn.calls[-1][2] == (
        "client-12345678",
        "brand-12345678",
        ["Alpha"],
    )
