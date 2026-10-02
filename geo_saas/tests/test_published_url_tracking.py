import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from routers.insights import published_url_tracking


CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_CLIENT_ID = UUID("22222222-2222-2222-2222-222222222222")
PROMPT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
PROMPT_B = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"


class FakeTrackingDatabase:
    def __init__(self):
        self.fetch_all_calls = []
        self.fetch_val_calls = []

    async def fetch_all(self, sql, params=None):
        self.fetch_all_calls.append((sql, params or {}))
        if "FROM geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        if "published_base" in sql:
            return [
                {
                    "source_url": "https://example.com/page",
                    "executed_at": None,
                    "client_prompt_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "domain_category": "Social Media",
                }
            ]
        if "FROM geo_published_urls pu" in sql:
            return [
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "title": "Tracked Page",
                    "published_url": "https://example.com/page",
                    "normalized_url": "https://example.com/page",
                    "published_at": "2026-06-01",
                    "channel": "Reddit",
                    "publish_status": "published",
                }
            ]
        return []

    async def fetch_val(self, sql, params=None):
        self.fetch_val_calls.append((sql, params or {}))
        return 1


def test_tracking_query_is_client_scoped_and_joins_prompts(monkeypatch):
    fake_db = FakeTrackingDatabase()
    monkeypatch.setattr(published_url_tracking, "database", fake_db)

    result = asyncio.run(
        published_url_tracking.get_published_url_tracking(
            client_id=CLIENT_ID,
            date_from="2026-06-04",
            date_to="2026-06-10",
        )
    )

    assert result.total == 1
    published_sql, published_params = next(
        (call_sql, call_params)
        for call_sql, call_params in fake_db.fetch_all_calls
        if "FROM geo_published_urls pu" in call_sql
    )
    citation_sql, citation_params = next(
        (call_sql, call_params)
        for call_sql, call_params in fake_db.fetch_all_calls
        if "FROM geo_citations c" in call_sql
    )
    assert "pu.client_id = :client_id" in published_sql
    assert "pu.publish_status = 'published'" in published_sql
    assert "c.client_id = :client_id" in citation_sql
    assert "JOIN geo_client_prompts cp" in citation_sql
    assert "cp.client_id = c.client_id" in citation_sql
    assert "cp.is_active = TRUE" in citation_sql
    assert "cp.intent IN (:intent_0)" in citation_sql
    assert "c.source_url = :published_candidate_exact_0" in citation_sql
    assert "c.source_url LIKE :published_candidate_query_0" in citation_sql
    assert "c.source_url LIKE :published_candidate_fragment_0" in citation_sql
    assert published_params["client_id"] == CLIENT_ID
    assert citation_params["client_id"] == CLIENT_ID
    assert citation_params["intent_0"] == "Solution Discovery"


class VariantTrackingDatabase:
    def __init__(self, source_url):
        self.source_url = source_url
        self.fetch_all_calls = []

    async def fetch_all(self, sql, params=None):
        self.fetch_all_calls.append((sql, params or {}))
        if "FROM geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        if "FROM geo_published_urls pu" in sql:
            return [{
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "title": "Tracked Page",
                "published_url": "https://example.com/page",
                "normalized_url": "https://example.com/page",
                "published_at": "2026-06-01",
                "channel": "Web",
                "publish_status": "published",
            }]
        if "FROM geo_published_url_citation_matches" in sql:
            return []
        if "MAX(c.executed_at) AS last_cited_at" in sql:
            if "c.source_url LIKE" not in sql:
                return []
            return [{
                "source_url": self.source_url,
                "domain_category": "Owned Media",
                "citation_count": 5,
                "last_cited_at": None,
            }]
        return []

    async def fetch_val(self, sql, params=None):
        return 5


def test_tracking_auto_aggregates_utm_variant_without_rewriting_citation(monkeypatch):
    fake_db = VariantTrackingDatabase("https://example.com/page?utm_source=chatgpt.com")
    monkeypatch.setattr(published_url_tracking, "database", fake_db)

    result = asyncio.run(published_url_tracking.get_published_url_tracking(
        client_id=CLIENT_ID,
        date_from="2026-06-04",
        date_to="2026-06-10",
    ))

    assert result.items[0].citation_count == 5
    assert result.items[0].candidate_count == 0


