"""Smoke tests for PeerRepository."""

from __future__ import annotations

import pytest

from geo_common.db import TenantIsolationError
from geo_common.services import PeerRepository

CID = "11111111-1111-1111-1111-111111111111"
PID = "44444444-4444-4444-4444-444444444444"


@pytest.mark.asyncio
async def test_list_for_client_scopes_by_client_id(fake_conn, fake_pool):
    fake_conn.fetch_rows = []
    repo = PeerRepository(fake_pool)
    await repo.list_for_client(CID)
    method, sql, args = fake_conn.calls[0]
    assert "WHERE client_id = $1" in sql
    assert args == (CID,)


@pytest.mark.asyncio
async def test_add_inserts_with_aliases(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": PID, "client_id": CID, "primary_name": "Acme",
        "aliases": ["a"], "created_at": None,
    }
    repo = PeerRepository(fake_pool)
    row = await repo.add(CID, primary_name="Acme", aliases=["a"])
    assert row["primary_name"] == "Acme"
    method, sql, args = fake_conn.calls[0]
    assert "INSERT INTO geo_client_peers" in sql
    assert "Acme" in args
    assert ["a"] in args


@pytest.mark.asyncio
async def test_update_aliases_updates_only_aliases(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": PID, "client_id": CID, "primary_name": "Acme",
        "aliases": ["b"], "created_at": None,
    }
    repo = PeerRepository(fake_pool)
    out = await repo.update_aliases(CID, PID, ["b"])
    assert out["aliases"] == ["b"]
    method, sql, args = fake_conn.calls[0]
    assert "UPDATE geo_client_peers SET aliases" in sql
    assert args == (CID, PID, ["b"])


@pytest.mark.asyncio
async def test_delete_returns_bool(fake_conn, fake_pool):
    fake_conn.execute_result = "DELETE 1"
    repo = PeerRepository(fake_pool)
    assert await repo.delete(CID, PID) is True


@pytest.mark.asyncio
async def test_tenant_decorator_enforced(fake_pool):
    repo = PeerRepository(fake_pool)
    with pytest.raises(TenantIsolationError):
        await repo.get_by_id("", PID)
