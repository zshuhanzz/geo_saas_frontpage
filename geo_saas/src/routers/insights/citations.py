"""
Citations endpoint — Domain Ranking + Time Series + Previous Period.

v1.2 note: ``geo_citations`` gained ``citation_role`` / ``matched_brand_id``
columns; this existing endpoint keeps the domain-based own detection logic
(``source_domain ∈ own_domains``) for backwards compatibility of the
dashboard. The new ``citation_role`` breakdown lives in the sibling
``citation_role.py`` endpoint (§8 new endpoints).
"""
import asyncio
import logging
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import database

from ._helpers import SHANGHAI_TZ, date_bucket_expr, date_range_filter_expr, iter_date_strings, parse_date_range, parse_multi_value
from .target_filters import build_target_filter
from .sorting import materialize_default_ranks, resolve_sort_or_422, sort_complete_rows

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Output models ─────────────────────────────────────────────────────────


class CitationDomainRow(BaseModel):
    rank: int
    domain: str
    citation_count: int
    share_pct: float
    is_own: bool
    domain_category: Optional[str] = None
    change_pct: Optional[float] = None


class CitationPageRow(BaseModel):
    rank: int
    url: Optional[str] = None
    domain: str
    citation_count: int
    share_pct: float
    domain_category: Optional[str] = None
    change_pct: Optional[float] = None


class CitationTimePoint(BaseModel):
    date: str
    own_share: Optional[float] = None
    total: int
    own_count: int


class CitationCategoryRow(BaseModel):
    label: str
    count: int
    pct: float


class CitationsSummary(BaseModel):
    total_citations: int
    own_domain_share: float
    own_domain_share_change: Optional[float] = None
    own_citation_count: int
    own_rank: Optional[int] = None
    own_rank_change: Optional[int] = None


class CitationsFilters(BaseModel):
    date_from: str
    date_to: str
    prev_date_from: str
    prev_date_to: str
    interval: str


class CitationsOut(BaseModel):
    summary: CitationsSummary
    domain_ranking: List[CitationDomainRow]
    page_ranking: List[CitationPageRow]
    category_breakdown: List[CitationCategoryRow] = []
    time_series: List[CitationTimePoint]
    prev_time_series: List[CitationTimePoint]
    filters: CitationsFilters


_FROM_CLAUSE = """
    FROM geo_citations c
    JOIN geo_client_prompts cp
      ON cp.id = c.client_prompt_id
     AND cp.client_id = c.client_id
"""


def _period_bounds(params: dict) -> tuple[Any, Any] | None:
    if "start_date" in params and "end_date" in params:
        return params["start_date"], params["end_date"]
    if "prev_start" in params and "prev_end" in params:
        return params["prev_start"], params["prev_end"]
    return None


def _empty_citations_summary(**overrides: Any) -> CitationsSummary:
    values = {
        "total_citations": 0,
        "own_domain_share": 0,
        "own_domain_share_change": None,
        "own_citation_count": 0,
        "own_rank": None,
        "own_rank_change": None,
    }
    values.update(overrides)
    return CitationsSummary(**values)


def _empty_citations_out(
    *,
    filters: CitationsFilters,
    summary: Optional[CitationsSummary] = None,
    domain_ranking: Optional[List[Dict[str, Any]]] = None,
    page_ranking: Optional[List[Dict[str, Any]]] = None,
    category_breakdown: Optional[List[Dict[str, Any]]] = None,
    time_series: Optional[List[Dict[str, Any]]] = None,
    prev_time_series: Optional[List[Dict[str, Any]]] = None,
) -> CitationsOut:
    return CitationsOut(
        summary=summary or _empty_citations_summary(),
        domain_ranking=[CitationDomainRow(**r) for r in (domain_ranking or [])],
        page_ranking=[CitationPageRow(**r) for r in (page_ranking or [])],
        category_breakdown=[CitationCategoryRow(**r) for r in (category_breakdown or [])],
        time_series=[CitationTimePoint(**p) for p in (time_series or [])],
        prev_time_series=[CitationTimePoint(**p) for p in (prev_time_series or [])],
        filters=filters,
    )


