"""Tests for customer-scoped sentiment extraction inputs and prompts."""
import asyncio
import json
from datetime import datetime
from uuid import uuid4

from src.parsers import sentiment_parser
from src.parsers.sentiment_parser import _build_extraction_prompt
from src.pipeline.phase0_load_config import ClientConfig
from src.pipeline.phase1_per_result_parse import parse_batch


class _NoopTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False


class _TransactionalFakeConn:
    def transaction(self):
        return _NoopTransaction()


def _result(text: str, *, platform: str = "Gemini"):
    return {
        "result_id": 101,
        "text": text,
        "sources": [],
        "citation_pills": [],
        "client_id": uuid4(),
        "client_prompt_id": uuid4(),
        "task_id": uuid4(),
        "ingested_at": datetime(2026, 1, 1),
        "platform": platform,
    }


def _config():
    return ClientConfig(
        brands=[
            {"brand_name": "Jimeng", "aliases": ["吉梦"], "is_shadow": False},
            {"brand_name": "Dreamina", "aliases": ["CapCut"], "is_shadow": False},
        ],
        peers=[
            {"primary_name": "Midjourney", "aliases": []},
        ],
        tracked_products=[],
        domains=[],
        tracked_urls=[],
        owned_domain_strs=[],
    )


def _config_with_product(*, owner_brand_id):
    brand_id = uuid4()
    return ClientConfig(
        brands=[
            {
                "id": brand_id,
                "brand_name": "Jimeng",
                "aliases": ["吉梦"],
                "is_shadow": False,
            },
        ],
        peers=[],
        tracked_products=[
            {
                "id": uuid4(),
                "product_name": "Studio Pro",
                "match_variants": ["Studio Pro"],
                "product_role": "own",
                "shadow_sub_role": None,
                "owner_brand_id": brand_id if owner_brand_id == "configured" else owner_brand_id,
                "owner_brand_name": "Jimeng" if owner_brand_id else None,
                "owner_peer_id": None,
                "owner_peer_name": None,
            },
        ],
        domains=[],
        tracked_urls=[],
        owned_domain_strs=[],
    )


def test_sentiment_input_skips_peer_only_competitive_response():
    text = (
        "Midjourney is powerful for image generation, but it has a steep learning curve "
        "and limited direct editing controls. For teams comparing AI image tools, those "
        "limitations can matter a lot when production speed is important."
    )

    parsed = parse_batch([_result(text)], _config())

    assert parsed.sentiment_inputs == []


def test_sentiment_input_includes_target_entities_when_own_brand_is_mentioned():
    text = (
        "Jimeng is easier for Chinese marketing teams to use than Midjourney, and its "
        "template-driven workflow can reduce production effort. Midjourney still has "
        "stronger artistic range, but Jimeng is more practical for campaign iteration."
    )

    parsed = parse_batch([_result(text)], _config())

    assert len(parsed.sentiment_inputs) == 1
    target_entities = parsed.sentiment_inputs[0][6]
    assert target_entities == {"brands": ["Jimeng (aliases: 吉梦)"], "products": []}


def test_sentiment_input_includes_aliases_when_brand_alias_is_mentioned():
    text = (
        "CapCut is useful for short-form video workflows because it has accessible "
        "templates and fast editing controls for campaign teams. Compared with many "
        "editing suites, CapCut is easier to adopt for social content production."
    )

    parsed = parse_batch([_result(text)], _config())

    assert len(parsed.sentiment_inputs) == 1
    target_entities = parsed.sentiment_inputs[0][6]
    assert target_entities == {"brands": ["Dreamina (aliases: CapCut)"], "products": []}


def test_sentiment_input_skips_product_without_verified_brand_owner():
    text = (
        "Studio Pro offers several workflow templates and editing controls for "
        "campaign teams, with enough detail here to qualify for sentiment parsing."
    )

    parsed = parse_batch([_result(text)], _config_with_product(owner_brand_id=None))

    assert parsed.sentiment_inputs == []


def test_sentiment_input_accepts_product_owned_by_configured_workspace_brand():
    text = (
        "Studio Pro offers several workflow templates and editing controls for "
        "campaign teams, with enough detail here to qualify for sentiment parsing."
    )

    parsed = parse_batch([_result(text)], _config_with_product(owner_brand_id="configured"))

    assert len(parsed.sentiment_inputs) == 1
    assert parsed.sentiment_inputs[0][6]["products"] == ["Studio Pro"]