def test_tracking_keeps_meaningful_query_variant_pending(monkeypatch):
    fake_db = VariantTrackingDatabase("https://example.com/page?variant=red")
    monkeypatch.setattr(published_url_tracking, "database", fake_db)

    result = asyncio.run(published_url_tracking.get_published_url_tracking(
        client_id=CLIENT_ID,
        date_from="2026-06-04",
        date_to="2026-06-10",
    ))

    assert result.items[0].citation_count == 0
    assert result.items[0].candidate_count == 1


def test_tracking_merges_duplicate_triggered_topics_across_url_variants(monkeypatch):
    class MultiVariantTopicDatabase(VariantTrackingDatabase):
        async def fetch_all(self, sql, params=None):
            if "FROM geo_published_urls pu" in sql:
                return await super().fetch_all(sql, params)
            if "FROM geo_published_url_citation_matches" in sql:
                return []
            if "MAX(c.executed_at) AS last_cited_at" in sql:
                return [
                    {
                        "source_url": "https://example.com/page?utm_source=chatgpt.com",
                        "domain_category": "Owned Media",
                        "citation_count": 3,
                        "last_cited_at": None,
                    },
                    {
                        "source_url": "https://example.com/page?srsltid=tracking",
                        "domain_category": "Owned Media",
                        "citation_count": 2,
                        "last_cited_at": None,
                    },
                ]
            if "ct.id AS topic_id" in sql and "FROM geo_citations c" in sql:
                return [
                    {
                        "source_url": "https://example.com/page?utm_source=chatgpt.com",
                        "topic_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                        "topic_name": "Fairings",
                        "citation_count": 3,
                    },
                    {
                        "source_url": "https://example.com/page?srsltid=tracking",
                        "topic_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                        "topic_name": "Fairings",
                        "citation_count": 2,
                    },
                ]
            return []

        async def fetch_val(self, sql, params=None):
            return 5

    fake_db = MultiVariantTopicDatabase(
        "https://example.com/page?utm_source=chatgpt.com"
    )
    monkeypatch.setattr(published_url_tracking, "database", fake_db)

    result = asyncio.run(published_url_tracking.get_published_url_tracking(
        client_id=CLIENT_ID,
        date_from="2026-06-04",
        date_to="2026-06-10",
    ))

    assert result.items[0].triggered_topics == [{
        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "topic_name": "Fairings",
        "citation_count": 5,
    }]


def test_detail_uses_resolved_utm_source_urls_for_every_aggregation(monkeypatch):
    class VariantDetailDatabase:
        async def fetch_one(self, sql, params=None):
            return {
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "title": "Tracked Page",
                "published_url": "https://example.com/page",
                "normalized_url": "https://example.com/page",
                "channel": "Web",
                "publish_status": "published",
            }

        async def fetch_all(self, sql, params=None):
            if "FROM geo_published_url_citation_matches" in sql:
                return []
            if "MIN(c.executed_at) AS first_cited_at" in sql:
                return [{
                    "source_url": "https://example.com/page?utm_source=chatgpt.com",
                    "citation_count": 5,
                    "first_cited_at": None,
                    "last_cited_at": None,
                }]
            if "AS citation_day" in sql:
                if "c.source_url = ANY(:matched_source_urls::text[])" not in sql:
                    return []
                return [{
                    "citation_day": published_url_tracking.date(2026, 6, 10),
                    "domain_category": "Owned Media",
                    "platform": "chatgpt",
                    "country": "US",
                    "topic_id": None,
                    "topic_name": None,
                    "citation_count": 5,
                }]
            return []

        async def fetch_val(self, sql, params=None):
            return 0

    monkeypatch.setattr(published_url_tracking, "database", VariantDetailDatabase())
    result = asyncio.run(published_url_tracking.get_published_url_tracking_detail(
        published_url_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        client_id=CLIENT_ID,
        date_from="2026-06-04",
        date_to="2026-06-10",
        prompt_limit=10,
        prompt_offset=0,
        response_limit=10,
        response_offset=0,
    ))

    assert sum(point["citation_count"] for point in result.trend_7d) == 5


