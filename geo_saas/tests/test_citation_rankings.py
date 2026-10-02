import asyncio
from datetime import date
from uuid import UUID

import pytest

from routers.insights import citations, cited_domains, cited_pages
from routers.insights.sorting import InvalidSortKey, materialize_default_ranks, sort_complete_rows


class FakeCitedPagesDatabase:
    def __init__(self):
        self.fetch_all_calls = []
        self.fetch_val_calls = []

    async def fetch_all(self, sql, params=None):
        self.fetch_all_calls.append((sql, params or {}))
        if "geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        if "geo_client_domains" in sql:
            return []
        return []

    async def fetch_val(self, sql, params=None):
        self.fetch_val_calls.append((sql, params or {}))
        return 0

    async def fetch_one(self, sql, params=None):
        return {"total_unique": 0, "total_citations": 0, "previous_total_citations": 0}


def test_cited_pages_search_matches_url_and_domain(monkeypatch):
    fake_db = FakeCitedPagesDatabase()
    monkeypatch.setattr(cited_pages, "database", fake_db)

    asyncio.run(
        cited_pages.get_cited_pages(
            client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
            date_from="2026-05-17",
            date_to="2026-05-23",
            search="linkedin.com",
            limit=50,
            offset=0,
        )
    )

    sql_text = "\n".join(sql for sql, _params in fake_db.fetch_all_calls + fake_db.fetch_val_calls)
    assert "(url ILIKE :search OR domain ILIKE :search)" in sql_text


def test_full_citation_domain_rows_materialize_canonical_rank_before_user_sort(monkeypatch):
    class RankingDatabase:
        async def fetch_all(self, _sql, _params=None):
            # Deliberately not in canonical order: rank materialization must use
            # the complete result set rather than trusting the caller's order.
            return [
                {
                    "source_domain": "zeta.example",
                    "citation_count": 5,
                    "domain_category": None,
                    "is_own": 0,
                },
                {
                    "source_domain": "Beta.example",
                    "citation_count": 10,
                    "domain_category": "Other",
                    "is_own": 0,
                },
                {
                    "source_domain": "alpha.example",
                    "citation_count": 5,
                    "domain_category": "Other",
                    "is_own": 0,
                },
            ]

    monkeypatch.setattr(citations, "database", RankingDatabase())

    rows = asyncio.run(
        citations._query_citation_domain_topn(
            "c.client_id = :client_id",
            {"client_id": "client-a"},
            set(),
            20,
        )
    )

    assert [(row["domain"], row["rank"]) for row in rows] == [
        ("Beta.example", 1),
        ("alpha.example", 2),
        ("zeta.example", 3),
    ]
    with pytest.raises(InvalidSortKey, match="Unsupported metric 'rank'"):
        sort_complete_rows("citation_domains", rows, "rank", "desc")


def test_full_citations_page_rows_share_canonical_rank_materialization(monkeypatch):
    class FullCitationsDatabase:
        async def fetch_one(self, _sql, _params=None):
            return {
                "total_citations": 20,
                "own_citation_count": 0,
                "own_rank": None,
            }

        async def fetch_val(self, _sql, _params=None):
            return 0

        async def fetch_all(self, sql, _params=None):
            if "GROUP BY c.source_url, c.source_domain" in sql:
                return [
                    {
                        "source_url": None,
                        "source_domain": "null.example",
                        "citation_count": 5,
                        "domain_category": None,
                    },
                    {
                        "source_url": "https://zeta.example/page",
                        "source_domain": "zeta.example",
                        "citation_count": 5,
                        "domain_category": "Other",
                    },
                    {
                        "source_url": "https://alpha.example/page",
                        "source_domain": "alpha.example",
                        "citation_count": 10,
                        "domain_category": "Other",
                    },
                ]
            return []

    monkeypatch.setattr(citations, "database", FullCitationsDatabase())

    result = asyncio.run(
        citations._query_citations(
            "c.client_id = :client_id",
            {
                "client_id": "client-a",
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 1),
            },
            "daily",
            set(),
        )
    )

    assert [(row["url"], row["rank"]) for row in result["page_ranking"]] == [
        ("https://alpha.example/page", 1),
        ("https://zeta.example/page", 2),
        (None, 3),
    ]


