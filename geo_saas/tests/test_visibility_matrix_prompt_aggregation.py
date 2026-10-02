import asyncio
from uuid import UUID

from routers.insights import visibility
from routers.insights._helpers import build_sov_ranking


def test_visibility_matrix_groups_prompt_rows_by_visible_prompt_text():
    rows = [
        {
            "topic_id": "topic-1",
            "topic_name": "AI Video",
            "prompt_id": "prompt-us",
            "prompt_text": "What is the best AI video generator?",
            "product": None,
            "company_name": "Dreamina",
            "mention_count": 1,
            "is_own": 1,
        },
        {
            "topic_id": "topic-1",
            "topic_name": "AI Video",
            "prompt_id": "prompt-jp",
            "prompt_text": "What is the best AI video generator?",
            "product": None,
            "company_name": "Dreamina",
            "mention_count": 2,
            "is_own": 1,
        },
    ]

    ranking = build_sov_ranking(
        rows,
        group_key_fn=lambda row: row["topic_id"],
        group_name_fn=lambda row: row["topic_name"],
    )

    assert len(ranking) == 1
    assert len(ranking[0]["prompts"]) == 1
    assert ranking[0]["prompts"][0]["prompt_text"] == "What is the best AI video generator?"
    assert ranking[0]["prompts"][0]["brands"][0]["mention_count"] == 3


def test_visibility_matrix_uses_full_logical_prompt_identity_and_representative_uuid():
    base = {
        "topic_id": "topic-1", "topic_name": "AI Video", "product": "Editor",
        "company_name": "Dreamina", "mention_count": 1, "is_own": 1,
    }
    rows = [
        {**base, "prompt_id": "00000000-0000-0000-0000-000000000002", "prompt_text": "Best   editor?", "intent": "Discovery", "language": "en-US"},
        {**base, "prompt_id": "00000000-0000-0000-0000-000000000001", "prompt_text": " best editor? ", "intent": "discovery", "language": "EN-us"},
        {**base, "prompt_id": "00000000-0000-0000-0000-000000000003", "prompt_text": "Best editor?", "intent": "Evaluation", "language": "en-US"},
        {**base, "topic_id": "topic-2", "topic_name": "Editors", "prompt_id": "00000000-0000-0000-0000-000000000004", "prompt_text": "Best editor?", "intent": "Discovery", "language": "de-DE"},
    ]
    ranking = build_sov_ranking(
        rows,
        group_key_fn=lambda row: row["product"],
        group_name_fn=lambda row: row["product"],
    )

    assert len(ranking[0]["prompts"]) == 3
    merged = next(prompt for prompt in ranking[0]["prompts"] if prompt["total_mentions"] == 2)
    assert merged["prompt_id"] == "00000000-0000-0000-0000-000000000001"
    assert merged["brands"][0]["mention_count"] == 2


def test_visibility_matrix_never_truncates_group_or_prompt_brand_universe():
    rows = [
        {
            "topic_id": "topic-1",
            "topic_name": "AI Video",
            "prompt_id": f"prompt-{index}",
            "prompt_text": "What is the best AI video generator?",
            "product": "Editor",
            "company_name": f"Brand {index:02d}",
            "mention_count": 20 - index,
            "is_own": index == 0,
        }
        for index in range(12)
    ]

    ranking = build_sov_ranking(
        rows,
        group_key_fn=lambda row: row["topic_id"],
        group_name_fn=lambda row: row["topic_name"],
    )

    assert len(ranking[0]["brands"]) == 12
    assert len(ranking[0]["prompts"][0]["brands"]) == 12
    assert len(visibility._rank_brands_from_counts({
        f"Brand {index:02d}": {"mention_count": 20 - index, "is_own": index == 0}
        for index in range(12)
    })) == 12


