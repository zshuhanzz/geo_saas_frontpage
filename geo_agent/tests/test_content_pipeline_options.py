import pytest
from datetime import datetime, timezone
import logging

from pipelines import content_pipeline
from routers import tasks as task_router


class FakePool:
    def __init__(self, value: str | None):
        self.value = value

    async def fetchrow(self, query: str, key: str):
        assert "content_generation_model_list" in key
        if self.value is None:
            return None
        return {"value": self.value}


class PromptDebugPool:
    def __init__(self, value: str | None):
        self.value = value
        self.keys: list[str] = []

    async def fetchrow(self, query: str, key: str):
        self.keys.append(key)
        if self.value is None:
            return None
        return {"value": self.value}


class BrandContextPool:
    async def fetchrow(self, query: str, client_id: str):
        if "geo_brand_profiles" in query:
            return {
                "brand_name": None,
                "tone_of_voice": "helpful and practical",
                "target_audience": "creators",
                "key_messages": [],
                "brand_values": [],
                "language": "en-US",
            }
        return None

    async def fetch(self, query: str, client_id: str):
        assert "geo_client_brands" in query
        assert "geo_client_domains" in query
        return [{
            "brand_name": "Dreamina",
            "aliases": ["Dreamina AI"],
            "domains": ["dreaminai.net", "dreamina.capcut.com"],
        }]


class TemplateRuntimePool:
    async def fetchrow(self, query: str, task_id: str):
        assert "agt.template_id = t.id::text" in query
        return {
            "name": "Reddit Article",
            "default_prompt": "Default template instruction",
            "defaults": {"publish_platform": "reddit", "depth": "deep"},
            "wizard_config": {
                "platform_profile": "reddit",
                "generation_requirements": {"tone": "community-first"},
                "resource_link_policy": {
                    "enabled": True,
                    "apply_to_content_types": ["reddit_article"],
                },
                "quality_gate": {
                    "enabled": True,
                    "rules": [{"id": "reddit_single_tldr", "type": "max_occurrences"}],
                },
                "citation_analysis": {"enabled": True, "mode": "reddit_citation_analysis_then_generate"},
                "steps": {
                    "generation_config": {"default_publish_platform": "reddit", "default_depth": "deep"},
                    "content_type": {"default": "reddit_article"},
                    "citation_analysis": {
                        "enabled": True,
                        "citation_source_scope": "reddit_citations",
                    },
                },
            },
        }


class CitationPreflightReusePool(TemplateRuntimePool, BrandContextPool):
    def __init__(self):
        self.logs: list[dict] = []

    async def execute(self, query: str, *args):
        if "status_logs" in query:
            self.logs.extend(args[1] if isinstance(args[1], list) else [])
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_load_template_runtime_config_joins_text_template_id_to_uuid_safely():
    config = await content_pipeline._load_template_runtime_config(
        TemplateRuntimePool(),
        "00000000-0000-0000-0000-000000000000",
    )

    assert config["template_name"] == "Reddit Article"
    assert config["default_prompt"] == "Default template instruction"
    assert config["default_publish_platform"] == "reddit"
    assert config["default_depth"] == "deep"
    assert config["default_content_type"] == "reddit_article"
    assert config["quality_gate"]["enabled"] is True
    assert config["generation_requirements"]["tone"] == "community-first"
    assert config["resource_link_policy"]["enabled"] is True
    assert config["citation_analysis"]["enabled"] is True
    assert config["citation_analysis_step"]["citation_source_scope"] == "reddit_citations"


@pytest.mark.asyncio
async def test_load_template_runtime_config_includes_prompt_artifact_blocks():
    template_id = "11111111-1111-1111-1111-111111111111"
    row = {
        "name": "Reddit AI Citable Post Generator",
        "default_prompt": "Generate a Reddit post.",
        "defaults": {},
        "wizard_config": {
            "prompt_input_policy": {"mode": "reddit_native"},
            "ratf_rendering": {"mode": "template_native"},
            "reddit_native_contract": {"opening_contract": {"required_shape": "first_person"}},
            "experience_style_notes": {"enabled": True},
            "community_brief": {"enabled": True},
            "derived_prompt_artifacts": {"enabled": True},
        },
    }

    class Pool:
        async def fetchrow(self, query, tid):
            assert tid == template_id
            return row

    config = await content_pipeline._load_template_runtime_config(Pool(), template_id)

    assert config["prompt_input_policy"] == {"mode": "reddit_native"}
    assert config["ratf_rendering"] == {"mode": "template_native"}
    assert config["reddit_native_contract"]["opening_contract"]["required_shape"] == "first_person"
    assert config["experience_style_notes"] == {"enabled": True}
    assert config["community_brief"] == {"enabled": True}
    assert config["derived_prompt_artifacts"] == {"enabled": True}


@pytest.mark.asyncio
async def test_step_citation_analysis_reuses_matching_preflight_result(monkeypatch):
    pool = CitationPreflightReusePool()

    async def fail_run_citation_analysis(**kwargs):
        raise AssertionError("pipeline should reuse the wizard preflight result")

    preflight = {
        "enabled": True,
        "source_count": 2,
        "fingerprint": "precomputed-fingerprint",
        "citation_grounded_brief": "Use citation-backed Reddit structure.",
    }
    monkeypatch.setattr(
        content_pipeline,
        "run_citation_analysis",
        fail_run_citation_analysis,
    )
    monkeypatch.setattr(
        content_pipeline.citation_analysis_service,
        "build_citation_analysis_fingerprint",
        lambda **kwargs: "precomputed-fingerprint",
    )

    result = await content_pipeline.step_citation_analysis(
        pool,
        "00000000-0000-0000-0000-000000000000",
        {
            "citation_analysis": {"enabled": True},
            "citation_analysis_result": preflight,
        },
        "client-1",
    )

    assert result["citation_analysis_result"] is preflight


@pytest.mark.asyncio
async def test_resolve_content_model_id_uses_allowed_task_model(monkeypatch):
    async def fallback_model(role: str) -> str:
        raise AssertionError("fallback should not be used for configured model")

    monkeypatch.setattr(content_pipeline, "get_model_id", fallback_model)

    model_id = await content_pipeline._resolve_content_model_id(
        FakePool("gemini-3.1-pro-preview, gemini-3-flash-preview"),
        {"model_id": "gemini-3-flash-preview"},
    )

    assert model_id == "gemini-3-flash-preview"


@pytest.mark.asyncio
async def test_resolve_content_model_id_falls_back_to_pro_when_no_task_model(monkeypatch):
    async def fallback_model(role: str) -> str:
        assert role == "pro"
        return "gemini-3.1-pro-preview"

    monkeypatch.setattr(content_pipeline, "get_model_id", fallback_model)

    model_id = await content_pipeline._resolve_content_model_id(
        FakePool("gemini-3.1-pro-preview, gemini-3-flash-preview"),
        {},
    )

    assert model_id == "gemini-3.1-pro-preview"


@pytest.mark.asyncio
async def test_resolve_strategy_model_id_always_uses_flash(monkeypatch):
    async def fallback_model(role: str) -> str:
        assert role == "flash"
        return "gemini-3-flash-preview"

    monkeypatch.setattr(content_pipeline, "get_model_id", fallback_model)

    model_id = await content_pipeline._resolve_strategy_model_id()

    assert model_id == "gemini-3-flash-preview"


@pytest.mark.asyncio
async def test_resolve_content_model_id_rejects_unconfigured_task_model(monkeypatch):
    async def fallback_model(role: str) -> str:
        return "gemini-3.1-pro-preview"

    monkeypatch.setattr(content_pipeline, "get_model_id", fallback_model)

    with pytest.raises(ValueError, match="not configured"):
        await content_pipeline._resolve_content_model_id(
            FakePool("gemini-3.1-pro-preview"),
            {"model_id": "gemini-unknown-preview"},
        )


def test_build_generation_config_adds_google_search_tool_when_enabled():
    config = content_pipeline._build_generation_config(
        max_tokens=8192,
        search_grounding_enabled=True,
    )

    assert config.max_output_tokens == 8192
    assert config.tools
    assert config.tools[0].google_search is not None


def test_build_generation_config_omits_tools_when_grounding_disabled():
    config = content_pipeline._build_generation_config(
        max_tokens=4096,
        search_grounding_enabled=False,
    )

    assert config.max_output_tokens == 4096
    assert config.tools is None


@pytest.mark.asyncio
async def test_content_prompt_debug_enabled_from_global_setting():
    pool = PromptDebugPool("true")

    enabled = await content_pipeline._content_prompt_debug_enabled(pool)

    assert enabled is True
    assert pool.keys == ["content_generation_log_final_prompt"]


@pytest.mark.asyncio
async def test_content_prompt_debug_logs_prompt_in_chunks(caplog):
    pool = PromptDebugPool("true")
    prompt = "A" * 10 + "\nB" * 8

    caplog.set_level(logging.INFO, logger=content_pipeline.logger.name)
    await content_pipeline._log_content_prompt_debug(
        pool,
        task_id="task-1",
        client_id="client-1",
        label="content_generation",
        model_id="gemini-test",
        prompt=prompt,
        template_name="Reddit Article",
        content_type="reddit_article",
        publish_platform="reddit",
        chunk_size=12,
    )

    records = [r for r in caplog.records if "[CONTENT_PROMPT_DEBUG]" in r.getMessage()]
    assert len(records) == 3
    assert "chunk=1/3" in records[0].getMessage()
    assert "chars=26" in records[0].getMessage()
    assert "task_id=task-1" in records[0].getMessage()
    assert "client_id=client-1" in records[0].getMessage()
    assert "label=content_generation" in records[0].getMessage()
    assert "model_id=gemini-test" in records[0].getMessage()
    assert "template=Reddit Article" in records[0].getMessage()
    assert 'prompt_chunk_json="AAAAAAAAAA\\nB"' in records[0].getMessage()


def test_build_citation_analysis_instruction_injects_aggregate_brief_only():
    instruction = content_pipeline._build_citation_analysis_instruction({
        "enabled": True,
        "source_count": 2,
        "citation_grounded_brief": "## Citation Analysis Summary\n- Primary content action: new_content_gap",
        "citation_sources": [
            {"url": "https://reddit.com/r/aivideo/comments/x", "page_text": "full source text should not appear"},
        ],
    })

    assert "Citation Analysis Summary" in instruction
    assert "Primary content action" in instruction
    assert "full source text should not appear" not in instruction


def test_build_citation_analysis_instruction_omits_disabled_result():
    assert content_pipeline._build_citation_analysis_instruction({"enabled": False}) == ""


