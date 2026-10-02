"""
Sentiment Router — SaaS API

GET /api/sentiment          — Main dashboard: KPIs, time series, theme list
GET /api/sentiment/result/{result_id} — Drawer detail: full response + citations
"""
import json
from datetime import date, datetime, timedelta
from typing import Annotated, Any, List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from db import database
from routers.insights._helpers import SHANGHAI_TZ, date_bucket_expr, date_range_filter_expr, iter_date_strings, parse_multi_value
from routers.insights.target_filters import build_target_filter
from routers.insights.sorting import resolve_sort_or_422, sort_complete_rows

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])


# ─── Output models ─────────────────────────────────────────────────────────


class SentimentSummary(BaseModel):
    positive_pct: float
    mixed_neutral_pct: float
    negative_pct: float
    positive_pct_change: float
    positive_count: int
    mixed_neutral_count: int
    negative_count: int
    insufficient_evidence_count: int
    rated_count: int
    total_count: int
    positive_top3_themes: List[str]
    negative_top3_themes: List[str]


class TimeSeriesPoint(BaseModel):
    date: str
    total: int
    rated: int
    positive: int
    mixed_neutral: int
    negative: int
    insufficient_evidence: int
    positive_pct: Optional[float] = None
    mixed_neutral_pct: Optional[float] = None
    negative_pct: Optional[float] = None


class ThemeRow(BaseModel):
    theme_name: str
    sentiment: Optional[str] = None
    occurrence_count: int
    prev_occurrence_count: int
    occurrence_change: int


class SentimentFilters(BaseModel):
    date_from: str
    date_to: str
    prev_date_from: str
    prev_date_to: str
    interval: str


class SentimentOut(BaseModel):
    summary: SentimentSummary
    time_series: List[TimeSeriesPoint]
    prev_time_series: List[TimeSeriesPoint]
    themes: List[ThemeRow]
    filters: SentimentFilters


class SentimentThemesOut(BaseModel):
    themes: List[ThemeRow]


class ThemeResultRow(BaseModel):
    id: Any
    result_id: int
    excerpt: Optional[str] = None
    sentiment: Optional[str] = None
    prompt_text: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    executed_at: Optional[str] = None


class ThemeResultsOut(BaseModel):
    total: int
    page: int
    pages: int
    results: List[ThemeResultRow]


class CitationRow(BaseModel):
    source_url: Optional[str] = None
    source_domain: Optional[str] = None
    source_label: Optional[str] = None
    domain_category: Optional[str] = None
    source_position: Optional[int] = None


class ResultDetailOut(BaseModel):
    result_id: int
    client_prompt: Optional[str] = None
    final_prompt: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    executed_at: Optional[str] = None
    response_text: Optional[str] = None
    search_queries: List[Any] = Field(default_factory=list)
    search_queries_status: Literal[
        "available",
        "upstream_not_provided",
        "not_requested",
        "not_applicable",
    ]
    topic_name: Optional[str] = None
    product: Optional[str] = None
    intent: Optional[str] = None
    citations: List[CitationRow] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(s: Optional[str], default: date) -> date:
    try:
        return date.fromisoformat(s) if s else default
    except ValueError:
        return default


def _explicit_search_queries_request(cloro_response: Any) -> Optional[bool]:
    if not isinstance(cloro_response, dict):
        return None

    paths = (
        ("include", "searchQueries"),
        ("request", "include", "searchQueries"),
        ("input", "include", "searchQueries"),
        ("task", "request", "include", "searchQueries"),
        ("task", "input", "include", "searchQueries"),
    )
    for path in paths:
        value: Any = cloro_response
        for key in path:
            if not isinstance(value, dict) or key not in value:
                break
            value = value[key]
        else:
            if isinstance(value, bool):
                return value
    return None


