from __future__ import annotations

import asyncio
from datetime import date
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from routers.static_reports.models import DYNAMIC_REPORT_VERSION, RenderingMode, StaticReportStatus
from routers.static_reports.repository import (
    MaterializationLeaseLost,
    StaticReportRepository,
    parse_materialization_lease_seconds,
)
from routers.static_reports.snapshot_builder import (
    build_static_report_list_blobs,
    build_static_report_list_rows,
)
from routers.static_reports.snapshot_builder import (
    bound_visibility_ranking_matrix,
    load_citation_dashboard_snapshot,
    load_prompt_topic_snapshot,
    load_sentiment_dashboard_snapshot,
    strip_static_report_complete_lists,
)
from routers.static_reports.sorting import (
    STATIC_REPORT_LIST_SPECS,
    StaticReportListUnavailable,
    sort_static_report_default_rows,
    stable_static_report_row_key,
    validate_static_report_list_sort,
    sort_visibility_ranking_matrix_defaults,
)


def _cursor_from_fake_fetch(connection, sql, *args, prefetch):
    assert prefetch > 0

    async def iterate():
        for row in await connection.fetch(sql, *args):
            yield row

    return iterate()


def test_router_exposes_fixed_frozen_list_endpoint():
    from routers.static_reports.router import router

    assert "/api/static-reports/{report_id}/lists/{list_type}" in {route.path for route in router.routes}


def test_list_endpoint_authorizes_report_in_repository_query_and_maps_legacy_error(monkeypatch):
    from routers.static_reports.router import get_static_report_frozen_list

    calls = []

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def get_authorized_summary_by_id(self, report_id, user_id):
            assert (report_id, user_id) == ("report-1", "user-1")
            return {"id": report_id, "client_id": "client-1", "snapshot_version": "static-report-v5"}

        async def list_frozen_rows(self, report_id, client_id, list_type, **kwargs):
            calls.append((report_id, client_id, list_type, kwargs))
            raise StaticReportListUnavailable("sorting_unavailable_for_snapshot_version")

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)

    with pytest.raises(HTTPException) as error:
        asyncio.run(get_static_report_frozen_list(
            "report-1",
            "citation.domain",
            sort_by="citation_count",
            sort_order="desc",
            limit=20,
            offset=0,
            parent_key=None,
            prompt_key=None,
            search="example",
            sentiment=None,
            user=type("User", (), {"id": "user-1"})(),
            pool=object(),
        ))

    assert error.value.status_code == 409
    assert error.value.detail == "sorting_unavailable_for_snapshot_version"
    assert calls[0][:3] == ("report-1", "client-1", "citation.domain")
    assert calls[0][3]["search"] == "example"


def _snapshot() -> dict:
    return {
        "visibility": {
            "dashboard": {
                "_complete_visibility_ranking": [
                    {"brand_name": "Beta", "visibility_pct": None, "mention_count": 2, "rank": 2},
                    {"brand_name": "Alpha", "visibility_pct": 80.0, "mention_count": 8, "rank": 1},
                ],
                "_complete_sov_ranking": [
                    {"brand_name": "Alpha", "sov_pct": 70.0, "mention_count": 7, "rank": 1},
                ],
                "_complete_position_ranking": [
                    {"brand_name": "Alpha", "avg_position": 1.5, "rank": 1},
                ],
                "topic_sov_ranking": [{
                    "topic_id": "topic-1",
                    "topic_name": "Robots",
                    "prompt_count": 1,
                    "total_mentions": 8,
                    "brands": [{"company_name": "Alpha", "rank": 1, "mention_count": 8}],
                    "prompts": [{
                        "prompt_id": "prompt-1",
                        "prompt_text": "Best robot",
                        "total_mentions": 8,
                        "brands": [{"company_name": "Alpha", "rank": 1, "mention_count": 8}],
                    }],
                }],
                "product_sov_ranking": [{
                    "product": "Vacuum",
                    "prompt_count": 1,
                    "total_mentions": 8,
                    "brands": [],
                    "prompts": [],
                }],
            },
        },
        "citations": {"dashboard": {
            "_complete_domain_ranking": [
                {"domain": "example.com", "rank": 1, "citation_count": 9, "share_pct": 90.0, "change_pct": 2.0},
            ],
            "_complete_page_ranking": [
                {"url": "https://example.com/a", "domain": "example.com", "rank": 1, "citation_count": 7, "share_pct": 70.0},
            ],
            "category_breakdown": [{"label": "Earned Media", "count": 9, "pct": 90.0}],
        }},
        "sentiment": {"dashboard": {"_complete_themes": [
            {"theme_name": "Quiet", "sentiment": "Positive", "occurrence_count": 4, "occurrence_change": 1},
        ]}},
        "prompts": {"_complete_ranking": [
            {"prompt_id": "prompt-1", "prompt_text": "Best robot", "platform": "chatgpt", "mention_count": 8, "citation_count": 7},
        ]},
        "topics": {"_complete_ranking": [
            {"topic_name": "Robots", "mention_count": 8, "citation_count": 7},
        ]},
    }


def test_materializes_complete_metric_lists_with_split_payloads_and_stable_keys():
    first = build_static_report_list_rows(_snapshot())
    second = build_static_report_list_rows(_snapshot())

    by_type: dict[str, list[dict]] = {}
    for row in first:
        by_type.setdefault(row["list_type"], []).append(row)
        assert row["row_key"]
        assert row["default_position"] >= 0
        assert (set(row["metric_payload"]) - {"rank"}).issubset(
            STATIC_REPORT_LIST_SPECS[row["list_type"]].allowed_metrics
        )
        assert not (set(row["dimension_payload"]) & set(row["metric_payload"]))

    assert len(by_type["visibility.brand_visibility"]) == 2
    assert by_type["visibility.brand_visibility"][1]["metric_payload"]["visibility_pct"] == 80.0
    assert by_type["visibility.topic_prompt"][0]["dimension_payload"]["prompt_text"] == "Best robot"
    assert by_type["visibility.topic_prompt_brand"][0]["metric_payload"]["mention_count"] == 8
    assert by_type["prompt.ranking"][0]["dimension_payload"]["platform"] == "chatgpt"
    assert [(r["list_type"], r["row_key"]) for r in first] == [
        (r["list_type"], r["row_key"]) for r in second
    ]
    assert _snapshot().get("frozen_lists") is None