def test_build_ratf_framework_block_uses_template_metric_jobs_without_table_default():
    block = content_pipeline._build_ratf_framework_block(
        [
            {
                "key": "answerability",
                "label": "Answerability",
                "description": "Directly answers the user question.",
            }
        ],
        [],
        {
            "answerability": (
                "关键结论前置，用短段落 / 清单 / 摘要承载核心信息；"
                "不要使用表格或矩阵。"
            )
        },
    )

    assert "不要使用表格或矩阵" in block
    assert "列表 / 表格 / 摘要" not in block


def test_build_ratf_framework_block_can_hide_raw_subgoal_descriptions():
    block = content_pipeline._build_ratf_framework_block(
        metric_defs=[{"key": "answerability", "label": "可做答案性", "description": "Direct answer source"}],
        subgoal_defs=[{
            "key": "information_presentation",
            "parent_key": "answerability",
            "label": "信息呈现",
            "description": "关键答案前置，用列表 / 表格 / 摘要等高信息密度格式直接回答用户问题",
        }],
        metric_jobs={"answerability": "Use short paragraphs and concrete examples."},
        ratf_rendering={
            "include_subgoal_raw_descriptions": False,
            "subgoal_overrides": {
                "information_presentation": "Use lightweight bullets only; do not use tables."
            },
        },
    )

    assert "Use short paragraphs and concrete examples." in block
    assert "Use lightweight bullets only; do not use tables." in block
    assert "列表 / 表格 / 摘要" not in block


def test_build_ratf_framework_block_legacy_includes_raw_subgoal_descriptions():
    block = content_pipeline._build_ratf_framework_block(
        metric_defs=[{"key": "answerability", "label": "可做答案性", "description": "Direct answer source"}],
        subgoal_defs=[{
            "key": "information_presentation",
            "parent_key": "answerability",
            "label": "信息呈现",
            "description": "关键答案前置，用列表 / 表格 / 摘要等高信息密度格式直接回答用户问题",
        }],
        metric_jobs={"answerability": "Use structured answer blocks."},
    )

    assert "列表 / 表格 / 摘要" in block


def test_build_segmented_outline_prompt_uses_configured_outline_rules_without_faq_default():
    prompt = content_pipeline._build_segmented_outline_prompt(
        context_prompt="Base context",
        content_type_label="Reddit 平台文章",
        depth_label="Comprehensive",
        language="en-US",
        plan={"section_min": 3, "section_max": 5},
        segmented_generation_config={
            "outline_rules": [
                "Reddit content must use natural community sections.",
                "Do not include a FAQ section unless explicitly requested.",
            ]
        },
    )

    assert "Reddit content must use natural community sections." in prompt
    assert "Do not include a FAQ section unless explicitly requested." in prompt
    assert "FAQ 应覆盖真实读者会问的问题" not in prompt


def test_build_derived_prompt_artifacts_is_disabled_by_default():
    artifacts = content_pipeline._build_derived_prompt_artifacts(
        template_runtime_config={},
        brand_context={"brand_name": "Dreamina"},
        reddit_discovery={"summary": "Reddit dislikes promotional posts."},
        official_website_discovery={},
        citation_analysis_result={"citation_grounded_brief": "Raw citation summary"},
        strategy={"strategies": [{"name": "Guide strategy"}]},
        prompt_texts=[{"text": "Which tool works best?"}],
    )

    assert artifacts == {}


def test_build_derived_prompt_artifacts_creates_reddit_native_brief():
    artifacts = content_pipeline._build_derived_prompt_artifacts(
        template_runtime_config={
            "prompt_input_policy": {"mode": "reddit_native"},
            "derived_prompt_artifacts": {
                "output_artifacts": [
                    {
                        "key": "community_brief",
                        "label": "Community Brief",
                        "fields": ["community_tension", "closing_discussion_question"],
                    },
                    {
                        "key": "experience_style_notes",
                        "label": "Experience Style Notes",
                        "fields": ["workflow_texture", "forbidden_experience_claims"],
                    },
                ]
            },
            "reddit_native_contract": {
                "voice_contract": {
                    "forbidden_patterns": ["consensus among creators"],
                },
                "closing_contract": {"required_shape": "real_discussion_question"},
            },
        },
        brand_context={"brand_name": "Dreamina"},
        reddit_discovery={
            "summary": "Users complain about short clip limits and character drift.",
            "objections": ["Single-tool workflows feel fake."],
            "community_questions": ["How do you handle short AI video clips?"],
        },
        official_website_discovery={
            "content_gaps": ["Need workflow examples."],
        },
        citation_analysis_result={
            "citation_grounded_brief": "Citation examples show workflow/checklist patterns.",
        },
        strategy={
            "strategy_summary": "Use a multi-tool workflow angle.",
            "strategies": [{"name": "Workflow", "description": "Generation to editing workflow."}],
        },
        prompt_texts=[{"text": "What AI video generator is best for TikTok creators?"}],
    )

    assert "prepared_json" in artifacts
    assert "rendered_sections" in artifacts
    assert "Community Brief" in artifacts["rendered_sections"]
    assert "short clip limits" in artifacts["rendered_sections"]
    assert "closing_discussion_question" in artifacts["rendered_sections"]
    assert "I've been testing" not in artifacts["rendered_sections"]


def test_build_reddit_native_prompt_sections_hides_raw_internal_artifacts():
    sections = content_pipeline._build_prompt_artifact_sections(
        template_runtime_config={
            "prompt_input_policy": {
                "mode": "reddit_native",
                "hide_internal_frameworks": True,
            },
            "reddit_native_contract": {
                "structure_contract": {"forbidden_headings": ["Phase 1", "FAQ"]},
            },
        },
        derived_artifacts={
            "rendered_sections": (
                "## Experience Style Notes\n- workflow_texture: short clip limits\n\n"
                "## Community Brief\n- community_tension: short clip limits"
            ),
        },
        reddit_discovery_instruction="## Reddit Discover Insight\nraw reddit discover",
        official_website_discovery_instruction="## Official Website Discover Insight\nraw official discover",
        citation_analysis_instruction="## Citation Analysis Summary\nraw citation summary",
    )

    assert "## Community Brief" in sections
    assert "## Experience Style Notes" in sections
    assert "raw citation summary" not in sections
    assert "raw reddit discover" not in sections
    assert "Reddit Native Writing Contract" in sections


def test_build_strategy_prompt_sections_can_suppress_raw_dimensions():
    section = content_pipeline._build_strategy_prompt_sections(
        strategy={
            "strategies": [{
                "name": "Guide strategy",
                "description": "Write a guide.",
                "dimensions": {
                    "instruction": "Use Phase 1 and checklist.",
                    "format": {"structure": "Step-by-step guide"},
                    "tone": "professional",
                },
            }],
        },
        template_runtime_config={"prompt_input_policy": {"mode": "reddit_native"}},
    )

    assert section["dimension_section"] == ""
    assert section["constraints_section"] == ""
    assert section["enhancements_section"] == ""


def test_quality_gate_first_paragraph_requires_configured_patterns():
    result = content_pipeline._run_configured_quality_gate(
        "This is a broad industry overview.\n\nMore content.",
        {
            "enabled": True,
            "rules": [{
                "id": "reddit_opening_first_person_required",
                "type": "first_paragraph_required_patterns",
                "patterns": ["\\bI(?:'ve| have)\\b", "\\bmy workflow\\b"],
                "message": "Opening must start from first-person workflow/testing friction.",
                "severity": "blocker",
            }],
        },
    )

    assert result["passed"] is False
    assert result["failures"][0]["rule_id"] == "reddit_opening_first_person_required"


def test_quality_gate_brand_mentions_max_count():
    result = content_pipeline._run_configured_quality_gate(
        "Dreamina helps. Dreamina works. Dreamina is here.",
        {
            "enabled": True,
            "rules": [{
                "id": "reddit_brand_mentions_limited",
                "type": "max_regex_count",
                "pattern": "\\bDreamina\\b",
                "max": 2,
                "message": "Brand mention count is too high for Reddit.",
                "severity": "blocker",
            }],
        },
    )

    assert result["passed"] is False
    assert result["failures"][0]["rule_id"] == "reddit_brand_mentions_limited"


def test_prompt_artifact_preparation_prompt_uses_template_config_not_hardcoded_voice():
    prompt = content_pipeline._build_prompt_artifact_preparation_prompt(
        template_runtime_config={
            "derived_prompt_artifacts": {
                "materialization": "llm_json",
                "instruction": "Compress raw inputs into a peer discussion brief without guide sections.",
                "output_artifacts": [
                    {
                        "key": "community_rules",
                        "label": "Community Rules",
                        "description": "Posting risks and local norms.",
                        "fields": ["risk", "norm"],
                    }
                ],
            }
        },
        raw_artifacts={
            "reddit_discover": {"data": {"summary": "Avoid polished promos."}},
            "citation_analysis": {"citation_grounded_brief": "Raw citation strategy."},
        },
        brand_name="Dreamina",
    )

    assert "Compress raw inputs into a peer discussion brief" in prompt
    assert "community_rules" in prompt
    assert "I've been testing" not in prompt
    assert "I still don't fully trust" not in prompt


def test_render_prepared_prompt_artifacts_uses_configured_fields_and_hides_raw_json():
    rendered = content_pipeline._render_prepared_prompt_artifacts(
        template_runtime_config={
            "derived_prompt_artifacts": {
                "output_artifacts": [
                    {
                        "key": "community_brief",
                        "label": "Community Brief",
                        "fields": [
                            "community_tension",
                            "reader_objections",
                            "workflow_angle",
                        ],
                    }
                ]
            }
        },
        prepared_artifacts={
            "community_brief": {
                "community_tension": "Creators distrust one-click polished claims.",
                "reader_objections": ["Feels like a guide, not a field note."],
                "workflow_angle": "Frame it as a tool-stack decision.",
            },
            "raw_citation_analysis": "SHOULD_NOT_RENDER",
        },
    )

    assert "## Community Brief" in rendered
    assert "community_tension" in rendered
    assert "Creators distrust one-click polished claims." in rendered
    assert "SHOULD_NOT_RENDER" not in rendered


def test_confirmed_prompt_artifacts_skip_runtime_preparation():
    inputs = {
        "derived_prompt_artifacts": {
            "status": "ready",
            "source": "wizard_confirmed",
            "prepared_json": {
                "community_brief": {"summary": "Use native Reddit tone."}
            },
            "rendered_sections": "## Community Brief\nUse native Reddit tone.",
        },
        "derived_prompt_artifacts_source": "wizard_confirmed",
    }

    artifacts = content_pipeline._resolve_confirmed_prompt_artifacts(inputs)

    assert artifacts is not None
    assert artifacts["rendered_sections"].startswith("## Community Brief")