def test_full_citation_response_rows_require_materialized_rank():
    domain_schema = citations.CitationDomainRow.model_json_schema()
    page_schema = citations.CitationPageRow.model_json_schema()

    assert "rank" in domain_schema["required"]
    assert "rank" in page_schema["required"]


def test_canonical_rank_is_stable_and_only_business_metrics_can_resort_rows():
    ranked = materialize_default_ranks(
        "citation_domains",
        [
            {"domain": "zeta.example", "citation_count": None, "change_pct": 4.0},
            {"domain": "alpha.example", "citation_count": 5, "change_pct": None},
            {"domain": "Alpha.example", "citation_count": 5, "change_pct": -2.0},
        ],
    )

    assert [(row["domain"], row["rank"]) for row in ranked] == [
        ("Alpha.example", 1),
        ("alpha.example", 2),
        ("zeta.example", 3),
    ]
    with pytest.raises(InvalidSortKey, match="Unsupported metric 'rank'"):
        sort_complete_rows("citation_domains", ranked, "rank", "asc")
    assert [row["change_pct"] for row in sort_complete_rows(
        "citation_domains", ranked, "change_pct", "asc"
    )] == [-2.0, 4.0, None]


def test_cited_domains_rank_is_materialized_before_metric_sort_and_pagination(monkeypatch):
    prompt_id = "11111111-1111-1111-1111-111111111111"

    class RankedDomainsDatabase:
        def __init__(self):
            self.fetch_all_calls = []

        async def fetch_one(self, _sql, _params=None):
            return {"total_unique": 40, "total_citations": 400}

        async def fetch_all(self, sql, params=None):
            self.fetch_all_calls.append((sql, params or {}))
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "geo_client_domains" in sql and "FROM metrics" not in sql:
                return []
            if "FROM metrics" in sql:
                return [
                    {
                        "rank": 21,
                        "domain": "page-21.example",
                        "domain_category": "Other",
                        "citation_count": 20,
                        "share_pct": 5,
                        "change_pct": None,
                    },
                    {
                        "rank": 22,
                        "domain": "page-22.example",
                        "domain_category": "Other",
                        "citation_count": 19,
                        "share_pct": 4.75,
                        "change_pct": -1,
                    },
                ]
            return []

    fake_db = RankedDomainsDatabase()
    monkeypatch.setattr(cited_domains, "database", fake_db)

    result = asyncio.run(
        cited_domains.get_cited_domains(
            client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
            date_from="2026-05-17",
            date_to="2026-05-23",
            products="Robot Vacuum",
            prompt_ids=prompt_id,
            sort_by="change_pct",
            sort_order="desc",
            limit=2,
            offset=20,
        )
    )

    assert [row.rank for row in result.domains] == [21, 22]
    page_sql, page_params = next(
        (sql, params) for sql, params in fake_db.fetch_all_calls if "FROM metrics" in sql
    )
    assert "ROW_NUMBER() OVER" in page_sql
    assert "ORDER BY ca.citation_count DESC, LOWER(ca.domain) ASC, ca.domain ASC" in page_sql
    assert "ORDER BY change_pct DESC NULLS LAST, LOWER(domain) ASC, domain ASC" in page_sql
    assert "LIMIT :limit OFFSET :offset" in page_sql
    assert "c.client_id = :client_id" in page_sql
    assert "cp.client_id = c.client_id" in page_sql
    assert "LOWER(TRIM(COALESCE(cp.product, '')))" in page_sql
    assert "c.client_prompt_id IN (:target_prompt_0)" in page_sql
    assert page_params["target_prompt_0"] == prompt_id


