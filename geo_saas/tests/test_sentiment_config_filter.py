import asyncio
from datetime import date

from routers import sentiment


class FakeDatabase:
    def __init__(self, intent_rows):
        self.intent_rows = intent_rows
        self.fetch_all_calls = []
        self.fetch_one_calls = []

    async def fetch_all(self, sql, params=None):
        self.fetch_all_calls.append((sql, params or {}))
        if "geo_global_intents" in sql:
            return self.intent_rows
        return []

    async def fetch_one(self, sql, params=None):
        self.fetch_one_calls.append((sql, params or {}))
        return {
            "total": 0,
            "rated": 0,
            "positive": 0,
            "mixed_neutral": 0,
            "negative": 0,
            "insufficient_evidence": 0,
        }


def test_get_sentiment_filters_to_configured_sentiment_intents(monkeypatch):
    fake_db = FakeDatabase([
        {"intent_name": "Specific Inquiries"},
        {"intent_name": "Competitive Evaluation"},
    ])
    monkeypatch.setattr(sentiment, "database", fake_db)

    asyncio.run(sentiment.get_sentiment(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        date_from="2026-05-01",
        date_to="2026-05-10",
        interval="daily",
    ))

    assert any(
        "categories @> :category_json::jsonb" in sql
        and params.get("category_json") == '["Sentiment"]'
        for sql, params in fake_db.fetch_all_calls
    )
    metric_sql = "\n".join(sql for sql, _ in fake_db.fetch_one_calls + fake_db.fetch_all_calls)
    assert "cp.intent IN (:sent_intent_0,:sent_intent_1)" in metric_sql
    assert "cp.is_active = TRUE" in metric_sql
    metric_params = {}
    for _, params in fake_db.fetch_one_calls + fake_db.fetch_all_calls:
        metric_params.update(params)
    assert metric_params["sent_intent_0"] == "Specific Inquiries"
    assert metric_params["sent_intent_1"] == "Competitive Evaluation"


def test_get_sentiment_returns_empty_when_no_intent_has_sentiment(monkeypatch):
    fake_db = FakeDatabase([])
    monkeypatch.setattr(sentiment, "database", fake_db)

    result = asyncio.run(sentiment.get_sentiment(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        date_from="2026-05-01",
        date_to="2026-05-10",
        interval="daily",
    ))

    assert result.summary.total_count == 0
    metric_sql = "\n".join(sql for sql, _ in fake_db.fetch_one_calls + fake_db.fetch_all_calls)
    assert "1 = 0" in metric_sql


def test_get_sentiment_excludes_insufficient_evidence_from_percentage_denominator(monkeypatch):
    class FourStateDatabase(FakeDatabase):
        def __init__(self):
            super().__init__([{"intent_name": "Competitive Evaluation"}])
            self.kpi_calls = 0

        async def fetch_one(self, sql, params=None):
            self.fetch_one_calls.append((sql, params or {}))
            self.kpi_calls += 1
            if self.kpi_calls == 1:
                return {
                    "total": 10,
                    "rated": 9,
                    "positive": 3,
                    "mixed_neutral": 4,
                    "negative": 2,
                    "insufficient_evidence": 1,
                }
            return {
                "total": 4,
                "rated": 4,
                "positive": 2,
                "mixed_neutral": 1,
                "negative": 1,
                "insufficient_evidence": 0,
            }

    fake_db = FourStateDatabase()
    monkeypatch.setattr(sentiment, "database", fake_db)

    result = asyncio.run(sentiment.get_sentiment(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        date_from="2026-05-01",
        date_to="2026-05-10",
        interval="daily",
    ))

    assert result.summary.total_count == 10
    assert result.summary.rated_count == 9
    assert result.summary.positive_count == 3
    assert result.summary.mixed_neutral_count == 4
    assert result.summary.negative_count == 2
    assert result.summary.insufficient_evidence_count == 1
    assert result.summary.positive_pct == 33.33
    assert result.summary.mixed_neutral_pct == 44.44
    assert result.summary.negative_pct == 22.22
    assert result.summary.positive_pct_change == -16.67