def test_materializer_embeds_exact_frozen_list_metadata_for_default_and_scoped_pages():
    snapshot = _snapshot()
    build_static_report_list_rows(snapshot)

    assert snapshot["frozen_lists"]["visibility.brand_visibility"] == {
        "total": 2,
        "default_sort_by": "visibility_pct",
        "default_sort_order": "desc",
    }
    assert snapshot["frozen_lists"]["visibility.topic_prompt_brand"]["scopes"] == [{
        "parent_key": "topic-1",
        "prompt_key": "prompt-1",
        "total": 1,
    }]


def test_frozen_scope_metadata_covers_groups_outside_the_embedded_first_page():
    groups = [
        {
            "topic_id": f"topic-{index}",
            "topic_name": f"Topic {index}",
            "prompt_count": 1,
            "total_mentions": 100 - index,
            "brands": [],
            "prompts": [{
                "prompt_id": f"prompt-{index}",
                "prompt_text": f"Prompt {index}",
                "total_mentions": 100 - index,
                "brands": [{"company_name": "Brand", "rank": 1, "mention_count": 1}],
            }],
        }
        for index in range(21)
    ]
    snapshot = {
        "visibility": {"dashboard": {
            "topic_sov_ranking": groups[:20],
            "_complete_topic_sov_ranking": groups,
        }},
    }

    build_static_report_list_rows(snapshot)

    scopes = snapshot["frozen_lists"]["visibility.topic_prompt_brand"]["scopes"]
    assert any(
        scope["parent_key"] == "topic-20" and scope["prompt_key"] == "prompt-20"
        for scope in scopes
    )


def test_generation_only_complete_arrays_never_leak_into_snapshot_json():
    snapshot = _snapshot()
    strip_static_report_complete_lists(snapshot)
    encoded = str(snapshot)
    assert "_complete_" not in encoded
    assert snapshot["visibility"]["dashboard"].get("visibility_ranking", []) == []


def test_registry_covers_snapshot_visibility_citation_sentiment_topic_product_prompt_lists():
    required = {
        "visibility.brand_visibility",
        "visibility.brand_sov",
        "visibility.brand_position",
        "visibility.topic",
        "visibility.product",
        "visibility.topic_prompt",
        "visibility.product_prompt",
        "visibility.topic_brand",
        "visibility.product_brand",
        "visibility.topic_prompt_brand",
        "visibility.product_prompt_brand",
        "citation.domain",
        "citation.page",
        "citation.category",
        "sentiment.theme",
        "prompt.ranking",
        "topic.ranking",
    }
    assert required <= set(STATIC_REPORT_LIST_SPECS)
    for spec in STATIC_REPORT_LIST_SPECS.values():
        assert spec.default_sort_by in spec.allowed_metrics
        assert spec.default_sort_order in {"asc", "desc"}
        assert spec.tie_dimension_keys


def test_snapshot_loaders_keep_complete_rankings_private_and_default_payload_bounded():
    dates = type("Dates", (), {
        "window_start": date(2026, 7, 1),
        "window_end": date(2026, 7, 7),
        "timezone": "Asia/Shanghai",
        "report_date": date(2026, 7, 7),
        "window_days": 7,
    })()

    class CitationConn:
        async def fetchval(self, sql, *_args):
            assert "FROM geo_citations" in sql
            return 25

        async def fetch(self, sql, *_args):
            if "FROM geo_client_domains" in sql:
                return []
            if "c.source_url, c.source_domain" in sql:
                return [
                    {
                        "date": date(2026, 7, 7),
                        "topic_id": "topic-1",
                        "platform": "ChatGPT",
                        "source_url": f"https://d{i}.example/a",
                        "source_domain": f"d{i}.example",
                        "citation_count": 1,
                        "domain_category": "Other",
                    }
                    for i in range(25)
                ]
            raise AssertionError(sql)

        cursor = _cursor_from_fake_fetch

    citation = asyncio.run(load_citation_dashboard_snapshot(
        CitationConn(), "client-1", dates, ("Discovery",),
    ))
    assert len(citation["domain_ranking"]) == 20
    assert len(citation["page_ranking"]) == 20
    assert len(citation["_complete_domain_ranking"]) == 25
    assert len(citation["_complete_page_ranking"]) == 25

    class SentimentConn:
        async def fetch(self, sql, *_args):
            if "FROM geo_sentiment_results sr" in sql:
                return [{
                    "period": "current", "date": date(2026, 7, 7),
                    "sentiment": "Positive", "count": 120, "avg_confidence": 0.9,
                }]
            if "st.excerpt" in sql:
                return []
            if "FROM geo_sentiment_themes st" in sql:
                return [
                    {
                        "period": "current", "date": date(2026, 7, 7),
                        "topic_id": "topic-1", "topic_name": "Topic",
                        "platform": "ChatGPT", "theme_name": f"Theme {i}",
                        "sentiment": "Positive", "occurrence_count": 1,
                    }
                    for i in range(120)
                ]
            raise AssertionError(sql)

        cursor = _cursor_from_fake_fetch

    sentiment = asyncio.run(load_sentiment_dashboard_snapshot(
        SentimentConn(), "client-1", dates, ("Discovery",),
    ))
    assert len(sentiment["themes"]) == 100
    assert len(sentiment["_complete_themes"]) == 120

    class PromptTopicConn:
        def __init__(self):
            self.sql = []

        async def fetch(self, sql, *_args):
            self.sql.append(sql)
            if "FROM geo_client_prompts cp" in sql and "prompt_events" not in sql:
                return [
                    {"prompt_id": f"p{i}", "prompt_text": f"Prompt {i}", "intent": "Discovery", "platform": "chatgpt", "country": "US", "language": "en", "mention_count": 1, "citation_count": 1}
                    for i in range(120)
                ]
            if "GROUP BY wr.topic_name" in sql:
                return [
                    {"topic_name": f"Topic {i}", "mention_count": 1, "citation_count": 1}
                    for i in range(120)
                ]
            return []

        cursor = _cursor_from_fake_fetch

    prompt_conn = PromptTopicConn()
    prompt_topic = asyncio.run(load_prompt_topic_snapshot(prompt_conn, "client-1", dates))
    assert len(prompt_topic["prompts"]["ranking"]) == 100
    assert len(prompt_topic["prompts"]["_complete_ranking"]) == 120
    assert len(prompt_topic["topics"]["ranking"]) == 100
    assert len(prompt_topic["topics"]["_complete_ranking"]) == 120
    assert "LIMIT 100" not in "\n".join(prompt_conn.sql[:2])


