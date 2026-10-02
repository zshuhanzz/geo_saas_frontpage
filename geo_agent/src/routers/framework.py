"""
Framework + Metrics router.

Extracted from ``routers/tasks.py`` in Phase 3A refactor (2026-04-25).
Owns the GEO Optimization Framework lookup endpoints (metrics/subgoals
hierarchy) and the analyzer-side metric registry endpoints (DB-backed list
+ live-schema discovery).

Endpoints (mounted under ``/api/agent/tasks``):
    - GET /framework/metrics            — Layer 1: optimization metrics
    - GET /framework/subgoals           — Layer 2: optimization subgoals
    - GET /framework/opportunity-tasks  — completed opportunity-discovery tasks
    - GET /metrics/list                 — analyzer metric registry (DB-backed)
    - GET /metrics/discover             — analyzer metric discovery (live schema → Gemini)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database import get_pool
from llm.client import get_genai_client, get_model_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/tasks", tags=["tasks", "framework"])


# ─── Response models ──────────────────────────────────────────────────


class FrameworkMetricOut(BaseModel):
    """One row from ``geo_optimization_metrics`` (Layer 1)."""

    id: str
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None


class FrameworkSubgoalOut(BaseModel):
    """One row from ``geo_optimization_subgoals`` (Layer 2)."""

    id: str
    metric_id: Optional[str] = None
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


class OpportunityTaskSummary(BaseModel):
    """Summary counts surfaced for the Content wizard's "import Analyzer
    output" picker."""

    topic_count: int = 0
    opportunity_count: int = 0
    platform_count: int = 0


class OpportunityTaskOut(BaseModel):
    """Compact view of one completed ``opportunity_discovery`` task."""

    id: str
    task_name: Optional[str] = None
    completed_at: Optional[str] = None
    topic_scope: Optional[str] = None
    summary: OpportunityTaskSummary = Field(default_factory=OpportunityTaskSummary)


class AnalysisMetricEntry(BaseModel):
    """One metric inside a domain bucket — shape is identical between the
    DB-backed ``/metrics/list`` and Gemini-driven ``/metrics/discover``
    endpoints so PromptEditor can use them interchangeably."""

    variable_name: str
    display_name: str
    description: str = ""
    unit: str = ""


# ───────── Optimization Framework (Layer 1 + Layer 2) ─────────

@router.get("/framework/metrics", response_model=list[FrameworkMetricOut])
async def list_metrics() -> list[FrameworkMetricOut]:
    """Return all active optimization metrics (Layer 1)."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, name_zh, name_en, description, icon, sort_order
           FROM geo_optimization_metrics
           WHERE is_active = true
           ORDER BY sort_order"""
    )
    return [FrameworkMetricOut(**dict(r)) for r in rows]


@router.get("/framework/subgoals", response_model=list[FrameworkSubgoalOut])
async def list_subgoals(
    metric_id: Optional[str] = None,
) -> list[FrameworkSubgoalOut]:
    """Return active sub-goals (Layer 2), optionally filtered by metric."""
    pool = await get_pool()
    if metric_id:
        rows = await pool.fetch(
            """SELECT id, metric_id, name_zh, name_en, description, sort_order
               FROM geo_optimization_subgoals
               WHERE is_active = true AND metric_id = $1
               ORDER BY sort_order""",
            metric_id,
        )
    else:
        rows = await pool.fetch(
            """SELECT id, metric_id, name_zh, name_en, description, sort_order
               FROM geo_optimization_subgoals
               WHERE is_active = true
               ORDER BY metric_id, sort_order"""
        )
    return [FrameworkSubgoalOut(**dict(r)) for r in rows]