def _resolve_search_queries_state(
    *,
    platform: Optional[str],
    search_queries: Any,
    cloro_response: Any = None,
    search_queries_requested: Optional[bool] = None,
) -> tuple[List[Any], str]:
    """Normalize search queries and expose why ChatGPT queries are unavailable."""
    if (platform or "").strip().lower() != "chatgpt":
        return [], "not_applicable"

    # asyncpg intentionally returns PostgreSQL json/jsonb values as JSON text
    # unless a custom codec is registered.  Accept both that production shape
    # and already-decoded lists used by tests/callers.  Malformed JSON and
    # unexpected scalar/object values safely degrade to an unavailable state.
    decoded_queries = search_queries
    if isinstance(search_queries, str):
        try:
            decoded_queries = json.loads(search_queries)
        except (json.JSONDecodeError, TypeError):
            decoded_queries = []

    normalized = [
        item
        for item in decoded_queries
        if isinstance(item, (str, dict))
    ] if isinstance(decoded_queries, list) else []
    if normalized:
        return normalized, "available"
    explicitly_requested = (
        search_queries_requested
        if isinstance(search_queries_requested, bool)
        else _explicit_search_queries_request(cloro_response)
    )
    if explicitly_requested is False:
        return [], "not_requested"
    return [], "upstream_not_provided"


def _prev_period(start: date, end: date):
    """Return the previous period of the same duration."""
    delta = end - start
    return start - delta - timedelta(days=1), start - timedelta(days=1)


def _shanghai_today() -> date:
    return datetime.now(ZoneInfo(SHANGHAI_TZ)).date()


async def _intent_category_filter(category: str, param_prefix: str) -> tuple[str, dict]:
    """Return a dynamic cp.intent SQL filter for a configured metric category."""
    rows = await database.fetch_all(
        """
        SELECT intent_name FROM geo_global_intents
        WHERE is_active = TRUE
          AND categories @> :category_json::jsonb
        """,
        {"category_json": f'["{category}"]'},
    )
    intent_names = [r["intent_name"] for r in rows]
    if not intent_names:
        return "1 = 0", {}

    placeholders = ",".join(f":{param_prefix}_{i}" for i in range(len(intent_names)))
    params = {f"{param_prefix}_{i}": name for i, name in enumerate(intent_names)}
    return f"cp.intent IN ({placeholders})", params


def _serialize(row) -> dict:
    """Convert an asyncpg.Record (or dict) to a JSON-friendly dict."""
    d = {}
    for k, v in dict(row).items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        else:
            d[k] = v
    return d