def test_offline_visibility_matrix_caps_every_nested_level_without_mutating_full_source():
    brands = [{"company_name": f"Brand {index}", "mention_count": index} for index in range(25)]
    prompts = [
        {"prompt_id": f"p-{index}", "prompt_text": f"Prompt {index}", "brands": brands}
        for index in range(25)
    ]
    groups = [
        {"topic_id": f"t-{index}", "topic_name": f"Topic {index}", "brands": brands, "prompts": prompts}
        for index in range(25)
    ]

    bounded = bound_visibility_ranking_matrix(groups)

    assert len(bounded) == 20
    assert all(len(group["brands"]) == 20 for group in bounded)
    assert all(len(group["prompts"]) == 20 for group in bounded)
    assert all(len(prompt["brands"]) == 20 for group in bounded for prompt in group["prompts"])
    assert len(groups[0]["brands"]) == 25
    assert len(groups[0]["prompts"]) == 25
    assert len(groups[0]["prompts"][0]["brands"]) == 25


def test_materializer_reads_complete_visibility_matrix_before_public_nested_caps():
    brands = [{"company_name": f"Brand {index}", "rank": index + 1, "mention_count": 1} for index in range(25)]
    prompts = [
        {"prompt_id": f"p-{index}", "prompt_text": f"Prompt {index}", "total_mentions": 1, "brands": brands}
        for index in range(25)
    ]
    groups = [
        {"topic_id": f"t-{index}", "topic_name": f"Topic {index}", "prompt_count": 25, "total_mentions": 25,
         "brands": brands if index == 0 else [], "prompts": prompts if index == 0 else []}
        for index in range(25)
    ]
    snapshot = {"visibility": {"dashboard": {
        "topic_sov_ranking": bound_visibility_ranking_matrix(groups),
        "_complete_topic_sov_ranking": groups,
    }}}

    rows = build_static_report_list_rows(snapshot)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["list_type"]] = counts.get(row["list_type"], 0) + 1

    assert counts["visibility.topic"] == 25
    assert counts["visibility.topic_brand"] == 25
    assert counts["visibility.topic_prompt"] == 25
    assert counts["visibility.topic_prompt_brand"] == 625


def test_visibility_matrix_default_sort_is_registry_exact_before_bounding_and_positions():
    groups = [
        {
            "topic_id": "topic-b", "topic_name": "Beta", "prompt_count": 3, "total_mentions": 5,
            "brands": [
                {"company_name": "Zulu", "rank": None, "mention_count": 2},
                {"company_name": "Beta", "rank": 1, "mention_count": 3},
                {"company_name": "Alpha", "rank": 1, "mention_count": 3},
            ],
            "prompts": [
                {"prompt_id": "prompt-z", "prompt_text": "Zulu", "total_mentions": 8, "brands": []},
                {"prompt_id": "prompt-a", "prompt_text": "Alpha", "total_mentions": 8, "brands": [
                    {"company_name": "Zulu", "rank": 2, "mention_count": 1},
                    {"company_name": "Alpha", "rank": 1, "mention_count": 2},
                ]},
                {"prompt_id": "prompt-null", "prompt_text": "Null", "total_mentions": None, "brands": []},
            ],
        },
        {"topic_id": "topic-a", "topic_name": "Alpha", "prompt_count": 0, "total_mentions": 5, "brands": [], "prompts": []},
        {"topic_id": "topic-null", "topic_name": "Null", "prompt_count": 0, "total_mentions": None, "brands": [], "prompts": []},
    ]

    ordered = sort_visibility_ranking_matrix_defaults(groups, "topic")
    assert [row["topic_id"] for row in ordered] == ["topic-a", "topic-b", "topic-null"]
    beta = ordered[1]
    assert [row["company_name"] for row in beta["brands"]] == ["Alpha", "Beta", "Zulu"]
    assert [row["prompt_id"] for row in beta["prompts"]] == ["prompt-a", "prompt-z", "prompt-null"]
    assert [row["company_name"] for row in beta["prompts"][0]["brands"]] == ["Alpha", "Zulu"]

    # The embedded first page and the API registry comparator must expose the
    # exact same default order, including NULL-last and dimension/ID ties.
    api_default_groups = sort_static_report_default_rows("visibility.topic", groups)
    api_default_prompts = sort_static_report_default_rows(
        "visibility.topic_prompt", groups[0]["prompts"],
    )
    assert [row["topic_id"] for row in ordered] == [row["topic_id"] for row in api_default_groups]
    assert [row["prompt_id"] for row in beta["prompts"]] == [
        row["prompt_id"] for row in api_default_prompts
    ]

    snapshot = {"visibility": {"dashboard": {
        "topic_sov_ranking": bound_visibility_ranking_matrix(ordered),
        "_complete_topic_sov_ranking": ordered,
    }}}
    rows = build_static_report_list_rows(snapshot)
    group_rows = [row for row in rows if row["list_type"] == "visibility.topic"]
    prompt_rows = [row for row in rows if row["list_type"] == "visibility.topic_prompt" and row["dimension_payload"].get("topic_id") == "topic-b"]
    assert [row["dimension_payload"]["topic_id"] for row in sorted(group_rows, key=lambda row: row["default_position"])] == ["topic-a", "topic-b", "topic-null"]
    assert [row["dimension_payload"]["prompt_id"] for row in sorted(prompt_rows, key=lambda row: row["default_position"])] == ["prompt-a", "prompt-z", "prompt-null"]
    assert snapshot["frozen_lists"]["visibility.topic"]["default_sort_by"] == "total_mentions"
    assert snapshot["frozen_lists"]["visibility.topic_prompt"]["default_sort_order"] == "desc"
    assert snapshot["frozen_lists"]["visibility.topic_brand"]["default_sort_by"] == "rank"
    assert snapshot["frozen_lists"]["visibility.topic_prompt_brand"]["default_sort_order"] == "asc"


