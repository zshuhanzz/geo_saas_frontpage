"""
Cited Pages endpoint — URL-level citation ranking.
"""
import logging
import time
from datetime import timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import database

from ._helpers import date_range_filter_expr, parse_date_range, parse_multi_value
from .target_filters import build_target_filter
from .sorting import resolve_sort_or_422

router = APIRouter()
logger = logging.getLogger(__name__)


class CitedPageRow(BaseModel):
    rank: int
    url: Optional[str] = None
    domain: str
    domain_category: Optional[str] = None
    citation_count: int
    share_pct: float
    is_own: bool
    change_pct: Optional[float] = None


class CitedPagesOut(BaseModel):
    pages: List[CitedPageRow]
    total_unique_pages: int
    total_citations: int
    limit: int
    offset: int
    has_more: bool = False


class CitedPagesCountOut(BaseModel):
    total_unique_pages: int


async def _build_cited_page_scope(
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
    search: Optional[str] = None,
) -> tuple[str, str, dict, object, object]:
    target_filter = build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
    )
    start_date, end_date = parse_date_range(date_from, date_to)
    base_where_parts = [
        "c.client_id = :client_id",
        "cp.is_active = TRUE",
    ]
    params: dict = {
        "client_id": client_id,
    }
    if target_filter.clause:
        base_where_parts.append(target_filter.clause)
        params.update(target_filter.params)

    if topic_id:
        base_where_parts.append("cp.topic_id = :topic_id")
        params["topic_id"] = topic_id
    if topic_ids:
        tid_list = parse_multi_value(topic_ids)
        if tid_list:
            placeholders = ",".join(f":tid_{i}" for i in range(len(tid_list)))
            base_where_parts.append(f"cp.topic_id IN ({placeholders})")
            for i, tid in enumerate(tid_list):
                params[f"tid_{i}"] = tid
    if platform:
        plat_list = parse_multi_value(platform)
        if len(plat_list) == 1:
            base_where_parts.append("cp.platform = :platform")
            params["platform"] = plat_list[0]
        elif plat_list:
            placeholders = ",".join(f":plat_{i}" for i in range(len(plat_list)))
            base_where_parts.append(f"cp.platform IN ({placeholders})")
            for i, p in enumerate(plat_list):
                params[f"plat_{i}"] = p
    country_list = parse_multi_value(country)
    if country_list:
        placeholders = ",".join(f":country_{i}" for i in range(len(country_list)))
        base_where_parts.append(f"cp.country IN ({placeholders})")
        for i, c in enumerate(country_list):
            params[f"country_{i}"] = c

    type_list = parse_multi_value(prompt_type)
    if type_list:
        type_clauses = []
        for i, t in enumerate(type_list):
            type_clauses.append(f"categories @> :pt_{i}::jsonb")
            params[f"pt_{i}"] = f'["{t}"]'
        cit_intent_rows = await database.fetch_all(
            f"""
            SELECT intent_name FROM geo_global_intents
            WHERE is_active = TRUE
              AND ({' OR '.join(type_clauses)})
            """,
            params,
        )
    else:
        cit_intent_rows = await database.fetch_all(
            """
            SELECT intent_name FROM geo_global_intents
            WHERE is_active = TRUE
              AND categories @> '["Citation"]'::jsonb
            """
        )
    cit_intent_names = [r["intent_name"] for r in cit_intent_rows]
    if cit_intent_names:
        placeholders = ",".join(f":intent_{i}" for i in range(len(cit_intent_names)))
        base_where_parts.append(f"cp.intent IN ({placeholders})")
        for i, name in enumerate(cit_intent_names):
            params[f"intent_{i}"] = name

    scope_where_parts = list(base_where_parts)
    list_where_parts = list(base_where_parts)
    if search:
        list_where_parts.append("(c.source_url ILIKE :search OR c.source_domain ILIKE :search)")
        params["search"] = f"%{search}%"

    scope_where_sql = " AND ".join(scope_where_parts)
    list_where_sql = " AND ".join(list_where_parts)
    scope_sql = scope_where_sql + " AND " + date_range_filter_expr("c.executed_at", "start_date", "end_date")
    list_sql = list_where_sql + " AND " + date_range_filter_expr("c.executed_at", "start_date", "end_date")
    return scope_sql, list_sql, params, start_date, end_date


