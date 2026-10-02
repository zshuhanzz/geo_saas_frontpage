"""High-level Overview aggregation for the SaaS dashboard."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel

from geo_common.llm import MODEL_REGION_OVERRIDES_KEY, resolve_model_region
from db import database

from ._helpers import date_bucket_expr, date_range_filter_expr, iter_date_strings, parse_date_range, parse_multi_value
router = APIRouter(tags=["insights-overview"])
logger = logging.getLogger(__name__)
PLATFORM_HEALTH_TIMEOUT_SECONDS = 12.0
FRESHNESS_TIMEOUT_SECONDS = 2.0
INSIGHT_LLM_TIMEOUT_SECONDS = 20.0
INSIGHT_LLM_MAX_ATTEMPTS = 2
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class OverviewSummary(BaseModel):
    visibility_score: float
    visibility_score_change: Optional[float] = None
    visibility_rank: Optional[int] = None
    visibility_rank_change: Optional[int] = None
    mentioned_responses: int
    total_responses: int
    sov_pct: Optional[float] = None
    own_mentions: int
    total_mentions: int
    avg_position: Optional[float] = None
    own_citation_share: float
    own_citation_share_change: Optional[float] = None
    own_citation_count: int
    total_citations: int
    own_citation_rank: Optional[int] = None
    positive_sentiment_pct: float
    positive_sentiment_pct_change: Optional[float] = None
    positive_count: int
    negative_count: int
    sentiment_total: int
    analyzer_completed_at: Optional[str] = None


class OverviewStatusOut(BaseModel):
    latest_analysis_time: Optional[str] = None
    next_analysis_time: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    cron_analyzer: Optional[str] = None


class OverviewKpisOut(BaseModel):
    summary: OverviewSummary


class OverviewTrendsOut(BaseModel):
    momentum: List["OverviewMomentumPoint"]
    filters: "OverviewFilters"


class OverviewMomentumPoint(BaseModel):
    date: str
    visibility_score: Optional[float] = None
    own_citation_share: Optional[float] = None
    positive_sentiment_pct: Optional[float] = None
    total_responses: Optional[int] = None
    total_citations: Optional[int] = None
    sentiment_total: Optional[int] = None


class OverviewPlatformHealthRow(BaseModel):
    platform: str
    visibility_score: float
    visibility_rank: Optional[int] = None
    own_citation_share: float
    own_citation_count: int
    positive_sentiment_pct: float
    negative_count: int
    sentiment_total: int


class OverviewTopicOpportunityRow(BaseModel):
    topic_id: str
    topic_name: Optional[str] = None
    visibility_pct: Optional[float] = None
    citation_coverage: Optional[float] = None
    sentiment_polarity: Optional[float] = None
    prompt_volume: int = 0
    mention_share_pct: Optional[float] = None
    opportunity_label: str = "monitor"
    own_rank: Optional[int] = None
    own_mentions: int = 0
    leading_brand: Optional[str] = None
    leading_mentions: int = 0
    prompt_count: int = 0


class OverviewCompetitorRow(BaseModel):
    rank: int
    brand_name: str
    visibility_pct: Optional[float] = None
    visibility_delta: Optional[float] = None
    sov_pct: Optional[float] = None
    citation_share: Optional[float] = None
    sentiment_pct: Optional[float] = None
    mention_count: int
    avg_position: Optional[float] = None
    rank_delta: Optional[int] = None
    is_own: bool = False


class OverviewInsightFact(BaseModel):
    kind: str
    severity: str
    metric: str
    value: Optional[float] = None
    delta: Optional[float] = None
    title: str = ""
    detail: str = ""


class OverviewInsightItem(OverviewInsightFact):
    pass


class OverviewInsightsOut(BaseModel):
    items: List[OverviewInsightItem]


class OverviewTopicOpportunitiesOut(BaseModel):
    items: List[OverviewTopicOpportunityRow]


class OverviewCompetitorsOut(BaseModel):
    items: List[OverviewCompetitorRow]


class OverviewPlatformHealthOut(BaseModel):
    items: List[OverviewPlatformHealthRow]


class OverviewFilters(BaseModel):
    date_from: str
    date_to: str
    prev_date_from: str
    prev_date_to: str
    interval: str
    topic_ids: List[str]
    platform: Optional[str] = None
    country: Optional[str] = None


class OverviewOut(BaseModel):
    summary: OverviewSummary
    momentum: List[OverviewMomentumPoint]
    platform_health: List[OverviewPlatformHealthRow]
    topic_opportunities: List[OverviewTopicOpportunityRow]
    competitor_snapshot: List[OverviewCompetitorRow]
    alerts: List[OverviewInsightItem]
    filters: OverviewFilters


def _isoformat_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        # Stored analyzer timestamps are UTC-like naive values in the current
        # DB. SaaS users read the dashboard in China time.
        if value.tzinfo is None:
            value = value + timedelta(hours=8)
        else:
            value = value.astimezone(SHANGHAI_TZ)
        return value.replace(tzinfo=None).isoformat()
    return str(value)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_cron_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, step_raw = part.split("/", 1)
            try:
                step = max(1, int(step_raw))
            except ValueError:
                step = 1
        if part == "*":
            start, end = minimum, maximum
        elif "-" in part:
            start_raw, end_raw = part.split("-", 1)
            try:
                start, end = int(start_raw), int(end_raw)
            except ValueError:
                continue
        else:
            try:
                value = int(part)
            except ValueError:
                continue
            start, end = value, value
        for value in range(max(minimum, start), min(maximum, end) + 1, step):
            values.add(value)
    return values


def _next_cron_run(cron_expr: Optional[str], *, now: Optional[datetime] = None) -> Optional[str]:
    if not cron_expr:
        return None
    parts = cron_expr.split()
    if len(parts) != 5:
        return None
    minute_set = _parse_cron_field(parts[0], 0, 59)
    hour_set = _parse_cron_field(parts[1], 0, 23)
    day_set = _parse_cron_field(parts[2], 1, 31)
    month_set = _parse_cron_field(parts[3], 1, 12)
    dow_set = _parse_cron_field(parts[4], 0, 7)
    if not minute_set or not hour_set or not day_set or not month_set or not dow_set:
        return None

    current = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    current = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366):
        cron_dow = (current.weekday() + 1) % 7
        if (
            current.minute in minute_set
            and current.hour in hour_set
            and current.day in day_set
            and current.month in month_set
            and (cron_dow in dow_set or (cron_dow == 0 and 7 in dow_set))
        ):
            return current.replace(tzinfo=None).isoformat()
        current += timedelta(minutes=1)
    return None


async def _list_platforms(client_id: UUID, selected_platform: Optional[str]) -> List[str]:
    selected = parse_multi_value(selected_platform)
    if selected:
        return selected
    rows = await database.fetch_all(
        """
        SELECT DISTINCT cp.platform
        FROM geo_client_prompts cp
        WHERE cp.client_id = :client_id
          AND cp.is_active = TRUE
          AND cp.platform IS NOT NULL
        ORDER BY cp.platform
        """,
        {"client_id": client_id},
    )
    return [str(row["platform"]) for row in rows if row["platform"]]


async def _get_analyzer_completed_at(client_id: UUID) -> Optional[str]:
    try:
        value = await asyncio.wait_for(
            database.fetch_val(
                """
                SELECT MAX(gr.analyzed_at)
                FROM geo_results gr
                WHERE gr.client_id = :client_id
                """,
                {"client_id": client_id},
            ),
            timeout=FRESHNESS_TIMEOUT_SECONDS,
        )
        return _isoformat_or_none(value)
    except asyncio.TimeoutError:
        return None


async def _resolve_flash_model_config() -> tuple[Optional[str], Optional[str]]:
    model_row, overrides_row = await asyncio.gather(
        database.fetch_one(
            "SELECT value FROM geo_global_settings WHERE key = 'agent_flash_model_id'"
        ),
        database.fetch_one(
            "SELECT value FROM geo_global_settings WHERE key = :key",
            {"key": MODEL_REGION_OVERRIDES_KEY},
        ),
    )
    model_id = (model_row["value"] or "").strip() if model_row and model_row["value"] else ""
    if not model_id:
        return None, None
    overrides = overrides_row["value"] if overrides_row and overrides_row["value"] else None
    region = resolve_model_region(
        model_id,
        overrides_value=overrides,
        default_region=os.getenv("GCP_REGION", "us-central1"),
        global_region=os.getenv("GCP_REGION_GLOBAL", "global"),
    )
    return model_id, region


def _resolve_gcp_project() -> Optional[str]:
    project_id = os.getenv("GCP_PROJECT_ID")
    if project_id:
        return project_id
    try:
        import google.auth

        _, project_id = google.auth.default()
        return project_id
    except Exception:
        return None


def _insight_polish_prompt(facts: List[OverviewInsightFact], language: str) -> str:
    payload = [
        {
            "kind": fact.kind,
            "severity": fact.severity,
            "metric": fact.metric,
            "value": fact.value,
            "delta": fact.delta,
            "fallback_title": fact.title,
            "fallback_detail": fact.detail,
        }
        for fact in facts
    ]
    if language.lower().startswith("zh"):
        copy_rules = (
            "用中文输出给商业 SaaS 高管看的洞察。不要照抄 fallback_title 或 fallback_detail。"
            "不要使用“当前为”“较上一周期变化”这类模板句。"
            "不要输出 visibility_score、own_citation_share、positive_sentiment_pct 等字段名。"
            "标题 8-14 个中文字符，描述保持 1 到 2 句话，必须点出业务含义和建议关注点。"
        )
    else:
        copy_rules = (
            "Write executive SaaS insight copy in English. Do not copy fallback_title or fallback_detail. "
            "Avoid template phrasing such as 'is currently' or 'changed vs previous period'. "
            "Do not output metric IDs such as visibility_score, own_citation_share, or positive_sentiment_pct. "
            "Use a concise title and one to two business-oriented sentences."
        )
    return (
        "You polish already-computed Overview dashboard facts. "
        "Use only the facts provided. Do not calculate, infer, or invent metrics. "
        "Return a JSON array in the same order and length. Each item must contain only title and detail. "
        f"{copy_rules} "
        f"Language: {language}.\n"
        f"Facts: {json.dumps(payload, ensure_ascii=False)}"
    )


def _extract_genai_text(response: Any) -> str:
    text = (getattr(response, "text", "") or "").strip()
    if text:
        return text
    try:
        candidates = getattr(response, "candidates", None) or []
        parts_text: List[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts_text.append(str(part_text))
        return "\n".join(parts_text).strip()
    except Exception:
        return ""


def _strip_json_code_fence(raw: str) -> str:
    value = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else value


def _parse_polished_insight_items(raw: str, facts: List[OverviewInsightFact]) -> List[OverviewInsightItem]:
    parsed = json.loads(_strip_json_code_fence(raw))
    if not isinstance(parsed, list):
        raise ValueError("Insight polish response is not a JSON array")
    items: List[OverviewInsightItem] = []
    for fact, polished in zip(facts, parsed):
        title = str((polished or {}).get("title") or fact.title).strip()
        detail = str((polished or {}).get("detail") or fact.detail).strip()
        items.append(
            OverviewInsightItem(
                **{
                    **fact.model_dump(),
                    "title": title[:120],
                    "detail": detail[:260],
                }
            )
        )
    return items


def _summarize_genai_response(response: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"response_type": type(response).__name__}
    try:
        candidates = getattr(response, "candidates", None) or []
        summary["candidate_count"] = len(candidates)
        summary["prompt_feedback"] = str(getattr(response, "prompt_feedback", None))[:500]
        summary["usage_metadata"] = str(getattr(response, "usage_metadata", None))[:500]
        candidate_summaries = []
        for candidate in candidates[:3]:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            candidate_summaries.append(
                {
                    "finish_reason": str(getattr(candidate, "finish_reason", None)),
                    "safety_ratings": str(getattr(candidate, "safety_ratings", None))[:500],
                    "part_count": len(parts),
                    "part_types": [type(part).__name__ for part in parts],
                    "part_text_lengths": [len(getattr(part, "text", "") or "") for part in parts],
                }
            )
        summary["candidates"] = candidate_summaries
    except Exception as exc:
        summary["inspect_error"] = str(exc)
    return summary


async def _polish_insight_facts_with_flash(
    facts: List[OverviewInsightFact],
    language: str,
) -> List[OverviewInsightItem]:
    if not facts:
        return []
    try:
        from google import genai
        from google.genai import types

        model_id, region = await _resolve_flash_model_config()
        project_id = _resolve_gcp_project()
        if not model_id or not region or not project_id:
            logger.warning(
                "overview_insight_flash_skipped model_id_set=%s region_set=%s project_id_set=%s",
                bool(model_id),
                bool(region),
                bool(project_id),
            )
            return [_localized_fallback_insight(fact, language) for fact in facts]

        client = genai.Client(
            vertexai=True,
            project=project_id,
            location=region,
            http_options=types.HttpOptions(timeout=INSIGHT_LLM_TIMEOUT_SECONDS * 1000),
        )
        response = None
        last_error: Optional[Exception] = None
        for attempt in range(INSIGHT_LLM_MAX_ATTEMPTS):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model_id,
                        contents=_insight_polish_prompt(facts, language),
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.2,
                            max_output_tokens=4096,
                        ),
                    ),
                    timeout=INSIGHT_LLM_TIMEOUT_SECONDS,
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "overview_insight_flash_attempt_failed attempt=%s/%s error=%s",
                    attempt + 1,
                    INSIGHT_LLM_MAX_ATTEMPTS,
                    exc,
                )
                if attempt + 1 < INSIGHT_LLM_MAX_ATTEMPTS:
                    await asyncio.sleep(0.6)
        if response is None:
            raise last_error or RuntimeError("Flash insight generation failed")
        raw = _extract_genai_text(response)
        logger.info(
            "overview_insight_flash_response model_id=%s region=%s raw_len=%s response=%s",
            model_id,
            region,
            len(raw),
            json.dumps(_summarize_genai_response(response), ensure_ascii=False),
        )
        if not raw:
            logger.warning(
                "overview_insight_flash_empty_response model_id=%s region=%s response=%s",
                model_id,
                region,
                json.dumps(_summarize_genai_response(response), ensure_ascii=False),
            )
            return [_localized_fallback_insight(fact, language) for fact in facts]
        items = _parse_polished_insight_items(raw, facts)
        return items or [_localized_fallback_insight(fact, language) for fact in facts]
    except Exception as exc:
        logger.warning("overview_insight_flash_failed error=%s", exc, exc_info=True)
        return [_localized_fallback_insight(fact, language) for fact in facts]


def _fallback_insight_title(metric: str) -> str:
    if metric == "visibility_score":
        return "Visibility moved"
    if metric == "own_citation_share":
        return "Citation share moved"
    return "Sentiment moved"


def _fallback_insight_detail(fact: OverviewInsightFact) -> str:
    value = "n/a" if fact.value is None else f"{fact.value:.2f}"
    delta = "n/a" if fact.delta is None else f"{fact.delta:+.2f}"
    return f"{fact.metric} is {value}, changed {delta} vs previous period."


def _localized_fallback_insight(fact: OverviewInsightFact, language: str) -> OverviewInsightItem:
    if language.lower().startswith("zh"):
        title_map = {
            "visibility_score": "可见度发生变化",
            "own_citation_share": "引用占比发生变化",
            "positive_sentiment_pct": "情感表现发生变化",
        }
        label_map = {
            "visibility_score": "可见度",
            "own_citation_share": "引用占比",
            "positive_sentiment_pct": "正向情感",
        }
        value = "暂无" if fact.value is None else f"{fact.value:.2f}"
        delta = "暂无" if fact.delta is None else f"{fact.delta:+.2f}"
        return OverviewInsightItem(
            **{
                **fact.model_dump(),
                "title": title_map.get(fact.metric, "关键指标发生变化"),
                "detail": f"{label_map.get(fact.metric, '关键指标')} 当前为 {value}，较上一周期变化 {delta} 个百分点。",
            }
        )
    return OverviewInsightItem(**fact.model_dump())


def _build_insight_facts(visibility: Any, citations: Any, sentiment: Any) -> List[OverviewInsightFact]:
    facts: List[OverviewInsightFact] = []
    vis_delta = visibility.summary.visibility_score_change
    if vis_delta is not None:
        facts.append(
            OverviewInsightFact(
                kind="visibility",
                severity="positive" if vis_delta > 0 else "negative",
                metric="visibility_score",
                value=visibility.summary.visibility_score,
                delta=vis_delta,
            )
    )
    citation_delta = citations.summary.own_domain_share_change
    if citation_delta is not None:
        facts.append(
            OverviewInsightFact(
                kind="citation",
                severity="positive" if citation_delta > 0 else "negative",
                metric="own_citation_share",
                value=citations.summary.own_domain_share,
                delta=citation_delta,
            )
    )
    sentiment_delta = sentiment.summary.positive_pct_change
    if sentiment_delta is not None:
        facts.append(
            OverviewInsightFact(
                kind="sentiment",
                severity="positive" if sentiment_delta > 0 else "negative",
                metric="positive_sentiment_pct",
                value=sentiment.summary.positive_pct,
                delta=sentiment_delta,
            )
        )
    facts = sorted(facts, key=lambda item: abs(item.delta or 0), reverse=True)[:5]
    for fact in facts:
        fact.title = _fallback_insight_title(fact.metric)
        fact.detail = _fallback_insight_detail(fact)
    return facts


def _build_alerts(visibility: Any, citations: Any, sentiment: Any) -> List[OverviewInsightItem]:
    return [OverviewInsightItem(**fact.model_dump()) for fact in _build_insight_facts(visibility, citations, sentiment)]


def _build_insight_facts_from_summary(summary: OverviewSummary) -> List[OverviewInsightFact]:
    facts: List[OverviewInsightFact] = []
    if summary.visibility_score_change is not None:
        facts.append(
            OverviewInsightFact(
                kind="visibility",
                severity="positive" if summary.visibility_score_change > 0 else "negative",
                metric="visibility_score",
                value=summary.visibility_score,
                delta=summary.visibility_score_change,
            )
        )
    if summary.own_citation_share_change is not None:
        facts.append(
            OverviewInsightFact(
                kind="citation",
                severity="positive" if summary.own_citation_share_change > 0 else "negative",
                metric="own_citation_share",
                value=summary.own_citation_share,
                delta=summary.own_citation_share_change,
            )
        )
    if summary.positive_sentiment_pct_change is not None:
        facts.append(
            OverviewInsightFact(
                kind="sentiment",
                severity="positive" if summary.positive_sentiment_pct_change > 0 else "negative",
                metric="positive_sentiment_pct",
                value=summary.positive_sentiment_pct,
                delta=summary.positive_sentiment_pct_change,
            )
        )
    facts = sorted(facts, key=lambda item: abs(item.delta or 0), reverse=True)[:5]
    for fact in facts:
        fact.title = _fallback_insight_title(fact.metric)
        fact.detail = _fallback_insight_detail(fact)
    return facts


async def _visibility_intent_filter(prefix: str = "ov_vis_intent") -> tuple[str, dict]:
    return await _metric_intent_filter("Visibility", prefix)


async def _metric_intent_filter(category: str, prefix: str) -> tuple[str, dict]:
    rows = await database.fetch_all(
        """
        SELECT intent_name FROM geo_global_intents
        WHERE is_active = TRUE
          AND categories @> :category_json::jsonb
        """,
        {"category_json": json.dumps([category])},
    )
    names = [row["intent_name"] for row in rows]
    if not names:
        return "1 = 0", {}
    placeholders = ",".join(f":{prefix}_{i}" for i in range(len(names)))
    return f"cp.intent IN ({placeholders})", {f"{prefix}_{i}": name for i, name in enumerate(names)}


def _append_overview_prompt_filters(
    where: list[str],
    params: dict[str, Any],
    *,
    prefix: str,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    cp_alias: str = "cp",
) -> None:
    topic_list = parse_multi_value(topic_ids)
    if topic_list:
        placeholders = ",".join(f":{prefix}_topic_{i}" for i in range(len(topic_list)))
        where.append(f"{cp_alias}.topic_id IN ({placeholders})")
        for i, value in enumerate(topic_list):
            params[f"{prefix}_topic_{i}"] = value

    platform_list = parse_multi_value(platform)
    if platform_list:
        placeholders = ",".join(f":{prefix}_platform_{i}" for i in range(len(platform_list)))
        where.append(f"{cp_alias}.platform IN ({placeholders})")
        for i, value in enumerate(platform_list):
            params[f"{prefix}_platform_{i}"] = value

    country_list = parse_multi_value(country)
    if country_list:
        placeholders = ",".join(f":{prefix}_country_{i}" for i in range(len(country_list)))
        where.append(f"{cp_alias}.country IN ({placeholders})")
        for i, value in enumerate(country_list):
            params[f"{prefix}_country_{i}"] = value


async def _overview_base_scope(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    category: str,
    prefix: str,
) -> tuple[str, dict[str, Any]]:
    where = [f"{prefix}.client_id = :client_id", "cp.is_active = TRUE"]
    params: dict[str, Any] = {"client_id": client_id}
    _append_overview_prompt_filters(
        where,
        params,
        prefix=f"{prefix}_ov",
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        cp_alias="cp",
    )
    intent_sql, intent_params = await _metric_intent_filter(category, f"{prefix}_intent")
    where.append(intent_sql)
    params.update(intent_params)
    return " AND ".join(where), params


def _series_lookup(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows}


async def _query_overview_visibility_period(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    start: date,
    end: date,
    interval: str,
    date_param_prefix: str,
    include_series: bool = True,
) -> dict[str, Any]:
    where_sql, params = await _overview_base_scope(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        category="Visibility",
        prefix="gr",
    )
    params = {**params, f"{date_param_prefix}_start": start, f"{date_param_prefix}_end": end}
    bucket_sql = date_bucket_expr("gr.ingested_at", interval, timezone=SHANGHAI_TZ.key)
    bucket_select = f"{bucket_sql} AS bucket," if include_series else ""
    bucket_group = f"GROUP BY {bucket_sql} ORDER BY {bucket_sql}" if include_series else ""
    rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_select}
            COUNT(DISTINCT gr.result_id) AS total_responses,
            COUNT(DISTINCT CASE WHEN bm.brand_role = 'own' THEN gr.result_id END) AS own_responses,
            COUNT(bm.result_id) AS total_mentions,
            SUM(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS own_mentions,
            AVG(CASE WHEN bm.brand_role = 'own' THEN bm.mention_position END) AS avg_position
        FROM geo_results gr
        JOIN geo_client_prompts cp
          ON cp.id = gr.client_prompt_id
         AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
        WHERE {where_sql}
          AND {date_range_filter_expr("gr.ingested_at", f"{date_param_prefix}_start", f"{date_param_prefix}_end")}
        {bucket_group}
        """,
        params,
    )
    series = []
    totals = {
        "total_responses": 0,
        "own_responses": 0,
        "total_mentions": 0,
        "own_mentions": 0,
        "avg_position_weighted": 0.0,
    }
    for row in rows:
        bucket = row["bucket"] if include_series else None
        total = int(row["total_responses"] or 0)
        own = int(row["own_responses"] or 0)
        own_mentions = int(row["own_mentions"] or 0)
        avg_position = _safe_float(row["avg_position"])
        totals["total_responses"] += total
        totals["own_responses"] += own
        totals["total_mentions"] += int(row["total_mentions"] or 0)
        totals["own_mentions"] += own_mentions
        if avg_position is not None and own_mentions:
            totals["avg_position_weighted"] += avg_position * own_mentions
        if include_series:
            series.append(
                {
                    "date": bucket.isoformat() if hasattr(bucket, "isoformat") else str(bucket),
                    "visibility_score": round(own / total * 100, 2) if total else 0,
                    "total_responses": total,
                    "own_responses": own,
                }
            )
    if include_series and interval == "daily":
        by_date = _series_lookup(series, "date")
        series = [
            by_date.get(day, {"date": day, "visibility_score": None, "total_responses": 0, "own_responses": 0})
            for day in iter_date_strings(start, end)
        ]
    avg_position = (
        round(totals["avg_position_weighted"] / totals["own_mentions"], 2)
        if totals["own_mentions"] else None
    )
    return {
        **totals,
        "visibility_score": round(totals["own_responses"] / totals["total_responses"] * 100, 2)
        if totals["total_responses"] else 0,
        "sov_pct": round(totals["own_mentions"] / totals["total_mentions"] * 100, 2)
        if totals["total_mentions"] else 0,
        "avg_position": avg_position,
        "series": series,
    }


