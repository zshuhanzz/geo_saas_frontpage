"""Smoke tests for TopicProductRepository."""

from __future__ import annotations

import pytest

from geo_common.db import TenantIsolationError
from geo_common.services import TopicProductRepository

CID = "11111111-1111-1111-1111-111111111111"
TID = "22222222-2222-2222-2222-222222222222"
PID = "33333333-3333-3333-3333-333333333333"


@pytest.mark.asyncio
async def test_list_for_topic_filters_by_role(fake_conn, fake_pool):
    fake_conn.fetch_rows = []
    repo = TopicProductRepository(fake_pool)
    await repo.list_for_topic(CID, TID, product_role="own")
    method, sql, args = fake_conn.calls[0]
    assert "product_role = $3" in sql
    assert "is_active = true" in sql
    assert args == (CID, TID, "own")


@pytest.mark.asyncio
async def test_list_for_topic_rejects_unknown_role(fake_pool):
    repo = TopicProductRepository(fake_pool)
    with pytest.raises(ValueError):
        await repo.list_for_topic(CID, TID, product_role="nonsense")


@pytest.mark.asyncio
async def test_add_own_product_inserts_with_role_own(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": PID, "topic_id": TID, "client_id": CID,
        "product_name": "X", "match_variants": [], "product_role": "own",
        "shadow_sub_role": None, "owner_brand_id": "44444444-4444-4444-4444-444444444444", "owner_peer_id": None,
        "is_active": True, "created_at": None, "updated_at": None,
    }
    repo = TopicProductRepository(fake_pool)
    owner_brand_id = "44444444-4444-4444-4444-444444444444"
    row = await repo.add_own_product(
        CID,
        topic_id=TID,
        product_name="X",
        owner_brand_id=owner_brand_id,
    )
    assert row["product_role"] == "own"
    method, sql, args = fake_conn.calls[0]
    assert "owner_brand_id" in sql
    assert owner_brand_id in args


@pytest.mark.asyncio
async def test_replace_own_products_skips_blank_names(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": PID, "topic_id": TID, "client_id": CID,
        "product_name": "kept", "match_variants": [], "product_role": "own",
        "shadow_sub_role": None, "owner_brand_id": None, "owner_peer_id": None,
        "is_active": True, "created_at": None, "updated_at": None,
    }
    repo = TopicProductRepository(fake_pool)
    rows = await repo.replace_own_products(CID, TID, ["", "  ", "kept"])
    # 1 DELETE + 1 INSERT (only "kept" survives)
    delete_calls = [c for c in fake_conn.calls if c[0] == "execute"]
    insert_calls = [c for c in fake_conn.calls if c[0] == "fetchrow"]
    assert len(delete_calls) == 1
    assert len(insert_calls) == 1
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_remove_own_product_by_name_returns_bool(fake_conn, fake_pool):
    fake_conn.execute_result = "DELETE 1"
    repo = TopicProductRepository(fake_pool)
    assert await repo.remove_own_product_by_name(CID, TID, "X") is True
    fake_conn.execute_result = "DELETE 0"
    assert await repo.remove_own_product_by_name(CID, TID, "X") is False


@pytest.mark.asyncio
async def test_delete_by_id_detaches_historical_citations_before_product_delete(
    fake_conn, fake_pool
):
    fake_conn.fetchrow_row = {"id": PID}
    fake_conn.execute_result = "DELETE 1"
    repo = TopicProductRepository(fake_pool)

    deleted = await repo.delete_by_id(
        CID,
        PID,
        scope={"product_role": "own", "topic_id": TID},
    )

    assert deleted is True
    assert [call[0] for call in fake_conn.calls] == [
        "fetchrow",
        "execute",
        "execute",
    ]
    select_sql = fake_conn.calls[0][1]
    detach_sql = fake_conn.calls[1][1]
    delete_sql = fake_conn.calls[2][1]
    assert "FOR UPDATE" in select_sql
    assert "client_id = $1" in select_sql
    assert "UPDATE geo_citations" in detach_sql
    assert "matched_product_id = NULL" in detach_sql
    assert fake_conn.calls[1][2] == (CID, PID)
    assert "DELETE FROM geo_client_topic_products" in delete_sql


@pytest.mark.asyncio
async def test_delete_by_id_does_not_detach_when_scoped_product_is_missing(
    fake_conn, fake_pool
):
    fake_conn.fetchrow_row = None
    repo = TopicProductRepository(fake_pool)

    deleted = await repo.delete_by_id(
        CID,
        PID,
        scope={"product_role": "peer"},
    )

    assert deleted is False
    assert len(fake_conn.calls) == 1
    assert fake_conn.calls[0][0] == "fetchrow"


@pytest.mark.asyncio
async def test_tenant_decorator_enforced(fake_pool):
    repo = TopicProductRepository(fake_pool)
    with pytest.raises(TenantIsolationError):
        await repo.list_for_topic("", TID)
