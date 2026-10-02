import asyncio
import json
import logging
import sys
import types as py_types
from datetime import datetime
from uuid import UUID

from routers.insights import overview
from routers.insights.citations import (
    CitationTimePoint,
    CitationsFilters,
    CitationsOut,
    CitationsSummary,
)
from routers.insights.visibility import (
    VisibilityFilters,
    VisibilityOut,
    VisibilitySummary,
    VisibilityTimePoint,
)
from routers.sentiment import SentimentFilters, SentimentOut, SentimentSummary, TimeSeriesPoint


CLIENT_ID = UUID("b0e10518-5f70-426f-b09e-dbe025984ba1")


def test_overview_base_scope_excludes_inactive_prompts(monkeypatch):
    async def fake_intent_filter(_category, _prefix):
        return "cp.intent IN (:intent_0)", {"intent_0": "Competitive Evaluation"}

    monkeypatch.setattr(overview, "_metric_intent_filter", fake_intent_filter)
    where_sql, _params = asyncio.run(overview._overview_base_scope(
        client_id=CLIENT_ID,
        topic_ids=None,
        platform=None,
        country=None,
        category="Sentiment",
        prefix="sr",
    ))

    assert "cp.is_active = TRUE" in where_sql


def test_overview_sentiment_queries_exclude_inactive_prompts():
    import inspect

    period_source = inspect.getsource(overview._query_overview_sentiment_period)
    platform_source = inspect.getsource(overview._query_overview_platform_health_light)

    assert 'where = ["sr.client_id = :client_id", "cp.is_active = TRUE"]' in period_source
    assert 'sentiment_where = ["sr.client_id = :client_id", "cp.is_active = TRUE"]' in platform_source


class FakeOverviewDatabase:
    async def fetch_all(self, sql, params=None):
        if "SELECT DISTINCT cp.platform" in sql:
            return [{"platform": "chatgpt"}, {"platform": "gemini"}]
        return []

    async def fetch_val(self, sql, params=None):
        if "MAX(gr.analyzed_at)" in sql:
            return datetime(2026, 6, 19, 11, 30)
        return None


def fake_visibility(platform=None):
    score = 8.93 if platform is None else (9.5 if platform == "chatgpt" else 7.1)
    return VisibilityOut(
        summary=VisibilitySummary(
            visibility_score=score,
            visibility_score_change=1.2,
            visibility_rank=8,
            visibility_rank_change=-1,
            mentioned=158,
            total_query=1770,
            sov_pct=3.62,
            sov_pct_change=0.4,
            sov_rank=8,
            sov_rank_change=0,
            total_mentions=4366,
            own_mentions=158,
            avg_position=2.4,
        ),
        time_series=[
            VisibilityTimePoint(date="2026-06-18", score=7.5, total=1700, own_count=128),
            VisibilityTimePoint(date="2026-06-19", score=score, total=1770, own_count=158),
        ],
        prev_time_series=[],
        avg_position_series=[],
        prev_avg_position_series=[],
        competitive_series={},
        sov_ranking=[
            {
                "brand_name": "Competitor",
                "mention_count": 420,
                "sov_pct": 9.62,
                "visibility_pct": 18.4,
                "avg_position": 2.1,
                "is_own": False,
            },
            {
                "brand_name": "Dreamina",
                "mention_count": 158,
                "sov_pct": 3.62,
                "visibility_pct": score,
                "avg_position": 2.4,
                "is_own": True,
            },
        ],
        visibility_ranking=[
            {
                "brand_name": "Competitor",
                "mention_count": 420,
                "sov_pct": 9.62,
                "visibility_pct": 18.4,
                "avg_position": 2.1,
                "is_own": False,
            },
            {
                "brand_name": "Dreamina",
                "mention_count": 158,
                "sov_pct": 3.62,
                "visibility_pct": score,
                "avg_position": 2.4,
                "is_own": True,
            },
        ],
        position_ranking=[],
        topic_sov_ranking=[
            {
                "topic_id": "topic-ai-video",
                "topic_name": "AI Video",
                "brands": [
                    {"rank": 1, "company_name": "Competitor", "mention_count": 420, "is_own": False},
                    {"rank": 8, "company_name": "Dreamina", "mention_count": 158, "is_own": True},
                ],
                "prompts": [{"prompt_id": "p1"}, {"prompt_id": "p2"}],
            }
        ],
        product_sov_ranking=[],
        filters=VisibilityFilters(
            date_from="2026-06-19",
            date_to="2026-06-19",
            prev_date_from="2026-06-18",
            prev_date_to="2026-06-18",
            interval="daily",
        ),
    )