def test_product_matrix_uses_registry_default_order_for_embedded_and_materialized_rows():
    groups = [
        {
            "product": "Zulu", "prompt_count": 2, "total_mentions": 9,
            "brands": [
                {"company_name": "Zulu", "rank": None, "mention_count": 1},
                {"company_name": "Alpha", "rank": 1, "mention_count": 2},
            ],
            "prompts": [
                {"prompt_id": "prompt-z", "prompt_text": "Zulu", "total_mentions": 4, "brands": []},
                {"prompt_id": "prompt-a", "prompt_text": "Alpha", "total_mentions": 4, "brands": []},
            ],
        },
        {"product": "Alpha", "prompt_count": 0, "total_mentions": 9, "brands": [], "prompts": []},
        {"product": "Null", "prompt_count": 0, "total_mentions": None, "brands": [], "prompts": []},
    ]

    ordered = sort_visibility_ranking_matrix_defaults(groups, "product")
    assert [row["product"] for row in ordered] == ["Alpha", "Zulu", "Null"]
    zulu = ordered[1]
    assert [row["company_name"] for row in zulu["brands"]] == ["Alpha", "Zulu"]
    assert [row["prompt_id"] for row in zulu["prompts"]] == ["prompt-a", "prompt-z"]
    assert [row["product"] for row in ordered] == [
        row["product"] for row in sort_static_report_default_rows("visibility.product", groups)
    ]

    snapshot = {"visibility": {"dashboard": {
        "product_sov_ranking": bound_visibility_ranking_matrix(ordered),
        "_complete_product_sov_ranking": ordered,
    }}}
    rows = build_static_report_list_rows(snapshot)
    group_rows = [row for row in rows if row["list_type"] == "visibility.product"]
    prompt_rows = [
        row for row in rows
        if row["list_type"] == "visibility.product_prompt"
        and row["dimension_payload"].get("product") == "Zulu"
    ]
    assert [
        row["dimension_payload"]["product"]
        for row in sorted(group_rows, key=lambda row: row["default_position"])
    ] == ["Alpha", "Zulu", "Null"]
    assert [
        row["dimension_payload"]["prompt_id"]
        for row in sorted(prompt_rows, key=lambda row: row["default_position"])
    ] == ["prompt-a", "prompt-z"]
    assert snapshot["frozen_lists"]["visibility.product"]["default_sort_by"] == "total_mentions"
    assert snapshot["frozen_lists"]["visibility.product_prompt_brand"]["default_sort_by"] == "rank"


def test_default_comparator_matches_sql_lower_row_key_and_position_ties():
    rows = [
        {"topic_id": "topic-2", "topic_name": "Straße", "total_mentions": 5, "prompt_count": 1},
        {"topic_id": "topic-1", "topic_name": "STRASSE", "total_mentions": 5, "prompt_count": 1},
        {"topic_id": "same", "topic_name": "Exact", "total_mentions": 5, "prompt_count": 1, "default_position": 8},
        {"topic_id": "same", "topic_name": "Exact", "total_mentions": 5, "prompt_count": 1, "default_position": 3},
    ]

    ordered = sort_static_report_default_rows("visibility.topic", rows)
    assert [(row["topic_name"], row.get("default_position")) for row in ordered] == [
        ("Exact", 3),
        ("Exact", 8),
        ("STRASSE", None),
        ("Straße", None),
    ]
    exact_dimensions = {"topic_id": "same", "topic_name": "Exact"}
    assert stable_static_report_row_key("visibility.topic", exact_dimensions) == stable_static_report_row_key(
        "visibility.topic", exact_dimensions,
    )


def test_unicode_and_exact_metric_ties_match_embedded_materialized_and_api_default_order():
    groups = [
        {"topic_id": "topic-street", "topic_name": "Straße", "total_mentions": 5, "prompt_count": 1,
         "brands": [], "prompts": []},
        {"topic_id": "topic-b", "topic_name": "Same", "total_mentions": 5, "prompt_count": 1,
         "brands": [], "prompts": []},
        {"topic_id": "topic-strasse", "topic_name": "STRASSE", "total_mentions": 5, "prompt_count": 1,
         "brands": [], "prompts": []},
        {"topic_id": "topic-a", "topic_name": "Same", "total_mentions": 5, "prompt_count": 1,
         "brands": [], "prompts": []},
    ]
    embedded = sort_visibility_ranking_matrix_defaults(groups, "topic")
    expected_ids = ["topic-a", "topic-b", "topic-strasse", "topic-street"]
    assert [row["topic_id"] for row in embedded] == expected_ids

    snapshot = {"visibility": {"dashboard": {
        "topic_sov_ranking": bound_visibility_ranking_matrix(embedded),
        "_complete_topic_sov_ranking": embedded,
    }}}
    materialized = [
        row for row in build_static_report_list_rows(snapshot)
        if row["list_type"] == "visibility.topic"
    ]
    assert [
        row["dimension_payload"]["topic_id"]
        for row in sorted(materialized, key=lambda row: row["default_position"])
    ] == expected_ids

    api_shaped = [
        {
            "row_key": row["row_key"],
            "default_position": row["default_position"],
            **row["dimension_payload"],
            **row["metric_payload"],
        }
        for row in reversed(materialized)
    ]
    assert [
        row["topic_id"]
        for row in sort_static_report_default_rows("visibility.topic", api_shaped)
    ] == expected_ids


def test_materialization_lease_seconds_has_deterministic_default_and_bounds():
    assert parse_materialization_lease_seconds(None) == 3600
    assert parse_materialization_lease_seconds("") == 3600
    assert parse_materialization_lease_seconds("invalid") == 3600
    assert parse_materialization_lease_seconds("899") == 900
    assert parse_materialization_lease_seconds("900") == 900
    assert parse_materialization_lease_seconds("86400") == 86400
    assert parse_materialization_lease_seconds("86401") == 86400