async def _query_overview_visibility_rank(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    start: date,
    end: date,
    date_param_prefix: str,
) -> Optional[int]:
    where_sql, params = await _overview_base_scope(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        category="Visibility",
        prefix="gr",
    )
    params = {**params, f"{date_param_prefix}_start": start, f"{date_param_prefix}_end": end}
    row = await database.fetch_one(
        f"""
        WITH brand_stats AS (
            SELECT
                bm.brand_name,
                MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS is_own,
                COUNT(DISTINCT gr.result_id) AS response_count,
                COUNT(*) AS mention_count
            FROM geo_results gr
            JOIN geo_client_prompts cp
              ON cp.id = gr.client_prompt_id
             AND cp.client_id = gr.client_id
            JOIN geo_brand_mentions bm
              ON bm.result_id = gr.result_id
             AND bm.client_id = gr.client_id
            WHERE {where_sql}
              AND {date_range_filter_expr("gr.ingested_at", f"{date_param_prefix}_start", f"{date_param_prefix}_end")}
            GROUP BY bm.brand_name
        ),
        ranked AS (
            SELECT
                is_own,
                RANK() OVER (ORDER BY response_count DESC, mention_count DESC, brand_name ASC) AS rank
            FROM brand_stats
        )
        SELECT MIN(rank) AS own_rank
        FROM ranked
        WHERE is_own = 1
        """,
        params,
    )
    if not row or row["own_rank"] is None:
        return None
    return int(row["own_rank"])


