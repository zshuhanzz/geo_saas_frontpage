"""
Content-preselect router.

Extracted from ``routers/tasks.py`` in Phase 3A refactor (2026-04-25).
Owns the "AI 帮我发现" (ai_discover) preselect endpoints used by the Content
Generation wizard, plus the supporting prompt/topic ranking endpoints that
power its underlying picks (worst-performing topics + prompts) and the
client-platform helper.

Endpoints (mounted under ``/api/agent/tasks``):
    - GET  /client-platforms    — list client's configured AI platforms
    - GET  /prompts/ranked      — prompts ranked by worst-performing dimension
    - GET  /topics/ranked       — topics ranked by worst-performing dimension
    - POST /content/preselect   — AI Preselect: pick worst topic + 5 prompts + form defaults
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from google.genai import types as genai_types
from pydantic import BaseModel, Field

from database import get_pool
from llm.client import get_genai_client, get_model_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/tasks", tags=["tasks", "content_preselect"])


# ─── Response models ──────────────────────────────────────────────────


class RankedPromptOut(BaseModel):
    """One row of ``GET /prompts/ranked`` — surfaces the worst-performing
    prompts by visibility / citation / sentiment dimension."""

    id: str
    ids: list[str] = Field(default_factory=list)
    prompt_text: Optional[str] = None
    platform: Optional[str] = None
    platforms: list[str] = Field(default_factory=list)
    country: Optional[str] = None
    countries: list[str] = Field(default_factory=list)
    intent: Optional[str] = None
    topic_name: Optional[str] = None
    mention_count: int = 0
    avg_position: float = 0.0
    citation_count: int = 0
    negative_count: int = 0


class RankedPromptPageOut(BaseModel):
    items: list[RankedPromptOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10
    view_mode: str = "detail"


class RankedTopicOut(BaseModel):
    """One row of ``GET /topics/ranked`` — topic-level rollup of underperformance."""

    id: str
    topic_name: Optional[str] = None
    prompt_count: int = 0
    mention_count: int = 0
    citation_count: int = 0
    negative_count: int = 0


class PreselectOut(BaseModel):
    """``POST /content/preselect`` response.

    Three statuses:
      - ``ok``         : preselected topic + prompts + form defaults populated
      - ``no_data``    : zero-data guard tripped — no signal anywhere
      - ``no_active_prompts``: client has data but no active prompts to anchor on
    """

    mode: str = "ai_discover"
    status: str
    message: Optional[str] = None
    sort_dimension: Optional[str] = None
    target_topic_id: Optional[str] = None
    target_topic_name: Optional[str] = None
    target_prompt_ids: list[str] = Field(default_factory=list)
    content_type: Optional[str] = None
    publish_platform: Optional[str] = None
    recommended_sub_goals: list[str] = Field(default_factory=list)
    reasoning: Optional[str] = None


class RedditDiscoverRequest(BaseModel):
    client_id: str
    source: str = "p0_web_search"
    reddit_urls: str = ""
    subreddits: str = ""
    keywords: str = ""
    topic_ids: list[str] = Field(default_factory=list)
    prompt_ids: list[str] = Field(default_factory=list)
    content_type: Optional[str] = None


class RedditDiscoverOut(BaseModel):
    source: str
    status: str
    summary: str = ""
    subreddits: list[dict] = Field(default_factory=list)
    community_questions: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    competitor_signals: list[str] = Field(default_factory=list)
    content_angles: list[dict] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    model_used: Optional[str] = None


class OfficialWebsiteDiscoverRequest(BaseModel):
    client_id: str
    source: str = "p0_web_search"
    official_website_urls: str = ""
    topic_ids: list[str] = Field(default_factory=list)
    prompt_ids: list[str] = Field(default_factory=list)
    content_type: Optional[str] = None


class OfficialWebsiteDiscoverOut(BaseModel):
    source: str
    status: str
    summary: str = ""
    pages_reviewed: list[dict] = Field(default_factory=list)
    content_gaps: list[str] = Field(default_factory=list)
    missing_use_cases: list[str] = Field(default_factory=list)
    brand_extractability_gaps: list[str] = Field(default_factory=list)
    commercial_conversion_gaps: list[str] = Field(default_factory=list)
    recommended_article_angles: list[dict] = Field(default_factory=list)
    faq_opportunities: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    model_used: Optional[str] = None


# Intent → content_type mapping. Mirrors the prompt-authoring taxonomy:
# users who ask "which X is best for Y" (Specifics Inquiry) tend to find
# their answer in FAQ-shaped content; Solution Discovery ("how do I …?")
# reads better as long-form article; Competitive Evaluation comparisons
# fit AEO article form factor. Default fallback = brief for everything else.
_INTENT_TO_CONTENT_TYPE = {
    "Specifics Inquiry": "faq",
    "Solution Discovery": "article",
    "Competitive Evaluation": "aeo_article",
}


def _coerce_json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def _load_template_preselect_config(pool, template_id: str | None) -> dict:
    if not template_id:
        return {}
    tpl_row = await pool.fetchrow(
        """
        SELECT defaults, wizard_config
        FROM geo_report_templates
        WHERE id = $1::uuid
        """,
        template_id,
    )
    if not tpl_row:
        return {}

    defaults = _coerce_json_object(tpl_row["defaults"])
    wc = _coerce_json_object(tpl_row["wizard_config"])
    steps = _coerce_json_object(wc.get("steps"))
    content_goal = _coerce_json_object(steps.get("content_goal"))
    content_type_cfg = _coerce_json_object(steps.get("content_type"))
    generation_config = _coerce_json_object(steps.get("generation_config"))
    sub_goals = content_goal.get("default_sub_goals")

    return {
        "content_type": content_type_cfg.get("default") or defaults.get("content_type"),
        "publish_platform": generation_config.get("default_publish_platform") or defaults.get("publish_platform"),
        "recommended_sub_goals": [str(x) for x in sub_goals] if isinstance(sub_goals, list) else [],
    }


def _resolve_preselect_publish_platform(template_preselect: dict) -> str:
    """Resolve the publishing channel for AI preselect without using AI-engine names."""
    value = template_preselect.get("publish_platform")
    return str(value).strip() if value else "official_site"


@router.get("/client-platforms", response_model=list[str])
async def get_client_platforms(client_id: str) -> list[str]:
    """Return the list of AI platforms configured for this client."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT config_platforms FROM geo_clients WHERE id = $1::uuid",
        client_id,
    )
    if not row:
        return []
    return row["config_platforms"] or []