@router.get("/cited-pages", response_model=CitedPagesOut)
async def get_cited_pages(
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
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> CitedPagesOut:
    """
    URL-level citation ranking — most cited pages.
    """
    resolved_sort = resolve_sort_or_422("citation_pages", sort_by, sort_order)
    endpoint_started_at = time.perf_counter()
    scope_sql, list_sql, params, start_date, end_date = await _build_cited_page_scope(
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
        search=search,
    )

    period_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    prev_scope_sql = scope_sql.replace(":start_date", ":prev_start").replace(":end_date", ":prev_end")
    current_period_sql = date_range_filter_expr(
        "c.executed_at", "start_date", "end_date"
    )
    previous_period_sql = date_range_filter_expr(
        "c.executed_at", "prev_start", "prev_end"
    )
    curr_params = {**params, "start_date": start_date, "end_date": end_date}
    prev_params = {**params, "prev_start": prev_start, "prev_end": prev_end}

    query_params = {**curr_params, **prev_params, "limit": limit, "offset": offset}

    page_started_at = time.perf_counter()
    combined_scope_sql = scope_sql.replace(":start_date", ":prev_start")
    current_search_sql = (
        "WHERE (url ILIKE :search OR domain ILIKE :search)"
        if search else ""
    )
    period_current_search_sql = (
        "AND (url ILIKE :search OR domain ILIKE :search)"
        if search else ""
    )
    query_sql = f"""
        WITH period_page_agg AS MATERIALIZED (
            SELECT
                c.source_url AS url,
                c.source_domain AS domain,
                COUNT(*) FILTER (
                    WHERE {current_period_sql}
                )::bigint AS citation_count,
                COUNT(*) FILTER (
                    WHERE {previous_period_sql}
                )::bigint AS previous_citation_count,
                MIN(c.domain_category) FILTER (
                    WHERE {current_period_sql}
                ) AS domain_category
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            WHERE {combined_scope_sql}
            GROUP BY c.source_url, c.source_domain
        ),
        current_agg AS (
            SELECT url, domain, citation_count, previous_citation_count, domain_category
            FROM period_page_agg
            WHERE citation_count > 0
            {period_current_search_sql}
        ),
        current_total AS (
            SELECT COALESCE(SUM(citation_count), 0)::bigint AS total_citations
            FROM period_page_agg
        ),
        previous_total AS (
            SELECT COALESCE(SUM(previous_citation_count), 0)::bigint AS total_citations
            FROM period_page_agg
        ),
        metrics AS (
            SELECT
                ROW_NUMBER() OVER (
                    ORDER BY ca.citation_count DESC, LOWER(ca.url) ASC, ca.url ASC, ca.domain ASC
                )::int AS rank,
                ca.url,
                ca.domain,
                ca.domain_category,
                ca.citation_count,
                EXISTS (
                    SELECT 1
                    FROM geo_client_domains cd
                    WHERE cd.client_id = :client_id
                      AND LOWER(TRIM(cd.domain)) = LOWER(TRIM(ca.domain))
                ) AS is_own,
                CASE
                    WHEN ct.total_citations > 0
                    THEN ROUND(ca.citation_count::numeric / ct.total_citations * 100, 2)
                    ELSE 0::numeric
                END AS share_pct,
                CASE
                    WHEN ca.previous_citation_count > 0 AND pt.total_citations > 0
                    THEN ROUND(
                        ROUND(ca.citation_count::numeric / NULLIF(ct.total_citations, 0) * 100, 2)
                        - ROUND(ca.previous_citation_count::numeric / pt.total_citations * 100, 2),
                        2
                    )
                    ELSE NULL
                END AS change_pct
            FROM current_agg ca
            CROSS JOIN current_total ct
            CROSS JOIN previous_total pt
        ),
        paged AS (
            SELECT
                metrics.*,
                ROW_NUMBER() OVER (ORDER BY {resolved_sort.order_by_sql}) AS page_order
            FROM metrics
            ORDER BY {resolved_sort.order_by_sql}
            LIMIT :limit OFFSET :offset
        ),
        summary AS (
            SELECT COUNT(*)::int AS total_unique FROM current_agg
        )
        SELECT
            paged.rank,
            paged.url,
            paged.domain,
            paged.domain_category,
            paged.citation_count,
            paged.share_pct,
            paged.change_pct,
            paged.is_own,
            summary.total_unique,
            current_total.total_citations
        FROM summary
        CROSS JOIN current_total
        LEFT JOIN paged ON TRUE
        ORDER BY paged.page_order NULLS LAST
        """
    if resolved_sort.sort_by != "change_pct":
        query_sql = f"""
        WITH current_page_agg AS MATERIALIZED (
            SELECT
                c.source_url AS url,
                c.source_domain AS domain,
                COUNT(*)::bigint AS citation_count,
                MIN(c.domain_category) AS domain_category
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            WHERE {scope_sql}
            GROUP BY c.source_url, c.source_domain
        ),
        current_agg AS (
            SELECT url, domain, citation_count, domain_category
            FROM current_page_agg
            {current_search_sql}
        ),
        current_total AS (
            SELECT COALESCE(SUM(citation_count), 0)::bigint AS total_citations
            FROM current_page_agg
        ),
        ranked_current AS MATERIALIZED (
            SELECT
                ROW_NUMBER() OVER (
                    ORDER BY ca.citation_count DESC, LOWER(ca.url) ASC, ca.url ASC, ca.domain ASC
                )::int AS rank,
                ca.url,
                ca.domain,
                ca.domain_category,
                ca.citation_count,
                EXISTS (
                    SELECT 1
                    FROM geo_client_domains cd
                    WHERE cd.client_id = :client_id
                      AND LOWER(TRIM(cd.domain)) = LOWER(TRIM(ca.domain))
                ) AS is_own,
                CASE
                    WHEN ct.total_citations > 0
                    THEN ROUND(ca.citation_count::numeric / ct.total_citations * 100, 2)
                    ELSE 0::numeric
                END AS share_pct
            FROM current_agg ca
            CROSS JOIN current_total ct
        ),
        current_paged AS MATERIALIZED (
            SELECT
                ranked_current.*,
                ROW_NUMBER() OVER (ORDER BY {resolved_sort.order_by_sql}) AS page_order
            FROM ranked_current
            ORDER BY {resolved_sort.order_by_sql}
            LIMIT :limit OFFSET :offset
        ),
        previous_total AS (
            SELECT COUNT(*)::bigint AS total_citations
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            WHERE {prev_scope_sql}
        ),
        previous_candidate_agg AS MATERIALIZED (
            SELECT
                c.source_url AS url,
                c.source_domain AS domain,
                COUNT(*)::bigint AS citation_count
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            JOIN current_paged candidate
              ON ARRAY[candidate.url, candidate.domain] = ARRAY[c.source_url, c.source_domain]
            WHERE {prev_scope_sql}
            GROUP BY c.source_url, c.source_domain
        ),
        metrics AS (
            SELECT
                candidate.rank,
                candidate.url,
                candidate.domain,
                candidate.domain_category,
                candidate.citation_count,
                candidate.share_pct,
                candidate.is_own,
                candidate.page_order,
                CASE
                    WHEN previous.citation_count IS NOT NULL AND pt.total_citations > 0
                    THEN ROUND(
                        candidate.share_pct
                        - ROUND(previous.citation_count::numeric / pt.total_citations * 100, 2),
                        2
                    )
                    ELSE NULL
                END AS change_pct
            FROM current_paged candidate
            LEFT JOIN previous_candidate_agg previous
              ON ARRAY[previous.url, previous.domain] = ARRAY[candidate.url, candidate.domain]
            CROSS JOIN previous_total pt
        ),
        summary AS (
            SELECT COUNT(*)::int AS total_unique FROM current_agg
        )
        SELECT
            metrics.rank,
            metrics.url,
            metrics.domain,
            metrics.domain_category,
            metrics.citation_count,
            metrics.share_pct,
            metrics.change_pct,
            metrics.is_own,
            summary.total_unique,
            current_total.total_citations
        FROM metrics
        RIGHT JOIN summary ON TRUE
        CROSS JOIN current_total
        ORDER BY metrics.page_order NULLS LAST
        """
    rows = await database.fetch_all(query_sql, query_params)
    page_sql_ms = (time.perf_counter() - page_started_at) * 1000

    shape_started_at = time.perf_counter()
    summary_row = dict(rows[0]) if rows else {}
    total_unique_pages = int(summary_row.get("total_unique") or 0)
    total_citations = int(summary_row.get("total_citations") or 0)
    pages: List[CitedPageRow] = []
    for r in rows:
        row = dict(r)
        if row.get("rank") is None:
            continue
        domain = row.get("domain") or ""
        pages.append(CitedPageRow(
            rank=int(row.get("rank") or 0),
            url=row.get("url"),
            domain=domain,
            domain_category=row.get("domain_category") or "Other",
            citation_count=int(row.get("citation_count") or 0),
            share_pct=float(row.get("share_pct") or 0),
            is_own=bool(row.get("is_own")),
            change_pct=float(row["change_pct"]) if row.get("change_pct") is not None else None,
        ))
    has_more = offset + len(pages) < total_unique_pages
    shape_ms = (time.perf_counter() - shape_started_at) * 1000
    logger.info(
        "[cited-pages] client_id=%s total=%s unique=%s limit=%s offset=%s "
        "page_sql_ms=%.1f shape_ms=%.1f total_ms=%.1f",
        client_id,
        total_citations,
        total_unique_pages,
        limit,
        offset,
        page_sql_ms,
        shape_ms,
        (time.perf_counter() - endpoint_started_at) * 1000,
    )

    return CitedPagesOut(
        pages=pages,
        total_unique_pages=total_unique_pages,
        total_citations=total_citations,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get("/cited-pages/count", response_model=CitedPagesCountOut)
async def get_cited_pages_count(
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
    search: Optional[str] = None,
) -> CitedPagesCountOut:
    """Exact unique cited-page count for asynchronous pagination metadata."""
    started_at = time.perf_counter()
    _scope_sql, list_sql, params, start_date, end_date = await _build_cited_page_scope(
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
        search=search,
    )
    total = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT 1
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            WHERE {list_sql}
            GROUP BY c.source_url, c.source_domain
        ) AS cited_page_identities
        """,
        {**params, "start_date": start_date, "end_date": end_date},
    ) or 0
    logger.info(
        "[cited-pages-count] client_id=%s total=%s elapsed_ms=%.1f",
        client_id,
        total,
        (time.perf_counter() - started_at) * 1000,
    )
    return CitedPagesCountOut(total_unique_pages=int(total))