async def _query_overview_citation_period(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    start: date,
    end: date,
    interval: str,
    date_param_prefix: str,
    include_series: bool = True,
) -> dict[str, Any]:
    where_sql, params = await _overview_base_scope(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        category="Citation",
        prefix="c",
    )
    params = {**params, f"{date_param_prefix}_start": start, f"{date_param_prefix}_end": end}
    domain_rows = await database.fetch_all(
        "SELECT domain FROM geo_client_domains WHERE client_id = :client_id",
        {"client_id": client_id},
    )
    own_domains = [str(row["domain"]).lower() for row in domain_rows if row["domain"]]
    if own_domains:
        placeholders = ",".join(f":cit_own_domain_{i}" for i in range(len(own_domains)))
        own_case = f"SUM(CASE WHEN LOWER(c.source_domain) IN ({placeholders}) THEN 1 ELSE 0 END)::int"
        for i, domain in enumerate(own_domains):
            params[f"cit_own_domain_{i}"] = domain
    else:
        own_case = "0::int"
    bucket_sql = date_bucket_expr("c.executed_at", interval, timezone=SHANGHAI_TZ.key)
    bucket_select = f"{bucket_sql} AS bucket," if include_series else ""
    bucket_group = f"GROUP BY {bucket_sql} ORDER BY {bucket_sql}" if include_series else ""
    rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_select}
            COUNT(*) AS total_citations,
            {own_case} AS own_citations
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE {where_sql}
          AND {date_range_filter_expr("c.executed_at", f"{date_param_prefix}_start", f"{date_param_prefix}_end")}
        {bucket_group}
        """,
        params,
    )
    total_citations = 0
    own_citations = 0
    series = []
    for row in rows:
        bucket = row["bucket"] if include_series else None
        total = int(row["total_citations"] or 0)
        own = int(row["own_citations"] or 0)
        total_citations += total
        own_citations += own
        if include_series:
            series.append(
                {
                    "date": bucket.isoformat() if hasattr(bucket, "isoformat") else str(bucket),
                    "own_citation_share": round(own / total * 100, 2) if total else 0,
                    "total_citations": total,
                    "own_citation_count": own,
                }
            )
    if include_series and interval == "daily":
        by_date = _series_lookup(series, "date")
        series = [
            by_date.get(day, {"date": day, "own_citation_share": None, "total_citations": 0, "own_citation_count": 0})
            for day in iter_date_strings(start, end)
        ]
    return {
        "total_citations": total_citations,
        "own_citation_count": own_citations,
        "own_citation_share": round(own_citations / total_citations * 100, 2) if total_citations else 0,
        "series": series,
    }


async def _query_overview_sentiment_period(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    start: date,
    end: date,
    interval: str,
    date_param_prefix: str,
    include_series: bool = True,
) -> dict[str, Any]:
    where = ["sr.client_id = :client_id", "cp.is_active = TRUE"]
    params: dict[str, Any] = {"client_id": str(client_id), f"{date_param_prefix}_start": start, f"{date_param_prefix}_end": end}
    _append_overview_prompt_filters(
        where,
        params,
        prefix="sent_ov",
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        cp_alias="cp",
    )
    intent_sql, intent_params = await _metric_intent_filter("Sentiment", "ov_sent_core_intent")
    where.append(intent_sql)
    params.update(intent_params)
    where_sql = " AND ".join(where)
    bucket_sql = date_bucket_expr("sr.executed_at", interval, timezone=SHANGHAI_TZ.key)
    bucket_select = f"{bucket_sql} AS bucket," if include_series else ""
    bucket_group = f"GROUP BY {bucket_sql} ORDER BY {bucket_sql}" if include_series else ""
    rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_select}
            COUNT(*) AS total,
            SUM(CASE WHEN sr.sentiment <> 'Insufficient Evidence' THEN 1 ELSE 0 END) AS rated,
            SUM(CASE WHEN sr.sentiment = 'Positive' THEN 1 ELSE 0 END) AS positive,
            SUM(CASE WHEN sr.sentiment = 'Negative' THEN 1 ELSE 0 END) AS negative
        FROM geo_sentiment_results sr
        JOIN geo_results gr
          ON gr.result_id = sr.result_id
         AND gr.client_id = sr.client_id
        JOIN geo_client_prompts cp
          ON cp.id = sr.client_prompt_id
         AND cp.client_id = sr.client_id
        WHERE {where_sql}
          AND {date_range_filter_expr("sr.executed_at", f"{date_param_prefix}_start", f"{date_param_prefix}_end")}
        {bucket_group}
        """,
        params,
    )
    total_count = 0
    positive_count = 0
    negative_count = 0
    series = []
    for row in rows:
        bucket = row["bucket"] if include_series else None
        total = int(row["rated"] or 0)
        positive = int(row["positive"] or 0)
        negative = int(row["negative"] or 0)
        total_count += total
        positive_count += positive
        negative_count += negative
        if include_series:
            series.append(
                {
                    "date": bucket.isoformat() if hasattr(bucket, "isoformat") else str(bucket),
                    "positive_sentiment_pct": round(positive / total * 100, 2) if total else 0,
                    "sentiment_total": total,
                }
            )
    if include_series and interval == "daily":
        by_date = _series_lookup(series, "date")
        series = [
            by_date.get(day, {"date": day, "positive_sentiment_pct": None, "sentiment_total": 0})
            for day in iter_date_strings(start, end)
        ]
    return {
        "sentiment_total": total_count,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "positive_sentiment_pct": round(positive_count / total_count * 100, 2) if total_count else 0,
        "series": series,
    }