@router.post("/reddit/discover", response_model=RedditDiscoverOut)
async def discover_reddit_context(body: RedditDiscoverRequest) -> RedditDiscoverOut:
    """P0 Reddit Discover via Gemini Search Grounding.

    This endpoint intentionally separates P0 and P1 product paths:
    - P0 uses Google Search grounding against user-provided Reddit URLs,
      subreddit names, and keywords.
    - P1 is reserved for authenticated Reddit API access and returns a
      clear "not enabled yet" response until OAuth, rate limiting, and data governance
      are implemented.
    """
    if body.source == "p1_reddit_api":
        raise HTTPException(
            status_code=501,
            detail="Reddit API discovery is planned but not enabled yet.",
        )
    if body.source != "p0_web_search":
        raise HTTPException(status_code=400, detail="Unsupported Reddit discovery source")

    pool = await get_pool()

    brand_row = await pool.fetchrow(
        """SELECT brand_name, tone_of_voice, target_audience,
                  key_messages, brand_values, language
           FROM geo_brand_profiles WHERE client_id = $1::uuid""",
        body.client_id,
    )
    brand_context = dict(brand_row) if brand_row else {}

    prompt_rows = []
    if body.prompt_ids:
        prompt_rows = await pool.fetch(
            """SELECT text, platform, intent
               FROM geo_client_prompts
               WHERE id = ANY($1::uuid[]) AND client_id = $2::uuid""",
            body.prompt_ids,
            body.client_id,
        )
    prompts = [dict(r) for r in prompt_rows]

    topic_rows = []
    if body.topic_ids:
        topic_rows = await pool.fetch(
            """SELECT topic_name
               FROM geo_client_topics
               WHERE id = ANY($1::uuid[]) AND client_id = $2::uuid""",
            body.topic_ids,
            body.client_id,
        )
    topics = [r["topic_name"] for r in topic_rows]

    model_id = await get_model_id("pro")
    client = await get_genai_client(model_id, role="pro")

    prompt = f"""You are a senior Reddit content strategist for GEO optimization.

Use Google Search grounding to investigate Reddit context only from the user-provided URLs, subreddit names, keywords, and closely related Reddit search results.

## Client Brand Context
{json.dumps(brand_context, ensure_ascii=False, indent=2)}

## Internal GEO Weak Signals
Selected topics:
{json.dumps(topics, ensure_ascii=False, indent=2)}

Selected prompts:
{json.dumps(prompts, ensure_ascii=False, indent=2)}

## User-provided Reddit discovery inputs
Reddit URLs:
{body.reddit_urls or "(none provided)"}

Subreddits:
{body.subreddits or "(none provided)"}

Keywords:
{body.keywords or "(none provided)"}

## Task
Find the Reddit external context that should shape a Reddit-ready content generation task.

Focus on:
1. Subreddits and discussion spaces likely relevant to this topic.
2. Common user questions and phrasing.
3. Objections, skepticism, and anti-promotion risks.
4. Competitor or alternative-tool signals if visible.
5. Content opportunities: attack, defend, compare, educate, refresh.
6. Source URLs that should be used or reviewed.

Do not invent Reddit posts, comments, subreddit names, vote counts, or user quotes. If you cannot verify something, keep it as a cautious hypothesis.

Return JSON only with this shape:
{{
  "summary": "short strategic summary",
  "subreddits": [
    {{"name": "r/example", "relevance": "why it matters", "risk": "posting risk or rule sensitivity"}}
  ],
  "community_questions": ["question or phrasing users appear to care about"],
  "objections": ["skeptical concern or anti-promotion risk"],
  "competitor_signals": ["competitor, alternative, or comparison signal"],
  "content_angles": [
    {{"type": "attack|defend|compare|educate|refresh", "angle": "recommended content angle", "why": "reason"}}
  ],
  "risks": ["risk to avoid during generation"],
  "source_urls": ["https://..."]
}}"""

    try:
        response = await client.aio.models.generate_content(
            model=model_id,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=8192,
                response_mime_type="application/json",
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
            ),
        )
        text = response.text or "{}"
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
        data = json.loads(text)
    except Exception as e:
        logger.warning("[REDDIT-DISCOVER] P0 discovery failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Reddit discovery failed: {e}")

    if not isinstance(data, dict):
        data = {}

    return RedditDiscoverOut(
        source="p0_web_search",
        status="ready",
        summary=str(data.get("summary") or ""),
        subreddits=data.get("subreddits") if isinstance(data.get("subreddits"), list) else [],
        community_questions=data.get("community_questions") if isinstance(data.get("community_questions"), list) else [],
        objections=data.get("objections") if isinstance(data.get("objections"), list) else [],
        competitor_signals=data.get("competitor_signals") if isinstance(data.get("competitor_signals"), list) else [],
        content_angles=data.get("content_angles") if isinstance(data.get("content_angles"), list) else [],
        risks=data.get("risks") if isinstance(data.get("risks"), list) else [],
        source_urls=data.get("source_urls") if isinstance(data.get("source_urls"), list) else [],
        model_used=model_id,
    )


