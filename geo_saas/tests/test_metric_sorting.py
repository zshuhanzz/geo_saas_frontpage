from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from routers.insights import citations, cited_domains, cited_pages, published_url_tracking, visibility
from routers.insights.sorting import (
    InvalidSortKey,
    InvalidSortOrder,
    resolve_sort,
    sort_complete_rows,
)


@pytest.mark.parametrize(
    ("list_type", "metric", "expected_expression", "expected_tie"),
    [
        ("citation_domains", "citation_count", "citation_count", "domain"),
        ("citation_pages", "share_pct", "share_pct", "url"),
        ("published_url_tracking", "change_count", "change_count", "published_url"),
        ("visibility_ranking_prompts", "total_mentions", "COUNT(*)", "MIN(cp.text)"),
        ("topic_visibility", "own_sov_pct", "own_sov_pct", "topic_name"),
        ("product_visibility", "visibility_pct", "visibility_pct", "pm.product_name"),
        ("product_visibility", "avg_position", "AVG(pm.mention_position)", "pm.product_name"),
        ("sentiment_themes", "occurrence_count", "occurrence_count", "theme_name"),
        ("sentiment_theme_results", "positive_percentage", "positive_percentage", "st.id"),
        ("prompt_metrics", "visibility_score", "visibility_score", "prompt_id"),
    ],
)
def test_resolve_sort_uses_server_owned_fragments(list_type, metric, expected_expression, expected_tie):
    resolved = resolve_sort(list_type, metric, "asc")

    assert expected_expression in resolved.expression
    assert expected_tie in resolved.tie_breaker
    assert resolved.direction == "ASC"
    assert "NULLS LAST" in resolved.order_by_sql
    assert resolved.order_by_sql.endswith("ASC")


def test_default_sort_preserves_existing_domain_order():
    resolved = resolve_sort("citation_domains", None, None)

    assert resolved.sort_by == "citation_count"
    assert resolved.sort_order == "desc"
    assert resolved.order_by_sql == "citation_count DESC NULLS LAST, LOWER(domain) ASC, domain ASC"


@pytest.mark.parametrize(
    ("list_type", "dimension_key"),
    [
        ("citation_domains", "domain"),
        ("citation_pages", "url"),
        ("topic_visibility", "topic_name"),
        ("product_visibility", "product_name"),
        ("sentiment_themes", "theme_name"),
        ("prompt_metrics", "prompt_text"),
    ],
)
def test_dimension_sort_keys_are_rejected(list_type, dimension_key):
    with pytest.raises(InvalidSortKey):
        resolve_sort(list_type, dimension_key, "asc")


@pytest.mark.parametrize("sort_order", ["ascending", "DESC NULLS FIRST", "", "Asc"])
def test_sort_order_is_strictly_validated(sort_order):
    with pytest.raises(InvalidSortOrder):
        resolve_sort("citation_domains", "citation_count", sort_order)


def test_complete_row_sort_is_null_last_stable_and_does_not_mutate_input():
    rows = [
        {"domain": "Zulu.example", "change_pct": None},
        {"domain": "beta.example", "change_pct": 2.0},
        {"domain": "Alpha.example", "change_pct": 2.0},
        {"domain": "omega.example", "change_pct": -1.0},
    ]

    sorted_rows = sort_complete_rows("citation_domains", rows, "change_pct", "desc")

    assert [row["domain"] for row in sorted_rows] == [
        "Alpha.example",
        "beta.example",
        "omega.example",
        "Zulu.example",
    ]
    assert rows[0]["domain"] == "Zulu.example"


def test_regular_metrics_keep_their_default_directions():
    assert resolve_sort("visibility_visibility_ranking", "visibility_pct", None).sort_order == "desc"


@pytest.mark.parametrize("list_type", [
    "visibility_visibility_ranking",
    "visibility_sov_ranking",
    "visibility_position_ranking",
    "citation_domains",
    "citation_pages",
    "published_url_tracking",
])
def test_presentation_rank_is_not_a_user_sort_metric(list_type):
    with pytest.raises(InvalidSortKey):
        resolve_sort(list_type, "rank", "asc")


def test_visibility_endpoint_allowlists_are_metric_specific():
    assert resolve_sort("visibility_visibility_ranking", "visibility_pct", "desc")
    assert resolve_sort("visibility_sov_ranking", "sov_pct", "desc")
    assert resolve_sort("visibility_position_ranking", "avg_position", "asc")
    with pytest.raises(InvalidSortKey):
        resolve_sort("visibility_visibility_ranking", "avg_position", "asc")
    with pytest.raises(InvalidSortKey):
        resolve_sort("visibility_sov_ranking", "visibility_pct", "desc")
    with pytest.raises(InvalidSortKey):
        resolve_sort("visibility_position_ranking", "sov_pct", "desc")


