# Reddit Native Content Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a configuration-driven Reddit-native content generation path that transforms raw analysis artifacts into Community Brief and Experience Style Notes before final drafting, while preserving legacy behavior for non-Reddit templates.

**Architecture:** Keep the existing five-step content pipeline. Add generic prompt-artifact preparation and template-driven prompt rendering controls. Reddit templates opt into the new behavior through `geo_report_templates.wizard_config`; Official Website and other templates default to existing raw prompt assembly.

**Tech Stack:** Python 3.11 FastAPI service in `geo_agent`, PostgreSQL JSONB migrations, existing Gemini generation helpers, existing template-configured Quality Gate, Admin React JSON config editor.

**Important constraint:** Do not run Git commands. The user has explicitly asked not to use Git in this workspace.

---

## File Map

- Modify `geo_agent/src/pipelines/content_pipeline.py`
  - Add generic helpers for template-driven prompt input policy, RATF rendering, derived prompt artifacts, Reddit-native prompt section assembly, and additional config-driven quality gate rule types.
  - Keep existing `CONTENT_V2_STEPS` stable unless a visible generic step is added; if a visible step is added, it must be generic and opt-in.
- Modify `geo_agent/src/routers/tasks.py`
  - Load new template config blocks into runtime config for previews and task execution.
- Modify `geo_agent/tests/test_content_pipeline_options.py`
  - Add focused unit tests for legacy stability, Reddit prompt assembly, RATF rendering, derived artifacts, and Quality Gate rules.
- Modify `geo_admin/web/src/components/WizardConfigEditor.tsx`
  - Add Advanced Template Config JSON fields for the new config blocks.
- Create `migrations/105_reddit_native_prompt_artifact_config.sql`
  - Upsert Reddit template config for `prompt_input_policy`, `ratf_rendering`, `reddit_native_contract`, `experience_style_notes`, `community_brief`, `derived_prompt_artifacts`, and additional Reddit Quality Gate rules.
  - Leave Official Website templates unchanged except for no-op-compatible defaults if required.

## Task 1: Runtime Config Loading

**Files:**
- Modify `geo_agent/src/pipelines/content_pipeline.py`
- Modify `geo_agent/src/routers/tasks.py`
- Test `geo_agent/tests/test_content_pipeline_options.py`

- [ ] **Step 1: Write failing test for new runtime config keys**

Add a test near `test_load_template_runtime_config_joins_text_template_id_to_uuid_safely`:

```python
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
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_load_template_runtime_config_includes_prompt_artifact_blocks -q
```

Expected: fail with missing runtime config keys.

- [ ] **Step 3: Implement runtime config loading**

In both `_load_template_runtime_config` implementations, add:

```python
"prompt_input_policy": wizard_config.get("prompt_input_policy") or defaults.get("prompt_input_policy") or {},
"ratf_rendering": wizard_config.get("ratf_rendering") or defaults.get("ratf_rendering") or {},
"reddit_native_contract": wizard_config.get("reddit_native_contract") or defaults.get("reddit_native_contract") or {},
"experience_style_notes": wizard_config.get("experience_style_notes") or defaults.get("experience_style_notes") or {},
"community_brief": wizard_config.get("community_brief") or defaults.get("community_brief") or {},
"derived_prompt_artifacts": wizard_config.get("derived_prompt_artifacts") or defaults.get("derived_prompt_artifacts") or {},
```

- [ ] **Step 4: Run the targeted test**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_load_template_runtime_config_includes_prompt_artifact_blocks -q
```

Expected: pass.

## Task 2: RATF Rendering Policy

**Files:**
- Modify `geo_agent/src/pipelines/content_pipeline.py`
- Test `geo_agent/tests/test_content_pipeline_options.py`

- [ ] **Step 1: Write failing tests for RATF rendering modes**

Add tests near existing RATF tests:

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_build_ratf_framework_block_can_hide_raw_subgoal_descriptions geo_agent/tests/test_content_pipeline_options.py::test_build_ratf_framework_block_legacy_includes_raw_subgoal_descriptions -q
```

Expected: first test fails because `_build_ratf_framework_block` does not accept `ratf_rendering`.