def test_sentiment_input_rejects_own_product_bound_to_shadow_brand():
    config = _config_with_product(owner_brand_id="configured")
    config.brands[0]["is_shadow"] = True
    text = (
        "Studio Pro offers several workflow templates and editing controls for "
        "campaign teams, with enough detail here to qualify for sentiment parsing."
    )

    parsed = parse_batch([_result(text)], config)

    assert parsed.sentiment_inputs == []


def test_sentiment_input_rejects_shadow_product_bound_to_own_brand():
    config = _config_with_product(owner_brand_id="configured")
    config.tracked_products[0]["product_role"] = "shadow_brand_product"
    text = (
        "Studio Pro offers several workflow templates and editing controls for "
        "campaign teams, with enough detail here to qualify for sentiment parsing."
    )

    parsed = parse_batch([_result(text)], config)

    assert parsed.sentiment_inputs == []


def test_sentiment_input_ignores_brand_name_used_only_as_citation_marker():
    text = (
        "The category has many capable tools, and this response discusses general workflow "
        "considerations without evaluating the customer brand at all. Dreamina+1"
    )

    parsed = parse_batch([_result(text, platform="ChatGPT")], _config())

    assert parsed.sentiment_inputs == []


def test_parse_batch_appends_pill_only_citations_for_chatgpt_only():
    chatgpt_result = _result("", platform="ChatGPT")
    chatgpt_result["citation_pills"] = [{"url": "https://pill.example.com/chatgpt"}]
    gemini_result = _result("", platform="Gemini")
    gemini_result["result_id"] = 102
    gemini_result["citation_pills"] = [{"url": "https://pill.example.com/gemini"}]

    parsed = parse_batch([chatgpt_result, gemini_result], _config())

    assert [row["source_url"] for row in parsed.per_result[0][3]] == [
        "https://pill.example.com/chatgpt"
    ]
    assert parsed.per_result[1][3] == []


def test_extraction_prompt_scopes_themes_to_target_entities_and_excludes_competitors():
    prompt = _build_extraction_prompt([
        {
            "result_id": 101,
            "text": "Jimeng is easier to use. Midjourney has limited editing controls.",
            "target_entities": {"brands": ["Jimeng (aliases: 吉梦)"], "products": []},
        }
    ])

    assert "Target customer entities for this result:" in prompt
    assert "Jimeng (aliases: 吉梦)" in prompt
    assert "Do NOT extract competitor pros/cons" in prompt
    assert "Only extract sentiment and themes about the target customer entities" in prompt


def test_extraction_prompt_classifies_conditional_competitor_advantage_as_mixed():
    prompt = _build_extraction_prompt([
        {
            "result_id": 102,
            "text": "Runway is generally the stronger choice over Dreamina for visual consistency.",
            "target_entities": {"brands": ["Dreamina"], "products": []},
        }
    ])

    assert "Mixed/Neutral" in prompt
    assert "competitor has a slight edge" in prompt
    assert "target remains a reasonable choice" in prompt


def test_extraction_prompt_requires_direct_negative_evidence_for_final_recommendation():
    prompt = _build_extraction_prompt([
        {
            "result_id": 104,
            "text": "Dreamina creates visual ingredients, but if you only pick one right now: Go with Canva AI.",
            "target_entities": {"brands": ["Dreamina"], "products": []},
        }
    ])

    assert "Final Recommendation Priority" in prompt
    assert "Go with X" in prompt
    assert "direct negative evidence" in prompt
    assert "Insufficient Evidence" in prompt


def test_extraction_prompt_handles_specific_inquiry_core_fit_and_caveats():
    prompt = _build_extraction_prompt([
        {
            "result_id": 103,
            "text": "Dreamina is reliable enough for drafts but needs manual oversight for final ads.",
            "target_entities": {"brands": ["Dreamina"], "products": []},
        }
    ])

    assert "For specific inquiry responses" in prompt
    assert "judge the overall sentiment by fit for the user's core requirement" in prompt
    assert "lower confidence" in prompt
    assert "extract negative themes for material caveats" in prompt


def test_extraction_prompt_uses_four_overall_states_and_three_theme_states():
    prompt = _build_extraction_prompt([
        {
            "result_id": 105,
            "text": "Jimeng is useful in some workflows but has meaningful limitations in others.",
            "target_entities": {"brands": ["Jimeng"], "products": []},
        }
    ])

    assert '"Positive" | "Mixed/Neutral" | "Negative" | "Insufficient Evidence"' in prompt
    assert 'theme sentiment: "Positive", "Mixed/Neutral", or "Negative"' in prompt
    assert "Insufficient Evidence must return an empty themes list" in prompt
    assert '"reason_code"' in prompt
    assert '"evidence"' in prompt


