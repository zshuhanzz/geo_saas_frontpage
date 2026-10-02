from pathlib import Path


WEB_ROOT = Path(__file__).parents[1] / "web" / "src"


def test_cross_route_keeps_cross_selected_in_top_level_view_selector():
    source = (WEB_ROOT / "pages" / "Insights.tsx").read_text()

    assert 'value={viewBy}' in source
    assert 'value={viewBy === "cross"' not in source
    assert 'location.pathname !== "/insights/channel-analysis"' not in source


def test_channel_page_uses_an_independent_cross_dimension_selector():
    source = (WEB_ROOT / "pages" / "insights" / "ChannelAnalysisPage.tsx").read_text()

    assert "const [crossDimension, setCrossDimension]" in source
    assert "value={crossDimension}" in source
    assert 'crossReason?.startsWith("missing_")' in source


def test_product_visibility_uses_backend_response_coverage_not_binary_presence():
    source = (WEB_ROOT / "pages" / "insights" / "Visibility.tsx").read_text()

    assert "visibility_score: total > 0 ? 100 : 0" not in source
    assert "visibilityRes.summary?.visibility_score" in source
    assert "pt.visibility_score" in source


def test_product_visuals_do_not_render_every_own_product_in_emerald():
    source = (WEB_ROOT / "components" / "insights" / "VisibilityDashboard.tsx").read_text()

    assert 'dimension === "product" ? PRODUCT_COLORS[index % PRODUCT_COLORS.length]' in source
    assert 'entityDimension={dimension}' in source


def test_non_brand_dimension_date_queries_use_shanghai_timezone():
    insights_root = WEB_ROOT.parents[1] / "src" / "routers" / "insights"
    product_visibility = (insights_root / "product_visibility.py").read_text()
    topic_visibility = (insights_root / "topic_visibility.py").read_text()
    product_sentiment = (insights_root / "product_sentiment.py").read_text()
    shadow_cooccurrence = (insights_root / "shadow_cooccurrence.py").read_text()

    assert 'date_bucket_expr("gr.ingested_at", interval, timezone=SHANGHAI_TZ)' in product_visibility
    assert 'date_bucket_expr("bm.executed_at", interval, timezone=SHANGHAI_TZ)' in topic_visibility
    assert 'date_range_filter_expr("pm.executed_at", "date_from", "date_to")' in product_sentiment
    assert 'local_date_expr("bm.executed_at")' in shadow_cooccurrence