- [ ] **Step 3: Implement RATF rendering config**

Change signature:

```python
def _build_ratf_framework_block(
    metric_defs: list[dict[str, Any]],
    subgoal_defs: list[dict[str, Any]],
    metric_jobs: dict[str, Any] | None = None,
    ratf_rendering: dict[str, Any] | None = None,
) -> str:
```

Inside the function:

```python
ratf_rendering = ratf_rendering if isinstance(ratf_rendering, dict) else {}
include_subgoal_raw = ratf_rendering.get("include_subgoal_raw_descriptions", True)
subgoal_overrides = ratf_rendering.get("subgoal_overrides") if isinstance(ratf_rendering.get("subgoal_overrides"), dict) else {}
```

When rendering each subgoal:

```python
override = str(subgoal_overrides.get(sg.get("key", "")) or "").strip()
if override:
    lines.append(f"     - **{sg_label}** — {override}")
elif include_subgoal_raw:
    lines.append(f"     - **{sg_label}** — {sg_desc}")
else:
    lines.append(f"     - **{sg_label}**")
```

Update call site in `step_content_generation`:

```python
ratf_rendering = template_runtime_config.get("ratf_rendering")
ratf_block = _build_ratf_framework_block(
    metric_defs,
    subgoal_defs,
    ratf_metric_jobs if isinstance(ratf_metric_jobs, dict) else {},
    ratf_rendering if isinstance(ratf_rendering, dict) else {},
)
```

