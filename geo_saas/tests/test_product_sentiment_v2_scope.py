from routers.insights.product_sentiment import _SQL


def test_product_sentiment_uses_verified_customer_products_and_active_prompts():
    assert "sr.client_id = :client_id" in _SQL
    assert "pm.client_id = sr.client_id" in _SQL
    assert "pm.product_role IN ('own', 'shadow_brand_product')" in _SQL
    assert "pm.owner_brand_id IS NOT NULL" in _SQL
    assert "JOIN geo_client_brands cb" in _SQL
    assert "cb.client_id = pm.client_id" in _SQL
    assert "pm.product_role = 'own' AND cb.is_shadow = FALSE" in _SQL
    assert "pm.product_role = 'shadow_brand_product' AND cb.is_shadow = TRUE" in _SQL
    assert "cp.is_active = TRUE" in _SQL
    assert "gi.is_active = TRUE" in _SQL
    assert "gi.categories @> '[\"Sentiment\"]'::jsonb" in _SQL
    assert "COUNT(DISTINCT sr.id)" in _SQL