@router.post("/official-website/discover", response_model=OfficialWebsiteDiscoverOut)
async def discover_official_website_context(body: OfficialWebsiteDiscoverRequest) -> OfficialWebsiteDiscoverOut:
    """P0 Official Website Discover via Gemini Search Grounding.

    The endpoint reads user-provided official website article URLs through
    Google Search grounding and turns them into a gap analysis for
    official-site SEO/AEO product-marketing content. It is intentionally
    separate from Reddit Discover because official-site content should be
    brand-forward, conversion-aware, and FAQ-friendly rather than community
    neutral.
    """
    if body.source != "p0_web_search":
        raise HTTPException(status_code=400, detail="Unsupported official website discovery source")
    if not body.official_website_urls.strip():
        raise HTTPException(status_code=400, detail="Official Website URLs are required")

    pool = await get_pool()

    brand_row = await pool.fetchrow(
        """SELECT brand_name, tone_of_voice, target_audience,
                  key_messages, brand_values, language
           FROM geo_brand_profiles WHERE client_id = $1::uuid""",
        body.client_id,
    )
    brand_context = dict(brand_row) if brand_row else {}

    prompt_rows = []
    if body.prompt_ids:
        prompt_rows = await pool.fetch(
            """SELECT text, platform, intent
               FROM geo_client_prompts
               WHERE id = ANY($1::uuid[]) AND client_id = $2::uuid""",
            body.prompt_ids,
            body.client_id,
        )
    prompts = [dict(r) for r in prompt_rows]

    topic_rows = []
    if body.topic_ids:
        topic_rows = await pool.fetch(
            """SELECT topic_name
               FROM geo_client_topics
               WHERE id = ANY($1::uuid[]) AND client_id = $2::uuid""",
            body.topic_ids,
            body.client_id,
        )
    topics = [r["topic_name"] for r in topic_rows]

    model_id = await get_model_id("pro")
    client = await get_genai_client(model_id, role="pro")

    prompt = f"""You are a senior SEO/AEO content strategist for official brand websites.

Use Google Search grounding to read and evaluate the official website article URLs provided by the user. If a URL cannot be read, report that limitation conservatively. Do not invent page content.

## Client Brand Context
{json.dumps(brand_context, ensure_ascii=False, indent=2)}

## Internal GEO Weak Signals
Selected topics:
{json.dumps(topics, ensure_ascii=False, indent=2)}

Selected prompts:
{json.dumps(prompts, ensure_ascii=False, indent=2)}

## Official Website URLs to analyze
{body.official_website_urls}

## Task
Identify what the existing official website content is missing and what a new article should cover to improve GEO performance.

Focus on:
1. Content gaps that weaken answerability, AEO extraction, or brand visibility.
2. Missing product use cases, buyer personas, comparison angles, and workflow examples.
3. Missing brand extractability signals: clear brand-fit summary, use cases, limitations, FAQs, and answer-ready paragraphs.
4. Commercial conversion gaps: CTA clarity, product value proof, feature-to-benefit mapping, examples, and trust signals.
5. Recommended official-site article angles that should complement the existing pages.
6. FAQ opportunities where the brand can be named naturally and helpfully.

Writing strategy for the next article:
- Official website content should be SEO/AEO product-marketing long-form, not Reddit style.
- It should make the brand more prominent than Reddit posts do, while staying accurate and useful.
- It should be brand-extractable, use-case rich, commercially dense, FAQ-friendly, and evidence conservative.

Return JSON only with this shape:
{{
  "summary": "short diagnosis of current official content gaps",
  "pages_reviewed": [
    {{"url": "https://...", "observed_focus": "what the page appears to cover", "gap": "what is missing"}}
  ],
  "content_gaps": ["specific gap to fill"],
  "missing_use_cases": ["use case or persona not covered well"],
  "brand_extractability_gaps": ["missing answer-ready brand signal"],
  "commercial_conversion_gaps": ["missing conversion or trust element"],
  "recommended_article_angles": [
    {{"angle": "article angle", "why": "why it fills a gap", "brand_role": "how the brand should be positioned"}}
  ],
  "faq_opportunities": ["brand-friendly FAQ question"],
  "source_urls": ["https://..."]
}}"""

    try:
        response = await client.aio.models.generate_content(
            model=model_id,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=8192,
                response_mime_type="application/json",
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
            ),
        )
        text = response.text or "{}"
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
        data = json.loads(text)
    except Exception as e:
        logger.warning("[OFFICIAL-WEBSITE-DISCOVER] P0 discovery failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Official Website discovery failed: {e}")

    if not isinstance(data, dict):
        data = {}

    return OfficialWebsiteDiscoverOut(
        source="p0_web_search",
        status="ready",
        summary=str(data.get("summary") or ""),
        pages_reviewed=data.get("pages_reviewed") if isinstance(data.get("pages_reviewed"), list) else [],
        content_gaps=data.get("content_gaps") if isinstance(data.get("content_gaps"), list) else [],
        missing_use_cases=data.get("missing_use_cases") if isinstance(data.get("missing_use_cases"), list) else [],
        brand_extractability_gaps=data.get("brand_extractability_gaps") if isinstance(data.get("brand_extractability_gaps"), list) else [],
        commercial_conversion_gaps=data.get("commercial_conversion_gaps") if isinstance(data.get("commercial_conversion_gaps"), list) else [],
        recommended_article_angles=data.get("recommended_article_angles") if isinstance(data.get("recommended_article_angles"), list) else [],
        faq_opportunities=data.get("faq_opportunities") if isinstance(data.get("faq_opportunities"), list) else [],
        source_urls=data.get("source_urls") if isinstance(data.get("source_urls"), list) else [],
        model_used=model_id,
    )