def test_duplicate_normalized_text_uses_unique_identity_tie():
    rows = [
        {"domain": "example.com", "citation_count": 2, "row_id": "a"},
        {"domain": "EXAMPLE.com", "citation_count": 2, "row_id": "b"},
    ]
    ordered = sort_complete_rows("citation_domains", rows, "citation_count", "desc")
    assert [row["row_id"] for row in ordered] == ["b", "a"]


@pytest.mark.parametrize(
    ("module", "endpoint", "kind", "row", "item_attr"),
    [
        (
            cited_domains, cited_domains.get_cited_domains, "domain",
            {"rank": 6, "domain": "stable.example", "domain_category": "Editorial", "citation_count": 4, "share_pct": 12.5, "change_pct": -2.5},
            "domains",
        ),
        (
            cited_pages, cited_pages.get_cited_pages,
            "page",
            {"rank": 6, "url": "https://stable.example/page", "domain": "stable.example", "domain_category": "Editorial", "citation_count": 4, "share_pct": 12.5, "change_pct": -2.5},
            "pages",
        ),
    ],
)
@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_cited_lists_use_sql_cte_sort_and_return_only_requested_page(
    monkeypatch, module, endpoint, kind, row, item_attr, sort_order
):
    class CteDatabase:
        def __init__(self):
            self.calls = []

        async def fetch_all(self, sql, params=None):
            self.calls.append(("fetch_all", sql, params or {}))
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "FROM metrics" in sql:
                return [{
                    **row,
                    "is_own": False,
                    "total_unique": 12,
                    "total_citations": 32,
                }]
            return []

        async def fetch_one(self, sql, params=None):
            self.calls.append(("fetch_one", sql, params or {}))
            if "total_unique" in sql:
                return {"total_unique": 12, "total_citations": 32, "previous_total_citations": 20}
            return None

        async def fetch_val(self, sql, params=None):
            raise AssertionError("CTE implementation must not issue legacy full-universe fetch_val queries")

    db = CteDatabase()
    monkeypatch.setattr(module, "database", db)
    result = asyncio.run(endpoint(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-01", date_to="2026-05-02",
        products="S8 MaxV", prompt_ids="11111111-1111-1111-1111-111111111111",
        sort_by="change_pct", sort_order=sort_order, limit=1, offset=5,
    ))
    items = getattr(result, item_attr)
    assert len(items) == 1 and items[0].rank == 6
    assert (result.total_unique_domains if kind == "domain" else result.total_unique_pages) == 12
    page_sql, page_params = next(
        (sql, params) for method, sql, params in db.calls
        if method == "fetch_all"
        and (
            "FROM metrics" in sql
        )
    )
    assert "COUNT(*) FILTER" in page_sql
    assert "LEFT JOIN previous_" not in page_sql
    assert f"ORDER BY change_pct {sort_order.upper()} NULLS LAST" in page_sql
    assert page_sql.index("ORDER BY change_pct") < page_sql.index("LIMIT :limit")
    assert page_params["limit"] == 1 and page_params["offset"] == 5
    assert page_params["target_product_0"] == "s8 maxv"
    assert page_params["target_prompt_0"] == "11111111-1111-1111-1111-111111111111"


def test_cited_pages_fast_and_combined_paths_use_legacy_rounded_share_delta():
    source = Path(__file__).parents[1].joinpath("src/routers/insights/cited_pages.py").read_text()
    assert "candidate.share_pct\n                        - ROUND(" in source
    assert (
        "ROUND(ca.citation_count::numeric / NULLIF(ct.total_citations, 0) * 100, 2)\n"
        "                        - ROUND(ca.previous_citation_count::numeric / pt.total_citations * 100, 2)"
    ) in source