def fake_citations(platform=None):
    share = 12.5 if platform is None else (14.0 if platform == "chatgpt" else 8.0)
    return CitationsOut(
        summary=CitationsSummary(
            total_citations=300,
            own_domain_share=share,
            own_domain_share_change=2.0,
            own_citation_count=38,
            own_rank=3,
        ),
        domain_ranking=[],
        page_ranking=[],
        category_breakdown=[],
        time_series=[
            CitationTimePoint(date="2026-06-18", own_share=11.0, total=280, own_count=31),
            CitationTimePoint(date="2026-06-19", own_share=share, total=300, own_count=38),
        ],
        prev_time_series=[],
        filters=CitationsFilters(
            date_from="2026-06-19",
            date_to="2026-06-19",
            prev_date_from="2026-06-18",
            prev_date_to="2026-06-18",
            interval="daily",
        ),
    )


def fake_citations_without_rank(platform=None):
    citations = fake_citations(platform)
    citations.summary.own_rank = None
    citations.summary.own_rank_change = None
    return citations


def fake_sentiment(platform=None):
    pct = 64.0 if platform is None else (70.0 if platform == "chatgpt" else 58.0)
    return SentimentOut(
        summary=SentimentSummary(
            positive_pct=pct,
            positive_pct_change=4.0,
            positive_count=96,
            negative_count=18,
            total_count=150,
            positive_top3_themes=["Ease of use"],
            negative_top3_themes=["Pricing"],
        ),
        time_series=[
            TimeSeriesPoint(date="2026-06-18", total=120, positive=72, positive_pct=60.0),
            TimeSeriesPoint(date="2026-06-19", total=150, positive=96, positive_pct=pct),
        ],
        prev_time_series=[],
        themes=[],
        filters=SentimentFilters(
            date_from="2026-06-19",
            date_to="2026-06-19",
            prev_date_from="2026-06-18",
            prev_date_to="2026-06-18",
            interval="daily",
        ),
    )


def fake_overview_summary():
    return overview.OverviewSummary(
        visibility_score=8.93,
        visibility_score_change=1.2,
        visibility_rank=8,
        visibility_rank_change=-1,
        mentioned_responses=158,
        total_responses=1770,
        sov_pct=3.62,
        own_mentions=158,
        total_mentions=4366,
        avg_position=2.4,
        own_citation_share=12.5,
        own_citation_share_change=2.0,
        own_citation_count=38,
        total_citations=300,
        own_citation_rank=None,
        positive_sentiment_pct=64.0,
        positive_sentiment_pct_change=4.0,
        positive_count=96,
        negative_count=18,
        sentiment_total=150,
    )


def fake_overview_core():
    return (
        fake_overview_summary(),
        [
            overview.OverviewMomentumPoint(
                date="2026-06-19",
                visibility_score=8.93,
                own_citation_share=12.5,
                positive_sentiment_pct=64.0,
                total_responses=1770,
                total_citations=300,
                sentiment_total=150,
            )
        ],
        overview.OverviewFilters(
            date_from="2026-06-19",
            date_to="2026-06-19",
            prev_date_from="2026-06-18",
            prev_date_to="2026-06-18",
            interval="daily",
            topic_ids=[],
        ),
    )


