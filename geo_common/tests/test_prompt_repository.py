"""Smoke tests for PromptRepository."""

from __future__ import annotations

import pytest

from geo_common.db import TenantIsolationError
from geo_common.services import PromptRepository
from geo_common.services import (
    canonical_prompt_logical_key,
    canonical_prompt_physical_key,
    canonical_prompt_text,
)

CID = "11111111-1111-1111-1111-111111111111"
PRID = "77777777-7777-7777-7777-777777777777"
OTHER_PRID = "88888888-8888-8888-8888-888888888888"


@pytest.mark.anyio
async def test_bulk_insert_on_connection_uses_one_set_based_insert_and_ordered_caller_ids():
    class BulkConn:
        def __init__(self):
            self.calls = []

        async def fetch(self, sql, *args):
            self.calls.append((sql, args))
            return [{"id": value} for value in args[1]]

    conn = BulkConn()
    ids = [PRID, OTHER_PRID]
    rows = [
        {"topic_id": PRID, "text": "A", "platform": "chatgpt", "country": "US", "language": "en-US"},
        {"topic_id": PRID, "text": "B", "platform": "gemini", "country": "US", "language": "en-US"},
    ]

    inserted = await PromptRepository(object()).bulk_insert_on_connection(CID, conn, rows, prompt_ids=ids)

    assert inserted == ids
    assert len(conn.calls) == 1
    sql, args = conn.calls[0]
    assert "INSERT INTO geo_client_prompts" in sql
    assert "UNNEST(" in sql
    assert "WITH ORDINALITY" in sql
    assert "executemany" not in sql.lower()
    assert [str(value) for value in args[1]] == ids
    assert str(args[0]) == CID


@pytest.mark.anyio
async def test_add_on_connection_uses_caller_connection_without_pool_acquire(fake_conn):
    fake_conn.fetchrow_row = {
        "id": PRID,
        "client_id": CID,
        "topic_id": OTHER_PRID,
        "text": "Prompt",
        "intent": "Solution Discovery",
        "product": None,
        "platform": "chatgpt",
        "country": "US",
        "language": "en-US",
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }

    row = await PromptRepository(object()).add_on_connection(
        CID,
        fake_conn,
        topic_id=OTHER_PRID,
        text="Prompt",
        intent="Solution Discovery",
        platform="chatgpt",
        country="US",
        language="en-US",
    )

    assert row["id"] == PRID
    assert len(fake_conn.calls) == 1
    assert fake_conn.calls[0][0] == "fetchrow"
    assert "client_id" in fake_conn.calls[0][1]


@pytest.mark.anyio
async def test_locked_write_helpers_keep_topic_and_candidate_queries_tenant_scoped(fake_conn):
    repo = PromptRepository(object())
    fake_conn.fetch_rows = [{"id": OTHER_PRID}]
    owned = await repo.owned_topic_ids_on_connection(CID, fake_conn, [OTHER_PRID])
    assert owned == {OTHER_PRID}
    _, ownership_sql, ownership_args = fake_conn.calls[-1]
    assert "client_id = $1" in ownership_sql
    assert "is_active" not in ownership_sql
    assert ownership_args[0] == CID

    fake_conn.fetch_rows = []
    candidates = await repo.physical_candidates_on_connection(
        CID,
        fake_conn,
        topic_ids=[OTHER_PRID],
        normalized_texts=["prompt"],
    )
    assert candidates == []
    _, candidate_sql, candidate_args = fake_conn.calls[-1]
    assert "client_id = $1" in candidate_sql
    assert "REGEXP_REPLACE" in candidate_sql
    assert candidate_args[0] == CID


def test_canonical_prompt_keys_collapse_spacing_and_ignore_case():
    assert canonical_prompt_text("  Best   Robot?  ") == "best robot?"
    assert canonical_prompt_logical_key(" BEST\tROBOT? ", OTHER_PRID) == (
        "best robot?",
        OTHER_PRID,
    )
    assert canonical_prompt_physical_key({
        "topic_id": OTHER_PRID,
        "text": " Best   Robot? ",
        "platform": " ChatGPT ",
        "country": " us ",
        "language": " EN-us ",
    }) == (OTHER_PRID, "best robot?", "chatgpt", "us", "en-us")


def test_canonical_prompt_text_matches_lower_contract_not_unicode_casefold():
    assert canonical_prompt_text("Straße") == "straße"
    assert canonical_prompt_text("STRASSE") == "strasse"
    assert canonical_prompt_text("Straße") != canonical_prompt_text("STRASSE")


