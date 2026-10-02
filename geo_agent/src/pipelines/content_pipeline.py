"""
Content Generation Pipeline v2 — strategy-driven 5-step workflow.

Steps:
  1. Citation Analysis              — Build citation-grounded brief when enabled
  2. 策略生成 (Strategy Generation) — Generate structured strategy from user selections + analyzer context
  3. 内容生成 (Content Generation)   — Generate content using strategy + brand profile
  4. 质量评审 (Quality Review)       — Score content against selected Metrics/Sub-goals
  5. 第一轮 Revise                   — Run configured deterministic QA and targeted revision when needed
  6. 修订后复查                       — Re-check the revised content against the Quality Gate
  7. 第二轮 Revise                   — Optional cleanup pass for remaining blockers

Inputs come from the 7-node frontend wizard:
  - selected_metrics, selected_subgoals (from Node 1)
  - content_type (from Node 2)
  - analyzer_context (from Node 0, optional)
  - ai_platforms, publish_platform, language, count, product_facts (from Node 4)
  - target_prompt_ids (from Node 5)
  - strategy, user_strategy_edits (from Node 3, confirmed strategy + optional user tweaks)
  - citation_analysis (from optional Citation Analysis wizard node)
"""
import asyncio
import copy
from datetime import datetime
import hashlib
import json
import logging
from typing import Any
from urllib.parse import urlparse

from google.genai import types

from llm.client import get_genai_client, get_model_id
from tools.content_tools import _build_brand_context, FAQ_SYSTEM_PROMPT
from pipelines.base import WorkflowStep, run_pipeline, append_status_log, update_step_status
from database import get_pool
from routers.tasks import register_pipeline
from pipelines.template_contracts import (
    get_contract_for_task,
    load_workflow_dictionary_rows,
)
from services import citation_analysis as citation_analysis_service
from services.citation_analysis import run_citation_analysis

import re as _re

logger = logging.getLogger(__name__)

_LLM_RETRIES = 3
_CONTENT_PROMPT_DEBUG_SETTING_KEY = "content_generation_log_final_prompt"
_CONTENT_PROMPT_DEBUG_CHUNK_SIZE = 12000
_TRUTHY_SETTING_VALUES = {"1", "true", "yes", "y", "on", "enabled"}

_LONGFORM_CONTENT_TYPES = {
    "aeo_article",
    "article",
    "comparison",
    "howto",
    "listicle",
    "reddit_article",
    "official_website_article",
}

_REPORT_CONTENT_TYPES = {"recommendations"}

_SHORT_CONTENT_TOKEN_BUDGET = {
    "faq": 4096,
    "brief": 4096,
    "platform_post": 4096,
}

_DEPTH_TOKEN_BUDGET = {
    "quick": 4096,
    "standard": 8192,
    "deep": 12288,
    "authority": 16384,
    "comprehensive": 16384,
}

_SEGMENTED_DEPTHS = {"deep", "authority", "comprehensive"}

_DANGLING_LINE_RE = _re.compile(
    r"\b(?:a|an|the|and|or|but|with|without|for|from|to|of|in|on|at|by|as|than|between|into|that|which|who|when|where|because)\s*$",
    _re.IGNORECASE,
)

_OUTDATED_TOOL_MARKERS = {
    "Runway Gen-2": "Runway Gen-2 is a legacy reference; use current Runway generation unless explicitly historical.",
    "Pika 1.0": "Pika 1.0 is a legacy reference; avoid making it the current market baseline.",
    "Stable Video Diffusion": "Stable Video Diffusion is a legacy/open model reference; avoid centering it as a current creator workflow default.",
    "Sora demos in February 2024": "Sora's 2024 demos are historical context; do not anchor a current article around them.",
}

_SENTENCE_END_RE = _re.compile(r"""[.!?。！？)"'\]]$""")

_LLM_PROCESS_ARTIFACT_PATTERNS = [
    r"^\s*RSThe search results confirm",
    r"\bThe prompt says\b",
    r"\bThe primary brand to mention is\b",
    r"\bLet's double check the rules\b",
    r"\bThe failure is\s+`",
    r"\bRe-evaluating the text\b",
    r"\bLet's review\b",
    r"\bLet's refine\b",
    r"\bLooks solid\.\s*#",
]


def _setting_value_is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUTHY_SETTING_VALUES


async def _content_prompt_debug_enabled(pool) -> bool:
    """Return whether full content-generation prompts should be logged.

    The setting is stored in geo_global_settings so Admin UI can toggle it
    without code changes. Missing or invalid values default to off.
    """
    try:
        row = await pool.fetchrow(
            "SELECT value FROM geo_global_settings WHERE key = $1",
            _CONTENT_PROMPT_DEBUG_SETTING_KEY,
        )
    except Exception as e:
        logger.warning("[CONTENT_PROMPT_DEBUG] failed to read setting: %s", e)
        return False
    return bool(row and _setting_value_is_truthy(row["value"]))


async def _log_content_prompt_debug(
    pool,
    *,
    task_id: str,
    client_id: str,
    label: str,
    model_id: str,
    prompt: str,
    template_name: str | None = None,
    content_type: str | None = None,
    publish_platform: str | None = None,
    enabled: bool | None = None,
    chunk_size: int = _CONTENT_PROMPT_DEBUG_CHUNK_SIZE,
) -> None:
    """Log the exact prompt sent to Gemini in bounded chunks when enabled."""
    if enabled is None:
        enabled = await _content_prompt_debug_enabled(pool)
    if not enabled:
        return

    prompt_text = prompt or ""
    chunk_size = max(int(chunk_size or _CONTENT_PROMPT_DEBUG_CHUNK_SIZE), 1)
    chunks = [
        prompt_text[index:index + chunk_size]
        for index in range(0, len(prompt_text), chunk_size)
    ] or [""]
    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    total_chunks = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        chunk_json = json.dumps(chunk, ensure_ascii=True)
        logger.info(
            "[CONTENT_PROMPT_DEBUG] task_id=%s client_id=%s label=%s model_id=%s "
            "template=%s content_type=%s publish_platform=%s chunk=%s/%s chars=%s "
            "sha256=%s encoding=json_escaped prompt_chunk_json=%s",
            task_id,
            client_id,
            label,
            model_id,
            template_name or "",
            content_type or "",
            publish_platform or "",
            index,
            total_chunks,
            len(prompt_text),
            digest,
            chunk_json,
        )


async def _log_llm_prompt_debug(prompt_debug: dict[str, Any] | None, *, label: str, model_id: str, prompt: str) -> None:
    if not prompt_debug:
        return
    await _log_content_prompt_debug(
        prompt_debug["pool"],
        task_id=prompt_debug["task_id"],
        client_id=prompt_debug["client_id"],
        label=label,
        model_id=model_id,
        prompt=prompt,
        template_name=prompt_debug.get("template_name"),
        content_type=prompt_debug.get("content_type"),
        publish_platform=prompt_debug.get("publish_platform"),
        enabled=prompt_debug.get("enabled"),
    )


def _content_prompt_debug_context(
    pool,
    *,
    task_id: str,
    client_id: str,
    template_runtime_config: dict[str, Any] | None,
    content_type: str | None,
    publish_platform: str | None,
    enabled: bool,
) -> dict[str, Any]:
    return {
        "pool": pool,
        "task_id": task_id,
        "client_id": client_id,
        "template_name": (template_runtime_config or {}).get("template_name"),
        "content_type": content_type,
        "publish_platform": publish_platform,
        "enabled": enabled,
    }


async def _resolve_content_model_id(pool, inputs: dict) -> str:
    """Resolve a content task model override from the Admin-configured allowlist."""
    requested = (inputs.get("model_id") or "").strip()
    if not requested:
        return await get_model_id("pro")

    row = await pool.fetchrow(
        "SELECT value FROM geo_global_settings WHERE key = $1",
        "content_generation_model_list",
    )
    allowed = [
        model_id.strip()
        for model_id in ((row["value"] if row and row["value"] else "")).split(",")
        if model_id.strip()
    ]
    if not allowed:
        raise ValueError("content_generation_model_list is not configured")
    if requested not in allowed:
        raise ValueError(f"Content generation model_id '{requested}' is not configured")
    return requested


async def _resolve_strategy_model_id() -> str:
    """Strategy generation is a lightweight planning step and always uses Flash."""
    return await get_model_id("flash")


def _build_generation_config(max_tokens: int, search_grounding_enabled: bool):
    """Build Gemini generation config, optionally enabling Google Search grounding."""
    tools = None
    if search_grounding_enabled:
        tools = [types.Tool(google_search=types.GoogleSearch())]
    return types.GenerateContentConfig(
        temperature=0.4,
        max_output_tokens=max_tokens,
        tools=tools,
    )


def _current_runtime_datetime(now: datetime | None = None) -> datetime:
    """Return the system clock value used for freshness prompts and QA."""
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    return current


def _build_freshness_context(now: datetime | None = None) -> str:
    """Inject a runtime freshness anchor into every content prompt."""
    current = _current_runtime_datetime(now)
    month_name = current.strftime("%B")
    current_date = current.strftime("%Y-%m-%d")
    current_month = current.strftime("%B %Y")
    stale_cutoff = current.year - 1
    return f"""
## Runtime Freshness Context（系统时间硬约束）
- Current date: {current_date}
- Current month: {current_month}
- Current year: {current.year}
- Use this runtime date as the temporal anchor for titles, intros, comparisons, tool landscapes, policy references, and market-state language.
- Do not frame the content as current for years earlier than {stale_cutoff} unless the section is explicitly historical context.
- Avoid titles such as "Q2 2024", "2024 trends", "as of 2024", or similar stale anchors for current-generation content.
- If Search Grounding is enabled, verify current product/tool/policy facts against recent or official sources before using words like current, recent, latest, verified, official, or community consensus.
- If current facts cannot be verified, use conservative wording and avoid pretending the market landscape is up to date.
"""


async def _load_content_brand_context(pool, client_id: str) -> dict[str, Any]:
    """Load brand context, falling back to workspace own-brand settings.

    geo_brand_profiles carries tonality and positioning, but some workspaces
    configure the actual "my brand" list in geo_client_brands. Content prompts
    need a concrete brand_name for Brand Mention objectives, so we merge both.
    """
    bp_row = await pool.fetchrow(
        """SELECT brand_name, tone_of_voice, target_audience,
                  key_messages, brand_values, language
           FROM geo_brand_profiles WHERE client_id = $1::uuid""",
        client_id,
    )
    brand_context = dict(bp_row) if bp_row else {}

    try:
        own_rows = await pool.fetch(
            """SELECT
                  b.id,
                  b.brand_name,
                  b.aliases,
                  COALESCE(
                    array_agg(d.domain ORDER BY d.is_primary DESC, d.domain)
                    FILTER (WHERE d.domain IS NOT NULL),
                    '{}'::text[]
                  ) AS domains
               FROM geo_client_brands b
               LEFT JOIN geo_client_domains d
                 ON d.brand_id = b.id
                AND d.client_id = b.client_id
               WHERE b.client_id = $1::uuid
                 AND b.is_shadow = false
                 AND b.is_active = true
               GROUP BY b.id, b.brand_name, b.aliases
               ORDER BY b.brand_name ASC
               LIMIT 5""",
            client_id,
        )
    except Exception as e:
        logger.warning("[CONTENT-V2] Own brand fallback lookup failed: %s", e)
        own_rows = []

    own_brands = []
    for row in own_rows or []:
        own_brands.append({
            "brand_name": row["brand_name"],
            "aliases": row["aliases"] or [],
            "domains": row["domains"] or [],
        })

    if own_brands:
        brand_context["own_brands"] = own_brands
        owned_domains: list[str] = []
        for brand in own_brands:
            for domain in brand.get("domains") or []:
                domain_text = str(domain or "").strip().lower().removeprefix("www.")
                if domain_text and domain_text not in owned_domains:
                    owned_domains.append(domain_text)
        if owned_domains:
            brand_context["owned_domains"] = owned_domains
        if not (brand_context.get("brand_name") or "").strip():
            brand_context["brand_name"] = own_brands[0]["brand_name"]
            brand_context["brand_name_source"] = "geo_client_brands"

    return brand_context


def _extract_primary_brand_name(brand_context: dict[str, Any] | None) -> str:
    if not isinstance(brand_context, dict):
        return ""
    brand_name = str(brand_context.get("brand_name") or "").strip()
    if brand_name:
        return brand_name
    own_brands = brand_context.get("own_brands")
    if isinstance(own_brands, list):
        for item in own_brands:
            if isinstance(item, dict) and item.get("brand_name"):
                return str(item["brand_name"]).strip()
    return ""


def _count_brand_mentions(text: str, brand_name: str) -> int:
    if not text or not brand_name:
        return 0
    return len(_re.findall(_re.escape(brand_name), text, flags=_re.IGNORECASE))


def _build_brand_visibility_instruction(brand_context: dict[str, Any] | None) -> str:
    brand_name = _extract_primary_brand_name(brand_context)
    if not brand_name:
        return ""
    return f"""
## Brand Mention / Brand-Safe Insertion（硬约束）
- Primary brand name: {brand_name}
- This content is generated for the primary brand above. The brand name must appear naturally where it helps the reader evaluate a category, workflow, use case, or tradeoff.
- For Reddit or community content, mention {brand_name} 2-4 times in helpful context; do not force it into the title, TL;DR, or every section.
- If facts about {brand_name} are not provided or grounded, describe it conservatively and avoid unsupported superiority claims.
- A generated article that never mentions {brand_name} fails the Brand Mention visibility objective.
"""


