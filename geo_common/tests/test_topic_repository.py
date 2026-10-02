"""Smoke tests for TopicRepository — SQL shape + tenant invariant."""

from __future__ import annotations

import pytest

from geo_common.db import TenantIsolationError
from geo_common.services import TopicRepository

CID = "11111111-1111-1111-1111-111111111111"
TID = "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_list_for_client_scopes_by_client_id(fake_conn, fake_pool):
    fake_conn.fetch_rows = [
        {"id": TID, "client_id": CID, "topic_name": "t", "topic_type": "semantic_topic", "created_at": None}
    ]
    repo = TopicRepository(fake_pool)
    rows = await repo.list_for_client(CID)
    assert rows[0]["topic_name"] == "t"
    method, sql, args = fake_conn.calls[0]
    assert method == "fetch"
    assert "WHERE client_id = $1" in sql
    assert args == (CID,)


@pytest.mark.asyncio
async def test_tenant_decorator_rejects_short_client_id(fake_pool):
    repo = TopicRepository(fake_pool)
    with pytest.raises(TenantIsolationError):
        await repo.list_for_client("short")


@pytest.mark.asyncio
async def test_add_validates_topic_type(fake_pool):
    repo = TopicRepository(fake_pool)
    with pytest.raises(ValueError):
        await repo.add(CID, topic_name="x", topic_type="bogus")


@pytest.mark.asyncio
async def test_add_returns_inserted_row(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": TID,
        "client_id": CID,
        "topic_name": "foo",
        "topic_type": "semantic_topic",
        "created_at": None,
    }
    repo = TopicRepository(fake_pool)
    row = await repo.add(CID, topic_name="foo")
    assert row["topic_name"] == "foo"
    method, sql, args = fake_conn.calls[0]
    assert method == "fetchrow"
    assert "INSERT INTO geo_client_topics" in sql
    assert CID in args
    assert "foo" in args


@pytest.mark.asyncio
async def test_delete_returns_true_on_match(fake_conn, fake_pool):
    fake_conn.execute_result = "DELETE 1"
    repo = TopicRepository(fake_pool)
    assert await repo.delete(CID, TID) is True
    fake_conn.execute_result = "DELETE 0"
    assert await repo.delete(CID, TID) is False


@pytest.mark.asyncio
async def test_existing_names_lower_normalizes_case_and_whitespace(fake_conn, fake_pool):
    fake_conn.fetch_rows = [
        {"topic_name": " Hello "},
        {"topic_name": "WORLD"},
        {"topic_name": ""},
    ]
    repo = TopicRepository(fake_pool)
    out = await repo.existing_names_lower(CID)
    assert out == {"hello", "world", ""}
