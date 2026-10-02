from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2] / "migrations" / "136_sentiment_v2.sql"
).read_text(encoding="utf-8")


def test_migration_136_enforces_product_owner_workspace_and_role_scope() -> None:
    assert "validate_geo_topic_product_scope" in MIGRATION
    assert "topic.client_id = NEW.client_id" in MIGRATION
    assert "topic.is_active" not in MIGRATION
    assert "brand.client_id = NEW.client_id" in MIGRATION
    assert "peer.client_id = NEW.client_id" in MIGRATION
    assert "NEW.product_role = 'own' AND brand.is_shadow = TRUE" in MIGRATION
    assert "NEW.product_role = 'shadow_brand_product' AND brand.is_shadow = FALSE" in MIGRATION
    assert "Active Own and Shadow products require owner_brand_id" not in MIGRATION
    assert "NEW.is_active AND NOT brand.is_active" in MIGRATION
    assert "owner_peer_id, is_active" in MIGRATION
    assert "CREATE TRIGGER trg_geo_topic_product_scope" in MIGRATION
    assert MIGRATION.count("FOR SHARE;") >= 3


def test_migration_136_blocks_brand_deactivation_with_active_products() -> None:
    assert "validate_geo_brand_deactivation" in MIGRATION
    assert "CREATE TRIGGER trg_geo_brand_deactivation" in MIGRATION
    assert "p.owner_brand_id = NEW.id" in MIGRATION
    assert "p.client_id = NEW.client_id" in MIGRATION
    assert "p.is_active = TRUE" in MIGRATION


def test_migration_136_product_check_limits_shadow_peer_owner_to_resale() -> None:
    shadow_branch = MIGRATION.split("product_role = 'shadow_brand_product'", 1)[1]
    branch = shadow_branch.split("OR (product_role = 'peer'", 1)[0]
    assert "shadow_sub_role = 'resale' OR owner_peer_id IS NULL" in branch


def test_migration_136_updates_every_active_v2_sentiment_metric_contract() -> None:
    for metric_name in (
        "sentiment_distribution",
        "sentiment_trend",
        "product_sentiment_by_role",
        "brand_sentiment_breakdown",
    ):
        assert f"metric_name = '{metric_name}'" in MIGRATION

    assert "Mixed/Neutral" in MIGRATION
    assert "Insufficient Evidence" in MIGRATION
    assert "FILTER (WHERE sentiment <> 'Insufficient Evidence')" in MIGRATION
    assert "WHERE domain = 'sentiment'" in MIGRATION
    assert "gi.categories @> '[\"Sentiment\"]'::jsonb" in MIGRATION
    assert "st.client_prompt_id" in MIGRATION
    assert "join geo_client_prompts cp directly" in MIGRATION
    assert "Every sentiment metric must filter cp.is_active = TRUE" in MIGRATION
    assert "COALESCE(calculation_hint, '') ||" in MIGRATION
    assert "JOIN geo_client_brands cb ON cb.id = pm.owner_brand_id" in MIGRATION
    assert "pm.product_role = 'own' AND cb.is_shadow = FALSE" in MIGRATION
    assert "pm.product_role = 'shadow_brand_product' AND cb.is_shadow = TRUE" in MIGRATION


def test_migration_136_makes_new_v2_sentiment_writes_idempotent() -> None:
    assert "uq_geo_sentiment_results_v2_client_result" in MIGRATION
    assert "WHERE classifier_version = 'sentiment-v2'" in MIGRATION
