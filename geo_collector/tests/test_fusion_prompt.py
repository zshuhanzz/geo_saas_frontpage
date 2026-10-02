from datetime import datetime

from src.services.fusion_prompt import build_fusion_instruction


def test_solution_discovery_fusion_prompt_prefers_lightweight_rewrites():
    prompt = build_fusion_instruction(
        "What AI video generator is best for brands creating promotional clips for launch campaigns?",
        persona="Growth marketer",
        intent="Solution Discovery",
        n=3,
    )

    assert "LIGHTWEIGHT rewrite" in prompt
    assert "stay close to the base query" in prompt
    assert "Do not turn a broad query into a much narrower channel" in prompt
    assert "Vary contextual modifiers: year, location, budget, use case, authority source" not in prompt
    assert "budget-conscious parent" not in prompt


def test_fusion_prompt_blocks_stale_years_and_only_allows_current_year_when_needed():
    current_year = datetime.now().year

    prompt = build_fusion_instruction(
        "Which text-to-video tool do most people recommend?",
        intent="Solution Discovery",
        n=2,
    )

    assert f"If a year is genuinely needed, use the current year ({current_year})" in prompt
    assert "Do not invent stale or past years" in prompt
    assert "2024" not in prompt


def test_fusion_prompt_requires_same_language_as_client_prompt():
    prompt = build_fusion_instruction(
        "在美国市场做AI搜索引擎优化，业内专家最推荐哪款实体优化工具？",
        intent="Solution Discovery",
        n=1,
    )

    assert "must use the same language as the base query" in prompt
    assert "Do not translate Chinese queries into English" in prompt
    assert "country, market, or platform" in prompt


def test_fusion_prompt_discourages_substantially_longer_rewrites():
    prompt = build_fusion_instruction(
        "Which GEO dashboard is best for B2B teams?",
        intent="Solution Discovery",
        n=1,
    )

    assert "Do not make a short base query substantially longer" in prompt
    assert "prefer similar or shorter length" in prompt


def test_single_variant_does_not_inject_persona_for_baseline_visibility_probe():
    prompt = build_fusion_instruction(
        "Which text-to-video tool do most people recommend?",
        persona="Growth marketer",
        intent="Solution Discovery",
        n=1,
    )

    assert "Growth marketer" not in prompt
    assert "PERSONA INTEGRATION" not in prompt
    assert "baseline visibility probe" in prompt


def test_multi_variant_uses_baseline_first_then_optional_persona():
    prompt = build_fusion_instruction(
        "Which text-to-video tool do most people recommend?",
        persona="Growth marketer",
        intent="Solution Discovery",
        n=3,
    )

    assert "Growth marketer" in prompt
    assert "Variant 1 must be a baseline" in prompt
    assert "Variant 2 may lightly reflect the persona" in prompt
    assert "Some variants should not use persona" in prompt
