"""
Strategy generation router.

Extracted from ``routers/tasks.py`` in Phase 3A refactor (2026-04-25).
Owns the real-time strategy preview endpoint used by Content Wizard Node 3,
which combines selected metrics + subgoals + analyzer context into a draft
strategy via Gemini Flash.

Endpoints (mounted under ``/api/agent/tasks``):
    - POST /generate-strategy
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_pool
from llm.client import get_genai_client, get_model_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/tasks", tags=["tasks", "strategy"])


class StrategyEntry(BaseModel):
    """One strategy in the LLM-generated list. ``dimensions`` is loose
    (LLM-shaped: instruction / format / tone / constraints /
    enhancement_rules can drift), so we keep it ``Any`` to avoid coupling
    to the prompt-template internals.
    """

    model_config = {"extra": "allow"}

    name: Optional[str] = None
    metric_id: Optional[str] = None
    subgoal_id: Optional[str] = None
    dimensions: Optional[Any] = None


class GenerateStrategyOut(BaseModel):
    """Outer envelope of ``POST /generate-strategy``. Outer keys
    (``strategies``, ``strategy_summary``) are stable per the prompt
    template; ``extra="allow"`` keeps it forward-compatible with future
    additions.
    """

    model_config = {"extra": "allow"}

    strategies: List[StrategyEntry] = []
    strategy_summary: Optional[str] = None


def _strategy_text_from_mapping(item: dict[str, Any]) -> str:
    for key in (
        "description",
        "instruction",
        "strategy",
        "summary",
        "rationale",
        "content_strategy",
        "approach",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    dimensions = item.get("dimensions")
    if isinstance(dimensions, dict):
        for key in ("instruction", "format", "tone", "constraints", "enhancement_rules"):
            value = dimensions.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (dict, list)) and value:
                return json.dumps(value, ensure_ascii=False)
    return json.dumps(item, ensure_ascii=False)


def _parse_json_string(value: str) -> Any:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except Exception:
        return None


def _extract_nested_strategy_payload(item: Any) -> Any:
    """Unwrap strategy entries that accidentally contain a full envelope.

    Some model responses pass schema validation as one strategy entry while
    placing the real ``{"strategies": [...]}`` payload inside description or
    dimensions.instruction. Rendering that literally produces the JSON blob the
    wizard is trying to avoid, so detect that shape before entry normalization.
    """
    if isinstance(item, str):
        parsed = _parse_json_string(item)
        if isinstance(parsed, dict) and isinstance(parsed.get("strategies"), list):
            return parsed
        return None
    if not isinstance(item, dict):
        return None
    candidates: list[Any] = [
        item.get("description"),
        item.get("instruction"),
        item.get("strategy"),
        item.get("content_strategy"),
    ]
    dimensions = item.get("dimensions")
    if isinstance(dimensions, dict):
        candidates.extend([
            dimensions.get("instruction"),
            dimensions.get("description"),
        ])
    for candidate in candidates:
        if isinstance(candidate, str):
            parsed = _parse_json_string(candidate)
            if isinstance(parsed, dict) and isinstance(parsed.get("strategies"), list):
                return parsed
    return None


def _normalize_strategy_entry(item: Any, index: int) -> dict[str, Any]:
    """Return a strategy entry that the wizard can actually render.

    The strategy LLM occasionally returns a root array, a single object, or a
    string-like plan. Pydantic can accept those only if the outer envelope is
    right, but the UI still needs displayable ``name``/``description`` fields.
    """
    if isinstance(item, str):
        parsed = _parse_json_string(item)
        if parsed is not None and not (
            isinstance(parsed, dict)
            and isinstance(parsed.get("strategies"), list)
        ):
            return _normalize_strategy_entry(parsed, index)
        text = item.strip()
        return {
            "name": f"Strategy {index + 1}",
            "description": text,
            "dimensions": {"instruction": text},
        }
    if not isinstance(item, dict):
        text = json.dumps(item, ensure_ascii=False)
        return {
            "name": f"Strategy {index + 1}",
            "description": text,
            "dimensions": {"instruction": text},
        }

    normalized = dict(item)
    name = normalized.get("name") or normalized.get("title") or normalized.get("strategy_name")
    if not isinstance(name, str) or not name.strip():
        name = f"Strategy {index + 1}"
    description = normalized.get("description")
    if not isinstance(description, str) or not description.strip():
        description = _strategy_text_from_mapping(normalized)
    dimensions = normalized.get("dimensions")
    if not isinstance(dimensions, dict):
        dimensions = {}
    if "instruction" not in dimensions and isinstance(description, str) and description.strip():
        dimensions["instruction"] = description.strip()

    normalized["name"] = name.strip()
    normalized["description"] = description.strip() if isinstance(description, str) else str(description)
    normalized["dimensions"] = dimensions
    return normalized


def normalize_strategy_payload(value: Any) -> dict[str, Any]:
    """Normalize LLM strategy JSON into the route response envelope.

    Gemini sometimes returns the requested ``strategies`` array as the root
    value. The UI and pipeline expect an object envelope, so keep the wizard
    resilient to that common JSON shape drift.
    """
    if isinstance(value, str):
        parsed = _parse_json_string(value)
        if parsed is not None:
            return normalize_strategy_payload(parsed)

    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        parsed = _parse_json_string(value[0])
        if parsed is not None:
            return normalize_strategy_payload(parsed)

    if isinstance(value, dict):
        strategies = value.get("strategies")
        if strategies is None:
            strategies = []
        elif not isinstance(strategies, list):
            strategies = [strategies]
        if len(strategies) == 1:
            nested = _extract_nested_strategy_payload(strategies[0])
            if isinstance(nested, dict):
                return normalize_strategy_payload(nested)
        value["strategies"] = [
            _normalize_strategy_entry(item, idx)
            for idx, item in enumerate(strategies)
        ]
        if not isinstance(value.get("strategy_summary"), str):
            count = len(value.get("strategies") or [])
            value["strategy_summary"] = f"Generated {count} strategy option{'s' if count != 1 else ''}."
        return value

    if isinstance(value, list):
        strategies = [
            _normalize_strategy_entry(item, idx)
            for idx, item in enumerate(value)
        ]
        return {
            "strategies": strategies,
            "strategy_summary": f"Generated {len(strategies)} strategy option{'s' if len(strategies) != 1 else ''}.",
        }

    raise ValueError("Strategy generation returned invalid JSON shape; expected object or strategies array")


@router.post("/generate-strategy", response_model=GenerateStrategyOut)
async def generate_strategy(request: dict) -> GenerateStrategyOut:
    """Generate strategy combination from user selections + analyzer context.
    Called by Content Node 3 for real-time strategy preview."""
    from google.genai import types as genai_types

    client_id = request.get("client_id", "")
    selected_metrics = request.get("selected_metrics", [])
    selected_subgoals = request.get("selected_subgoals", [])
    content_type = request.get("content_type", "faq")
    publish_platform = request.get("publish_platform", "")
    depth = request.get("depth", "")
    template_id = request.get("template_id")
    analyzer_context = request.get("analyzer_context")
    reddit_discovery = request.get("reddit_discovery")
    official_website_discovery = request.get("official_website_discovery")
    citation_analysis = request.get("citation_analysis")
    citation_analysis_result = request.get("citation_analysis_result")
    user_edits = request.get("user_strategy_edits")

    pool = await get_pool()

    # Load sub-goal descriptions
    sg_rows = await pool.fetch(
        """SELECT sg.id, sg.name_zh, sg.description, m.name_zh AS metric_name
           FROM geo_optimization_subgoals sg
           JOIN geo_optimization_metrics m ON sg.metric_id = m.id
           WHERE sg.id = ANY($1::text[])""",
        selected_subgoals,
    )
    sg_descriptions = [f"- {r['metric_name']} > {r['name_zh']}: {r['description']}" for r in sg_rows]

    # Brand profile
    bp_row = await pool.fetchrow(
        """SELECT brand_name, tone_of_voice, target_audience, key_messages, brand_values
           FROM geo_brand_profiles WHERE client_id = $1::uuid""",
        client_id,
    )
    brand = dict(bp_row) if bp_row else {}

    template_runtime_config: dict[str, Any] = {}
    if template_id:
        tmpl_row = await pool.fetchrow(
            """
            SELECT default_prompt, defaults, wizard_config
            FROM geo_report_templates
            WHERE id = $1::uuid
            """,
            template_id,
        )
        if tmpl_row:
            defaults = tmpl_row["defaults"]
            wizard_config = tmpl_row["wizard_config"]
            if isinstance(defaults, str):
                try:
                    defaults = json.loads(defaults)
                except Exception:
                    defaults = {}
            if isinstance(wizard_config, str):
                try:
                    wizard_config = json.loads(wizard_config)
                except Exception:
                    wizard_config = {}
            defaults = defaults if isinstance(defaults, dict) else {}
            wizard_config = wizard_config if isinstance(wizard_config, dict) else {}
            steps = wizard_config.get("steps") if isinstance(wizard_config.get("steps"), dict) else {}
            generation_config = steps.get("generation_config") if isinstance(steps.get("generation_config"), dict) else {}
            template_runtime_config = {
                "default_prompt": tmpl_row["default_prompt"],
                "platform_profile": wizard_config.get("platform_profile") or defaults.get("platform_profile"),
                "platform_playbook": wizard_config.get("platform_playbook") or defaults.get("platform_playbook"),
                "depth_profiles": wizard_config.get("depth_profiles") or defaults.get("depth_profiles") or {},
                "generation_requirements": wizard_config.get("generation_requirements") or defaults.get("generation_requirements"),
                "default_publish_platform": generation_config.get("default_publish_platform") or defaults.get("publish_platform"),
                "default_depth": generation_config.get("default_depth") or defaults.get("depth"),
            }

    analyzer_snippet = ""
    if analyzer_context:
        analyzer_snippet = f"""
