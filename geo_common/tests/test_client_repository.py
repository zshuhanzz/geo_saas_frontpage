"""Smoke tests for ClientRepository.

ClientRepository is intentionally NOT tenant-scoped — it operates above
the tenant scope (admin god-mode). These tests verify it does NOT enforce
``@tenant_scoped`` and that its methods build the expected SQL shapes.
"""

from __future__ import annotations

import pytest

from geo_common.services import ClientRepository

CID_A = "11111111-1111-1111-1111-111111111111"
CID_B = "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_list_all_no_search_returns_alphabetical(fake_conn, fake_pool):
    fake_conn.fetch_rows = []
    repo = ClientRepository(fake_pool)
    await repo.list_all()
    method, sql, args = fake_conn.calls[0]
    assert "ORDER BY name" in sql
    assert args == ()


@pytest.mark.asyncio
async def test_list_all_with_search_emits_ilike(fake_conn, fake_pool):
    fake_conn.fetch_rows = []
    repo = ClientRepository(fake_pool)
    await repo.list_all(search="Tmax")
    method, sql, args = fake_conn.calls[0]
    assert "ILIKE $1" in sql
    assert args == ("%Tmax%",)


@pytest.mark.asyncio
async def test_get_by_id_does_not_use_tenant_decorator(fake_conn, fake_pool):
    """Even a too-short id should NOT raise — we are deliberately above
    the tenant scope here, no @tenant_scoped enforcement."""
    fake_conn.fetchrow_row = None
    repo = ClientRepository(fake_pool)
    out = await repo.get_by_id("short")
    assert out is None  # no exception raised


@pytest.mark.asyncio
async def test_add_uses_provided_pools(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": CID_A, "name": "Tmax", "client_prompt_quota": 50,
        "aliases": [], "config_countries": [], "config_platforms": [],
        "config_languages": [], "cron_collector": None, "cron_analyzer": None,
        "cron_llm_discovery": None, "agent_daily_token_quota": 1,
        "agent_rpm_limit": 1, "onboarding_wizard_completed": False,
        "created_at": None, "updated_at": None,
    }
    repo = ClientRepository(fake_pool)
    row = await repo.add(name="Tmax")
    assert row["name"] == "Tmax"
    method, sql, args = fake_conn.calls[0]
    assert "INSERT INTO geo_clients" in sql
    insert_columns = sql.split("VALUES", 1)[0]
    assert "aliases" not in insert_columns
    assert len(args) == 8


@pytest.mark.asyncio
async def test_update_cannot_write_legacy_aliases(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": CID_A,
        "name": "Tmax",
        "aliases": [],
    }

    await ClientRepository(fake_pool).update(
        CID_A,
        updates={"aliases": ["must-not-write"]},
    )

    method, sql, args = fake_conn.calls[0]
    assert method == "fetchrow"
    assert sql.startswith("SELECT")
    assert "UPDATE geo_clients" not in sql
    assert args == (CID_A,)


@pytest.mark.asyncio
async def test_fetch_related_collections_groups_by_client_id(fake_conn, fake_pool):
    """Verify the per-table grouping path. Each fetch is mocked to return
    rows with two distinct client_ids; the grouping should preserve that."""

    # Override fetch to return different rows depending on the SQL string.
    real_fetch = fake_conn.fetch

    rows_for = {
        "geo_client_peers":    [{"id": "p1", "client_id": CID_A, "primary_name": "x", "aliases": [], "created_at": None}],
        "geo_client_domains":  [{"id": "d1", "client_id": CID_B, "domain": "y.com", "is_primary": False, "domain_scope": "whole", "brand_id": None, "peer_id": None, "created_at": None}],
        "geo_client_topics":   [{"id": "t1", "client_id": CID_A, "topic_name": "tx", "topic_type": "semantic_topic", "created_at": None}],
        "geo_client_personas": [],
    }

    async def routed_fetch(sql, *args):
        for table, rows in rows_for.items():
            if table in sql:
                fake_conn.calls.append(("fetch", sql, args))
                return list(rows)
        return await real_fetch(sql, *args)

    fake_conn.fetch = routed_fetch  # type: ignore[assignment]

    repo = ClientRepository(fake_pool)
    out = await repo.fetch_related_collections([CID_A, CID_B])

    assert list(out["peers"][CID_A][0])
    assert out["domains"][CID_B][0]["domain"] == "y.com"
    assert out["topics"][CID_A][0]["topic_name"] == "tx"
    assert out["personas"] == {}


@pytest.mark.asyncio
async def test_fetch_related_collections_empty_short_circuits(fake_pool):
    repo = ClientRepository(fake_pool)
    out = await repo.fetch_related_collections([])
    assert out == {"peers": {}, "domains": {}, "topics": {}, "personas": {}}


@pytest.mark.asyncio
async def test_delete_returns_bool(fake_conn, fake_pool):
    fake_conn.execute_result = "DELETE 1"
    repo = ClientRepository(fake_pool)
    assert await repo.delete(CID_A) is True
    fake_conn.execute_result = "DELETE 0"
    assert await repo.delete(CID_A) is False