def _first_markdown_title(content: str) -> str:
    for line in (content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _contains_llm_process_artifacts(content: str) -> bool:
    text = content or ""
    return any(_re.search(pattern, text, flags=_re.IGNORECASE | _re.MULTILINE) for pattern in _LLM_PROCESS_ARTIFACT_PATTERNS)


def _strip_llm_process_artifacts(
    content: str,
    *,
    content_type: str = "",
    publish_platform: str = "",
) -> str:
    """Remove leaked model reasoning while preserving the final Markdown article.

    Revision models can occasionally prepend self-check notes before the actual
    answer. When that happens and a publishable H1 is present, keep the final
    article block instead of persisting the reasoning transcript.
    """
    text = (content or "").strip()
    if not text or not _contains_llm_process_artifacts(text):
        return text

    text = _re.sub(r"(?<![\n#])(#{1,6}\s+)", r"\n\1", text).strip()
    h1_matches = list(_re.finditer(r"(?m)^\s{0,3}#\s+\S.*$", text))
    if h1_matches:
        first_prefix = text[: h1_matches[0].start()]
        starts_with_artifact = _contains_llm_process_artifacts(first_prefix or text[:400])
        if first_prefix.strip() or starts_with_artifact:
            return text[h1_matches[-1].start():].strip()

    is_reddit = str(content_type).lower() == "reddit_article" or str(publish_platform).lower() == "reddit"
    if is_reddit:
        lines = text.splitlines()
        first_publishable_idx = next(
            (
                idx
                for idx, line in enumerate(lines)
                if line.strip()
                and not _contains_llm_process_artifacts(line)
                and not line.strip().lower().startswith(("wait", "looks solid"))
            ),
            0,
        )
        return "\n".join(lines[first_publishable_idx:]).strip()

    return text


def _normalize_content_markdown_for_output(
    content: str,
    *,
    content_type: str = "",
    publish_platform: str = "",
) -> str:
    """Normalize final Markdown shape for frontend/report rendering.

    Reddit single-shot generation sometimes returns the post title as the first
    plain line. The report renderer then treats it as body text while official
    articles already use ``#``. Promote a title-like first line to H1 for
    Markdown display without changing the prose.
    """
    text = _strip_llm_process_artifacts(
        content,
        content_type=content_type,
        publish_platform=publish_platform,
    )
    if not text:
        return ""
    if _first_markdown_title(text):
        return text
    is_reddit = str(content_type).lower() == "reddit_article" or str(publish_platform).lower() == "reddit"
    if not is_reddit:
        return text

    lines = text.splitlines()
    first_idx = next((idx for idx, line in enumerate(lines) if line.strip()), None)
    if first_idx is None:
        return text
    first = lines[first_idx].strip()
    if first.startswith(("#", "-", "*", ">", "|")):
        return text
    if len(first) > 180 or first.endswith((":", ";", ",")):
        return text
    lines[first_idx] = f"# {first}"
    return "\n".join(lines).strip()


def _normalize_official_internal_linking_section(
    content: str,
    *,
    content_type: str = "",
    brand_name: str = "",
) -> str:
    """Make official-site internal links reader-facing in final Markdown.

    The template needs internal-link guidance for GEO extractability, but a
    live official article should not expose editor-facing headings such as
    "Internal Linking Suggestions". Keep the section useful while making it
    read like a publishable related-resources block.
    """
    text = (content or "").strip()
    if not text or str(content_type).lower() != "official_website_article":
        return text

    resource_heading_re = (
        r"(?:Internal Linking Suggestions|Internal Links?|Internal Linking Plan|"
        r"Suggested Internal Links|Related\s+(?:[A-Za-z0-9][\w.-]*\s+)?Resources)"
    )
    editor_artifact_re = _re.compile(
        r"(?:Anchor Text\s*:|Target Page\s*:|Destination\s*:|"
        r"\bSEO\b|\bAEO\b|internal links?|"
        r"we recommend integrating|consider adding|strategically placing|"
        r"Insert Official|Insert\s+.+URL|placeholder)",
        flags=_re.IGNORECASE,
    )

    def _clean_anchor(anchor: str) -> str:
        anchor = (anchor or "").strip().strip("*` ")
        anchor = anchor.split('" or "')[0].strip('" ')
        return anchor

    def _extract_resource_pairs(section_body: str) -> list[str]:
        links: list[str] = []
        pair_re = _re.compile(
            r"^\s*[*-]\s+\*\*Anchor Text:\*\*\s+(?P<anchor>.+?)\s*\n"
            r"\s*[*-]\s+\*\*(?:Target Page|Destination):\*\*\s+"
            r"(?:`(?P<url1>https?://[^`]+)`|(?P<url2>https?://\S+))\s*$",
            flags=_re.IGNORECASE | _re.MULTILINE,
        )
        for match in pair_re.finditer(section_body):
            url = (match.group("url1") or match.group("url2") or "").strip().rstrip(").,")
            anchor = _clean_anchor(match.group("anchor"))
            if url and anchor:
                links.append(f"- [{anchor}]({url})")
        return links

    def _clean_resource_section(match: _re.Match[str]) -> str:
        body = match.group("body") or ""
        cleaned_lines: list[str] = _extract_resource_pairs(body)

        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if editor_artifact_re.search(line):
                continue
            line = _re.sub(r"^\s*[-*]\s*Link to the\s+", "- Read the ", line, flags=_re.IGNORECASE)
            line = _re.sub(r"^\s*[-*]\s*Link to\s+", "- Read ", line, flags=_re.IGNORECASE)
            if line.startswith(("- ", "* ")):
                normalized_line = "- " + line[2:].strip()
                if normalized_line not in cleaned_lines:
                    cleaned_lines.append(normalized_line)

        if not cleaned_lines:
            return ""
        return "## Helpful Resources\n\n" + "\n".join(cleaned_lines).strip() + "\n\n"

    text = _re.sub(
        rf"(?ms)^\s{{0,3}}##\s+{resource_heading_re}\s*\n(?P<body>.*?)(?=^\s{{0,3}}##\s+|\Z)",
        _clean_resource_section,
        text,
    )
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _next_non_empty_line(lines: list[str], start_index: int) -> str:
    for next_line in lines[start_index + 1:]:
        stripped = next_line.strip()
        if stripped:
            return stripped
    return ""


def _detect_content_integrity_issues(
    content: str,
    *,
    current_year: int | None = None,
    brand_name: str = "",
    require_brand_mention: bool = False,
) -> list[str]:
    """Deterministic QA guardrails for freshness, truncation and repetition."""
    issues: list[str] = []
    if not content or not content.strip():
        return ["内容为空，无法进行质量评审。"]

    year = current_year or _current_runtime_datetime().year
    if _contains_llm_process_artifacts(content):
        issues.append("内容包含模型过程文本或修订自检指令，必须删除，只保留可发布正文。")

    title = _first_markdown_title(content)
    if title:
        stale_years = sorted({
            int(match)
            for match in _re.findall(r"\b(20\d{2})\b", title[:240])
            if int(match) <= year - 2
        })
        if stale_years:
            issues.append(
                f"标题包含过期时间锚点 {stale_years}；当前年份是 {year}，除非是历史回顾，否则标题必须改为当前时间语境。"
            )
        if title.endswith((",", ":", ";", "-", "—", "(", "[")) or _DANGLING_LINE_RE.search(title):
            issues.append("标题疑似截断或未完成句，请重写为完整、自然的可发布标题。")

    early_text = "\n".join(content.splitlines()[:80])
    stale_body_years = sorted({
        int(match)
        for match in _re.findall(r"\b(20\d{2})\b", early_text)
        if int(match) <= year - 2
    })
    if stale_body_years:
        issues.append(
            f"正文开头包含过期时间锚点 {stale_body_years}；当前年份是 {year}，不能把旧年份作为当前市场状态。"
        )

    lines = content.splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if len(stripped) < 8 or stripped.startswith(("#", "|", "-", "*")):
            continue
        next_line = _next_non_empty_line(lines, idx - 1)
        if stripped.endswith(":") and (
            next_line.startswith(("-", "*", "|", "#"))
            or bool(_re.match(r"^\d+\.", next_line))
        ):
            continue
        if stripped.endswith((",", ":", ";", "-", "—", "(", "[")) or _DANGLING_LINE_RE.search(stripped):
            issues.append(f"第 {idx} 行疑似残缺或未完成句：{stripped[:120]}")
            break

    blocks = _re.split(r"\n\s*\n", content.strip())
    previous_text_block = ""
    for block in blocks:
        stripped_block = block.strip()
        if not stripped_block:
            continue
        if stripped_block.startswith("#"):
            if previous_text_block:
                last_line = previous_text_block.splitlines()[-1].strip()
                if (
                    len(last_line) >= 24
                    and not _SENTENCE_END_RE.search(last_line)
                    and not last_line.endswith((",", ":", ";", "-", "—", "(", "["))
                ):
                    issues.append(f"标题前正文块疑似截断或残缺：{last_line[:140]}")
                    break
            previous_text_block = ""
            continue
        if not stripped_block.startswith(("|", "-", "*", ">")):
            previous_text_block = stripped_block

    normalized_lines = [
        _re.sub(r"\s+", " ", line.strip().lower())
        for line in content.splitlines()
        if len(line.strip()) >= 48 and not line.strip().startswith("|")
    ]
    seen: set[str] = set()
    for line in normalized_lines:
        if line in seen:
            issues.append("检测到重复段落或重复结尾，请压缩重复内容并保留一个清晰收束。")
            break
        seen.add(line)

    outdated_markers = [
        marker for marker in _OUTDATED_TOOL_MARKERS
        if _re.search(_re.escape(marker), content, flags=_re.IGNORECASE)
    ]
    if outdated_markers:
        issues.append(
            "内容疑似以过旧工具格局作为当前基准："
            + ", ".join(outdated_markers)
            + "。应使用当前工具/模型格局，旧工具只能作为历史背景。"
        )

    if require_brand_mention and brand_name:
        mention_count = _count_brand_mentions(content, brand_name)
        if mention_count <= 0:
            issues.append(
                f"内容没有提到当前品牌 {brand_name}；这不满足 Brand Mention / GEO visibility 目标。"
            )

    return issues


def _detect_brand_density_issues(
    content: str,
    *,
    brand_name: str,
    quality_gate_config: dict[str, Any] | None = None,
) -> list[str]:
    if not content or not brand_name:
        return []
    cfg = (quality_gate_config or {}).get("brand_density")
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return []

    mention_count = _count_brand_mentions(content, brand_name)
    words = _re.findall(r"\b[\w'-]+\b", content)
    word_count = max(len(words), 1)
    max_mentions = cfg.get("max_mentions")
    max_per_1000 = cfg.get("max_mentions_per_1000_words")
    issues: list[str] = []

    try:
        max_mentions_int = int(max_mentions)
    except (TypeError, ValueError):
        max_mentions_int = 0
    if max_mentions_int and mention_count > max_mentions_int:
        issues.append(
            f"品牌提及过密：{brand_name} 出现 {mention_count} 次，超过上限 {max_mentions_int} 次；请减少重复品牌露出，改用代词、类别词或具体 use case。"
        )

    try:
        max_per_1000_float = float(max_per_1000)
    except (TypeError, ValueError):
        max_per_1000_float = 0.0
    density = mention_count / word_count * 1000
    if max_per_1000_float and density > max_per_1000_float:
        issues.append(
            f"品牌提及密度过高：约 {density:.1f} 次 / 1000 words，超过上限 {max_per_1000_float:g}；请降低商业感。"
        )

    return issues[:2]


def _evaluate_framework_coverage(
    content: str,
    metric_defs: list[dict[str, Any]],
    quality_gate_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate RATF/framework coverage through evidence markers.

    The previous implementation expected metric labels like "answerability" to
    appear in the article. That is especially wrong for Reddit: a good post can
    be answerable and trustworthy without naming the metric. This helper uses
    configurable marker groups and returns evidence instead of forcing literal
    metric terms into the final content.
    """
    if not metric_defs:
        return {"required": [], "missing": [], "ok": True, "evidence": {}}

    lowered = (content or "").lower()
    heading_count = len(_markdown_heading_entries(content))
    has_table = bool(_re.search(r"^\s*\|.+\|\s*$", content or "", flags=_re.MULTILINE))
    has_list = bool(_re.search(r"^\s*(?:[-*]|\d+\.)\s+", content or "", flags=_re.MULTILINE))
    has_faq = bool(_re.search(r"^\s{0,3}#{2,4}\s+.*faq", content or "", flags=_re.IGNORECASE | _re.MULTILINE))
    has_current_year = bool(_re.search(r"\b20\d{2}\b", content or ""))

    configured = (quality_gate_config or {}).get("framework_coverage_markers")
    default_markers = {
        "readability": ["tl;dr", "step", "workflow", "checklist", "table", "short answer"],
        "answerability": ["direct answer", "the answer", "best", "how to", "workflow", "faq", "step"],
        "trustworthy": ["limitation", "tradeoff", "verify", "source", "citation", "not a magic", "caveat", "disclaimer"],
        "freshness": ["as of", "current", "updated", "2026", "may 2026", "this year"],
        "content_understandability": ["tl;dr", "step", "workflow", "example", "checklist"],
        "information_presentation": ["table", "matrix", "bullet", "faq", "comparison"],
        "audience_fit": ["target audience", "buyer", "user", "team", "persona", "use case", "workflow"],
        "platform_fit": ["reddit", "subreddit", "comment", "discussion", "official website", "guide", "article", "workflow"],
        "authority_eeat": ["limitation", "source", "evidence", "tested", "current", "verify", "not legal advice"],
        "verifiability": ["source", "citation", "verify", "fact", "limitation", "as of"],
        "trending_relevance": ["2026", "may 2026", "current", "updated", "recent", "this year"],
    }
    if isinstance(configured, dict):
        marker_map = {
            str(key): [str(item).lower() for item in value if str(item).strip()]
            for key, value in configured.items()
            if isinstance(value, list)
        }
    else:
        marker_map = default_markers

    required: list[str] = []
    missing: list[str] = []
    evidence: dict[str, list[str]] = {}
    for metric in metric_defs:
        key = str(metric.get("key") or "").strip()
        if not key:
            continue
        required.append(key)
        markers = marker_map.get(key, [])
        matched = [marker for marker in markers if marker in lowered]
        if key in {"readability", "content_understandability"}:
            if heading_count >= 2:
                matched.append("multiple Markdown headings")
            if has_list:
                matched.append("list formatting")
        if key in {"information_presentation"}:
            if has_table:
                matched.append("Markdown table")
            if has_list:
                matched.append("list formatting")
        if key in {"answerability"} and has_faq:
            matched.append("FAQ section")
        if key in {"freshness", "trending_relevance"} and has_current_year:
            matched.append("current-year reference")
        if matched:
            evidence[key] = list(dict.fromkeys(matched))[:5]
        else:
            missing.append(key)

    return {
        "required": required,
        "missing": missing,
        "ok": not missing,
        "evidence": evidence,
    }


def _trim_to_line_boundary(text: str, *, limit: int, keep: str) -> str:
    """Trim text near a line boundary so review excerpts do not end mid-word."""
    if len(text) <= limit:
        return text.strip()
    if keep == "head":
        candidate = text[:limit]
        boundary = max(candidate.rfind("\n\n"), candidate.rfind("\n"))
        if boundary > limit * 0.65:
            candidate = candidate[:boundary]
        return candidate.strip()
    candidate = text[-limit:]
    boundary = candidate.find("\n\n")
    if 0 <= boundary < limit * 0.35:
        candidate = candidate[boundary + 2:]
    else:
        boundary = candidate.find("\n")
        if 0 <= boundary < limit * 0.35:
            candidate = candidate[boundary + 1:]
    return candidate.strip()


def _build_review_content_excerpt(content: str, max_chars: int = 18000) -> str:
    """Build a quality-review excerpt without creating fake truncation.

    The previous review prompt used ``generated_content[:8000]``. For long
    articles that often cut the text mid-sentence, causing the review model to
    report a severe truncation that did not exist in the saved output. This
    helper preserves the start and end of long content and marks omitted middle
    content explicitly.
    """
    text = (content or "").strip()
    if len(text) <= max_chars:
        return text

    marker = (
        "\n\n[Middle content omitted for review prompt size. "
        "Do not treat this marker as article truncation; evaluate the visible "
        "beginning and ending plus deterministic integrity checks.]\n\n"
    )
    available = max(max_chars - len(marker), 1000)
    head_limit = max(available // 2, 500)
    tail_limit = max(available - head_limit, 500)
    head = _trim_to_line_boundary(text, limit=head_limit, keep="head")
    tail = _trim_to_line_boundary(text, limit=tail_limit, keep="tail")
    return f"{head}{marker}{tail}".strip()


def _markdown_headings(content: str) -> list[str]:
    headings: list[str] = []
    for entry in _markdown_heading_entries(content):
        headings.append(entry["normalized"])
    return headings


def _markdown_heading_entries(content: str) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    for line in (content or "").splitlines():
        match = _re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if match:
            text = _re.sub(r"\s+", " ", match.group(2).strip())
            headings.append({
                "level": len(match.group(1)),
                "text": text,
                "normalized": text.lower(),
            })
    return headings


def _heading_pattern_matches(heading: str, pattern: str) -> bool:
    normalized_heading = _re.sub(r"\s+", " ", str(heading).strip()).lower()
    normalized_pattern = _re.sub(r"\s+", " ", str(pattern).strip()).lower()
    if not normalized_pattern:
        return False
    return normalized_pattern in normalized_heading


def _contains_heading(content: str, candidates: list[str]) -> bool:
    headings = _markdown_headings(content)
    normalized_candidates = [
        _re.sub(r"\s+", " ", str(candidate).strip()).lower()
        for candidate in candidates
        if str(candidate).strip()
    ]
    if any(
        candidate in {
            "internal linking suggestions",
            "suggested internal links",
            "internal links",
            "internal linking plan",
        }
        for candidate in normalized_candidates
    ):
        normalized_candidates.extend([
            "related brand resources",
            "related resources",
            "recommended resources",
        ])
    return any(
        any(candidate in heading for heading in headings)
        for candidate in normalized_candidates
    )


def _quality_gate_issue(
    *,
    rule: dict[str, Any],
    message: str,
    matches: list[str] | None = None,
) -> dict[str, Any]:
    severity = str(rule.get("severity") or "warning").lower()
    if severity not in {"blocker", "warning"}:
        severity = "warning"
    return {
        "rule_id": str(rule.get("id") or rule.get("type") or "quality_rule"),
        "type": str(rule.get("type") or "unknown"),
        "severity": severity,
        "message": message,
        "matches": matches or [],
    }


def _quality_gate_status(
    *,
    enabled: bool,
    failures: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    revise_required: bool = False,
    human_review_required: bool = False,
    status_override: str | None = None,
) -> dict[str, Any]:
    if status_override:
        status = status_override
    elif human_review_required:
        status = "needs_human_review"
    elif not enabled or failures:
        status = "failed" if enabled and failures else "pass"
    elif warnings:
        status = "pass_with_warnings"
    else:
        status = "pass"
    return {
        "status": status,
        "passed": enabled is False or not failures,
        "revise_required": bool(revise_required),
        "human_review_required": bool(human_review_required),
    }


def _run_configured_quality_gate(
    content: str,
    quality_gate: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic, template-configured checks against generated content.

    The rule engine is intentionally small and data-driven: templates provide
    the rule list through ``wizard_config.quality_gate`` while code only knows
    generic rule types.
    """
    if not isinstance(quality_gate, dict) or not quality_gate.get("enabled"):
        return {
            "enabled": False,
            "passed": True,
            "status": "pass",
            "revise_required": False,
            "human_review_required": False,
            "triggers": [],
            "score_cap": 10.0,
            "failures": [],
            "warnings": [],
            "failure_count": 0,
            "warning_count": 0,
        }

    text = content or ""
    context = context if isinstance(context, dict) else {}
    heading_entries = _markdown_heading_entries(text)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def add_issue(issue: dict[str, Any]) -> None:
        if issue.get("severity") == "blocker":
            failures.append(issue)
        else:
            warnings.append(issue)

    for raw_rule in quality_gate.get("rules") or []:
        if not isinstance(raw_rule, dict):
            continue
        rule_type = str(raw_rule.get("type") or "").strip()

        if rule_type == "required_heading":
            candidates = list(raw_rule.get("any_of") or raw_rule.get("headings") or [])
            if candidates and not _contains_heading(text, candidates):
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message="Missing required heading: " + " OR ".join(str(c) for c in candidates),
                ))

        elif rule_type == "required_table":
            candidates = list(raw_rule.get("near_heading_any_of") or raw_rule.get("any_of") or [])
            has_required_heading = (not candidates) or _contains_heading(text, candidates)
            has_table = bool(_re.search(r"^\s*\|.+\|\s*$", text, flags=_re.MULTILINE))
            if not (has_required_heading and has_table):
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message="Missing required Markdown table"
                    + (f" near heading: {' OR '.join(str(c) for c in candidates)}" if candidates else ""),
                ))

        elif rule_type == "max_occurrences":
            pattern = str(raw_rule.get("pattern") or "").strip()
            max_count = int(raw_rule.get("max", 1))
            if pattern:
                count = len(_re.findall(_re.escape(pattern), text, flags=_re.IGNORECASE))
                if count > max_count:
                    add_issue(_quality_gate_issue(
                        rule=raw_rule,
                        message=f"Pattern {pattern!r} appears {count} times; maximum allowed is {max_count}.",
                        matches=[pattern],
                    ))

        elif rule_type == "max_regex_count":
            pattern = str(raw_rule.get("pattern") or "").strip()
            try:
                max_count = int(raw_rule.get("max", 1))
            except (TypeError, ValueError):
                max_count = 1
            if pattern:
                try:
                    matches = _re.findall(pattern, text, flags=_re.IGNORECASE | _re.MULTILINE)
                except _re.error as exc:
                    add_issue(_quality_gate_issue(
                        rule=raw_rule,
                        message=f"Invalid regex pattern {pattern!r}: {exc}",
                    ))
                    continue
                if len(matches) > max_count:
                    message = str(raw_rule.get("message") or "").strip() or (
                        f"Regex pattern {pattern!r} appears {len(matches)} times; "
                        f"maximum allowed is {max_count}."
                    )
                    add_issue(_quality_gate_issue(
                        rule=raw_rule,
                        message=message,
                        matches=[str(m) for m in matches[:10]],
                    ))

        elif rule_type == "first_paragraph_required_patterns":
            patterns = [str(p).strip() for p in (raw_rule.get("patterns") or []) if str(p).strip()]
            paragraphs = [
                p.strip()
                for p in _re.split(r"\n\s*\n", text)
                if p.strip() and not p.lstrip().startswith("#")
            ]
            first_paragraph = paragraphs[0] if paragraphs else ""
            matched = []
            for pattern in patterns:
                try:
                    if _re.search(pattern, first_paragraph, flags=_re.IGNORECASE | _re.MULTILINE):
                        matched.append(pattern)
                except _re.error as exc:
                    add_issue(_quality_gate_issue(
                        rule=raw_rule,
                        message=f"Invalid regex pattern {pattern!r}: {exc}",
                    ))
                    continue
            if patterns and not matched:
                message = str(raw_rule.get("message") or "").strip() or (
                    "First paragraph does not match any required pattern."
                )
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message=message,
                    matches=[],
                ))

        elif rule_type == "ending_required_patterns":
            patterns = [str(p).strip() for p in (raw_rule.get("patterns") or []) if str(p).strip()]
            paragraphs = [
                p.strip()
                for p in _re.split(r"\n\s*\n", text)
                if p.strip() and not p.lstrip().startswith("#")
            ]
            ending_text = paragraphs[-1] if paragraphs else ""
            matched = []
            for pattern in patterns:
                try:
                    if _re.search(pattern, ending_text, flags=_re.IGNORECASE | _re.MULTILINE):
                        matched.append(pattern)
                except _re.error as exc:
                    add_issue(_quality_gate_issue(
                        rule=raw_rule,
                        message=f"Invalid regex pattern {pattern!r}: {exc}",
                    ))
                    continue
            if patterns and not matched:
                message = str(raw_rule.get("message") or "").strip() or (
                    "Ending does not match any required pattern."
                )
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message=message,
                    matches=[],
                ))

        elif rule_type == "dynamic_brand_mention_count":
            brand_name = str(
                raw_rule.get("brand_name")
                or context.get("brand_name")
                or ""
            ).strip()
            if not brand_name:
                continue
            min_count = raw_rule.get("min")
            max_count = raw_rule.get("max")
            count = _count_brand_mentions(text, brand_name)
            issue_message = ""
            if min_count is not None:
                try:
                    min_int = int(min_count)
                except (TypeError, ValueError):
                    min_int = 0
                if count < min_int:
                    issue_message = (
                        str(raw_rule.get("message") or "").strip()
                        or f"Brand {brand_name!r} appears {count} times; minimum required is {min_int}."
                    )
            if max_count is not None and not issue_message:
                try:
                    max_int = int(max_count)
                except (TypeError, ValueError):
                    max_int = 999999
                if count > max_int:
                    issue_message = (
                        str(raw_rule.get("message") or "").strip()
                        or f"Brand {brand_name!r} appears {count} times; maximum allowed is {max_int}."
                    )
            if issue_message:
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message=issue_message,
                    matches=[brand_name],
                ))

        elif rule_type == "forbidden_standalone_brand_section":
            brand_name = str(
                raw_rule.get("brand_name")
                or context.get("brand_name")
                or ""
            ).strip()
            if not brand_name:
                continue
            pattern = rf"^\s{{0,3}}#{{1,6}}\s+.*\b{_re.escape(brand_name)}\b.*$"
            matches = _re.findall(pattern, text, flags=_re.IGNORECASE | _re.MULTILINE)
            if matches:
                message = str(raw_rule.get("message") or "").strip() or (
                    f"Standalone section heading for {brand_name!r} is not allowed."
                )
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message=message,
                    matches=[str(m) for m in matches[:10]],
                ))

        elif rule_type == "forbidden_terms":
            terms = [str(t).strip() for t in (raw_rule.get("terms") or []) if str(t).strip()]
            matches = [
                term for term in terms
                if _re.search(rf"\b{_re.escape(term)}\b", text, flags=_re.IGNORECASE)
            ]
            if matches:
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message="Forbidden or discouraged terms found: " + ", ".join(matches),
                    matches=matches,
                ))

        elif rule_type == "forbidden_patterns":
            patterns = [str(p).strip() for p in (raw_rule.get("patterns") or []) if str(p).strip()]
            matches = []
            for pattern in patterns:
                if _re.search(pattern, text, flags=_re.IGNORECASE):
                    matches.append(pattern)
            if matches:
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message="Forbidden or discouraged patterns found: " + ", ".join(matches),
                    matches=matches,
                ))

        elif rule_type == "duplicate_heading":
            level = raw_rule.get("level")
            try:
                level_int = int(level) if level is not None else None
            except (TypeError, ValueError):
                level_int = None
            counts: dict[str, int] = {}
            display_by_norm: dict[str, str] = {}
            for heading in heading_entries:
                if level_int is not None and heading["level"] != level_int:
                    continue
                normalized = heading["normalized"]
                counts[normalized] = counts.get(normalized, 0) + 1
                display_by_norm.setdefault(normalized, heading["text"])
            duplicates = [
                display_by_norm[key]
                for key, count in counts.items()
                if count > int(raw_rule.get("max", 1))
            ]
            if duplicates:
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message="Duplicate Markdown headings found: " + ", ".join(duplicates),
                    matches=duplicates,
                ))

        elif rule_type == "max_heading_occurrences":
            patterns = [
                str(p).strip()
                for p in (raw_rule.get("heading_patterns") or raw_rule.get("patterns") or [])
                if str(p).strip()
            ]
            max_count = int(raw_rule.get("max", 1))
            matches = [
                heading["text"]
                for heading in heading_entries
                if any(_heading_pattern_matches(heading["text"], pattern) for pattern in patterns)
            ]
            if patterns and len(matches) > max_count:
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message=(
                        f"Heading patterns {patterns!r} appear {len(matches)} times; "
                        f"maximum allowed is {max_count}."
                    ),
                    matches=matches,
                ))

        elif rule_type == "cooccurring_headings":
            patterns = [
                str(p).strip()
                for p in (raw_rule.get("heading_patterns") or raw_rule.get("patterns") or [])
                if str(p).strip()
            ]
            present = [
                pattern for pattern in patterns
                if any(_heading_pattern_matches(heading["text"], pattern) for heading in heading_entries)
            ]
            if patterns and len(present) == len(patterns):
                add_issue(_quality_gate_issue(
                    rule=raw_rule,
                    message="Co-occurring headings found: " + ", ".join(present),
                    matches=present,
                ))

    score_cap = 10.0
    if failures:
        score_cap = float(quality_gate.get("blocker_score_cap", 6.0))
    elif warnings:
        score_cap = float(quality_gate.get("warning_score_cap", 8.0))

    status_bits = _quality_gate_status(
        enabled=True,
        failures=failures,
        warnings=warnings,
        revise_required=bool(failures),
    )
    return {
        "enabled": True,
        **status_bits,
        "triggers": ["blocker_failure"] if failures else [],
        "score_cap": score_cap,
        "failures": failures,
        "warnings": warnings,
        "failure_count": len(failures),
        "warning_count": len(warnings),
    }


def _apply_quality_gate_to_review(
    review_result: dict[str, Any],
    quality_gate_result: dict[str, Any],
    quality_gate_config: dict[str, Any] | None = None,
    *,
    include_review_triggers: bool = True,
) -> dict[str, Any]:
    if not isinstance(review_result, dict):
        review_result = {}

    quality_gate_config = quality_gate_config if isinstance(quality_gate_config, dict) else {}
    quality_gate_result = dict(quality_gate_result or {})
    quality_gate_result.setdefault("failures", [])
    quality_gate_result.setdefault("warnings", [])
    quality_gate_result.setdefault("triggers", [])
    quality_gate_result["failures"] = list(quality_gate_result.get("failures") or [])
    quality_gate_result["warnings"] = list(quality_gate_result.get("warnings") or [])
    quality_gate_result["triggers"] = list(quality_gate_result.get("triggers") or [])

    review_result["quality_gate"] = quality_gate_result
    issues = review_result.get("issues")
    if not isinstance(issues, list):
        issues = []
    issues = [issue for issue in issues if not str(issue).startswith("Quality Gate ")]
    review_result["issues"] = issues

    if "llm_overall_score" not in review_result and review_result.get("overall_score") is not None:
        review_result["llm_overall_score"] = review_result.get("overall_score")

    if quality_gate_result.get("enabled") and include_review_triggers:
        try:
            current_score = float(review_result.get("overall_score", 0))
        except (TypeError, ValueError):
            current_score = 0.0

        if quality_gate_config.get("revise_below_score"):
            try:
                min_score = float(quality_gate_config.get("min_overall_score", 0))
            except (TypeError, ValueError):
                min_score = 0.0
            if min_score and current_score < min_score:
                quality_gate_result["failures"].append({
                    "rule_id": "overall_score_below_threshold",
                    "type": "overall_score_threshold",
                    "severity": "blocker",
                    "message": f"Overall score {current_score:g} is below required threshold {min_score:g}.",
                    "matches": [str(current_score)],
                })
                quality_gate_result["triggers"].append("overall_score_below_threshold")

        citation_alignment = review_result.get("citation_alignment")
        if (
            quality_gate_config.get("citation_alignment_as_blocker")
            and isinstance(citation_alignment, dict)
            and citation_alignment.get("required")
            and not citation_alignment.get("ok", True)
        ):
            if not any(f.get("rule_id") == "citation_alignment_failed" for f in quality_gate_result["failures"]):
                primary_action = citation_alignment.get("primary_action") or "unknown"
                quality_gate_result["failures"].append({
                    "rule_id": "citation_alignment_failed",
                    "type": "citation_alignment",
                    "severity": "blocker",
                    "message": (
                        "Content did not visibly respond to Citation Analysis "
                        f"primary_action={primary_action}."
                    ),
                    "matches": [str(primary_action)],
                })
                quality_gate_result["triggers"].append("citation_alignment_failed")

        llm_issue_patterns = [
            str(pattern).strip()
            for pattern in (quality_gate_config.get("llm_issue_blocker_patterns") or [])
            if str(pattern).strip()
        ]
        issue_texts = [str(issue) for issue in issues]
        for pattern in llm_issue_patterns:
            matches = [
                issue for issue in issue_texts
                if _re.search(_re.escape(pattern), issue, flags=_re.IGNORECASE)
            ]
            if matches:
                rule_id = f"llm_issue_blocker:{pattern}"
                if not any(f.get("rule_id") == rule_id for f in quality_gate_result["failures"]):
                    quality_gate_result["failures"].append({
                        "rule_id": rule_id,
                        "type": "llm_issue_blocker",
                        "severity": "blocker",
                        "message": f"LLM review issue matched blocker pattern {pattern!r}.",
                        "matches": matches[:3],
                    })
                    quality_gate_result["triggers"].append(rule_id)

        warning_rule_ids = {
            str(rule_id)
            for rule_id in (quality_gate_config.get("revise_on_warning_rule_ids") or [])
            if str(rule_id)
        }
        warning_matches = [
            str(warning.get("rule_id"))
            for warning in quality_gate_result["warnings"]
            if str(warning.get("rule_id")) in warning_rule_ids
        ]
        if warning_matches:
            for rule_id in sorted(set(warning_matches)):
                quality_gate_result["triggers"].append(f"warning_rule_requires_revise:{rule_id}")
        elif quality_gate_config.get("revise_on_warning") and quality_gate_result["warnings"]:
            quality_gate_result["triggers"].append("warning_requires_revise")

    failures = quality_gate_result.get("failures") or []
    warnings = quality_gate_result.get("warnings") or []
    triggers = list(dict.fromkeys(str(t) for t in (quality_gate_result.get("triggers") or []) if str(t)))
    revise_required = bool(
        failures
        or any(trigger.startswith("warning_rule_requires_revise:") for trigger in triggers)
        or "warning_requires_revise" in triggers
    )
    status_override = None
    if (
        not include_review_triggers
        and quality_gate_result.get("status") in {"revised", "needs_human_review"}
    ):
        status_override = str(quality_gate_result.get("status"))

    quality_gate_result.update(_quality_gate_status(
        enabled=bool(quality_gate_result.get("enabled")),
        failures=failures,
        warnings=warnings,
        revise_required=revise_required,
        human_review_required=bool(quality_gate_result.get("human_review_required")),
        status_override=status_override,
    ))
    quality_gate_result["triggers"] = triggers
    quality_gate_result["failure_count"] = len(failures)
    quality_gate_result["warning_count"] = len(warnings)

    if quality_gate_result.get("enabled"):
        if failures:
            quality_gate_result["score_cap"] = float(quality_gate_config.get(
                "blocker_score_cap",
                quality_gate_result.get("score_cap", 6.0),
            ))
        elif warnings:
            quality_gate_result["score_cap"] = float(quality_gate_config.get(
                "warning_score_cap",
                quality_gate_result.get("score_cap", 8.0),
            ))
        else:
            quality_gate_result["score_cap"] = float(quality_gate_result.get("score_cap", 10.0))

    if quality_gate_result.get("enabled"):
        for failure in reversed(quality_gate_result.get("failures") or []):
            issues.insert(0, f"Quality Gate blocker [{failure.get('rule_id')}]: {failure.get('message')}")
        for warning in reversed(quality_gate_result.get("warnings") or []):
            issues.insert(0, f"Quality Gate warning [{warning.get('rule_id')}]: {warning.get('message')}")

        try:
            current_score = float(review_result.get("overall_score", 0))
        except (TypeError, ValueError):
            current_score = 0.0
        score_cap = float(quality_gate_result.get("score_cap", 10.0))
        if current_score > score_cap:
            review_result["overall_score"] = score_cap

    review_result["quality_gate"] = quality_gate_result
    return review_result


def _mark_quality_gate_after_revision(quality_gate_result: dict[str, Any]) -> dict[str, Any]:
    revised_gate = dict(quality_gate_result or {})
    failures = list(revised_gate.get("failures") or [])
    warnings = list(revised_gate.get("warnings") or [])
    if failures:
        revised_gate.update(_quality_gate_status(
            enabled=bool(revised_gate.get("enabled", True)),
            failures=failures,
            warnings=warnings,
            revise_required=False,
            human_review_required=True,
            status_override="needs_human_review",
        ))
    else:
        revised_gate.update(_quality_gate_status(
            enabled=bool(revised_gate.get("enabled", True)),
            failures=[],
            warnings=warnings,
            revise_required=False,
            status_override="revised",
        ))
    revised_gate["failures"] = failures
    revised_gate["warnings"] = warnings
    revised_gate["failure_count"] = len(failures)
    revised_gate["warning_count"] = len(warnings)
    return revised_gate


def _append_post_revision_failure(
    quality_gate_result: dict[str, Any],
    *,
    rule_id: str,
    issue_type: str,
    message: str,
    matches: list[str] | None = None,
) -> None:
    failures = quality_gate_result.setdefault("failures", [])
    if any(failure.get("rule_id") == rule_id for failure in failures):
        return
    failures.append({
        "rule_id": rule_id,
        "type": issue_type,
        "severity": "blocker",
        "message": message,
        "matches": matches or [],
    })
    triggers = quality_gate_result.setdefault("triggers", [])
    if rule_id not in triggers:
        triggers.append(rule_id)