async def _query_overview_core_light(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    interval: str,
    include_ranks: bool = False,
    include_momentum: bool = True,
) -> tuple[OverviewSummary, List[OverviewMomentumPoint], OverviewFilters]:
    start, end = parse_date_range(date_from, date_to)
    period_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    visibility, prev_visibility, citations, prev_citations, sentiment, prev_sentiment = await asyncio.gather(
        _query_overview_visibility_period(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            start=start,
            end=end,
            interval=interval,
            date_param_prefix="ov_vis",
            include_series=include_momentum,
        ),
        _query_overview_visibility_period(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            start=prev_start,
            end=prev_end,
            interval=interval,
            date_param_prefix="ov_prev_vis",
            include_series=False,
        ),
        _query_overview_citation_period(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            start=start,
            end=end,
            interval=interval,
            date_param_prefix="ov_cit",
            include_series=include_momentum,
        ),
        _query_overview_citation_period(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            start=prev_start,
            end=prev_end,
            interval=interval,
            date_param_prefix="ov_prev_cit",
            include_series=False,
        ),
        _query_overview_sentiment_period(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            start=start,
            end=end,
            interval=interval,
            date_param_prefix="ov_sent",
            include_series=include_momentum,
        ),
        _query_overview_sentiment_period(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            start=prev_start,
            end=prev_end,
            interval=interval,
            date_param_prefix="ov_prev_sent",
            include_series=False,
        ),
    )

    visibility_rank = None
    visibility_rank_change = None
    if include_ranks:
        current_rank, previous_rank = await asyncio.gather(
            _query_overview_visibility_rank(
                client_id=client_id,
                topic_ids=topic_ids,
                platform=platform,
                country=country,
                start=start,
                end=end,
                date_param_prefix="ov_rank",
            ),
            _query_overview_visibility_rank(
                client_id=client_id,
                topic_ids=topic_ids,
                platform=platform,
                country=country,
                start=prev_start,
                end=prev_end,
                date_param_prefix="ov_prev_rank",
            ),
        )
        visibility_rank = current_rank
        visibility_rank_change = (
            current_rank - previous_rank
            if current_rank is not None and previous_rank is not None
            else None
        )

    momentum: List[OverviewMomentumPoint] = []
    if include_momentum:
        by_date: dict[str, dict[str, Any]] = {}
        for point in visibility["series"]:
            by_date.setdefault(point["date"], {"date": point["date"]}).update(point)
        for point in citations["series"]:
            by_date.setdefault(point["date"], {"date": point["date"]}).update(point)
        for point in sentiment["series"]:
            by_date.setdefault(point["date"], {"date": point["date"]}).update(point)
        momentum = [OverviewMomentumPoint(**by_date[key]) for key in sorted(by_date.keys())]

    summary = OverviewSummary(
        visibility_score=visibility["visibility_score"],
        visibility_score_change=round(visibility["visibility_score"] - prev_visibility["visibility_score"], 2),
        visibility_rank=visibility_rank,
        visibility_rank_change=visibility_rank_change,
        mentioned_responses=int(visibility["own_responses"]),
        total_responses=int(visibility["total_responses"]),
        sov_pct=visibility["sov_pct"],
        own_mentions=int(visibility["own_mentions"]),
        total_mentions=int(visibility["total_mentions"]),
        avg_position=visibility["avg_position"],
        own_citation_share=citations["own_citation_share"],
        own_citation_share_change=round(citations["own_citation_share"] - prev_citations["own_citation_share"], 2),
        own_citation_count=int(citations["own_citation_count"]),
        total_citations=int(citations["total_citations"]),
        own_citation_rank=None,
        positive_sentiment_pct=sentiment["positive_sentiment_pct"],
        positive_sentiment_pct_change=round(sentiment["positive_sentiment_pct"] - prev_sentiment["positive_sentiment_pct"], 2),
        positive_count=int(sentiment["positive_count"]),
        negative_count=int(sentiment["negative_count"]),
        sentiment_total=int(sentiment["sentiment_total"]),
    )
    filters = OverviewFilters(
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        prev_date_from=prev_start.isoformat(),
        prev_date_to=prev_end.isoformat(),
        interval=interval,
        topic_ids=parse_multi_value(topic_ids),
        platform=platform,
        country=country,
    )
    return summary, momentum, filters