def test_sentiment_context_keeps_target_evidence_and_final_conclusion_beyond_prefix():
    text = (
        ("Background category commentary. " * 150)
        + "Dreamina is still a practical choice for fast campaign iteration. "
        + ("Additional comparison detail. " * 80)
        + "Final verdict: choose Dreamina when editing speed is the core requirement."
    )

    context = sentiment_parser._select_sentiment_context(
        text,
        {"brands": ["Dreamina"], "products": []},
    )

    assert "Dreamina is still a practical choice" in context
    assert "Final verdict: choose Dreamina" in context
    assert len(context) <= sentiment_parser.SENTIMENT_CONTEXT_MAX_CHARS


def test_sentiment_context_removes_target_citation_markers_without_removing_real_mentions():
    text = (
        "Dreamina+1 provides the cited source label. Later, Dreamina is described as "
        "useful for campaign iteration and rapid editing workflows."
    )

    context = sentiment_parser._select_sentiment_context(
        text,
        {"brands": ["Dreamina"], "products": []},
    )

    assert "Dreamina+1" not in context
    assert "Dreamina is described as useful" in context


def test_gemini_extraction_failure_returns_no_sentiment_results():
    def fail_client(_model_id=None):
        raise RuntimeError("Gemini unavailable")

    original = sentiment_parser._get_gemini_client_and_model
    sentiment_parser._get_gemini_client_and_model = fail_client

    try:
        results = asyncio.run(sentiment_parser._gemini_extract_sentiment([
            (
                101,
                "Jimeng is useful for campaign teams because it has accessible templates.",
                "client-id",
                "prompt-id",
                "task-id",
                "2026-01-01",
                {"brands": ["Jimeng"], "products": []},
            )
        ]))
    finally:
        sentiment_parser._get_gemini_client_and_model = original

    assert results == {}


def test_gemini_extraction_empty_response_text_returns_no_sentiment_results(caplog):
    class FakeResponse:
        text = None

    class FakeModels:
        async def generate_content(self, **_kwargs):
            return FakeResponse()

    class FakeAio:
        models = FakeModels()

    class FakeClient:
        aio = FakeAio()

    def fake_client(_model_id=None):
        return FakeClient(), "fake-model"

    original = sentiment_parser._get_gemini_client_and_model
    sentiment_parser._get_gemini_client_and_model = fake_client

    try:
        with caplog.at_level("ERROR"):
            results = asyncio.run(sentiment_parser._gemini_extract_sentiment([
                (
                    101,
                    "Jimeng is useful for campaign teams because it has accessible templates.",
                    "client-id",
                    "prompt-id",
                    "task-id",
                    "2026-01-01",
                    {"brands": ["Jimeng"], "products": []},
                )
            ]))
    finally:
        sentiment_parser._get_gemini_client_and_model = original

    assert results == {}
    assert "NoneType" not in caplog.text
    assert "empty response text" in caplog.text


def test_v2_normalization_keeps_mixed_theme_and_records_traceability():
    text = "Dreamina is practical for drafts, but final ad quality still needs manual review."
    result = sentiment_parser._normalize_extraction_item(
        {
            "result_id": 101,
            "sentiment": "Mixed/Neutral",
            "confidence": 0.73,
            "reason_code": "MIXED_TRADEOFF",
            "evidence": ["Dreamina is practical for drafts"],
            "themes": [
                {
                    "theme": "Manual Review Required",
                    "sentiment": "Mixed/Neutral",
                    "excerpt": "final ad quality still needs manual review",
                }
            ],
        },
        model_id="gemini-test-model",
        context_text=text,
    )

    assert result is not None
    assert result["sentiment"] == "Mixed/Neutral"
    assert result["themes"][0]["sentiment"] == "Mixed/Neutral"
    assert result["classifier_version"] == "sentiment-v2"
    assert result["model_id"] == "gemini-test-model"
    assert result["reason_code"] == "MIXED_TRADEOFF"
    assert result["evidence"] == ["Dreamina is practical for drafts"]