def test_matrix_default_preserves_builder_order_and_scoped_sort_is_explicit():
    groups = [
        {
            "group_key": "group-b", "group_name": "B", "total_mentions": 1, "prompt_count": 2,
            "brands": [
                {"rank": 1, "company_name": "Zulu", "mention_count": 9, "is_own": False},
                {"rank": 2, "company_name": "Alpha", "mention_count": 1, "is_own": True},
            ],
            "prompts": [
                {"prompt_id": "small", "prompt_text": "Small", "total_mentions": 1, "brands": []},
                {"prompt_id": "large", "prompt_text": "Large", "total_mentions": 10, "brands": []},
            ],
        },
        {"group_key": "group-a", "group_name": "A", "total_mentions": 10, "prompt_count": 1, "brands": [], "prompts": []},
    ]

    unchanged = visibility._sort_visibility_matrix(groups)
    assert [group["group_key"] for group in unchanged] == ["group-b", "group-a"]
    assert [prompt["prompt_id"] for prompt in unchanged[0]["prompts"]] == ["small", "large"]
    assert [brand["company_name"] for brand in unchanged[0]["brands"]] == ["Zulu", "Alpha"]

    sorted_groups = visibility._sort_visibility_matrix(
        groups,
        group_sort_by="total_mentions", group_sort_order="desc",
        prompt_sort_by="total_mentions", prompt_sort_order="desc",
        brand_sort_by="mention_count", brand_sort_order="asc",
    )
    assert [group["group_key"] for group in sorted_groups] == ["group-a", "group-b"]
    group_b = next(group for group in sorted_groups if group["group_key"] == "group-b")
    assert [prompt["prompt_id"] for prompt in group_b["prompts"]] == ["large", "small"]
    assert [brand["company_name"] for brand in group_b["brands"]] == ["Alpha", "Zulu"]


class FakeVisibilityDatabase:
    def __init__(self):
        self.fetch_all_calls = []
        self.fetch_val_calls = []

    async def fetch_all(self, sql, params=None):
        self.fetch_all_calls.append((sql, params or {}))
        if "FROM geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        if "WITH prompt_page" in sql:
            return [
                {
                    "prompt_key": "logical-z",
                    "prompt_id": "33333333-3333-3333-3333-333333333333",
                    "prompt_text": "Zulu Prompt",
                    "page_ordinal": 1,
                    "total_mentions": 9,
                    "brand_name": "Dreamina",
                    "mention_count": 9,
                    "is_own": 1,
                },
                {
                    "prompt_key": "logical-a",
                    "prompt_id": "11111111-1111-1111-1111-111111111111",
                    "prompt_text": "Alpha Prompt",
                    "page_ordinal": 2,
                    "total_mentions": 2,
                    "brand_name": "Dreamina",
                    "mention_count": 2,
                    "is_own": 1,
                },
            ]
        return []

    async def fetch_val(self, sql, params=None):
        self.fetch_val_calls.append((sql, params or {}))
        return 2


def test_visibility_ranking_prompts_aggregates_by_prompt_text_and_scopes_client(monkeypatch):
    fake_db = FakeVisibilityDatabase()
    monkeypatch.setattr(visibility, "database", fake_db)
    client_id = UUID("11111111-1111-1111-1111-111111111111")

    result = asyncio.run(
        visibility.get_visibility_ranking_prompts(
            client_id=client_id,
            group_by="topic",
            group_key="22222222-2222-2222-2222-222222222222",
            date_from="2026-06-04",
            date_to="2026-06-10",
            sort_by="total_mentions",
            sort_order="asc",
        )
    )

    assert result.total == 2
    assert [item.prompt_text for item in result.items] == ["Zulu Prompt", "Alpha Prompt"]
    assert [item.prompt_id for item in result.items] == [
        "33333333-3333-3333-3333-333333333333",
        "11111111-1111-1111-1111-111111111111",
    ]
    combined_sql = "\n".join(sql for sql, _ in fake_db.fetch_all_calls + fake_db.fetch_val_calls)
    assert "LOWER(REGEXP_REPLACE(BTRIM(COALESCE(cp.text, ''))" in combined_sql
    assert "bm.client_id = :client_id" in combined_sql
    assert "cp.client_id = bm.client_id" in combined_sql
    assert "cp.is_active = TRUE" in combined_sql
    prompt_page_sql = next(sql for sql, _ in fake_db.fetch_all_calls if "WITH prompt_page" in sql)
    assert "ORDER BY COUNT(*) ASC NULLS LAST, LOWER(MIN(cp.text)) ASC, MIN(cp.id::text) ASC" in prompt_page_sql
    assert prompt_page_sql.index("ORDER BY") < prompt_page_sql.index("OFFSET :offset")
    assert "page_ordinal" in prompt_page_sql
    assert "ORDER BY pp.page_ordinal" in prompt_page_sql
    assert "REGEXP_REPLACE" in prompt_page_sql
    assert "cp.intent" in prompt_page_sql and "cp.language" in prompt_page_sql