def test_cited_domains_uses_one_aggregate_for_page_summary_and_ownership(monkeypatch):
    class SingleAggregateDatabase:
        def __init__(self):
            self.fetch_all_calls = []

        async def fetch_one(self, *_args, **_kwargs):
            raise AssertionError("cited-domains must not issue a separate totals query")

        async def fetch_all(self, sql, params=None):
            self.fetch_all_calls.append((sql, params or {}))
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "FROM metrics" in sql:
                return [{
                    "rank": 1,
                    "domain": "answer-x.ai",
                    "domain_category": "Corporate",
                    "citation_count": 7,
                    "share_pct": 70,
                    "change_pct": 5,
                    "is_own": True,
                    "total_unique": 3,
                    "total_citations": 10,
                }]
            raise AssertionError(f"unexpected standalone query: {sql}")

    fake_db = SingleAggregateDatabase()
    monkeypatch.setattr(cited_domains, "database", fake_db)

    result = asyncio.run(cited_domains.get_cited_domains(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-17",
        date_to="2026-05-23",
        limit=20,
        offset=0,
    ))

    metric_queries = [
        sql for sql, _params in fake_db.fetch_all_calls if "geo_citations" in sql
    ]
    assert len(metric_queries) == 1
    assert "combined_domain_agg AS MATERIALIZED" in metric_queries[0]
    assert "current_domain_agg AS MATERIALIZED" not in metric_queries[0]
    assert "previous_domain_agg AS MATERIALIZED" not in metric_queries[0]
    assert metric_queries[0].count("FROM geo_citations c") == 1
    assert "COUNT(*) FILTER" in metric_queries[0]
    assert "AS current_count" in metric_queries[0]
    assert "AS previous_count" in metric_queries[0]
    assert "LEFT JOIN previous_domain_agg" not in metric_queries[0]
    assert "current_base AS MATERIALIZED" not in metric_queries[0]
    assert "previous_base AS MATERIALIZED" not in metric_queries[0]
    assert "EXISTS (" in metric_queries[0]
    assert "FROM geo_client_domains cd" in metric_queries[0]
    assert result.total_unique_domains == 3
    assert result.total_citations == 10
    assert result.domains[0].is_own is True


def test_cited_domains_count_matches_grouped_list_identity(monkeypatch):
    fake_db = FakeCitedPagesDatabase()
    fake_db.fetch_val = lambda *_args, **_kwargs: None

    async def fetch_val(sql, params=None):
        fake_db.fetch_val_calls.append((sql, params or {}))
        return 4

    fake_db.fetch_val = fetch_val
    monkeypatch.setattr(cited_domains, "database", fake_db)

    result = asyncio.run(cited_domains.get_cited_domains_count(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-17",
        date_to="2026-05-23",
    ))

    count_sql, _params = fake_db.fetch_val_calls[-1]
    assert "GROUP BY c.source_domain" in count_sql
    assert "COUNT(DISTINCT c.source_domain)" not in count_sql
    assert result.total_unique_domains == 4


def test_cited_pages_rank_ties_and_nulls_are_resolved_before_pagination(monkeypatch):
    class RankedPagesDatabase:
        def __init__(self):
            self.fetch_all_calls = []

        async def fetch_one(self, _sql, _params=None):
            return {"total_unique": 40, "total_citations": 400}

        async def fetch_all(self, sql, params=None):
            self.fetch_all_calls.append((sql, params or {}))
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "geo_client_domains" in sql and "FROM metrics" not in sql:
                return []
            if "FROM metrics" in sql:
                return [
                    {
                        "rank": 21,
                        "url": "https://alpha.example/page",
                        "domain": "alpha.example",
                        "domain_category": "Other",
                        "citation_count": 20,
                        "share_pct": 5,
                        "change_pct": -1,
                    },
                    {
                        "rank": 22,
                        "url": None,
                        "domain": "null.example",
                        "domain_category": "Other",
                        "citation_count": 20,
                        "share_pct": 5,
                        "change_pct": None,
                    },
                ]
            return []

    fake_db = RankedPagesDatabase()
    monkeypatch.setattr(cited_pages, "database", fake_db)

    result = asyncio.run(
        cited_pages.get_cited_pages(
            client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
            date_from="2026-05-17",
            date_to="2026-05-23",
            sort_by="change_pct",
            sort_order="asc",
            limit=2,
            offset=20,
        )
    )

    assert [row.rank for row in result.pages] == [21, 22]
    page_sql, _page_params = next(
        (sql, params) for sql, params in fake_db.fetch_all_calls if "FROM metrics" in sql
    )
    assert (
        "ORDER BY ca.citation_count DESC, LOWER(ca.url) ASC, ca.url ASC, ca.domain ASC"
        in page_sql
    )
    assert "ORDER BY change_pct ASC NULLS LAST" in page_sql
    assert "LOWER(url) ASC, url ASC, domain ASC" in page_sql
    assert "LIMIT :limit OFFSET :offset" in page_sql