def test_v2_normalization_downgrades_unsupported_label_to_insufficient_evidence():
    result = sentiment_parser._normalize_extraction_item(
        {
            "result_id": 101,
            "sentiment": "Negative",
            "confidence": 0.9,
            "reason_code": "NEGATIVE_CORE_FIT",
            "evidence": ["This sentence does not exist in the response"],
            "themes": [
                {
                    "theme": "Weak Output",
                    "sentiment": "Negative",
                    "excerpt": "also absent",
                }
            ],
        },
        model_id="gemini-test-model",
        context_text="Dreamina is mentioned without a substantive evaluation.",
    )

    assert result is not None
    assert result["sentiment"] == "Insufficient Evidence"
    assert result["reason_code"] == "NO_SUBSTANTIVE_EVIDENCE"
    assert result["evidence"] == []
    assert result["themes"] == []


def test_v2_negative_rejects_competitor_only_evidence_even_when_verbatim():
    context = (
        "Dreamina appears in the comparison. "
        "Midjourney is difficult to learn and is not recommended for beginners."
    )
    result = sentiment_parser._normalize_extraction_item(
        {
            "result_id": 101,
            "sentiment": "Negative",
            "confidence": 0.92,
            "reason_code": "NEGATIVE_CORE_FIT",
            "evidence": ["Midjourney is difficult to learn and is not recommended for beginners."],
            "themes": [],
        },
        model_id="gemini-test-model",
        context_text=context,
        target_entities={"brands": ["Dreamina"], "products": []},
    )

    assert result is not None
    assert result["sentiment"] == "Insufficient Evidence"
    assert result["reason_code"] == "NO_SUBSTANTIVE_EVIDENCE"
    assert result["evidence"] == []


def test_v2_negative_rejects_competitor_only_evidence_after_chinese_sentence_boundary():
    context = "Dreamina 只是被列入比较。Midjourney 学习成本高，不适合新手。"
    result = sentiment_parser._normalize_extraction_item(
        {
            "result_id": 101,
            "sentiment": "Negative",
            "confidence": 0.92,
            "reason_code": "NEGATIVE_CORE_FIT",
            "evidence": ["Midjourney 学习成本高，不适合新手。"],
            "themes": [],
        },
        model_id="gemini-test-model",
        context_text=context,
        target_entities={"brands": ["Dreamina"], "products": []},
    )

    assert result is not None
    assert result["sentiment"] == "Insufficient Evidence"


def test_v2_negative_accepts_chinese_target_without_ascii_word_boundaries():
    context = "即梦在最终成片质量上不够可靠。"
    result = sentiment_parser._normalize_extraction_item(
        {
            "result_id": 101,
            "sentiment": "Negative",
            "confidence": 0.88,
            "reason_code": "NEGATIVE_CORE_FIT",
            "evidence": ["最终成片质量上不够可靠"],
            "themes": [],
        },
        model_id="gemini-test-model",
        context_text=context,
        target_entities={"brands": ["即梦"], "products": []},
    )

    assert result is not None
    assert result["sentiment"] == "Negative"


def test_v2_negative_accepts_target_evidence_in_same_comparison_sentence():
    context = "Dreamina is less reliable than Midjourney for final production assets."
    result = sentiment_parser._normalize_extraction_item(
        {
            "result_id": 101,
            "sentiment": "Negative",
            "confidence": 0.88,
            "reason_code": "NEGATIVE_CORE_FIT",
            "evidence": ["less reliable than Midjourney for final production assets"],
            "themes": [],
        },
        model_id="gemini-test-model",
        context_text=context,
        target_entities={"brands": ["Dreamina"], "products": []},
    )

    assert result is not None
    assert result["sentiment"] == "Negative"


def test_v2_themes_reject_competitor_only_evidence_for_mixed_response():
    context = (
        "Dreamina is a practical option for quick drafts. "
        "Midjourney is difficult to learn and expensive for small teams."
    )
    result = sentiment_parser._normalize_extraction_item(
        {
            "result_id": 101,
            "sentiment": "Mixed/Neutral",
            "confidence": 0.75,
            "reason_code": "MIXED_TRADEOFF",
            "evidence": ["Dreamina is a practical option for quick drafts."],
            "themes": [
                {
                    "theme": "Learning Curve",
                    "sentiment": "Negative",
                    "excerpt": "Midjourney is difficult to learn",
                }
            ],
        },
        model_id="gemini-test-model",
        context_text=context,
        target_entities={"brands": ["Dreamina"], "products": []},
    )

    assert result is not None
    assert result["sentiment"] == "Mixed/Neutral"
    assert result["themes"] == []