def test_overview_composes_lightweight_query_outputs(monkeypatch):
    calls = []

    async def stub_core(**kwargs):
        calls.append(("core", kwargs))
        return fake_overview_core()

    async def stub_platform_health(**kwargs):
        calls.append(("platform_health", kwargs))
        return [
            overview.OverviewPlatformHealthRow(
                platform="chatgpt",
                visibility_score=9.5,
                visibility_rank=None,
                own_citation_share=14.0,
                own_citation_count=20,
                positive_sentiment_pct=70.0,
                negative_count=4,
                sentiment_total=60,
            )
        ]

    async def stub_topic_opportunities(**kwargs):
        calls.append(("topic_opportunities", kwargs))
        return [
            overview.OverviewTopicOpportunityRow(
                topic_id="topic-ai-video",
                topic_name="AI Video",
                own_rank=8,
            )
        ]

    async def stub_competitors(**kwargs):
        calls.append(("competitors", kwargs))
        return overview.OverviewCompetitorsOut(
            items=[
                overview.OverviewCompetitorRow(
                    rank=1,
                    brand_name="Competitor",
                    mention_count=420,
                ),
                overview.OverviewCompetitorRow(
                    rank=8,
                    brand_name="Dreamina",
                    mention_count=158,
                    is_own=True,
                ),
            ]
        )

    monkeypatch.setattr(overview, "database", FakeOverviewDatabase())
    monkeypatch.setattr(overview, "_query_overview_core_light", stub_core)
    monkeypatch.setattr(overview, "_query_overview_platform_health_light", stub_platform_health)
    monkeypatch.setattr(overview, "_query_topic_opportunities_light", stub_topic_opportunities)
    monkeypatch.setattr(overview, "get_overview_competitors", stub_competitors)

    result = asyncio.run(
        overview.get_overview(
            client_id=CLIENT_ID,
            date_from="2026-06-19",
            date_to="2026-06-19",
            interval="daily",
            topic_ids=None,
            platform=None,
            country=None,
        )
    )

    assert result.summary.visibility_score == 8.93
    assert result.summary.visibility_rank == 8
    assert result.summary.own_citation_share == 12.5
    assert result.summary.positive_sentiment_pct == 64.0
    assert result.summary.total_responses == 1770
    assert result.summary.analyzer_completed_at == "2026-06-19T19:30:00"
    assert result.momentum[-1].visibility_score == 8.93
    assert result.momentum[-1].own_citation_share == 12.5
    assert result.momentum[-1].positive_sentiment_pct == 64.0
    assert [row.platform for row in result.platform_health] == ["chatgpt"]
    assert result.platform_health[0].visibility_score == 9.5
    assert result.competitor_snapshot[1].brand_name == "Dreamina"
    assert result.topic_opportunities[0].topic_name == "AI Video"
    assert result.topic_opportunities[0].own_rank == 8

    core_call = next(kwargs for name, kwargs in calls if name == "core")
    assert core_call["include_ranks"] is True
    assert {name for name, _kwargs in calls} == {
        "core",
        "platform_health",
        "topic_opportunities",
        "competitors",
    }


def test_split_overview_kpis_and_trends_use_lightweight_core(monkeypatch):
    calls = []

    async def stub_core(**kwargs):
        calls.append(kwargs)
        return fake_overview_core()

    monkeypatch.setattr(overview, "_query_overview_core_light", stub_core)

    kpis = asyncio.run(
        overview.get_overview_kpis(
            client_id=CLIENT_ID,
            date_from="2026-06-19",
            date_to="2026-06-19",
            interval="daily",
            topic_ids=None,
            platform=None,
            country=None,
        )
    )
    trends = asyncio.run(
        overview.get_overview_trends(
            client_id=CLIENT_ID,
            date_from="2026-06-19",
            date_to="2026-06-19",
            interval="daily",
            topic_ids=None,
            platform=None,
            country=None,
        )
    )

    assert kpis.summary.visibility_score == 8.93
    assert kpis.summary.own_citation_share == 12.5
    assert kpis.summary.positive_sentiment_pct == 64.0
    assert trends.momentum[-1].visibility_score == 8.93
    assert trends.momentum[-1].own_citation_share == 12.5
    assert trends.momentum[-1].positive_sentiment_pct == 64.0
    assert calls[0]["include_ranks"] is True
    assert calls[0]["include_momentum"] is False
    assert "include_ranks" not in calls[1]
    assert "include_momentum" not in calls[1]


def test_overview_core_merges_lightweight_periods_and_visibility_rank(monkeypatch):
    async def stub_visibility_period(**kwargs):
        is_previous = "prev" in kwargs["date_param_prefix"]
        return {
            "total_responses": 1600 if is_previous else 1770,
            "own_responses": 120 if is_previous else 158,
            "total_mentions": 4000 if is_previous else 4366,
            "own_mentions": 120 if is_previous else 158,
            "avg_position": 2.7 if is_previous else 2.4,
            "visibility_score": 7.5 if is_previous else 8.93,
            "sov_pct": 3.0 if is_previous else 3.62,
            "series": [],
        }

    async def stub_citation_period(**kwargs):
        is_previous = "prev" in kwargs["date_param_prefix"]
        return {
            "total_citations": 280 if is_previous else 300,
            "own_citation_count": 31 if is_previous else 38,
            "own_citation_share": 11.0 if is_previous else 12.5,
            "series": [],
        }

    async def stub_sentiment_period(**kwargs):
        is_previous = "prev" in kwargs["date_param_prefix"]
        return {
            "sentiment_total": 120 if is_previous else 150,
            "positive_count": 72 if is_previous else 96,
            "negative_count": 20 if is_previous else 18,
            "positive_sentiment_pct": 60.0 if is_previous else 64.0,
            "series": [],
        }

    async def stub_visibility_rank(**kwargs):
        return 9 if "prev" in kwargs["date_param_prefix"] else 8

    monkeypatch.setattr(overview, "_query_overview_visibility_period", stub_visibility_period)
    monkeypatch.setattr(overview, "_query_overview_citation_period", stub_citation_period)
    monkeypatch.setattr(overview, "_query_overview_sentiment_period", stub_sentiment_period)
    monkeypatch.setattr(overview, "_query_overview_visibility_rank", stub_visibility_rank)

    result = asyncio.run(
        overview._query_overview_core_light(
            client_id=CLIENT_ID,
            date_from="2026-06-19",
            date_to="2026-06-19",
            interval="daily",
            topic_ids=None,
            platform=None,
            country=None,
            include_ranks=True,
            include_momentum=False,
        )
    )

    summary, momentum, filters = result
    assert summary.visibility_rank == 8
    assert summary.visibility_rank_change == -1
    assert summary.own_citation_rank is None
    assert summary.sov_pct == 3.62
    assert summary.own_mentions == 158
    assert summary.total_mentions == 4366
    assert summary.visibility_score_change == 1.43
    assert summary.own_citation_share_change == 1.5
    assert summary.positive_sentiment_pct_change == 4.0
    assert momentum == []
    assert filters.prev_date_from == "2026-06-18"