## Analyzer 上下文
{json.dumps(analyzer_context.get("topic_quadrants", [])[:3], ensure_ascii=False, indent=2)}
{json.dumps(analyzer_context.get("content_opportunities", [])[:3], ensure_ascii=False, indent=2)}
"""

    platform_hint = ""
    if str(publish_platform).lower() == "reddit":
        platform_hint = """
## Reddit 策略约束
- 策略要优先回应社区常见问题，不要规划硬广或官网白皮书式内容。
- 标题与结构要像真实讨论帖、经验分享帖或问题帖。
- 语气应具体、坦诚、可讨论，可包含取舍分析和实操清单。
"""

    template_hint = ""
    if template_runtime_config:
        template_hint = f"""
## 模板配置约束
{json.dumps({
    "default_prompt": template_runtime_config.get("default_prompt"),
    "platform_profile": template_runtime_config.get("platform_profile"),
    "platform_playbook": template_runtime_config.get("platform_playbook"),
    "depth_profile": (template_runtime_config.get("depth_profiles") or {}).get(str(depth or template_runtime_config.get("default_depth") or "standard").lower()) if isinstance(template_runtime_config.get("depth_profiles"), dict) else None,
                "generation_requirements": template_runtime_config.get("generation_requirements"),
                "citation_analysis": wizard_config.get("citation_analysis"),
                "citation_analysis_step": steps.get("citation_analysis"),
            }, ensure_ascii=False, indent=2)}