def test_sort_validation_rejects_unknown_list_metric_direction_and_bounds():
    with pytest.raises(ValueError, match="list_type"):
        validate_static_report_list_sort("private.table", None, "desc", 20, 0)
    with pytest.raises(ValueError, match="sort_by"):
        validate_static_report_list_sort("citation.domain", "source_domain", "desc", 20, 0)
    with pytest.raises(ValueError, match="sort_order"):
        validate_static_report_list_sort("citation.domain", "citation_count", "drop table", 20, 0)
    with pytest.raises(ValueError, match="limit"):
        validate_static_report_list_sort("citation.domain", None, "desc", 101, 0)
    with pytest.raises(ValueError, match="offset"):
        validate_static_report_list_sort("citation.domain", None, "desc", 20, -1)


@pytest.mark.parametrize("list_type", [
    "visibility.brand_visibility",
    "visibility.brand_sov",
    "visibility.brand_position",
    "citation.domain",
    "citation.page",
])
def test_static_user_lists_reject_presentation_rank_sort(list_type):
    with pytest.raises(ValueError, match="sort_by"):
        validate_static_report_list_sort(list_type, "rank", "asc", 20, 0)


class _Transaction:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        self.events.append("transaction:enter")

    async def __aexit__(self, exc_type, _exc, _tb):
        self.events.append("transaction:rollback" if exc_type else "transaction:commit")


class _Connection:
    def __init__(self):
        self.events: list[str] = []
        self.fetchrow_result = {"id": "report-1", "client_id": "client-1", "status": "COMPLETED"}
        self.fetch_result = []
        self.fetchval_result = 0
        self.last_fetch_sql = ""
        self.last_fetch_args = ()
        self.executemany_args = []
        self.fetch_calls = []
        self.fetchval_calls = []
        self.fetchrow_calls = []
        self.blob_result = None

    def transaction(self):
        return _Transaction(self.events)

    async def execute(self, sql, *_args):
        if "DELETE FROM geo_static_report_lists" in sql:
            self.events.append("blobs:delete")
        else:
            self.events.append("execute")

    async def executemany(self, sql, args):
        assert "INSERT INTO geo_static_report_lists" in sql
        self.events.append("blobs:insert")
        self.executemany_args = list(args)

    async def fetchrow(self, sql, *_args):
        self.fetchrow_calls.append((sql, _args))
        if "FOR UPDATE" in sql:
            self.events.append("owner:lock")
            return {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value}
        assert "UPDATE geo_static_reports" in sql
        self.events.append("snapshot:update")
        return self.fetchrow_result

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        self.last_fetch_sql = sql
        self.last_fetch_args = args
        if "FROM geo_static_report_lists" in sql:
            if len(args) >= 3 and "@sort." in str(args[2]):
                return []
            if self.blob_result is None:
                return []
            return [{
                "list_type": args[2],
                **self.blob_result,
                "payload_bytes": len(str(self.blob_result.get("rows_payload", [])).encode("utf-8")),
            }]
        return self.fetch_result

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        self.last_fetch_sql = sql
        self.last_fetch_args = args
        if "pg_try_advisory_xact_lock_shared" in sql:
            return True
        if "SELECT client_id::text" in sql:
            return "client-1"
        if "FROM geo_clients" in sql:
            return True
        return self.fetchval_result


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def test_complete_replaces_snapshot_and_every_frozen_list_blob_in_one_transaction():
    conn = _Connection()
    token = datetime(2026, 7, 7, tzinfo=timezone.utc)
    rows = build_static_report_list_blobs(_snapshot())
    repo = StaticReportRepository(_Pool(conn))

    asyncio.run(repo.complete(
        "report-1",
        token,
        {"version": "static-report-v3"},
        RenderingMode.MULTI_DAY,
        {},
        [],
        rows,
    ))

    assert conn.events == [
        "transaction:enter",
        "owner:lock",
        "blobs:delete",
        "blobs:insert",
        "snapshot:update",
        "transaction:commit",
    ]
    assert "SELECT client_id::text" in conn.fetchval_calls[0][0]
    assert "pg_try_advisory_xact_lock_shared" in conn.fetchval_calls[1][0]
    assert "FROM geo_clients" in conn.fetchval_calls[2][0]
    assert len(conn.executemany_args) == len(STATIC_REPORT_LIST_SPECS)


def test_complete_dynamic_writes_only_minimal_descriptor_to_report_table():
    token = datetime(2026, 7, 14, tzinfo=timezone.utc)

    class DynamicConnection(_Connection):
        def __init__(self):
            super().__init__()
            self.snapshot_payload = None

        async def execute(self, sql, *_args):
            raise AssertionError(f"dynamic completion must not execute side-table mutations: {sql}")

        async def executemany(self, sql, _args):
            raise AssertionError(f"dynamic completion must not write geo_static_report_lists: {sql}")

        async def fetchval(self, sql, *args):
            self.fetchval_calls.append((sql, args))
            if "SELECT client_id::text" in sql:
                return "client-1"
            if "pg_try_advisory_xact_lock_shared" in sql:
                return True
            if "FROM geo_clients" in sql and "SELECT name" in sql:
                return "AnswerX"
            if "FROM geo_clients" in sql:
                return True
            raise AssertionError(sql)

        async def fetch(self, sql, *args):
            self.fetch_calls.append((sql, args))
            if "SELECT DISTINCT cp.topic_id::text" in sql:
                return [{"id": "topic-1", "name": "AI Search"}]
            if "SELECT DISTINCT cp.platform AS id" in sql:
                return [{"id": "chatgpt", "name": "ChatGPT"}]
            raise AssertionError(sql)

        async def fetchrow(self, sql, *args):
            self.fetchrow_calls.append((sql, args))
            if "FOR UPDATE" in sql:
                self.events.append("owner:lock")
                return {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value}
            assert "UPDATE geo_static_reports" in sql
            assert "geo_static_report_lists" not in sql
            self.events.append("dynamic:update")
            self.snapshot_payload = args[4]
            return self.fetchrow_result

    conn = DynamicConnection()
    dates = type("Dates", (), {
        "report_date": date(2026, 7, 14),
        "timezone": "Asia/Shanghai",
        "window_start": date(2026, 7, 8),
        "window_end": date(2026, 7, 14),
        "window_days": 7,
    })()

    report = asyncio.run(StaticReportRepository(_Pool(conn)).complete_dynamic(
        "report-1",
        token,
        dates,
        {"raw_results": 17},
        [],
    ))

    assert report["status"] == StaticReportStatus.COMPLETED.value
    assert conn.events == [
        "transaction:enter",
        "owner:lock",
        "dynamic:update",
        "transaction:commit",
    ]
    descriptor = __import__("json").loads(conn.snapshot_payload)
    assert descriptor == {
        "version": DYNAMIC_REPORT_VERSION,
        "client": {"id": "client-1", "name": "AnswerX"},
        "report": {
            "date": "2026-07-14",
            "timezone": "Asia/Shanghai",
            "window_start": "2026-07-08",
            "window_end": "2026-07-14",
            "window_days": 7,
            "rendering_mode": RenderingMode.MULTI_DAY.value,
        },
        "filters": {
            "topics": [{"id": "topic-1", "name": "AI Search"}],
            "platforms": [{"id": "chatgpt", "name": "ChatGPT"}],
        },
    }


