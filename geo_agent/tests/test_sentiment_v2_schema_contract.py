from pipelines.analysis_pipeline import SCHEMA_HINTS, build_metric_category_scope_rules
from graphs.analyze import SCHEMA_CONTEXT


def test_sentiment_fallback_schema_uses_v2_labels_and_denominator_contract():
    hint = SCHEMA_HINTS["sentiment"]

    assert "Mixed/Neutral" in hint
    assert "Insufficient Evidence" in hint
    assert "Theme sentiment" in hint
    assert "rated denominator" in hint
    assert "exclude Insufficient Evidence" in hint
    assert "client_prompt_id" in hint
    assert "sentiment_result_id" not in hint


def test_sentiment_scope_rules_use_direct_theme_prompt_relationship():
    rules = build_metric_category_scope_rules(["sentiment"])

    assert "geo_sentiment_themes.client_prompt_id" in rules
    assert "for example `geo_sentiment_themes`" not in rules
    assert "cp.is_active = true" in rules


def test_direct_nl2sql_schema_uses_sentiment_v2_prompt_scope():
    assert "geo_sentiment_results(id UUID, client_id UUID, client_prompt_id UUID" in SCHEMA_CONTEXT
    assert "geo_sentiment_themes(id UUID, client_id UUID, client_prompt_id UUID" in SCHEMA_CONTEXT
    assert "geo_sentiment_themes.client_prompt_id" in SCHEMA_CONTEXT
    assert "cp.is_active = true" in SCHEMA_CONTEXT
    assert "cp.is_active = true AND gi.is_active = true AND gi.categories @> '[\"Sentiment\"]'::jsonb" in SCHEMA_CONTEXT
    assert "sentiment_result_id" not in SCHEMA_CONTEXT