async def _build_post_revision_quality_review(
    *,
    revised_content: str,
    pre_revision_review: dict[str, Any],
    quality_gate_config: dict[str, Any] | None,
    metric_defs: list[dict[str, Any]],
    include_data_disclosure: bool,
    brand_context: dict[str, Any],
    content_type: str,
    publish_platform: str,
    citation_analysis_result: dict[str, Any] | None,
    official_website_discovery: Any = None,
    resource_link_policy_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the final review object from the revised content, not stale issues.

    The initial LLM review is still useful audit evidence, but after a Revise
    pass the user-facing ``quality_review`` must describe the final Markdown.
    """
    pre_revision_review = copy.deepcopy(pre_revision_review or {})
    quality_gate_config = quality_gate_config if isinstance(quality_gate_config, dict) else {}
    issues: list[str] = []
    text = revised_content or ""
    lowered_content = text.lower()

    disclosure_present = True
    if include_data_disclosure and text:
        disclosure_present = (
            "## 数据依据" in text
            or "data sources" in lowered_content
        )
    if include_data_disclosure and not disclosure_present:
        issues.append("内容缺失「数据依据 (Data Sources)」章节。")

    framework_coverage = _evaluate_framework_coverage(
        text,
        metric_defs,
        quality_gate_config,
    )
    framework_missing = list(framework_coverage.get("missing") or [])
    if framework_missing:
        issues.append(f"内容未覆盖 RATF 维度: {', '.join(framework_missing)}")

    primary_brand_name = _extract_primary_brand_name(brand_context)
    require_brand_mention = bool(
        primary_brand_name
        and (
            content_type in _LONGFORM_CONTENT_TYPES
            or content_type in _REPORT_CONTENT_TYPES
            or str(publish_platform).lower() == "reddit"
        )
    )
    integrity_issues = _detect_content_integrity_issues(
        text,
        brand_name=primary_brand_name,
        require_brand_mention=require_brand_mention,
    )
    integrity_issues.extend(_detect_brand_density_issues(
        text,
        brand_name=primary_brand_name,
        quality_gate_config=quality_gate_config,
    ))
    issues.extend(integrity_issues)

    citation_alignment = _evaluate_citation_alignment(
        text,
        citation_analysis_result,
        quality_gate_config,
    )
    citation_review_mode = str(
        quality_gate_config.get("citation_alignment_review_mode") or ""
    ).lower()
    if (
        citation_review_mode in {"llm", "hybrid"}
        and isinstance(citation_analysis_result, dict)
        and citation_analysis_result.get("enabled")
    ):
        citation_alignment = await _review_citation_alignment_with_llm(
            generated_content=text,
            citation_analysis_result=citation_analysis_result,
            base_alignment=citation_alignment,
            mode=citation_review_mode,
        )
    if citation_alignment.get("required") and not citation_alignment.get("ok", True):
        issues.append(
            "内容未明显响应 Citation Analysis 的 primary_action="
            f"{citation_alignment.get('primary_action')}。"
        )

    final_gate = _run_configured_quality_gate(
        text,
        quality_gate_config,
        context={"brand_name": primary_brand_name},
    )
    if framework_missing:
        _append_post_revision_failure(
            final_gate,
            rule_id="post_revision_framework_missing",
            issue_type="framework_coverage",
            message=f"Revised content still misses RATF dimensions: {', '.join(framework_missing)}.",
            matches=framework_missing,
        )
    if integrity_issues:
        _append_post_revision_failure(
            final_gate,
            rule_id="post_revision_integrity_failed",
            issue_type="content_integrity",
            message="Revised content still has integrity issues.",
            matches=integrity_issues[:3],
        )
    if (
        quality_gate_config.get("citation_alignment_as_blocker")
        and citation_alignment.get("required")
        and not citation_alignment.get("ok", True)
    ):
        _append_post_revision_failure(
            final_gate,
            rule_id="citation_alignment_failed",
            issue_type="citation_alignment",
            message=(
                "Revised content did not visibly respond to Citation Analysis "
                f"primary_action={citation_alignment.get('primary_action')}."
            ),
            matches=[str(citation_alignment.get("primary_action") or "")],
        )

    helpful_resource_link_policy = _evaluate_official_helpful_resource_link_policy(
        text,
        content_type=content_type,
        publish_platform=publish_platform,
        brand_context=brand_context,
        official_website_discovery=official_website_discovery,
        template_config={"resource_link_policy": resource_link_policy_config or {}},
    )
    if helpful_resource_link_policy.get("failures"):
        resource_rule = _resource_link_policy_rule({"resource_link_policy": resource_link_policy_config or {}})
        invalid_urls = [
            str(link.get("url") or link.get("domain") or "")
            for link in helpful_resource_link_policy.get("failures") or []
            if str(link.get("url") or link.get("domain") or "")
        ]
        issues.append(
            "Helpful Resources 包含未通过 Official Website Discovery 验证的链接: "
            + ", ".join(invalid_urls[:5])
            + "。"
        )
        _append_post_revision_failure(
            final_gate,
            rule_id=resource_rule["id"],
            issue_type=resource_rule["type"],
            message=resource_rule["message"],
            matches=invalid_urls[:5],
        )

    verified_link_preservation = _evaluate_verified_markdown_link_preservation(
        text,
        pre_revision_review=pre_revision_review,
        content_type=content_type,
        publish_platform=publish_platform,
        official_website_discovery=official_website_discovery,
        template_config={"resource_link_policy": resource_link_policy_config or {}},
    )
    if verified_link_preservation.get("missing_links"):
        preservation_rule = _verified_link_preservation_rule({
            "resource_link_policy": resource_link_policy_config or {}
        })
        missing_urls = [
            str(link.get("url") or link.get("normalized_url") or "")
            for link in verified_link_preservation.get("missing_links") or []
            if str(link.get("url") or link.get("normalized_url") or "")
        ]
        issues.append(
            "修订后删除了已验证的正文 Markdown 链接: "
            + ", ".join(missing_urls[:5])
            + "。"
        )
        _append_post_revision_failure(
            final_gate,
            rule_id=preservation_rule["id"],
            issue_type=preservation_rule["type"],
            message=preservation_rule["message"],
            matches=missing_urls[:5],
        )

    revised_gate = _mark_quality_gate_after_revision(final_gate)
    min_score = 8.0
    try:
        min_score = float(quality_gate_config.get("min_overall_score", 8.0))
    except (TypeError, ValueError):
        min_score = 8.0
    try:
        llm_score = float(
            pre_revision_review.get("llm_overall_score", pre_revision_review.get("overall_score", min_score))
        )
    except (TypeError, ValueError):
        llm_score = min_score

    final_review = {
        "scores": pre_revision_review.get("scores", []),
        "llm_overall_score": pre_revision_review.get("llm_overall_score", pre_revision_review.get("overall_score")),
        "overall_score": max(llm_score, min_score) if revised_gate.get("passed") else min(llm_score, 6.0),
        "improvement_suggestions": pre_revision_review.get("improvement_suggestions", []),
        "summary": (
            "Content was revised after Quality Gate review. The visible review fields now describe "
            "the revised final content; the original review is stored separately as pre_revision_quality_review."
        ),
        "issues": issues,
        "framework_coverage": {
            **framework_coverage,
        },
        "disclosure_coverage": {
            "required": bool(include_data_disclosure),
            "present": bool(disclosure_present),
            "ok": (not include_data_disclosure) or disclosure_present,
        },
        "content_integrity": {
            "ok": not integrity_issues,
            "issues": integrity_issues,
            "current_year": _current_runtime_datetime().year,
            "brand_name": primary_brand_name or None,
            "brand_mention_count": _count_brand_mentions(text, primary_brand_name) if primary_brand_name else None,
        },
        "citation_alignment": citation_alignment,
        "helpful_resource_link_policy": helpful_resource_link_policy,
        "verified_link_preservation": verified_link_preservation,
        "pre_revision_issue_count": len(pre_revision_review.get("issues") or []),
    }
    return _apply_quality_gate_to_review(
        final_review,
        revised_gate,
        quality_gate_config,
        include_review_triggers=False,
    )


def _build_quality_gate_revision_prompt(
    *,
    generated_content: str,
    quality_gate_result: dict[str, Any],
    content_type: str,
    publish_platform: str,
    brand_context: dict[str, Any],
    template_runtime_config: dict[str, Any],
    citation_analysis_result: dict[str, Any] | None = None,
    attempt_number: int = 1,
    max_attempts: int = 1,
) -> str:
    failures = quality_gate_result.get("failures") or []
    warnings = quality_gate_result.get("warnings") or []
    issue_payload = {
        "failures": failures,
        "warnings": warnings,
    }
    quality_gate_config = (
        template_runtime_config.get("quality_gate")
        if isinstance(template_runtime_config, dict)
        else {}
    )
    quality_gate_config = quality_gate_config if isinstance(quality_gate_config, dict) else {}

    def _coerce_guidance_lines(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    revision_guidance = quality_gate_config.get("revision_guidance") or {}
    revision_guidance = revision_guidance if isinstance(revision_guidance, dict) else {}
    configured_lines = [
        *_coerce_guidance_lines(revision_guidance.get("general")),
        *_coerce_guidance_lines(revision_guidance.get(f"round_{attempt_number}")),
    ]
    configured_stage_instruction = ""
    if configured_lines:
        configured_stage_instruction = "\n## 模板配置的 Revise 指令\n" + "\n".join(
            f"- {line}" for line in configured_lines
        ) + "\n"

    resource_policy = _resource_link_policy_config(template_runtime_config)
    resource_revision_lines: list[str] = []
    resource_revision_instruction = str(resource_policy.get("revision_instruction") or "").strip()
    if resource_revision_instruction:
        resource_revision_lines.append(resource_revision_instruction)
    if (
        _resource_link_policy_applies(
            content_type=content_type,
            publish_platform=publish_platform,
            template_config=template_runtime_config,
        )
        and resource_policy.get("preserve_verified_markdown_links") is not False
    ):
        preservation_instruction = str(resource_policy.get("preservation_instruction") or "").strip()
        if not preservation_instruction:
            preservation_instruction = (
                "保留原文中已属于 verified URL pool 的 Markdown links；"
                "只能移除或转纯文本未验证链接，不能把已验证链接改成纯文本。"
            )
        resource_revision_lines.append(preservation_instruction)
    resource_revision_block = "".join(f"- {line}\n" for line in resource_revision_lines)

    stage_instruction = configured_stage_instruction
    return f"""你是内容修正编辑。请基于 Quality Gate 的失败项，对下面 Markdown 内容做最小必要修正。

## 修正原则
- 输出完整修正后的 Markdown，不要解释，不要输出 JSON。
- 优先修复 failures；warnings 只做低风险局部修正。
- 不要全文重写，尽量保留原文章结构、语气和已有论点。
- 不要引入无法验证的新事实、数字、竞品能力、价格、发布时间、算法承诺或结果承诺。
{resource_revision_block.rstrip()}
- 如果需要新增缺失章节，只新增必要章节，并放在最自然的位置。
- Reddit 内容保持社区讨论语气；官网内容保持可信、克制、可发布的产品教育语气。

{stage_instruction}

## 内容类型
{content_type}

## 发布平台
{publish_platform}

## 品牌信息
{json.dumps(brand_context, ensure_ascii=False, indent=2) if brand_context else "未提供"}

{_build_platform_instruction(publish_platform, template_runtime_config)}
{_build_template_instruction(template_runtime_config)}
{_build_citation_analysis_instruction(citation_analysis_result)}

## Quality Gate 失败项
{json.dumps(issue_payload, ensure_ascii=False, indent=2)}

## 原始 Markdown
{generated_content}
"""


def _build_search_grounding_instruction(enabled: bool) -> str:
    if not enabled:
        return ""
    return """
## Search Grounding 要求
本次任务已开启 Google Search Grounding。对产品参数、竞品信息、价格、发布时间、市场动态、法规/政策、榜单、评测结论等易变化事实，请优先基于联网检索结果生成。

执行规则：
- 优先采用官方站点、产品文档、新闻稿、可信评测、权威媒体或行业报告。
- 不要把搜索结果、用户提供的 Product Facts、品牌画像混为一谈；如信息冲突，请标注不确定性，并优先保留用户提供的硬事实。
- 关键事实后尽量保留来源名称或链接；Content Brief 需单独列出建议引用来源。
- 无法通过搜索确认的信息不要编造，可写明“未能确认”或改写为保守表述。
"""


def _coerce_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _parse_strategy_json_string(value: str) -> Any:
    stripped = (value or "").strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except Exception:
        return None


def _extract_nested_strategy_payload(item: Any) -> Any:
    if isinstance(item, str):
        parsed = _parse_strategy_json_string(item)
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
        if not isinstance(candidate, str):
            continue
        parsed = _parse_strategy_json_string(candidate)
        if isinstance(parsed, dict) and isinstance(parsed.get("strategies"), list):
            return parsed
    return None


def _normalize_strategy_result(value: Any) -> dict[str, Any]:
    """Normalize strategy_generation JSON into the contract shape.

    Gemini occasionally returns the requested ``strategies`` array as the root
    JSON value. The pipeline contract is an object with ``strategies`` and
    ``strategy_summary``; normalize the common shape drift instead of failing
    the whole Discover then Generate flow.
    """
    if isinstance(value, dict):
        strategies = value.get("strategies")
        if strategies is None:
            value["strategies"] = []
        elif not isinstance(strategies, list):
            value["strategies"] = [strategies]
        if len(value.get("strategies") or []) == 1:
            nested = _extract_nested_strategy_payload(value["strategies"][0])
            if isinstance(nested, dict):
                return _normalize_strategy_result(nested)
        if not isinstance(value.get("strategy_summary"), str):
            count = len(value.get("strategies") or [])
            value["strategy_summary"] = f"Generated {count} strategy option{'s' if count != 1 else ''}."
        return value

    if isinstance(value, list):
        if len(value) == 1:
            nested = _extract_nested_strategy_payload(value[0])
            if isinstance(nested, dict):
                return _normalize_strategy_result(nested)
        return {
            "strategies": value,
            "strategy_summary": f"Generated {len(value)} strategy option{'s' if len(value) != 1 else ''}.",
        }

    raise RuntimeError(
        "strategy_generation returned invalid JSON shape; expected object or strategies array"
    )


def _normalize_depth_key(depth: str | None) -> str:
    key = (depth or "standard").strip().lower()
    # ``comprehensive`` is a display alias. Stored tasks and DB dictionaries
    # continue to use the stable key ``authority`` for backward compatibility.
    return "authority" if key == "comprehensive" else key


def _resolve_content_token_budget(content_type: str, depth: str | None) -> int:
    """Resolve max output tokens by content shape and depth.

    Short-form outputs keep their historical caps so existing FAQ / brief /
    platform-post templates do not become unexpectedly verbose. Article-like
    content scales with depth to support Standard / Deep / Comprehensive.
    """
    if content_type in _SHORT_CONTENT_TOKEN_BUDGET:
        return _SHORT_CONTENT_TOKEN_BUDGET[content_type]
    if content_type in _REPORT_CONTENT_TYPES:
        if _normalize_depth_key(depth) in _SEGMENTED_DEPTHS:
            return _DEPTH_TOKEN_BUDGET.get(_normalize_depth_key(depth), 8192)
        return 4096
    if content_type in _LONGFORM_CONTENT_TYPES:
        return _DEPTH_TOKEN_BUDGET.get(_normalize_depth_key(depth), 8192)
    return 8192


def _should_use_segmented_generation(content_type: str, depth: str | None) -> bool:
    """Use outline/section assembly for long-form Deep and Comprehensive."""
    return (
        content_type in _LONGFORM_CONTENT_TYPES
        and _normalize_depth_key(depth) in _SEGMENTED_DEPTHS
    )


def _should_use_report_segmented_generation(content_type: str, depth: str | None) -> bool:
    """Use report-style segmented generation for Deep/Comprehensive reports."""
    return (
        content_type in _REPORT_CONTENT_TYPES
        and _normalize_depth_key(depth) in _SEGMENTED_DEPTHS
    )


async def _load_template_runtime_config(pool, task_id: str) -> dict[str, Any]:
    """Load template runtime metadata used by content prompts.

    This intentionally reads from ``wizard_config`` JSONB instead of adding
    columns. Platform playbooks and depth profiles are template-configured
    behavior, so Admin can adjust them later without a schema migration.
    """
    row = await pool.fetchrow(
        """
        SELECT t.name, t.default_prompt, t.defaults, t.wizard_config
        FROM geo_agent_tasks agt
        JOIN geo_report_templates t ON agt.template_id = t.id::text
        WHERE agt.id = $1::uuid
        """,
        task_id,
    )
    if not row:
        return {}

    defaults = _coerce_json_object(row["defaults"])
    wizard_config = _coerce_json_object(row["wizard_config"])
    steps = _coerce_json_object(wizard_config.get("steps"))
    generation_config = _coerce_json_object(steps.get("generation_config"))
    content_type_cfg = _coerce_json_object(steps.get("content_type"))

    return {
        "template_name": row["name"],
        "default_prompt": row["default_prompt"],
        "template_group": wizard_config.get("template_group") or defaults.get("template_group"),
        "platform_profile": wizard_config.get("platform_profile") or defaults.get("platform_profile"),
        "platform_playbook": wizard_config.get("platform_playbook") or defaults.get("platform_playbook"),
        "depth_profiles": wizard_config.get("depth_profiles") or defaults.get("depth_profiles") or {},
        "generation_requirements": wizard_config.get("generation_requirements") or defaults.get("generation_requirements"),
        "ratf_metric_jobs": wizard_config.get("ratf_metric_jobs") or defaults.get("ratf_metric_jobs") or {},
        "ratf_rendering": wizard_config.get("ratf_rendering") or defaults.get("ratf_rendering") or {},
        "prompt_input_policy": wizard_config.get("prompt_input_policy") or defaults.get("prompt_input_policy") or {},
        "reddit_native_contract": wizard_config.get("reddit_native_contract") or defaults.get("reddit_native_contract") or {},
        "experience_style_notes": wizard_config.get("experience_style_notes") or defaults.get("experience_style_notes") or {},
        "community_brief": wizard_config.get("community_brief") or defaults.get("community_brief") or {},
        "derived_prompt_artifacts": wizard_config.get("derived_prompt_artifacts") or defaults.get("derived_prompt_artifacts") or {},
        "segmented_generation": wizard_config.get("segmented_generation") or defaults.get("segmented_generation") or {},
        "quality_gate": wizard_config.get("quality_gate") or defaults.get("quality_gate") or {},
        "resource_link_policy": wizard_config.get("resource_link_policy") or defaults.get("resource_link_policy") or {},
        "reddit_research": wizard_config.get("reddit_research") or defaults.get("reddit_research") or {},
        "citation_analysis": wizard_config.get("citation_analysis") or defaults.get("citation_analysis") or {},
        "citation_analysis_step": steps.get("citation_analysis") or {},
        "default_publish_platform": generation_config.get("default_publish_platform") or defaults.get("publish_platform"),
        "default_depth": generation_config.get("default_depth") or defaults.get("depth"),
        "default_content_type": content_type_cfg.get("default") or defaults.get("content_type"),
    }


def _build_platform_instruction(publish_platform: str, template_config: dict[str, Any]) -> str:
    platform = (publish_platform or template_config.get("default_publish_platform") or "").strip()
    profile = (template_config.get("platform_profile") or platform or "").strip().lower()
    playbook = template_config.get("platform_playbook")

    lines: list[str] = []
    if playbook:
        lines += [
            "## 平台适配规则（来自模板配置）",
            json.dumps(playbook, ensure_ascii=False, indent=2)
            if isinstance(playbook, (dict, list))
            else str(playbook),
            "",
        ]

    if (profile == "reddit" or platform.lower() == "reddit") and not playbook:
        lines += [
            "## Reddit 发布适配（硬约束）",
            "- 标题要像真实讨论帖、经验分享帖或问题帖，避免广告语、官网标题、白皮书标题。",
            "- 正文要先回应 subreddit 用户常见疑问，再自然带出品牌/产品；不要把品牌卖点堆成硬广。",
            "- 使用社区语气：具体、坦诚、可讨论，可承认取舍；避免企业公关稿、官网 landing page 或过度修饰的营销语。",
            "- 不要伪造第一人称使用经历、投票数据、Reddit 评论、用户评价或 subreddit 名称；没有输入证据时保持保守。",
            "- 结构上优先使用短段落、自然小节和必要的短清单；避免表格、矩阵、FAQ 堆叠和过度结构化。",
            "- CTA 只能低压、自然；优先给出选型建议、检查清单、实操步骤或讨论问题。",
            "",
        ]

    return "\n".join(lines)


def _hostname_from_url(url: str) -> str:
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return ""
    return (parsed.hostname or "").lower().removeprefix("www.")


def _normalize_resource_url(url: Any) -> str:
    """Normalize URLs for exact Helpful Resources allowlist comparison."""
    if not isinstance(url, str):
        return ""
    candidate = url.strip().strip("<>`'\"").rstrip(".,)")
    if not candidate:
        return ""
    try:
        parsed = urlparse(candidate)
    except Exception:
        return ""
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        return ""
    netloc = host
    if parsed.port and not (
        (scheme == "http" and parsed.port == 80)
        or (scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{host}:{parsed.port}"
    path = parsed.path or ""
    if path != "/":
        path = path.rstrip("/")
    else:
        path = ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def _extract_markdown_links(text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in _re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text or "", flags=_re.IGNORECASE):
        url = match.group(2).strip().rstrip(".,)")
        links.append({
            "label": match.group(1).strip(),
            "url": url,
            "normalized_url": _normalize_resource_url(url),
            "domain": _hostname_from_url(url),
        })
    return links


def _extract_heading_section_bodies(text: str, heading_patterns: list[str]) -> list[str]:
    if not text:
        return []
    patterns = [p for p in heading_patterns if p]
    if not patterns:
        return []
    heading_re = "|".join(f"(?:{p})" for p in patterns)
    return [
        match.group("body") or ""
        for match in _re.finditer(
            rf"(?ms)^\s{{0,3}}##\s+(?:{heading_re})\s*\n(?P<body>.*?)(?=^\s{{0,3}}##\s+|\Z)",
            text,
            flags=_re.IGNORECASE,
        )
    ]


def _verified_resource_pool_from_official_discovery(
    official_website_discovery: Any,
) -> list[dict[str, str]]:
    """Return exact, verified URLs discovered from the official website crawl.

    This intentionally ignores raw wizard input such as ``official_website_urls``.
    Those fields tell discovery what to crawl; they are not proof that an exact
    page exists and is publishable.
    """
    if not isinstance(official_website_discovery, dict):
        return []

    data = official_website_discovery.get("data")
    if not isinstance(data, (dict, list)):
        return []

    url_keys = {
        "url",
        "canonical_url",
        "canonicalUrl",
        "canonical",
        "href",
        "page_url",
        "pageUrl",
        "source_url",
        "sourceUrl",
        "resolved_url",
        "resolvedUrl",
    }
    title_keys = {
        "title",
        "page_title",
        "name",
        "label",
        "heading",
        "meta_title",
    }
    pool: dict[str, dict[str, str]] = {}

    def title_from_mapping(value: dict[str, Any]) -> str:
        for key in title_keys:
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return ""

    def visit(value: Any, inherited_title: str = "") -> None:
        if isinstance(value, dict):
            local_title = title_from_mapping(value) or inherited_title
            for key, raw in value.items():
                if key in url_keys and isinstance(raw, str):
                    normalized = _normalize_resource_url(raw)
                    if normalized:
                        pool.setdefault(normalized, {
                            "url": normalized,
                            "title": local_title,
                            "domain": _hostname_from_url(normalized),
                        })
                        if local_title and not pool[normalized].get("title"):
                            pool[normalized]["title"] = local_title
                visit(raw, local_title)
        elif isinstance(value, list):
            for item in value:
                visit(item, inherited_title)

    visit(data)
    return sorted(pool.values(), key=lambda item: item["url"])


def _verified_resource_url_set(official_website_discovery: Any) -> set[str]:
    return {
        item["url"]
        for item in _verified_resource_pool_from_official_discovery(official_website_discovery)
        if item.get("url")
    }


def _resource_link_policy_config(template_config: dict[str, Any] | None) -> dict[str, Any]:
    policy = (template_config or {}).get("resource_link_policy")
    return policy if isinstance(policy, dict) else {}


def _resource_link_policy_applies(
    *,
    content_type: str = "",
    publish_platform: str = "",
    template_config: dict[str, Any] | None = None,
) -> bool:
    policy = _resource_link_policy_config(template_config)
    if not policy or policy.get("enabled") is not True:
        return False

    def normalize_list(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value.strip().lower()} if value.strip() else set()
        if isinstance(value, list):
            return {str(item).strip().lower() for item in value if str(item).strip()}
        return set()

    content_types = normalize_list(policy.get("content_types") or policy.get("apply_to_content_types"))
    publish_platforms = normalize_list(policy.get("publish_platforms") or policy.get("apply_to_publish_platforms"))
    platform_profiles = normalize_list(policy.get("platform_profiles") or policy.get("apply_to_platform_profiles"))
    if content_types or publish_platforms or platform_profiles:
        profile = str((template_config or {}).get("platform_profile") or "").strip().lower()
        return (
            str(content_type or "").strip().lower() in content_types
            or str(publish_platform or "").strip().lower() in publish_platforms
            or profile in platform_profiles
        )
    return True


def _resource_link_policy_headings(template_config: dict[str, Any] | None) -> list[str]:
    policy = _resource_link_policy_config(template_config)
    headings = policy.get("section_headings")
    if not isinstance(headings, list) or not headings:
        headings = ["Helpful Resources", "Further Reading", "Related Resources", "Learn More"]
    return [str(heading).strip() for heading in headings if str(heading).strip()]


def _resource_heading_patterns(template_config: dict[str, Any] | None) -> list[str]:
    patterns: list[str] = []
    for heading in _resource_link_policy_headings(template_config):
        escaped = _re.escape(heading)
        if heading.lower() in {"helpful resources", "further reading", "related resources"}:
            patterns.append(rf"{escaped}(?:\s+for\s+[^\n]+)?")
        elif heading.lower() == "learn more":
            patterns.append(rf"{escaped}(?:\s+about\s+[^\n]+)?")
        else:
            patterns.append(escaped)
    return patterns


def _resource_link_policy_rule(template_config: dict[str, Any] | None) -> dict[str, str]:
    policy = _resource_link_policy_config(template_config)
    rule = policy.get("quality_gate_rule")
    rule = rule if isinstance(rule, dict) else {}
    return {
        "id": str(rule.get("id") or "resource_links_unverified"),
        "type": str(rule.get("type") or "resource_link_policy"),
        "message": str(
            rule.get("message")
            or "Resource links contain URLs outside the verified discovery URL pool."
        ),
    }


def _verified_link_preservation_rule(template_config: dict[str, Any] | None) -> dict[str, str]:
    policy = _resource_link_policy_config(template_config)
    rule = policy.get("verified_link_preservation_rule")
    rule = rule if isinstance(rule, dict) else {}
    return {
        "id": str(rule.get("id") or "verified_markdown_links_removed"),
        "type": str(rule.get("type") or "resource_link_policy"),
        "message": str(
            rule.get("message")
            or "Verified Markdown links were removed during revision."
        ),
    }


def _evaluate_verified_markdown_link_preservation(
    revised_content: str,
    *,
    pre_revision_review: dict[str, Any] | None = None,
    content_type: str = "",
    publish_platform: str = "",
    official_website_discovery: Any = None,
    template_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _resource_link_policy_applies(
        content_type=content_type,
        publish_platform=publish_platform,
        template_config=template_config,
    ):
        return {"required": False, "ok": True, "previous_verified_links": [], "missing_links": []}

    policy_cfg = _resource_link_policy_config(template_config)
    if policy_cfg.get("preserve_verified_markdown_links") is False:
        return {"required": False, "ok": True, "previous_verified_links": [], "missing_links": []}

    verified_urls = set(_verified_resource_url_set(official_website_discovery))
    previous_policy = (
        (pre_revision_review or {}).get("helpful_resource_link_policy")
        if isinstance(pre_revision_review, dict)
        else None
    )
    previous_policy = previous_policy if isinstance(previous_policy, dict) else {}
    for url in previous_policy.get("verified_resource_urls") or []:
        normalized = _normalize_resource_url(url)
        if normalized:
            verified_urls.add(normalized)

    previous_verified: list[dict[str, str]] = []
    seen_previous: set[str] = set()
    for link in previous_policy.get("links") or []:
        if not isinstance(link, dict):
            continue
        normalized = _normalize_resource_url(link.get("normalized_url") or link.get("url"))
        if not normalized or normalized not in verified_urls or normalized in seen_previous:
            continue
        previous_verified.append({
            "label": str(link.get("label") or "").strip(),
            "url": str(link.get("url") or normalized).strip(),
            "normalized_url": normalized,
            "domain": str(link.get("domain") or _hostname_from_url(normalized)).strip(),
        })
        seen_previous.add(normalized)

    if not previous_verified:
        return {
            "required": False,
            "ok": True,
            "previous_verified_links": [],
            "missing_links": [],
            "verified_resource_urls": sorted(verified_urls),
        }

    revised_verified_urls = {
        link.get("normalized_url")
        for link in _extract_markdown_links(revised_content)
        if link.get("normalized_url") in verified_urls
    }
    missing_links = [
        link for link in previous_verified
        if link.get("normalized_url") not in revised_verified_urls
    ]
    return {
        "required": True,
        "ok": not missing_links,
        "previous_verified_links": previous_verified,
        "missing_links": missing_links,
        "verified_resource_urls": sorted(verified_urls),
    }


def _evaluate_official_helpful_resource_link_policy(
    content: str,
    *,
    content_type: str = "",
    publish_platform: str = "",
    brand_context: dict[str, Any] | None = None,
    official_website_discovery: Any = None,
    template_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _resource_link_policy_applies(
        content_type=content_type,
        publish_platform=publish_platform,
        template_config=template_config,
    ):
        return {"required": False, "ok": True, "failures": [], "warnings": []}

    policy_cfg = _resource_link_policy_config(template_config)
    link_scope = str(policy_cfg.get("link_scope") or "resource_sections").strip().lower()
    if link_scope in {"all", "all_markdown", "all_markdown_links", "body"}:
        links = _extract_markdown_links(content)
    else:
        section_bodies = _extract_heading_section_bodies(
            content,
            _resource_heading_patterns(template_config),
        )
        links = [link for body in section_bodies for link in _extract_markdown_links(body)]
    if not links:
        return {
            "required": True,
            "ok": True,
            "failures": [],
            "warnings": [],
            "links": [],
            "verified_resource_urls": sorted(_verified_resource_url_set(official_website_discovery)),
        }

    verified_urls = _verified_resource_url_set(official_website_discovery)
    require_exact = policy_cfg.get("verified_url_match") != "none"
    failures = []
    for link in links:
        if require_exact and link.get("normalized_url") not in verified_urls:
            failures.append(link)

    return {
        "required": True,
        "ok": not failures,
        "verified_resource_urls": sorted(verified_urls),
        "links": links,
        "failures": failures,
        "warnings": [],
    }


def _sanitize_official_helpful_resources_to_verified_pool(
    content: str,
    *,
    content_type: str = "",
    publish_platform: str = "",
    template_config: dict[str, Any] | None = None,
    official_website_discovery: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Drop unverified Helpful Resources links from official-site articles.

    The model may invent plausible owned-domain paths. This sanitizer is
    deterministic: keep exact URLs from discovery, remove everything else, and
    delete the whole resources section when nothing publishable remains.
    """
    text = (content or "").strip()
    if not text or not _resource_link_policy_applies(
        content_type=content_type,
        publish_platform=publish_platform,
        template_config=template_config,
    ):
        return text, {"required": False, "ok": True, "removed_links": [], "kept_links": []}

    policy_cfg = _resource_link_policy_config(template_config)
    if policy_cfg.get("sanitize_generated_content") is False:
        return text, {"required": True, "ok": True, "removed_links": [], "kept_links": [], "skipped": True}

    verified_urls = _verified_resource_url_set(official_website_discovery)
    removed_links: list[dict[str, str]] = []
    kept_links: list[dict[str, str]] = []
    heading_patterns = _resource_heading_patterns(template_config)
    section_heading_re = "|".join(f"(?:{pattern})" for pattern in heading_patterns)
    output_heading = str(policy_cfg.get("output_heading") or "Helpful Resources").strip() or "Helpful Resources"

    def sanitize_section(match: _re.Match[str]) -> str:
        body = match.group("body") or ""
        kept_lines: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.rstrip()
            links = _extract_markdown_links(line)
            if links:
                valid_links = [link for link in links if link.get("normalized_url") in verified_urls]
                invalid_links = [link for link in links if link.get("normalized_url") not in verified_urls]
                removed_links.extend(invalid_links)
                kept_links.extend(valid_links)
                if valid_links and len(valid_links) == len(links):
                    kept_lines.append(line)
                continue
            if line.strip() and kept_lines:
                kept_lines.append(line)
        while kept_lines and not kept_lines[0].strip():
            kept_lines.pop(0)
        while kept_lines and not kept_lines[-1].strip():
            kept_lines.pop()
        if not kept_lines:
            return ""
        return f"## {output_heading}\n\n" + "\n".join(kept_lines).strip() + "\n\n"

    sanitized = _re.sub(
        rf"(?ms)^\s{{0,3}}##\s+(?:{section_heading_re})\s*\n(?P<body>.*?)(?=^\s{{0,3}}##\s+|\Z)",
        sanitize_section,
        text,
    ) if section_heading_re else text

    link_scope = str(policy_cfg.get("link_scope") or "resource_sections").strip().lower()
    sanitize_inline_links = policy_cfg.get("sanitize_inline_markdown_links") is True
    if sanitize_inline_links and link_scope in {"all", "all_markdown", "all_markdown_links", "body"}:
        def sanitize_inline_link(match: _re.Match[str]) -> str:
            label = match.group(1).strip()
            url = match.group(2).strip().rstrip(".,)")
            normalized = _normalize_resource_url(url)
            link = {
                "label": label,
                "url": url,
                "normalized_url": normalized,
                "domain": _hostname_from_url(url),
            }
            if normalized in verified_urls:
                kept_links.append(link)
                return match.group(0)
            removed_links.append(link)
            return label

        sanitized = _re.sub(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            sanitize_inline_link,
            sanitized,
            flags=_re.IGNORECASE,
        )

    sanitized = _re.sub(r"\n{3,}", "\n\n", sanitized).strip()
    return sanitized, {
        "required": True,
        "ok": not removed_links,
        "verified_resource_urls": sorted(verified_urls),
        "removed_links": removed_links,
        "kept_links": kept_links,
    }


def _build_official_publishable_resource_policy(
    content_type: str,
    publish_platform: str,
    template_config: dict[str, Any],
    brand_context: dict[str, Any] | None = None,
    official_website_discovery: Any = None,
) -> str:
    """Return template-configured resource/link policy for generation prompts."""
    if not _resource_link_policy_applies(
        content_type=content_type,
        publish_platform=publish_platform,
        template_config=template_config,
    ):
        return ""

    policy_cfg = _resource_link_policy_config(template_config)
    prompt_title = str(policy_cfg.get("prompt_title") or "Publishable Resource Link Policy").strip()
    configured_rules = [
        str(rule).strip()
        for rule in (policy_cfg.get("generation_rules") or [])
        if str(rule).strip()
    ]
    if not configured_rules:
        configured_rules = [
            "正文只能包含读者可直接阅读和发布的内容；不要输出编辑备注、SEO/AEO 操作说明或后台执行建议。",
            "Citation Analysis sources 只能用于学习结构、信息密度、FAQ 形态和内容缺口；不要默认把 Citation source URL 放进正文资源列表。",
            "资源列表只能引用已验证过的精确 URL；同一域名下未发现的路径也不能使用。",
        ]
    no_verified_instruction = str(
        policy_cfg.get("no_verified_urls_instruction")
        or "未识别到验证过的精确 URL；不要生成独立资源列表。"
    )
    verified_resources = _verified_resource_pool_from_official_discovery(official_website_discovery)
    if verified_resources:
        verified_lines = [
            f"  - {item.get('title') + ': ' if item.get('title') else ''}{item['url']}"
            for item in verified_resources[:20]
        ]
        verified_line = "\n".join(verified_lines)
    else:
        verified_line = f"  - {no_verified_instruction}"

    lines = [f"## {prompt_title}"]
    lines.extend(f"- {rule}" for rule in configured_rules)
    lines.extend([
        "- 当前允许的精确 URL：",
        verified_line,
        "",
    ])
    return "\n".join(lines)


def _build_depth_instruction(depth: str | None, template_config: dict[str, Any]) -> str:
    key = (depth or template_config.get("default_depth") or "standard").strip().lower()
    profiles = template_config.get("depth_profiles")
    profile = profiles.get(key) if isinstance(profiles, dict) else None

    if profile:
        return "\n".join([
            "## 内容深度要求（来自模板配置）",
            json.dumps(profile, ensure_ascii=False, indent=2)
            if isinstance(profile, (dict, list))
            else str(profile),
            "",
        ])

    defaults = {
        "quick": "快速版：保持简洁，优先输出可直接使用的核心内容。",
        "standard": "Standard：文章类内容建议 900-1200 words，覆盖核心论点、关键小节和简短结论；具体结构以模板 depth_profiles 为准。",
        "deep": "Deep：文章类内容建议 1800-2500 words，要求更完整的小节、示例和可执行建议；具体结构以模板 depth_profiles 为准。",
        "authority": "Comprehensive：文章类内容至少 2200 words，要求更完整的论证、证据组织和扩展结论；具体结构以模板 depth_profiles 为准。",
    }
    return f"## 内容深度要求\n{defaults.get(key, defaults['standard'])}\n"


def _build_template_instruction(template_config: dict[str, Any]) -> str:
    lines: list[str] = []
    default_prompt = str(template_config.get("default_prompt") or "").strip()
    if default_prompt:
        lines += [
            "## 模板默认指令",
            default_prompt,
            "",
        ]

    requirements = template_config.get("generation_requirements")
    if requirements:
        lines += [
            "## 模板补充要求",
            json.dumps(requirements, ensure_ascii=False, indent=2)
            if isinstance(requirements, (dict, list))
            else str(requirements),
            "",
        ]
    return "\n".join(lines)


def _build_reddit_discovery_instruction(reddit_discovery: Any) -> str:
    if not isinstance(reddit_discovery, dict):
        return ""
    data = reddit_discovery.get("data")
    if not isinstance(data, dict):
        return ""
    return "\n".join([
        "## Reddit Discover Insight（硬约束）",
        "以下是本次 Reddit Discover 得到的外部语境。生成策略和正文时必须使用它来决定社区问题、反对意见、内容角度和发布风险；不得编造未出现的 Reddit 帖子、评论、票数或 subreddit 规则。",
        json.dumps(data, ensure_ascii=False, indent=2),
        "",
    ])


def _build_official_website_discovery_instruction(official_website_discovery: Any) -> str:
    if not isinstance(official_website_discovery, dict):
        return ""
    data = official_website_discovery.get("data")
    if not isinstance(data, dict):
        return ""
    return "\n".join([
        "## Official Website Discover Insight（硬约束）",
        "以下是本次 Official Website Discover 基于客户官网文章 URL 得到的内容诊断。生成策略和正文时必须使用它来补齐官网内容短板、增强品牌可抽取性、完善 Use Case 覆盖、提升商业转化信息密度和品牌友好 FAQ；不得编造未读取到的官网内容、价格、功能、版本或客户案例。",
        json.dumps(data, ensure_ascii=False, indent=2),
        "",
    ])


def _build_citation_analysis_instruction(citation_analysis_result: Any) -> str:
    if not isinstance(citation_analysis_result, dict):
        return ""
    if not citation_analysis_result.get("enabled"):
        return ""
    brief = str(citation_analysis_result.get("citation_grounded_brief") or "").strip()
    if not brief:
        return ""
    return "\n".join([
        "## Citation Analysis Brief（硬约束）",
        "以下是基于 Citation data 聚合后的摘要。它是结构、可抽取性、品牌提及状态和内容动作的依据；只能使用聚合摘要，不要复述或展开完整页面正文。",
        brief,
        "",
    ])


def _text_from_jsonish(value: Any, *, max_chars: int = 1200) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:max_chars]
    try:
        return json.dumps(value, ensure_ascii=False)[:max_chars]
    except Exception:
        return str(value)[:max_chars]


