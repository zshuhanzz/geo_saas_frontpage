from routers import content_preselect


def test_preselect_publish_platform_uses_template_channel():
    assert (
        content_preselect._resolve_preselect_publish_platform(
            {"publish_platform": "reddit"}
        )
        == "reddit"
    )


def test_preselect_publish_platform_does_not_fallback_to_ai_engine():
    assert content_preselect._resolve_preselect_publish_platform({}) == "official_site"
