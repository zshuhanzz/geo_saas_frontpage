"""Smoke tests for PersonaRepository."""

from __future__ import annotations

import pytest

from geo_common.db import TenantIsolationError
from geo_common.services import PersonaRepository

CID = "11111111-1111-1111-1111-111111111111"
PID = "66666666-6666-6666-6666-666666666666"


@pytest.mark.asyncio
async def test_list_for_client(fake_conn, fake_pool):
    fake_conn.fetch_rows = []
    repo = PersonaRepository(fake_pool)
    await repo.list_for_client(CID)
    method, sql, args = fake_conn.calls[0]
    assert "WHERE client_id = $1" in sql
    assert args == (CID,)


@pytest.mark.asyncio
async def test_add_persona_inserts(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": PID, "client_id": CID,
        "persona_name": "Buyer", "persona_description": "desc",
        "created_at": None,
    }
    repo = PersonaRepository(fake_pool)
    row = await repo.add(CID, persona_name="Buyer", persona_description="desc")
    assert row["persona_name"] == "Buyer"
    method, sql, args = fake_conn.calls[0]
    assert "INSERT INTO geo_client_personas" in sql


@pytest.mark.asyncio
async def test_update_no_op_refetches(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": PID, "client_id": CID,
        "persona_name": "Buyer", "persona_description": None,
        "created_at": None,
    }
    repo = PersonaRepository(fake_pool)
    out = await repo.update(CID, PID)
    assert out["persona_name"] == "Buyer"
    method, sql, args = fake_conn.calls[0]
    assert sql.startswith("SELECT")


@pytest.mark.asyncio
async def test_tenant_decorator_enforced(fake_pool):
    repo = PersonaRepository(fake_pool)
    with pytest.raises(TenantIsolationError):
        await repo.get_by_id("", PID)