def test_competitor_snapshot_uses_lightweight_aggregate_rows(monkeypatch):
    class FakeCompetitorDatabase:
        async def fetch_all(self, sql, params=None):
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "WITH scoped AS" in sql:
                return [
                    {
                        "rank": 1,
                        "brand_name": "Competitor",
                        "response_count": 184,
                        "total_responses": 1000,
                        "mention_count": 420,
                        "total_mentions": 4366,
                        "avg_position": 2.1,
                        "is_own": 0,
                    },
                    {
                        "rank": 8,
                        "brand_name": "Dreamina",
                        "response_count": 89,
                        "total_responses": 1000,
                        "mention_count": 158,
                        "total_mentions": 4366,
                        "avg_position": 2.4,
                        "is_own": 1,
                    },
                ]
            return []

    monkeypatch.setattr(overview, "database", FakeCompetitorDatabase())

    rows = asyncio.run(
        overview._query_overview_competitors_light(
            client_id=CLIENT_ID,
            topic_ids=None,
            platform=None,
            country=None,
            date_from="2026-06-19",
            date_to="2026-06-19",
        )
    )

    assert rows[0].brand_name == "Competitor"
    assert rows[0].visibility_pct == 18.4
    assert rows[0].sov_pct == 9.62
    assert rows[0].avg_position == 2.1
    assert rows[1].brand_name == "Dreamina"
    assert rows[1].sov_pct == 3.62


def test_topic_opportunities_include_citation_coverage(monkeypatch):
    class FakeTopicDatabase:
        async def fetch_all(self, sql, params=None):
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "geo_client_domains" in sql:
                return [{"domain": "dreamina.capcut.com"}]
            if "citation_totals" in sql:
                return [
                    {
                        "topic_id": "topic-ai-video",
                        "topic_name": "AI Video",
                        "total_responses": 100,
                        "prompt_volume": 10,
                        "leading_brand": "Runway",
                        "leading_mentions": 80,
                        "own_rank": 4,
                        "own_mentions": 30,
                        "own_response_count": 12,
                        "total_mentions": 120,
                        "total_citations": 200,
                        "own_citations": 50,
                    }
                ]
            return []

    monkeypatch.setattr(overview, "database", FakeTopicDatabase())

    result = asyncio.run(
        overview.get_overview_topic_opportunities(
            client_id=CLIENT_ID,
            date_from="2026-06-19",
            date_to="2026-06-19",
            interval="daily",
            topic_ids=None,
            platform=None,
            country=None,
        )
    )

    assert result.items[0].visibility_pct == 12.0
    assert result.items[0].citation_coverage == 25.0
    assert result.items[0].mention_share_pct == 25.0
    assert result.items[0].opportunity_label == "improve"