def _owned_domain_filter(own_domains: set[str], prefix: str, params: dict) -> str:
    if not own_domains:
        return "FALSE"
    placeholders = ",".join(f":{prefix}_{i}" for i in range(len(own_domains)))
    for i, domain in enumerate(sorted(own_domains)):
        params[f"{prefix}_{i}"] = domain
    return f"LOWER(c.source_domain) IN ({placeholders})"


async def _query_citation_domain_summary(
    where_sql: str,
    params: dict,
    own_domains: set[str],
) -> Dict[str, Any]:
    query_params = {**params}
    if own_domains:
        own_placeholders = ",".join(f":own_domain_{i}" for i in range(len(own_domains)))
        for i, domain in enumerate(sorted(own_domains)):
            query_params[f"own_domain_{i}"] = domain
        own_filter = f"dc.source_domain_lower IN ({own_placeholders})"
    else:
        own_filter = "FALSE"
    row = await database.fetch_one(
        f"""
        WITH domain_counts AS (
            SELECT
                c.source_domain,
                LOWER(c.source_domain) AS source_domain_lower,
                COUNT(*)::int AS citation_count
            {_FROM_CLAUSE}
            WHERE {where_sql}
            GROUP BY c.source_domain
        ),
        owned AS (
            SELECT
                COALESCE(SUM(citation_count), 0)::int AS own_citation_count,
                MIN(1 + higher_count)::int AS own_rank
            FROM (
                SELECT
                    dc.citation_count,
                    (
                        SELECT COUNT(*)
                        FROM domain_counts other_dc
                        WHERE other_dc.citation_count > dc.citation_count
                    ) AS higher_count
                FROM domain_counts dc
                WHERE {own_filter}
            ) owned_domains
        )
        SELECT
            COALESCE((SELECT SUM(citation_count) FROM domain_counts), 0)::int AS total_citations,
            COALESCE((SELECT own_citation_count FROM owned), 0)::int AS own_citation_count,
            (SELECT own_rank FROM owned) AS own_rank
        """,
        query_params,
    )
    total = int(row["total_citations"] or 0) if row else 0
    own_count = int(row["own_citation_count"] or 0) if row else 0
    return {
        "total_citations": total,
        "own_citation_count": own_count,
        "own_share": round(own_count / total * 100, 2) if total else 0,
        "own_rank": int(row["own_rank"]) if row and row["own_rank"] is not None else None,
    }


async def _query_citation_domain_topn(
    where_sql: str,
    params: dict,
    own_domains: set[str],
    total_citations: int,
) -> List[Dict[str, Any]]:
    query_params = {**params}
    own_filter = _owned_domain_filter(own_domains, "top_own_domain", query_params)
    rows = await database.fetch_all(
        f"""
        SELECT
            c.source_domain,
            COUNT(*)::int AS citation_count,
            MIN(c.domain_category) AS domain_category,
            CASE WHEN {own_filter} THEN 1 ELSE 0 END AS is_own
        {_FROM_CLAUSE}
        WHERE {where_sql}
        GROUP BY c.source_domain
        ORDER BY COUNT(*) DESC, c.source_domain ASC
        """,
        query_params,
    )
    shaped_rows = [
        {
            "domain": row["source_domain"] or "",
            "citation_count": int(row["citation_count"] or 0),
            "share_pct": round(int(row["citation_count"] or 0) / total_citations * 100, 2) if total_citations else 0,
            "is_own": int(row["is_own"] or 0) == 1,
            "domain_category": row["domain_category"] or "Other",
        }
        for row in rows
    ]
    return materialize_default_ranks("citation_domains", shaped_rows)


async def _query_citation_domain_share_lookup(
    where_sql: str,
    params: dict,
    total_citations: int,
    domains: List[str],
) -> Dict[str, float]:
    lookup_domains = [domain for domain in domains if domain]
    if not lookup_domains or not total_citations:
        return {}
    query_params = {**params}
    placeholders = ",".join(f":lookup_domain_{i}" for i in range(len(lookup_domains)))
    for i, domain in enumerate(lookup_domains):
        query_params[f"lookup_domain_{i}"] = domain
    rows = await database.fetch_all(
        f"""
        SELECT c.source_domain, COUNT(*)::int AS citation_count
        {_FROM_CLAUSE}
        WHERE {where_sql}
          AND c.source_domain IN ({placeholders})
        GROUP BY c.source_domain
        """,
        query_params,
    )
    return {
        row["source_domain"]: round(int(row["citation_count"] or 0) / total_citations * 100, 2)
        for row in rows
    }