@pytest.mark.anyio
async def test_active_prompt_keys_on_connection_use_canonical_logical_identity(fake_conn):
    fake_conn.fetch_rows = [
        {"text": " Best   Robot? ", "topic_id": OTHER_PRID},
        {"text": "best robot?", "topic_id": OTHER_PRID},
    ]

    keys = await PromptRepository(object()).active_prompt_keys_on_connection(
        CID, fake_conn
    )

    assert keys == {("best robot?", OTHER_PRID)}


@pytest.mark.anyio
async def test_active_prompt_keys_on_connection_can_exclude_updated_physical_ids(fake_conn):
    fake_conn.fetch_rows = [{"text": "Sibling Prompt", "topic_id": OTHER_PRID}]

    keys = await PromptRepository(object()).active_prompt_keys_on_connection(
        CID, fake_conn, exclude_prompt_ids=[PRID]
    )

    assert keys == {("sibling prompt", OTHER_PRID)}
    _method, sql, args = fake_conn.calls[-1]
    assert "NOT (id = ANY($2::uuid[]))" in sql
    assert args[0] == CID
    assert [str(value) for value in args[1]] == [PRID]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_list_for_client_with_topic_name_emits_join(fake_conn, fake_pool):
    fake_conn.fetch_rows = []
    repo = PromptRepository(fake_pool)
    await repo.list_for_client(CID, with_topic_name=True)
    method, sql, args = fake_conn.calls[0]
    assert "JOIN geo_client_topics t" in sql
    assert "t.topic_name" in sql
    assert args == (CID,)


@pytest.mark.anyio
async def test_list_for_client_without_join_skips_topic_table(fake_conn, fake_pool):
    fake_conn.fetch_rows = []
    repo = PromptRepository(fake_pool)
    await repo.list_for_client(CID, with_topic_name=False)
    method, sql, args = fake_conn.calls[0]
    assert "geo_client_topics" not in sql
    assert "FROM geo_client_prompts p" in sql