def test_stale_takeover_fences_old_owner_from_every_terminal_mutation():
    old_token = datetime(2026, 7, 7, 1, 0, tzinfo=timezone.utc)
    current_token = datetime(2026, 7, 7, 2, 0, tzinfo=timezone.utc)

    class FenceTransaction:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            await self.connection.lock.acquire()

        async def __aexit__(self, *_args):
            self.connection.lock.release()

    class FenceConnection:
        def __init__(self):
            self.lock = asyncio.Lock()
            self.status = StaticReportStatus.MATERIALIZING.value
            self.token = old_token
            self.mutations = []

        def transaction(self):
            return FenceTransaction(self)

        async def fetchval(self, sql, *_args):
            if "pg_try_advisory_xact_lock_shared" in sql:
                return True
            if "FROM geo_clients" in sql:
                return True
            if "SELECT client_id::text" in sql:
                return "client-1"
            return None

        async def fetchrow(self, sql, *args):
            if "INSERT INTO geo_static_reports" in sql:
                return None
            if "WHERE client_id = $1::uuid AND report_date = $2 AND window_days = $3" in sql:
                return {
                    "id": "report-1", "client_id": args[0], "report_date": args[1],
                    "status": self.status, "updated_at": self.token,
                }
            if "INTERVAL '1 second'" in sql:
                assert args[2] == old_token
                self.token = current_token
                return {
                    "id": "report-1", "client_id": "client-1", "report_date": date(2026, 7, 7),
                    "status": self.status, "updated_at": self.token,
                }
            if "FOR UPDATE" in sql:
                assert "status = $2" in sql
                assert "updated_at IS NOT DISTINCT FROM $3::timestamptz" in sql
                if self.status == args[1] and self.token == args[2]:
                    return {"id": args[0], "status": self.status, "updated_at": self.token}
                return None
            if "UPDATE geo_static_reports" in sql:
                self.status = args[3]
                self.mutations.append(f"status:{args[3]}")
                return {
                    "id": args[0], "client_id": "client-1",
                    "status": self.status, "updated_at": current_token,
                }
            raise AssertionError(sql)

        async def execute(self, sql, *_args):
            assert "DELETE FROM geo_static_report_lists" in sql
            self.mutations.append("blobs:delete")

        async def executemany(self, sql, _args):
            assert "INSERT INTO geo_static_report_lists" in sql
            self.mutations.append("blobs:insert")

    connection = FenceConnection()
    repository = StaticReportRepository(_Pool(connection))
    dates = type("Dates", (), {
        "report_date": date(2026, 7, 7), "timezone": "Asia/Shanghai",
        "window_start": date(2026, 7, 1), "window_end": date(2026, 7, 7), "window_days": 7,
    })()
    takeover = asyncio.run(repository.claim_materialization("client-1", dates, "new-user"))
    assert takeover["acquired_materialization"] is True
    assert takeover["materialization_token"] == current_token
    valid_blobs = build_static_report_list_blobs(_snapshot())

    async def reject_old_owner_operations():
        with pytest.raises(MaterializationLeaseLost):
            await repository.mark_not_ready("report-1", old_token, ["not-ready"], {})
        with pytest.raises(MaterializationLeaseLost):
            await repository.fail("report-1", old_token, "old failure")
        with pytest.raises(MaterializationLeaseLost):
            await repository.complete(
                "report-1", old_token, {}, RenderingMode.MULTI_DAY, {}, [], valid_blobs,
            )

    asyncio.run(reject_old_owner_operations())
    assert connection.mutations == []

    async def race_finalization():
        old = repository.complete(
            "report-1", old_token, {}, RenderingMode.MULTI_DAY, {}, [], valid_blobs,
        )
        current = repository.complete(
            "report-1", current_token, {}, RenderingMode.MULTI_DAY, {}, [], valid_blobs,
        )
        return await asyncio.gather(old, current, return_exceptions=True)

    old_result, current_result = asyncio.run(race_finalization())
    assert isinstance(old_result, MaterializationLeaseLost)
    assert current_result["status"] == StaticReportStatus.COMPLETED.value
    assert connection.mutations == [
        "blobs:delete", "blobs:insert", f"status:{StaticReportStatus.COMPLETED.value}",
    ]