def _ranked_prompt_order_expr(sort_by: str) -> str:
    if sort_by == "citation":
        return "citation_count ASC, mention_count ASC"
    if sort_by == "sentiment":
        return "negative_count DESC, mention_count ASC"
    return "mention_count ASC, avg_position DESC"


def _ranked_prompt_metric_ctes() -> str:
    return """
        WITH m AS (
            SELECT client_prompt_id,
                   COUNT(*) AS mention_count,
                   SUM(mention_position)::NUMERIC(12,2) AS position_sum,
                   COUNT(mention_position) AS position_count,
                   AVG(mention_position)::NUMERIC(10,2) AS avg_position
            FROM geo_brand_mentions
            WHERE brand_role = 'own' AND client_id = $1::uuid
            GROUP BY client_prompt_id
        ),
        c AS (
            SELECT client_prompt_id,
                   COUNT(*) AS citation_count
            FROM geo_citations
            WHERE client_id = $1::uuid
            GROUP BY client_prompt_id
        ),
        s AS (
            SELECT client_prompt_id,
                   COUNT(*) AS negative_count
            FROM geo_sentiment_results
            WHERE client_id = $1::uuid AND sentiment = 'Negative'
            GROUP BY client_prompt_id
        ),
        prompt_metrics AS (
            SELECT
                p.id,
                p.text AS prompt_text,
                p.platform,
                p.country,
                p.intent,
                p.topic_id,
                t.topic_name,
                COALESCE(m.mention_count, 0) AS mention_count,
                COALESCE(m.position_sum, 0) AS position_sum,
                COALESCE(m.position_count, 0) AS position_count,
                COALESCE(m.avg_position, 0) AS avg_position,
                COALESCE(c.citation_count, 0) AS citation_count,
                COALESCE(s.negative_count, 0) AS negative_count
            FROM geo_client_prompts p
            JOIN geo_client_topics t ON p.topic_id = t.id
            LEFT JOIN m ON p.id = m.client_prompt_id
            LEFT JOIN c ON p.id = c.client_prompt_id
            LEFT JOIN s ON p.id = s.client_prompt_id
            WHERE p.client_id = $1::uuid
              AND p.is_active = true
              AND ($2::text IS NULL OR p.text ILIKE ('%' || $2::text || '%'))
        )
    """


