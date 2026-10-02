"""Smoke tests for DomainRepository."""

from __future__ import annotations

import pytest

from geo_common.db import TenantIsolationError
from geo_common.services import DomainRepository

CID = "11111111-1111-1111-1111-111111111111"
DID = "55555555-5555-5555-5555-555555555555"


@pytest.mark.asyncio
async def test_list_for_client_filter_scope(fake_conn, fake_pool):
    fake_conn.fetch_rows = []
    repo = DomainRepository(fake_pool)
    await repo.list_for_client(CID, scope="whole")
    method, sql, args = fake_conn.calls[0]
    assert "domain_scope = $2" in sql
    assert args == (CID, "whole")


@pytest.mark.asyncio
async def test_add_passes_brand_and_peer_to_db_for_check_constraint(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": DID, "client_id": CID, "domain": "x.com",
        "is_primary": False, "domain_scope": "whole",
        "brand_id": None, "peer_id": None, "created_at": None,
    }
    repo = DomainRepository(fake_pool)
    # Both brand_id and peer_id passed — repository does NOT validate; the
    # DB CHECK constraint owns that invariant.
    await repo.add(CID, domain="x.com", brand_id="b", peer_id="p")
    method, sql, args = fake_conn.calls[0]
    assert "INSERT INTO geo_client_domains" in sql
    assert "b" in args and "p" in args


@pytest.mark.asyncio
async def test_domain_owner_map_strips_www_prefix(fake_conn, fake_pool):
    fake_conn.fetch_rows = [
        {"domain": "WWW.Foo.com", "brand_id": "b1", "peer_id": None},
        {"domain": "bar.com", "brand_id": None, "peer_id": "p1"},
        {"domain": "", "brand_id": None, "peer_id": None},
    ]
    repo = DomainRepository(fake_pool)
    out = await repo.domain_owner_map(CID)
    assert out == {"foo.com": ("b1", None), "bar.com": (None, "p1")}


@pytest.mark.asyncio
async def test_update_no_op_returns_existing_row(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": DID, "client_id": CID, "domain": "x.com",
        "is_primary": False, "domain_scope": "whole",
        "brand_id": None, "peer_id": None, "created_at": None,
    }
    repo = DomainRepository(fake_pool)
    out = await repo.update(CID, DID, updates={})
    assert out["domain"] == "x.com"
    method, sql, args = fake_conn.calls[0]
    assert sql.startswith("SELECT")  # No UPDATE issued for empty patch.


@pytest.mark.asyncio
async def test_tenant_decorator_enforced(fake_pool):
    repo = DomainRepository(fake_pool)
    with pytest.raises(TenantIsolationError):
        await repo.get_by_id("bad", DID)
