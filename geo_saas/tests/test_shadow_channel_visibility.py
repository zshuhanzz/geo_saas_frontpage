from __future__ import annotations

import asyncio
from uuid import UUID

from routers.insights import product_visibility, shadow_cooccurrence


CLIENT_ID = UUID("804456ec-b9db-4d68-9b45-ee7064459542")


class ProductVisibilityDatabase:
    def __init__(
        self,
        *,
        has_shadow: bool,
        metric_rows=None,
        configured_rows=None,
        time_rows=None,
        total_responses: int = 0,
        mentioned_responses: int = 0,
    ):
        self.has_shadow = has_shadow
        self.metric_rows = list(metric_rows or [])
        self.configured_rows = list(configured_rows or [])
        self.time_rows = list(time_rows or [])
        self.total_responses = total_responses
        self.mentioned_responses = mentioned_responses
        self.calls = []

    async def fetch_one(self, sql, params=None):
        self.calls.append(("fetch_one", sql, params or {}))
        if "FROM geo_results gr" in sql:
            return {
                "total_responses": self.total_responses,
                "mentioned_responses": self.mentioned_responses,
            }
        return {"has_shadow_brand": self.has_shadow}

    async def fetch_all(self, sql, params=None):
        self.calls.append(("fetch_all", sql, params or {}))
        if "FROM geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        if "FROM geo_client_topic_products" in sql:
            return self.configured_rows
        if "GROUP BY pm.product_name" in sql:
            return self.metric_rows
        if "GROUP BY" in sql and "FROM geo_results gr" in sql:
            return self.time_rows
        return []


def _product_row(name: str, mentions: int = 0):
    return {
        "product_name": name,
        "owner_brand_name": None,
        "owner_peer_name": None,
        "shadow_sub_role": None,
        "mention_count": mentions,
        "response_count": mentions,
        "avg_position": 2 if mentions else None,
    }


def _call_product_visibility():
    return product_visibility.get_product_visibility(
        client_id=CLIENT_ID,
        product_role="own",
        topic_id=None,
        topic_ids=None,
        platform=None,
        country=None,
        prompt_id=None,
        date_from="2026-07-21",
        date_to="2026-07-23",
        interval="daily",
        sort_by="mention_count",
        sort_order="desc",
    )


def test_shadow_workspace_lists_configured_products_as_zero_without_mentions(monkeypatch):
    db = ProductVisibilityDatabase(
        has_shadow=True,
        configured_rows=[_product_row("PSR055220"), _product_row("PSR055110")],
    )
    monkeypatch.setattr(product_visibility, "database", db)

    result = asyncio.run(_call_product_visibility())

    assert result.reason is None
    assert result.summary is not None
    assert result.summary.total_mentions == 0
    assert result.summary.unique_products == 2
    assert [(row.product_name, row.mention_count, row.sov_pct) for row in result.ranking] == [
        ("PSR055110", 0, 0),
        ("PSR055220", 0, 0),
    ]


def test_non_shadow_workspace_preserves_existing_no_data_behavior(monkeypatch):
    db = ProductVisibilityDatabase(
        has_shadow=False,
        configured_rows=[_product_row("Configured but not mentioned")],
    )
    monkeypatch.setattr(product_visibility, "database", db)

    result = asyncio.run(_call_product_visibility())

    assert result.reason == "no_data"
    assert result.ranking is None
    assert not any("FROM geo_client_topic_products" in sql for _, sql, _ in db.calls)


def test_shadow_workspace_merges_real_metrics_with_zero_products(monkeypatch):
    db = ProductVisibilityDatabase(
        has_shadow=True,
        metric_rows=[_product_row("PSR055110", mentions=4)],
        configured_rows=[_product_row("PSR055110"), _product_row("PSR055220")],
    )
    monkeypatch.setattr(product_visibility, "database", db)

    result = asyncio.run(_call_product_visibility())

    assert result.summary.total_mentions == 4
    assert [(row.product_name, row.mention_count, row.sov_pct) for row in result.ranking] == [
        ("PSR055110", 4, 100.0),
        ("PSR055220", 0, 0),
    ]


def test_product_visibility_uses_response_coverage_and_preserves_sov(monkeypatch):
    db = ProductVisibilityDatabase(
        has_shadow=True,
        total_responses=84,
        mentioned_responses=6,
        metric_rows=[
            {**_product_row("Tacoma (05-23)", mentions=2), "response_count": 2},
            {**_product_row("Tundra (22-26)", mentions=1), "response_count": 1},
            {**_product_row("Wrangler (07-18)", mentions=4), "response_count": 3},
        ],
        time_rows=[{
            "bucket": __import__("datetime").date(2026, 7, 23),
            "total": 7,
            "total_responses": 84,
            "mentioned_responses": 6,
        }],
    )
    monkeypatch.setattr(product_visibility, "database", db)

    result = asyncio.run(_call_product_visibility())

    assert result.summary.visibility_score == 7.14
    assert result.summary.total_responses == 84
    assert result.summary.mentioned_responses == 6
    rows = {row.product_name: row for row in result.ranking}
    assert rows["Tacoma (05-23)"].visibility_pct == 2.38
    assert rows["Tacoma (05-23)"].sov_pct == 28.57
    point = next(row for row in result.time_series if row.date == "2026-07-23")
    assert point.visibility_score == 7.14
    assert point.total_responses == 84
    assert point.mentioned_responses == 6

    sql = "\n".join(call[1] for call in db.calls)
    assert "AT TIME ZONE 'Asia/Shanghai'" in sql
    assert "FROM geo_global_intents" in sql
    assert "cp.intent IN" in sql


class EmptyCrossDatabase:
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics

    async def fetch_all(self, _sql, _params=None):
        return []

    async def fetch_one(self, _sql, _params=None):
        return self.diagnostics


def test_product_cross_empty_state_distinguishes_missing_analysis(monkeypatch):
    monkeypatch.setattr(
        shadow_cooccurrence,
        "database",
        EmptyCrossDatabase({
            "has_shadow_brand": True,
            "has_own_product": True,
            "has_product_mentions": False,
        }),
    )

    result = asyncio.run(shadow_cooccurrence.shadow_product_cooccurrence(
        client_id=CLIENT_ID,
        date_from="2026-07-21",
        date_to="2026-07-22",
    ))

    assert result.reason == "no_analyzed_product_mentions"


def test_product_cross_empty_state_identifies_missing_shadow_configuration(monkeypatch):
    monkeypatch.setattr(
        shadow_cooccurrence,
        "database",
        EmptyCrossDatabase({
            "has_shadow_brand": False,
            "has_own_product": True,
            "has_product_mentions": False,
        }),
    )

    result = asyncio.run(shadow_cooccurrence.shadow_product_cooccurrence(
        client_id=CLIENT_ID,
        date_from="2026-07-21",
        date_to="2026-07-22",
    ))

    assert result.reason == "missing_shadow_brand_configuration"