def test_overview_insights_uses_llm_only_to_polish_structured_facts(monkeypatch):
    prompts = []

    async def stub_core(**kwargs):
        return fake_overview_core()

    async def stub_polish(facts, language):
        prompts.append((facts, language))
        return [
            overview.OverviewInsightItem(
                kind=fact.kind,
                severity=fact.severity,
                metric=fact.metric,
                value=fact.value,
                delta=fact.delta,
                title=f"Polished {fact.metric}",
                detail=f"Fact value {fact.value}",
            )
            for fact in facts
        ]

    monkeypatch.setattr(overview, "_query_overview_core_light", stub_core)
    monkeypatch.setattr(overview, "_polish_insight_facts_with_flash", stub_polish)

    result = asyncio.run(
        overview.get_overview_insights(
            client_id=CLIENT_ID,
            date_from="2026-06-19",
            date_to="2026-06-19",
            interval="daily",
            topic_ids=None,
            platform=None,
            country=None,
            language="zh-CN",
        )
    )

    assert prompts
    assert prompts[0][1] == "zh-CN"
    assert prompts[0][0][0].metric == "positive_sentiment_pct"
    assert result.items[0].title == "Polished positive_sentiment_pct"


def test_insight_polish_prompt_rejects_template_copy_and_metric_ids():
    facts = [
        overview.OverviewInsightFact(
            kind="visibility",
            severity="positive",
            metric="visibility_score",
            value=10.23,
            delta=0.32,
            title="可见度发生变化",
            detail="可见度 当前为 10.23，较上一周期变化 +0.32 个百分点。",
        )
    ]

    prompt = overview._insight_polish_prompt(facts, "zh-CN")

    assert "不要照抄" in prompt
    assert "不要输出 visibility_score" in prompt
    assert "不要使用“当前为" in prompt


def test_parse_polished_insights_accepts_json_code_fence():
    facts = [
        overview.OverviewInsightFact(
            kind="citation",
            severity="positive",
            metric="own_citation_share",
            value=2.91,
            delta=0.14,
            title="Citation moved",
            detail="Citation share moved.",
        )
    ]
    raw = '```json\n[{"title":"引用质量回升","detail":"自有域名引用占比小幅走高，品牌可信来源在恢复。"}]\n```'

    items = overview._parse_polished_insight_items(raw, facts)

    assert items[0].title == "引用质量回升"
    assert items[0].detail == "自有域名引用占比小幅走高，品牌可信来源在恢复。"


def test_polish_logs_response_summary_on_success(monkeypatch, caplog):
    class FakePart:
        text = json.dumps(
            [
                {
                    "title": "可见度继续抬升",
                    "detail": "品牌在最新周期的回答覆盖继续走高。",
                }
            ],
            ensure_ascii=False,
        )

    class FakeContent:
        parts = [FakePart()]

    class FakeCandidate:
        content = FakeContent()
        finish_reason = "STOP"
        safety_ratings = []

    class FakeResponse:
        text = ""
        candidates = [FakeCandidate()]
        prompt_feedback = None
        usage_metadata = "prompt_token_count: 1 candidates_token_count: 1 total_token_count: 2"

    class FakeModels:
        async def generate_content(self, **kwargs):
            return FakeResponse()

    class FakeAio:
        models = FakeModels()

    class FakeClient:
        aio = FakeAio()

    class FakeTypes:
        class HttpOptions:
            def __init__(self, **kwargs):
                pass

        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    async def fake_resolve_model_config():
        return "gemini-3-flash-preview", "global"

    fake_google = py_types.ModuleType("google")
    fake_genai = py_types.ModuleType("google.genai")
    fake_genai.Client = lambda **kwargs: FakeClient()
    fake_genai.types = FakeTypes
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setattr(overview, "_resolve_flash_model_config", fake_resolve_model_config)
    monkeypatch.setattr(overview, "_resolve_gcp_project", lambda: "project-test")
    caplog.set_level(logging.INFO, logger="routers.insights.overview")

    facts = [
        overview.OverviewInsightFact(
            kind="visibility",
            severity="positive",
            metric="visibility_score",
            value=10.23,
            delta=0.32,
        )
    ]

    result = asyncio.run(overview._polish_insight_facts_with_flash(facts, "zh-CN"))

    assert result[0].title == "可见度继续抬升"
    assert "overview_insight_flash_response" in caplog.text


def test_overview_status_reads_latest_and_next_analysis_time(monkeypatch):
    class FakeStatusDatabase:
        async def fetch_one(self, sql, params=None):
            if "MAX(gr.analyzed_at)" in sql:
                return {
                    "latest_analysis_time": datetime(2026, 6, 19, 0, 18, 1),
                    "cron_analyzer": "0 9 * * *",
                }
            return None

    monkeypatch.setattr(overview, "database", FakeStatusDatabase())

    result = asyncio.run(
        overview.get_overview_status(
            client_id=CLIENT_ID,
            date_from="2026-06-19",
            date_to="2026-06-19",
        )
    )

    assert result.latest_analysis_time == "2026-06-19T08:18:01"
    assert result.next_analysis_time is not None