def test_cited_pages_change_sort_uses_one_conditional_period_aggregate(monkeypatch):
    fake_db = FakeCitedPagesDatabase()
    monkeypatch.setattr(cited_pages, "database", fake_db)

    asyncio.run(cited_pages.get_cited_pages(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-17",
        date_to="2026-05-23",
        sort_by="change_pct",
        sort_order="desc",
        limit=20,
        offset=0,
    ))

    aggregate_sql = next(sql for sql, _params in fake_db.fetch_all_calls if "FROM metrics" in sql)
    normalized_sql = " ".join(aggregate_sql.split())
    assert "period_page_agg AS MATERIALIZED" in aggregate_sql
    assert normalized_sql.count("FROM geo_citations c") == 1
    assert "COUNT(*) FILTER" in aggregate_sql
    assert "previous_citation_count" in aggregate_sql
    assert "previous_page_agg" not in aggregate_sql
    assert "ARRAY[pa.url, pa.domain]" not in aggregate_sql
    assert normalized_sql.count("AT TIME ZONE 'Asia/Shanghai'") >= 3
    assert "c.executed_at >= :start_date" not in normalized_sql
    assert "cp.is_active = TRUE" in normalized_sql


def test_cited_domains_change_sort_uses_combined_period_counts_and_two_stage_rounding(monkeypatch):
    fake_db = FakeCitedPagesDatabase()
    monkeypatch.setattr(cited_domains, "database", fake_db)

    asyncio.run(cited_domains.get_cited_domains(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-17",
        date_to="2026-05-23",
        sort_by="change_pct",
        sort_order="desc",
        limit=20,
        offset=0,
    ))

    aggregate_sql = next(sql for sql, _params in fake_db.fetch_all_calls if "FROM metrics" in sql)
    normalized_sql = " ".join(aggregate_sql.split())
    assert "combined_domain_agg AS MATERIALIZED" in aggregate_sql
    assert "LEFT JOIN previous_domain_agg" not in aggregate_sql
    assert "ca.previous_count > 0" in aggregate_sql
    assert "ROUND( ca.citation_count::numeric / NULLIF(ct.total_citations, 0) * 100, 2 )" in normalized_sql
    assert "ROUND( ca.previous_count::numeric / pt.total_citations * 100, 2 )" in normalized_sql
    assert "cp.is_active = TRUE" in normalized_sql


def test_cited_pages_returns_rows_totals_and_ownership_in_one_aggregate_query(monkeypatch):
    class SingleQueryDatabase:
        def __init__(self):
            self.fetch_all_calls = []
            self.fetch_one_calls = []

        async def fetch_one(self, sql, params=None):
            self.fetch_one_calls.append((sql, params or {}))
            raise AssertionError("cited-pages must not issue a separate totals query")

        async def fetch_all(self, sql, params=None):
            self.fetch_all_calls.append((sql, params or {}))
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "FROM metrics" in sql:
                return [{
                    "rank": 1,
                    "url": "https://answerx.ai/page",
                    "domain": "answerx.ai",
                    "domain_category": "Owned Media",
                    "citation_count": 12,
                    "share_pct": 60,
                    "change_pct": 5,
                    "is_own": True,
                    "total_unique": 3,
                    "total_citations": 20,
                }]
            return []

    fake_db = SingleQueryDatabase()
    monkeypatch.setattr(cited_pages, "database", fake_db)

    result = asyncio.run(cited_pages.get_cited_pages(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-17",
        date_to="2026-05-23",
        limit=20,
        offset=0,
    ))

    aggregate_calls = [
        (sql, params) for sql, params in fake_db.fetch_all_calls if "FROM metrics" in sql
    ]
    assert len(aggregate_calls) == 1
    sql, _ = aggregate_calls[0]
    assert "geo_client_domains" in sql
    assert "total_unique" in sql
    assert "current_page_agg AS MATERIALIZED" in sql
    assert "previous_candidate_agg AS MATERIALIZED" in sql
    assert "JOIN current_paged candidate" in sql
    assert "previous_page_agg AS MATERIALIZED" not in sql
    assert "current_base AS MATERIALIZED" not in sql
    assert "previous_base AS MATERIALIZED" not in sql
    assert result.total_unique_pages == 3
    assert result.total_citations == 20
    assert result.pages[0].is_own is True