async def _query_theme_rows(
    *,
    client_id: str,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
    topic_ids: Optional[str],
    products: Optional[str],
    prompt_id: Optional[str],
    prompt_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    sentiment_filter: Optional[str],
    intent_sql: str,
    intent_params: dict,
    sort_by: str,
    sort_order: str,
) -> tuple[list[dict], list[str], list[str]]:
    """Query the canonical theme list used by both dashboard and list-only refreshes."""
    target = build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        prompt_column="st.client_prompt_id",
        prefix="theme_target",
    )
    topic_list = parse_multi_value(topic_ids)
    platform_list = parse_multi_value(platform)
    country_list = parse_multi_value(country)
    clauses = [intent_sql]
    params: dict = {"client_id": client_id, **intent_params}
    if topic_list:
        placeholders = ",".join(f":ttid_{i}" for i in range(len(topic_list)))
        clauses.append(f"cp.topic_id IN ({placeholders})")
        params.update({f"ttid_{i}": value for i, value in enumerate(topic_list)})
    if target.clause:
        clauses.append(target.clause)
        params.update(target.params)
    if platform_list:
        placeholders = ",".join(f":tplat_{i}" for i in range(len(platform_list)))
        clauses.append(f"gr.platform IN ({placeholders})")
        params.update({f"tplat_{i}": value for i, value in enumerate(platform_list)})
    if country_list:
        placeholders = ",".join(f":tcountry_{i}" for i in range(len(country_list)))
        clauses.append(f"cp.country IN ({placeholders})")
        params.update({f"tcountry_{i}": value for i, value in enumerate(country_list)})
    if sentiment_filter in ("Positive", "Mixed/Neutral", "Negative"):
        clauses.append("st.sentiment = :sent_filter")
        params["sent_filter"] = sentiment_filter

    extra_sql = " AND " + " AND ".join(clauses)
    theme_join = """
        FROM geo_sentiment_themes st
        JOIN geo_results gr
          ON gr.result_id = st.result_id
         AND gr.client_id = st.client_id
        JOIN geo_client_prompts cp ON cp.id = st.client_prompt_id
         AND cp.client_id = st.client_id
        WHERE st.client_id = :client_id
          AND cp.is_active = TRUE
    """
    current_sql = f"""
        SELECT st.theme_name, st.sentiment, COUNT(*) AS occurrence_count
        {theme_join}
          AND {date_range_filter_expr("st.executed_at", "start", "end")}
        {extra_sql}
        GROUP BY st.theme_name, st.sentiment
        ORDER BY occurrence_count DESC, LOWER(st.theme_name), st.theme_name
    """
    previous_sql = f"""
        SELECT st.theme_name, st.sentiment, COUNT(*) AS prev_count
        {theme_join}
          AND {date_range_filter_expr("st.executed_at", "start", "end")}
        {extra_sql}
        GROUP BY st.theme_name, st.sentiment
    """
    current_rows = await database.fetch_all(current_sql, {**params, "start": start, "end": end})
    previous_rows = await database.fetch_all(
        previous_sql,
        {**params, "start": prev_start, "end": prev_end},
    )
    previous_counts = {
        (row["theme_name"], row["sentiment"]): row["prev_count"]
        for row in previous_rows
    }
    themes = [
        {
            "theme_name": row["theme_name"],
            "sentiment": row["sentiment"],
            "occurrence_count": row["occurrence_count"],
            "prev_occurrence_count": previous_counts.get((row["theme_name"], row["sentiment"]), 0),
            "occurrence_change": row["occurrence_count"] - previous_counts.get((row["theme_name"], row["sentiment"]), 0),
        }
        for row in current_rows
    ]
    positive_top3 = [row["theme_name"] for row in themes if row["sentiment"] == "Positive"][:3]
    negative_top3 = [row["theme_name"] for row in themes if row["sentiment"] == "Negative"][:3]
    return (
        sort_complete_rows("sentiment_themes", themes, sort_by, sort_order),
        positive_top3,
        negative_top3,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main Sentiment Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=SentimentOut)
