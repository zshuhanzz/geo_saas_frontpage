from geo_common.llm import parse_model_region_overrides, resolve_model_region


def test_resolve_model_region_uses_configured_override_for_ga_global_model():
    overrides = '{"gemini-3.5-flash": "global"}'

    assert (
        resolve_model_region(
            "gemini-3.5-flash",
            overrides_value=overrides,
            default_region="us-central1",
            global_region="global",
        )
        == "global"
    )


def test_resolve_model_region_preserves_legacy_preview_fallback():
    assert (
        resolve_model_region(
            "gemini-3-flash-preview",
            overrides_value=None,
            default_region="us-central1",
            global_region="global",
        )
        == "global"
    )


def test_resolve_model_region_preserves_stable_default_fallback():
    assert (
        resolve_model_region(
            "gemini-2.0-flash",
            overrides_value=None,
            default_region="us-central1",
            global_region="global",
        )
        == "us-central1"
    )


def test_parse_model_region_overrides_accepts_comma_separated_escape_hatch():
    assert parse_model_region_overrides("gemini-3.5-flash=global,foo=us") == {
        "gemini-3.5-flash": "global",
        "foo": "us",
    }