@pytest.mark.parametrize("tenant_id", [CLIENT_ID, OTHER_CLIENT_ID])
def test_main_product_and_logical_prompt_targets_scope_every_citation_aggregation(monkeypatch, tenant_id):
    fake_db = FakeTrackingDatabase()
    monkeypatch.setattr(published_url_tracking, "database", fake_db)

    asyncio.run(
        published_url_tracking.get_published_url_tracking(
            client_id=tenant_id,
            date_from="2026-06-04",
            date_to="2026-06-10",
            products="S8 MaxV",
            prompt_ids=f"{PROMPT_A},{PROMPT_B}",
        )
    )

    metric_calls = [
        (sql, params)
        for sql, params in fake_db.fetch_val_calls + fake_db.fetch_all_calls
        if "FROM geo_citations c" in sql
    ]
    assert metric_calls
    for sql, params in metric_calls:
        assert "c.client_id = :client_id" in sql
        assert "cp.client_id = :client_id" in sql
        assert "cp.client_id = c.client_id" in sql
        assert "cp.is_active = TRUE" in sql
        assert "LOWER(TRIM(COALESCE(cp.product, ''))) IN" in sql
        assert "c.client_prompt_id IN" in sql
        assert params["client_id"] == tenant_id
        assert "s8 maxv" in params.values()
        assert PROMPT_A in params.values()
        assert PROMPT_B in params.values()
        other_tenant = OTHER_CLIENT_ID if tenant_id == CLIENT_ID else CLIENT_ID
        assert other_tenant not in params.values()


@pytest.mark.parametrize("tenant_id", [CLIENT_ID, OTHER_CLIENT_ID])
def test_detail_product_and_logical_prompt_targets_scope_all_detail_aggregations(monkeypatch, tenant_id):
    class DetailDatabase(FakeTrackingDatabase):
        async def fetch_one(self, sql, params=None):
            return {
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "title": "Tracked Page",
                "published_url": "https://example.com/page",
                "normalized_url": "https://example.com/page",
                "channel": "Reddit",
                "publish_status": "published",
            }

    fake_db = DetailDatabase()
    monkeypatch.setattr(published_url_tracking, "database", fake_db)

    asyncio.run(
        published_url_tracking.get_published_url_tracking_detail(
            published_url_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            client_id=tenant_id,
            date_from="2026-06-04",
            date_to="2026-06-10",
            products="S8 MaxV",
            prompt_ids=f"{PROMPT_A},{PROMPT_B}",
            prompt_limit=10,
            prompt_offset=0,
            response_limit=10,
            response_offset=0,
        )
    )

    metric_calls = [
        (sql, params)
        for sql, params in fake_db.fetch_val_calls + fake_db.fetch_all_calls
        if "FROM geo_citations c" in sql
    ]
    assert metric_calls
    for sql, params in metric_calls:
        assert "c.client_id = :client_id" in sql
        assert "cp.client_id = :client_id" in sql
        assert "cp.client_id = c.client_id" in sql
        assert "cp.is_active = TRUE" in sql
        assert "LOWER(TRIM(COALESCE(cp.product, ''))) IN" in sql
        assert "c.client_prompt_id IN" in sql
        assert params["client_id"] == tenant_id
        other_tenant = OTHER_CLIENT_ID if tenant_id == CLIENT_ID else CLIENT_ID
        assert other_tenant not in params.values()
        assert PROMPT_A in params.values()
        assert PROMPT_B in params.values()


def test_detail_rejects_invalid_prompt_target_before_any_database_query(monkeypatch):
    class ForbiddenDatabase:
        def __getattr__(self, name):
            raise AssertionError(f"database access is forbidden: {name}")

    monkeypatch.setattr(published_url_tracking, "database", ForbiddenDatabase())
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            published_url_tracking.get_published_url_tracking_detail(
                published_url_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                client_id=CLIENT_ID,
                prompt_ids="not-a-uuid",
                prompt_limit=10,
                prompt_offset=0,
                response_limit=10,
                response_offset=0,
            )
        )
    assert exc_info.value.status_code == 422