def test_invalid_sort_is_422_and_fails_before_database_execution(monkeypatch):
    class ExplodingDatabase:
        async def fetch_all(self, *_args, **_kwargs):
            raise AssertionError("database must not be reached")

        async def fetch_val(self, *_args, **_kwargs):
            raise AssertionError("database must not be reached")

    monkeypatch.setattr(cited_domains, "database", ExplodingDatabase())
    app = FastAPI()
    app.include_router(cited_domains.router, prefix="/api/insights")

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/api/insights/cited-domains",
                params={
                    "client_id": "b0e10518-5f70-426f-b09e-dbe025984ba1",
                    "sort_by": "domain",
                    "sort_order": "asc",
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 422
    assert "Unsupported metric" in response.json()["detail"]


def test_visibility_composite_payload_sorts_each_metric_list_independently(monkeypatch):
    class VisibilityDatabase:
        async def fetch_all(self, sql, params=None):
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            return []

    def row(name, rank, mentions, visibility_pct, sov_pct, avg_position):
        return {
            "company_name": name, "brand_name": name, "rank": rank,
            "mention_count": mentions, "visibility_pct": visibility_pct,
            "sov_pct": sov_pct, "avg_position": avg_position, "is_own": name == "A",
        }

    async def query_visibility(*_args, **_kwargs):
        rows = [row("A", 1, 10, 20, 40, 3), row("B", 2, 5, 80, 20, 1)]
        return {
            "visibility_score": 20, "own_rank": 1, "mentioned": 1, "total_query": 5,
            "own_sov": 40, "own_sov_rank": 1, "total_mentions": 15, "own_mentions": 10,
            "own_avg_position": 3, "own_avg_position_rank": 2,
            "sov_ranking": [dict(item) for item in rows],
            "visibility_ranking": [dict(item) for item in rows],
            "position_ranking": [dict(item) for item in rows],
            "time_series": [], "avg_position_series": [],
        }

    monkeypatch.setattr(visibility, "database", VisibilityDatabase())
    monkeypatch.setattr(visibility, "_query_visibility", query_visibility)
    result = asyncio.run(visibility.get_visibility(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-01", date_to="2026-05-02", interval="daily", include_matrix=False,
        sort_by="visibility_pct", sort_order="asc",
        sov_sort_by="sov_pct", sov_sort_order="desc",
    ))

    assert [item.brand_name for item in result.visibility_ranking] == ["A", "B"]
    assert [item.brand_name for item in result.sov_ranking] == ["A", "B"]
    assert [item.brand_name for item in result.position_ranking] == ["B", "A"]


def test_citation_composite_payload_sorts_domain_page_category_independently(monkeypatch):
    class CitationDatabase:
        async def fetch_all(self, sql, params=None):
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            return []

    async def query_citations(*_args, **_kwargs):
        return {
            "total_citations": 10, "own_citation_count": 0, "own_share": 0,
            "own_rank": None, "domain_lookup": {}, "time_series": [],
            "domain_ranking": [
                {"domain": "a.example", "citation_count": 8, "share_pct": 80, "is_own": False},
                {"domain": "b.example", "citation_count": 2, "share_pct": 20, "is_own": False},
            ],
            "page_ranking": [
                {"url": "https://a.example", "domain": "a.example", "citation_count": 8, "share_pct": 80},
                {"url": "https://b.example", "domain": "b.example", "citation_count": 2, "share_pct": 20},
            ],
            "category_breakdown": [
                {"label": "Editorial", "count": 8, "pct": 80},
                {"label": "Social", "count": 2, "pct": 20},
            ],
        }

    async def previous_lookup(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(citations, "database", CitationDatabase())
    monkeypatch.setattr(citations, "_query_citations", query_citations)
    monkeypatch.setattr(citations, "_query_citation_domain_share_lookup", previous_lookup)
    result = asyncio.run(citations.get_citations(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-01", date_to="2026-05-02", interval="daily",
        sort_by="citation_count", sort_order="asc",
        page_sort_by="citation_count", page_sort_order="desc",
        category_sort_by="pct", category_sort_order="asc",
    ))

    assert [item.domain for item in result.domain_ranking] == ["b.example", "a.example"]
    assert [item.rank for item in result.domain_ranking] == [2, 1]
    assert [item.url for item in result.page_ranking] == ["https://a.example", "https://b.example"]
    assert [item.rank for item in result.page_ranking] == [1, 2]
    assert [item.label for item in result.category_breakdown] == ["Social", "Editorial"]


def test_published_main_sorts_full_universe_before_python_pagination(monkeypatch):
    class PublishedDatabase:
        async def fetch_all(self, sql, params=None):
            if "FROM geo_published_urls pu" in sql:
                return [
                    {"id": "00000000-0000-0000-0000-000000000001", "title": "Z", "published_url": "https://z.example", "normalized_url": "https://z.example", "channel": "Web", "publish_status": "published", "published_at": "2026-05-01"},
                    {"id": "00000000-0000-0000-0000-000000000002", "title": "A", "published_url": "https://a.example", "normalized_url": "https://a.example", "channel": "Web", "publish_status": "published", "published_at": "2026-05-01"},
                    {"id": "00000000-0000-0000-0000-000000000003", "title": "M", "published_url": "https://m.example", "normalized_url": "https://m.example", "channel": "Web", "publish_status": "published", "published_at": "2026-05-01"},
                ]
            if "MAX(c.executed_at) AS last_cited_at" in sql:
                return [
                    {"source_url": "https://z.example", "domain_category": "Editorial", "citation_count": 1, "last_cited_at": None},
                    {"source_url": "https://a.example", "domain_category": "Editorial", "citation_count": 3, "last_cited_at": None},
                    {"source_url": "https://m.example", "domain_category": "Editorial", "citation_count": 2, "last_cited_at": None},
                ]
            return []

        async def fetch_val(self, sql, params=None):
            return 6

    monkeypatch.setattr(published_url_tracking, "database", PublishedDatabase())
    result = asyncio.run(published_url_tracking.get_published_url_tracking(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-01", date_to="2026-05-02",
        sort_by="citation_count", sort_order="asc", limit=1, offset=1,
    ))
    assert result.total == 3
    assert [item.published_url for item in result.items] == ["https://m.example"]


def test_published_detail_generic_targets_prompt_and_scoped_topic_validates_before_db(monkeypatch):
    class DetailDatabase:
        def __init__(self):
            self.calls = []

        async def fetch_one(self, sql, params=None):
            self.calls.append((sql, params or {}))
            return {
                "id": "00000000-0000-0000-0000-000000000001", "title": "Page",
                "published_url": "https://example.com", "normalized_url": "https://example.com",
                "channel": "Web", "publish_status": "published",
            }

        async def fetch_all(self, sql, params=None):
            self.calls.append((sql, params or {}))
            return []

        async def fetch_val(self, sql, params=None):
            self.calls.append((sql, params or {}))
            return 0

    db = DetailDatabase()
    monkeypatch.setattr(published_url_tracking, "database", db)
    asyncio.run(published_url_tracking.get_published_url_tracking_detail(
        published_url_id=UUID("00000000-0000-0000-0000-000000000001"),
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-01", date_to="2026-05-02",
        sort_by="citation_count", sort_order="asc",
        topic_sort_by="citation_count", topic_sort_order="desc",
        prompt_limit=10, prompt_offset=0, response_limit=10, response_offset=0,
    ))
    prompt_sql, prompt_params = next(
        (sql, params) for sql, params in db.calls if "MIN(cp.id::text) AS client_prompt_id" in sql
    )
    assert prompt_sql.index("ORDER BY") < prompt_sql.index("LIMIT :prompt_limit")
    assert "COUNT(*) ASC NULLS LAST" in prompt_sql
    assert prompt_params["client_id"] == UUID("b0e10518-5f70-426f-b09e-dbe025984ba1")


@pytest.mark.parametrize(
    ("list_type", "metric", "tie_fields"),
    [
        ("visibility_visibility_ranking", "visibility_pct", {"brand_name": "Alpha"}),
        ("visibility_sov_ranking", "sov_pct", {"brand_name": "Alpha"}),
        ("visibility_position_ranking", "avg_position", {"brand_name": "Alpha"}),
        ("visibility_matrix_groups", "total_mentions", {"group_name": "Alpha", "group_key": "group-a"}),
        ("visibility_matrix_prompts", "total_mentions", {"prompt_text": "Alpha", "prompt_id": "prompt-a"}),
        ("visibility_matrix_brands", "mention_count", {"company_name": "Alpha"}),
        ("topic_visibility", "mention_count", {"topic_name": "Alpha", "topic_id": "topic-a"}),
        ("product_visibility", "mention_count", {"product_name": "Alpha", "owner_brand_name": "Brand", "owner_peer_name": "", "shadow_sub_role": ""}),
        ("citation_domains", "citation_count", {"domain": "alpha.example"}),
        ("citation_pages", "citation_count", {"url": "https://alpha.example", "domain": "alpha.example"}),
        ("citation_categories", "count", {"label": "Alpha"}),
        ("published_url_tracking", "citation_count", {"published_url": "https://alpha.example", "published_url_id": "00000000-0000-0000-0000-000000000001"}),
        ("published_url_prompts", "citation_count", {"client_prompt_text": "Alpha", "client_prompt_id": "00000000-0000-0000-0000-000000000001"}),
        ("published_url_topics", "citation_count", {"topic_name": "Alpha", "id": "topic-a"}),
        ("published_url_platforms", "citation_count", {"platform": "Alpha"}),
        ("published_url_countries", "citation_count", {"country": "Alpha"}),
        ("sentiment_themes", "occurrence_count", {"theme_name": "Alpha", "sentiment": "Positive"}),
        ("prompt_metrics", "visibility_score", {"prompt_id": "prompt-a"}),
    ],
)
def test_every_actual_list_shaper_supports_both_directions_and_null_last(list_type, metric, tie_fields):
    low = {**tie_fields, metric: 1, "marker": "low"}
    high = {**tie_fields, metric: 9, "marker": "high"}
    null = {**tie_fields, metric: None, "marker": "null"}
    assert [row["marker"] for row in sort_complete_rows(list_type, [high, null, low], metric, "asc")] == ["low", "high", "null"]
    assert [row["marker"] for row in sort_complete_rows(list_type, [low, null, high], metric, "desc")] == ["high", "low", "null"]


@pytest.mark.parametrize(
    ("list_type", "metric", "first_identity", "second_identity", "expected"),
    [
        ("visibility_visibility_ranking", "visibility_pct", {"brand_name": "alpha"}, {"brand_name": "Alpha"}, ["second", "first"]),
        ("visibility_sov_ranking", "sov_pct", {"brand_name": "alpha"}, {"brand_name": "Alpha"}, ["second", "first"]),
        ("visibility_position_ranking", "avg_position", {"brand_name": "alpha"}, {"brand_name": "Alpha"}, ["second", "first"]),
        ("visibility_matrix_groups", "total_mentions", {"group_name": "Alpha", "group_key": "b"}, {"group_name": "alpha", "group_key": "a"}, ["second", "first"]),
        ("visibility_matrix_prompts", "total_mentions", {"prompt_text": "Alpha", "prompt_id": "b"}, {"prompt_text": "alpha", "prompt_id": "a"}, ["second", "first"]),
        ("visibility_matrix_brands", "mention_count", {"company_name": "alpha"}, {"company_name": "Alpha"}, ["second", "first"]),
        ("topic_visibility", "mention_count", {"topic_name": "Alpha", "topic_id": "b"}, {"topic_name": "alpha", "topic_id": "a"}, ["second", "first"]),
        ("product_visibility", "mention_count", {"product_name": "alpha", "owner_brand_name": "", "owner_peer_name": "", "shadow_sub_role": ""}, {"product_name": "Alpha", "owner_brand_name": "", "owner_peer_name": "", "shadow_sub_role": ""}, ["second", "first"]),
        ("citation_domains", "citation_count", {"domain": "alpha.example"}, {"domain": "Alpha.example"}, ["second", "first"]),
        ("citation_pages", "citation_count", {"url": "https://alpha.example", "domain": "b"}, {"url": "https://Alpha.example", "domain": "a"}, ["second", "first"]),
        ("citation_categories", "count", {"label": "alpha"}, {"label": "Alpha"}, ["second", "first"]),
        ("published_url_tracking", "citation_count", {"published_url": "https://alpha.example", "published_url_id": "b"}, {"published_url": "https://Alpha.example", "published_url_id": "a"}, ["second", "first"]),
        ("published_url_prompts", "citation_count", {"client_prompt_text": "Alpha", "client_prompt_id": "b"}, {"client_prompt_text": "alpha", "client_prompt_id": "a"}, ["second", "first"]),
        ("published_url_topics", "citation_count", {"topic_name": "Alpha", "id": "b"}, {"topic_name": "alpha", "id": "a"}, ["second", "first"]),
        ("published_url_platforms", "citation_count", {"platform": "alpha"}, {"platform": "Alpha"}, ["second", "first"]),
        ("published_url_countries", "citation_count", {"country": "alpha"}, {"country": "Alpha"}, ["second", "first"]),
        ("sentiment_themes", "occurrence_count", {"theme_name": "Alpha", "sentiment": "Positive"}, {"theme_name": "Alpha", "sentiment": "Negative"}, ["second", "first"]),
        ("prompt_metrics", "visibility_score", {"prompt_id": "b"}, {"prompt_id": "a"}, ["second", "first"]),
    ],
)
def test_every_actual_list_shaper_has_normalized_text_and_unique_tie(
    list_type, metric, first_identity, second_identity, expected
):
    first = {**first_identity, metric: 5, "marker": "first"}
    second = {**second_identity, metric: 5, "marker": "second"}
    assert [row["marker"] for row in sort_complete_rows(list_type, [first, second], metric, "desc")] == expected