def test_repository_materialization_claim_has_exactly_one_concurrent_owner():
    class ClaimTransaction:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            await self.connection.lock.acquire()

        async def __aexit__(self, *_args):
            self.connection.lock.release()

    class ClaimConnection:
        def __init__(self):
            self.lock = asyncio.Lock()
            self.row = None

        def transaction(self):
            return ClaimTransaction(self)

        async def fetchval(self, sql, *_args):
            if "pg_try_advisory_xact_lock_shared" in sql:
                return True
            if "FROM geo_clients" in sql:
                return True
            return None

        async def fetchrow(self, sql, *args):
            if "INSERT INTO geo_static_reports" in sql:
                if self.row is not None:
                    return None
                self.row = {
                    "id": "report-claim",
                    "client_id": args[0],
                    "report_date": args[1],
                    "timezone": args[2],
                    "status": StaticReportStatus.MATERIALIZING.value,
                    "snapshot_version": args[4],
                    "data_window_start": args[5],
                    "data_window_end": args[6],
                    "window_days": args[7],
                    "rendering_mode": args[8],
                    "data_completeness": {},
                    "warnings": [],
                    "updated_at": datetime.now(timezone.utc),
                }
                return self.row
            if "WHERE client_id = $1::uuid AND report_date = $2 AND window_days = $3" in sql:
                return self.row
            if "UPDATE geo_static_reports" in sql and "INTERVAL '1 second'" in sql:
                return None
            if "WHERE id = $1::uuid" in sql:
                return self.row
            raise AssertionError(sql)

    connection = ClaimConnection()
    repository = StaticReportRepository(_Pool(connection))
    dates = type("Dates", (), {
        "report_date": date(2026, 7, 7),
        "timezone": "Asia/Shanghai",
        "window_start": date(2026, 7, 1),
        "window_end": date(2026, 7, 7),
        "window_days": 7,
    })()

    async def claim_twice():
        return await asyncio.gather(
            repository.claim_materialization("client-1", dates, "user-1"),
            repository.claim_materialization("client-1", dates, "user-2"),
        )

    claims = asyncio.run(claim_twice())
    assert sorted(claim["acquired_materialization"] for claim in claims) == [False, True]
    assert {claim["report"]["id"] for claim in claims} == {"report-claim"}
    owner = next(claim for claim in claims if claim["acquired_materialization"])
    assert owner["report"]["snapshot_version"] == DYNAMIC_REPORT_VERSION
    assert owner["materialization_token"] == owner["report"]["updated_at"]
    assert next(claim for claim in claims if not claim["acquired_materialization"])["materialization_token"] is None


def test_repository_retry_claim_uses_status_and_updated_at_compare_and_swap():
    updated_at = datetime.now(timezone.utc)

    class RetryConnection:
        def transaction(self):
            return _Transaction([])

        async def fetchval(self, sql, *_args):
            if "pg_try_advisory_xact_lock_shared" in sql:
                return True
            if "FROM geo_clients" in sql:
                return True
            return None

        async def fetchrow(self, sql, *args):
            if "INSERT INTO geo_static_reports" in sql:
                return None
            if "WHERE client_id = $1::uuid AND report_date = $2 AND window_days = $3" in sql:
                return {
                    "id": "report-retry", "client_id": args[0], "report_date": args[1],
                    "status": StaticReportStatus.FAILED.value, "updated_at": updated_at,
                }
            if "UPDATE geo_static_reports" in sql:
                assert "AND status = $2" in sql
                assert "updated_at IS NOT DISTINCT FROM $3::timestamptz" in sql
                assert args[1] == StaticReportStatus.FAILED.value
                assert args[2] == updated_at
                return {
                    "id": "report-retry", "client_id": "client-1", "report_date": date(2026, 7, 7),
                    "status": StaticReportStatus.MATERIALIZING.value, "updated_at": datetime.now(timezone.utc),
                }
            raise AssertionError(sql)

    dates = type("Dates", (), {
        "report_date": date(2026, 7, 7), "timezone": "Asia/Shanghai",
        "window_start": date(2026, 7, 1), "window_end": date(2026, 7, 7), "window_days": 7,
    })()
    result = asyncio.run(StaticReportRepository(_Pool(RetryConnection())).claim_materialization(
        "client-1", dates, "user-1",
    ))
    assert result["acquired_materialization"] is True
    assert result["report"]["status"] == StaticReportStatus.MATERIALIZING.value
    assert result["materialization_token"] == result["report"]["updated_at"]


def test_materializing_lease_fresh_cannot_be_stolen_and_stale_has_one_recovery_owner():
    class LeaseTransaction:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            await self.connection.lock.acquire()

        async def __aexit__(self, *_args):
            self.connection.lock.release()

    class LeaseConnection:
        def __init__(self, stale):
            self.lock = asyncio.Lock()
            self.stale = stale
            self.row = {
                "id": "report-lease", "client_id": "client-1", "report_date": date(2026, 7, 7),
                "status": StaticReportStatus.MATERIALIZING.value,
                "updated_at": datetime(2026, 7, 7, tzinfo=timezone.utc),
            }

        def transaction(self):
            return LeaseTransaction(self)

        async def fetchval(self, sql, *_args):
            if "pg_try_advisory_xact_lock_shared" in sql:
                return True
            if "FROM geo_clients" in sql:
                return True
            return None

        async def fetchrow(self, sql, *args):
            if "INSERT INTO geo_static_reports" in sql:
                return None
            if "WHERE client_id = $1::uuid AND report_date = $2 AND window_days = $3" in sql:
                return dict(self.row)
            if "UPDATE geo_static_reports" in sql and "INTERVAL '1 second'" in sql:
                if not self.stale or args[2] != self.row["updated_at"]:
                    return None
                self.stale = False
                self.row = {**self.row, "updated_at": datetime.now(timezone.utc)}
                return dict(self.row)
            if "WHERE id = $1::uuid" in sql:
                return dict(self.row)
            raise AssertionError(sql)

    dates = type("Dates", (), {
        "report_date": date(2026, 7, 7), "timezone": "Asia/Shanghai",
        "window_start": date(2026, 7, 1), "window_end": date(2026, 7, 7), "window_days": 7,
    })()

    async def claim_twice(connection):
        repository = StaticReportRepository(_Pool(connection))
        return await asyncio.gather(
            repository.claim_materialization("client-1", dates, "user-1"),
            repository.claim_materialization("client-1", dates, "user-2"),
        )

    fresh_claims = asyncio.run(claim_twice(LeaseConnection(stale=False)))
    assert [claim["acquired_materialization"] for claim in fresh_claims] == [False, False]
    stale_claims = asyncio.run(claim_twice(LeaseConnection(stale=True)))
    assert sorted(claim["acquired_materialization"] for claim in stale_claims) == [False, True]
    stale_owner = next(claim for claim in stale_claims if claim["acquired_materialization"])
    assert stale_owner["materialization_token"] == stale_owner["report"]["updated_at"]
    assert stale_owner["materialization_token"] != datetime(2026, 7, 7, tzinfo=timezone.utc)


