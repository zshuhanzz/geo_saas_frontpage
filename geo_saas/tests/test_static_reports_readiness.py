import inspect

from routers.static_reports.readiness import ReadinessResult, check_report_readiness


def test_readiness_result_ready_requires_no_reasons():
    assert ReadinessResult(reasons=[]).ready is True
    assert ReadinessResult(reasons=["sentiment_missing"]).ready is False


def test_readiness_result_preserves_counts():
    result = ReadinessResult(
        reasons=["citation_missing"],
        data_completeness={"raw_results": 10, "analyzed_results": 9},
    )
    assert result.ready is False
    assert result.data_completeness["analyzed_results"] == 9


def test_sentiment_readiness_uses_active_prompt_and_intent_scope():
    source = inspect.getsource(check_report_readiness)

    assert "JOIN geo_client_prompts cp" in source
    assert "cp.is_active = true" in source
    assert "JOIN geo_global_intents gi" in source
    assert "gi.is_active = true" in source
    assert "gi.categories @> '[\"Sentiment\"]'::jsonb" in source