async def get_sentiment(
    client_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    topic_ids: Optional[str] = None,       # comma-separated UUIDs
    products: Optional[str] = None,        # comma-separated product names
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    platform: Optional[str] = None,        # comma-separated platforms
    country: Optional[str] = None,         # comma-separated countries
    sentiment_filter: Optional[str] = None, # rated theme labels only
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> SentimentOut:
    resolved_sort = resolve_sort_or_422("sentiment_themes", sort_by, sort_order)
    result_target = build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        prompt_column="sr.client_prompt_id",
        prefix="sent_target",
    )
    today = _shanghai_today()
    end = _parse_date(date_to, today)
    start = _parse_date(date_from, end - timedelta(days=6))
    prev_start, prev_end = _prev_period(start, end)

    # Build filter fragments
    topic_list = [t.strip() for t in topic_ids.split(",") if t.strip()] if topic_ids else []
    platform_list = parse_multi_value(platform)
    country_list = parse_multi_value(country)

    # Common JOIN: sentiment_results → geo_results → geo_client_prompts
    join_snippet = """
        FROM geo_sentiment_results sr
        JOIN geo_results gr
          ON gr.result_id = sr.result_id
         AND gr.client_id = sr.client_id
        JOIN geo_client_prompts cp ON cp.id = sr.client_prompt_id
         AND cp.client_id = sr.client_id
        WHERE sr.client_id = :client_id
          AND cp.is_active = TRUE
    """

    def _extra_filters(alias_prefix=""):
        clauses, params = [], {}
        if topic_list:
            placeholders = ",".join(f":tid_{i}" for i in range(len(topic_list)))
            clauses.append(f"cp.topic_id IN ({placeholders})")
            for i, t in enumerate(topic_list):
                params[f"tid_{i}"] = t
        if result_target.clause:
            clauses.append(result_target.clause)
            params.update(result_target.params)
        if platform_list:
            placeholders = ",".join(f":plat_{i}" for i in range(len(platform_list)))
            clauses.append(f"gr.platform IN ({placeholders})")
            for i, p in enumerate(platform_list):
                params[f"plat_{i}"] = p
        if country_list:
            placeholders = ",".join(f":country_{i}" for i in range(len(country_list)))
            clauses.append(f"cp.country IN ({placeholders})")
            for i, c in enumerate(country_list):
                params[f"country_{i}"] = c
        return clauses, params

    extra_clauses, extra_params = _extra_filters()
    intent_sql, intent_params = await _intent_category_filter("Sentiment", "sent_intent")
    extra_clauses.append(intent_sql)
    extra_sql = (" AND " + " AND ".join(extra_clauses)) if extra_clauses else ""

    base_params = {"client_id": client_id, **extra_params, **intent_params}

    # ── 1. KPI Summary (current period) ──────────────────────────────────────
    kpi_sql = f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN sr.sentiment <> 'Insufficient Evidence' THEN 1 ELSE 0 END) AS rated,
            SUM(CASE WHEN sr.sentiment = 'Positive' THEN 1 ELSE 0 END) AS positive,
            SUM(CASE WHEN sr.sentiment = 'Mixed/Neutral' THEN 1 ELSE 0 END) AS mixed_neutral,
            SUM(CASE WHEN sr.sentiment = 'Negative' THEN 1 ELSE 0 END) AS negative,
            SUM(CASE WHEN sr.sentiment = 'Insufficient Evidence' THEN 1 ELSE 0 END) AS insufficient_evidence
        {join_snippet}
          AND {date_range_filter_expr("sr.executed_at", "start", "end")}
        {extra_sql}
    """
    kpi_row = await database.fetch_one(kpi_sql, {**base_params, "start": start, "end": end})

    total = kpi_row["total"] or 0
    rated = kpi_row["rated"] or 0
    pos = kpi_row["positive"] or 0
    mixed = kpi_row["mixed_neutral"] or 0
    neg = kpi_row["negative"] or 0
    insufficient = kpi_row["insufficient_evidence"] or 0
    positive_pct = round(pos / rated * 100, 2) if rated else 0
    mixed_neutral_pct = round(mixed / rated * 100, 2) if rated else 0
    negative_pct = round(neg / rated * 100, 2) if rated else 0

    # KPI prev period
    kpi_prev_row = await database.fetch_one(kpi_sql, {**base_params, "start": prev_start, "end": prev_end})
    prev_rated = kpi_prev_row["rated"] or 0
    prev_pos = kpi_prev_row["positive"] or 0
    prev_pct = round(prev_pos / prev_rated * 100, 2) if prev_rated else 0
    pct_change = round(positive_pct - prev_pct, 2)

    # ── 2. Time Series ────────────────────────────────────────────────────────
    bucket_expr = date_bucket_expr("sr.executed_at", interval, timezone=SHANGHAI_TZ)

    ts_sql = f"""
        SELECT
            {bucket_expr} AS bucket,
            COUNT(*) AS total,
            SUM(CASE WHEN sr.sentiment <> 'Insufficient Evidence' THEN 1 ELSE 0 END) AS rated,
            SUM(CASE WHEN sr.sentiment = 'Positive' THEN 1 ELSE 0 END) AS positive,
            SUM(CASE WHEN sr.sentiment = 'Mixed/Neutral' THEN 1 ELSE 0 END) AS mixed_neutral,
            SUM(CASE WHEN sr.sentiment = 'Negative' THEN 1 ELSE 0 END) AS negative,
            SUM(CASE WHEN sr.sentiment = 'Insufficient Evidence' THEN 1 ELSE 0 END) AS insufficient_evidence
        {join_snippet}
          AND {date_range_filter_expr("sr.executed_at", "start", "end")}
        {extra_sql}
        GROUP BY 1 ORDER BY 1
    """
    ts_rows = await database.fetch_all(ts_sql, {**base_params, "start": start, "end": end})
    ts_prev_rows = await database.fetch_all(ts_sql, {**base_params, "start": prev_start, "end": prev_end})

    def _format_ts(rows, period_start: date, period_end: date):
        formatted = [
            {
                "date": str(r["bucket"]),
                "total": r["total"],
                "rated": r["rated"],
                "positive": r["positive"],
                "mixed_neutral": r["mixed_neutral"],
                "negative": r["negative"],
                "insufficient_evidence": r["insufficient_evidence"],
                "positive_pct": round(r["positive"] / r["rated"] * 100, 2) if r["rated"] else 0,
                "mixed_neutral_pct": round(r["mixed_neutral"] / r["rated"] * 100, 2) if r["rated"] else 0,
                "negative_pct": round(r["negative"] / r["rated"] * 100, 2) if r["rated"] else 0,
            }
            for r in rows
        ]
        if interval != "daily":
            return formatted
        by_date = {row["date"]: row for row in formatted}
        return [
            by_date.get(day, {
                "date": day,
                "total": 0,
                "rated": 0,
                "positive": 0,
                "mixed_neutral": 0,
                "negative": 0,
                "insufficient_evidence": 0,
                "positive_pct": None,
                "mixed_neutral_pct": None,
                "negative_pct": None,
            })
            for day in iter_date_strings(period_start, period_end)
        ]

    themes, pos_themes_top3, neg_themes_top3 = await _query_theme_rows(
        client_id=client_id,
        start=start,
        end=end,
        prev_start=prev_start,
        prev_end=prev_end,
        topic_ids=topic_ids,
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        platform=platform,
        country=country,
        sentiment_filter=sentiment_filter,
        intent_sql=intent_sql,
        intent_params=intent_params,
        sort_by=resolved_sort.sort_by,
        sort_order=resolved_sort.sort_order,
    )

    return SentimentOut(
        summary=SentimentSummary(
            positive_pct=positive_pct,
            mixed_neutral_pct=mixed_neutral_pct,
            negative_pct=negative_pct,
            positive_pct_change=pct_change,
            positive_count=pos,
            mixed_neutral_count=mixed,
            negative_count=neg,
            insufficient_evidence_count=insufficient,
            rated_count=rated,
            total_count=total,
            positive_top3_themes=pos_themes_top3,
            negative_top3_themes=neg_themes_top3,
        ),
        time_series=[TimeSeriesPoint(**p) for p in _format_ts(ts_rows, start, end)],
        prev_time_series=[TimeSeriesPoint(**p) for p in _format_ts(ts_prev_rows, prev_start, prev_end)],
        themes=[ThemeRow(**t) for t in themes],
        filters=SentimentFilters(
            date_from=str(start),
            date_to=str(end),
            prev_date_from=str(prev_start),
            prev_date_to=str(prev_end),
            interval=interval,
        ),
    )


@router.get("/themes", response_model=SentimentThemesOut)
async def get_sentiment_themes(
    client_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    topic_ids: Optional[str] = None,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    sentiment_filter: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> SentimentThemesOut:
    """Refresh only the sortable theme list without recomputing KPIs or trends."""
    resolved_sort = resolve_sort_or_422("sentiment_themes", sort_by, sort_order)
    today = _shanghai_today()
    end = _parse_date(date_to, today)
    start = _parse_date(date_from, end - timedelta(days=6))
    prev_start, prev_end = _prev_period(start, end)
    intent_sql, intent_params = await _intent_category_filter("Sentiment", "sent_intent")
    themes, _, _ = await _query_theme_rows(
        client_id=client_id,
        start=start,
        end=end,
        prev_start=prev_start,
        prev_end=prev_end,
        topic_ids=topic_ids,
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        platform=platform,
        country=country,
        sentiment_filter=sentiment_filter,
        intent_sql=intent_sql,
        intent_params=intent_params,
        sort_by=resolved_sort.sort_by,
        sort_order=resolved_sort.sort_order,
    )
    return SentimentThemesOut(themes=[ThemeRow(**row) for row in themes])


# ─────────────────────────────────────────────────────────────────────────────
# Theme Occurrences (expandable row detail)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/theme-results", response_model=ThemeResultsOut)
async def get_theme_results(
    client_id: str,
    theme_name: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    topic_ids: Optional[str] = None,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    sentiment_filter: Optional[str] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 5,
) -> ThemeResultsOut:
    """
    Return paginated list of geo_results that contributed to a given theme.
    Used for the expandable row in the themes table.
    """
    target_filter = build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        prompt_column="st.client_prompt_id",
        prefix="theme_result_target",
    )
    today = _shanghai_today()
    end = _parse_date(date_to, today)
    start = _parse_date(date_from, end - timedelta(days=6))
    offset = (page - 1) * page_size
    intent_sql, intent_params = await _intent_category_filter("Sentiment", "sent_intent")
    extra_clauses = [intent_sql]
    params = {
        "client_id": client_id,
        "theme_name": theme_name,
        "start": start,
        "end": end,
        **intent_params,
    }
    if target_filter.clause:
        extra_clauses.append(target_filter.clause)
        params.update(target_filter.params)

    topic_list = parse_multi_value(topic_ids)
    if topic_list:
        placeholders = ",".join(f":tid_{i}" for i in range(len(topic_list)))
        extra_clauses.append(f"cp.topic_id IN ({placeholders})")
        for i, topic_id in enumerate(topic_list):
            params[f"tid_{i}"] = topic_id
    platform_list = parse_multi_value(platform)
    if platform_list:
        placeholders = ",".join(f":plat_{i}" for i in range(len(platform_list)))
        extra_clauses.append(f"gr.platform IN ({placeholders})")
        for i, p in enumerate(platform_list):
            params[f"plat_{i}"] = p
    country_list = parse_multi_value(country)
    if country_list:
        placeholders = ",".join(f":country_{i}" for i in range(len(country_list)))
        extra_clauses.append(f"cp.country IN ({placeholders})")
        for i, c in enumerate(country_list):
            params[f"country_{i}"] = c
    if sentiment_filter in ("Positive", "Mixed/Neutral", "Negative"):
        extra_clauses.append("st.sentiment = :sent_filter")
        params["sent_filter"] = sentiment_filter

    extra_sql = " AND ".join(extra_clauses)

    sql = f"""
        SELECT
            st.id,
            st.result_id,
            st.excerpt,
            st.sentiment,
            gr.client_prompt  AS prompt_text,
            gr.platform,
            gr.country,
            gr.ingested_at    AS executed_at
        FROM geo_sentiment_themes st
        JOIN geo_results gr
          ON gr.result_id = st.result_id
         AND gr.client_id = st.client_id
        JOIN geo_client_prompts cp ON cp.id = st.client_prompt_id
         AND cp.client_id = st.client_id
        WHERE st.client_id = :client_id
          AND cp.is_active = TRUE
          AND st.theme_name = :theme_name
          AND {date_range_filter_expr("st.executed_at", "start", "end")}
          AND {extra_sql}
        ORDER BY st.executed_at DESC
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM geo_sentiment_themes st
        JOIN geo_results gr
          ON gr.result_id = st.result_id
         AND gr.client_id = st.client_id
        JOIN geo_client_prompts cp ON cp.id = st.client_prompt_id
         AND cp.client_id = st.client_id
        WHERE st.client_id = :client_id
          AND cp.is_active = TRUE
          AND st.theme_name = :theme_name
          AND {date_range_filter_expr("st.executed_at", "start", "end")}
          AND {extra_sql}
    """
    rows = await database.fetch_all(sql, {**params, "limit": page_size, "offset": offset})
    total_row = await database.fetch_one(count_sql, params)
    total = total_row["total"] if total_row else 0

    return ThemeResultsOut(
        total=total,
        page=page,
        pages=max(1, (total + page_size - 1) // page_size),
        results=[ThemeResultRow(**_serialize(r)) for r in rows],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Result Detail Drawer
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/result/{result_id}", response_model=ResultDetailOut)
async def get_result_detail(
    client_id: str,
    result_id: int,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
) -> ResultDetailOut:
    """
    Return full detail for a single geo_result for the response Drawer.
    Includes: client_prompt, final_prompt, platform, country, executed_at,
              search_queries, full AI response text, and citations.
    """
    target_filter = build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        prompt_column="gr.client_prompt_id",
        prefix="result_detail_target",
    )
    target_sql = f" AND {target_filter.clause}" if target_filter.clause else ""
    result_sql = f"""
        SELECT
            gr.result_id,
            gr.client_prompt,
            gr.final_prompt,
            gr.platform,
            gr.country,
            gr.language,
            gr.ingested_at   AS executed_at,
            gr.text          AS response_text,
            gr.search_queries,
            CASE
                WHEN COALESCE(
                    gr.cloro_response #>> '{{include,searchQueries}}',
                    gr.cloro_response #>> '{{request,include,searchQueries}}',
                    gr.cloro_response #>> '{{input,include,searchQueries}}',
                    gr.cloro_response #>> '{{task,request,include,searchQueries}}',
                    gr.cloro_response #>> '{{task,input,include,searchQueries}}'
                ) = 'false' THEN FALSE
                WHEN COALESCE(
                    gr.cloro_response #>> '{{include,searchQueries}}',
                    gr.cloro_response #>> '{{request,include,searchQueries}}',
                    gr.cloro_response #>> '{{input,include,searchQueries}}',
                    gr.cloro_response #>> '{{task,request,include,searchQueries}}',
                    gr.cloro_response #>> '{{task,input,include,searchQueries}}'
                ) = 'true' THEN TRUE
                ELSE NULL
            END AS search_queries_requested,
            gr.topic_name,
            gr.product,
            gr.intent
        FROM geo_results gr
        JOIN geo_client_prompts cp
          ON cp.id = gr.client_prompt_id
         AND cp.client_id = gr.client_id
        WHERE gr.result_id = :result_id
          AND gr.client_id = :client_id
          AND cp.is_active = TRUE
          {target_sql}
    """
    citations_sql = """
        SELECT source_url, source_domain, source_label, domain_category, source_position
        FROM geo_citations
        WHERE result_id = :result_id AND client_id = :client_id
        ORDER BY source_position NULLS LAST
        LIMIT 100
    """

    result_row = await database.fetch_one(
        result_sql,
        {
            "result_id": result_id,
            "client_id": client_id,
            **target_filter.params,
        },
    )
    if not result_row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Result not found")

    citation_rows = await database.fetch_all(citations_sql, {"result_id": result_id, "client_id": client_id})

    result = _serialize(result_row)
    result["search_queries"], result["search_queries_status"] = _resolve_search_queries_state(
        platform=result.get("platform"),
        search_queries=result.get("search_queries"),
        search_queries_requested=result.pop("search_queries_requested", None),
    )
    result["citations"] = [CitationRow(**_serialize(c)) for c in citation_rows]
    return ResultDetailOut(**result)