def _is_reddit_native_prompt_mode(template_runtime_config: dict[str, Any]) -> bool:
    policy = template_runtime_config.get("prompt_input_policy")
    return isinstance(policy, dict) and policy.get("mode") == "reddit_native"


def _resolve_include_data_disclosure(
    *,
    default: bool,
    template_runtime_config: dict[str, Any],
) -> bool:
    policy = template_runtime_config.get("prompt_input_policy")
    policy = policy if isinstance(policy, dict) else {}
    explicit = (
        policy.get("data_disclosure_policy")
        or template_runtime_config.get("data_disclosure_policy")
    )
    explicit_normalized = str(explicit or "").strip().lower()
    if explicit_normalized in {"disabled", "off", "internal_only", "suppress_final_section", "none"}:
        return False
    if explicit_normalized in {"required", "on", "append_final_section"}:
        return True
    return bool(default)


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _artifact_definitions(template_runtime_config: dict[str, Any]) -> list[dict[str, Any]]:
    config = template_runtime_config.get("derived_prompt_artifacts")
    config = config if isinstance(config, dict) else {}
    definitions = config.get("output_artifacts") or config.get("artifacts")
    if not isinstance(definitions, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in definitions:
        if isinstance(item, dict) and str(item.get("key") or "").strip():
            normalized.append(item)
        elif isinstance(item, str) and item.strip():
            normalized.append({"key": item.strip(), "label": item.strip(), "fields": []})
    return normalized


def _artifact_definition_by_key(template_runtime_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key")): item for item in _artifact_definitions(template_runtime_config)}


def _default_artifact_definitions(template_runtime_config: dict[str, Any]) -> list[dict[str, Any]]:
    configured = _artifact_definitions(template_runtime_config)
    if configured:
        return configured
    return [
        {
            "key": "community_brief",
            "label": "Community Brief",
            "fields": [
                "community_tension",
                "reader_objections",
                "workflow_angle",
                "brand_safe_mention_angle",
                "things_to_avoid",
                "closing_discussion_question",
            ],
        },
        {
            "key": "experience_style_notes",
            "label": "Experience Style Notes",
            "fields": [
                "persona_frame",
                "workflow_texture",
                "skeptical_phrases",
                "allowed_experience_claims",
                "forbidden_experience_claims",
            ],
        },
    ]


def _build_prompt_artifact_preparation_prompt(
    *,
    template_runtime_config: dict[str, Any],
    raw_artifacts: dict[str, Any],
    brand_name: str,
) -> str:
    """Build a generic prompt that prepares final-prompt-safe artifacts.

    Template data owns the artifact names, fields, and writing policies. The
    code only supplies raw inputs and asks the model to return the configured
    JSON shape without inventing facts.
    """
    config = template_runtime_config.get("derived_prompt_artifacts")
    config = config if isinstance(config, dict) else {}
    policy = template_runtime_config.get("prompt_input_policy")
    policy = policy if isinstance(policy, dict) else {}
    contract = template_runtime_config.get("reddit_native_contract")
    contract = contract if isinstance(contract, dict) else {}
    definitions = _default_artifact_definitions(template_runtime_config)

    output_schema = {
        item["key"]: {
            field: "string | string[]"
            for field in _coerce_string_list(item.get("fields"))
        }
        for item in definitions
    }
    artifact_instructions = [
        {
            "key": item.get("key"),
            "label": item.get("label") or item.get("key"),
            "description": item.get("description") or "",
            "fields": _coerce_string_list(item.get("fields")),
            "rules": item.get("rules") or item.get("rendering_policy") or [],
        }
        for item in definitions
    ]

    return f"""You prepare template-specific prompt artifacts for a downstream content generator.

Do not write the final article. Do not copy raw internal strategy, citation, or discovery artifacts into the output. Compress them into the configured artifact schema.

## Template Artifact Instruction
{str(config.get("instruction") or config.get("purpose") or "Prepare concise final-prompt-safe artifacts according to the template configuration.")}

## Prompt Input Policy
{json.dumps(policy, ensure_ascii=False, indent=2, default=str)}

## Writing Contract
{json.dumps(contract, ensure_ascii=False, indent=2, default=str)}

## Brand
{brand_name or "Unknown"}

## Artifact Definitions
{json.dumps(artifact_instructions, ensure_ascii=False, indent=2, default=str)}

## Raw Inputs
{json.dumps(raw_artifacts, ensure_ascii=False, indent=2, default=str)[:24000]}

## Output JSON Schema
Return only JSON matching this shape:
{json.dumps(output_schema, ensure_ascii=False, indent=2, default=str)}
"""


def _render_artifact_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        lines = []
        for item in value:
            text = str(item if not isinstance(item, (dict, list)) else json.dumps(item, ensure_ascii=False)).strip()
            if text:
                lines.append(f"- {text}")
        return lines
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False, indent=2)]
    text = str(value).strip()
    return [text] if text else []


def _render_prepared_prompt_artifacts(
    *,
    template_runtime_config: dict[str, Any],
    prepared_artifacts: dict[str, Any],
) -> str:
    """Render prepared artifacts for the final prompt using template fields."""
    if not isinstance(prepared_artifacts, dict):
        return ""
    definitions = _default_artifact_definitions(template_runtime_config)
    sections: list[str] = []
    for definition in definitions:
        key = str(definition.get("key") or "").strip()
        if not key or key not in prepared_artifacts:
            continue
        artifact = prepared_artifacts.get(key)
        label = str(definition.get("label") or key).strip()
        fields = _coerce_string_list(definition.get("fields"))
        lines = [f"## {label}"]
        if isinstance(artifact, dict):
            rendered_any = False
            for field in fields or list(artifact.keys()):
                if field not in artifact:
                    continue
                value_lines = _render_artifact_value(artifact.get(field))
                if not value_lines:
                    continue
                rendered_any = True
                lines.append(f"- {field}:")
                lines.extend(f"  {line}" if line.startswith("- ") else f"  {line}" for line in value_lines)
            if not rendered_any:
                continue
        else:
            value_lines = _render_artifact_value(artifact)
            if not value_lines:
                continue
            lines.extend(value_lines)
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _build_deterministic_prompt_artifacts(
    *,
    template_runtime_config: dict[str, Any],
    raw_artifacts: dict[str, Any],
    brand_name: str,
) -> dict[str, Any]:
    """Conservative fallback when LLM artifact preparation is unavailable."""
    prepared: dict[str, Any] = {}
    definitions = _default_artifact_definitions(template_runtime_config)
    raw_summary = {
        "reddit_discover": _text_from_jsonish(raw_artifacts.get("reddit_discover"), max_chars=900),
        "citation_analysis": _text_from_jsonish(raw_artifacts.get("citation_analysis"), max_chars=900),
        "strategy": _text_from_jsonish(raw_artifacts.get("strategy"), max_chars=900),
        "selected_prompts": _text_from_jsonish(raw_artifacts.get("selected_prompts"), max_chars=600),
    }
    for definition in definitions:
        key = str(definition.get("key") or "").strip()
        fields = _coerce_string_list(definition.get("fields"))
        if not key:
            continue
        if key == "community_brief":
            prepared[key] = {
                "community_tension": raw_summary["reddit_discover"] or raw_summary["selected_prompts"],
                "reader_objections": raw_summary["citation_analysis"],
                "workflow_angle": raw_summary["strategy"],
                "brand_safe_mention_angle": f"{brand_name or 'The brand'} should appear only where it clarifies the configured workflow or tradeoff.",
                "things_to_avoid": _coerce_string_list(
                    (template_runtime_config.get("reddit_native_contract") or {}).get("voice_contract", {}).get("forbidden_patterns")
                    if isinstance(template_runtime_config.get("reddit_native_contract"), dict)
                    else []
                ),
                "closing_discussion_question": "Use the template-configured closing contract to ask a real discussion question.",
            }
        elif key == "experience_style_notes":
            prepared[key] = {
                "persona_frame": str((definition.get("persona_frame") or "")).strip(),
                "workflow_texture": [
                    raw_summary["reddit_discover"],
                    raw_summary["citation_analysis"],
                ],
                "skeptical_phrases": _coerce_string_list(definition.get("skeptical_phrases")),
                "allowed_experience_claims": _coerce_string_list(definition.get("allowed_experience_claims")),
                "forbidden_experience_claims": _coerce_string_list(definition.get("forbidden_experience_claims")),
            }
        else:
            prepared[key] = {
                field: raw_summary.get(field, "")
                for field in fields
            } if fields else {"summary": raw_summary}
    return prepared