async def _build_citation_filter_context(
    *,
    client_id: UUID,
    topic_id: Optional[str],
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    prompt_type: Optional[str],
    products: Optional[str],
    prompt_id: Optional[str],
    prompt_ids: Optional[str],
    interval: str,
) -> Dict[str, Any]:
    target_filter = build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
    )
    start_date, end_date = parse_date_range(date_from, date_to)
    period_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    base_where_parts = ["c.client_id = :client_id", "cp.is_active = TRUE"]
    base_params: dict = {"client_id": client_id}
    if target_filter.clause:
        base_where_parts.append(target_filter.clause)
        base_params.update(target_filter.params)

    if topic_id:
        base_where_parts.append("cp.topic_id = :topic_id")
        base_params["topic_id"] = topic_id
    if topic_ids:
        tid_list = parse_multi_value(topic_ids)
        if tid_list:
            placeholders = ",".join(f":tid_{i}" for i in range(len(tid_list)))
            base_where_parts.append(f"cp.topic_id IN ({placeholders})")
            for i, tid in enumerate(tid_list):
                base_params[f"tid_{i}"] = tid
    if platform:
        plat_list = parse_multi_value(platform)
        if len(plat_list) == 1:
            base_where_parts.append("cp.platform = :platform")
            base_params["platform"] = plat_list[0]
        elif plat_list:
            placeholders = ",".join(f":plat_{i}" for i in range(len(plat_list)))
            base_where_parts.append(f"cp.platform IN ({placeholders})")
            for i, p in enumerate(plat_list):
                base_params[f"plat_{i}"] = p
    country_list = parse_multi_value(country)
    if country_list:
        placeholders = ",".join(f":country_{i}" for i in range(len(country_list)))
        base_where_parts.append(f"cp.country IN ({placeholders})")
        for i, c in enumerate(country_list):
            base_params[f"country_{i}"] = c

    type_list = parse_multi_value(prompt_type)
    if type_list:
        type_clauses = []
        for i, t in enumerate(type_list):
            type_clauses.append(f"categories @> :pt_{i}::jsonb")
            base_params[f"pt_{i}"] = f'["{t}"]'
        intent_rows = await database.fetch_all(
            f"""
            SELECT intent_name FROM geo_global_intents
            WHERE is_active = TRUE
              AND ({' OR '.join(type_clauses)})
            """,
            base_params,
        )
    else:
        intent_rows = await database.fetch_all(
            """
            SELECT intent_name FROM geo_global_intents
            WHERE is_active = TRUE
              AND categories @> '["Citation"]'::jsonb
            """
        )
    cit_intent_names = [r["intent_name"] for r in intent_rows]
    if cit_intent_names:
        placeholders = ",".join(f":intent_{i}" for i in range(len(cit_intent_names)))
        base_where_parts.append(f"cp.intent IN ({placeholders})")
        for i, name in enumerate(cit_intent_names):
            base_params[f"intent_{i}"] = name

    domain_rows = await database.fetch_all(
        "SELECT domain FROM geo_client_domains WHERE client_id = :client_id",
        {"client_id": client_id},
    )
    own_domains = {r["domain"].lower() for r in domain_rows}
    base_where_sql = " AND ".join(base_where_parts)
    curr_where_sql = base_where_sql + " AND " + date_range_filter_expr("c.executed_at", "start_date", "end_date")
    prev_where_sql = base_where_sql + " AND " + date_range_filter_expr("c.executed_at", "prev_start", "prev_end")
    return {
        "curr_where_sql": curr_where_sql,
        "curr_params": {**base_params, "start_date": start_date, "end_date": end_date},
        "prev_where_sql": prev_where_sql,
        "prev_params": {**base_params, "prev_start": prev_start, "prev_end": prev_end},
        "own_domains": own_domains,
        "filters": CitationsFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            prev_date_from=prev_start.isoformat(),
            prev_date_to=prev_end.isoformat(),
            interval=interval,
        ),
        "interval": interval,
    }