def test_v2_themes_accept_target_scoped_excerpt_in_same_sentence():
    context = "Dreamina is practical for drafts but needs manual review for final ads."
    result = sentiment_parser._normalize_extraction_item(
        {
            "result_id": 101,
            "sentiment": "Mixed/Neutral",
            "confidence": 0.75,
            "reason_code": "MIXED_TRADEOFF",
            "evidence": ["Dreamina is practical for drafts"],
            "themes": [
                {
                    "theme": "Manual Review",
                    "sentiment": "Negative",
                    "excerpt": "needs manual review for final ads",
                }
            ],
        },
        model_id="gemini-test-model",
        context_text=context,
        target_entities={"brands": ["Dreamina"], "products": []},
    )

    assert result is not None
    assert result["themes"] == [
        {
            "theme": "Manual Review",
            "sentiment": "Negative",
            "excerpt": "needs manual review for final ads",
        }
    ]


def test_write_sentiment_results_persists_v2_metadata_and_json_evidence():
    async def fake_prompt_exists(_conn, _client_id, _client_prompt_id):
        return True

    class FakeConn(_TransactionalFakeConn):
        def __init__(self):
            self.executed = []

        async def fetchval(self, sql, *args):
            self.executed.append((sql, args))
            return "sentiment-result-id"

        async def execute(self, sql, *args):
            self.executed.append((sql, args))

    conn = FakeConn()
    original_prompt_exists = sentiment_parser._prompt_exists_for_client
    sentiment_parser._prompt_exists_for_client = fake_prompt_exists
    try:
        written = asyncio.run(sentiment_parser.write_sentiment_results(
            conn,
            [(101, "text", "client-id", "prompt-id", "task-id", "2026-08-02")],
            {
                101: {
                    "sentiment": "Mixed/Neutral",
                    "confidence": 0.7,
                    "classifier_version": "sentiment-v2",
                    "model_id": "gemini-test-model",
                    "reason_code": "MIXED_TRADEOFF",
                    "evidence": ["verbatim evidence"],
                    "themes": [],
                }
            },
        ))
    finally:
        sentiment_parser._prompt_exists_for_client = original_prompt_exists

    assert written == 1
    sql, args = conn.executed[0]
    assert "classifier_version, model_id" in sql
    assert args[7:10] == ("sentiment-v2", "gemini-test-model", "MIXED_TRADEOFF")
    # The Analyzer pool registers a JSONB codec. Passing an already serialized
    # string would make PostgreSQL store a JSON string instead of an array.
    assert args[10] == ["verbatim evidence"]


def test_write_sentiment_results_wraps_each_result_in_a_savepoint():
    async def fake_prompt_exists(_conn, _client_id, _client_prompt_id):
        return True

    class FakeTransaction:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            self.conn.savepoints_entered += 1

        async def __aexit__(self, exc_type, _exc, _tb):
            if exc_type is not None:
                self.conn.rollbacks += 1
            return False

    class FakeConn(_TransactionalFakeConn):
        def __init__(self):
            self.insert_attempts = 0
            self.savepoints_entered = 0
            self.rollbacks = 0

        def transaction(self):
            return FakeTransaction(self)

        async def fetchval(self, sql, *_args):
            if "INSERT INTO geo_sentiment_results" not in sql:
                return 1
            self.insert_attempts += 1
            if self.insert_attempts == 1:
                raise RuntimeError("first row rejected")
            return "sentiment-result-id"

        async def execute(self, _sql, *_args):
            return None

    conn = FakeConn()
    original_prompt_exists = sentiment_parser._prompt_exists_for_client
    sentiment_parser._prompt_exists_for_client = fake_prompt_exists
    try:
        written = asyncio.run(sentiment_parser.write_sentiment_results(
            conn,
            [
                (101, "text", "client-id", "prompt-id", "task-id", "2026-08-02"),
                (102, "text", "client-id", "prompt-id", "task-id", "2026-08-02"),
            ],
            {
                101: {"sentiment": "Positive", "themes": []},
                102: {"sentiment": "Positive", "themes": []},
            },
        ))
    finally:
        sentiment_parser._prompt_exists_for_client = original_prompt_exists

    assert written == 1
    assert conn.savepoints_entered == 2
    assert conn.rollbacks == 1