def _ranked_prompt_out_from_row(row) -> RankedPromptOut:
    ids = [str(v) for v in (row.get("ids") or []) if str(v).strip()] if hasattr(row, "get") else [str(v) for v in (row["ids"] or []) if str(v).strip()]
    platforms = [str(v) for v in ((row.get("platforms") if hasattr(row, "get") else row["platforms"]) or []) if str(v).strip()]
    countries = [str(v) for v in ((row.get("countries") if hasattr(row, "get") else row["countries"]) or []) if str(v).strip()]
    row_id = str(row["id"])
    return RankedPromptOut(
        id=row_id,
        ids=ids or ([row_id] if not row_id.startswith("agg:") else []),
        prompt_text=row["prompt_text"],
        platform=row["platform"],
        platforms=platforms,
        country=row["country"],
        countries=countries,
        intent=row["intent"],
        topic_name=row["topic_name"],
        mention_count=int(row["mention_count"] or 0),
        avg_position=float(row["avg_position"] or 0),
        citation_count=int(row["citation_count"] or 0),
        negative_count=int(row["negative_count"] or 0),
    )


@router.get("/prompts/ranked-page", response_model=RankedPromptPageOut)
async def get_ranked_prompts_page(
    client_id: str,
    sort_by: str = "visibility",
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    view_mode: str = "detail",
) -> RankedPromptPageOut:
    """Return ranked prompts with pagination/search.

    ``detail`` returns one row per ``geo_client_prompts`` record.
    ``aggregate`` rolls rows with the same client prompt text/topic/intent into
    a single user-facing row and returns every underlying prompt id in ``ids``.
    """
    sort_by = sort_by if sort_by in ("visibility", "citation", "sentiment") else "visibility"
    view_mode = view_mode if view_mode in ("detail", "aggregate") else "detail"
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 10)))
    offset = (page - 1) * page_size
    search_value = search.strip() if search and search.strip() else None
    order_expr = _ranked_prompt_order_expr(sort_by)
    pool = await get_pool()

    if view_mode == "aggregate":
        sql = f"""
        {_ranked_prompt_metric_ctes()},
        grouped AS (
            SELECT
                ('agg:' || md5(prompt_text || '|' || topic_id::text || '|' || COALESCE(intent, ''))) AS id,
                ARRAY_AGG(id::text ORDER BY platform NULLS LAST, country NULLS LAST, id::text) AS ids,
                prompt_text,
                NULL::text AS platform,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT platform ORDER BY platform), NULL) AS platforms,
                NULL::text AS country,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT country ORDER BY country), NULL) AS countries,
                intent,
                topic_name,
                SUM(mention_count)::int AS mention_count,
                CASE
                    WHEN SUM(position_count) > 0 THEN ROUND((SUM(position_sum) / SUM(position_count))::numeric, 2)
                    ELSE 0
                END AS avg_position,
                SUM(citation_count)::int AS citation_count,
                SUM(negative_count)::int AS negative_count
            FROM prompt_metrics
            GROUP BY prompt_text, topic_id, topic_name, intent
        )
        SELECT *, COUNT(*) OVER()::int AS total_count
        FROM grouped
        ORDER BY {order_expr}
        LIMIT $3 OFFSET $4
        """
    else:
        sql = f"""
        {_ranked_prompt_metric_ctes()}
        SELECT
            id::text AS id,
            ARRAY[id::text] AS ids,
            prompt_text,
            platform,
            ARRAY_REMOVE(ARRAY[platform], NULL) AS platforms,
            country,
            ARRAY_REMOVE(ARRAY[country], NULL) AS countries,
            intent,
            topic_name,
            mention_count,
            avg_position,
            citation_count,
            negative_count,
            COUNT(*) OVER()::int AS total_count
        FROM prompt_metrics
        ORDER BY {order_expr}
        LIMIT $3 OFFSET $4
        """

    rows = await pool.fetch(sql, client_id, search_value, page_size, offset)
    total = int(rows[0]["total_count"]) if rows else 0
    return RankedPromptPageOut(
        items=[_ranked_prompt_out_from_row(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        view_mode=view_mode,
    )


@router.get("/prompts/ranked", response_model=list[RankedPromptOut])
async def get_ranked_prompts(
    client_id: str,
    sort_by: str = "visibility",
    limit: int = 20,
) -> list[RankedPromptOut]:
    """Return prompts ranked by worst-performing metric.

    sort_by options:
      - visibility: ascending by own-brand mention count (least visible first)
      - citation: ascending by own-domain citation count (least cited first)
      - sentiment: descending by negative sentiment count (most negative first)
    """
    result = await get_ranked_prompts_page(
        client_id=client_id,
        sort_by=sort_by,
        page=1,
        page_size=min(200, max(1, int(limit or 20))),
        view_mode="detail",
    )
    return result.items


@router.get("/topics/ranked", response_model=list[RankedTopicOut])
async def get_ranked_topics(
    client_id: str,
    sort_by: str = "visibility",
    limit: int = 20,
) -> list[RankedTopicOut]:
    """Return topics ranked by aggregate underperformance across their prompts.

    sort_by options mirror /prompts/ranked:
      - visibility: ascending by total own-brand mention count (least visible first)
      - citation: ascending by total own-domain citation count (least cited first)
      - sentiment: descending by total negative sentiment count (most negative first)

    Topic-level aggregate rolls up every active prompt under the topic.
    Used by the wizard's Topic picker (B-1b tier badge + B-2b auto-prefill).
    """
    pool = await get_pool()

    if sort_by == "citation":
        order_expr = "citation_count ASC, prompt_count DESC"
    elif sort_by == "sentiment":
        order_expr = "negative_count DESC, prompt_count DESC"
    else:
        order_expr = "mention_count ASC, prompt_count DESC"

    rows = await pool.fetch(
        f"""
        SELECT
            t.id,
            t.topic_name,
            (SELECT COUNT(*) FROM geo_client_prompts p
             WHERE p.topic_id = t.id AND p.is_active) AS prompt_count,
            COALESCE(m.mention_count, 0) AS mention_count,
            COALESCE(c.citation_count, 0) AS citation_count,
            COALESCE(s.negative_count, 0) AS negative_count
        FROM geo_client_topics t
        LEFT JOIN (
            SELECT p.topic_id, COUNT(*) AS mention_count
            FROM geo_brand_mentions bm
            JOIN geo_client_prompts p ON bm.client_prompt_id = p.id
            WHERE bm.brand_role = 'own' AND bm.client_id = $1::uuid
            GROUP BY p.topic_id
        ) m ON t.id = m.topic_id
        LEFT JOIN (
            SELECT p.topic_id, COUNT(*) AS citation_count
            FROM geo_citations cn
            JOIN geo_client_prompts p ON cn.client_prompt_id = p.id
            WHERE cn.client_id = $1::uuid
            GROUP BY p.topic_id
        ) c ON t.id = c.topic_id
        LEFT JOIN (
            SELECT p.topic_id, COUNT(*) AS negative_count
            FROM geo_sentiment_results sr
            JOIN geo_client_prompts p ON sr.client_prompt_id = p.id
            WHERE sr.client_id = $1::uuid AND sr.sentiment = 'Negative'
            GROUP BY p.topic_id
        ) s ON t.id = s.topic_id
        WHERE t.client_id = $1::uuid
          AND EXISTS (
            SELECT 1 FROM geo_client_prompts p
            WHERE p.topic_id = t.id AND p.is_active
          )
        ORDER BY {order_expr}
        LIMIT $2
        """,
        client_id, limit,
    )

    return [
        RankedTopicOut(
            id=str(r["id"]),
            topic_name=r["topic_name"],
            prompt_count=int(r["prompt_count"]),
            mention_count=int(r["mention_count"]),
            citation_count=int(r["citation_count"]),
            negative_count=int(r["negative_count"]),
        )
        for r in rows
    ]


@router.post("/content/preselect", response_model=PreselectOut)
async def preselect_content(
    body: dict = Body(...),
) -> PreselectOut:
    """AI Preselect endpoint — used by the Content Generation wizard
    when the user picks "AI 帮我发现" (ai_discover) in Mode Gate.

    Looks at the client's data across three underperformance dimensions
    and returns a bundle of suggested form values the wizard can
    bulk-apply:
      - worst-performing topic (by chosen sort dimension)
      - 5 worst-performing prompts under that topic
      - inferred content_type from the dominant prompt intent
      - preferred publish_platform (template default publishing channel)
      - recommended_sub_goals (inherited from the template, if provided)
      - human-readable reasoning string

    Zero-data case: if the client has no brand_mentions + citations +
    sentiment rows, returns status="no_data" so the UI can render a CTA
    back to the Prompts page instead of silently preselecting nothing.
    """
    client_id = body.get("client_id")
    sort_dimension = (body.get("sort_dimension") or "visibility").lower()
    template_id = body.get("template_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if sort_dimension not in ("visibility", "citation", "sentiment"):
        sort_dimension = "visibility"

    pool = await get_pool()
    template_preselect = await _load_template_preselect_config(pool, template_id)

    # 1) Zero-data guard — if all three signal tables are empty for this
    # client, the preselect has nothing to anchor on. Return a clear
    # reason so the UI surfaces the right CTA.
    counts = await pool.fetchrow(
        """
        SELECT
          (SELECT COUNT(*) FROM geo_brand_mentions    WHERE client_id=$1::uuid) AS bm,
          (SELECT COUNT(*) FROM geo_citations         WHERE client_id=$1::uuid) AS c,
          (SELECT COUNT(*) FROM geo_sentiment_results WHERE client_id=$1::uuid) AS s
        """,
        client_id,
    )
    if counts and counts["bm"] == 0 and counts["c"] == 0 and counts["s"] == 0:
        return PreselectOut(
            mode="ai_discover",
            status="no_data",
            message="暂无数据，请先配置 Prompt 并等待 Analyzer 处理完再试",
        )

    # 2) Pick the worst topic per the chosen dimension.
    if sort_dimension == "citation":
        topic_order = "citation_count ASC, prompt_count DESC"
    elif sort_dimension == "sentiment":
        topic_order = "negative_count DESC, prompt_count DESC"
    else:
        topic_order = "mention_count ASC, prompt_count DESC"

    worst_topic = await pool.fetchrow(
        f"""
        SELECT
            t.id,
            t.topic_name,
            (SELECT COUNT(*) FROM geo_client_prompts p
             WHERE p.topic_id = t.id AND p.is_active) AS prompt_count,
            COALESCE(m.mention_count, 0) AS mention_count,
            COALESCE(c.citation_count, 0) AS citation_count,
            COALESCE(s.negative_count, 0) AS negative_count
        FROM geo_client_topics t
        LEFT JOIN (
            SELECT p.topic_id, COUNT(*) AS mention_count
            FROM geo_brand_mentions bm
            JOIN geo_client_prompts p ON bm.client_prompt_id = p.id
            WHERE bm.brand_role = 'own' AND bm.client_id = $1::uuid
            GROUP BY p.topic_id
        ) m ON t.id = m.topic_id
        LEFT JOIN (
            SELECT p.topic_id, COUNT(*) AS citation_count
            FROM geo_citations cn
            JOIN geo_client_prompts p ON cn.client_prompt_id = p.id
            WHERE cn.client_id = $1::uuid
            GROUP BY p.topic_id
        ) c ON t.id = c.topic_id
        LEFT JOIN (
            SELECT p.topic_id, COUNT(*) AS negative_count
            FROM geo_sentiment_results sr
            JOIN geo_client_prompts p ON sr.client_prompt_id = p.id
            WHERE sr.client_id = $1::uuid AND sr.sentiment = 'Negative'
            GROUP BY p.topic_id
        ) s ON t.id = s.topic_id
        WHERE t.client_id = $1::uuid
          AND EXISTS (
            SELECT 1 FROM geo_client_prompts p
            WHERE p.topic_id = t.id AND p.is_active
          )
        ORDER BY {topic_order}
        LIMIT 1
        """,
        client_id,
    )

    if not worst_topic:
        return PreselectOut(
            mode="ai_discover",
            status="no_active_prompts",
            message="客户有数据但没有任何 active prompts，请先在 Prompts 页启用 prompts",
        )

    target_topic_id = str(worst_topic["id"])
    target_topic_name = worst_topic["topic_name"]

    # 3) Pick the 5 worst prompts under that topic.
    if sort_dimension == "citation":
        prompt_order = "citation_count ASC, mention_count ASC"
    elif sort_dimension == "sentiment":
        prompt_order = "negative_count DESC, mention_count ASC"
    else:
        prompt_order = "mention_count ASC, avg_position DESC"

    worst_prompts = await pool.fetch(
        f"""
        SELECT
            p.id,
            p.text AS prompt_text,
            p.platform,
            p.intent,
            COALESCE(m.mention_count, 0) AS mention_count,
            COALESCE(m.avg_position, 0) AS avg_position,
            COALESCE(c.citation_count, 0) AS citation_count,
            COALESCE(s.negative_count, 0) AS negative_count
        FROM geo_client_prompts p
        LEFT JOIN (
            SELECT client_prompt_id,
                   COUNT(*) AS mention_count,
                   AVG(mention_position)::NUMERIC(10,2) AS avg_position
            FROM geo_brand_mentions
            WHERE brand_role = 'own' AND client_id = $1::uuid
            GROUP BY client_prompt_id
        ) m ON p.id = m.client_prompt_id
        LEFT JOIN (
            SELECT client_prompt_id, COUNT(*) AS citation_count
            FROM geo_citations
            WHERE client_id = $1::uuid
            GROUP BY client_prompt_id
        ) c ON p.id = c.client_prompt_id
        LEFT JOIN (
            SELECT client_prompt_id, COUNT(*) AS negative_count
            FROM geo_sentiment_results
            WHERE client_id = $1::uuid AND sentiment = 'Negative'
            GROUP BY client_prompt_id
        ) s ON p.id = s.client_prompt_id
        WHERE p.client_id = $1::uuid
          AND p.topic_id = $2::uuid
          AND p.is_active = true
        ORDER BY {prompt_order}
        LIMIT 5
        """,
        client_id, target_topic_id,
    )
    target_prompt_ids = [str(r["id"]) for r in worst_prompts]

    # 4) Infer content_type from the dominant intent across the picked prompts.
    if worst_prompts:
        intent_counts: dict[str, int] = {}
        for r in worst_prompts:
            if r["intent"]:
                intent_counts[r["intent"]] = intent_counts.get(r["intent"], 0) + 1
        if intent_counts:
            dominant_intent = max(intent_counts.items(), key=lambda kv: kv[1])[0]
        else:
            dominant_intent = None
    else:
        dominant_intent = None
    inferred_content_type = _INTENT_TO_CONTENT_TYPE.get(dominant_intent or "", "brief")
    content_type = template_preselect.get("content_type") or inferred_content_type

    # 5) publish_platform is a publishing / social channel, not an AI engine.
    # Do not infer it from geo_results.platform (ChatGPT/Gemini/AiMode).
    # Existing templates can pin this via default_publish_platform; otherwise
    # use official_site as the neutral channel.
    publish_platform = _resolve_preselect_publish_platform(template_preselect)

    # 6) Pull sub_goals defaults from the template (if provided).
    recommended_sub_goals: list[str] = list(template_preselect.get("recommended_sub_goals") or [])

    # 7) Reasoning string
    dim_label = {"visibility": "可见度", "citation": "引用", "sentiment": "情感"}[sort_dimension]
    metric_val = (
        worst_topic["mention_count"] if sort_dimension == "visibility"
        else worst_topic["citation_count"] if sort_dimension == "citation"
        else worst_topic["negative_count"]
    )
    metric_label = (
        f"own-brand 提及 {metric_val} 次" if sort_dimension == "visibility"
        else f"own-domain 引用 {metric_val} 次" if sort_dimension == "citation"
        else f"负面情感 {metric_val} 条"
    )
    reasoning = (
        f"按「{dim_label}」维度排序，该客户在 '{target_topic_name}' 话题下"
        f"{metric_label}（共 {worst_topic['prompt_count']} 个 active prompts）"
        f"，是表现最差的话题。"
        f"推荐聚焦此话题下最弱的 {len(target_prompt_ids)} 个 prompts，"
        f"采用 {content_type} 形式在 {publish_platform} 平台发声。"
    )

    return PreselectOut(
        mode="ai_discover",
        status="ok",
        sort_dimension=sort_dimension,
        target_topic_id=target_topic_id,
        target_topic_name=target_topic_name,
        target_prompt_ids=target_prompt_ids,
        content_type=content_type,
        publish_platform=publish_platform,
        recommended_sub_goals=recommended_sub_goals,
        reasoning=reasoning,
    )