def test_reddit_research_requires_confirmed_artifacts_unless_runtime_allowed():
    assert content_pipeline._requires_confirmed_prompt_artifacts({
        "reddit_research": {
            "enabled": True,
            "artifact_preparation": {
                "reuse_confirmed_artifacts_in_final_generation": True,
                "allow_runtime_generation": False,
            },
        }
    }) is True

    assert content_pipeline._requires_confirmed_prompt_artifacts({
        "reddit_research": {
            "enabled": True,
            "artifact_preparation": {
                "reuse_confirmed_artifacts_in_final_generation": True,
                "allow_runtime_generation": True,
            },
        }
    }) is False


def test_validate_required_confirmed_prompt_artifacts_raises_clear_error():
    with pytest.raises(ValueError, match="Artifact Preparation"):
        content_pipeline._validate_required_confirmed_prompt_artifacts(
            {
                "reddit_research": {
                    "enabled": True,
                    "artifact_preparation": {
                        "reuse_confirmed_artifacts_in_final_generation": True,
                    },
                }
            },
            None,
        )


def test_quality_gate_ending_required_patterns():
    result = content_pipeline._run_configured_quality_gate(
        "I would test this as a workflow.\n\nThis ends with a CTA.",
        {
            "enabled": True,
            "rules": [{
                "id": "reddit_discussion_question_required",
                "type": "ending_required_patterns",
                "patterns": ["\\?\\s*$"],
                "message": "Reddit post must end with a discussion question.",
                "severity": "blocker",
            }],
        },
    )

    assert result["passed"] is False
    assert result["failures"][0]["rule_id"] == "reddit_discussion_question_required"


def test_quality_gate_dynamic_brand_mention_count():
    result = content_pipeline._run_configured_quality_gate(
        "Dreamina helps. Dreamina fits. Dreamina again.",
        {
            "enabled": True,
            "rules": [{
                "id": "reddit_dynamic_brand_mentions",
                "type": "dynamic_brand_mention_count",
                "max": 2,
                "severity": "blocker",
            }],
        },
        context={"brand_name": "Dreamina"},
    )

    assert result["passed"] is False
    assert result["failures"][0]["rule_id"] == "reddit_dynamic_brand_mentions"


def test_framework_coverage_uses_semantic_evidence_not_literal_metric_names():
    content = """# AI video workflow for Instagram Reels in May 2026

TL;DR: Start with a simple prompt, generate vertical B-roll, then edit the final cut in CapCut.

## Practical workflow

Use native 9:16 generation, check motion artifacts, and add captions before publishing.

## Limits and source caveats

This reflects current creator workflows as of May 2026. Verify product features before making paid decisions.

## FAQ

### What is the best setup?

Use a generator for raw clips and a timeline editor for final pacing.
"""

    result = content_pipeline._evaluate_framework_coverage(
        content,
        [
            {"key": "readability", "label": "Readability"},
            {"key": "answerability", "label": "Answerability"},
            {"key": "trustworthy", "label": "Trustworthy"},
            {"key": "freshness", "label": "Freshness"},
        ],
        {},
    )

    assert result["ok"] is True
    assert result["missing"] == []
    assert set(result["evidence"].keys()) == {
        "readability",
        "answerability",
        "trustworthy",
        "freshness",
    }


def test_brand_density_issues_flag_overstuffed_official_article():
    content = "\n".join([
        "# Best AI video generator",
        "Dreamina helps creators.",
        "Dreamina is useful for Reels.",
        "Dreamina supports a workflow.",
        "Dreamina can fit social posts.",
        "Dreamina may reduce editing friction.",
        "Dreamina is one option.",
    ])

    issues = content_pipeline._detect_brand_density_issues(
        content,
        brand_name="Dreamina",
        quality_gate_config={
            "brand_density": {
                "enabled": True,
                "max_mentions": 3,
                "max_mentions_per_1000_words": 20,
            }
        },
    )

    assert issues
    assert "品牌提及过密" in issues[0]


def test_revision_prompt_has_stage_specific_cleanup_and_reddit_natural_heading_rules():
    prompt = content_pipeline._build_quality_gate_revision_prompt(
        generated_content="# Post\n\n## Brand Fit Summary\n\nDreamina fits here.",
        quality_gate_result={
            "failures": [{"rule_id": "post_revision_integrity_failed"}],
            "warnings": [],
        },
        content_type="reddit_article",
        publish_platform="reddit",
        brand_context={"brand_name": "Dreamina"},
        template_runtime_config={
            "quality_gate": {
                "revision_guidance": {
                    "round_2": [
                        "第二轮只清理重复 FAQ、重复 Conclusion 和残缺句。",
                        "继续把 Brand Fit Summary 改成自然 Reddit 标题。",
                    ],
                }
            }
        },
        citation_analysis_result=None,
        attempt_number=2,
        max_attempts=2,
    )

    assert "第二轮" in prompt
    assert "重复 FAQ" in prompt
    assert "Brand Fit Summary" in prompt
    assert "自然 Reddit 标题" in prompt


def test_revision_prompt_uses_template_configured_round_guidance():
    prompt = content_pipeline._build_quality_gate_revision_prompt(
        generated_content="# Draft\n\nDreamina draft.",
        quality_gate_result={
            "failures": [{"rule_id": "brand_density"}],
            "warnings": [],
        },
        content_type="official_website_article",
        publish_platform="official_site",
        brand_context={"brand_name": "Dreamina"},
        template_runtime_config={
            "quality_gate": {
                "revision_guidance": {
                    "general": [
                        "Use the template-specific revision voice.",
                    ],
                    "round_1": [
                        "Official round one must repair commercial extractability.",
                    ],
                    "round_2": [
                        "Official round two must remove residual editor-facing artifacts.",
                    ],
                }
            }
        },
        citation_analysis_result=None,
        attempt_number=1,
        max_attempts=2,
    )

    assert "Use the template-specific revision voice." in prompt
    assert "Official round one must repair commercial extractability." in prompt
    assert "Official round two must remove residual editor-facing artifacts." not in prompt
    assert "本轮修正重点：第一轮" not in prompt
    assert "本轮修正重点：第二轮" not in prompt


def test_revision_prompt_preserves_verified_markdown_links():
    prompt = content_pipeline._build_quality_gate_revision_prompt(
        generated_content=(
            "# Guide\n\n"
            "Use the [verified workflow guide]"
            "(https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator)."
        ),
        quality_gate_result={
            "failures": [{"rule_id": "brand_density"}],
            "warnings": [],
        },
        content_type="official_website_article",
        publish_platform="official_site",
        brand_context={"brand_name": "Dreamina"},
        template_runtime_config={
            "resource_link_policy": {
                "enabled": True,
                "apply_to_content_types": ["official_website_article"],
                "link_scope": "all_markdown_links",
                "preserve_verified_markdown_links": True,
            }
        },
        citation_analysis_result=None,
        attempt_number=1,
        max_attempts=1,
    )

    assert "保留" in prompt
    assert "verified" in prompt.lower()
    assert "Markdown link" in prompt or "Markdown 链接" in prompt
    assert "不能把已验证链接改成纯文本" in prompt


@pytest.mark.asyncio
async def test_build_post_revision_quality_review_does_not_leak_pre_revision_issues(monkeypatch):
    async def fake_citation_alignment_review(**kwargs):
        raise AssertionError("LLM citation review should not run when mode is not llm/hybrid")

    monkeypatch.setattr(
        content_pipeline,
        "_review_citation_alignment_with_llm",
        fake_citation_alignment_review,
    )

    pre_review = {
        "overall_score": 6.5,
        "llm_overall_score": 6.5,
        "summary": "Original review found problems.",
        "issues": [
            "内容未明显响应 Citation Analysis 的 primary_action=new_content_gap; 需要围绕该动作补充结构或措辞。",
            "第 99 行疑似残缺或未完成句：broken sentence",
        ],
        "quality_gate": {
            "enabled": True,
            "status": "failed",
            "passed": False,
            "failures": [{"rule_id": "citation_alignment_failed"}],
            "warnings": [],
        },
    }
    revised_content = """# Practical AI video workflow for Reddit

Dreamina is one option in a broader workflow for creators comparing AI video tools.

## Brand Fit Summary: Where Dreamina fits

Dreamina fits when someone needs a quick concept-to-asset workflow, but it still needs timeline editing for final polish.

## Practical workflow

Use a simple prompt, generate a visual asset, test motion, then edit the final Reel in a normal timeline.

## Limitations

No current AI video tool is a one-click replacement for editing.
"""

    final_review = await content_pipeline._build_post_revision_quality_review(
        revised_content=revised_content,
        pre_revision_review=pre_review,
        quality_gate_config={
            "enabled": True,
            "min_overall_score": 8,
            "citation_alignment_as_blocker": True,
            "citation_alignment_markers": {"new_content_gap": ["brand fit", "workflow", "limitation"]},
        },
        metric_defs=[],
        include_data_disclosure=False,
        brand_context={"brand_name": "Dreamina"},
        content_type="reddit_article",
        publish_platform="reddit",
        citation_analysis_result={
            "enabled": True,
            "source_count": 2,
            "content_action_decision": {"primary_action": "new_content_gap"},
            "brand_mention_summary": {"unmentioned": 2},
        },
    )

    assert final_review["quality_gate"]["status"] == "revised"
    assert final_review["quality_gate"]["passed"] is True
    assert final_review["issues"] == []
    assert final_review["pre_revision_issue_count"] == 2
    assert final_review["content_integrity"]["ok"] is True
    assert final_review["citation_alignment"]["ok"] is True