def test_cited_pages_uses_previous_count_as_presence_for_null_urls(monkeypatch):
    fake_db = FakeCitedPagesDatabase()
    monkeypatch.setattr(cited_pages, "database", fake_db)

    asyncio.run(cited_pages.get_cited_pages(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-17",
        date_to="2026-05-23",
        limit=20,
        offset=0,
    ))

    aggregate_sql = next(sql for sql, _params in fake_db.fetch_all_calls if "FROM metrics" in sql)
    assert "WHEN previous.citation_count IS NOT NULL" in aggregate_sql
    assert "WHEN previous.url IS NOT NULL" not in aggregate_sql


def test_cited_pages_count_uses_same_url_domain_identity_as_list(monkeypatch):
    class CountDatabase(FakeCitedPagesDatabase):
        async def fetch_val(self, sql, params=None):
            self.fetch_val_calls.append((sql, params or {}))
            return 4

    fake_db = CountDatabase()
    monkeypatch.setattr(cited_pages, "database", fake_db)
    result = asyncio.run(cited_pages.get_cited_pages_count(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-17",
        date_to="2026-05-23",
    ))

    count_sql, _params = fake_db.fetch_val_calls[-1]
    assert "GROUP BY c.source_url, c.source_domain" in count_sql
    assert "COUNT(DISTINCT c.source_url)" not in count_sql
    assert result.total_unique_pages == 4


def test_cited_pages_offset_past_end_keeps_summary_without_rows(monkeypatch):
    class SummaryOnlyDatabase(FakeCitedPagesDatabase):
        async def fetch_all(self, sql, params=None):
            self.fetch_all_calls.append((sql, params or {}))
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "FROM metrics" in sql:
                return [{"rank": None, "total_unique": 3, "total_citations": 9}]
            return []

    fake_db = SummaryOnlyDatabase()
    monkeypatch.setattr(cited_pages, "database", fake_db)
    result = asyncio.run(cited_pages.get_cited_pages(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-17",
        date_to="2026-05-23",
        limit=20,
        offset=20,
    ))

    assert result.pages == []
    assert result.total_unique_pages == 3
    assert result.total_citations == 9
    assert result.has_more is False


def test_cited_domains_endpoint_supports_pagination_and_global_search(monkeypatch):
    from routers.insights import cited_domains

    class FakeCitedDomainsDatabase(FakeCitedPagesDatabase):
        async def fetch_all(self, sql, params=None):
            self.fetch_all_calls.append((sql, params or {}))
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "FROM metrics" in sql:
                return [
                    {
                        "rank": 1,
                        "domain": "linkedin.com",
                        "citation_count": 303,
                        "share_pct": 100,
                        "change_pct": None,
                        "domain_category": "Social Media",
                        "is_own": False,
                        "total_unique": 1,
                        "total_citations": 303,
                    }
                ]
            return []

        async def fetch_one(self, sql, params=None):
            return {"total_unique": 1, "total_citations": 303, "previous_total_citations": 0}

    fake_db = FakeCitedDomainsDatabase()
    monkeypatch.setattr(cited_domains, "database", fake_db)

    result = asyncio.run(
        cited_domains.get_cited_domains(
            client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
            date_from="2026-05-17",
            date_to="2026-05-23",
            search="linkedin",
            limit=50,
            offset=0,
        )
    )

    assert result.limit == 50
    assert result.offset == 0
    assert result.domains[0].domain == "linkedin.com"
    assert result.total_unique_domains == 1

    sql_text = "\n".join(sql for sql, _params in fake_db.fetch_all_calls + fake_db.fetch_val_calls)
    assert "domain ILIKE :search" in sql_text
    assert "LIMIT :limit OFFSET :offset" in sql_text
