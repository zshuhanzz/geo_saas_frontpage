import asyncio
from datetime import date
from uuid import UUID

from routers.insights import prompt_metrics
from routers.insights import visibility


class FakeVisibilityDatabase:
    def __init__(self):
        self.fetch_one_calls = 0

    async def fetch_one(self, sql, params=None):
        self.fetch_one_calls += 1
        if "own_avg_position" in sql:
            return {
                "total_mentions": 4,
                "own_mentions": 2,
                "own_avg_position": 1.5,
            }
        if "total_responses" in sql:
            return {
                "total_responses": 3,
                "own_response_count": 2,
            }
        return None

    async def fetch_all(self, sql, params=None):
        if "GROUP BY bm.brand_name" in sql and "COUNT(*) AS mention_count" in sql:
            return [
                {
                    "brand_name": "Dreamina",
                    "mention_count": 2,
                    "is_own": 1,
                    "avg_position": 1.5,
                },
                {
                    "brand_name": "Competitor",
                    "mention_count": 2,
                    "is_own": 0,
                    "avg_position": 3.0,
                },
            ]
        if "response_count" in sql:
            return [
                {"brand_name": "Dreamina", "response_count": 2},
                {"brand_name": "Competitor", "response_count": 2},
            ]
        return []


def test_visibility_summary_uses_own_distinct_responses_for_prompt_metrics(monkeypatch):
    monkeypatch.setattr(visibility, "database", FakeVisibilityDatabase())

    result = asyncio.run(
        visibility._query_visibility(
            mention_where_sql="bm.client_id = :client_id",
            response_where_sql="gr.client_id = :client_id",
            base_params={"client_id": "client-1"},
            interval="daily",
        )
    )

    assert result["mentioned"] == 2
    assert result["total_query"] == 3
    assert result["visibility_score"] == 66.67
    assert result["own_avg_position"] == 1.5


class FakeVisibilityTop20Database(FakeVisibilityDatabase):
    async def fetch_val(self, sql, params=None):
        return sum(100 - i for i in range(1, 26))

    async def fetch_all(self, sql, params=None):
        if "GROUP BY bm.brand_name" in sql and "COUNT(*) AS mention_count" in sql:
            return [
                {
                    "brand_name": f"Brand {i:02d}",
                    "mention_count": 100 - i,
                    "is_own": 1 if i == 3 else 0,
                    "avg_position": float(i),
                }
                for i in range(1, 26)
            ]
        if "response_count" in sql:
            return []
        return []


def test_sov_ranking_returns_complete_brand_universe(monkeypatch):
    monkeypatch.setattr(visibility, "database", FakeVisibilityTop20Database())

    result = asyncio.run(
        visibility._query_visibility(
            mention_where_sql="bm.client_id = :client_id",
            response_where_sql="gr.client_id = :client_id",
            base_params={"client_id": "client-1"},
            interval="daily",
        )
    )

    assert len(result["sov_ranking"]) == 25
    assert result["sov_ranking"][0]["brand_name"] == "Brand 01"
    assert result["sov_ranking"][-1]["brand_name"] == "Brand 25"


def test_split_sov_chart_also_returns_complete_brand_universe(monkeypatch):
    monkeypatch.setattr(visibility, "database", FakeVisibilityTop20Database())

    result = asyncio.run(visibility._query_visibility_sov_chart(
        mention_where_sql="bm.client_id = :client_id",
        params={"client_id": "client-1"},
        interval="daily",
    ))

    assert len(result["ranking"]) == 25
    assert result["ranking"][-1]["brand_name"] == "Brand 25"


class FakeVisibilitySparseAvgPositionDatabase(FakeVisibilityDatabase):
    async def fetch_all(self, sql, params=None):
        if "AS avg_pos\n" in sql:
            return [
                {"bucket": date(2026, 5, 21), "avg_pos": 2.0},
                {"bucket": date(2026, 5, 23), "avg_pos": 1.5},
            ]
        return await super().fetch_all(sql, params)


def test_avg_position_series_keeps_empty_daily_axis_slots(monkeypatch):
    monkeypatch.setattr(visibility, "database", FakeVisibilitySparseAvgPositionDatabase())

    result = asyncio.run(
        visibility._query_visibility(
            mention_where_sql="bm.client_id = :client_id",
            response_where_sql="gr.client_id = :client_id",
            base_params={
                "client_id": "client-1",
                "start_date": date(2026, 5, 21),
                "end_date": date(2026, 5, 23),
            },
            interval="daily",
        )
    )

    assert result["avg_position_series"] == [
        {"date": "2026-05-21", "avg_position": 2.0},
        {"date": "2026-05-22", "avg_position": None},
        {"date": "2026-05-23", "avg_position": 1.5},
    ]


class FakeVisibilityRouterDatabase(FakeVisibilityDatabase):
    def __init__(self):
        super().__init__()
        self.fetch_all_sql = []

    async def fetch_all(self, sql, params=None):
        self.fetch_all_sql.append(sql)
        if "geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        return await super().fetch_all(sql, params)