@pytest.mark.asyncio
async def test_step_content_revise_runs_second_recheck_after_second_revision(monkeypatch):
    class RecordingPool:
        def __init__(self):
            self.executions: list[tuple[str, tuple]] = []

        async def execute(self, query: str, *args):
            self.executions.append((query, args))
            return "UPDATE 1"

    async def fake_resolve_model_id(pool, inputs):
        return "gemini-test-pro"

    async def fake_get_client(model_id, role="pro"):
        return object()

    async def fake_llm_generate(*args, **kwargs):
        attempt = len(generated_attempts) + 1
        generated_attempts.append(attempt)
        return f"# Revised attempt {attempt}\n\nDreamina is mentioned in a practical workflow."

    review_calls: list[str] = []

    async def fake_post_revision_review(**kwargs):
        review_calls.append(kwargs["revised_content"])
        if len(review_calls) == 1:
            return {
                "overall_score": 7.0,
                "issues": ["Still has a structural blocker."],
                "quality_gate": {
                    "enabled": True,
                    "status": "failed",
                    "passed": False,
                    "revise_required": True,
                    "failure_count": 1,
                    "warning_count": 0,
                    "failures": [{"rule_id": "still_bad"}],
                    "warnings": [],
                },
            }
        return {
            "overall_score": 8.8,
            "issues": [],
            "quality_gate": {
                "enabled": True,
                "status": "revised",
                "passed": True,
                "revise_required": False,
                "failure_count": 0,
                "warning_count": 0,
                "failures": [],
                "warnings": [],
            },
        }

    generated_attempts: list[int] = []
    monkeypatch.setattr(content_pipeline, "_resolve_content_model_id", fake_resolve_model_id)
    monkeypatch.setattr(content_pipeline, "get_genai_client", fake_get_client)
    monkeypatch.setattr(content_pipeline, "_llm_generate", fake_llm_generate)
    monkeypatch.setattr(content_pipeline, "_build_post_revision_quality_review", fake_post_revision_review)

    pool = RecordingPool()
    result = await content_pipeline.step_content_revise(
        pool,
        "00000000-0000-0000-0000-000000000000",
        {
            "_output": {
                "content": "# Draft\n\nDreamina draft.",
                "content_markdown": "# Draft\n\nDreamina draft.",
                "content_type": "reddit_article",
                "quality_review": {
                    "overall_score": 6.5,
                    "issues": ["Duplicate FAQ."],
                    "quality_gate": {
                        "enabled": True,
                        "status": "failed",
                        "passed": False,
                        "revise_required": True,
                        "failure_count": 1,
                        "warning_count": 0,
                        "failures": [{"rule_id": "duplicate_faq"}],
                        "warnings": [],
                    },
                },
            },
            "brand_context": {"brand_name": "Dreamina"},
            "template_runtime_config": {"quality_gate": {"enabled": True, "max_revise_attempts": 2}},
            "content_metric_definitions": [],
            "include_data_disclosure": False,
            "publish_platform": "reddit",
        },
        "client-id",
    )

    output = result["_output"]
    assert generated_attempts == [1, 2]
    assert len(review_calls) == 2
    assert output["quality_review"]["quality_gate"]["status"] == "revised"
    assert output["quality_review"]["revision"]["attempt_count"] == 2
    assert output["pre_revision_quality_review"]["quality_gate"]["status"] == "failed"
    assert any(args[1] == 8 and args[2] == "running" for _, args in pool.executions)
    assert any(args[1] == 8 and args[2] == "done" for _, args in pool.executions)


@pytest.mark.asyncio
async def test_step_content_revise_marks_second_round_skipped_when_first_revision_passes(monkeypatch):
    class RecordingPool:
        def __init__(self):
            self.executions: list[tuple[str, tuple]] = []

        async def execute(self, query: str, *args):
            self.executions.append((query, args))
            return "UPDATE 1"

    async def fake_resolve_model_id(pool, inputs):
        return "gemini-test-pro"

    async def fake_get_client(model_id, role="pro"):
        return object()

    async def fake_llm_generate(*args, **kwargs):
        return "# Revised once\n\nDreamina now has balanced brand density."

    async def fake_post_revision_review(**kwargs):
        return {
            "overall_score": 8.8,
            "issues": [],
            "quality_gate": {
                "enabled": True,
                "status": "revised",
                "passed": True,
                "revise_required": False,
                "failure_count": 0,
                "warning_count": 0,
                "failures": [],
                "warnings": [],
            },
        }

    monkeypatch.setattr(content_pipeline, "_resolve_content_model_id", fake_resolve_model_id)
    monkeypatch.setattr(content_pipeline, "get_genai_client", fake_get_client)
    monkeypatch.setattr(content_pipeline, "_llm_generate", fake_llm_generate)
    monkeypatch.setattr(content_pipeline, "_build_post_revision_quality_review", fake_post_revision_review)

    pool = RecordingPool()
    result = await content_pipeline.step_content_revise(
        pool,
        "00000000-0000-0000-0000-000000000000",
        {
            "_output": {
                "content": "# Draft\n\nDreamina draft with too many Dreamina mentions.",
                "content_markdown": "# Draft\n\nDreamina draft with too many Dreamina mentions.",
                "content_type": "official_website_article",
                "quality_review": {
                    "overall_score": 6.0,
                    "issues": ["Brand density too high."],
                    "quality_gate": {
                        "enabled": True,
                        "status": "failed",
                        "passed": False,
                        "revise_required": True,
                        "failure_count": 1,
                        "warning_count": 0,
                        "failures": [{"rule_id": "brand_density"}],
                        "warnings": [],
                    },
                },
            },
            "brand_context": {"brand_name": "Dreamina"},
            "template_runtime_config": {"quality_gate": {"enabled": True, "max_revise_attempts": 2}},
            "content_metric_definitions": [],
            "include_data_disclosure": False,
            "publish_platform": "official_website",
        },
        "client-id",
    )

    output = result["_output"]
    assert output["quality_review"]["revision"]["attempt_count"] == 1
    assert output["quality_review"]["quality_gate"]["status"] == "revised"
    assert any(args[1] == 7 and args[2] == "skipped" for _, args in pool.executions)
    assert any(args[1] == 8 and args[2] == "skipped" for _, args in pool.executions)
    assert not any(args[1] == 7 and args[2] == "done" for _, args in pool.executions)
    assert not any(args[1] == 8 and args[2] == "done" for _, args in pool.executions)


def test_content_workflow_steps_include_visible_citation_quality_and_revise():
    steps = task_router._get_workflow_steps("content_generation")

    assert [step["name"] for step in steps] == [
        "citation_analysis",
        "strategy_generation",
        "content_generation",
        "quality_review",
        "revise_round_1",
        "quality_recheck",
        "revise_round_2",
        "quality_recheck_round_2",
    ]
    assert steps[0]["label"] == "Citation Analysis"
    assert steps[3]["label"] == "Quality Gate"
    assert steps[4]["label"] == "第一轮 Revise"
    assert steps[5]["label"] == "修订后复查"
    assert steps[6]["label"] == "第二轮 Revise"
    assert steps[7]["label"] == "第二轮后复查"


def test_normalize_content_markdown_promotes_plain_reddit_title_to_h1():
    content = "I stopped looking for one best AI video app for Reels.\n\nBody paragraph."

    normalized = content_pipeline._normalize_content_markdown_for_output(
        content,
        content_type="reddit_article",
        publish_platform="reddit",
    )

    assert normalized.startswith("# I stopped looking for one best AI video app for Reels.\n\n")


def test_strip_llm_process_artifacts_keeps_final_markdown_article():
    content = """RSThe search results confirm that in the simulated current time, these tools exist.

The primary brand to mention is "AnswerX". The prompt says:

Let's double check the rules.

Looks solid.# I stopped treating GEO content like keyword stuffing

TL;DR: The useful workflow is to make each section answer-ready before publishing.

## Where AnswerX fits

AnswerX fits teams that need clearer citation-ready product education.
"""

    cleaned = content_pipeline._strip_llm_process_artifacts(
        content,
        content_type="reddit_article",
        publish_platform="reddit",
    )

    assert cleaned.startswith("# I stopped treating GEO content like keyword stuffing")
    assert "Let's double check the rules" not in cleaned
    assert "The prompt says" not in cleaned
    assert "Where AnswerX fits" in cleaned


def test_detect_content_integrity_flags_llm_process_artifacts():
    content = """# I stopped treating GEO content like keyword stuffing

The failure is `post_revision_framework_missing`, so let's double check the rules.

## Where AnswerX fits

AnswerX fits teams that need clearer citation-ready product education.
"""

    issues = content_pipeline._detect_content_integrity_issues(
        content,
        current_year=2026,
        brand_name="AnswerX",
        require_brand_mention=True,
    )

    assert any("模型过程文本" in issue for issue in issues)


def test_detect_content_integrity_allows_colon_before_bullet_list():
    content = """# Choosing an AI Video Tool for Instagram Creators in 2026

When evaluating an AI video tool for social media, creators should look for platforms that meet these core requirements:

* **Native 9:16 generation:** Keeps the subject framed for Reels.
* **Motion consistency:** Reduces distracting visual artifacts.

Dreamina can be evaluated as one option in this workflow.
"""

    issues = content_pipeline._detect_content_integrity_issues(
        content,
        current_year=2026,
        brand_name="Dreamina",
        require_brand_mention=True,
    )

    assert not any("第 3 行疑似残缺" in issue for issue in issues)


def test_detect_content_integrity_allows_colon_before_subheadings():
    content = """# My field notes on AI video tools for Reels

Dreamina fits a workflow where creators divide the video stack into three categories:

### 1. Native Social Editors
Tools like CapCut remain useful for final pacing.

### 2. Image-to-Video Motion Tools
These tools help creators keep framing and lighting consistent.
"""

    issues = content_pipeline._detect_content_integrity_issues(
        content,
        current_year=2026,
        brand_name="Dreamina",
        require_brand_mention=True,
    )

    assert not any("疑似残缺或未完成句" in issue for issue in issues)


def test_normalize_official_internal_links_uses_generic_reader_facing_section():
    content = """# Best AI Video Tool for Instagram Creators

## Internal Linking Suggestions

- Link to the text-to-video guide.
- Suggested anchor text: what is text-to-video.
"""

    normalized = content_pipeline._normalize_official_internal_linking_section(
        content,
        content_type="official_website_article",
        brand_name="Dreamina",
    )

    assert "Internal Linking Suggestions" not in normalized
    assert "## Helpful Resources" in normalized
    assert "Related Dreamina Resources" not in normalized
    assert "Link to the" not in normalized
    assert "Read the text-to-video guide." in normalized
    assert "Suggested anchor text" not in normalized


def test_normalize_official_internal_links_removes_non_publishable_editor_artifacts():
    content = """# Commercial AI Video Workflow

## Related Dreamina Resources
To maximize the SEO and AEO visibility of this guide and help brand marketers navigate the complete Generate-to-Edit pipeline, consider adding the following internal links across your official website:

*   **Anchor Text:** "Dreamina AI video generator"
    *   **Destination:** Dreamina official homepage or web app portal.
*   **Anchor Text:** "commercial licensing guidelines"
    *   **Destination:** Official Dreamina pricing, terms of service, or brand safety policy page.

Strategically placing these links throughout the implementation checklist and workflow sections will guide users toward their next steps.

## Frequently Asked Questions

**Can I use AI video for commercial campaigns?**
Yes, after checking current usage rights.
"""

    normalized = content_pipeline._normalize_official_internal_linking_section(
        content,
        content_type="official_website_article",
        brand_name="Dreamina",
    )

    assert "Related Dreamina Resources" not in normalized
    assert "Anchor Text" not in normalized
    assert "Destination" not in normalized
    assert "Strategically placing" not in normalized
    assert "SEO and AEO visibility" not in normalized
    assert "## Frequently Asked Questions" in normalized