async def _query_overview_platform_health_light(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    interval: str,
) -> List[OverviewPlatformHealthRow]:
    start, end = parse_date_range(date_from, date_to)
    platforms = await _list_platforms(client_id, platform)

    vis_where = ["gr.client_id = :client_id"]
    vis_params: dict[str, Any] = {"client_id": client_id, "start": start, "end": end}
    _append_overview_prompt_filters(
        vis_where,
        vis_params,
        prefix="ph_vis",
        topic_ids=topic_ids,
        platform=platform,
        country=country,
    )
    vis_intent_sql, vis_intent_params = await _metric_intent_filter("Visibility", "ph_vis_intent")
    vis_where.append(vis_intent_sql)
    vis_params.update(vis_intent_params)

    citation_where = ["c.client_id = :client_id"]
    citation_params: dict[str, Any] = {"client_id": client_id, "start": start, "end": end}
    _append_overview_prompt_filters(
        citation_where,
        citation_params,
        prefix="ph_cit",
        topic_ids=topic_ids,
        platform=platform,
        country=country,
    )
    citation_intent_sql, citation_intent_params = await _metric_intent_filter("Citation", "ph_cit_intent")
    citation_where.append(citation_intent_sql)
    citation_params.update(citation_intent_params)

    sentiment_where = ["sr.client_id = :client_id", "cp.is_active = TRUE"]
    sentiment_params: dict[str, Any] = {"client_id": str(client_id), "start": start, "end": end}
    _append_overview_prompt_filters(
        sentiment_where,
        sentiment_params,
        prefix="ph_sent",
        topic_ids=topic_ids,
        platform=platform,
        country=country,
    )
    sentiment_intent_sql, sentiment_intent_params = await _metric_intent_filter("Sentiment", "ph_sent_intent")
    sentiment_where.append(sentiment_intent_sql)
    sentiment_params.update(sentiment_intent_params)

    domain_rows = await database.fetch_all(
        "SELECT domain FROM geo_client_domains WHERE client_id = :client_id",
        {"client_id": client_id},
    )
    own_domains = [str(row["domain"]).lower() for row in domain_rows if row["domain"]]
    if own_domains:
        placeholders = ",".join(f":ph_own_domain_{i}" for i in range(len(own_domains)))
        own_case = f"SUM(CASE WHEN LOWER(c.source_domain) IN ({placeholders}) THEN 1 ELSE 0 END)::int"
        for i, domain in enumerate(own_domains):
            citation_params[f"ph_own_domain_{i}"] = domain
    else:
        own_case = "0::int"

    vis_rows, citation_rows, sentiment_rows = await asyncio.gather(
        database.fetch_all(
            f"""
            SELECT
                cp.platform,
                COUNT(DISTINCT gr.result_id) AS total_responses,
                COUNT(DISTINCT CASE WHEN bm.brand_role = 'own' THEN gr.result_id END) AS own_responses
            FROM geo_results gr
            JOIN geo_client_prompts cp
              ON cp.id = gr.client_prompt_id
             AND cp.client_id = gr.client_id
            LEFT JOIN geo_brand_mentions bm
              ON bm.result_id = gr.result_id
             AND bm.client_id = gr.client_id
            WHERE {" AND ".join(vis_where)}
              AND cp.platform IS NOT NULL
              AND {date_range_filter_expr("gr.ingested_at", "start", "end")}
            GROUP BY cp.platform
            """,
            vis_params,
        ),
        database.fetch_all(
            f"""
            SELECT
                cp.platform,
                COUNT(*) AS total_citations,
                {own_case} AS own_citations
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            WHERE {" AND ".join(citation_where)}
              AND cp.platform IS NOT NULL
              AND {date_range_filter_expr("c.executed_at", "start", "end")}
            GROUP BY cp.platform
            """,
            citation_params,
        ),
        database.fetch_all(
            f"""
            SELECT
                cp.platform,
                COUNT(*) AS total,
                SUM(CASE WHEN sr.sentiment <> 'Insufficient Evidence' THEN 1 ELSE 0 END) AS rated,
                SUM(CASE WHEN sr.sentiment = 'Positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN sr.sentiment = 'Negative' THEN 1 ELSE 0 END) AS negative
            FROM geo_sentiment_results sr
            JOIN geo_results gr
              ON gr.result_id = sr.result_id
             AND gr.client_id = sr.client_id
            JOIN geo_client_prompts cp
              ON cp.id = sr.client_prompt_id
             AND cp.client_id = sr.client_id
            WHERE {" AND ".join(sentiment_where)}
              AND cp.platform IS NOT NULL
              AND {date_range_filter_expr("sr.executed_at", "start", "end")}
            GROUP BY cp.platform
            """,
            sentiment_params,
        ),
    )

    visibility_by_platform = {str(row["platform"]): row for row in vis_rows if row["platform"]}
    citation_by_platform = {str(row["platform"]): row for row in citation_rows if row["platform"]}
    sentiment_by_platform = {str(row["platform"]): row for row in sentiment_rows if row["platform"]}
    output: List[OverviewPlatformHealthRow] = []
    for platform_name in platforms:
        vis = visibility_by_platform.get(platform_name)
        cit = citation_by_platform.get(platform_name)
        sent = sentiment_by_platform.get(platform_name)
        total_responses = int(vis["total_responses"] or 0) if vis else 0
        own_responses = int(vis["own_responses"] or 0) if vis else 0
        total_citations = int(cit["total_citations"] or 0) if cit else 0
        own_citations = int(cit["own_citations"] or 0) if cit else 0
        sentiment_total = int(sent["rated"] or 0) if sent else 0
        positive_count = int(sent["positive"] or 0) if sent else 0
        output.append(
            OverviewPlatformHealthRow(
                platform=platform_name,
                visibility_score=round(own_responses / total_responses * 100, 2) if total_responses else 0,
                visibility_rank=None,
                own_citation_share=round(own_citations / total_citations * 100, 2) if total_citations else 0,
                own_citation_count=own_citations,
                positive_sentiment_pct=round(positive_count / sentiment_total * 100, 2) if sentiment_total else 0,
                negative_count=int(sent["negative"] or 0) if sent else 0,
                sentiment_total=sentiment_total,
            )
        )
    return output