@pytest.mark.anyio
async def test_count_for_client(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {"n": 42}
    repo = PromptRepository(fake_pool)
    assert await repo.count_for_client(CID) == 42


@pytest.mark.anyio
async def test_list_concepts_for_client_pages_grouped_prompt_concepts(fake_conn, fake_pool):
    fake_conn.fetch_rows = [
        {
            "text": "Prompt A",
            "topic_id": PRID,
            "topic_name": "Topic A",
            "intent": "Solution Discovery",
            "product": "",
            "language": "en-US",
            "prompt_ids": [PRID],
            "countries": ["US", "CA"],
            "platforms": ["chatgpt", "gemini"],
            "final_prompt_count": 4,
            "active_final_prompt_count": 4,
            "inactive_final_prompt_count": 0,
            "created_at": None,
            "updated_at": None,
        }
    ]
    repo = PromptRepository(fake_pool)
    rows = await repo.list_concepts_for_client(
        CID,
        is_active=True,
        limit=5,
        offset=10,
        with_topic_name=True,
    )
    assert rows[0]["final_prompt_count"] == 4
    method, sql, args = fake_conn.calls[0]
    assert method == "fetch"
    assert "GROUP BY" in sql
    assert "p.text" in sql
    assert "ARRAY_AGG(p.id" in sql
    assert "COUNT(*) AS final_prompt_count" in sql
    assert "JOIN geo_client_topics t" in sql
    assert "LIMIT $3 OFFSET $4" in sql
    assert args == (CID, True, 5, 10)


@pytest.mark.anyio
async def test_count_concepts_for_client_counts_grouped_prompt_concepts(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {"n": 9}
    repo = PromptRepository(fake_pool)
    assert await repo.count_concepts_for_client(CID, is_active=False) == 9
    method, sql, args = fake_conn.calls[0]
    assert method == "fetchrow"
    assert "SELECT COUNT(*) AS n FROM (" in sql
    assert "GROUP BY" in sql
    assert "p.text" in sql
    assert args == (CID, False)


@pytest.mark.anyio
async def test_count_active_for_client_filters_active(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {"n": 5}
    repo = PromptRepository(fake_pool)
    assert await repo.count_active_for_client(CID) == 5
    method, sql, args = fake_conn.calls[0]
    assert "is_active = true" in sql


@pytest.mark.anyio
async def test_count_active_unique_for_client_counts_text_topic_pairs(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {"n": 5}
    repo = PromptRepository(fake_pool)
    assert await repo.count_active_unique_for_client(CID) == 5
    method, sql, args = fake_conn.calls[0]
    assert "SELECT DISTINCT text, topic_id" in sql
    assert "is_active = true" in sql
    assert args == (CID,)


@pytest.mark.anyio
async def test_active_prompt_keys_for_client_returns_text_topic_pairs(fake_conn, fake_pool):
    fake_conn.fetch_rows = [
        {"text": "Prompt A", "topic_id": "topic-1"},
        {"text": "Prompt B", "topic_id": "topic-2"},
    ]
    repo = PromptRepository(fake_pool)
    assert await repo.active_prompt_keys_for_client(CID) == {
        ("prompt a", "topic-1"),
        ("prompt b", "topic-2"),
    }
    method, sql, args = fake_conn.calls[0]
    assert "SELECT DISTINCT text, topic_id" in sql
    assert "is_active = true" in sql
    assert args == (CID,)


@pytest.mark.anyio
async def test_resolve_concept_is_tenant_scoped_and_normalizes_logical_key(fake_conn, fake_pool):
    representative = {
        "id": PRID,
        "client_id": CID,
        "topic_id": "22222222-2222-2222-2222-222222222222",
        "text": "  Best   Robot Vacuum ",
        "intent": "solution discovery",
        "product": "  S8 MaxV  ",
        "platform": "chatgpt",
        "country": "US",
        "language": "EN-us",
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }

    class SequentialConn(type(fake_conn)):
        async def fetchrow(self, sql, *args):
            self.calls.append(("fetchrow", sql, args))
            if "geo_clients" in sql:
                return {"config_languages": ["en-US", "de-DE"]}
            return representative

        async def fetch(self, sql, *args):
            self.calls.append(("fetch", sql, args))
            if "geo_global_intents" in sql:
                return [
                    {"intent_name": "solution discovery"},
                    {"intent_name": "Solution Discovery"},
                    {"intent_name": "SOLUTION DISCOVERY"},
                ]
            return [{"id": PRID}, {"id": OTHER_PRID}]

    conn = SequentialConn()
    repo = PromptRepository(type(fake_pool)(conn))
    resolved = await repo.resolve_concept_by_prompt_id(CID, PRID)

    assert resolved is not None
    assert resolved["representative"]["intent"] == "SOLUTION DISCOVERY"
    assert resolved["representative"]["language"] == "en-US"
    assert resolved["prompt_ids"] == [PRID, OTHER_PRID]
    first_method, first_sql, first_args = conn.calls[0]
    assert first_method == "fetchrow"
    assert "WHERE client_id = $1 AND id = $2" in first_sql
    assert first_args == (CID, PRID)
    language_method, language_sql, language_args = conn.calls[1]
    assert language_method == "fetchrow"
    assert "FROM geo_clients WHERE id = $1" in language_sql
    assert language_args == (CID,)
    variant_method, variant_sql, variant_args = conn.calls[3]
    assert variant_method == "fetch"
    assert "p.client_id = $1" in variant_sql
    assert "REGEXP_REPLACE(TRIM(p.text)" in variant_sql
    assert "LOWER(TRIM(COALESCE(p.product" in variant_sql
    assert "LOWER(TRIM(COALESCE(p.language" in variant_sql
    assert "p.platform" not in variant_sql
    assert "p.country" not in variant_sql
    assert "p.is_active = TRUE" in variant_sql
    assert variant_args[0] == CID
    assert variant_args[4] == "en-us"
    assert "de-DE" not in variant_args


@pytest.mark.anyio
async def test_resolve_concept_preserves_case_for_unconfigured_historical_intent(fake_conn, fake_pool):
    representative = {
        "id": PRID,
        "client_id": CID,
        "topic_id": "22222222-2222-2222-2222-222222222222",
        "text": "Prompt",
        "intent": " Legacy Intent ",
        "product": None,
        "language": "en-US",
    }

    class SequentialConn(type(fake_conn)):
        async def fetchrow(self, sql, *args):
            self.calls.append(("fetchrow", sql, args))
            if "geo_clients" in sql:
                return {"config_languages": []}
            return representative

        async def fetch(self, sql, *args):
            self.calls.append(("fetch", sql, args))
            return [] if "geo_global_intents" in sql else [{"id": PRID}]

    conn = SequentialConn()
    repo = PromptRepository(type(fake_pool)(conn))
    resolved = await repo.resolve_concept_by_prompt_id(CID, PRID)

    assert resolved["representative"]["intent"] == "Legacy Intent"
    _method, variant_sql, variant_args = conn.calls[3]
    assert "TRIM(COALESCE(p.intent, ''))" in variant_sql
    assert "TRIM(COALESCE(p.language, '')) = $5" in variant_sql
    assert "LOWER(TRIM(COALESCE(p.language" not in variant_sql
    assert variant_args[-1] == "Legacy Intent"


@pytest.mark.anyio
async def test_resolve_concept_keeps_unconfigured_language_case_sensitive(fake_conn, fake_pool):
    representative = {
        "id": PRID,
        "client_id": CID,
        "topic_id": "22222222-2222-2222-2222-222222222222",
        "text": "Prompt",
        "intent": "Solution Discovery",
        "product": None,
        "language": " EN-us ",
    }

    class SequentialConn(type(fake_conn)):
        async def fetchrow(self, sql, *args):
            self.calls.append(("fetchrow", sql, args))
            if "geo_clients" in sql:
                return {"config_languages": ["de-DE"]}
            return representative

        async def fetch(self, sql, *args):
            self.calls.append(("fetch", sql, args))
            return (
                [{"intent_name": "Solution Discovery"}]
                if "geo_global_intents" in sql
                else [{"id": PRID}]
            )

    conn = SequentialConn()
    repo = PromptRepository(type(fake_pool)(conn))
    resolved = await repo.resolve_concept_by_prompt_id(CID, PRID)

    assert resolved["representative"]["language"] == "EN-us"
    _method, variant_sql, variant_args = conn.calls[3]
    assert "TRIM(COALESCE(p.language, '')) = $5" in variant_sql
    assert variant_args[4] == "EN-us"


@pytest.mark.anyio
async def test_resolve_concept_returns_none_without_variant_queries(fake_conn, fake_pool):
    fake_conn.fetchrow_row = None
    repo = PromptRepository(fake_pool)
    assert await repo.resolve_concept_by_prompt_id(CID, PRID) is None
    assert len(fake_conn.calls) == 1


@pytest.mark.anyio
async def test_update_no_op_returns_existing_row(fake_conn, fake_pool):
    fake_conn.fetchrow_row = {
        "id": PRID, "client_id": CID, "topic_id": PRID,
        "text": "x", "intent": None, "product": None,
        "platform": "p", "country": "c", "language": "en",
        "is_active": True, "created_at": None, "updated_at": None,
    }
    repo = PromptRepository(fake_pool)
    out = await repo.update(CID, PRID, updates={})
    assert out["text"] == "x"


@pytest.mark.anyio
async def test_update_many_updates_prompt_ids_in_one_statement(fake_conn, fake_pool):
    fake_conn.execute_result = "UPDATE 3"
    repo = PromptRepository(fake_pool)
    n = await repo.update_many(
        CID,
        [PRID, PRID, PRID],
        updates={"is_active": False, "ignored": "nope"},
    )
    assert n == 3
    method, sql, args = fake_conn.calls[0]
    assert method == "execute"
    assert "id = ANY($2::uuid[])" in sql
    assert "is_active = $3" in sql
    assert "ignored" not in sql
    assert args == (CID, [PRID, PRID, PRID], False)


@pytest.mark.anyio
async def test_update_many_empty_short_circuits(fake_pool):
    repo = PromptRepository(fake_pool)
    assert await repo.update_many(CID, [], updates={"is_active": False}) == 0


@pytest.mark.anyio
async def test_delete_many_passes_uuid_array_param(fake_conn, fake_pool):
    fake_conn.execute_result = "DELETE 3"
    repo = PromptRepository(fake_pool)
    n = await repo.delete_many(CID, [PRID, PRID, PRID])
    assert n == 3
    method, sql, args = fake_conn.calls[0]
    assert "ANY($2::uuid[])" in sql
    assert isinstance(args[1], list)


@pytest.mark.anyio
async def test_delete_many_empty_short_circuits(fake_pool):
    repo = PromptRepository(fake_pool)
    assert await repo.delete_many(CID, []) == 0


@pytest.mark.anyio
async def test_tenant_decorator_enforced(fake_pool):
    repo = PromptRepository(fake_pool)
    with pytest.raises(TenantIsolationError):
        await repo.list_for_client("nope")