def test_normalize_official_internal_links_keeps_real_links_as_helpful_resources():
    content = """# Commercial AI Video Workflow

## Internal Linking Suggestions
To optimize this article for AI search engines, we recommend integrating the following internal links naturally within the text:

*   **Anchor Text:** "what is text-to-video AI" or "basics of AI video generation"
    *   **Target Page:** `https://dreamina.capcut.com/ai-video/what-is-text-to-video`
*   **Anchor Text:** "daily credits" or "commercial plan pricing"
    *   **Target Page:** *[Insert Official Pricing/Credits Page URL]*
"""

    normalized = content_pipeline._normalize_official_internal_linking_section(
        content,
        content_type="official_website_article",
        brand_name="Dreamina",
    )

    assert "## Helpful Resources" in normalized
    assert "Internal Linking Suggestions" not in normalized
    assert "we recommend integrating" not in normalized
    assert "[what is text-to-video AI](https://dreamina.capcut.com/ai-video/what-is-text-to-video)" in normalized
    assert "Insert Official Pricing" not in normalized


def test_quality_gate_flags_editor_facing_resource_artifacts():
    content = """# Commercial AI Video Workflow

## Brand Fit Summary

Dreamina fits social media teams that need reliable image-to-video workflow support.

## Related Dreamina Resources

* **Anchor Text:** "Dreamina AI video generator"
  * **Destination:** Dreamina official homepage or web app portal.
"""

    result = content_pipeline._run_configured_quality_gate(
        content,
        {
            "enabled": True,
            "rules": [
                {
                    "id": "official_editor_artifacts",
                    "type": "forbidden_patterns",
                    "severity": "blocker",
                    "patterns": [
                        "Anchor Text\\s*:",
                        "Destination\\s*:",
                        "^\\s{0,3}##\\s+Related\\s+Dreamina\\s+Resources\\s*$",
                    ],
                }
            ],
        },
    )

    assert result["passed"] is False
    assert result["failure_count"] == 1
    assert result["failures"][0]["rule_id"] == "official_editor_artifacts"


def test_normalize_strategy_result_unwraps_nested_json_envelope_from_description():
    normalized = content_pipeline._normalize_strategy_result({
        "strategies": [
            {
                "name": "Strategy 1",
                "description": '{"strategies":[{"name":"Commercial comparison","description":"Use cited comparison patterns while adding Dreamina brand fit.","dimensions":{"tone":"official"}}],"strategy_summary":"Use comparison pattern."}',
                "dimensions": {
                    "instruction": '{"strategies":[{"name":"Commercial comparison","description":"Use cited comparison patterns while adding Dreamina brand fit.","dimensions":{"tone":"official"}}],"strategy_summary":"Use comparison pattern."}',
                },
            }
        ]
    })

    assert normalized["strategy_summary"] == "Use comparison pattern."
    assert normalized["strategies"][0]["name"] == "Commercial comparison"
    assert normalized["strategies"][0]["description"] == "Use cited comparison patterns while adding Dreamina brand fit."


def test_build_freshness_context_uses_runtime_month_and_year():
    instruction = content_pipeline._build_freshness_context(
        datetime(2026, 5, 21, tzinfo=timezone.utc)
    )

    assert "Current date: 2026-05-21" in instruction
    assert "Current month: May 2026" in instruction
    assert "Current year: 2026" in instruction
    assert "Do not frame the content as current for years earlier than 2025" in instruction


@pytest.mark.asyncio
async def test_load_content_brand_context_falls_back_to_own_brand():
    context = await content_pipeline._load_content_brand_context(
        BrandContextPool(),
        "00000000-0000-0000-0000-000000000000",
    )

    assert context["brand_name"] == "Dreamina"
    assert context["brand_name_source"] == "geo_client_brands"
    assert context["own_brands"][0]["aliases"] == ["Dreamina AI"]
    assert context["own_brands"][0]["domains"] == ["dreaminai.net", "dreamina.capcut.com"]
    assert context["owned_domains"] == ["dreaminai.net", "dreamina.capcut.com"]


def test_detect_content_integrity_issues_flags_stale_year_truncation_and_missing_brand():
    content = """# Megathread: State of AI Video for Instagram Reels in Q2 2024

The AI video space has exploded since Sora demos in February 2024, and a

## Conclusion

What tools are you using?
"""

    issues = content_pipeline._detect_content_integrity_issues(
        content,
        current_year=2026,
        brand_name="Dreamina",
        require_brand_mention=True,
    )

    assert any("标题包含过期时间锚点" in issue for issue in issues)
    assert any("疑似残缺或未完成句" in issue for issue in issues)
    assert any("过旧工具格局" in issue for issue in issues)
    assert any("没有提到当前品牌 Dreamina" in issue for issue in issues)


def test_detect_content_integrity_issues_accepts_current_complete_brand_content():
    content = """# How I would compare AI video tools for Instagram Reels in 2026

Dreamina can be evaluated alongside CapCut and Runway when creators need a workflow for turning product images into short-form campaign assets.

## Practical workflow

Use current tool documentation and keep claims conservative.
"""

    issues = content_pipeline._detect_content_integrity_issues(
        content,
        current_year=2026,
        brand_name="Dreamina",
        require_brand_mention=True,
    )

    assert issues == []


def test_detect_content_integrity_issues_flags_paragraph_cut_before_heading():
    content = """# CapCut vs automation in May 2026

Conversely, fully automated prompt-to-video

## The Core Dilemma

Dreamina fits creators who need scene-level control without rebuilding an entire timeline.
"""

    issues = content_pipeline._detect_content_integrity_issues(
        content,
        current_year=2026,
        brand_name="Dreamina",
        require_brand_mention=True,
    )

    assert any("标题前正文块疑似截断" in issue for issue in issues)


def test_build_review_content_excerpt_preserves_tail_without_fake_truncation():
    body = "\n\n".join(
        f"## Section {idx}\n\nThis is a complete paragraph for section {idx} with enough detail to force the review excerpt helper to omit the middle safely."
        for idx in range(1, 180)
    )
    content = f"# Long Reddit Article\n\nIntro paragraph is complete.\n\n{body}\n\n## Conclusion\n\nFinal complete conclusion."

    excerpt = content_pipeline._build_review_content_excerpt(content, max_chars=900)

    assert "# Long Reddit Article" in excerpt
    assert "## Conclusion" in excerpt
    assert "Final complete conclusion." in excerpt
    assert "Middle content omitted for review prompt size" in excerpt
    assert not excerpt.rstrip().endswith("section")


def test_build_review_content_excerpt_returns_full_short_content():
    content = "# Short Article\n\nComplete body.\n\n## Conclusion\n\nDone."

    assert content_pipeline._build_review_content_excerpt(content, max_chars=1000) == content


def test_normalize_strategy_result_wraps_list_response():
    result = content_pipeline._normalize_strategy_result([
        {
            "name": "Reddit workflow strategy",
            "description": "Use Reddit-native workflow framing.",
            "dimensions": {"instruction": "Write like a community field test."},
        }
    ])

    assert len(result["strategies"]) == 1
    assert "strategy_summary" in result
    assert "1 strategy" in result["strategy_summary"]


def test_normalize_strategy_result_preserves_valid_object_response():
    result = content_pipeline._normalize_strategy_result({
        "strategies": [{"name": "A"}],
        "strategy_summary": "Summary",
    })

    assert result == {"strategies": [{"name": "A"}], "strategy_summary": "Summary"}


@pytest.mark.asyncio
async def test_step_strategy_generation_reuses_existing_strategy_without_model_id(monkeypatch):
    class StrategyPool:
        async def fetch(self, query, *args):
            if "geo_optimization_subgoals" in query:
                return []
            if "geo_analysis_metrics" in query:
                return []
            return []

    async def fake_contract(*args, **kwargs):
        return None, None

    async def fake_template_config(*args, **kwargs):
        return {}

    async def fake_brand_context(*args, **kwargs):
        return {"brand_name": "Dreamina", "own_brands": [{"brand_name": "Dreamina"}]}

    async def fake_workflow_rows(*args, **kwargs):
        return []

    async def fail_resolve_model(*args, **kwargs):
        raise AssertionError("strategy model should not be resolved when existing strategy is reused")

    async def fail_llm_json(*args, **kwargs):
        raise AssertionError("LLM strategy generation should not run when existing strategy is reused")

    async def noop_status(*args, **kwargs):
        return None

    monkeypatch.setattr(content_pipeline, "get_contract_for_task", fake_contract)
    monkeypatch.setattr(content_pipeline, "_load_template_runtime_config", fake_template_config)
    monkeypatch.setattr(content_pipeline, "_load_content_brand_context", fake_brand_context)
    monkeypatch.setattr(content_pipeline, "load_workflow_dictionary_rows", fake_workflow_rows)
    monkeypatch.setattr(content_pipeline, "_resolve_strategy_model_id", fail_resolve_model)
    monkeypatch.setattr(content_pipeline, "_llm_json", fail_llm_json)
    monkeypatch.setattr(content_pipeline, "append_status_log", noop_status)

    existing_strategy = {
        "strategies": [{"name": "Confirmed", "dimensions": {"instruction": "Use confirmed plan."}}],
        "strategy_summary": "Confirmed by wizard",
    }

    result = await content_pipeline.step_strategy_generation(
        StrategyPool(),
        "00000000-0000-0000-0000-000000000000",
        {
            "strategy": existing_strategy,
            "selected_metrics": ["answerability"],
            "selected_subgoals": [],
            "content_type": "official_website_article",
        },
        "00000000-0000-0000-0000-000000000000",
    )

    assert result["strategy"] == existing_strategy
    assert result["model_used"] is None


def test_build_platform_instruction_adds_reddit_rules():
    instruction = content_pipeline._build_platform_instruction(
        "reddit",
        {"platform_profile": "reddit"},
    )

    assert "Reddit 发布适配" in instruction
    assert "硬广" in instruction
    assert "真实讨论帖" in instruction


def test_build_platform_instruction_prefers_template_playbook_over_reddit_fallback():
    instruction = content_pipeline._build_platform_instruction(
        "reddit",
        {
            "platform_profile": "reddit",
            "platform_playbook": {
                "content_rules": [
                    "Use natural community language.",
                    "Do not use Markdown tables.",
                ],
            },
        },
    )

    assert "平台适配规则（来自模板配置）" in instruction
    assert "Do not use Markdown tables." in instruction
    assert "Reddit 发布适配" not in instruction
    assert "对比表" not in instruction


def test_build_depth_instruction_uses_template_profile():
    instruction = content_pipeline._build_depth_instruction(
        "authority",
        {
            "depth_profiles": {
                "authority": {
                    "label": "Comprehensive",
                    "word_count": "2200+ words",
                },
            },
        },
    )

    assert "来自模板配置" in instruction
    assert "2200+ words" in instruction
    assert "Comprehensive" in instruction