async def _query_topic_opportunities_light(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> List[OverviewTopicOpportunityRow]:
    start, end = parse_date_range(date_from, date_to)
    where = ["gr.client_id = :client_id", date_range_filter_expr("gr.ingested_at", "start_date", "end_date")]
    params: dict[str, Any] = {"client_id": client_id, "start_date": start, "end_date": end}

    topic_list = parse_multi_value(topic_ids)
    if topic_list:
        placeholders = ",".join(f":topic_{i}" for i in range(len(topic_list)))
        where.append(f"cp.topic_id IN ({placeholders})")
        for i, value in enumerate(topic_list):
            params[f"topic_{i}"] = value
    platform_list = parse_multi_value(platform)
    if platform_list:
        placeholders = ",".join(f":platform_{i}" for i in range(len(platform_list)))
        where.append(f"cp.platform IN ({placeholders})")
        for i, value in enumerate(platform_list):
            params[f"platform_{i}"] = value
    country_list = parse_multi_value(country)
    if country_list:
        placeholders = ",".join(f":country_{i}" for i in range(len(country_list)))
        where.append(f"cp.country IN ({placeholders})")
        for i, value in enumerate(country_list):
            params[f"country_{i}"] = value
    intent_sql, intent_params = await _visibility_intent_filter()
    where.append(intent_sql)
    params.update(intent_params)
    where_sql = " AND ".join(where)
    domain_rows = await database.fetch_all(
        "SELECT domain FROM geo_client_domains WHERE client_id = :client_id",
        {"client_id": client_id},
    )
    own_domains = [str(row["domain"]).lower() for row in domain_rows if row["domain"]]
    if own_domains:
        own_domain_placeholders = ",".join(f":own_domain_{i}" for i in range(len(own_domains)))
        own_domain_expr = f"LOWER(c.source_domain) IN ({own_domain_placeholders})"
        for i, domain in enumerate(own_domains):
            params[f"own_domain_{i}"] = domain
    else:
        own_domain_expr = "FALSE"

    rows = await database.fetch_all(
        f"""
        WITH scoped AS (
            SELECT gr.result_id, cp.topic_id, ct.topic_name, cp.text AS prompt_text
            FROM geo_results gr
            JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
            JOIN geo_client_topics ct ON ct.id = cp.topic_id
            WHERE {where_sql}
        ),
        topic_totals AS (
            SELECT topic_id, topic_name, COUNT(DISTINCT result_id) AS total_responses,
                   COUNT(DISTINCT prompt_text) AS prompt_volume
            FROM scoped
            GROUP BY topic_id, topic_name
        ),
        brand_stats AS (
            SELECT s.topic_id, bm.brand_name, MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS is_own,
                   COUNT(DISTINCT s.result_id) AS response_count,
                   COUNT(*) AS mention_count
            FROM scoped s
            JOIN geo_brand_mentions bm ON bm.result_id = s.result_id AND bm.client_id = :client_id
            GROUP BY s.topic_id, bm.brand_name
        ),
        topic_mentions AS (
            SELECT topic_id, SUM(mention_count) AS total_mentions
            FROM brand_stats
            GROUP BY topic_id
        ),
        ranked AS (
            SELECT bs.*, tt.topic_name, tt.total_responses, tt.prompt_volume, tm.total_mentions,
                   RANK() OVER (PARTITION BY bs.topic_id ORDER BY bs.response_count DESC, bs.mention_count DESC, bs.brand_name ASC) AS rank
            FROM brand_stats bs
            JOIN topic_totals tt ON tt.topic_id = bs.topic_id
            JOIN topic_mentions tm ON tm.topic_id = bs.topic_id
        ),
        citation_totals AS (
            SELECT s.topic_id,
                   COUNT(c.source_domain) AS total_citations,
                   SUM(CASE WHEN {own_domain_expr} THEN 1 ELSE 0 END) AS own_citations
            FROM scoped s
            LEFT JOIN geo_citations c ON c.result_id = s.result_id AND c.client_id = :client_id
            GROUP BY s.topic_id
        )
        SELECT topic_id::text, topic_name, total_responses, prompt_volume,
               MAX(CASE WHEN rank = 1 THEN brand_name END) AS leading_brand,
               MAX(CASE WHEN rank = 1 THEN mention_count END) AS leading_mentions,
               MAX(CASE WHEN is_own = 1 THEN rank END) AS own_rank,
               MAX(CASE WHEN is_own = 1 THEN mention_count END) AS own_mentions,
               MAX(CASE WHEN is_own = 1 THEN response_count END) AS own_response_count,
               MAX(total_mentions) AS total_mentions,
               COALESCE(MAX(ct.total_citations), 0) AS total_citations,
               COALESCE(MAX(ct.own_citations), 0) AS own_citations
        FROM ranked
        LEFT JOIN citation_totals ct USING (topic_id)
        GROUP BY topic_id, topic_name, total_responses, prompt_volume
        ORDER BY COALESCE(MAX(CASE WHEN is_own = 1 THEN response_count END), 0) DESC, total_responses DESC
        LIMIT 8
        """,
        params,
    )
    items: List[OverviewTopicOpportunityRow] = []
    for row in rows:
        total = int(row["total_responses"] or 0)
        own_responses = int(row["own_response_count"] or 0)
        own_mentions = int(row["own_mentions"] or 0)
        own_rank = int(row["own_rank"]) if row["own_rank"] is not None else None
        leading_mentions = int(row["leading_mentions"] or 0)
        total_mentions = int(row["total_mentions"] or 0)
        total_citations = int(row["total_citations"] or 0)
        own_citations = int(row["own_citations"] or 0)
        label = "monitor"
        if own_rank is None or own_mentions == 0:
            label = "content_gap"
        elif own_rank <= 3:
            label = "defend"
        elif leading_mentions > own_mentions * 2:
            label = "improve"
        items.append(
            OverviewTopicOpportunityRow(
                topic_id=row["topic_id"],
                topic_name=row["topic_name"],
                visibility_pct=round(own_responses / total * 100, 2) if total else 0,
                citation_coverage=round(own_citations / total_citations * 100, 2) if total_citations else 0,
                sentiment_polarity=None,
                prompt_volume=int(row["prompt_volume"] or 0),
                mention_share_pct=round(own_mentions / total_mentions * 100, 2) if total_mentions else 0,
                opportunity_label=label,
                own_rank=own_rank,
                own_mentions=own_mentions,
                leading_brand=row["leading_brand"],
                leading_mentions=leading_mentions,
                prompt_count=int(row["prompt_volume"] or 0),
            )
        )
    return items


async def _query_overview_competitors_light(
    *,
    client_id: UUID,
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> List[OverviewCompetitorRow]:
    start, end = parse_date_range(date_from, date_to)
    where = ["gr.client_id = :client_id", date_range_filter_expr("gr.ingested_at", "start_date", "end_date")]
    params: dict[str, Any] = {"client_id": client_id, "start_date": start, "end_date": end}
    _append_overview_prompt_filters(
        where,
        params,
        prefix="ov_comp",
        topic_ids=topic_ids,
        platform=platform,
        country=country,
    )
    intent_sql, intent_params = await _visibility_intent_filter()
    where.append(intent_sql)
    params.update(intent_params)
    where_sql = " AND ".join(where)

    rows = await database.fetch_all(
        f"""
        WITH scoped AS (
            SELECT gr.result_id
            FROM geo_results gr
            JOIN geo_client_prompts cp
              ON cp.id = gr.client_prompt_id
             AND cp.client_id = gr.client_id
            WHERE {where_sql}
        ),
        totals AS (
            SELECT COUNT(DISTINCT result_id) AS total_responses
            FROM scoped
        ),
        brand_stats AS (
            SELECT
                bm.brand_name,
                MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS is_own,
                COUNT(DISTINCT s.result_id) AS response_count,
                COUNT(*) AS mention_count,
                AVG(bm.mention_position) AS avg_position
            FROM scoped s
            JOIN geo_brand_mentions bm
              ON bm.result_id = s.result_id
             AND bm.client_id = :client_id
            WHERE bm.brand_name IS NOT NULL
              AND bm.brand_name <> ''
            GROUP BY bm.brand_name
        ),
        mention_totals AS (
            SELECT COALESCE(SUM(mention_count), 0) AS total_mentions
            FROM brand_stats
        ),
        ranked AS (
            SELECT
                bs.*,
                t.total_responses,
                mt.total_mentions,
                RANK() OVER (
                    ORDER BY bs.response_count DESC, bs.mention_count DESC, bs.brand_name ASC
                ) AS rank
            FROM brand_stats bs
            CROSS JOIN totals t
            CROSS JOIN mention_totals mt
        )
        SELECT *
        FROM ranked
        ORDER BY rank
        LIMIT 10
        """,
        params,
    )
    items: List[OverviewCompetitorRow] = []
    for row in rows:
        total_responses = int(row["total_responses"] or 0)
        total_mentions = int(row["total_mentions"] or 0)
        response_count = int(row["response_count"] or 0)
        mention_count = int(row["mention_count"] or 0)
        items.append(
            OverviewCompetitorRow(
                rank=int(row["rank"]),
                brand_name=row["brand_name"],
                visibility_pct=round(response_count / total_responses * 100, 2) if total_responses else 0,
                sov_pct=round(mention_count / total_mentions * 100, 2) if total_mentions else 0,
                citation_share=None,
                sentiment_pct=None,
                mention_count=mention_count,
                avg_position=round(float(row["avg_position"]), 2) if row["avg_position"] is not None else None,
                is_own=bool(row["is_own"]),
            )
        )
    return items


@router.get("/overview/status", response_model=OverviewStatusOut)
async def get_overview_status(
    client_id: UUID = Query(...),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> OverviewStatusOut:
    row = await database.fetch_one(
        """
        SELECT
            MAX(gr.analyzed_at) AS latest_analysis_time,
            gc.cron_analyzer AS cron_analyzer
        FROM geo_clients gc
        LEFT JOIN geo_results gr
          ON gr.client_id = gc.id
        WHERE gc.id = :client_id
        GROUP BY gc.cron_analyzer
        """,
        {"client_id": client_id},
    )
    latest = _isoformat_or_none(row["latest_analysis_time"]) if row else None
    cron_expr = row["cron_analyzer"] if row else None
    return OverviewStatusOut(
        latest_analysis_time=latest,
        next_analysis_time=_next_cron_run(cron_expr),
        date_from=date_from,
        date_to=date_to,
        cron_analyzer=cron_expr,
    )


@router.get("/overview/kpis", response_model=OverviewKpisOut)
async def get_overview_kpis(
    client_id: UUID = Query(...),
    topic_ids: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    interval: str = Query("daily"),
) -> OverviewKpisOut:
    summary, _momentum, _filters = await _query_overview_core_light(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
        include_ranks=True,
        include_momentum=False,
    )
    return OverviewKpisOut(summary=summary)


@router.get("/overview/trends", response_model=OverviewTrendsOut)
async def get_overview_trends(
    client_id: UUID = Query(...),
    topic_ids: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    interval: str = Query("daily"),
) -> OverviewTrendsOut:
    _summary, momentum, filters = await _query_overview_core_light(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
    )
    return OverviewTrendsOut(momentum=momentum, filters=filters)


@router.get("/overview/insights", response_model=OverviewInsightsOut)
async def get_overview_insights(
    client_id: UUID = Query(...),
    topic_ids: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    interval: str = Query("daily"),
    language: str = Query("zh-CN"),
) -> OverviewInsightsOut:
    summary, _momentum, _filters = await _query_overview_core_light(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
        include_momentum=False,
    )
    facts = _build_insight_facts_from_summary(summary)
    items = await _polish_insight_facts_with_flash(facts, language)
    return OverviewInsightsOut(items=items)


@router.get("/overview/topic-opportunities", response_model=OverviewTopicOpportunitiesOut)
async def get_overview_topic_opportunities(
    client_id: UUID = Query(...),
    topic_ids: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    interval: str = Query("daily"),
) -> OverviewTopicOpportunitiesOut:
    items = await _query_topic_opportunities_light(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
    )
    return OverviewTopicOpportunitiesOut(items=items)


@router.get("/overview/competitors", response_model=OverviewCompetitorsOut)
async def get_overview_competitors(
    client_id: UUID = Query(...),
    topic_ids: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    interval: str = Query("daily"),
) -> OverviewCompetitorsOut:
    items = await _query_overview_competitors_light(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
    )
    return OverviewCompetitorsOut(items=items)


@router.get("/overview/platform-health", response_model=OverviewPlatformHealthOut)
async def get_overview_platform_health(
    client_id: UUID = Query(...),
    topic_ids: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    interval: str = Query("daily"),
) -> OverviewPlatformHealthOut:
    rows = await _query_overview_platform_health_light(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
    )
    return OverviewPlatformHealthOut(items=list(rows))


@router.get("/overview", response_model=OverviewOut)
async def get_overview(
    client_id: UUID = Query(...),
    topic_ids: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    interval: str = Query("daily"),
) -> OverviewOut:
    summary, momentum, filters = await _query_overview_core_light(
        client_id=client_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
        include_ranks=True,
    )
    summary.analyzer_completed_at = await _get_analyzer_completed_at(client_id)
    platform_health, topic_opportunities, competitors = await asyncio.gather(
        _query_overview_platform_health_light(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            date_from=date_from,
            date_to=date_to,
            interval=interval,
        ),
        _query_topic_opportunities_light(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            date_from=date_from,
            date_to=date_to,
        ),
        get_overview_competitors(
            client_id=client_id,
            topic_ids=topic_ids,
            platform=platform,
            country=country,
            date_from=date_from,
            date_to=date_to,
            interval=interval,
        ),
    )

    return OverviewOut(
        summary=summary,
        momentum=momentum,
        platform_health=platform_health,
        topic_opportunities=topic_opportunities,
        competitor_snapshot=competitors.items,
        alerts=[OverviewInsightItem(**fact.model_dump()) for fact in _build_insight_facts_from_summary(summary)],
        filters=filters,
    )
