import pytest

from routers import content_preselect
from pipelines.content_pipeline import _dedupe_target_prompt_rows


class FakePool:
    def __init__(self, rows):
        self.rows = rows
        self.last_query = ""
        self.last_args = ()

    async def fetch(self, query, *args):
        self.last_query = query
        self.last_args = args
        return self.rows


@pytest.mark.asyncio
async def test_ranked_prompts_page_returns_paginated_detail_rows(monkeypatch):
    pool = FakePool(
        [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "ids": ["11111111-1111-1111-1111-111111111111"],
                "prompt_text": "best AI design tool",
                "platform": "perplexity",
                "platforms": ["perplexity"],
                "country": "US",
                "countries": ["US"],
                "intent": "Solution Discovery",
                "topic_name": "AI Design",
                "mention_count": 0,
                "avg_position": 0,
                "citation_count": 2,
                "negative_count": 1,
                "total_count": 42,
            }
        ]
    )

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(content_preselect, "get_pool", fake_get_pool)

    result = await content_preselect.get_ranked_prompts_page(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        sort_by="visibility",
        page=2,
        page_size=10,
        search="design",
        view_mode="detail",
    )

    assert result.page == 2
    assert result.page_size == 10
    assert result.total == 42
    assert result.view_mode == "detail"
    assert result.items[0].prompt_text == "best AI design tool"
    assert result.items[0].country == "US"
    assert result.items[0].countries == ["US"]
    assert result.items[0].ids == ["11111111-1111-1111-1111-111111111111"]
    assert "p.text ILIKE" in pool.last_query
    assert pool.last_args[-2:] == (10, 10)


@pytest.mark.asyncio
async def test_ranked_prompts_page_supports_aggregate_rows(monkeypatch):
    pool = FakePool(
        [
            {
                "id": "agg:ai-design",
                "ids": [
                    "11111111-1111-1111-1111-111111111111",
                    "22222222-2222-2222-2222-222222222222",
                ],
                "prompt_text": "best AI design tool",
                "platform": None,
                "platforms": ["chatgpt", "perplexity"],
                "country": None,
                "countries": ["JP", "US"],
                "intent": "Solution Discovery",
                "topic_name": "AI Design",
                "mention_count": 3,
                "avg_position": 2.5,
                "citation_count": 9,
                "negative_count": 0,
                "total_count": 1,
            }
        ]
    )

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(content_preselect, "get_pool", fake_get_pool)

    result = await content_preselect.get_ranked_prompts_page(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        sort_by="citation",
        page=1,
        page_size=20,
        view_mode="aggregate",
    )

    assert result.view_mode == "aggregate"
    assert result.total == 1
    assert result.items[0].platform is None
    assert result.items[0].country is None
    assert result.items[0].ids == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    assert "GROUP BY prompt_text, topic_id, topic_name, intent" in pool.last_query


def test_target_prompt_rows_are_deduped_by_client_prompt_concept():
    rows = [
        {
            "text": "best AI design tool",
            "platform": "perplexity",
            "country": "US",
            "intent": "Solution Discovery",
            "product": None,
            "topic_id": "topic-1",
            "topic_name": "AI Design",
        },
        {
            "text": "best AI design tool",
            "platform": "chatgpt",
            "country": "JP",
            "intent": "Solution Discovery",
            "product": None,
            "topic_id": "topic-1",
            "topic_name": "AI Design",
        },
    ]

    result = _dedupe_target_prompt_rows(rows)

    assert len(result) == 1
    assert result[0]["text"] == "best AI design tool"
    assert result[0]["platforms"] == ["chatgpt", "perplexity"]
    assert result[0]["countries"] == ["JP", "US"]
    assert result[0]["platform"] == "chatgpt, perplexity"
    assert result[0]["country"] == "JP, US"