@router.get(
    "/framework/opportunity-tasks", response_model=list[OpportunityTaskOut]
)
async def list_opportunity_tasks(client_id: str) -> list[OpportunityTaskOut]:
    """List completed opportunity discovery analysis tasks for a client.
    Used by Content Node 0 to import Analyzer results."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT t.id, t.task_name, t.completed_at, t.output,
                  t.inputs->>'topic' AS topic_scope
           FROM geo_agent_tasks t
           WHERE t.client_id = $1::uuid
             AND t.task_type = 'opportunity_discovery'
             AND t.status = 'COMPLETED'
           ORDER BY t.completed_at DESC
           LIMIT 20""",
        client_id,
    )
    results: list[OpportunityTaskOut] = []
    for r in rows:
        output = r["output"] if r["output"] else {}
        if isinstance(output, str):
            output = json.loads(output)
        results.append(OpportunityTaskOut(
            id=str(r["id"]),
            task_name=r["task_name"],
            completed_at=r["completed_at"].isoformat() if r["completed_at"] else None,
            topic_scope=r["topic_scope"],
            summary=OpportunityTaskSummary(
                topic_count=len(output.get("topic_quadrants", [])),
                opportunity_count=len(output.get("content_opportunities", [])),
                platform_count=len(output.get("platform_recommendations", [])),
            ),
        ))
    return results


# ───────── Analyzer Metric Registry & Discovery ─────────

# Domain → tables that are relevant for that analysis domain.
# v1.2: geo_company_mentions renamed to geo_brand_mentions, plus new
# product-level mention + tracked-URL tables surfaced for visibility /
# citation metric discovery.
_DOMAIN_TABLES = {
    "visibility": [
        "geo_brand_mentions", "geo_product_mentions",
        "geo_results", "geo_tasks",
        "geo_client_brands", "geo_client_peers", "geo_client_topic_products",
    ],
    "citation": [
        "geo_citations", "geo_results", "geo_tasks",
        "geo_client_domains", "geo_product_tracked_urls",
        "geo_domain_categories",
    ],
    "sentiment": [
        "geo_sentiment_results", "geo_sentiment_themes",
        "geo_results", "geo_tasks",
    ],
}

# In-memory cache: { domains_key: (timestamp, result) }
_discover_cache: dict[str, tuple[float, dict]] = {}
_DISCOVER_CACHE_TTL = 3600  # 1 hour — schema rarely changes


_DISCOVER_SYSTEM = """You are a database metrics expert for a GEO (Generative Engine Optimization) analytics platform.

Given database table schemas, generate a catalog of useful analytical metrics.

## Rules
1. Each metric must be computable from the provided tables.
2. Group metrics by domain (visibility, citation, sentiment).
3. Generate exactly 5 metrics per domain. Focus on metrics useful for brand GEO optimization.
4. For each metric: variable_name (snake_case, unique), display_name (Chinese, max 10 chars), description (Chinese, max 20 chars), domain, unit.
5. Keep output compact. No SQL in output.

## Output (JSON array):
[{"variable_name":"brand_mention_rate","display_name":"品牌提及率","description":"品牌在AI回答中被提及的比例","domain":"visibility","unit":"%"}]"""


async def _read_schema_for_domains(pool, domains: list[str]) -> str:
    """Read live table schemas for the requested domains."""
    tables = set()
    for d in domains:
        tables.update(_DOMAIN_TABLES.get(d, []))

    schema_parts = []
    for table_name in sorted(tables):
        rows = await pool.fetch(
            """SELECT column_name, data_type
               FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = $1
               ORDER BY ordinal_position""",
            table_name,
        )
        if rows:
            cols = ", ".join(f"{r['column_name']} ({r['data_type']})" for r in rows)
            schema_parts.append(f"Table: {table_name}\nColumns: {cols}")

    return "\n\n".join(schema_parts)


@router.get(
    "/metrics/list", response_model=dict[str, list[AnalysisMetricEntry]]
)
async def list_analysis_metrics(
    domains: str = "visibility,citation,sentiment",
) -> dict[str, list[AnalysisMetricEntry]]:
    """Return analysis metrics from geo_analysis_metrics table, grouped by domain.

    Same response shape as /metrics/discover so the PromptEditor can use either
    endpoint interchangeably. Used when the template has required_metrics set —
    the slugs are metric_name values from this table, NOT the LLM-generated
    variable_name from /metrics/discover.
    """
    pool = await get_pool()
    domain_list = [d.strip() for d in domains.split(",") if d.strip()]
    rows = await pool.fetch(
        """SELECT metric_name, display_name_zh, description, domain, unit
           FROM geo_analysis_metrics
           WHERE is_active = true
             AND domain = ANY($1::text[])
           ORDER BY domain, sort_order""",
        domain_list,
    )
    grouped: dict[str, list[AnalysisMetricEntry]] = {}
    for r in rows:
        d = r["domain"]
        if d not in grouped:
            grouped[d] = []
        grouped[d].append(AnalysisMetricEntry(
            variable_name=r["metric_name"],
            display_name=r["display_name_zh"] or r["metric_name"],
            description=r["description"] or "",
            unit=r["unit"] or "",
        ))
    return grouped