def test_theme_results_uses_same_sentiment_intent_filter(monkeypatch):
    fake_db = FakeDatabase([
        {"intent_name": "Specific Inquiries"},
    ])
    monkeypatch.setattr(sentiment, "database", fake_db)

    asyncio.run(sentiment.get_theme_results(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        theme_name="Easy To Use",
        date_from="2026-05-01",
        date_to="2026-05-10",
    ))

    sql_text = "\n".join(sql for sql, _ in fake_db.fetch_one_calls + fake_db.fetch_all_calls)
    assert "JOIN geo_client_prompts cp ON cp.id = st.client_prompt_id" in sql_text
    assert "cp.intent IN (:sent_intent_0)" in sql_text
    assert "cp.is_active = TRUE" in sql_text


def test_theme_results_accepts_mixed_neutral_filter(monkeypatch):
    fake_db = FakeDatabase([{"intent_name": "Competitive Evaluation"}])
    monkeypatch.setattr(sentiment, "database", fake_db)

    asyncio.run(sentiment.get_theme_results(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        theme_name="Conditional Fit",
        date_from="2026-05-01",
        date_to="2026-05-10",
        sentiment_filter="Mixed/Neutral",
    ))

    calls = fake_db.fetch_one_calls + fake_db.fetch_all_calls
    assert any(
        "st.sentiment = :sent_filter" in sql
        and params.get("sent_filter") == "Mixed/Neutral"
        for sql, params in calls
    )


def test_theme_sort_endpoint_queries_only_the_theme_list(monkeypatch):
    fake_db = FakeDatabase([{"intent_name": "Specific Inquiries"}])
    monkeypatch.setattr(sentiment, "database", fake_db)

    result = asyncio.run(sentiment.get_sentiment_themes(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        date_from="2026-05-01",
        date_to="2026-05-10",
        sort_by="occurrence_change",
        sort_order="asc",
    ))

    metric_sql = "\n".join(sql for sql, _ in fake_db.fetch_all_calls)
    assert "geo_sentiment_themes" in metric_sql
    assert "geo_sentiment_results" not in metric_sql
    assert "cp.is_active = TRUE" in metric_sql
    assert fake_db.fetch_one_calls == []
    assert result.themes == []


def test_theme_previous_period_counts_are_scoped_by_sentiment(monkeypatch):
    class MixedSentimentDatabase:
        async def fetch_all(self, sql, params=None):
            if "AS occurrence_count" in sql:
                return [
                    {"theme_name": "Shared Theme", "sentiment": "Positive", "occurrence_count": 5},
                    {"theme_name": "Shared Theme", "sentiment": "Negative", "occurrence_count": 3},
                ]
            if "AS prev_count" in sql:
                return [
                    {"theme_name": "Shared Theme", "sentiment": "Positive", "prev_count": 2},
                    {"theme_name": "Shared Theme", "sentiment": "Negative", "prev_count": 7},
                ]
            return []

    monkeypatch.setattr(sentiment, "database", MixedSentimentDatabase())
    themes, _positive, _negative = asyncio.run(sentiment._query_theme_rows(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        start=date(2026, 7, 8),
        end=date(2026, 7, 14),
        prev_start=date(2026, 7, 1),
        prev_end=date(2026, 7, 7),
        topic_ids=None,
        products=None,
        prompt_id=None,
        prompt_ids=None,
        platform=None,
        country=None,
        sentiment_filter=None,
        intent_sql="1 = 1",
        intent_params={},
        sort_by="occurrence_count",
        sort_order="desc",
    ))

    keyed = {(row["theme_name"], row["sentiment"]): row for row in themes}
    assert keyed[("Shared Theme", "Positive")]["prev_occurrence_count"] == 2
    assert keyed[("Shared Theme", "Positive")]["occurrence_change"] == 3
    assert keyed[("Shared Theme", "Negative")]["prev_occurrence_count"] == 7
    assert keyed[("Shared Theme", "Negative")]["occurrence_change"] == -4