async def _prepare_derived_prompt_artifacts(
    *,
    pool,
    task_id: str,
    client_llm,
    model_id: str,
    template_runtime_config: dict[str, Any],
    brand_context: dict[str, Any] | None,
    reddit_discovery: dict[str, Any] | None,
    official_website_discovery: dict[str, Any] | None,
    citation_analysis_result: dict[str, Any] | None,
    strategy: dict[str, Any] | None,
    prompt_texts: list[dict[str, Any]] | None,
    prompt_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _is_reddit_native_prompt_mode(template_runtime_config):
        return {}

    config = template_runtime_config.get("derived_prompt_artifacts")
    config = config if isinstance(config, dict) else {}
    if config.get("enabled") is False:
        return {}

    brand_name = _extract_primary_brand_name(brand_context or {}) or ""
    raw_artifacts = {
        "reddit_discover": reddit_discovery,
        "citation_analysis": citation_analysis_result,
        "strategy": strategy,
        "selected_prompts": prompt_texts,
        "brand_context": brand_context,
    }
    if task_id:
        await append_status_log(pool, task_id, {
            "step": 3,
            "event": "detail",
            "label": "正在准备模板派生 Prompt Artifacts...",
        })

    materialization = str(config.get("materialization") or "llm_json").strip().lower()
    prepared_json: dict[str, Any]
    if materialization in {"llm_json", "model", "gemini"}:
        prompt = _build_prompt_artifact_preparation_prompt(
            template_runtime_config=template_runtime_config,
            raw_artifacts=raw_artifacts,
            brand_name=brand_name,
        )
        try:
            prepared_json = await _llm_json(
                client_llm,
                model_id,
                prompt,
                "prompt_artifact_preparation",
                max_tokens=int(config.get("max_output_tokens") or 4096),
                prompt_debug=prompt_debug,
            )
        except Exception as exc:
            logger.warning("[CONTENT-V2] prompt_artifact_preparation failed; using deterministic fallback: %s", exc)
            prepared_json = _build_deterministic_prompt_artifacts(
                template_runtime_config=template_runtime_config,
                raw_artifacts=raw_artifacts,
                brand_name=brand_name,
            )
    else:
        prepared_json = _build_deterministic_prompt_artifacts(
            template_runtime_config=template_runtime_config,
            raw_artifacts=raw_artifacts,
            brand_name=brand_name,
        )

    rendered = _render_prepared_prompt_artifacts(
        template_runtime_config=template_runtime_config,
        prepared_artifacts=prepared_json,
    )
    result = {
        "prepared_json": prepared_json,
        "rendered_sections": rendered,
        "materialization": materialization,
    }
    if task_id:
        await append_status_log(pool, task_id, {
            "step": 3,
            "event": "detail",
            "label": "✓ Prompt Artifact Preparation 完成",
            "data": {
                "artifact_keys": list(prepared_json.keys()) if isinstance(prepared_json, dict) else [],
                "rendered_preview": rendered[:600],
            },
        })
    return result


def _resolve_confirmed_prompt_artifacts(inputs: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = inputs.get("derived_prompt_artifacts")
    if not isinstance(artifacts, dict):
        return None
    source = inputs.get("derived_prompt_artifacts_source") or artifacts.get("source")
    if source != "wizard_confirmed":
        return None
    if artifacts.get("status") not in (None, "ready"):
        return None
    rendered = artifacts.get("rendered_sections")
    prepared = artifacts.get("prepared_json")
    if not isinstance(rendered, str) and not isinstance(prepared, dict):
        return None
    return artifacts


def _requires_confirmed_prompt_artifacts(template_runtime_config: dict[str, Any]) -> bool:
    reddit_research = template_runtime_config.get("reddit_research")
    if not isinstance(reddit_research, dict) or not reddit_research.get("enabled"):
        return False
    artifact_config = reddit_research.get("artifact_preparation")
    if not isinstance(artifact_config, dict):
        return False
    if artifact_config.get("allow_runtime_generation") is True:
        return False
    return bool(artifact_config.get("reuse_confirmed_artifacts_in_final_generation"))


def _validate_required_confirmed_prompt_artifacts(
    template_runtime_config: dict[str, Any],
    confirmed_artifacts: dict[str, Any] | None,
) -> None:
    if confirmed_artifacts or not _requires_confirmed_prompt_artifacts(template_runtime_config):
        return
    raise ValueError(
        "Artifact Preparation is required for this Reddit template. "
        "Please run and confirm the Wizard Artifact Preparation step before final generation."
    )


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
    if not _is_reddit_native_prompt_mode(template_runtime_config):
        return {}
    brand_name = _extract_primary_brand_name(brand_context or {}) or "the brand"
    raw_artifacts = {
        "reddit_discover": reddit_discovery,
        "citation_analysis": citation_analysis_result,
        "strategy": strategy,
        "selected_prompts": prompt_texts,
    }
    prepared_json = _build_deterministic_prompt_artifacts(
        template_runtime_config=template_runtime_config,
        raw_artifacts=raw_artifacts,
        brand_name=brand_name,
    )
    rendered = _render_prepared_prompt_artifacts(
        template_runtime_config=template_runtime_config,
        prepared_artifacts=prepared_json,
    )
    return {
        "prepared_json": prepared_json,  # type: ignore[dict-item]
        "rendered_sections": rendered,
        "materialization": "deterministic_summary",
    }  # type: ignore[return-value]


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
    if not _is_reddit_native_prompt_mode(template_runtime_config):
        return "\n".join([
            reddit_discovery_instruction,
            official_website_discovery_instruction,
            citation_analysis_instruction,
        ])

    parts: list[str] = []
    rendered_sections = derived_artifacts.get("rendered_sections")
    if isinstance(rendered_sections, str) and rendered_sections.strip():
        parts.append(rendered_sections)
    else:
        for value in derived_artifacts.values():
            if isinstance(value, str) and value.strip():
                parts.append(value)
    contract_section = _build_reddit_native_contract_section(
        template_runtime_config.get("reddit_native_contract")
    )
    if contract_section:
        parts.append(contract_section)
    return "\n".join(p for p in parts if p.strip())


def _build_strategy_prompt_sections(
    *,
    strategy: dict[str, Any],
    template_runtime_config: dict[str, Any],
) -> dict[str, str]:
    if _is_reddit_native_prompt_mode(template_runtime_config):
        return {
            "dimension_section": "",
            "constraints_section": "",
            "enhancements_section": "",
        }

    strategies_list = strategy.get("strategies", []) if isinstance(strategy, dict) else []
    dimension_instructions: list[str] = []
    all_constraints: list[Any] = []
    all_enhancements: list[Any] = []
    for s in strategies_list:
        if not isinstance(s, dict):
            continue
        dims = s.get("dimensions", {})
        dims = dims if isinstance(dims, dict) else {}
        dimension_instructions.append(
            f"### 策略: {s.get('name', '')}\n"
            f"- 指导: {dims.get('instruction', '')}\n"
            f"- 格式: {json.dumps(dims.get('format', {}), ensure_ascii=False)}\n"
            f"- 调性: {dims.get('tone', '')}"
        )
        all_constraints.extend(dims.get("constraints", []) if isinstance(dims.get("constraints"), list) else [])
        all_enhancements.extend(dims.get("enhancement_rules", []) if isinstance(dims.get("enhancement_rules"), list) else [])

    return {
        "dimension_section": "\n".join(dimension_instructions),
        "constraints_section": "\n".join(f"- {c}" for c in all_constraints) if all_constraints else "无特殊约束",
        "enhancements_section": "\n".join(f"- {e}" for e in all_enhancements) if all_enhancements else "无特殊规则",
    }


def _build_citation_analysis_summary_markdown(citation_analysis_result: Any) -> str:
    if not isinstance(citation_analysis_result, dict) or not citation_analysis_result.get("enabled"):
        return ""
    brief = str(citation_analysis_result.get("citation_grounded_brief") or "").strip()
    if brief:
        return brief

    decision = citation_analysis_result.get("content_action_decision") or {}
    lines = [
        "## Citation Analysis Summary",
        "",
        f"- Source count: {citation_analysis_result.get('source_count', 0)}",
        f"- Brand mention summary: {json.dumps(citation_analysis_result.get('brand_mention_summary', {}), ensure_ascii=False)}",
        f"- Primary content action: {decision.get('primary_action') or 'unknown'}",
        f"- Rationale: {decision.get('rationale') or 'No rationale provided.'}",
    ]
    return "\n".join(lines)


def _evaluate_citation_alignment(
    generated_content: str,
    citation_analysis_result: Any,
    quality_gate_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(citation_analysis_result, dict) or not citation_analysis_result.get("enabled"):
        return {"required": False, "ok": True}

    quality_gate_config = quality_gate_config if isinstance(quality_gate_config, dict) else {}
    decision = citation_analysis_result.get("content_action_decision") or {}
    primary_action = str(decision.get("primary_action") or "")
    default_markers = {
        "clarification_rebuttal": ["clarification", "correct", "misleading", "comparison", "troubleshooting"],
        "refresh_extractability": ["brand fit", "feature", "benefit", "faq", "internal link"],
        "new_content_gap": ["brand fit", "use case", "workflow", "limitation"],
    }
    configured = quality_gate_config.get("citation_alignment_markers")
    if isinstance(configured, dict):
        markers_by_action = {
            action: [str(marker).lower() for marker in markers if str(marker).strip()]
            for action, markers in configured.items()
            if isinstance(markers, list)
        }
    else:
        markers_by_action = default_markers

    required_markers = markers_by_action.get(primary_action, [])
    lowered = (generated_content or "").lower()
    matched = [marker for marker in required_markers if marker in lowered]
    return {
        "required": True,
        "ok": not required_markers or bool(matched),
        "primary_action": primary_action,
        "required_markers": required_markers,
        "matched_markers": matched,
        "source_count": citation_analysis_result.get("source_count", 0),
        "brand_mention_summary": citation_analysis_result.get("brand_mention_summary", {}),
    }


def _merge_citation_alignment_llm_review(
    base_result: dict[str, Any],
    llm_review: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    merged = dict(base_result or {})
    review = {
        "ok": bool(llm_review.get("ok")),
        "reason": str(llm_review.get("reason") or ""),
        "missing_actions": [
            str(item) for item in (llm_review.get("missing_actions") or [])
            if str(item).strip()
        ][:5],
    }
    merged["llm_review"] = review
    if mode == "llm":
        merged["ok"] = review["ok"]
    elif mode == "hybrid":
        merged["ok"] = bool(merged.get("ok", True)) and review["ok"]
    return merged


async def _review_citation_alignment_with_llm(
    *,
    generated_content: str,
    citation_analysis_result: dict[str, Any],
    base_alignment: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    prompt = f"""You are a strict GEO content QA reviewer.

Judge whether the generated content visibly responds to the Citation Analysis primary action.
For primary_action=new_content_gap, PASS when the content does both:
1. learns from already-cited source patterns such as comparison framing, workflow/checklist structure, FAQ-ready answers, limitations, or clear evaluation criteria; and
2. fills the customer visibility gap by adding a conservative brand/use-case fit that the cited sources did not cover.

Do NOT require the article to literally mention "Citation Analysis", "citation gap", or internal research process. Public-facing wording such as "general category lists explain the landscape; this guide focuses on how the brand fits a specific workflow" is acceptable evidence.
Use only the Citation Brief and generated content excerpt. Return JSON:
{{"ok": true, "reason": "short reason", "missing_actions": ["action 1"]}}

Primary action: {base_alignment.get("primary_action")}

Citation Brief:
{citation_analysis_result.get("citation_grounded_brief", "")}

Generated content excerpt:
{generated_content[:9000]}
"""
    try:
        model_id = await _resolve_strategy_model_id()
        client_llm = await get_genai_client(model_id, role="flash")
        data = await _llm_json(
            client_llm,
            model_id,
            prompt,
            label="citation_alignment_review",
            max_tokens=2048,
        )
    except Exception as exc:
        logger.warning("[CONTENT-V2] Citation alignment LLM review failed: %s", exc)
        return base_alignment

    if not isinstance(data, dict) or "ok" not in data:
        return base_alignment
    return _merge_citation_alignment_llm_review(base_alignment, data, mode=mode)


def _build_topic_context_instruction(
    topics: list[dict[str, Any]],
    prompt_texts: list[dict[str, Any]],
) -> str:
    """Build explicit topic/product context for content generation."""
    topic_payload = []
    for topic in topics or []:
        if not isinstance(topic, dict):
            continue
        topic_payload.append({
            "topic_name": topic.get("topic_name"),
            "topic_type": topic.get("topic_type"),
        })

    prompt_topic_payload = []
    for prompt in prompt_texts or []:
        if not isinstance(prompt, dict):
            continue
        topic_name = prompt.get("topic_name")
        product = prompt.get("product")
        if topic_name or product:
            prompt_topic_payload.append({
                "prompt": prompt.get("text"),
                "topic_name": topic_name,
                "product": product,
            })

    if not topic_payload and not prompt_topic_payload:
        return ""

    return "\n".join([
        "## 当前 Topic / 监控主题",
        "以下 Topic 和产品语境来自工作区配置或目标 Prompts。生成内容时必须围绕这些主题组织论点，并自然服务品牌可见度（Brand Mention）目标。",
        json.dumps({
            "selected_topics": topic_payload,
            "prompt_topic_context": prompt_topic_payload,
        }, ensure_ascii=False, indent=2),
        "",
    ])


def _normalize_prompt_dimension(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe_target_prompt_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Collapse platform/country-expanded prompt rows into user-visible prompts.

    The wizard's aggregate view may submit all underlying ``geo_client_prompts``
    IDs for a single Client Prompt concept. Content generation should echo the
    user's question once, while retaining which platforms/countries it covered.
    """
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    for row in rows or []:
        text = _normalize_prompt_dimension(row["text"])
        if not text:
            continue
        topic_id = str(row["topic_id"]) if row["topic_id"] else ""
        product = _normalize_prompt_dimension(row["product"]) or ""
        intent = _normalize_prompt_dimension(row["intent"]) or ""
        topic_name = _normalize_prompt_dimension(row["topic_name"]) or ""
        key = (text, topic_id, product, intent, topic_name)

        item = grouped.get(key)
        if item is None:
            item = {
                "text": text,
                "platform": None,
                "platforms": [],
                "country": None,
                "countries": [],
                "intent": intent or None,
                "product": product or None,
                "topic_id": topic_id or None,
                "topic_name": topic_name or None,
            }
            grouped[key] = item

        platform = _normalize_prompt_dimension(row["platform"])
        if platform and platform not in item["platforms"]:
            item["platforms"].append(platform)
        country = _normalize_prompt_dimension(row["country"])
        if country and country not in item["countries"]:
            item["countries"].append(country)

    for item in grouped.values():
        item["platforms"].sort()
        item["countries"].sort()
        item["platform"] = ", ".join(item["platforms"]) if item["platforms"] else None
        item["country"] = ", ".join(item["countries"]) if item["countries"] else None

    return list(grouped.values())


def _strip_html_artifacts(text: str) -> str:
    """Remove HTML tags, Schema Markup, and JSON-LD blocks from LLM output.

    Gemini sometimes injects <script type="application/ld+json">...</script>
    blocks or raw HTML tags despite being told to output pure Markdown.
    """
    if not text:
        return text

    # Remove ```html ... ``` code blocks containing HTML/Schema Markup
    text = _re.sub(r'```html\s*\n.*?```', '', text, flags=_re.DOTALL)

    # Remove <!-- Schema Markup --> ... </script> blocks
    text = _re.sub(r'<!--\s*Schema\s*Markup\s*-->.*?</script>', '', text, flags=_re.DOTALL | _re.IGNORECASE)

    # Remove <script ...>...</script> blocks (JSON-LD etc.)
    text = _re.sub(r'<script[^>]*>.*?</script>', '', text, flags=_re.DOTALL | _re.IGNORECASE)

    # Remove remaining HTML tags but keep content (e.g. <div>text</div> → text)
    text = _re.sub(r'<(?!br\s*/?>)/?[a-zA-Z][^>]*>', '', text)

    # Clean up excessive blank lines left by removal
    text = _re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def _strip_leading_markdown_title(text: str) -> str:
    """Remove a leading H1 from generated fragments before assembly."""
    if not text:
        return ""
    return _re.sub(r"^\s*#\s+.+?(?:\n+|$)", "", text.strip(), count=1).strip()


def _ensure_section_heading(markdown: str, heading: str) -> str:
    text = _strip_leading_markdown_title(markdown)
    if not text:
        return f"## {heading}".strip()
    first_line = text.splitlines()[0].strip()
    if first_line.startswith("## "):
        return text
    return f"## {heading}\n\n{text}".strip()


def _outline_sections(outline: dict[str, Any]) -> list[dict[str, Any]]:
    sections = outline.get("sections")
    if not isinstance(sections, list):
        return []
    normalized = []
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or f"s{index}").strip() or f"s{index}"
        heading = str(section.get("heading") or section.get("title") or f"Section {index}").strip()
        normalized.append({
            **section,
            "id": section_id,
            "heading": heading,
        })
    return normalized


def _outline_findings(outline: dict[str, Any]) -> list[dict[str, Any]]:
    findings = outline.get("findings")
    if not isinstance(findings, list):
        return []
    normalized = []
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            continue
        finding_id = str(finding.get("id") or f"f{index}").strip() or f"f{index}"
        heading = str(finding.get("heading") or finding.get("title") or f"Finding {index}").strip()
        normalized.append({
            **finding,
            "id": finding_id,
            "heading": heading,
        })
    return normalized


def _assemble_segmented_markdown(
    *,
    outline: dict[str, Any],
    intro: str,
    section_markdowns: dict[str, str],
    faq_markdown: str,
    conclusion_markdown: str,
) -> str:
    """Deterministically assemble long-form content from an outline contract."""
    title = str(outline.get("title") or "Generated Content").strip()
    parts = [f"# {title}"]

    cleaned_intro = _strip_leading_markdown_title(intro)
    if cleaned_intro:
        parts.append(cleaned_intro)

    for section in _outline_sections(outline):
        section_id = section["id"]
        body = section_markdowns.get(section_id, "")
        parts.append(_ensure_section_heading(body, section["heading"]))

    cleaned_faq = _strip_leading_markdown_title(faq_markdown)
    if cleaned_faq:
        parts.append(cleaned_faq)

    cleaned_conclusion = _strip_leading_markdown_title(conclusion_markdown)
    if cleaned_conclusion:
        parts.append(cleaned_conclusion)

    markdown = "\n\n".join(part.strip() for part in parts if part and part.strip())
    return _re.sub(r"\n{3,}", "\n\n", markdown).strip()


def _assemble_segmented_report_markdown(
    *,
    outline: dict[str, Any],
    executive_summary: str,
    finding_markdowns: dict[str, str],
    action_plan_markdown: str,
    review_markdown: str,
) -> str:
    """Deterministically assemble a recommendation report from fragments."""
    title = str(outline.get("title") or "Content Optimization Recommendations").strip()
    parts = [f"# {title}"]

    summary = _strip_leading_markdown_title(executive_summary)
    if summary:
        parts.append(_ensure_section_heading(summary, "Executive Summary"))

    for finding in _outline_findings(outline):
        parts.append(_ensure_section_heading(
            finding_markdowns.get(finding["id"], ""),
            finding["heading"],
        ))

    actions = _strip_leading_markdown_title(action_plan_markdown)
    if actions:
        parts.append(_ensure_section_heading(actions, "Prioritized Actions"))

    review = _strip_leading_markdown_title(review_markdown)
    if review:
        parts.append(_ensure_section_heading(review, "Final Review"))

    markdown = "\n\n".join(part.strip() for part in parts if part and part.strip())
    return _re.sub(r"\n{3,}", "\n\n", markdown).strip()


def _segmented_generation_plan(depth: str | None) -> dict[str, int]:
    key = _normalize_depth_key(depth)
    if key == "authority":
        return {
            "section_min": 8,
            "section_max": 10,
            "outline_tokens": 8192,
            "intro_tokens": 2048,
            "section_tokens": 3072,
            "faq_tokens": 3072,
            "conclusion_tokens": 2048,
            "review_tokens": 4096,
        }
    return {
        "section_min": 6,
        "section_max": 9,
        "outline_tokens": 6144,
        "intro_tokens": 1536,
        "section_tokens": 2048,
        "faq_tokens": 2048,
        "conclusion_tokens": 1536,
        "review_tokens": 3072,
    }


def _coerce_prompt_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = [value]
    else:
        raw_items = []
    lines: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text:
            lines.append(text)
    return lines


def _build_segmented_outline_prompt(
    *,
    context_prompt: str,
    content_type_label: str,
    depth_label: str,
    language: str,
    plan: dict[str, Any],
    segmented_generation_config: dict[str, Any] | None = None,
) -> str:
    config = segmented_generation_config if isinstance(segmented_generation_config, dict) else {}
    outline_rules = _coerce_prompt_lines(config.get("outline_rules"))
    if not outline_rules:
        outline_rules = [
            "生成一个逻辑完整、可发布的长文结构。",
            f"sections 数量必须在 {plan['section_min']} 到 {plan['section_max']} 之间。",
            "每个 section 必须有稳定 id，例如 s1、s2、s3。",
            "每个 section 必须只承担一个清晰论点，避免章节之间重复。",
        ]
    outline_rule_text = "\n".join(f"- {line}" for line in outline_rules)
    faq_outline_mode = str(config.get("faq_outline_mode") or "omit").strip().lower()
    if faq_outline_mode not in {"omit", "optional", "required"}:
        faq_outline_mode = "omit"
    faq_outline_rule = str(config.get("faq_outline_rule") or "").strip()
    faq_schema_block = ""
    if faq_outline_mode != "omit":
        faq_requirement = (
            faq_outline_rule
            or (
                "FAQ is optional: use an empty array when the article does not naturally need one."
                if faq_outline_mode == "optional"
                else "FAQ is required: include questions readers would genuinely ask."
            )
        )
        faq_schema_block = f""",
  "faq": [
    {{
      "question": "问题",
      "answer_brief": "回答方向"
    }}
  ],
  "faq_rule": {json.dumps(faq_requirement, ensure_ascii=False)}"""

    return f"""{context_prompt}

## 分段生成阶段：Outline Contract
你现在只生成结构化大纲，不要写完整正文。这个大纲后续会作为不可随意偏离的写作合同。

## 内容类型
{content_type_label}

## 深度
{depth_label}

## 语言
{language}

## 大纲要求
{outline_rule_text}

## 输出 JSON Schema
{{
  "title": "可发布标题",
  "thesis": "全文核心论点",
  "audience": "目标读者",
  "intro_brief": "引言应完成的任务",
  "sections": [
    {{
      "id": "s1",
      "heading": "H2 标题",
      "purpose": "本节目的",
      "must_cover": ["必须覆盖的点"],
      "avoid": ["本节避免事项"],
      "target_words": 250
    }}
  ]{faq_schema_block},
  "conclusion_brief": "结论应完成的任务",
  "coherence_rules": ["全文连贯性规则"]
}}"""


async def _llm_generate(
    client,
    model_id: str,
    contents: str,
    config,
    label: str = "llm",
    prompt_debug: dict[str, Any] | None = None,
) -> str:
    """Call Gemini with retry and graduated backoff. Returns raw text."""
    await _log_llm_prompt_debug(prompt_debug, label=label, model_id=model_id, prompt=contents)
    last_err = None
    for attempt in range(1, _LLM_RETRIES + 1):
        try:
            response = await client.aio.models.generate_content(
                model=model_id, contents=contents, config=config,
            )
            return response.text or ""
        except Exception as e:
            last_err = str(e) or f"{type(e).__name__}: {repr(e)}"
            logger.warning(f"[CONTENT-V2] {label} error attempt {attempt}/{_LLM_RETRIES}: {last_err}")
            if attempt < _LLM_RETRIES:
                err_upper = str(last_err).upper()
                is_deadline = (
                    "DEADLINE" in err_upper
                    or "READTIMEOUT" in err_upper
                    or "TIMEOUT" in err_upper
                    or "504" in str(last_err)
                )
                delay = attempt * 5 if is_deadline else 2 ** attempt
                logger.info(f"[CONTENT-V2] Retrying in {delay}s ({'deadline' if is_deadline else 'other'})")
                await asyncio.sleep(delay)
    raise RuntimeError(f"{label} failed after {_LLM_RETRIES} attempts: {last_err}")


def _json_error_looks_truncated(error: Exception, text: str) -> bool:
    """Return true when a JSON parse failure likely came from token truncation."""
    if not isinstance(error, json.JSONDecodeError):
        return False

    message = str(error).lower()
    if "unterminated string" in message:
        return True
    if "expecting value" in message or "expecting ',' delimiter" in message or "expecting property name" in message:
        return bool(text) and error.pos >= max(len(text) - 20, 0)
    return False


async def _llm_json(
    client,
    model_id: str,
    prompt: str,
    label: str = "llm",
    max_tokens: int = 8192,
    prompt_debug: dict[str, Any] | None = None,
) -> dict:
    """Call Gemini and parse JSON response."""
    await _log_llm_prompt_debug(prompt_debug, label=label, model_id=model_id, prompt=prompt)
    current_max_tokens = max_tokens
    last_err: Exception | None = None
    for attempt in range(1, 4):
        text = ""
        try:
            response = await client.aio.models.generate_content(
                model=model_id, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2, max_output_tokens=current_max_tokens,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as e:
            last_err = e
            logger.warning(f"[CONTENT-V2] {label} attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                if _json_error_looks_truncated(e, text):
                    next_max_tokens = min(max(current_max_tokens * 2, current_max_tokens + 2048), 16384)
                    if next_max_tokens > current_max_tokens:
                        current_max_tokens = next_max_tokens
                        logger.info(
                            "[CONTENT-V2] %s JSON looked truncated; retrying with max_output_tokens=%s",
                            label,
                            current_max_tokens,
                        )
                err_str = str(e)
                err_upper = err_str.upper()
                is_deadline = (
                    "DEADLINE" in err_upper
                    or "READTIMEOUT" in err_upper
                    or "TIMEOUT" in err_upper
                    or "504" in err_str
                )
                delay = attempt * 5 if is_deadline else 2 ** attempt
                await asyncio.sleep(delay)
    raise RuntimeError(f"{label} failed after 3 attempts: {last_err}")


# ─── RATF framework & data disclosure hard-constraint helpers ────────

def _build_ratf_framework_block(
    metric_defs: list[dict[str, Any]],
    subgoal_defs: list[dict[str, Any]],
    metric_jobs: dict[str, Any] | None = None,
    ratf_rendering: dict[str, Any] | None = None,
) -> str:
    """Build the HARD-CONSTRAINT RATF content framework block that locks
    every generated piece of content to the template's required quality
    dimensions.

    Returns an empty string when no metrics/sub-goals are configured
    (Custom / ad-hoc entries), letting the legacy prompt remain the
    only constraint.

    The block:
      - Lists every active top-level metric with its bilingual label,
        definition, and narrative job (what the metric must achieve).
      - Groups sub-goals under their parent metric so the LLM sees the
        hierarchy (RATF → sub-goal) and understands each metric is a
        conjunction of sub-goals, not a bag of synonyms.
      - Explicitly forbids fabricating product claims, citations, or
        statistics and requires verifiable sources for every factual
        statement. This is the direct response to the "数据不准确"
        regression.
    """
    if not metric_defs:
        return ""
    metric_jobs = metric_jobs if isinstance(metric_jobs, dict) else {}
    ratf_rendering = ratf_rendering if isinstance(ratf_rendering, dict) else {}
    include_subgoal_raw_descriptions = bool(ratf_rendering.get("include_subgoal_raw_descriptions", True))
    subgoal_overrides = ratf_rendering.get("subgoal_overrides")
    subgoal_overrides = subgoal_overrides if isinstance(subgoal_overrides, dict) else {}

    # Index sub-goals by parent_key so each metric prints with its own children.
    subgoals_by_parent: dict[str, list[dict[str, Any]]] = {}
    for sg in subgoal_defs:
        subgoals_by_parent.setdefault(sg.get("parent_key") or "", []).append(sg)

    lines: list[str] = [
        "## 内容质量框架 (Content Quality Framework) — 硬约束",
        "",
        (
            "本次生成的内容必须严格遵循以下 RATF 质量维度，每一维度都是"
            "必须满足的**硬性质量目标**。偏离任何一条都视为不合格输出："
        ),
        "",
    ]
    for idx, m in enumerate(metric_defs, start=1):
        key = m.get("key", "")
        label = m.get("label", key)
        desc = m.get("description", "")
        job = str(metric_jobs.get(key) or "").strip() or "按该维度的定义优化内容"
        lines.append(f"{idx}. **{label}**")
        lines.append(f"   - 定义：{desc}")
        lines.append(f"   - 执行要求：{job}")

        children = subgoals_by_parent.get(key, [])
        if children:
            lines.append("   - 必须同时达成以下子目标：")
            for sg in children:
                sg_key = str(sg.get("key") or "").strip()
                sg_label = sg.get("label") or sg.get("key", "")
                sg_desc = sg.get("description") or ""
                override_desc = str(subgoal_overrides.get(sg_key) or "").strip()
                if override_desc:
                    lines.append(f"     - **{sg_label}** — {override_desc}")
                elif include_subgoal_raw_descriptions and sg_desc:
                    lines.append(f"     - **{sg_label}** — {sg_desc}")
                else:
                    lines.append(f"     - **{sg_label}**")

    lines += [
        "",
        "**内容真实性约束（对应用户反馈「数据不准确」的核心硬约束）：**",
        (
            "- 严禁编造任何产品参数、价格、市场份额、销量、评分、用户评论、"
            "媒体报道、奖项或第三方测评；只能使用 \"## 品牌画像\" / "
            "\"## 产品核心事实\" / \"## 选题机会参考\" / \"## Analyzer 上下文\" "
            "明确给出的事实。"
        ),
        (
            "- 每一个具体数字、百分比、年份、排名、对比结论都必须能追溯到上述"
            "输入的某一行；找不到来源时必须改写成通用表述（例如 "
            "\"在多个评测榜单中表现优异\"）或直接删除，不得编造。"
        ),
        (
            "- 严禁发明不存在的 URL、媒体名、研究机构、白皮书、博客作者、"
            "社交媒体帖子；引用来源只能使用输入中真实出现过的 domain / 名称。"
        ),
        (
            "- 对于品牌 / 产品没有给出明确立场的事实，不得凭训练知识补全；"
            "宁可让句子更保守，也不能让句子更具体。"
        ),
        "",
    ]
    return "\n".join(lines)


def _build_content_disclosure_block(
    include: bool,
    selected_metrics: list[str],
    selected_subgoals: list[str],
    brand_context: dict[str, Any],
    product_facts: dict[str, Any],
    target_prompts: list[dict[str, Any]],
    analyzer_context: dict[str, Any] | None,
) -> str:
    """Build the runtime directive that tells the LLM whether (and how)
    to emit a "## 数据依据 / Data Sources" chapter at the end of the
    generated content.

    When ``include=True`` (default), the model must append a final
    section listing every input that was used — selected metrics,
    sub-goals, brand profile keys, product facts keys, target prompts,
    analyzer snippets. This is the content-pipeline analogue of the
    analysis pipeline's data disclosure chapter and serves as a
    provenance audit trail.
    """
    if not include:
        return (
            "**数据依据披露：** 本次模板已关闭数据依据披露章节，内容最终不需要"
            "附带 Data Sources 段落。但所有事实仍必须来源于上文输入，不得编造。\n"
        )

    # Summarise which inputs are non-empty so the LLM can't pretend a
    # missing input was "provided but implicit".
    brand_keys = [k for k, v in (brand_context or {}).items() if v]
    product_keys = list((product_facts or {}).keys())
    prompt_count = len(target_prompts or [])
    analyzer_present = bool(analyzer_context)

    lines = [
        "**数据依据披露要求（必须执行）：** 生成内容的最后一个 H2 章节必须是 ",
        "\"## 数据依据 (Data Sources)\"，列出本次生成实际使用到的所有输入来源。",
        "该章节的内容必须如实反映以下清单，不得夸大或编造：",
        "",
        f"- 优化 Metrics：{', '.join(selected_metrics) if selected_metrics else '（未指定）'}",
        f"- 优化 Sub-goals：{', '.join(selected_subgoals) if selected_subgoals else '（未指定）'}",
        f"- 品牌画像字段：{', '.join(brand_keys) if brand_keys else '（未提供）'}",
        f"- 产品核心事实字段：{', '.join(product_keys) if product_keys else '（未提供）'}",
        f"- 目标 AI 搜索 Prompts 数量：{prompt_count}",
        f"- Analyzer 上下文：{'已加载' if analyzer_present else '未加载'}",
        "",
        (
            "披露格式：用 Markdown bullet list 列出上述条目；对每条简短说明"
            "它在本次内容中被如何使用（例如 \"brand_name 决定文末 CTA 中的"
            "品牌称呼\"）。禁止在该节出现任何未在上方清单中出现的来源名称。"
        ),
        "",
    ]
    return "\n".join(lines)


# ─── Step 1: Citation Analysis ───────────────────────────────────────

async def step_citation_analysis(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Build a citation-grounded brief when the selected template enables it."""
    try:
        template_runtime_config = await _load_template_runtime_config(pool, task_id)
    except Exception as e:
        logger.warning(f"[CONTENT-V2] Template runtime config lookup failed before citation analysis: {e}")
        template_runtime_config = {}

    preflight_result = inputs.get("citation_analysis_result")
    if isinstance(preflight_result, dict) and preflight_result.get("enabled"):
        expected_fingerprint = citation_analysis_service.build_citation_analysis_fingerprint(
            inputs=inputs,
            template_runtime_config=template_runtime_config,
        )
        if preflight_result.get("fingerprint") == expected_fingerprint:
            await append_status_log(pool, task_id, {
                "step": 1,
                "event": "step_output",
                "label": "Citation Analysis 已复用 Wizard 预运行结果",
                "data": {
                    "source_count": preflight_result.get("source_count", 0),
                    "brand_mention_summary": preflight_result.get("brand_mention_summary", {}),
                    "primary_action": (preflight_result.get("content_action_decision") or {}).get("primary_action"),
                    "citation_sources": (preflight_result.get("citation_sources") or [])[:5],
                    "fingerprint": expected_fingerprint,
                },
            })
            return {
                "citation_analysis_result": preflight_result,
                "template_runtime_config": template_runtime_config,
            }

        await append_status_log(pool, task_id, {
            "step": 1,
            "event": "detail",
            "label": "Citation Analysis 预运行结果已过期，正在重新分析",
            "data": {
                "expected_fingerprint": expected_fingerprint,
                "received_fingerprint": preflight_result.get("fingerprint"),
            },
        })

    try:
        brand_context = await _load_content_brand_context(pool, client_id)
    except Exception as e:
        logger.warning("[CONTENT-V2] Brand context lookup failed before citation analysis: %s", e)
        brand_context = {}

    await append_status_log(pool, task_id, {
        "step": 1,
        "event": "detail",
        "label": "正在检查 Citation Analysis 配置...",
    })

    citation_result = await run_citation_analysis(
        pool=pool,
        client_id=client_id,
        inputs=inputs,
        brand_context=brand_context,
        template_runtime_config=template_runtime_config,
    )

    if not citation_result.get("enabled"):
        await append_status_log(pool, task_id, {
            "step": 1,
            "event": "detail",
            "label": "Citation Analysis 未启用，跳过",
        })
        return {
            "citation_analysis_result": citation_result,
            "template_runtime_config": template_runtime_config,
        }

    decision = citation_result.get("content_action_decision") or {}
    await append_status_log(pool, task_id, {
        "step": 1,
        "event": "step_output",
        "label": "Citation Analysis 完成",
        "data": {
            "source_count": citation_result.get("source_count", 0),
            "brand_mention_summary": citation_result.get("brand_mention_summary", {}),
            "primary_action": decision.get("primary_action"),
            "citation_sources": citation_result.get("citation_sources", [])[:5],
        },
    })

    return {
        "citation_analysis_result": citation_result,
        "template_runtime_config": template_runtime_config,
    }


# ─── Step 2: Strategy Generation ─────────────────────────────────────

async def step_strategy_generation(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Generate strategy combination from user selections + analyzer context.

    Phase 2 contract mode — if the task's template has a ``wizard_config``
    that declares ``required_metrics`` / ``required_subgoals``, those IDs
    are UNION'd into the user's selections. This guarantees that every
    run of a given template optimizes the same core goals, while still
    letting users add extras via the wizard (Node 1).
    """
    selected_metrics = list(inputs.get("selected_metrics", []) or [])
    selected_subgoals = list(inputs.get("selected_subgoals", []) or [])
    existing_strategy = inputs.get("strategy")
    content_type = inputs.get("content_type", "faq")
    publish_platform = inputs.get("publish_platform", "")
    depth = inputs.get("depth")
    reddit_discovery = inputs.get("reddit_discovery")
    official_website_discovery = inputs.get("official_website_discovery")
    citation_analysis_result = inputs.get("citation_analysis_result")
    analyzer_context = inputs.get("analyzer_context")  # from Node 0 import
    user_strategy_edits = inputs.get("user_strategy_edits")  # from Node 3 tweaks
    model_id: str | None = None
    prompt_debug_enabled = await _content_prompt_debug_enabled(pool)

    # ── Contract override: merge template-locked metrics/subgoals ──
    try:
        contract, contract_template_name = await get_contract_for_task(pool, task_id)
    except Exception as e:
        logger.warning(f"[CONTENT-V2] Contract lookup failed: {e}")
        contract, contract_template_name = None, None

    try:
        template_runtime_config = await _load_template_runtime_config(pool, task_id)
    except Exception as e:
        logger.warning(f"[CONTENT-V2] Template runtime config lookup failed: {e}")
        template_runtime_config = {}

    # Migration 029 — data disclosure flag & RATF step defaults surfaced
    # from wizard_config.steps.content_framework / output_config.
    include_data_disclosure = _resolve_include_data_disclosure(
        default=bool((contract or {}).get("include_data_disclosure", True)),
        template_runtime_config=template_runtime_config if isinstance(template_runtime_config, dict) else {},
    )
    default_content_metrics = list((contract or {}).get("default_content_metrics") or [])
    default_content_subgoals = list((contract or {}).get("default_content_subgoals") or [])

    if contract:
        # Required metrics/subgoals come from two sources that we must
        # UNION: (a) the legacy flat contract fields
        # (``required_metrics`` / ``required_subgoals``) from
        # migration 026, and (b) the new schema-driven step defaults
        # (``default_content_metrics`` / ``default_content_subgoals``)
        # from migration 029. Newer templates populate both; older ones
        # only have (a). Either way, the union is what step 1 locks in.
        locked_metrics = list(contract.get("required_metrics") or [])
        locked_subgoals = list(contract.get("required_subgoals") or [])
        for m in default_content_metrics:
            if m not in locked_metrics:
                locked_metrics.append(m)
        for sg in default_content_subgoals:
            if sg not in locked_subgoals:
                locked_subgoals.append(sg)

        def _union_preserve_order(a: list[str], b: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for v in list(a) + list(b):
                if v and v not in seen:
                    seen.add(v)
                    out.append(v)
            return out

        pre_metrics = list(selected_metrics)
        pre_subgoals = list(selected_subgoals)
        selected_metrics = _union_preserve_order(locked_metrics, selected_metrics)
        selected_subgoals = _union_preserve_order(locked_subgoals, selected_subgoals)

        added_metrics = [m for m in locked_metrics if m not in pre_metrics]
        added_subgoals = [s for s in locked_subgoals if s not in pre_subgoals]
        if added_metrics or added_subgoals:
            await append_status_log(pool, task_id, {
                "step": 2, "event": "detail",
                "label": (
                    f"✓ 契约模式：模板 《{contract_template_name}》 锁定 "
                    f"{len(locked_metrics)} 个指标 / {len(locked_subgoals)} 个子目标 "
                    f"（新增 metrics={added_metrics or '无'}, subgoals={added_subgoals or '无'}）"
                ),
            })
            logger.info(
                "[CONTENT-V2] Contract union applied: template=%r "
                "locked_metrics=%s locked_subgoals=%s",
                contract_template_name, locked_metrics, locked_subgoals,
            )

    await append_status_log(pool, task_id, {"step": 2, "event": "detail", "label": "正在加载品牌信息..."})

    brand_context = await _load_content_brand_context(pool, client_id)

    # Load sub-goal descriptions for prompt
    sg_rows = await pool.fetch(
        """SELECT sg.id, sg.name_zh, sg.description, m.name_zh AS metric_name
           FROM geo_optimization_subgoals sg
           JOIN geo_optimization_metrics m ON sg.metric_id = m.id
           WHERE sg.id = ANY($1::text[])""",
        selected_subgoals,
    )
    subgoal_descriptions = [
        f"- {r['metric_name']} > {r['name_zh']}: {r['description']}" for r in sg_rows
    ]

    # Build analyzer context snippet
    analyzer_snippet = ""
    if analyzer_context:
        quadrants = analyzer_context.get("topic_quadrants", [])
        opportunities = analyzer_context.get("content_opportunities", [])
        platforms = analyzer_context.get("platform_recommendations", [])
        analyzer_snippet = f"""
## Analyzer 上下文（来自优化机会发现）

### Topic 四象限诊断
{json.dumps(quadrants[:5], ensure_ascii=False, indent=2)}

### 选题机会
{json.dumps(opportunities[:5], ensure_ascii=False, indent=2)}

### 平台推荐
{json.dumps(platforms[:5], ensure_ascii=False, indent=2)}
"""

    await append_status_log(pool, task_id, {"step": 2, "event": "detail", "label": "正在生成内容策略..."})

    strategy_result: dict[str, Any] | None = None
    citation_enabled_for_strategy = bool(
        isinstance(citation_analysis_result, dict)
        and citation_analysis_result.get("enabled")
    )
    if existing_strategy and not citation_enabled_for_strategy:
        try:
            candidate = _normalize_strategy_result(existing_strategy)
            if candidate.get("strategies"):
                strategy_result = candidate
                await append_status_log(pool, task_id, {
                    "step": 2,
                    "event": "detail",
                    "label": "✓ 使用 Wizard 已确认的策略，不再重新生成策略",
                })
        except Exception as e:
            logger.warning("[CONTENT-V2] Ignoring invalid precomputed strategy: %s", e)
    elif existing_strategy and citation_enabled_for_strategy:
        await append_status_log(pool, task_id, {
            "step": 2,
            "event": "detail",
            "label": "✓ Citation Analysis 已生成新的证据摘要，正在基于 Citation Brief 重新生成策略",
        })

    if strategy_result is None:
        # LLM generates strategy only when the wizard did not provide a
        # confirmed strategy payload. This keeps preview strategy and final
        # execution aligned without wasting an extra model call.
        model_id = await _resolve_strategy_model_id()
        client_llm = await get_genai_client(model_id, role="flash")

        prompt = f"""你是 GEO 内容策略专家。请基于以下输入，生成一组内容策略组合。

## 用户选择
- 内容类型: {content_type}
- 发布平台: {publish_platform or template_runtime_config.get("default_publish_platform") or "未指定"}
- 内容深度: {depth or template_runtime_config.get("default_depth") or "standard"}
- 优化 Metrics: {', '.join(selected_metrics)}
- 优化 Sub-goals:
{chr(10).join(subgoal_descriptions)}

{_build_platform_instruction(publish_platform, template_runtime_config)}
{_build_depth_instruction(depth, template_runtime_config)}
{_build_template_instruction(template_runtime_config)}
{_build_reddit_discovery_instruction(reddit_discovery)}
{_build_official_website_discovery_instruction(official_website_discovery)}
{_build_citation_analysis_instruction(citation_analysis_result)}
{_build_freshness_context()}
{_build_brand_visibility_instruction(brand_context)}

## 品牌画像
{json.dumps(brand_context, ensure_ascii=False, indent=2)}

{analyzer_snippet}

{f"## 用户策略调整{chr(10)}{user_strategy_edits}" if user_strategy_edits else ""}

## 输出要求

输出 JSON 对象，包含以下字段：
{{
  "strategies": [
    {{
      "name": "策略名称",
      "description": "一句话描述",
      "dimensions": {{
        "instruction": "内容目标和范围描述",
        "format": {{
          "structure": "内容结构要求",
          "schema_markup": "推荐的 schema 类型",
          "word_count": "字数要求"
        }},
        "tone": "写作调性",
        "constraints": ["约束1", "约束2"],
        "enhancement_rules": ["增强规则1", "增强规则2"]
      }},
      "source_metrics": ["metric_id"],
      "source_subgoals": ["subgoal_id"]
    }}
  ],
  "strategy_summary": "用自然语言概述策略组合（给用户确认用）"
}}

生成 2-4 个互补策略，覆盖用户选择的所有 Sub-goals。"""
        strategy_result = _normalize_strategy_result(
            await _llm_json(
                client_llm,
                model_id,
                prompt,
                "strategy_generation",
                prompt_debug=_content_prompt_debug_context(
                    pool,
                    task_id=task_id,
                    client_id=client_id,
                    template_runtime_config=template_runtime_config,
                    content_type=content_type,
                    publish_platform=publish_platform,
                    enabled=prompt_debug_enabled,
                ),
            )
        )

    await append_status_log(pool, task_id, {
        "step": 2, "event": "step_output", "label": "策略生成完成",
        "data": {
            "strategy_summary": strategy_result.get("strategy_summary", ""),
            "strategy_count": len(strategy_result.get("strategies", [])),
            "selected_metrics": selected_metrics,
            "selected_subgoals": selected_subgoals,
            "citation_analysis_enabled": bool(
                isinstance(citation_analysis_result, dict)
                and citation_analysis_result.get("enabled")
            ),
        },
    })

    # ── Load bilingual dictionary rows for selected metrics/sub-goals ──
    # These feed the RATF hard-constraint block that step 2 injects into
    # the content-generation prompt. Pulled from ``geo_workflow_config``
    # (migration 029) so labels carry both Chinese and English copies.
    metric_defs = await load_workflow_dictionary_rows(
        pool, "content_metric", "content_generation", selected_metrics,
    )
    subgoal_defs = await load_workflow_dictionary_rows(
        pool, "content_sub_goal", "content_generation", selected_subgoals,
    )

    # ── Bug #5 fix (2026-04-20): fall-back to geo_analysis_metrics ──
    # Content templates' wizard_config.required_metrics historically lists
    # ANALYSIS metric keys (e.g. 'prompt_coverage_rate') as data-context
    # references — NOT RATF content-quality dimensions. Those keys are NOT
    # in geo_workflow_config's content_metric scope, so the previous lookup
    # silently dropped them with a warning. Now we check
    # geo_analysis_metrics for any key that missed the content_metric
    # dict. Recovered keys are promoted to metric_defs so the LLM prompt
    # knows "this content targets the data gap measured by X".
    found_keys = {d["key"] for d in metric_defs}
    missing_keys = [m for m in selected_metrics if m not in found_keys]
    if missing_keys:
        rows = await pool.fetch(
            """SELECT metric_name AS key,
                      COALESCE(display_name_zh, display_name_en, metric_name) AS label,
                      COALESCE(description, '') AS description,
                      domain
               FROM geo_analysis_metrics
               WHERE metric_name = ANY($1::text[]) AND is_active = true""",
            missing_keys,
        )
        analysis_refs = [dict(r) for r in rows]
        if analysis_refs:
            metric_defs = list(metric_defs) + analysis_refs
            logger.info(
                "[CONTENT-V2] Recovered %d analysis-scope metric refs for content context: %s",
                len(analysis_refs), [r["key"] for r in analysis_refs],
            )

    if metric_defs:
        await append_status_log(pool, task_id, {
            "step": 2, "event": "detail",
            "label": (
                f"✓ 内容框架锁定：{len(metric_defs)} 个 RATF 维度 / "
                f"{len(subgoal_defs)} 个子目标，数据依据披露="
                f"{'开启' if include_data_disclosure else '关闭'}"
            ),
        })
        logger.info(
            "[CONTENT-V2] RATF framework locked: metrics=%s subgoals=%s "
            "disclosure=%s",
            [m.get("key") for m in metric_defs],
            [s.get("key") for s in subgoal_defs],
            include_data_disclosure,
        )

    return {
        "strategy": strategy_result,
        "brand_context": brand_context,
        "model_used": model_id,
        # Surface the (possibly contract-expanded) selections so step 3
        # (quality review) sees the same list the LLM was briefed on.
        "selected_metrics": selected_metrics,
        "selected_subgoals": selected_subgoals,
        # Migration 029 — pass framework definitions + disclosure flag
        # through to step_content_generation and step_quality_review.
        "content_metric_definitions": metric_defs,
        "content_subgoal_definitions": subgoal_defs,
        "include_data_disclosure": include_data_disclosure,
        "template_runtime_config": template_runtime_config,
        "citation_analysis_result": citation_analysis_result,
    }


async def _generate_segmented_longform_content(
    *,
    pool,
    task_id: str,
    client_llm,
    model_id: str,
    context_prompt: str,
    content_type: str,
    content_type_label: str,
    depth: str | None,
    language: str,
    search_grounding_enabled: bool,
    template_runtime_config: dict[str, Any] | None = None,
    prompt_debug: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Generate long-form content as outline -> sections -> assembly -> review.

    The pipeline deliberately keeps the final assembly deterministic. Gemini
    writes the outline and fragments, but Python owns final ordering so long
    articles remain coherent and less likely to timeout on one huge response.
    """
    depth_key = _normalize_depth_key(depth)
    plan = _segmented_generation_plan(depth_key)
    depth_label = "Comprehensive" if depth_key == "authority" else depth_key.title()

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": f"正在生成 {depth_label} 长文结构大纲...",
    })

    runtime_config = template_runtime_config if isinstance(template_runtime_config, dict) else {}
    outline_prompt = _build_segmented_outline_prompt(
        context_prompt=context_prompt,
        content_type_label=content_type_label,
        depth_label=depth_label,
        language=language,
        plan=plan,
        segmented_generation_config=runtime_config.get("segmented_generation"),
    )

    outline = await _llm_json(
        client_llm,
        model_id,
        outline_prompt,
        "content_outline_generation",
        max_tokens=plan["outline_tokens"],
        prompt_debug=prompt_debug,
    )
    sections = _outline_sections(outline)
    if not sections:
        raise RuntimeError("content_outline_generation returned no sections")

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": f"✓ 长文大纲完成：{len(sections)} 个章节，开始分段生成",
        "data": {
            "generation_mode": "segmented",
            "depth": depth_key,
            "section_count": len(sections),
            "title": outline.get("title"),
        },
    })

    outline_json = json.dumps(outline, ensure_ascii=False, indent=2)

    intro_prompt = f"""{context_prompt}

## 分段生成阶段：Intro
请只写这篇文章的引言部分，不要输出 H1，不要写后续章节。

## Outline Contract
{outline_json}

## 写作要求
- 直接进入读者问题和决策场景。
- 清晰交代全文 thesis。
- 不要硬广，不要夸大，不要伪造个人经历。
- 输出纯 Markdown 段落。"""

    intro = _strip_html_artifacts(await _llm_generate(
        client_llm,
        model_id,
        intro_prompt,
        _build_generation_config(plan["intro_tokens"], search_grounding_enabled),
        "content_intro_generation",
        prompt_debug=prompt_debug,
    ))

    section_markdowns: dict[str, str] = {}
    previous_summaries: list[str] = []
    for index, section in enumerate(sections, start=1):
        section_id = section["id"]
        heading = section["heading"]
        prev_context = "\n".join(previous_summaries[-2:]) or "无"
        next_heading = sections[index]["heading"] if index < len(sections) else "FAQ / Conclusion"

        await append_status_log(pool, task_id, {
            "step": 3,
            "event": "detail",
            "label": f"正在生成章节 {index}/{len(sections)}：{heading}",
        })

        section_prompt = f"""{context_prompt}

## 分段生成阶段：Section Generation
你现在只写一个 H2 章节。必须服从 Outline Contract，不要写整篇文章，不要写 FAQ 或 Conclusion。

## Outline Contract
{outline_json}

## 当前章节
{json.dumps(section, ensure_ascii=False, indent=2)}

## 前文摘要
{prev_context}

## 下一章节标题
{next_heading}

## 写作要求
- 第一行必须是：## {heading}
- 本节只完成当前章节目的，不重复其他章节。
- 与前文自然衔接，并为下一节留出逻辑过渡。
- 具体事实必须来自任务输入或 Search Grounding；无法确认的信息要保守表达。
- 输出纯 Markdown。"""

        section_text = _strip_html_artifacts(await _llm_generate(
            client_llm,
            model_id,
            section_prompt,
            _build_generation_config(plan["section_tokens"], search_grounding_enabled),
            f"content_section_generation:{section_id}",
            prompt_debug=prompt_debug,
        ))
        section_text = _ensure_section_heading(section_text, heading)
        section_markdowns[section_id] = section_text
        previous_summaries.append(f"{heading}: {section.get('purpose', '')}")

    faq_markdown = ""
    if isinstance(outline.get("faq"), list) and outline.get("faq"):
        await append_status_log(pool, task_id, {
            "step": 3,
            "event": "detail",
            "label": "正在生成 FAQ...",
        })
        faq_prompt = f"""{context_prompt}

## 分段生成阶段：FAQ
请只写 FAQ 章节，不要重写正文。

## Outline Contract
{outline_json}

## 已生成章节摘要
{chr(10).join(previous_summaries)}

## 写作要求
- 第一行必须是：## Frequently Asked Questions
- FAQ 必须回答读者真实疑问，避免广告式自问自答。
- 每个回答要简洁、具体、可验证。
- 输出纯 Markdown。"""
        faq_markdown = _strip_html_artifacts(await _llm_generate(
            client_llm,
            model_id,
            faq_prompt,
            _build_generation_config(plan["faq_tokens"], search_grounding_enabled),
            "content_faq_generation",
            prompt_debug=prompt_debug,
        ))

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": "正在生成结论...",
    })
    conclusion_prompt = f"""{context_prompt}

## 分段生成阶段：Conclusion
请只写结论章节，不要重写正文。

## Outline Contract
{outline_json}

## 已生成章节摘要
{chr(10).join(previous_summaries)}

## 写作要求
- 第一行必须是：## Conclusion
- 总结全文决策逻辑，不要突然加入新事实。
- Reddit 内容使用低压、自然的收束方式，避免销售 CTA。
- 输出纯 Markdown。"""
    conclusion_markdown = _strip_html_artifacts(await _llm_generate(
        client_llm,
        model_id,
        conclusion_prompt,
        _build_generation_config(plan["conclusion_tokens"], search_grounding_enabled),
        "content_conclusion_generation",
        prompt_debug=prompt_debug,
    ))

    assembled = _assemble_segmented_markdown(
        outline=outline,
        intro=intro,
        section_markdowns=section_markdowns,
        faq_markdown=faq_markdown,
        conclusion_markdown=conclusion_markdown,
    )

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": "正在进行长文连贯性复核...",
    })
    review_prompt = f"""{context_prompt}

## 分段生成阶段：Coherence Review
请评审下面这篇已组装文章，只输出 JSON。不要重写全文。

## Outline Contract
{outline_json}

## Assembled Article
{assembled[:24000]}

## 输出 JSON Schema
{{
  "overall_ok": true,
  "issues": [
    {{
      "section_id": "s2",
      "problem": "问题描述",
      "revision_instruction": "给该章节的具体修订要求"
    }}
  ],
  "global_notes": ["整体建议"]
}}"""
    coherence_review = await _llm_json(
        client_llm,
        model_id,
        review_prompt,
        "content_coherence_review",
        max_tokens=plan["review_tokens"],
        prompt_debug=prompt_debug,
    )

    issues = coherence_review.get("issues")
    if isinstance(issues, list) and issues:
        section_by_id = {section["id"]: section for section in sections}
        revised_count = 0
        for issue in issues:
            if revised_count >= 2 or not isinstance(issue, dict):
                continue
            section_id = str(issue.get("section_id") or "").strip()
            section = section_by_id.get(section_id)
            if not section or section_id not in section_markdowns:
                continue
            await append_status_log(pool, task_id, {
                "step": 3,
                "event": "detail",
                "label": f"正在局部修订章节：{section['heading']}",
            })
            revision_prompt = f"""{context_prompt}

## 分段生成阶段：Targeted Section Revision
请只重写指定章节，保留 H2 标题，不要输出其他章节。

## Outline Contract
{outline_json}

## 当前章节
{json.dumps(section, ensure_ascii=False, indent=2)}

## 原章节内容
{section_markdowns[section_id]}

## 复核发现的问题
{json.dumps(issue, ensure_ascii=False, indent=2)}

## 修订要求
- 修复复核指出的问题。
- 不引入无法验证的新事实。
- 不破坏 Reddit / 平台语气要求。
- 第一行必须是：## {section['heading']}"""
            revised = _strip_html_artifacts(await _llm_generate(
                client_llm,
                model_id,
                revision_prompt,
                _build_generation_config(plan["section_tokens"], search_grounding_enabled),
                f"content_section_revision:{section_id}",
                prompt_debug=prompt_debug,
            ))
            section_markdowns[section_id] = _ensure_section_heading(revised, section["heading"])
            revised_count += 1

        if revised_count:
            assembled = _assemble_segmented_markdown(
                outline=outline,
                intro=intro,
                section_markdowns=section_markdowns,
                faq_markdown=faq_markdown,
                conclusion_markdown=conclusion_markdown,
            )
            coherence_review["revised_section_count"] = revised_count

    metadata = {
        "generation_mode": "segmented",
        "outline": outline,
        "section_count": len(sections),
        "depth": depth_key,
        "token_budget": _resolve_content_token_budget(content_type, depth_key),
        "coherence_review": coherence_review,
    }
    return assembled, metadata