async def _query_citation_share_chart(where_sql: str, params: dict, interval: str, own_domains: set) -> Dict[str, Any]:
    bucket_sql = date_bucket_expr("c.executed_at", interval, timezone=SHANGHAI_TZ)
    if own_domains:
        owned_placeholders = ",".join(f":owned_{i}" for i in range(len(own_domains)))
        query_params = {**params}
        for i, dom in enumerate(own_domains):
            query_params[f"owned_{i}"] = dom
        own_case = (
            f"SUM(CASE WHEN LOWER(c.source_domain) IN ({owned_placeholders}) "
            "THEN 1 ELSE 0 END)::int"
        )
    else:
        own_case = "0::int"
        query_params = params
    rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_sql} AS bucket,
            COUNT(*) AS total,
            {own_case} AS own_count
        {_FROM_CLAUSE}
        WHERE {where_sql}
        GROUP BY {bucket_sql}
        ORDER BY {bucket_sql}
        """,
        query_params,
    )
    time_series = []
    total_citations = 0
    own_citation_count = 0
    for row in rows:
        d = row["bucket"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        total = int(row["total"] or 0)
        own = int(row["own_count"] or 0)
        total_citations += total
        own_citation_count += own
        time_series.append({
            "date": date_str,
            "own_share": round((own / total * 100), 2) if total else 0,
            "total": total,
            "own_count": own,
        })
    if interval == "daily" and (bounds := _period_bounds(params)):
        by_date = {row["date"]: row for row in time_series}
        time_series = [
            by_date.get(day, {"date": day, "own_share": None, "total": 0, "own_count": 0})
            for day in iter_date_strings(bounds[0], bounds[1])
        ]
    own_share = (
        round((int(own_citation_count) / int(total_citations) * 100), 2)
        if total_citations else 0
    )
    return {
        "total_citations": int(total_citations),
        "own_share": own_share,
        "own_citation_count": int(own_citation_count),
        "time_series": time_series,
    }


async def _query_citation_ranking_chart(where_sql: str, params: dict, own_domains: set) -> Dict[str, Any]:
    summary, domain_ranking = await asyncio.gather(
        _query_citation_domain_summary(where_sql, params, own_domains),
        _query_citation_domain_topn(where_sql, params, own_domains, 0),
    )
    total_citations = summary["total_citations"]
    if total_citations:
        for row in domain_ranking:
            row["share_pct"] = round(row["citation_count"] / total_citations * 100, 2)
    return {
        "total_citations": total_citations,
        "own_citation_count": summary["own_citation_count"],
        "own_share": summary["own_share"],
        "own_rank": summary["own_rank"],
        "domain_ranking": domain_ranking,
        "domain_lookup": {row["domain"]: row["share_pct"] for row in domain_ranking},
    }


async def _query_citation_categories_chart(where_sql: str, params: dict) -> Dict[str, Any]:
    total_citations = await database.fetch_val(
        f"SELECT COUNT(*) {_FROM_CLAUSE} WHERE {where_sql}",
        params,
    ) or 0
    rows = await database.fetch_all(
        f"""
        SELECT
            COALESCE(c.domain_category, 'Other') AS domain_category,
            COUNT(*) AS citation_count
        {_FROM_CLAUSE}
        WHERE {where_sql}
        GROUP BY COALESCE(c.domain_category, 'Other')
        ORDER BY COUNT(*) DESC
        """,
        params,
    )
    return {
        "total_citations": int(total_citations),
        "category_breakdown": [
            {
                "label": row["domain_category"],
                "count": int(row["citation_count"] or 0),
                "pct": round((int(row["citation_count"] or 0) / int(total_citations) * 100), 2) if total_citations else 0,
            }
            for row in rows
        ],
    }


async def _query_citations(
    where_sql: str, params: dict, interval: str, own_domains: set
) -> dict:
    """Reusable query helper for citations data."""
    started_at = time.perf_counter()
    bucket_sql = date_bucket_expr("c.executed_at", interval, timezone=SHANGHAI_TZ)

    # ----- Domain Ranking -----
    domain_summary, domain_ranking = await asyncio.gather(
        _query_citation_domain_summary(where_sql, params, own_domains),
        _query_citation_domain_topn(where_sql, params, own_domains, 0),
    )
    domain_sql_ms = (time.perf_counter() - started_at) * 1000
    total_citations = int(domain_summary["total_citations"])
    own_citation_count = int(domain_summary["own_citation_count"])
    own_share = float(domain_summary["own_share"])
    own_rank = domain_summary["own_rank"]
    for row in domain_ranking:
        row["share_pct"] = round(row["citation_count"] / total_citations * 100, 2) if total_citations else 0
    domain_lookup = {row["domain"]: row["share_pct"] for row in domain_ranking}
    domain_shape_ms = 0.0

    category_started_at = time.perf_counter()
    category_rows = await database.fetch_all(
        f"""
        SELECT
            COALESCE(c.domain_category, 'Other') AS domain_category,
            COUNT(*) AS citation_count
        {_FROM_CLAUSE}
        WHERE {where_sql}
        GROUP BY COALESCE(c.domain_category, 'Other')
        ORDER BY COUNT(*) DESC
        """,
        params,
    )
    category_sql_ms = (time.perf_counter() - category_started_at) * 1000
    category_shape_started_at = time.perf_counter()
    category_breakdown = [
        {
            "label": r["domain_category"],
            "count": int(r["citation_count"] or 0),
            "pct": round((int(r["citation_count"] or 0) / total_citations * 100), 2) if total_citations > 0 else 0,
        }
        for r in category_rows
    ]
    category_shape_ms = (time.perf_counter() - category_shape_started_at) * 1000

    # ----- Time Series -----
    ts_started_at = time.perf_counter()
    if own_domains:
        # Inline the own_domains set as a literal IN clause via params.
        owned_placeholders = ",".join(
            f":owned_{i}" for i in range(len(own_domains))
        )
        ts_params = {**params}
        for i, dom in enumerate(own_domains):
            ts_params[f"owned_{i}"] = dom
        own_case = (
            f"SUM(CASE WHEN LOWER(c.source_domain) IN ({owned_placeholders}) "
            "THEN 1 ELSE 0 END)::int"
        )
    else:
        own_case = "0::int"
        ts_params = params

    ts_rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_sql} AS bucket,
            COUNT(*) AS total,
            {own_case} AS own_count
        {_FROM_CLAUSE}
        WHERE {where_sql}
        GROUP BY {bucket_sql}
        ORDER BY {bucket_sql}
        """,
        ts_params,
    )
    ts_sql_ms = (time.perf_counter() - ts_started_at) * 1000

    ts_shape_started_at = time.perf_counter()
    time_series = []
    for r in ts_rows:
        d = r["bucket"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        total = r["total"]
        own = r["own_count"] or 0
        share = round((own / total * 100), 2) if total > 0 else 0
        time_series.append({"date": date_str, "own_share": share, "total": total, "own_count": own})
    if interval == "daily" and (bounds := _period_bounds(params)):
        by_date = {row["date"]: row for row in time_series}
        time_series = [
            by_date.get(day, {"date": day, "own_share": None, "total": 0, "own_count": 0})
            for day in iter_date_strings(bounds[0], bounds[1])
        ]
    ts_shape_ms = (time.perf_counter() - ts_shape_started_at) * 1000

    # ----- Page Ranking (by full URL) -----
    page_started_at = time.perf_counter()
    page_rows = await database.fetch_all(
        f"""
        SELECT
            c.source_url,
            c.source_domain,
            COUNT(*) AS citation_count,
            MIN(c.domain_category) AS domain_category
        {_FROM_CLAUSE}
        WHERE {where_sql}
        GROUP BY c.source_url, c.source_domain
        ORDER BY COUNT(*) DESC, c.source_url ASC
        """,
        params,
    )
    page_sql_ms = (time.perf_counter() - page_started_at) * 1000

    page_shape_started_at = time.perf_counter()
    page_ranking = []
    for r in page_rows:
        url = r["source_url"]
        domain = r["source_domain"] or ""
        pct = round((r["citation_count"] / total_citations * 100), 2) if total_citations > 0 else 0
        page_ranking.append({
            "url": url,
            "domain": domain,
            "citation_count": r["citation_count"],
            "share_pct": pct,
            "domain_category": r["domain_category"] or "Other",
        })
    page_ranking = materialize_default_ranks("citation_pages", page_ranking)
    page_shape_ms = (time.perf_counter() - page_shape_started_at) * 1000

    logger.info(
        "[citations] client_id=%s interval=%s total=%s domain_topn_summary_sql_ms=%.1f "
        "category_sql_ms=%.1f ts_sql_ms=%.1f page_sql_ms=%.1f shape_ms=%.1f",
        params.get("client_id"),
        interval,
        total_citations,
        domain_sql_ms,
        category_sql_ms,
        ts_sql_ms,
        page_sql_ms,
        domain_shape_ms + category_shape_ms + ts_shape_ms + page_shape_ms,
    )

    return {
        "total_citations": total_citations,
        "own_share": own_share,
        "own_citation_count": own_citation_count,
        "own_rank": own_rank,
        "domain_ranking": domain_ranking,
        "page_ranking": page_ranking,
        "category_breakdown": category_breakdown,
        "domain_lookup": domain_lookup,
        "time_series": time_series,
    }


@router.get("/citations", response_model=CitationsOut)
async def get_citations(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    prompt_type: Optional[str] = None,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    domain_sort_by: Optional[str] = None,
    domain_sort_order: Optional[str] = None,
    page_sort_by: Optional[str] = None,
    page_sort_order: Optional[str] = None,
    category_sort_by: Optional[str] = None,
    category_sort_order: Optional[str] = None,
) -> CitationsOut:
    """Pre-aggregated Citation metrics with previous period comparison."""
    domain_sort = resolve_sort_or_422(
        "citation_domains",
        domain_sort_by if domain_sort_by is not None else sort_by,
        domain_sort_order if domain_sort_order is not None else sort_order,
    )
    page_sort = resolve_sort_or_422(
        "citation_pages",
        page_sort_by,
        page_sort_order,
    )
    category_sort = resolve_sort_or_422("citation_categories", category_sort_by, category_sort_order)
    target_filter = build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
    )
    start_date, end_date = parse_date_range(date_from, date_to)
    period_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    base_where_parts = ["c.client_id = :client_id", "cp.is_active = TRUE"]
    base_params: dict = {"client_id": client_id}
    if target_filter.clause:
        base_where_parts.append(target_filter.clause)
        base_params.update(target_filter.params)

    if topic_id:
        base_where_parts.append("cp.topic_id = :topic_id")
        base_params["topic_id"] = topic_id
    if topic_ids:
        tid_list = parse_multi_value(topic_ids)
        if tid_list:
            placeholders = ",".join(f":tid_{i}" for i in range(len(tid_list)))
            base_where_parts.append(f"cp.topic_id IN ({placeholders})")
            for i, tid in enumerate(tid_list):
                base_params[f"tid_{i}"] = tid
    if platform:
        plat_list = parse_multi_value(platform)
        if len(plat_list) == 1:
            base_where_parts.append("cp.platform = :platform")
            base_params["platform"] = plat_list[0]
        elif plat_list:
            placeholders = ",".join(f":plat_{i}" for i in range(len(plat_list)))
            base_where_parts.append(f"cp.platform IN ({placeholders})")
            for i, p in enumerate(plat_list):
                base_params[f"plat_{i}"] = p
    country_list = parse_multi_value(country)
    if country_list:
        placeholders = ",".join(f":country_{i}" for i in range(len(country_list)))
        base_where_parts.append(f"cp.country IN ({placeholders})")
        for i, c in enumerate(country_list):
            base_params[f"country_{i}"] = c

    type_list = parse_multi_value(prompt_type)
    if type_list:
        # Match intents whose JSONB ``categories`` array contains any of the
        # requested types. Build OR over @> jsonb checks.
        type_clauses = []
        for i, t in enumerate(type_list):
            type_clauses.append(f"categories @> :pt_{i}::jsonb")
            base_params[f"pt_{i}"] = f'["{t}"]'
        intent_rows = await database.fetch_all(
            f"""
            SELECT intent_name FROM geo_global_intents
            WHERE is_active = TRUE
              AND ({' OR '.join(type_clauses)})
            """,
            base_params,
        )
    else:
        intent_rows = await database.fetch_all(
            """
            SELECT intent_name FROM geo_global_intents
            WHERE is_active = TRUE
              AND categories @> '["Citation"]'::jsonb
            """
        )
    cit_intent_names = [r["intent_name"] for r in intent_rows]
    if cit_intent_names:
        placeholders = ",".join(f":intent_{i}" for i in range(len(cit_intent_names)))
        base_where_parts.append(f"cp.intent IN ({placeholders})")
        for i, name in enumerate(cit_intent_names):
            base_params[f"intent_{i}"] = name

    # Load own domains (v1.2: restrict to client's full domain list — Own Brand
    # gates are applied via citation_role elsewhere).
    domain_rows = await database.fetch_all(
        "SELECT domain FROM geo_client_domains WHERE client_id = :client_id",
        {"client_id": client_id},
    )
    own_domains = {r["domain"].lower() for r in domain_rows}

    base_where_sql = " AND ".join(base_where_parts)

    curr_where_sql = base_where_sql + " AND " + date_range_filter_expr("c.executed_at", "start_date", "end_date")
    curr_params = {**base_params, "start_date": start_date, "end_date": end_date}
    curr = await _query_citations(curr_where_sql, curr_params, interval, own_domains)

    prev_where_sql = base_where_sql + " AND " + date_range_filter_expr("c.executed_at", "prev_start", "prev_end")
    prev_params = {**base_params, "prev_start": prev_start, "prev_end": prev_end}
    prev = await _query_citations(prev_where_sql, prev_params, interval, own_domains)

    for payload in (curr, prev):
        payload["domain_ranking"] = materialize_default_ranks(
            "citation_domains", payload["domain_ranking"]
        )
        payload["page_ranking"] = materialize_default_ranks(
            "citation_pages", payload["page_ranking"]
        )

    share_change = round(curr["own_share"] - prev["own_share"], 2) if prev["own_share"] is not None else None
    rank_change = (
        int(curr["own_rank"]) - int(prev["own_rank"])
        if curr["own_rank"] is not None and prev["own_rank"] is not None
        else None
    )

    prev_domain_map = await _query_citation_domain_share_lookup(
        prev_where_sql,
        prev_params,
        prev["total_citations"],
        [r["domain"] for r in curr["domain_ranking"]],
    )
    for r in curr["domain_ranking"]:
        prev_pct = prev_domain_map.get(r["domain"])
        r["change_pct"] = round(r["share_pct"] - prev_pct, 2) if prev_pct is not None else None

    prev_page_map = {r["url"]: r["share_pct"] for r in prev["page_ranking"]}
    for r in curr["page_ranking"]:
        prev_pct = prev_page_map.get(r["url"])
        r["change_pct"] = round(r["share_pct"] - prev_pct, 2) if prev_pct is not None else None
    curr["domain_ranking"] = sort_complete_rows(
        "citation_domains", curr["domain_ranking"], domain_sort.sort_by, domain_sort.sort_order
    )
    curr["page_ranking"] = sort_complete_rows(
        "citation_pages", curr["page_ranking"], page_sort.sort_by, page_sort.sort_order
    )
    curr["category_breakdown"] = sort_complete_rows(
        "citation_categories", curr["category_breakdown"], category_sort.sort_by, category_sort.sort_order
    )

    return CitationsOut(
        summary=CitationsSummary(
            total_citations=curr["total_citations"],
            own_domain_share=curr["own_share"],
            own_domain_share_change=share_change,
            own_citation_count=curr["own_citation_count"],
            own_rank=curr["own_rank"],
            own_rank_change=rank_change,
        ),
        domain_ranking=[CitationDomainRow(**r) for r in curr["domain_ranking"]],
        page_ranking=[CitationPageRow(**r) for r in curr["page_ranking"]],
        category_breakdown=[CitationCategoryRow(**r) for r in curr["category_breakdown"]],
        time_series=[CitationTimePoint(**p) for p in curr["time_series"]],
        prev_time_series=[CitationTimePoint(**p) for p in prev["time_series"]],
        filters=CitationsFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            prev_date_from=prev_start.isoformat(),
            prev_date_to=prev_end.isoformat(),
            interval=interval,
        ),
    )