def test_build_template_instruction_includes_default_prompt_and_requirements():
    instruction = content_pipeline._build_template_instruction(
        {
            "default_prompt": "Use prompt-first official website source rules.",
            "generation_requirements": {
                "prompt_first_source_policy": "Official URLs are diagnostics only.",
            },
        }
    )

    assert "模板默认指令" in instruction
    assert "Use prompt-first official website source rules." in instruction
    assert "模板补充要求" in instruction
    assert "Official URLs are diagnostics only." in instruction


def test_resolve_content_token_budget_is_depth_aware_for_longform():
    assert content_pipeline._resolve_content_token_budget("reddit_article", "standard") == 8192
    assert content_pipeline._resolve_content_token_budget("reddit_article", "deep") == 12288
    assert content_pipeline._resolve_content_token_budget("reddit_article", "authority") == 16384
    assert content_pipeline._resolve_content_token_budget("official_website_article", "authority") == 16384


def test_resolve_content_token_budget_preserves_short_content_types():
    assert content_pipeline._resolve_content_token_budget("faq", "authority") == 4096
    assert content_pipeline._resolve_content_token_budget("brief", "deep") == 4096


def test_should_use_segmented_generation_for_deep_longform_only():
    assert content_pipeline._should_use_segmented_generation("reddit_article", "deep") is True
    assert content_pipeline._should_use_segmented_generation("article", "authority") is True
    assert content_pipeline._should_use_segmented_generation("official_website_article", "authority") is True
    assert content_pipeline._should_use_segmented_generation("reddit_article", "standard") is False
    assert content_pipeline._should_use_segmented_generation("faq", "authority") is False


def test_should_use_report_segmented_generation_for_deep_recommendations():
    assert content_pipeline._should_use_report_segmented_generation("recommendations", "deep") is True
    assert content_pipeline._should_use_report_segmented_generation("recommendations", "authority") is True
    assert content_pipeline._should_use_report_segmented_generation("recommendations", "standard") is False
    assert content_pipeline._should_use_report_segmented_generation("brief", "authority") is False


def test_segmented_generation_plan_uses_outline_budget_large_enough_for_longform_json():
    deep_plan = content_pipeline._segmented_generation_plan("deep")
    authority_plan = content_pipeline._segmented_generation_plan("authority")

    assert deep_plan["outline_tokens"] >= 6144
    assert authority_plan["outline_tokens"] >= 8192


def test_json_error_looks_truncated_detects_unterminated_string():
    bad_json = '{"sections": [{"heading": "This string never closes'
    err = None
    try:
        content_pipeline.json.loads(bad_json)
    except Exception as exc:
        err = exc

    assert err is not None
    assert content_pipeline._json_error_looks_truncated(err, bad_json) is True


@pytest.mark.asyncio
async def test_llm_json_retries_truncated_json_with_larger_token_budget(monkeypatch):
    class Response:
        def __init__(self, text):
            self.text = text

    class FakeModels:
        def __init__(self):
            self.max_tokens_seen = []

        async def generate_content(self, model, contents, config):
            self.max_tokens_seen.append(config.max_output_tokens)
            if len(self.max_tokens_seen) == 1:
                return Response('{"sections": [{"heading": "unfinished')
            return Response('{"sections": [{"heading": "finished"}]}')

    class FakeClient:
        def __init__(self):
            self.models = FakeModels()
            self.aio = self

    async def noop_sleep(*args, **kwargs):
        return None

    fake_client = FakeClient()
    monkeypatch.setattr(content_pipeline.asyncio, "sleep", noop_sleep)

    result = await content_pipeline._llm_json(
        fake_client,
        "gemini-test",
        "prompt",
        "content_outline_generation",
        max_tokens=4096,
    )

    assert result["sections"][0]["heading"] == "finished"
    assert fake_client.models.max_tokens_seen == [4096, 8192]


def test_assemble_segmented_markdown_preserves_outline_order():
    outline = {
        "title": "How small teams use AI video tools",
        "intro_brief": "Open with the decision context.",
        "sections": [
            {"id": "s1", "heading": "Start with campaign goals"},
            {"id": "s2", "heading": "Compare production tradeoffs"},
        ],
        "faq": [
            {"question": "Can small teams use AI video tools?"},
        ],
        "conclusion_brief": "Close with a practical recommendation.",
    }
    sections = {
        "s1": "## Start with campaign goals\n\nSection one body.",
        "s2": "## Compare production tradeoffs\n\nSection two body.",
    }
    faq = "## Frequently Asked Questions\n\n### Can small teams use AI video tools?\n\nYes."
    conclusion = "## Conclusion\n\nChoose the workflow that fits your campaign."

    markdown = content_pipeline._assemble_segmented_markdown(
        outline=outline,
        intro="Small teams need speed without losing brand control.",
        section_markdowns=sections,
        faq_markdown=faq,
        conclusion_markdown=conclusion,
    )

    assert markdown.index("# How small teams use AI video tools") < markdown.index("## Start with campaign goals")
    assert markdown.index("## Start with campaign goals") < markdown.index("## Compare production tradeoffs")
    assert markdown.index("## Compare production tradeoffs") < markdown.index("## Frequently Asked Questions")
    assert markdown.endswith("Choose the workflow that fits your campaign.")


def test_assemble_segmented_report_markdown_preserves_report_order():
    outline = {
        "title": "Content Optimization Recommendations",
        "executive_summary_brief": "Summarize the core diagnosis.",
        "findings": [
            {"id": "f1", "heading": "Weak answer coverage"},
            {"id": "f2", "heading": "Low verifiability signals"},
        ],
        "action_plan_brief": "Prioritize the next actions.",
        "review_brief": "Close with implementation guardrails.",
    }
    findings = {
        "f1": "## Weak answer coverage\n\nFinding one body.",
        "f2": "## Low verifiability signals\n\nFinding two body.",
    }

    markdown = content_pipeline._assemble_segmented_report_markdown(
        outline=outline,
        executive_summary="The client needs stronger answer-ready content.",
        finding_markdowns=findings,
        action_plan_markdown="## Prioritized Actions\n\n1. Rewrite the core answer pages.",
        review_markdown="## Final Review\n\nThe plan is coherent and practical.",
    )

    assert markdown.index("# Content Optimization Recommendations") < markdown.index("## Executive Summary")
    assert markdown.index("## Executive Summary") < markdown.index("## Weak answer coverage")
    assert markdown.index("## Weak answer coverage") < markdown.index("## Low verifiability signals")
    assert markdown.index("## Low verifiability signals") < markdown.index("## Prioritized Actions")
    assert markdown.endswith("The plan is coherent and practical.")


def test_build_reddit_discovery_instruction_uses_ready_data():
    instruction = content_pipeline._build_reddit_discovery_instruction(
        {
            "status": "ready",
            "data": {
                "summary": "Users are skeptical of AI video quality.",
                "objections": ["Looks generic"],
            },
        }
    )

    assert "Reddit Discover Insight" in instruction
    assert "Looks generic" in instruction


def test_build_official_website_discovery_instruction_uses_ready_data():
    instruction = content_pipeline._build_official_website_discovery_instruction(
        {
            "status": "ready",
            "data": {
                "summary": "Official content lacks use-case comparison sections.",
                "content_gaps": ["No Dreamina product-video workflow page"],
            },
        }
    )

    assert "Official Website Discover Insight" in instruction
    assert "No Dreamina product-video workflow page" in instruction


def test_build_official_publishable_resource_policy_injects_generation_contract():
    policy = content_pipeline._build_official_publishable_resource_policy(
        "official_website_article",
        "official_site",
        {
            "resource_link_policy": {
                "enabled": True,
                "apply_to_content_types": ["official_website_article"],
                "prompt_title": "Publishable-only Resource Policy（官网文章硬约束）",
                "generation_rules": [
                    "禁止输出以下字段或措辞：Anchor Text、Destination、Target Page、Internal Linking Suggestions。",
                    "Helpful Resources 只能引用 Official Website Discovery 已验证过的真实、精确 URL；同一个 owned domain 下未发现的路径也不能使用。",
                    "Citation Analysis sources 只能用于学习结构；不要默认把 Citation source URL 放进正文 Helpful Resources。",
                    "不要编造外部 destination。",
                ],
                "no_verified_urls_instruction": "未识别到 Official Website Discovery 验证过的精确 URL；不要生成独立 Helpful Resources 外链列表。",
            }
        },
        {"brand_name": "Dreamina"},
        {
            "status": "ready",
            "data": {
                "pages": [
                    {
                        "title": "What is text-to-video AI?",
                        "url": "https://dreamina.capcut.com/ai-video/what-is-text-to-video",
                        "canonical_url": "https://dreamina.capcut.com/ai-video/what-is-text-to-video/",
                    }
                ],
            },
            "official_website_urls": "https://dreamina.capcut.com/not-verified",
        },
    )

    assert "Publishable-only Resource Policy" in policy
    assert "Anchor Text" in policy
    assert "Destination" in policy
    assert "Target Page" in policy
    assert "Internal Linking Suggestions" in policy
    assert "真实、精确 URL" in policy
    assert "不要编造" in policy
    assert "Citation Analysis sources 只能用于学习结构" in policy
    assert "dreamina.capcut.com" in policy
    assert "https://dreamina.capcut.com/ai-video/what-is-text-to-video" in policy
    assert "not-verified" not in policy


def test_verified_resource_pool_uses_only_official_discovery_result_urls():
    pool = content_pipeline._verified_resource_pool_from_official_discovery(
        {
            "status": "ready",
            "official_website_urls": "https://answer-x.ai/unverified-input-only",
            "data": {
                "home": {
                    "title": "AnswerX GEO",
                    "url": "https://answer-x.ai/",
                    "canonical_url": "https://answer-x.ai",
                },
                "pages": [
                    {
                        "page_title": "GEO Keyword Research",
                        "url": "https://answer-x.ai/resources/geo-keyword-research",
                    },
                    {
                        "title": "Bad citation source",
                        "url": "https://example.com/citation-source",
                    },
                ],
            },
        }
    )

    urls = {item["url"] for item in pool}
    assert "https://answer-x.ai" in urls
    assert "https://answer-x.ai/resources/geo-keyword-research" in urls
    assert "https://answer-x.ai/unverified-input-only" not in urls
    assert "https://example.com/citation-source" in urls