async def _generate_segmented_report_content(
    *,
    pool,
    task_id: str,
    client_llm,
    model_id: str,
    context_prompt: str,
    content_type: str,
    depth: str | None,
    language: str,
    search_grounding_enabled: bool,
    prompt_debug: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Generate recommendation reports as outline -> findings -> actions -> review."""
    depth_key = _normalize_depth_key(depth)
    plan = _segmented_generation_plan(depth_key)
    depth_label = "Comprehensive" if depth_key == "authority" else depth_key.title()

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": f"正在生成 {depth_label} 建议报告结构...",
    })

    outline_prompt = f"""{context_prompt}

## 报告式分段生成：Report Outline
你现在只生成结构化建议报告大纲，不要写完整报告。

## 报告类型
Content Optimization Recommendations

## 深度
{depth_label}

## 语言
{language}

## 大纲要求
- findings 数量必须在 {plan['section_min']} 到 {plan['section_max']} 之间。
- 每个 finding 只诊断一个清晰问题或机会，避免重复。
- 每个 finding 必须能连接到后续行动建议。
- 行动计划必须有优先级、预期影响、执行难度和依赖项。
- 不要写成文章，不要写成 Reddit 帖；这是面向客户交付的建议报告。

## 输出 JSON Schema
{{
  "title": "报告标题",
  "executive_summary_brief": "执行摘要应完成的任务",
  "findings": [
    {{
      "id": "f1",
      "heading": "H2 发现标题",
      "diagnosis": "诊断结论",
      "evidence_needed": ["需要使用的证据或数据"],
      "business_impact": "业务影响",
      "recommended_direction": "建议方向",
      "target_words": 250
    }}
  ],
  "action_plan_brief": "优先行动计划应完成的任务",
  "review_brief": "最终复核应完成的任务",
  "coherence_rules": ["报告连贯性规则"]
}}"""

    outline = await _llm_json(
        client_llm,
        model_id,
        outline_prompt,
        "report_outline_generation",
        max_tokens=plan["outline_tokens"],
        prompt_debug=prompt_debug,
    )
    findings = _outline_findings(outline)
    if not findings:
        raise RuntimeError("report_outline_generation returned no findings")

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": f"✓ 建议报告大纲完成：{len(findings)} 个发现，开始分段生成",
        "data": {
            "generation_mode": "segmented_report",
            "depth": depth_key,
            "finding_count": len(findings),
            "title": outline.get("title"),
        },
    })

    outline_json = json.dumps(outline, ensure_ascii=False, indent=2)

    summary_prompt = f"""{context_prompt}

## 报告式分段生成：Executive Summary
请只写执行摘要，不要输出 H1，不要写 Findings 或 Actions。

## Report Outline
{outline_json}

## 写作要求
- 第一行必须是：## Executive Summary
- 概括最重要的诊断、机会和执行方向。
- 保持客户交付报告语气：清晰、直接、可执行。
- 不要编造未提供的数据。"""

    executive_summary = _strip_html_artifacts(await _llm_generate(
        client_llm,
        model_id,
        summary_prompt,
        _build_generation_config(plan["intro_tokens"], search_grounding_enabled),
        "report_executive_summary_generation",
        prompt_debug=prompt_debug,
    ))

    finding_markdowns: dict[str, str] = {}
    finding_summaries: list[str] = []
    for index, finding in enumerate(findings, start=1):
        finding_id = finding["id"]
        heading = finding["heading"]
        await append_status_log(pool, task_id, {
            "step": 3,
            "event": "detail",
            "label": f"正在生成报告发现 {index}/{len(findings)}：{heading}",
        })
        finding_prompt = f"""{context_prompt}

## 报告式分段生成：Finding Section
你现在只写一个 H2 发现章节。不要写完整报告，不要写行动计划。

## Report Outline
{outline_json}

## 当前 Finding
{json.dumps(finding, ensure_ascii=False, indent=2)}

## 已生成发现摘要
{chr(10).join(finding_summaries) or "无"}

## 写作要求
- 第一行必须是：## {heading}
- 结构建议：Diagnosis / Evidence / Impact / Recommended Direction。
- 只完成当前 finding，不重复其他 finding。
- 具体事实必须来自任务输入或 Search Grounding；无法确认的信息要保守表达。
- 输出纯 Markdown。"""
        finding_text = _strip_html_artifacts(await _llm_generate(
            client_llm,
            model_id,
            finding_prompt,
            _build_generation_config(plan["section_tokens"], search_grounding_enabled),
            f"report_finding_generation:{finding_id}",
            prompt_debug=prompt_debug,
        ))
        finding_markdowns[finding_id] = _ensure_section_heading(finding_text, heading)
        finding_summaries.append(f"{heading}: {finding.get('diagnosis', '')}")

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": "正在生成优先行动计划...",
    })
    action_prompt = f"""{context_prompt}

## 报告式分段生成：Prioritized Actions
请只写优先行动计划，不要重写 Findings。

## Report Outline
{outline_json}

## Findings 摘要
{chr(10).join(finding_summaries)}

## 写作要求
- 第一行必须是：## Prioritized Actions
- 用表格或编号列表给出优先级、行动、预期影响、执行难度、依赖项、下一步。
- 行动必须对应上文 findings。
- 不要加入无法验证的新事实。
- 输出纯 Markdown。"""
    action_plan = _strip_html_artifacts(await _llm_generate(
        client_llm,
        model_id,
        action_prompt,
        _build_generation_config(plan["faq_tokens"], search_grounding_enabled),
        "report_action_plan_generation",
        prompt_debug=prompt_debug,
    ))

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": "正在生成报告最终复核段...",
    })
    final_review_prompt = f"""{context_prompt}

## 报告式分段生成：Final Report Review Section
请只写报告最后的复核和执行守则章节，不要重写全文。

## Report Outline
{outline_json}

## Findings 摘要
{chr(10).join(finding_summaries)}

## 写作要求
- 第一行必须是：## Final Review
- 说明执行风险、验证方式、后续复盘节奏。
- 保持客户交付报告语气。
- 输出纯 Markdown。"""
    final_review = _strip_html_artifacts(await _llm_generate(
        client_llm,
        model_id,
        final_review_prompt,
        _build_generation_config(plan["conclusion_tokens"], search_grounding_enabled),
        "report_final_review_generation",
        prompt_debug=prompt_debug,
    ))

    assembled = _assemble_segmented_report_markdown(
        outline=outline,
        executive_summary=executive_summary,
        finding_markdowns=finding_markdowns,
        action_plan_markdown=action_plan,
        review_markdown=final_review,
    )

    await append_status_log(pool, task_id, {
        "step": 3,
        "event": "detail",
        "label": "正在进行建议报告连贯性复核...",
    })
    review_prompt = f"""{context_prompt}

## 报告式分段生成：Coherence Review
请评审下面这份已组装建议报告，只输出 JSON。不要重写全文。

## Report Outline
{outline_json}

## Assembled Report
{assembled[:24000]}

## 输出 JSON Schema
{{
  "overall_ok": true,
  "issues": [
    {{
      "finding_id": "f2",
      "problem": "问题描述",
      "revision_instruction": "给该 finding 的具体修订要求"
    }}
  ],
  "global_notes": ["整体建议"]
}}"""
    coherence_review = await _llm_json(
        client_llm,
        model_id,
        review_prompt,
        "report_coherence_review",
        max_tokens=plan["review_tokens"],
        prompt_debug=prompt_debug,
    )

    issues = coherence_review.get("issues")
    if isinstance(issues, list) and issues:
        finding_by_id = {finding["id"]: finding for finding in findings}
        revised_count = 0
        for issue in issues:
            if revised_count >= 2 or not isinstance(issue, dict):
                continue
            finding_id = str(issue.get("finding_id") or "").strip()
            finding = finding_by_id.get(finding_id)
            if not finding or finding_id not in finding_markdowns:
                continue
            await append_status_log(pool, task_id, {
                "step": 3,
                "event": "detail",
                "label": f"正在局部修订报告发现：{finding['heading']}",
            })
            revision_prompt = f"""{context_prompt}

## 报告式分段生成：Targeted Finding Revision
请只重写指定 Finding，保留 H2 标题，不要输出其他章节。

## Report Outline
{outline_json}

## 当前 Finding
{json.dumps(finding, ensure_ascii=False, indent=2)}

## 原 Finding 内容
{finding_markdowns[finding_id]}

## 复核发现的问题
{json.dumps(issue, ensure_ascii=False, indent=2)}

## 修订要求
- 修复复核指出的问题。
- 不引入无法验证的新事实。
- 保持建议报告语气。
- 第一行必须是：## {finding['heading']}"""
            revised = _strip_html_artifacts(await _llm_generate(
                client_llm,
                model_id,
                revision_prompt,
                _build_generation_config(plan["section_tokens"], search_grounding_enabled),
                f"report_finding_revision:{finding_id}",
                prompt_debug=prompt_debug,
            ))
            finding_markdowns[finding_id] = _ensure_section_heading(revised, finding["heading"])
            revised_count += 1

        if revised_count:
            assembled = _assemble_segmented_report_markdown(
                outline=outline,
                executive_summary=executive_summary,
                finding_markdowns=finding_markdowns,
                action_plan_markdown=action_plan,
                review_markdown=final_review,
            )
            coherence_review["revised_finding_count"] = revised_count

    return assembled, {
        "generation_mode": "segmented_report",
        "outline": outline,
        "finding_count": len(findings),
        "depth": depth_key,
        "token_budget": _resolve_content_token_budget(content_type, depth_key),
        "coherence_review": coherence_review,
    }


# ─── Step 2: Content Generation ──────────────────────────────────────

async def step_content_generation(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Generate content using strategy + brand profile + prompt targets."""
    strategy = inputs.get("strategy", {})
    brand_context = inputs.get("brand_context", {})
    template_runtime_config = inputs.get("template_runtime_config") or {}
    content_type = inputs.get("content_type") or template_runtime_config.get("default_content_type") or "faq"
    language = inputs.get("language", "zh-CN")
    count = inputs.get("count", 5)
    publish_platform = inputs.get("publish_platform") or template_runtime_config.get("default_publish_platform") or "official_site"
    depth = inputs.get("depth") or template_runtime_config.get("default_depth")
    product_facts = inputs.get("product_facts", {})
    target_prompt_ids = inputs.get("target_prompt_ids", [])
    topic_ids = inputs.get("topic_ids") or []
    analyzer_context = inputs.get("analyzer_context")
    reddit_discovery = inputs.get("reddit_discovery")
    official_website_discovery = inputs.get("official_website_discovery")
    citation_analysis_result = inputs.get("citation_analysis_result")
    # Migration 029 — RATF framework + data disclosure from step 1.
    metric_defs = inputs.get("content_metric_definitions") or []
    subgoal_defs = inputs.get("content_subgoal_definitions") or []
    include_data_disclosure = _resolve_include_data_disclosure(
        default=bool(inputs.get("include_data_disclosure", True)),
        template_runtime_config=template_runtime_config if isinstance(template_runtime_config, dict) else {},
    )
    selected_metrics = inputs.get("selected_metrics") or []
    selected_subgoals = inputs.get("selected_subgoals") or []

    await append_status_log(pool, task_id, {"step": 3, "event": "detail", "label": "正在加载目标 Prompts..."})

    # Load target prompts
    prompt_texts = []
    if target_prompt_ids:
        rows = await pool.fetch(
            """SELECT cp.text, cp.platform, cp.country, cp.intent, cp.product,
                      cp.topic_id, ct.topic_name
               FROM geo_client_prompts cp
               LEFT JOIN geo_client_topics ct
                 ON ct.id = cp.topic_id AND ct.client_id = cp.client_id
               WHERE cp.id = ANY($1::uuid[]) AND cp.client_id = $2::uuid""",
            target_prompt_ids, client_id,
        )
        prompt_texts = _dedupe_target_prompt_rows(rows)

    topics = []
    if topic_ids:
        rows = await pool.fetch(
            """SELECT topic_name, topic_type
               FROM geo_client_topics
               WHERE id = ANY($1::uuid[]) AND client_id = $2::uuid""",
            topic_ids, client_id,
        )
        topics = [dict(r) for r in rows]

    # Build brand context string
    brand_str = _build_brand_context(brand_context) if brand_context else ""

    # Compose generation prompt
    strategies_json = json.dumps(strategy.get("strategies", []), ensure_ascii=False, indent=2)
    strategy_summary = strategy.get("strategy_summary", "")

    content_type_labels = {
        "faq": "FAQ 问答内容",
        "aeo_article": "AEO 优化文章（800-1200字）",
        "article": "SEO 文章",
        "brief": "Content Brief（内容大纲）",
        "comparison": "产品对比/测评文",
        "platform_post": "平台定制帖",
        "reddit_article": "Reddit 平台文章",
        "official_website_article": "官网 SEO/AEO 长文",
        "howto": "How-to 教程",
        "listicle": "Listicle 列表文章",
        "recommendations": "优化建议报告",
    }

    await append_status_log(pool, task_id, {"step": 3, "event": "detail", "label": f"正在生成 {content_type_labels.get(content_type, content_type)}..."})

    model_id = await _resolve_content_model_id(pool, inputs)
    client_llm = await get_genai_client(model_id, role="pro")
    search_grounding_enabled = bool(inputs.get("search_grounding_enabled"))
    prompt_debug_enabled = await _content_prompt_debug_enabled(pool)
    prompt_debug = _content_prompt_debug_context(
        pool,
        task_id=task_id,
        client_id=client_id,
        template_runtime_config=template_runtime_config,
        content_type=content_type,
        publish_platform=publish_platform,
        enabled=prompt_debug_enabled,
    )

    opp_context = ""
    if analyzer_context:
        opps = analyzer_context.get("content_opportunities", [])
        if opps:
            opp_context = f"\n## 选题机会参考\n{json.dumps(opps[:3], ensure_ascii=False, indent=2)}"

    # ── B-6 (2026-04-20) ── Soft guidance for addressing target prompts.
    # When the user (or AI discovery) has selected specific client prompts
    # — especially underperforming ones — we want the generated content's
    # title and body to *address* those exact user questions. This is a
    # GUIDE, not a hard constraint: we give the LLM a ranked list of the
    # selected prompts and ask it to weave them into title + headings +
    # body where natural, but do not mandate verbatim inclusion. The
    # design intent is "content should echo the user's real questions"
    # without degrading into keyword stuffing.
    #
    # If prompts come with a `visibility_rank` hint (added by the
    # SaaS-side prompt picker when it surfaces underperformers first),
    # we pass that signal through so the LLM can prioritise the weakest
    # ones. Otherwise we fall back to the order the user selected them.
    target_prompt_guidance = ""
    if prompt_texts:
        ranked_preview = []
        for idx, p in enumerate(prompt_texts[:5]):
            rank_hint = p.get("visibility_rank")
            rank_tag = f" [可见度排名 #{rank_hint}]" if rank_hint else ""
            platform_label = p.get("platform") or "n/a"
            country_label = p.get("country") or "n/a"
            ranked_preview.append(
                f"{idx + 1}. \"{p.get('text', '')}\" (平台: {platform_label}, "
                f"国家: {country_label}, intent: {p.get('intent', 'n/a')}){rank_tag}"
            )
        target_prompt_guidance = (
            "\n## 目标问题呼应（建议,非硬约束）\n"
            "用户挑选了以下 AI 搜索 Prompts — 这些是真实用户会问的问题。\n"
            "请在生成内容时**优先回应**这些问题,尤其是带 [可见度排名] 的靠前条目\n"
            "(排名越靠后表示我们的品牌在该问题上表现越差,越值得集中火力)。\n\n"
            "具体建议(非强制):\n"
            "- 标题(H1)或引言段尽量呼应排名最靠后的那个 prompt 的核心疑问句(可改写,不必逐字)\n"
            "- 至少一个 H2 章节的标题建议采用其中一个 prompt 的问法变体\n"
            "- 正文回答时保留这些 prompt 的**关键实体和词汇**,便于 AI 搜索命中\n"
            "- 若用户 prompt 和当前 content_type 不契合,可跳过该条,不要硬塞\n\n"
            "目标 Prompts(按建议优先级排序):\n"
            + "\n".join(ranked_preview)
            + "\n"
        )

    strategy_prompt_sections = _build_strategy_prompt_sections(
        strategy=strategy if isinstance(strategy, dict) else {},
        template_runtime_config=template_runtime_config if isinstance(template_runtime_config, dict) else {},
    )
    strategy_sections_block = ""
    if any(str(v or "").strip() for v in strategy_prompt_sections.values()):
        strategy_sections_block = "\n".join([
            "## 策略维度（必须遵循每条策略的 5 个维度）",
            "",
            strategy_prompt_sections["dimension_section"],
            "",
            "## 硬性约束（Constraints）— 所有策略的约束合集",
            strategy_prompt_sections["constraints_section"],
            "",
            "## 后处理增强规则（Enhancement Rules）— 生成后自检",
            strategy_prompt_sections["enhancements_section"],
            "",
        ])

    # Content Brief produces structured outline, not full article
    is_brief = content_type == "brief"
    output_instruction = (
        "输出详细的内容大纲（Content Brief），包含：\n"
        "1. 内容目标和受众定位\n"
        "2. 章节结构（H2/H3 层级）及每节要点\n"
        "3. 每节推荐的关键数据点和引用来源\n"
        "4. 目标关键词列表\n"
        "5. 竞品差异化要点\n"
        "6. RAFT 评分目标\n"
        "注意：这是大纲，不是完整文章。"
    ) if is_brief else (
        f"{'生成 ' + str(count) + ' 条 FAQ（每条包含 Question 和 Answer）' if content_type == 'faq' else '生成完整文章'}\n"
        "输出纯 Markdown 格式的可发布内容。\n"
        "**严禁输出以下内容：**\n"
        "- 不要输出任何 HTML 标签（包括 <script>, <div>, <span> 等）\n"
        "- 不要输出 Schema Markup 或 JSON-LD 结构化数据\n"
        "- 不要输出代码块中的 HTML/JSON 代码\n"
        "- 只使用纯 Markdown 语法（#标题, **加粗**, *斜体*, 列表, 引用等）"
    )

    # ── Migration 029 — build RATF + data disclosure hard-constraint blocks
    ratf_metric_jobs = template_runtime_config.get("ratf_metric_jobs")
    ratf_rendering = template_runtime_config.get("ratf_rendering")
    ratf_block = _build_ratf_framework_block(
        metric_defs,
        subgoal_defs,
        ratf_metric_jobs if isinstance(ratf_metric_jobs, dict) else {},
        ratf_rendering if isinstance(ratf_rendering, dict) else {},
    )
    disclosure_block = _build_content_disclosure_block(
        include=include_data_disclosure,
        selected_metrics=selected_metrics,
        selected_subgoals=selected_subgoals,
        brand_context=brand_context,
        product_facts=product_facts,
        target_prompts=prompt_texts,
        analyzer_context=analyzer_context,
    )
    framework_section = f"{ratf_block}\n" if ratf_block else ""

    search_grounding_instruction = _build_search_grounding_instruction(search_grounding_enabled)
    freshness_context = _build_freshness_context()
    platform_instruction = _build_platform_instruction(publish_platform, template_runtime_config)
    publishable_resource_policy = _build_official_publishable_resource_policy(
        content_type,
        publish_platform,
        template_runtime_config,
        brand_context,
        official_website_discovery,
    )
    depth_instruction = _build_depth_instruction(depth, template_runtime_config)
    template_instruction = _build_template_instruction(template_runtime_config)
    reddit_discovery_instruction = _build_reddit_discovery_instruction(reddit_discovery)
    official_website_discovery_instruction = _build_official_website_discovery_instruction(official_website_discovery)
    citation_analysis_instruction = _build_citation_analysis_instruction(citation_analysis_result)
    derived_prompt_artifacts = _resolve_confirmed_prompt_artifacts(inputs)
    _validate_required_confirmed_prompt_artifacts(
        template_runtime_config if isinstance(template_runtime_config, dict) else {},
        derived_prompt_artifacts,
    )
    if not derived_prompt_artifacts:
        derived_prompt_artifacts = await _prepare_derived_prompt_artifacts(
            pool=pool,
            task_id=task_id,
            client_llm=client_llm,
            model_id=model_id,
            template_runtime_config=template_runtime_config if isinstance(template_runtime_config, dict) else {},
            brand_context=brand_context if isinstance(brand_context, dict) else {},
            reddit_discovery=reddit_discovery if isinstance(reddit_discovery, dict) else None,
            official_website_discovery=None,
            citation_analysis_result=citation_analysis_result if isinstance(citation_analysis_result, dict) else None,
            strategy=strategy if isinstance(strategy, dict) else {},
            prompt_texts=prompt_texts,
            prompt_debug=prompt_debug,
        )
    prompt_artifact_sections = _build_prompt_artifact_sections(
        template_runtime_config=template_runtime_config if isinstance(template_runtime_config, dict) else {},
        derived_artifacts=derived_prompt_artifacts,
        reddit_discovery_instruction=reddit_discovery_instruction,
        official_website_discovery_instruction=official_website_discovery_instruction,
        citation_analysis_instruction=citation_analysis_instruction,
    )
    topic_context_instruction = _build_topic_context_instruction(topics, prompt_texts)
    brand_visibility_instruction = _build_brand_visibility_instruction(brand_context)

    context_prompt = f"""你是一位专业的 GEO 内容创作者。请严格按照以下策略维度与质量框架生成内容。

{framework_section}{disclosure_block}
{search_grounding_instruction}
{freshness_context}
{platform_instruction}
{publishable_resource_policy}
{depth_instruction}
{template_instruction}
{prompt_artifact_sections}
{topic_context_instruction}
{brand_visibility_instruction}
## 内容类型
{content_type_labels.get(content_type, content_type)}

{strategy_sections_block}

## 品牌信息
{brand_str}

## 产品核心事实
{json.dumps(product_facts, ensure_ascii=False) if product_facts else "未提供"}

## 目标 AI 搜索 Prompts
{json.dumps(prompt_texts, ensure_ascii=False, indent=2) if prompt_texts else "未指定"}
{target_prompt_guidance}
## 发布平台
{publish_platform}

## 内容深度
{depth or template_runtime_config.get("default_depth") or "standard"}

## 语言
{language}
{opp_context}"""

    prompt = f"""{context_prompt}

## 输出要求
{output_instruction}"""

    max_tokens = _resolve_content_token_budget(content_type, depth)
    generation_metadata: dict[str, Any] = {
        "generation_mode": "single_shot",
        "token_budget": max_tokens,
        "derived_prompt_artifacts": derived_prompt_artifacts,
    }
    if _should_use_report_segmented_generation(content_type, depth):
        generated_content, segmented_metadata = await _generate_segmented_report_content(
            pool=pool,
            task_id=task_id,
            client_llm=client_llm,
            model_id=model_id,
            context_prompt=context_prompt,
            content_type=content_type,
            depth=depth,
            language=language,
            search_grounding_enabled=search_grounding_enabled,
            prompt_debug=prompt_debug,
        )
        generation_metadata.update(segmented_metadata)
    elif _should_use_segmented_generation(content_type, depth):
        generated_content, segmented_metadata = await _generate_segmented_longform_content(
            pool=pool,
            task_id=task_id,
            client_llm=client_llm,
            model_id=model_id,
            context_prompt=context_prompt,
            content_type=content_type,
            content_type_label=content_type_labels.get(content_type, content_type),
            depth=depth,
            language=language,
            search_grounding_enabled=search_grounding_enabled,
            template_runtime_config=template_runtime_config,
            prompt_debug=prompt_debug,
        )
        generation_metadata.update(segmented_metadata)
    else:
        config = _build_generation_config(
            max_tokens=max_tokens,
            search_grounding_enabled=search_grounding_enabled,
        )
        raw_content = await _llm_generate(
            client_llm,
            model_id,
            prompt,
            config,
            "content_generation",
            prompt_debug=prompt_debug,
        )
        # Post-process: strip HTML tags, Schema Markup, and JSON-LD blocks that Gemini sometimes injects
        generated_content = _strip_html_artifacts(raw_content) if raw_content else ""

    primary_brand_name = _extract_primary_brand_name(brand_context)
    generated_content = _normalize_content_markdown_for_output(
        generated_content,
        content_type=content_type,
        publish_platform=publish_platform,
    )
    generated_content = _normalize_official_internal_linking_section(
        generated_content,
        content_type=content_type,
        brand_name=primary_brand_name,
    )
    generated_content, helpful_resource_sanitizer = _sanitize_official_helpful_resources_to_verified_pool(
        generated_content,
        content_type=content_type,
        publish_platform=publish_platform,
        template_config=template_runtime_config,
        official_website_discovery=official_website_discovery,
    )
    if helpful_resource_sanitizer.get("removed_links"):
        generation_metadata["helpful_resource_sanitizer"] = helpful_resource_sanitizer
        await append_status_log(pool, task_id, {
            "step": 3,
            "event": "detail",
            "label": f"⚠ Helpful Resources 已移除 {len(helpful_resource_sanitizer.get('removed_links') or [])} 个未验证链接",
            "data": {"helpful_resource_sanitizer": helpful_resource_sanitizer},
        })
    require_brand_mention = bool(
        primary_brand_name
        and (
            content_type in _LONGFORM_CONTENT_TYPES
            or content_type in _REPORT_CONTENT_TYPES
            or publish_platform.lower() == "reddit"
        )
    )
    content_integrity_issues = _detect_content_integrity_issues(
        generated_content,
        brand_name=primary_brand_name,
        require_brand_mention=require_brand_mention,
    )
    if content_integrity_issues:
        generation_metadata["content_integrity_issues"] = content_integrity_issues
        await append_status_log(pool, task_id, {
            "step": 3,
            "event": "detail",
            "label": f"⚠ 内容完整性预检发现 {len(content_integrity_issues)} 个问题，质量评审将继续标记",
            "data": {"issues": content_integrity_issues},
        })

    await append_status_log(pool, task_id, {
        "step": 3, "event": "step_output", "label": "内容生成完成",
        "data": {
            "content_type": content_type,
            "preview": generated_content[:500] if generated_content else "",
            "search_grounding_enabled": search_grounding_enabled,
            "publish_platform": publish_platform,
            "depth": depth,
            "generation_mode": generation_metadata.get("generation_mode"),
            "token_budget": generation_metadata.get("token_budget"),
            "section_count": generation_metadata.get("section_count"),
            "finding_count": generation_metadata.get("finding_count"),
            "derived_prompt_artifact_keys": list(
                (generation_metadata.get("derived_prompt_artifacts") or {}).get("prepared_json", {}).keys()
            ) if isinstance(generation_metadata.get("derived_prompt_artifacts"), dict) else [],
            "content_integrity_issue_count": len(content_integrity_issues),
            "reddit_discovery_status": reddit_discovery.get("status") if isinstance(reddit_discovery, dict) else None,
            "official_website_discovery_status": official_website_discovery.get("status") if isinstance(official_website_discovery, dict) else None,
            "citation_analysis_enabled": bool(
                isinstance(citation_analysis_result, dict)
                and citation_analysis_result.get("enabled")
            ),
        },
    })

    return {
        "generated_content": generated_content,
        "model_used": model_id,
        "search_grounding_enabled": search_grounding_enabled,
        "publish_platform": publish_platform,
        "depth": depth,
        "reddit_discovery": reddit_discovery,
        "official_website_discovery": official_website_discovery,
        "citation_analysis_result": citation_analysis_result,
        "generation_metadata": generation_metadata,
    }


# ─── Step 3: Quality Review ──────────────────────────────────────────

async def step_quality_review(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Score generated content against selected Metrics/Sub-goals."""
    generated_content = inputs.get("generated_content", "")
    selected_metrics = inputs.get("selected_metrics", [])
    selected_subgoals = inputs.get("selected_subgoals", [])
    strategy = inputs.get("strategy", {})
    brand_context = inputs.get("brand_context") or {}
    content_type = inputs.get("content_type") or ""
    publish_platform = inputs.get("publish_platform") or ""
    template_runtime_config = inputs.get("template_runtime_config") or {}
    generation_metadata = inputs.get("generation_metadata") or {}
    citation_analysis_result = inputs.get("citation_analysis_result")
    prompt_debug_enabled = await _content_prompt_debug_enabled(pool)
    prompt_debug = _content_prompt_debug_context(
        pool,
        task_id=task_id,
        client_id=client_id,
        template_runtime_config=template_runtime_config,
        content_type=content_type,
        publish_platform=publish_platform,
        enabled=prompt_debug_enabled,
    )
    # Migration 029 — framework + disclosure inputs surface through here
    # so the audit trail can verify that the locked RATF metrics and the
    # "## 数据依据 (Data Sources)" chapter are actually present.
    metric_defs = inputs.get("content_metric_definitions") or []
    subgoal_defs = inputs.get("content_subgoal_definitions") or []
    include_data_disclosure = _resolve_include_data_disclosure(
        default=bool(inputs.get("include_data_disclosure", True)),
        template_runtime_config=template_runtime_config if isinstance(template_runtime_config, dict) else {},
    )

    # Verify the data disclosure chapter exists when the template
    # requires it. This catches the exact regression that prompted the
    # hard-constraint block (LLM silently dropping the closing chapter).
    disclosure_present = True
    if include_data_disclosure and generated_content:
        lowered = generated_content.lower()
        # Match either the Chinese heading or the bilingual variant.
        disclosure_present = (
            "## 数据依据" in generated_content
            or "data sources" in lowered
        )

    framework_coverage = _evaluate_framework_coverage(
        generated_content,
        metric_defs,
        template_runtime_config.get("quality_gate") if isinstance(template_runtime_config, dict) else {},
    )
    framework_missing = list(framework_coverage.get("missing") or [])

    await append_status_log(pool, task_id, {"step": 4, "event": "detail", "label": "正在评审内容质量..."})

    # Load sub-goal definitions
    sg_rows = await pool.fetch(
        """SELECT sg.id, sg.name_zh, sg.description, m.id AS metric_id, m.name_zh AS metric_name
           FROM geo_optimization_subgoals sg
           JOIN geo_optimization_metrics m ON sg.metric_id = m.id
           WHERE sg.id = ANY($1::text[])""",
        selected_subgoals,
    )
    scoring_criteria = [
        f"- {r['metric_name']} > {r['name_zh']}: {r['description']}" for r in sg_rows
    ]

    model_id = await _resolve_content_model_id(pool, inputs)
    client_llm = await get_genai_client(model_id, role="pro")
    review_content_excerpt = _build_review_content_excerpt(generated_content)

    prompt = f"""你是 GEO 内容质量评审专家。请对以下生成内容进行评分和评审。

{_build_freshness_context()}

## 必查质量问题
- 标题、引言、结论不得出现过期时间锚点，除非明确是在做历史回顾。
- 标题和正文不得有未完成句、截断句、重复结尾、残缺段落。
- 当前工具/平台格局必须符合 runtime date；旧工具或旧年份只能作为历史背景，不能当作当前状态。
- 如果提供了品牌名，内容必须自然体现 Brand Mention 目标，不得完全缺失品牌。
- 如果下面内容中出现 "[Middle content omitted for review prompt size]"，这是评审 prompt 为控制长度而省略的中间内容，不是文章正文截断；不得因此给出截断问题。
- 仍需重点检查可见标题、引言和结尾是否自身完整，是否存在重复结尾或承诺与正文不一致。

## 评分维度（每个 Sub-goal 打 1-10 分）
{chr(10).join(scoring_criteria)}

## 生成的内容
{review_content_excerpt}

{_build_citation_analysis_instruction(citation_analysis_result)}

## 输出要求（JSON）
{{
  "scores": [
    {{
      "subgoal_id": "xxx",
      "subgoal_name": "xxx",
      "metric_name": "xxx",
      "score": 8,
      "comment": "评语"
    }}
  ],
  "overall_score": 7.5,
  "improvement_suggestions": ["建议1", "建议2"],
  "summary": "一段话总结"
}}"""

    review_result = await _llm_json(
        client_llm,
        model_id,
        prompt,
        "quality_review",
        prompt_debug=prompt_debug,
    )
    if isinstance(review_result, dict) and review_result.get("overall_score") is not None:
        review_result["llm_overall_score"] = review_result.get("overall_score")

    # Attach framework + disclosure coverage to the quality review payload
    # so the frontend and audit log can surface missing pieces. These
    # don't fail the task, but they do downgrade the effective quality
    # score (by prepending issues) so Wentao can see the gap directly.
    if not isinstance(review_result, dict):
        review_result = {"issues": []}
    issues = review_result.get("issues")
    if issues is None or not isinstance(issues, list):
        issues = []
        review_result["issues"] = issues

    if include_data_disclosure and not disclosure_present:
        issues.insert(
            0,
            "内容缺失「数据依据 (Data Sources)」章节 — 模板开启了数据披露要求，"
            "但生成结果未追加该章节，请复核 prompt 硬约束是否生效。",
        )
        logger.warning(
            "[CONTENT-V2] Data disclosure chapter missing in generated content "
            "(task_id=%s)", task_id,
        )

    if framework_missing:
        issues.insert(
            0,
            f"内容未覆盖 RATF 维度: {', '.join(framework_missing)}",
        )

    primary_brand_name = _extract_primary_brand_name(brand_context)
    require_brand_mention = bool(
        primary_brand_name
        and (
            content_type in _LONGFORM_CONTENT_TYPES
            or content_type in _REPORT_CONTENT_TYPES
            or str(publish_platform).lower() == "reddit"
        )
    )
    integrity_issues = list(generation_metadata.get("content_integrity_issues") or [])
    fresh_integrity_issues = _detect_content_integrity_issues(
        generated_content,
        brand_name=primary_brand_name,
        require_brand_mention=require_brand_mention,
    )
    for issue in fresh_integrity_issues:
        if issue not in integrity_issues:
            integrity_issues.append(issue)

    quality_gate_config = (
        template_runtime_config.get("quality_gate")
        if isinstance(template_runtime_config, dict)
        else None
    )
    for issue in _detect_brand_density_issues(
        generated_content,
        brand_name=primary_brand_name,
        quality_gate_config=quality_gate_config,
    ):
        if issue not in integrity_issues:
            integrity_issues.append(issue)

    helpful_resource_link_policy = _evaluate_official_helpful_resource_link_policy(
        generated_content,
        content_type=content_type,
        publish_platform=publish_platform,
        brand_context=brand_context,
        official_website_discovery=inputs.get("official_website_discovery"),
        template_config=template_runtime_config,
    )
    if helpful_resource_link_policy.get("failures"):
        invalid_urls = sorted({
            str(link.get("url") or link.get("domain") or "")
            for link in helpful_resource_link_policy.get("failures") or []
            if str(link.get("url") or link.get("domain") or "")
        })
        if invalid_urls:
            issues.insert(
                0,
                "Helpful Resources 包含未通过 Official Website Discovery 验证的链接: "
                + ", ".join(invalid_urls[:5])
                + "。官网正文可学习 citation 来源结构，但不能默认把 citation URL 或同域幻觉路径放入资源列表。",
            )
    if helpful_resource_link_policy.get("warnings"):
        warning_domains = sorted({
            str(link.get("domain") or "")
            for link in helpful_resource_link_policy.get("warnings") or []
            if str(link.get("domain") or "")
        })
        if warning_domains:
            issues.insert(
                0,
                "Helpful Resources 包含中立权威外部链接，请确认是否需要保留: "
                + ", ".join(warning_domains),
            )

    if integrity_issues:
        for issue in reversed(integrity_issues):
            issues.insert(0, issue)
        logger.warning(
            "[CONTENT-V2] Content integrity issues detected in quality review "
            "(task_id=%s issues=%s)", task_id, integrity_issues,
        )

    review_result["framework_coverage"] = {
        **framework_coverage,
    }
    review_result["disclosure_coverage"] = {
        "required": bool(include_data_disclosure),
        "present": bool(disclosure_present),
        "ok": (not include_data_disclosure) or disclosure_present,
    }
    review_result["content_integrity"] = {
        "ok": not integrity_issues,
        "issues": integrity_issues,
        "current_year": _current_runtime_datetime().year,
        "brand_name": primary_brand_name or None,
        "brand_mention_count": _count_brand_mentions(generated_content, primary_brand_name) if primary_brand_name else None,
    }
    review_result["helpful_resource_link_policy"] = helpful_resource_link_policy

    review_result["citation_alignment"] = _evaluate_citation_alignment(
        generated_content,
        citation_analysis_result,
        quality_gate_config,
    )
    citation_review_mode = str(
        (quality_gate_config or {}).get("citation_alignment_review_mode") or ""
    ).lower()
    if (
        citation_review_mode in {"llm", "hybrid"}
        and isinstance(citation_analysis_result, dict)
        and citation_analysis_result.get("enabled")
    ):
        review_result["citation_alignment"] = await _review_citation_alignment_with_llm(
            generated_content=generated_content,
            citation_analysis_result=citation_analysis_result,
            base_alignment=review_result["citation_alignment"],
            mode=citation_review_mode,
        )
    if (
        review_result["citation_alignment"].get("required")
        and not review_result["citation_alignment"].get("ok", True)
    ):
        issues.insert(
            0,
            "内容未明显响应 Citation Analysis 的 primary_action="
            f"{review_result['citation_alignment'].get('primary_action')}; 需要围绕该动作补充结构或措辞。",
        )

    quality_gate_result = _run_configured_quality_gate(
        generated_content,
        quality_gate_config,
        context={"brand_name": primary_brand_name},
    )
    if (
        (quality_gate_config or {}).get("framework_coverage_as_blocker")
        and framework_missing
    ):
        _append_post_revision_failure(
            quality_gate_result,
            rule_id="framework_coverage_missing",
            issue_type="framework_coverage",
            message=f"Generated content misses required framework dimensions: {', '.join(framework_missing)}.",
            matches=framework_missing,
        )
    if (
        (quality_gate_config or {}).get("content_integrity_as_blocker")
        and integrity_issues
    ):
        _append_post_revision_failure(
            quality_gate_result,
            rule_id="content_integrity_failed",
            issue_type="content_integrity",
            message="Generated content has integrity, repetition, truncation, or brand-density issues.",
            matches=integrity_issues[:3],
        )
    if helpful_resource_link_policy.get("failures"):
        resource_rule = _resource_link_policy_rule(template_runtime_config)
        _append_post_revision_failure(
            quality_gate_result,
            rule_id=resource_rule["id"],
            issue_type=resource_rule["type"],
            message=resource_rule["message"],
            matches=[
                f"{link.get('label')} -> {link.get('url') or link.get('domain')}"
                for link in helpful_resource_link_policy.get("failures") or []
            ][:5],
        )
    if helpful_resource_link_policy.get("warnings"):
        quality_gate_result.setdefault("warnings", []).append({
            "rule_id": "official_helpful_resources_neutral_external_links",
            "type": "official_resource_link_policy",
            "severity": "warning",
            "message": "Helpful Resources contains neutral-authority external links; verify they are intentional.",
            "matches": [
                f"{link.get('label')} -> {link.get('domain')}"
                for link in helpful_resource_link_policy.get("warnings") or []
            ][:5],
        })
    review_result = _apply_quality_gate_to_review(
        review_result,
        quality_gate_result,
        quality_gate_config,
    )

    # Build final output
    output = {
        "content": generated_content,
        "content_markdown": generated_content,  # Frontend reads this field
        "citation_analysis_summary_markdown": _build_citation_analysis_summary_markdown(citation_analysis_result),
        "content_type": content_type,
        "strategy": strategy,
        "quality_review": review_result,
        "citation_analysis_result": citation_analysis_result,
        "selected_metrics": selected_metrics,
        "selected_subgoals": selected_subgoals,
        "model_used": model_id,
    }

    await append_status_log(pool, task_id, {
        "step": 4, "event": "step_output", "label": "质量评审完成",
        "data": {
            "overall_score": review_result.get("overall_score"),
            "scores": review_result.get("scores", []),
            "improvement_suggestions": review_result.get("improvement_suggestions", [])[:5],
            "summary": review_result.get("summary", ""),
            "framework_coverage": review_result.get("framework_coverage"),
            "disclosure_coverage": review_result.get("disclosure_coverage"),
            "quality_gate": review_result.get("quality_gate"),
        },
    })

    return {"_output": output, "model_used": model_id}


async def step_content_revise(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Revise generated content only when the configured Quality Gate fails."""
    output = dict(inputs.get("_output") or {})
    review_result = dict(output.get("quality_review") or {})
    quality_gate_result = review_result.get("quality_gate") or {}
    template_runtime_config = inputs.get("template_runtime_config") or {}
    quality_gate_config = template_runtime_config.get("quality_gate") if isinstance(template_runtime_config, dict) else {}
    citation_analysis_result = inputs.get("citation_analysis_result") or output.get("citation_analysis_result")
    official_website_discovery = inputs.get("official_website_discovery") or output.get("official_website_discovery")

    if not quality_gate_result.get("enabled"):
        await append_status_log(pool, task_id, {
            "step": 5,
            "event": "detail",
            "label": "Quality Gate 未启用，跳过 Revise",
        })
        await update_step_status(pool, task_id, 6, "done")
        await update_step_status(pool, task_id, 7, "done")
        await update_step_status(pool, task_id, 8, "done")
        return {"_output": output}

    if not quality_gate_result.get("revise_required"):
        status = quality_gate_result.get("status") or ("pass_with_warnings" if quality_gate_result.get("warnings") else "pass")
        await append_status_log(pool, task_id, {
            "step": 5,
            "event": "detail",
            "label": f"Quality Gate 状态为 {status}，无需 Revise，跳过",
        })
        await update_step_status(pool, task_id, 6, "skipped")
        await update_step_status(pool, task_id, 7, "skipped")
        await update_step_status(pool, task_id, 8, "skipped")
        return {"_output": output}

    max_attempts = min(int((quality_gate_config or {}).get("max_revise_attempts", 1)), 2)
    if max_attempts <= 0:
        await append_status_log(pool, task_id, {
            "step": 5,
            "event": "detail",
            "label": "Quality Gate 未通过，但模板禁用了自动 Revise",
        })
        await update_step_status(pool, task_id, 6, "skipped")
        await update_step_status(pool, task_id, 7, "skipped")
        await update_step_status(pool, task_id, 8, "skipped")
        return {"_output": output}

    generated_content = output.get("content_markdown") or output.get("content") or inputs.get("generated_content") or ""
    if not generated_content:
        await update_step_status(pool, task_id, 6, "skipped")
        await update_step_status(pool, task_id, 7, "skipped")
        await update_step_status(pool, task_id, 8, "skipped")
        return {"_output": output}

    await append_status_log(pool, task_id, {
        "step": 5,
        "event": "detail",
            "label": (
                f"Quality Gate 需要 Revise：{quality_gate_result.get('failure_count', 0)} 个阻断项 / "
                f"{quality_gate_result.get('warning_count', 0)} 个警告，正在定向修正..."
            ),
        "data": {"quality_gate": quality_gate_result},
    })

    model_id = await _resolve_content_model_id(pool, inputs)
    client_llm = await get_genai_client(model_id, role="pro")
    content_type = output.get("content_type") or inputs.get("content_type") or ""
    publish_platform = inputs.get("publish_platform") or output.get("publish_platform") or ""
    brand_context = inputs.get("brand_context") or {}
    prompt_debug_enabled = await _content_prompt_debug_enabled(pool)
    prompt_debug = _content_prompt_debug_context(
        pool,
        task_id=task_id,
        client_id=client_id,
        template_runtime_config=template_runtime_config,
        content_type=content_type,
        publish_platform=publish_platform,
        enabled=prompt_debug_enabled,
    )
    pre_revision_review = copy.deepcopy(review_result)
    revised_content = generated_content
    attempt_records: list[dict[str, Any]] = []
    current_gate = quality_gate_result
    for attempt_number in range(1, max_attempts + 1):
        if attempt_number == 2:
            await update_step_status(pool, task_id, 7, "running")
            await append_status_log(pool, task_id, {
                "step": 7,
                "event": "start",
                "label": "第二轮 Revise...",
            })
        revision_prompt = _build_quality_gate_revision_prompt(
            generated_content=revised_content,
            quality_gate_result=current_gate,
            content_type=content_type,
            publish_platform=publish_platform,
            brand_context=brand_context,
            template_runtime_config=template_runtime_config,
            citation_analysis_result=citation_analysis_result if isinstance(citation_analysis_result, dict) else None,
            attempt_number=attempt_number,
            max_attempts=max_attempts,
        )
        revised_content = _strip_html_artifacts(await _llm_generate(
            client_llm,
            model_id,
            revision_prompt,
            _build_generation_config(
                max_tokens=_resolve_content_token_budget(content_type, inputs.get("depth")),
                search_grounding_enabled=bool(inputs.get("search_grounding_enabled")),
            ),
            f"content_quality_gate_revision_attempt_{attempt_number}",
            prompt_debug=prompt_debug,
        ))
        revised_content = _normalize_content_markdown_for_output(
            revised_content,
            content_type=content_type,
            publish_platform=publish_platform,
        )
        revised_content = _normalize_official_internal_linking_section(
            revised_content,
            content_type=content_type,
            brand_name=_extract_primary_brand_name(brand_context),
        )
        revised_content, helpful_resource_sanitizer = _sanitize_official_helpful_resources_to_verified_pool(
            revised_content,
            content_type=content_type,
            publish_platform=publish_platform,
            template_config=template_runtime_config,
            official_website_discovery=official_website_discovery,
        )
        if helpful_resource_sanitizer.get("removed_links"):
            await append_status_log(pool, task_id, {
                "step": 5 if attempt_number == 1 else 7,
                "event": "detail",
                "label": f"Helpful Resources 修订后清理了 {len(helpful_resource_sanitizer.get('removed_links') or [])} 个未验证链接",
                "data": {"helpful_resource_sanitizer": helpful_resource_sanitizer},
            })

        if attempt_number == 1:
            await update_step_status(pool, task_id, 6, "running")
            await append_status_log(pool, task_id, {
                "step": 6,
                "event": "start",
                "label": "第一轮修订后复查...",
            })
        else:
            await update_step_status(pool, task_id, 8, "running")
            await append_status_log(pool, task_id, {
                "step": 8,
                "event": "start",
                "label": "第二轮修订后复查...",
            })
        review_result = await _build_post_revision_quality_review(
            revised_content=revised_content,
            pre_revision_review=pre_revision_review,
            quality_gate_config=quality_gate_config,
            metric_defs=inputs.get("content_metric_definitions") or [],
            include_data_disclosure=bool(inputs.get("include_data_disclosure", True)),
            brand_context=brand_context,
            content_type=content_type,
            publish_platform=publish_platform,
            citation_analysis_result=citation_analysis_result if isinstance(citation_analysis_result, dict) else None,
            official_website_discovery=official_website_discovery,
            resource_link_policy_config=template_runtime_config.get("resource_link_policy") if isinstance(template_runtime_config, dict) else {},
        )
        revised_gate = review_result.get("quality_gate") or {}
        attempt_records.append({
            "attempt": attempt_number,
            "status_after_revise": revised_gate.get("status"),
            "passed_after_revise": revised_gate.get("passed"),
            "remaining_failure_count": revised_gate.get("failure_count", 0),
            "remaining_warning_count": revised_gate.get("warning_count", 0),
            "failure_rule_ids": [
                failure.get("rule_id")
                for failure in (revised_gate.get("failures") or [])
                if isinstance(failure, dict)
            ],
        })
        if attempt_number == 1:
            await update_step_status(pool, task_id, 5, "done")
            await update_step_status(pool, task_id, 6, "done")
            await append_status_log(pool, task_id, {
                "step": 6,
                "event": "step_output",
                "label": f"第一轮修订后复查完成：{revised_gate.get('status')}",
                "data": {"quality_gate": revised_gate},
            })
        else:
            await update_step_status(pool, task_id, 7, "done")
            await update_step_status(pool, task_id, 8, "done")
            await append_status_log(pool, task_id, {
                "step": 8,
                "event": "step_output",
                "label": f"第二轮修订后复查完成：{revised_gate.get('status')}",
                "data": {"quality_gate": revised_gate},
            })
        await append_status_log(pool, task_id, {
            "step": 5 if attempt_number == 1 else 7,
            "event": "detail",
            "label": (
                f"Revise 第 {attempt_number}/{max_attempts} 轮完成："
                f"{revised_gate.get('status')}"
            ),
            "data": {"quality_gate": revised_gate},
        })
        if revised_gate.get("passed"):
            if attempt_number == 1:
                await update_step_status(pool, task_id, 7, "skipped")
                await update_step_status(pool, task_id, 8, "skipped")
                await append_status_log(pool, task_id, {
                    "step": 7,
                    "event": "detail",
                    "label": "第一轮已通过，跳过第二轮 Revise",
                })
            break
        if not revised_gate.get("failures"):
            if attempt_number == 1:
                await update_step_status(pool, task_id, 7, "skipped")
                await update_step_status(pool, task_id, 8, "skipped")
                await append_status_log(pool, task_id, {
                    "step": 7,
                    "event": "detail",
                    "label": "复查无阻断项，跳过第二轮 Revise",
                })
            break
        current_gate = revised_gate

    if len(attempt_records) < 2:
        await update_step_status(pool, task_id, 7, "skipped")
        await update_step_status(pool, task_id, 8, "skipped")

    revised_gate = review_result.get("quality_gate") or {}
    review_result["revision"] = {
        "attempted": True,
        "attempt_count": len(attempt_records),
        "max_attempts": max_attempts,
        "attempts": attempt_records,
        "passed_after_revise": revised_gate.get("passed"),
        "status_after_revise": revised_gate.get("status"),
        "remaining_failure_count": revised_gate.get("failure_count", 0),
        "remaining_warning_count": revised_gate.get("warning_count", 0),
    }

    output["content"] = revised_content
    output["content_markdown"] = revised_content
    output["pre_revision_quality_review"] = pre_revision_review
    output["quality_review"] = review_result
    output["revision_metadata"] = review_result["revision"]

    await append_status_log(pool, task_id, {
        "step": 5,
        "event": "step_output",
        "label": "内容修正完成" if revised_gate.get("passed") else "内容修正完成，但需要人工复核",
        "data": {
            "quality_gate": revised_gate,
            "revision": review_result["revision"],
        },
    })

    return {"_output": output, "model_used": model_id}


# ─── Pipeline Registration ───────────────────────────────────────────

CONTENT_V2_STEPS = [
    WorkflowStep(1, "citation_analysis", "Citation Analysis", step_citation_analysis),
    WorkflowStep(2, "strategy_generation", "策略生成", step_strategy_generation),
    WorkflowStep(3, "content_generation", "内容生成", step_content_generation),
    WorkflowStep(4, "quality_review", "质量评审", step_quality_review),
    WorkflowStep(5, "revise_round_1", "第一轮 Revise", step_content_revise),
]


async def run_content_v2_pipeline(task_id: str, inputs: dict, client_id: str):
    await run_pipeline(task_id, CONTENT_V2_STEPS, inputs, client_id)


# Override the existing content_generation registration
register_pipeline("content_generation", run_content_v2_pipeline)