@router.get(
    "/metrics/discover", response_model=dict[str, list[AnalysisMetricEntry]]
)
async def discover_metrics(
    domains: str = "visibility,citation,sentiment",
) -> dict[str, list[AnalysisMetricEntry]]:
    """Agent-ized metric discovery: reads live schema, uses Gemini to generate metric catalog.

    Returns same grouped format as /metrics/list for frontend compatibility.
    Results are cached for 1 hour (schema rarely changes).
    """
    from google.genai import types

    try:
        return await _discover_metrics_impl(domains, types)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DISCOVER] Unhandled error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Metric discovery error: {e}")


async def _discover_metrics_impl(domains: str, types):
    """Inner implementation — wrapped by discover_metrics for error handling."""
    domain_list = sorted(d.strip() for d in domains.split(",") if d.strip())
    cache_key = ",".join(domain_list)

    if cache_key in _discover_cache:
        cached_ts, cached_result = _discover_cache[cache_key]
        if time.time() - cached_ts < _DISCOVER_CACHE_TTL:
            logger.info(f"[DISCOVER] Cache hit for domains={cache_key}")
            return cached_result

    pool = await get_pool()

    schema_text = await _read_schema_for_domains(pool, domain_list)
    if not schema_text:
        return {}

    model_id = await get_model_id("flash")
    client = await get_genai_client(model_id, role="flash")

    prompt = f"Domains to analyze: {', '.join(domain_list)}\n\nDatabase schema:\n{schema_text}"

    raw_text = ""
    last_err = None
    for attempt in range(2):
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=_DISCOVER_SYSTEM,
                        response_mime_type="application/json",
                        temperature=0.1,
                        max_output_tokens=8192,
                    ),
                ),
                timeout=60,
            )
            raw_text = response.text or ""
            logger.info(f"[DISCOVER] Gemini response: {len(raw_text)} chars (attempt {attempt + 1})")
            metrics = json.loads(raw_text)
            last_err = None
            break
        except asyncio.TimeoutError:
            last_err = "timeout"
            logger.warning(f"[DISCOVER] Timeout on attempt {attempt + 1}")
        except (json.JSONDecodeError, TypeError) as e:
            last_err = f"parse: {e}"
            logger.warning(f"[DISCOVER] Parse error on attempt {attempt + 1}: {e}, raw={raw_text[:300]}")
        except Exception as e:
            last_err = str(e)
            logger.warning(f"[DISCOVER] Gemini error on attempt {attempt + 1}: {e}")

    if last_err:
        logger.error(f"[DISCOVER] All attempts failed: {last_err}")
        raise HTTPException(status_code=504, detail=f"Metric discovery failed: {last_err}")

    grouped: dict[str, list[AnalysisMetricEntry]] = {}
    if not isinstance(metrics, list):
        logger.error(f"[DISCOVER] Unexpected response type: {type(metrics)}")
        raise HTTPException(status_code=502, detail="Unexpected metric discovery response format")
    for m in metrics:
        if not isinstance(m, dict) or "variable_name" not in m or "display_name" not in m:
            continue
        d = m.get("domain", "unknown")
        if d not in grouped:
            grouped[d] = []
        grouped[d].append(AnalysisMetricEntry(
            variable_name=m["variable_name"],
            display_name=m["display_name"],
            description=m.get("description", ""),
            unit=m.get("unit", ""),
        ))

    _discover_cache[cache_key] = (time.time(), grouped)
    logger.info(f"[DISCOVER] Generated {sum(len(v) for v in grouped.values())} metrics for domains={cache_key}")

    return grouped