def test_sanitize_helpful_resources_keeps_only_verified_exact_links():
    content = """# GEO Content Guide

## Helpful Resources

- [Verified guide](https://answer-x.ai/resources/geo-keyword-research)
- [Hallucinated same-domain guide](https://answer-x.ai/resources/fake-playbook)
- [Competitor guide](https://example.com/citation-source)

## FAQ

Useful answer.
"""

    sanitized, policy = content_pipeline._sanitize_official_helpful_resources_to_verified_pool(
        content,
        content_type="official_website_article",
        publish_platform="official_site",
        template_config={
            "resource_link_policy": {
                "enabled": True,
                "apply_to_content_types": ["official_website_article"],
                "section_headings": ["Helpful Resources"],
                "output_heading": "Helpful Resources",
            }
        },
        official_website_discovery={
            "status": "ready",
            "data": {
                "pages": [
                    {
                        "title": "GEO Keyword Research",
                        "url": "https://answer-x.ai/resources/geo-keyword-research",
                    }
                ],
            },
        },
    )

    assert "[Verified guide](https://answer-x.ai/resources/geo-keyword-research)" in sanitized
    assert "fake-playbook" not in sanitized
    assert "example.com/citation-source" not in sanitized
    assert "## FAQ" in sanitized
    assert policy["removed_links"]
    assert policy["kept_links"][0]["url"] == "https://answer-x.ai/resources/geo-keyword-research"


def test_sanitize_helpful_resources_removes_section_when_no_verified_links():
    content = """# GEO Content Guide

## Helpful Resources

- [Hallucinated same-domain guide](https://answer-x.ai/resources/fake-playbook)

## FAQ

Useful answer.
"""

    sanitized, policy = content_pipeline._sanitize_official_helpful_resources_to_verified_pool(
        content,
        content_type="official_website_article",
        publish_platform="official_site",
        template_config={
            "resource_link_policy": {
                "enabled": True,
                "apply_to_content_types": ["official_website_article"],
                "section_headings": ["Helpful Resources"],
            }
        },
        official_website_discovery={"status": "ready", "data": {"pages": []}},
    )

    assert "## Helpful Resources" not in sanitized
    assert "fake-playbook" not in sanitized
    assert "## FAQ" in sanitized
    assert policy["removed_links"]


def test_build_official_publishable_resource_policy_skips_reddit():
    policy = content_pipeline._build_official_publishable_resource_policy(
        "reddit_article",
        "reddit",
        {"platform_profile": "reddit"},
    )

    assert policy == ""


def test_official_helpful_resource_policy_requires_exact_verified_links():
    content = """# AI Video Generator for Instagram Reels

## Helpful Resources for Instagram Creators

- [Dreamina text-to-video guide](https://dreamina.capcut.com/ai-video/what-is-text-to-video)
- [Dreamina official site](https://dreaminai.net/)
- [Same domain hallucinated guide](https://dreamina.capcut.com/ai-video/fake-guide)
"""

    result = content_pipeline._evaluate_official_helpful_resource_link_policy(
        content,
        content_type="official_website_article",
        publish_platform="official_site",
        brand_context={
            "brand_name": "Dreamina",
            "owned_domains": ["dreaminai.net", "dreamina.capcut.com"],
        },
        official_website_discovery={
            "status": "ready",
            "data": {
                "pages": [
                    {"url": "https://dreamina.capcut.com/ai-video/what-is-text-to-video"},
                    {"url": "https://dreaminai.net/"},
                ],
            },
        },
        template_config={
            "resource_link_policy": {
                "enabled": True,
                "apply_to_content_types": ["official_website_article"],
                "section_headings": ["Helpful Resources"],
            }
        },
    )

    assert result["ok"] is False
    assert [link["url"] for link in result["failures"]] == ["https://dreamina.capcut.com/ai-video/fake-guide"]
    assert all(link["url"] != "https://dreamina.capcut.com/ai-video/what-is-text-to-video" for link in result["failures"])
    assert all(link["url"] != "https://dreaminai.net/" for link in result["failures"])


def test_official_resource_policy_can_require_all_markdown_links_verified():
    content = """# AI Video Generator for Instagram Reels

Use the [social media guide](https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator).
Do not keep [root domain fallback](https://dreamina.capcut.com).
"""

    result = content_pipeline._evaluate_official_helpful_resource_link_policy(
        content,
        content_type="official_website_article",
        publish_platform="official_site",
        official_website_discovery={
            "status": "ready",
            "data": {
                "pages": [
                    {"url": "https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator"},
                ],
            },
        },
        template_config={
            "resource_link_policy": {
                "enabled": True,
                "apply_to_content_types": ["official_website_article"],
                "link_scope": "all_markdown_links",
            }
        },
    )

    assert result["ok"] is False
    assert [link["url"] for link in result["failures"]] == ["https://dreamina.capcut.com"]


def test_sanitize_official_all_markdown_links_unwraps_unverified_inline_links():
    content = """# AI Video Generator for Instagram Reels

Use the [social media guide](https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator).
Do not keep [root domain fallback](https://dreamina.capcut.com).
"""

    sanitized, policy = content_pipeline._sanitize_official_helpful_resources_to_verified_pool(
        content,
        content_type="official_website_article",
        publish_platform="official_site",
        template_config={
            "resource_link_policy": {
                "enabled": True,
                "apply_to_content_types": ["official_website_article"],
                "link_scope": "all_markdown_links",
                "sanitize_inline_markdown_links": True,
            }
        },
        official_website_discovery={
            "status": "ready",
            "data": {
                "pages": [
                    {"url": "https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator"},
                ],
            },
        },
    )

    assert "[social media guide](https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator)" in sanitized
    assert "[root domain fallback](https://dreamina.capcut.com)" not in sanitized
    assert "root domain fallback" in sanitized
    assert policy["removed_links"][0]["url"] == "https://dreamina.capcut.com"


def test_official_helpful_resource_policy_blocks_unverified_neutral_authority_links():
    content = """# AI Video Generator for Instagram Reels

## Helpful Resources

- [Instagram creators help](https://help.instagram.com/12345)
"""

    result = content_pipeline._evaluate_official_helpful_resource_link_policy(
        content,
        content_type="official_website_article",
        publish_platform="official_site",
        brand_context={"brand_name": "Dreamina"},
        template_config={
            "resource_link_policy": {
                "enabled": True,
                "apply_to_content_types": ["official_website_article"],
                "section_headings": ["Helpful Resources"],
            }
        },
    )

    assert result["ok"] is False
    assert result["failures"][0]["domain"] == "help.instagram.com"
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_post_revision_quality_review_reruns_helpful_resource_policy():
    final_review = await content_pipeline._build_post_revision_quality_review(
        revised_content="""# GEO Guide

Dreamina helps creators.

## Helpful Resources

- [Fake same-domain resource](https://answer-x.ai/resources/fake)
""",
        pre_revision_review={
            "overall_score": 8,
            "issues": [],
            "quality_gate": {"enabled": True, "status": "failed", "passed": False},
        },
        quality_gate_config={"enabled": True},
        metric_defs=[],
        include_data_disclosure=False,
        brand_context={"brand_name": "AnswerX", "owned_domains": ["answer-x.ai"]},
        content_type="official_website_article",
        publish_platform="official_site",
        citation_analysis_result=None,
        official_website_discovery={
            "status": "ready",
            "data": {"pages": [{"url": "https://answer-x.ai/resources/real"}]},
        },
        resource_link_policy_config={
            "enabled": True,
            "apply_to_content_types": ["official_website_article"],
            "section_headings": ["Helpful Resources"],
            "quality_gate_rule": {
                "id": "official_helpful_resources_unverified_links",
                "type": "official_resource_link_policy",
                "message": "Helpful Resources contains links outside the verified official discovery URL pool.",
            },
        },
    )

    gate = final_review["quality_gate"]
    assert gate["passed"] is False
    assert final_review["helpful_resource_link_policy"]["ok"] is False
    assert any(
        failure["rule_id"] == "official_helpful_resources_unverified_links"
        for failure in gate["failures"]
    )


@pytest.mark.asyncio
async def test_post_revision_quality_review_blocks_dropping_verified_markdown_links():
    final_review = await content_pipeline._build_post_revision_quality_review(
        revised_content="""# GEO Guide

Dreamina helps creators with social media video workflows.
""",
        pre_revision_review={
            "overall_score": 8,
            "issues": [],
            "quality_gate": {"enabled": True, "status": "failed", "passed": False},
            "helpful_resource_link_policy": {
                "required": True,
                "ok": True,
                "links": [
                    {
                        "label": "Dreamina workflow guide",
                        "url": "https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator",
                        "normalized_url": "https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator",
                        "domain": "dreamina.capcut.com",
                    }
                ],
            },
        },
        quality_gate_config={"enabled": True},
        metric_defs=[],
        include_data_disclosure=False,
        brand_context={"brand_name": "Dreamina", "owned_domains": ["dreamina.capcut.com"]},
        content_type="official_website_article",
        publish_platform="official_site",
        citation_analysis_result=None,
        official_website_discovery={
            "status": "ready",
            "data": {
                "pages": [
                    {
                        "url": "https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator"
                    }
                ]
            },
        },
        resource_link_policy_config={
            "enabled": True,
            "apply_to_content_types": ["official_website_article"],
            "link_scope": "all_markdown_links",
            "preserve_verified_markdown_links": True,
            "verified_link_preservation_rule": {
                "id": "official_verified_links_dropped",
                "type": "official_resource_link_policy",
                "message": "Verified Markdown links were removed during revision.",
            },
        },
    )

    gate = final_review["quality_gate"]
    assert gate["passed"] is False
    assert final_review["verified_link_preservation"]["ok"] is False
    assert final_review["verified_link_preservation"]["missing_links"][0]["url"] == (
        "https://dreamina.capcut.com/ai-video/social-media-content-with-ai-video-generator"
    )
    assert any(
        failure["rule_id"] == "official_verified_links_dropped"
        for failure in gate["failures"]
    )


def test_run_configured_quality_gate_flags_official_site_missing_sections_and_hype():
    content = """# The Best AI Video Generator

Dreamina is the ultimate AI video solution for Instagram creators. It guarantees viral-ready Reels.

## Feature-to-Benefit Mapping

| Feature | Benefit |
| --- | --- |
| 9:16 | Vertical clips |

## FAQ

### Is Dreamina useful?

Yes.
"""

    result = content_pipeline._run_configured_quality_gate(
        content,
        {
            "enabled": True,
            "rules": [
                {
                    "id": "brand_fit",
                    "type": "required_heading",
                    "severity": "blocker",
                    "any_of": ["Brand Fit Summary", "Where Dreamina fits"],
                },
                {
                    "id": "internal_links",
                    "type": "required_heading",
                    "severity": "blocker",
                    "any_of": ["Internal Linking Suggestions"],
                },
                {
                    "id": "hype_terms",
                    "type": "forbidden_terms",
                    "severity": "warning",
                    "terms": ["ultimate", "guarantees", "viral-ready"],
                },
            ],
        },
    )

    assert result["enabled"] is True
    assert result["passed"] is False
    assert result["failure_count"] == 2
    assert result["warning_count"] == 1
    assert result["score_cap"] == 6.0
    assert {f["rule_id"] for f in result["failures"]} == {"brand_fit", "internal_links"}