@router.get("/citations/share", response_model=CitationsOut)
async def get_citation_share_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    prompt_type: Optional[str] = None,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
) -> CitationsOut:
    ctx = await _build_citation_filter_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
        prompt_type=prompt_type,
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        interval=interval,
    )
    curr = await _query_citation_share_chart(ctx["curr_where_sql"], ctx["curr_params"], interval, ctx["own_domains"])
    prev = await _query_citation_share_chart(ctx["prev_where_sql"], ctx["prev_params"], interval, ctx["own_domains"])
    return _empty_citations_out(
        filters=ctx["filters"],
        summary=_empty_citations_summary(
            total_citations=curr["total_citations"],
            own_domain_share=curr["own_share"],
            own_domain_share_change=round(curr["own_share"] - prev["own_share"], 2),
            own_citation_count=curr["own_citation_count"],
        ),
        time_series=curr["time_series"],
        prev_time_series=prev["time_series"],
    )


@router.get("/citations/ranking", response_model=CitationsOut)
async def get_citation_ranking_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    prompt_type: Optional[str] = None,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> CitationsOut:
    resolved_sort = resolve_sort_or_422("citation_domains", sort_by, sort_order)
    ctx = await _build_citation_filter_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
        prompt_type=prompt_type,
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        interval=interval,
    )
    curr = await _query_citation_ranking_chart(ctx["curr_where_sql"], ctx["curr_params"], ctx["own_domains"])
    prev = await _query_citation_ranking_chart(ctx["prev_where_sql"], ctx["prev_params"], ctx["own_domains"])
    for payload in (curr, prev):
        payload["domain_ranking"] = materialize_default_ranks(
            "citation_domains", payload["domain_ranking"]
        )
    prev_domain_map = await _query_citation_domain_share_lookup(
        ctx["prev_where_sql"],
        ctx["prev_params"],
        prev["total_citations"],
        [row["domain"] for row in curr["domain_ranking"]],
    )
    for row in curr["domain_ranking"]:
        prev_pct = prev_domain_map.get(row["domain"])
        row["change_pct"] = round(row["share_pct"] - prev_pct, 2) if prev_pct is not None else None
    curr["domain_ranking"] = sort_complete_rows(
        "citation_domains", curr["domain_ranking"], resolved_sort.sort_by, resolved_sort.sort_order
    )
    own_rank_change = (
        int(curr["own_rank"]) - int(prev["own_rank"])
        if curr["own_rank"] is not None and prev["own_rank"] is not None
        else None
    )
    return _empty_citations_out(
        filters=ctx["filters"],
        summary=_empty_citations_summary(
            total_citations=curr["total_citations"],
            own_domain_share=curr["own_share"],
            own_citation_count=curr["own_citation_count"],
            own_rank=curr["own_rank"],
            own_rank_change=own_rank_change,
        ),
        domain_ranking=curr["domain_ranking"],
    )


@router.get("/citations/categories", response_model=CitationsOut)
async def get_citation_categories_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    prompt_type: Optional[str] = None,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> CitationsOut:
    resolved_sort = resolve_sort_or_422("citation_categories", sort_by, sort_order)
    ctx = await _build_citation_filter_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        date_from=date_from,
        date_to=date_to,
        prompt_type=prompt_type,
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        interval=interval,
    )
    curr = await _query_citation_categories_chart(ctx["curr_where_sql"], ctx["curr_params"])
    curr["category_breakdown"] = sort_complete_rows(
        "citation_categories", curr["category_breakdown"], resolved_sort.sort_by, resolved_sort.sort_order
    )
    return _empty_citations_out(
        filters=ctx["filters"],
        summary=_empty_citations_summary(total_citations=curr["total_citations"]),
        category_breakdown=curr["category_breakdown"],
    )