def test_prompt_table_drilldown_keeps_visibility_intent_filter(monkeypatch):
    fake_db = FakeVisibilityRouterDatabase()
    monkeypatch.setattr(visibility, "database", fake_db)

    asyncio.run(
        visibility.get_visibility(
            client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
            topic_id="b3a1971e-063b-4b21-8874-d9a257fc5c25",
            date_from="2026-05-13",
            date_to="2026-05-17",
            interval="daily",
        )
    )

    sql_text = "\n".join(fake_db.fetch_all_sql)
    assert "geo_global_intents" in sql_text
    assert "cp.intent IN (:vis_intent_0)" in sql_text


def test_prompt_ids_drilldown_keeps_visibility_intent_filter(monkeypatch):
    fake_db = FakeVisibilityRouterDatabase()
    monkeypatch.setattr(visibility, "database", fake_db)

    asyncio.run(
        visibility.get_visibility(
            client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
            prompt_ids="11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222",
            date_from="2026-05-13",
            date_to="2026-05-17",
            interval="daily",
        )
    )

    sql_text = "\n".join(fake_db.fetch_all_sql)
    assert "geo_global_intents" in sql_text
    assert "cp.intent IN (:vis_intent_0)" in sql_text


class FakePromptMetricsDatabase:
    def __init__(self):
        self.fetch_all_calls = []

    async def fetch_all(self, sql, params=None):
        self.fetch_all_calls.append((sql, params or {}))
        if "geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        return []


def test_prompt_metrics_keeps_visibility_intent_filter(monkeypatch):
    fake_db = FakePromptMetricsDatabase()
    monkeypatch.setattr(prompt_metrics, "database", fake_db)

    asyncio.run(
        prompt_metrics.get_prompt_metrics(
            client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
            date_from="2026-05-13",
            date_to="2026-05-17",
        )
    )

    sql_text = "\n".join(sql for sql, _ in fake_db.fetch_all_calls)
    params = {}
    for _, call_params in fake_db.fetch_all_calls:
        params.update(call_params)
    assert "geo_global_intents" in sql_text
    assert "cp.intent IN (:vis_intent_0)" in sql_text
    assert "cp.is_active = TRUE" in sql_text
    assert "WHERE client_id = :client_id AND is_active = TRUE" in " ".join(sql_text.split())
    assert params["vis_intent_0"] == "Solution Discovery"


class FakePromptMetricsBrandRankDatabase:
    async def fetch_all(self, sql, params=None):
        if "geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        if "COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END)" in sql:
            return [
                {
                    "client_prompt_id": "11111111-1111-1111-1111-111111111111",
                    "total_query": 10,
                    "mentioned": 7,
                }
            ]
        if "SUM(bm.mention_position)" in sql:
            return []
        if "COUNT(DISTINCT gr.result_id)::int AS response_count" in sql:
            return [
                {
                    "client_prompt_id": "11111111-1111-1111-1111-111111111111",
                    "brand_name": "Competitor A",
                    "response_count": 9,
                    "mention_count": 11,
                    "is_own": 0,
                },
                {
                    "client_prompt_id": "11111111-1111-1111-1111-111111111111",
                    "brand_name": "Dreamina",
                    "response_count": 7,
                    "mention_count": 8,
                    "is_own": 1,
                },
            ]
        return []


def test_prompt_metrics_returns_brand_rank_inputs(monkeypatch):
    monkeypatch.setattr(prompt_metrics, "database", FakePromptMetricsBrandRankDatabase())

    result = asyncio.run(
        prompt_metrics.get_prompt_metrics(
            client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
            date_from="2026-05-13",
            date_to="2026-05-17",
        )
    )

    metric = result.metrics["11111111-1111-1111-1111-111111111111"]
    assert metric.brand_rank == 2
    assert metric.brand_response_counts == {"Competitor A": 9, "Dreamina": 7}
    assert metric.brand_mention_counts == {"Competitor A": 11, "Dreamina": 8}
    assert metric.own_brand_names == ["Dreamina"]


class FakeOrderedPromptMetricsDatabase:
    async def fetch_all(self, sql, params=None):
        if "geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        if "COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END)" in sql:
            return [
                {"client_prompt_id": "11111111-1111-1111-1111-111111111111", "total_query": 10, "mentioned": 2},
                {"client_prompt_id": "22222222-2222-2222-2222-222222222222", "total_query": 10, "mentioned": 8},
            ]
        if "SELECT id AS client_prompt_id" in sql:
            return [
                {"client_prompt_id": "11111111-1111-1111-1111-111111111111"},
                {"client_prompt_id": "22222222-2222-2222-2222-222222222222"},
                {"client_prompt_id": "33333333-3333-3333-3333-333333333333"},
            ]
        return []


def test_prompt_metrics_returns_explicit_full_order_contract(monkeypatch):
    monkeypatch.setattr(prompt_metrics, "database", FakeOrderedPromptMetricsDatabase())

    result = asyncio.run(prompt_metrics.get_prompt_metrics(
        client_id=UUID("b0e10518-5f70-426f-b09e-dbe025984ba1"),
        date_from="2026-05-13",
        date_to="2026-05-17",
        sort_by="visibility_score",
        sort_order="desc",
    ))

    assert result.total == 3
    assert result.ordered_prompt_ids == [
        "22222222-2222-2222-2222-222222222222",
        "11111111-1111-1111-1111-111111111111",
        "33333333-3333-3333-3333-333333333333",
    ]
    assert set(result.ordered_prompt_ids) == set(result.metrics)