- [ ] **Step 4: Run RATF tests**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_build_ratf_framework_block_can_hide_raw_subgoal_descriptions geo_agent/tests/test_content_pipeline_options.py::test_build_ratf_framework_block_legacy_includes_raw_subgoal_descriptions -q
```

Expected: pass.

## Task 3: Derived Prompt Artifacts

**Files:**
- Modify `geo_agent/src/pipelines/content_pipeline.py`
- Test `geo_agent/tests/test_content_pipeline_options.py`

- [ ] **Step 1: Write failing tests for artifact derivation**

Add tests:

```python
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
            "experience_style_notes": {"enabled": True},
            "community_brief": {"enabled": True, "max_words": 500},
            "reddit_native_contract": {
                "voice_contract": {
                    "preferred_patterns": ["I've been testing...", "I still don't fully trust..."],
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

    assert "experience_style_notes" in artifacts
    assert "community_brief" in artifacts
    assert "writing-perspective scaffolding" in artifacts["experience_style_notes"]
    assert "community_tension" in artifacts["community_brief"]
    assert "short clip limits" in artifacts["community_brief"]
    assert "closing_discussion_question" in artifacts["community_brief"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_build_derived_prompt_artifacts_is_disabled_by_default geo_agent/tests/test_content_pipeline_options.py::test_build_derived_prompt_artifacts_creates_reddit_native_brief -q
```

Expected: fail because helper does not exist.

- [ ] **Step 3: Implement helper**

Add helpers near prompt assembly helpers:

```python
def _text_from_jsonish(value: Any, *, max_chars: int = 1200) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:max_chars]
    try:
        return json.dumps(value, ensure_ascii=False)[:max_chars]
    except Exception:
        return str(value)[:max_chars]


def _build_derived_prompt_artifacts(
    *,
    template_runtime_config: dict[str, Any],
    brand_context: dict[str, Any] | None,
    reddit_discovery: dict[str, Any] | None,
    official_website_discovery: dict[str, Any] | None,
    citation_analysis_result: dict[str, Any] | None,
    strategy: dict[str, Any] | None,
    prompt_texts: list[dict[str, Any]] | None,
) -> dict[str, str]:
    policy = template_runtime_config.get("prompt_input_policy")
    if not isinstance(policy, dict) or policy.get("mode") != "reddit_native":
        return {}

    experience_config = template_runtime_config.get("experience_style_notes")
    community_config = template_runtime_config.get("community_brief")
    contract = template_runtime_config.get("reddit_native_contract")
    experience_config = experience_config if isinstance(experience_config, dict) else {}
    community_config = community_config if isinstance(community_config, dict) else {}
    contract = contract if isinstance(contract, dict) else {}

    reddit_text = _text_from_jsonish(reddit_discovery)
    official_text = _text_from_jsonish(official_website_discovery)
    citation_text = _text_from_jsonish(citation_analysis_result)
    strategy_text = _text_from_jsonish(strategy)
    prompts_text = _text_from_jsonish(prompt_texts)
    brand_name = _extract_primary_brand_name(brand_context or {}) or "the brand"

    artifacts: dict[str, str] = {}
    if experience_config.get("enabled"):
        artifacts["experience_style_notes"] = "\n".join([
            "## Experience Style Notes（写作视角素材，不是事实声明）",
            "- These notes are writing-perspective scaffolding, not factual claims.",
            f"- Write as a practitioner discussing a workflow where {brand_name} may appear naturally as one tool in the stack.",
            "- Use cautious language: I've been testing, I still don't fully trust, what worked better for me.",
            "- Do not claim first-hand product benchmarks unless the input explicitly provides them.",
            f"- Reddit/Community signals: {reddit_text}",
            f"- Official-site context that can inform workflow texture: {official_text}",
            f"- Citation patterns to translate into user tensions: {citation_text}",
        ])

    if community_config.get("enabled"):
        artifacts["community_brief"] = "\n".join([
            "## Community Brief（Reddit 生成唯一上游摘要）",
            f"- community_tension: Translate this into a concrete Reddit workflow friction: {reddit_text or prompts_text}",
            f"- reader_objections: Pull objections from community and citation inputs: {citation_text}",
            f"- workflow_angle: Use the strategy only as raw material, not as section structure: {strategy_text}",
            f"- brand_safe_mention_angle: Mention {brand_name} only inside a workflow or tool stack, never as a standalone ad block.",
            f"- things_to_avoid: {json.dumps(contract.get('voice_contract', {}).get('forbidden_patterns', []), ensure_ascii=False)}",
            "- closing_discussion_question: End with a real question asking how other users handle the workflow.",
        ])

    return artifacts
```

This implementation is deterministic and config-driven. It does not call LLM yet. A later version can make artifact generation model-powered, but deterministic v1 is safer and testable.

- [ ] **Step 4: Run artifact tests**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_build_derived_prompt_artifacts_is_disabled_by_default geo_agent/tests/test_content_pipeline_options.py::test_build_derived_prompt_artifacts_creates_reddit_native_brief -q
```

Expected: pass.

## Task 4: Reddit-Native Prompt Assembly

**Files:**
- Modify `geo_agent/src/pipelines/content_pipeline.py`
- Test `geo_agent/tests/test_content_pipeline_options.py`

- [ ] **Step 1: Write failing test for prompt section policy**

Add test:

```python
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
            "experience_style_notes": "## Experience Style Notes\n- writing-perspective scaffolding",
            "community_brief": "## Community Brief\n- community_tension: short clip limits",
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
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_build_reddit_native_prompt_sections_hides_raw_internal_artifacts -q
```

Expected: fail because helper does not exist.

- [ ] **Step 3: Implement prompt section helper**

Add:

```python
def _build_reddit_native_contract_section(contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict) or not contract:
        return ""
    return "## Reddit Native Writing Contract（硬约束）\n" + json.dumps(contract, ensure_ascii=False, indent=2)


def _build_prompt_artifact_sections(
    *,
    template_runtime_config: dict[str, Any],
    derived_artifacts: dict[str, str],
    reddit_discovery_instruction: str,
    official_website_discovery_instruction: str,
    citation_analysis_instruction: str,
) -> str:
    policy = template_runtime_config.get("prompt_input_policy")
    policy = policy if isinstance(policy, dict) else {}
    if policy.get("mode") != "reddit_native":
        return "\n".join([
            reddit_discovery_instruction,
            official_website_discovery_instruction,
            citation_analysis_instruction,
        ])

    parts = []
    if derived_artifacts.get("experience_style_notes"):
        parts.append(derived_artifacts["experience_style_notes"])
    if derived_artifacts.get("community_brief"):
        parts.append(derived_artifacts["community_brief"])
    contract_section = _build_reddit_native_contract_section(
        template_runtime_config.get("reddit_native_contract")
    )
    if contract_section:
        parts.append(contract_section)
    return "\n".join(p for p in parts if p.strip())
```

- [ ] **Step 4: Wire into `step_content_generation`**

Before `context_prompt`, build derived artifacts:

```python
derived_prompt_artifacts = _build_derived_prompt_artifacts(
    template_runtime_config=template_runtime_config,
    brand_context=brand_context,
    reddit_discovery=reddit_discovery,
    official_website_discovery=official_website_discovery,
    citation_analysis_result=citation_analysis_result,
    strategy=strategy,
    prompt_texts=prompt_texts,
)
prompt_artifact_sections = _build_prompt_artifact_sections(
    template_runtime_config=template_runtime_config,
    derived_artifacts=derived_prompt_artifacts,
    reddit_discovery_instruction=reddit_discovery_instruction,
    official_website_discovery_instruction=official_website_discovery_instruction,
    citation_analysis_instruction=citation_analysis_instruction,
)
```

Replace this block inside `context_prompt`:

```python
{reddit_discovery_instruction}
{official_website_discovery_instruction}
{citation_analysis_instruction}
```

with:

```python
{prompt_artifact_sections}
```

Store metadata:

```python
generation_metadata["derived_prompt_artifacts"] = derived_prompt_artifacts
```

- [ ] **Step 5: Run prompt section test**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_build_reddit_native_prompt_sections_hides_raw_internal_artifacts -q
```

Expected: pass.

## Task 5: Strategy Dimensions Suppression for Reddit Native Mode

**Files:**
- Modify `geo_agent/src/pipelines/content_pipeline.py`
- Test `geo_agent/tests/test_content_pipeline_options.py`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_build_strategy_prompt_sections_can_suppress_raw_dimensions():
    section = content_pipeline._build_strategy_dimension_sections(
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

    assert "策略维度" not in section
    assert "Phase 1" not in section
```

- [ ] **Step 2: Implement strategy section helper**

Extract current `dimension_instructions`, `all_constraints`, and `all_enhancements` assembly into:

```python
def _build_strategy_dimension_sections(
    *,
    strategy: dict[str, Any],
    template_runtime_config: dict[str, Any],
) -> tuple[str, str, str]:
    policy = template_runtime_config.get("prompt_input_policy")
    if isinstance(policy, dict) and policy.get("mode") == "reddit_native":
        return "", "", ""
    # existing legacy assembly here
```

If keeping return type as string is simpler, return a dict:

```python
{
  "dimension_section": "...",
  "constraints_section": "...",
  "enhancements_section": "..."
}
```

Use this helper in `step_content_generation`. Legacy mode must produce the same text as before.

- [ ] **Step 3: Run the test**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_build_strategy_prompt_sections_can_suppress_raw_dimensions -q
```

Expected: pass.

## Task 6: Config-Driven Reddit Quality Rules

**Files:**
- Modify `geo_agent/src/pipelines/content_pipeline.py`
- Test `geo_agent/tests/test_content_pipeline_options.py`
- Create `migrations/105_reddit_native_prompt_artifact_config.sql`

- [ ] **Step 1: Add generic quality rule tests**

Add tests:

```python
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
```

- [ ] **Step 2: Implement generic rule types**

In `_run_configured_quality_gate`, add:

```python
elif rule_type == "first_paragraph_required_patterns":
    patterns = [str(p).strip() for p in (raw_rule.get("patterns") or []) if str(p).strip()]
    first_para = (text.strip().split("\n\n", 1)[0] if text.strip() else "")
    if patterns and not any(_re.search(p, first_para, flags=_re.IGNORECASE) for p in patterns):
        add_issue(_quality_gate_issue(
            rule=raw_rule,
            message=raw_rule.get("message") or "First paragraph did not match required patterns.",
            matches=[],
        ))

elif rule_type == "max_regex_count":
    pattern = str(raw_rule.get("pattern") or "").strip()
    max_count = int(raw_rule.get("max", 1))
    if pattern:
        count = len(_re.findall(pattern, text, flags=_re.IGNORECASE))
        if count > max_count:
            add_issue(_quality_gate_issue(
                rule=raw_rule,
                message=raw_rule.get("message") or f"Pattern {pattern!r} appears {count} times; maximum allowed is {max_count}.",
                matches=[pattern],
            ))
```

- [ ] **Step 3: Run quality rule tests**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py::test_quality_gate_first_paragraph_requires_configured_patterns geo_agent/tests/test_content_pipeline_options.py::test_quality_gate_brand_mentions_max_count -q
```

Expected: pass.

## Task 7: Admin Advanced Config Fields

**Files:**
- Modify `geo_admin/web/src/components/WizardConfigEditor.tsx`

- [ ] **Step 1: Add advanced config entries**

Add to `ADVANCED_CONFIG_FIELDS`:

```ts
{
    key: "prompt_input_policy",
    label: "Prompt Input Policy",
    description: "控制 raw artifacts 是否原样进入最终 Prompt，或先转成模板原生摘要。",
    rows: 8,
},
{
    key: "ratf_rendering",
    label: "RATF Rendering",
    description: "控制 RATF 指标和 Subgoal 在 Prompt 中的渲染方式。",
    rows: 7,
},
{
    key: "reddit_native_contract",
    label: "Reddit Native Contract",
    description: "Reddit 原生标题、开头、结构、语气、品牌提及和结尾约束。",
    rows: 10,
},
{
    key: "experience_style_notes",
    label: "Experience Style Notes",
    description: "基于 Discover/Citation 生成写作视角素材；不是事实声明。",
    rows: 7,
},
{
    key: "community_brief",
    label: "Community Brief",
    description: "Reddit 最终生成使用的社区摘要结构。",
    rows: 7,
},
{
    key: "derived_prompt_artifacts",
    label: "Derived Prompt Artifacts",
    description: "模板派生 Prompt Artifacts 的启用和审计配置。",
    rows: 7,
},
```

- [ ] **Step 2: Run Admin typecheck**

Run:

```bash
npm run typecheck
```

from `geo_admin/web`.

Expected: pass.

## Task 8: Data Migration

**Files:**
- Create `migrations/105_reddit_native_prompt_artifact_config.sql`

- [ ] **Step 1: Create migration with Reddit-only config**

Use this structure:

```sql
BEGIN;

WITH reddit_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%reddit%'
      OR defaults->>'content_type' = 'reddit_article'
      OR defaults->>'publish_platform' = 'reddit'
      OR wizard_config->>'platform_profile' = 'reddit'
    )
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            COALESCE(t.wizard_config, '{}'::jsonb),
            '{prompt_input_policy}',
            '{
              "mode": "reddit_native",
              "raw_artifact_policy": {
                "strategy_generation": "summarize_to_community_brief",
                "citation_analysis": "summarize_to_reader_tensions",
                "reddit_discover": "summarize_to_community_rules",
                "official_discover": "derive_experience_style_notes",
                "ratf_framework": "render_template_native"
              },
              "hide_internal_frameworks": true
            }'::jsonb,
            true
          ),
          '{ratf_rendering}',
          '{
            "mode": "template_native",
            "include_metric_jobs": true,
            "include_subgoal_raw_descriptions": false,
            "subgoal_overrides": {
              "information_presentation": "Use short paragraphs, lightweight bullets, concrete examples, and natural Reddit pacing. Do not use tables, matrices, or FAQ blocks."
            }
          }'::jsonb,
          true
        ),
        '{experience_style_notes}',
        '{
          "enabled": true,
          "sources": ["reddit_discover", "official_discover", "citation_analysis"],
          "fact_policy": "writing_perspective_only_not_factual_claims"
        }'::jsonb,
        true
      ),
      '{community_brief}',
      '{
        "enabled": true,
        "max_words": 500,
        "source_priority": ["subreddit_community_rules", "experience_style_notes", "reddit_discover", "citation_analysis", "selected_prompts"]
      }'::jsonb,
      true
    ),
    '{derived_prompt_artifacts}',
    '{
      "enabled": true,
      "visible_in_task_output": true
    }'::jsonb,
    true
  ),
  '{reddit_native_contract}',
  '{
    "opening_contract": {
      "required_shape": "first_person_workflow_or_testing_friction",
      "forbidden_openers": ["If you are trying to", "In 2026", "A question that comes up a lot", "The landscape is shifting"]
    },
    "structure_contract": {
      "forbidden_headings": ["Phase 1", "Step-by-Step", "Checklist", "The Reality Check", "Where [Brand] Fits", "Helpful Resources", "FAQ"]
    },
    "voice_contract": {
      "preferred_patterns": ["I''ve been testing", "What has worked better for me", "I still don''t fully trust", "The annoying part is"],
      "forbidden_patterns": ["consensus among creators", "brand-safe visual control", "platform-ready", "scroll-stopping", "high-volume creators", "industry-leading", "highly recommended"]
    },
    "brand_mention_contract": {
      "max_mentions": 2,
      "must_be_inside_workflow_or_tool_stack": true,
      "forbid_standalone_brand_section": true
    },
    "closing_contract": {
      "required_shape": "real_discussion_question",
      "forbidden_shape": "marketing_cta"
    }
  }'::jsonb,
  true
)
FROM reddit_templates
WHERE t.id = reddit_templates.id;

COMMIT;
```

- [ ] **Step 2: Add Reddit Quality Gate rules in same migration**

Use a second `UPDATE` that appends rules to `wizard_config.quality_gate.rules` while preserving existing rules. Include:

- `reddit_opening_first_person_required`
- `reddit_guide_headings_forbidden`
- `reddit_marketing_voice_forbidden`
- `reddit_brand_mentions_limited`

Use `jsonb_set` with:

```sql
COALESCE(t.wizard_config#>'{quality_gate,rules}', '[]'::jsonb) || '[...]'::jsonb
```

- [ ] **Step 3: Validate SQL with rollback**

Run:

```bash
perl -pe 's/^COMMIT;/ROLLBACK;/' migrations/105_reddit_native_prompt_artifact_config.sql | psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1
```

Expected output includes `BEGIN`, one or more `UPDATE` counts, and `ROLLBACK`.

## Task 9: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run Python syntax checks**

Run:

```bash
python3 -m py_compile geo_agent/src/pipelines/content_pipeline.py geo_agent/src/routers/tasks.py geo_agent/tests/test_content_pipeline_options.py
```

Expected: no output, exit 0.

- [ ] **Step 2: Run focused Python tests**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py -q
```

Expected: pass. If the local environment lacks `pytest`, report that explicitly and run targeted smoke tests with `PYTHONPATH=geo_agent/src:geo_common/src python3 -c ...`.

- [ ] **Step 3: Run Admin checks**

Run from `geo_admin/web`:

```bash
npm run typecheck
npm run build
```

Expected: both pass. Vite chunk-size warnings are acceptable if build exits 0.

- [ ] **Step 4: Static scan for forbidden hardcoding**

Run:

```bash
rg -n "consensus among creators|brand-safe visual control|Phase 1|Step-by-Step|reddit_native_contract|prompt_input_policy" geo_agent/src
```

Expected:

- Config key names may appear in generic code.
- Reddit-specific forbidden phrases should not appear in Python source except in tests.

- [ ] **Step 5: Deployment script update**

Only if code changes are ready for deployment:

- bump `AGENT_VERSION`
- bump `ADMIN_WEB_VERSION` if Admin UI changed
- keep unrelated modules commented in `deploy_all.sh`

Do not run Git.

## Spec Coverage Review

- Template-configured Reddit behavior: Tasks 1, 3, 4, 8.
- Wizard main engine stability: Tasks 1, 4, 5 with legacy fallback tests.
- RATF native rendering: Task 2.
- Experience Style Notes and Community Brief: Task 3.
- Reddit five-gap closure: Tasks 4, 6, 8.
- Other template stability: Tasks 1, 2, 4, 5 include legacy behavior checks.
- Admin editability: Task 7.
- Data migration: Task 8.
- Verification and deployment readiness: Task 9.