def test_repository_sorts_frozen_rows_globally_before_pagination_with_nulls_last_and_stable_ties():
    conn = _Connection()
    conn.blob_result = {
        "list_version": "static-report-v5",
        "row_count": 4,
        "rows_payload": [
            {"row_key": "null", "domain": "null.example", "citation_count": None, "default_position": 3},
            {"row_key": "b", "domain": "b.example", "citation_count": 5, "default_position": 1},
            {"row_key": "a", "domain": "a.example", "citation_count": 5, "default_position": 0},
            {"row_key": "c", "domain": "c.example", "citation_count": 1, "default_position": 2},
        ],
    }
    repo = StaticReportRepository(_Pool(conn))

    result = asyncio.run(repo.list_frozen_rows(
        "report-1",
        "client-1",
        "citation.domain",
        sort_by="citation_count",
        sort_order="desc",
        limit=2,
        offset=1,
    ))

    assert result["total"] == 4
    assert [row["domain"] for row in result["items"]] == ["b.example", "c.example"]
    blob_sql, blob_args = next(
        (sql, args) for sql, args in conn.fetch_calls
        if "FROM geo_static_report_lists" in sql and args[2] == "citation.domain"
    )
    assert "ORDER BY LIST_TYPE" in blob_sql.upper()
    assert blob_args == ("report-1", "client-1", "citation.domain")


def test_repository_default_sort_pages_follow_materialized_default_positions_exactly():
    materialized = [
        {
            "row_key": f"key-{position}",
            "topic_id": f"topic-{position}",
            "topic_name": f"Topic {position}",
            "total_mentions": 10 - position,
            "default_position": position,
        }
        for position in range(4)
    ]
    conn = _Connection()
    conn.blob_result = {
        "list_version": "static-report-v5",
        "row_count": len(materialized),
        "rows_payload": materialized,
    }
    repo = StaticReportRepository(_Pool(conn))
    page1 = asyncio.run(repo.list_frozen_rows(
        "report-1", "client-1", "visibility.topic",
        sort_by="total_mentions", sort_order="desc", limit=2, offset=0,
    ))
    page2 = asyncio.run(repo.list_frozen_rows(
        "report-1", "client-1", "visibility.topic",
        sort_by=None, sort_order=None, limit=2, offset=2,
    ))

    assert [item["topic_id"] for item in page1["items"] + page2["items"]] == [
        "topic-0", "topic-1", "topic-2", "topic-3",
    ]


def test_repository_marks_legacy_or_missing_materialization_unavailable_without_live_fallback():
    conn = _Connection()
    conn.fetchval_result = "static-report-v3"
    repo = StaticReportRepository(_Pool(conn))

    with pytest.raises(StaticReportListUnavailable, match="sorting_unavailable_for_snapshot_version"):
        asyncio.run(repo.list_frozen_rows(
            "report-1",
            "client-1",
            "citation.domain",
            sort_by="citation_count",
            sort_order="desc",
            limit=20,
            offset=0,
        ))

    assert all(
        "geo_citations" not in sql and "geo_results" not in sql
        for sql, _args in [*conn.fetchrow_calls, *conn.fetch_calls]
    )


def test_repository_applies_server_owned_scope_search_and_exact_filters_before_count_and_page():
    conn = _Connection()
    conn.blob_result = {
        "list_version": "static-report-v5",
        "row_count": 2,
        "rows_payload": [
            {"row_key": "match", "topic_id": "topic-1", "topic_name": "T", "prompt_id": "prompt-1", "prompt_text": "P", "brand_name": "Acme", "mention_count": 5, "default_position": 0},
            {"row_key": "other", "topic_id": "topic-2", "topic_name": "U", "prompt_id": "prompt-2", "prompt_text": "Q", "brand_name": "Other", "mention_count": 9, "default_position": 1},
        ],
    }
    repo = StaticReportRepository(_Pool(conn))

    scoped = asyncio.run(repo.list_frozen_rows(
        "report-1", "client-1", "visibility.topic_prompt_brand",
        sort_by="mention_count", sort_order="desc", limit=20, offset=0,
        parent_key="topic-1", prompt_key="prompt-1", search="Acme",
    ))
    assert scoped["total"] == 1
    assert scoped["items"][0]["brand_name"] == "Acme"

    conn.blob_result = {
        "list_version": "static-report-v5",
        "row_count": 2,
        "rows_payload": [
            {"row_key": "positive", "theme_name": "Quiet", "sentiment": "Positive", "occurrence_count": 3, "default_position": 0},
            {"row_key": "negative", "theme_name": "Quiet", "sentiment": "Negative", "occurrence_count": 4, "default_position": 1},
        ],
    }
    themes = asyncio.run(repo.list_frozen_rows(
        "report-1", "client-1", "sentiment.theme",
        sort_by="occurrence_count", sort_order="desc", limit=20, offset=0,
        search="quiet", sentiment="Positive",
    ))
    assert themes["total"] == 1
    assert themes["items"][0]["sentiment"] == "Positive"


def test_repository_rejects_scope_or_filter_not_registered_for_list_type():
    repo = StaticReportRepository(_Pool(_Connection()))
    with pytest.raises(ValueError, match="parent_key"):
        asyncio.run(repo.list_frozen_rows(
            "report-1", "client-1", "citation.domain",
            sort_by=None, sort_order=None, parent_key="topic-1",
        ))
    with pytest.raises(ValueError, match="sentiment"):
        asyncio.run(repo.list_frozen_rows(
            "report-1", "client-1", "prompt.ranking",
            sort_by=None, sort_order=None, sentiment="Positive",
        ))
    with pytest.raises(ValueError, match="parent_key is required"):
        asyncio.run(repo.list_frozen_rows(
            "report-1", "client-1", "visibility.topic_prompt",
            sort_by=None, sort_order=None,
        ))
    with pytest.raises(ValueError, match="prompt_key is required"):
        asyncio.run(repo.list_frozen_rows(
            "report-1", "client-1", "visibility.topic_prompt_brand",
            sort_by=None, sort_order=None, parent_key="topic-1",
        ))