"""

    reddit_discovery_block = ""
    if isinstance(reddit_discovery, dict) and reddit_discovery.get("data"):
        reddit_discovery_block = f"""
## Reddit Discover Insight
{json.dumps(reddit_discovery.get("data"), ensure_ascii=False, indent=2)}
"""

    official_website_discovery_block = ""
    if isinstance(official_website_discovery, dict) and official_website_discovery.get("data"):
        official_website_discovery_block = f"""
## Official Website Discover Insight
{json.dumps(official_website_discovery.get("data"), ensure_ascii=False, indent=2)}
"""

    citation_analysis_block = ""
    if isinstance(citation_analysis_result, dict) and citation_analysis_result.get("enabled"):
        citation_analysis_block = f"""
## Citation Analysis Summary
{citation_analysis_result.get("citation_grounded_brief", "")}
"""
    elif isinstance(citation_analysis, dict) and citation_analysis.get("enabled"):
        citation_analysis_block = f"""
## Citation Analysis Config
Citation Analysis is enabled for this template. The final execution will analyze cited pages before content generation. In this preview, use the config below as a planning constraint but do not invent citation findings.
{json.dumps(citation_analysis, ensure_ascii=False, indent=2)}
"""

    model_id = await get_model_id("flash")
    client_llm = await get_genai_client(model_id, role="flash")

    prompt = f"""你是 GEO 内容策略专家。请基于以下输入生成策略组合。

## 输入
- 内容类型: {content_type}
- 发布平台: {publish_platform or "未指定"}
- 内容深度: {depth or "standard"}
- 优化 Metrics: {', '.join(selected_metrics)}
- Sub-goals:
{chr(10).join(sg_descriptions)}

## 品牌画像
{json.dumps(brand, ensure_ascii=False, indent=2)}
{analyzer_snippet}
{platform_hint}
{template_hint}
{reddit_discovery_block}
{official_website_discovery_block}
{citation_analysis_block}
{f"## 用户调整要求{chr(10)}{user_edits}" if user_edits else ""}

## 输出 JSON
{{"strategies": [{{"name": "...", "description": "...", "dimensions": {{"instruction": "...", "format": {{"structure": "...", "schema_markup": "...", "word_count": "..."}}, "tone": "...", "constraints": ["..."], "enhancement_rules": ["..."]}}, "source_metrics": ["..."], "source_subgoals": ["..."]}}], "strategy_summary": "..."}}

生成 2-4 个互补策略。"""

    for attempt in range(1, 4):
        try:
            response = await client_llm.aio.models.generate_content(
                model=model_id, contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.3, max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return GenerateStrategyOut(**normalize_strategy_payload(json.loads(text)))
        except Exception as e:
            logger.warning(f"[STRATEGY] attempt {attempt}/3 failed: {e}")
            if attempt == 3:
                raise HTTPException(status_code=500, detail=f"Strategy generation failed: {e}")
            await asyncio.sleep(1)
