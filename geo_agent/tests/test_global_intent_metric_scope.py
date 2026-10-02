from pipelines.analysis_pipeline import (
    build_metric_category_scope_rules,
    validate_sql_safety,
)


def test_metric_category_scope_rules_map_domains_to_global_config_categories():
    rules = build_metric_category_scope_rules(["visibility", "citation", "sentiment"])

    assert "geo_global_intents" in rules
    assert "gi.intent_name = cp.intent" in rules
    assert """gi.categories @> '["Visibility"]'::jsonb""" in rules
    assert """gi.categories @> '["Citation"]'::jsonb""" in rules
    assert """gi.categories @> '["Sentiment"]'::jsonb""" in rules


def test_global_intents_table_is_allowed_for_metric_scope_filters():
    sql = """
        SELECT COUNT(*)
        FROM geo_sentiment_results sr
        JOIN geo_client_prompts cp
          ON cp.id = sr.client_prompt_id AND cp.client_id = sr.client_id
        JOIN geo_global_intents gi
          ON gi.intent_name = cp.intent
        WHERE sr.client_id = $1
          AND cp.client_id = $1
          AND gi.is_active = true
          AND gi.categories @> '["Sentiment"]'::jsonb
    """

    ok, reason = validate_sql_safety(sql, ["sentiment"])

    assert ok, reason