def test_run_configured_quality_gate_flags_reddit_duplicate_tldr_and_fake_benchmark():
    content = """# I tested every major AI video tool

TL;DR: Dreamina is useful in some workflows.

## TL;DR & Reality Check

I spent 30 days testing every major AI video generator with a master spreadsheet.

## Where Dreamina fits

Dreamina fits creators who need quick B-roll, but it is not a full editor.
"""

    result = content_pipeline._run_configured_quality_gate(
        content,
        {
            "enabled": True,
            "rules": [
                {
                    "id": "single_tldr",
                    "type": "max_occurrences",
                    "severity": "blocker",
                    "pattern": "TL;DR",
                    "max": 1,
                },
                {
                    "id": "fake_benchmark",
                    "type": "forbidden_patterns",
                    "severity": "blocker",
                    "patterns": ["I spent \\d+ days testing", "master spreadsheet"],
                },
            ],
        },
    )

    assert result["passed"] is False
    assert result["failure_count"] == 2
    assert result["score_cap"] == 6.0


def test_quality_gate_allows_reddit_experience_voice_but_blocks_fake_benchmarks():
    gate = {
        "enabled": True,
        "rules": [
            {
                "id": "reddit_unverifiable_specific_experience_forbidden",
                "type": "forbidden_patterns",
                "severity": "blocker",
                "patterns": [
                    "\\bI\\s+(?:tested|benchmarked)\\s+\\d+\\b",
                    "\\bI\\s+spent\\s+\\d+\\s+(?:days|weeks|months)\\b",
                    "\\bmy\\s+results\\b",
                ],
            }
        ],
    }

    allowed = content_pipeline._run_configured_quality_gate(
        "I've been trying to scale daily clips, and the workflow problem is cost-per-clip.",
        gate,
    )
    blocked = content_pipeline._run_configured_quality_gate(
        "I tested 14 AI video tools for 30 days and my results prove this is best.",
        gate,
    )

    assert allowed["passed"] is True
    assert blocked["passed"] is False
    assert blocked["failures"][0]["rule_id"] == "reddit_unverifiable_specific_experience_forbidden"


def test_apply_quality_gate_score_cap_lowers_overgenerous_review_score():
    review = {"overall_score": 9.5, "issues": []}
    gated = content_pipeline._apply_quality_gate_to_review(
        review,
        {
            "enabled": True,
            "passed": False,
            "score_cap": 6.0,
            "failures": [
                {
                    "rule_id": "brand_fit",
                    "message": "Missing required heading.",
                    "severity": "blocker",
                }
            ],
            "warnings": [],
        },
    )

    assert gated["overall_score"] == 6.0
    assert gated["quality_gate"]["passed"] is False
    assert any("Quality Gate blocker" in issue for issue in gated["issues"])


def test_quality_gate_v2_score_below_threshold_requires_revise():
    review = {"overall_score": 7.6, "issues": []}
    gated = content_pipeline._apply_quality_gate_to_review(
        review,
        {
            "enabled": True,
            "passed": True,
            "score_cap": 10.0,
            "failures": [],
            "warnings": [],
            "failure_count": 0,
            "warning_count": 0,
        },
        {
            "min_overall_score": 8.0,
            "revise_below_score": True,
        },
    )

    quality_gate = gated["quality_gate"]
    assert quality_gate["passed"] is False
    assert quality_gate["revise_required"] is True
    assert quality_gate["status"] == "failed"
    assert any(f["rule_id"] == "overall_score_below_threshold" for f in quality_gate["failures"])


def test_quality_gate_v2_llm_issue_patterns_upgrade_to_blockers():
    review = {
        "overall_score": 8.8,
        "issues": [
            "检测到重复段落或重复结尾，请压缩重复内容并保留一个清晰收束。",
            "第 84 行疑似残缺或未完成句：Before hitting publish...",
        ],
    }
    gated = content_pipeline._apply_quality_gate_to_review(
        review,
        {
            "enabled": True,
            "passed": True,
            "score_cap": 10.0,
            "failures": [],
            "warnings": [],
            "failure_count": 0,
            "warning_count": 0,
        },
        {
            "llm_issue_blocker_patterns": ["重复结尾", "重复 FAQ", "残缺", "未完成句", "结构性错误"],
        },
    )

    quality_gate = gated["quality_gate"]
    assert quality_gate["passed"] is False
    assert quality_gate["revise_required"] is True
    assert {f["rule_id"] for f in quality_gate["failures"]} == {
        "llm_issue_blocker:重复结尾",
        "llm_issue_blocker:残缺",
        "llm_issue_blocker:未完成句",
    }


def test_quality_gate_v2_detects_heading_structure_warnings():
    content = """# Draft

## Direct Answer: Which AI Video Tool Fits Instagram Creators?

Intro.

## Direct Answer: Which AI Video Tool Fits Instagram Creators?

Duplicate intro.

## Frequently Asked Questions

FAQ one.

## FAQ

FAQ two.

## Final thoughts

Almost done.

## Conclusion

Done.
"""
    result = content_pipeline._run_configured_quality_gate(
        content,
        {
            "enabled": True,
            "rules": [
                {"id": "duplicate_h2_heading", "type": "duplicate_heading", "level": 2, "severity": "warning"},
                {
                    "id": "multiple_faq_sections",
                    "type": "max_heading_occurrences",
                    "severity": "warning",
                    "heading_patterns": ["FAQ", "Frequently Asked Questions"],
                    "max": 1,
                },
                {
                    "id": "final_thoughts_and_conclusion",
                    "type": "cooccurring_headings",
                    "severity": "warning",
                    "heading_patterns": ["Final thoughts", "Conclusion"],
                },
                {
                    "id": "duplicate_direct_answer",
                    "type": "max_heading_occurrences",
                    "severity": "warning",
                    "heading_patterns": ["Direct Answer"],
                    "max": 1,
                },
            ],
        },
    )

    assert result["passed"] is True
    assert result["warning_count"] == 4
    assert {w["rule_id"] for w in result["warnings"]} == {
        "duplicate_h2_heading",
        "multiple_faq_sections",
        "final_thoughts_and_conclusion",
        "duplicate_direct_answer",
    }
    assert result["status"] == "pass_with_warnings"


def test_quality_gate_v2_configured_warning_ids_require_revise():
    gated = content_pipeline._apply_quality_gate_to_review(
        {"overall_score": 8.6, "issues": []},
        {
            "enabled": True,
            "passed": True,
            "score_cap": 8.0,
            "failures": [],
            "warnings": [
                {
                    "rule_id": "multiple_faq_sections",
                    "message": "Multiple FAQ sections found.",
                    "severity": "warning",
                }
            ],
            "failure_count": 0,
            "warning_count": 1,
        },
        {
            "revise_on_warning_rule_ids": ["multiple_faq_sections"],
        },
    )

    quality_gate = gated["quality_gate"]
    assert quality_gate["passed"] is True
    assert quality_gate["status"] == "pass_with_warnings"
    assert quality_gate["revise_required"] is True
    assert "warning_rule_requires_revise:multiple_faq_sections" in quality_gate["triggers"]


def test_quality_gate_v2_citation_alignment_can_require_revise():
    gated = content_pipeline._apply_quality_gate_to_review(
        {
            "overall_score": 8.7,
            "issues": ["内容未明显响应 Citation Analysis 的 primary_action=new_content_gap；需要围绕该动作补充结构或措辞。"],
            "citation_alignment": {
                "required": True,
                "ok": False,
                "primary_action": "new_content_gap",
            },
        },
        {
            "enabled": True,
            "passed": True,
            "score_cap": 10.0,
            "failures": [],
            "warnings": [],
            "failure_count": 0,
            "warning_count": 0,
        },
        {
            "citation_alignment_as_blocker": True,
        },
    )

    quality_gate = gated["quality_gate"]
    assert quality_gate["passed"] is False
    assert quality_gate["revise_required"] is True
    assert any(f["rule_id"] == "citation_alignment_failed" for f in quality_gate["failures"])


def test_evaluate_citation_alignment_uses_configured_markers():
    citation_result = {
        "enabled": True,
        "content_action_decision": {"primary_action": "new_content_gap"},
        "source_count": 3,
        "brand_mention_summary": {"unmentioned": 3},
    }
    content = "## AI-citable structure\n\nThis article fills a missing citation gap with a direct answer."

    result = content_pipeline._evaluate_citation_alignment(
        content,
        citation_result,
        {
            "citation_alignment_markers": {
                "new_content_gap": ["citation gap", "missing coverage"]
            }
        },
    )

    assert result["required"] is True
    assert result["ok"] is True
    assert result["matched_markers"] == ["citation gap"]


def test_merge_citation_alignment_llm_review_can_override_keyword_pass():
    base = {
        "required": True,
        "ok": True,
        "primary_action": "clarification_rebuttal",
        "matched_markers": ["comparison"],
    }
    merged = content_pipeline._merge_citation_alignment_llm_review(
        base,
        {
            "ok": False,
            "reason": "The article says comparison but does not correct the misleading cited claim.",
            "missing_actions": ["clarify the cited misconception"],
        },
        mode="hybrid",
    )

    assert merged["ok"] is False
    assert merged["llm_review"]["ok"] is False
    assert "clarify the cited misconception" in merged["llm_review"]["missing_actions"]


def test_quality_gate_v2_marks_revised_and_needs_human_review_statuses():
    revised = content_pipeline._mark_quality_gate_after_revision(
        {
            "enabled": True,
            "passed": True,
            "failures": [],
            "warnings": [],
            "failure_count": 0,
            "warning_count": 0,
            "score_cap": 10.0,
        }
    )
    needs_review = content_pipeline._mark_quality_gate_after_revision(
        {
            "enabled": True,
            "passed": False,
            "failures": [{"rule_id": "still_bad", "severity": "blocker"}],
            "warnings": [],
            "failure_count": 1,
            "warning_count": 0,
            "score_cap": 6.0,
        }
    )

    assert revised["status"] == "revised"
    assert revised["revise_required"] is False
    assert needs_review["status"] == "needs_human_review"
    assert needs_review["human_review_required"] is True


def test_build_topic_context_instruction_uses_topics_and_prompt_topics():
    instruction = content_pipeline._build_topic_context_instruction(
        topics=[{"topic_name": "AI video", "topic_type": "semantic_topic"}],
        prompt_texts=[
            {
                "text": "What AI video tool is best for Instagram Reels?",
                "topic_name": "AI video",
                "product": "Dreamina",
            }
        ],
    )

    assert "当前 Topic / 监控主题" in instruction
    assert "AI video" in instruction
    assert "Dreamina" in instruction