def test_write_sentiment_results_does_not_count_or_duplicate_themes_on_conflict():
    async def fake_prompt_exists(_conn, _client_id, _client_prompt_id):
        return True

    class FakeConn(_TransactionalFakeConn):
        def __init__(self):
            self.executed = []

        async def fetchval(self, sql, *args):
            self.executed.append((sql, args))
            return None

        async def execute(self, sql, *args):
            self.executed.append((sql, args))

    conn = FakeConn()
    original_prompt_exists = sentiment_parser._prompt_exists_for_client
    sentiment_parser._prompt_exists_for_client = fake_prompt_exists
    try:
        written = asyncio.run(sentiment_parser.write_sentiment_results(
            conn,
            [(101, "text", "client-id", "prompt-id", "task-id", "2026-08-02")],
            {
                101: {
                    "sentiment": "Negative",
                    "confidence": 0.7,
                    "classifier_version": "sentiment-v2",
                    "model_id": "gemini-test-model",
                    "reason_code": "NEGATIVE_CORE_FIT",
                    "evidence": ["verbatim evidence"],
                    "themes": [{
                        "theme": "Core Fit",
                        "sentiment": "Negative",
                        "excerpt": "verbatim evidence",
                    }],
                }
            },
        ))
    finally:
        sentiment_parser._prompt_exists_for_client = original_prompt_exists

    assert written == 0
    assert len(conn.executed) == 1
    assert "INSERT INTO geo_sentiment_results" in conn.executed[0][0]


def test_write_sentiment_results_does_not_write_orphan_themes_after_result_error():
    async def fake_prompt_exists(_conn, _client_id, _client_prompt_id):
        return True

    class FakeConn(_TransactionalFakeConn):
        def __init__(self):
            self.theme_writes = []

        async def fetchval(self, _sql, *_args):
            raise RuntimeError("result insert failed")

        async def execute(self, sql, *args):
            self.theme_writes.append((sql, args))

    conn = FakeConn()
    original_prompt_exists = sentiment_parser._prompt_exists_for_client
    sentiment_parser._prompt_exists_for_client = fake_prompt_exists
    try:
        written = asyncio.run(sentiment_parser.write_sentiment_results(
            conn,
            [(101, "text", "client-id", "prompt-id", "task-id", "2026-08-02")],
            {
                101: {
                    "sentiment": "Negative",
                    "confidence": 0.8,
                    "classifier_version": "sentiment-v2",
                    "model_id": "gemini-test-model",
                    "reason_code": "NEGATIVE_CORE_FIT",
                    "evidence": ["negative evidence"],
                    "themes": [
                        {
                            "theme": "Output Quality",
                            "sentiment": "Negative",
                            "excerpt": "negative evidence",
                        }
                    ],
                }
            },
        ))
    finally:
        sentiment_parser._prompt_exists_for_client = original_prompt_exists

    assert written == 0
    assert conn.theme_writes == []


def test_parse_sentiment_batch_splits_failed_batch_to_single_item_retries():
    call_sizes = []

    async def fake_extract(batch, model_id=None):
        call_sizes.append(len(batch))
        if len(batch) > 1:
            return {}
        row_id = batch[0][0]
        return {
            row_id: {
                "sentiment": "Positive",
                "confidence": 0.8,
                "themes": [],
            }
        }

    async def fake_prompt_exists(_conn, _client_id, _client_prompt_id):
        return True

    class FakeConn(_TransactionalFakeConn):
        def __init__(self):
            self.executed = []

        async def fetchval(self, sql, *args):
            self.executed.append((sql, args))
            return "sentiment-result-id"

        async def execute(self, sql, *args):
            self.executed.append((sql, args))

    conn = FakeConn()
    batch = [
        (
            101,
            "Jimeng is useful for campaign teams because it has accessible templates.",
            "client-id",
            "prompt-id",
            "task-id",
            "2026-01-01",
            {"brands": ["Jimeng"], "products": []},
        ),
        (
            102,
            "Dreamina is helpful for editing workflows and quick iteration.",
            "client-id",
            "prompt-id",
            "task-id",
            "2026-01-01",
            {"brands": ["Dreamina"], "products": []},
        ),
    ]

    original_extract = sentiment_parser._gemini_extract_sentiment
    original_prompt_exists = sentiment_parser._prompt_exists_for_client
    sentiment_parser._gemini_extract_sentiment = fake_extract
    sentiment_parser._prompt_exists_for_client = fake_prompt_exists

    try:
        written = asyncio.run(sentiment_parser.parse_sentiment_batch(conn, batch))
    finally:
        sentiment_parser._gemini_extract_sentiment = original_extract
        sentiment_parser._prompt_exists_for_client = original_prompt_exists

    assert written == 2
    assert call_sizes == [2, 1, 1]
    assert len(conn.executed) == 2
