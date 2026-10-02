"""Published URL citation tracking for the Citation dashboard."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from db import database
from ._helpers import date_range_filter_expr, local_date_expr, parse_date_range, parse_multi_value
from .sorting import resolve_sort_or_422, sort_complete_rows
from .target_filters import build_target_filter
from .published_url_matching import (
    build_candidate_url_predicate,
    resolve_published_url_variants,
)


router = APIRouter()
logger = logging.getLogger(__name__)


class PublishedUrlTrackingRow(BaseModel):
    rank: int
    published_url_id: UUID
    title: str
    published_url: str
    normalized_url: str
    channel: str
    publish_status: str
    citation_category: Optional[str] = None
    published_at: Optional[date] = None
    citation_count: int
    share_pct: float
    previous_citation_count: Optional[int] = None
    change_count: Optional[int] = None
    previous_share_pct: Optional[float] = None
    change_share_pct: Optional[float] = None
    last_cited_at: Optional[str] = None
    candidate_count: int = 0
    topics: List[dict] = Field(default_factory=list)
    triggered_topics: List[dict] = Field(default_factory=list)


class PublishedUrlTrackingOut(BaseModel):
    items: List[PublishedUrlTrackingRow]
    total: int
    total_citations: int
    limit: int
    offset: int


class PublishedUrlVariantRow(BaseModel):
    source_url: str
    match_key: str
    status: Literal["exact", "automatic", "confirmed", "pending", "rejected"]
    citation_count: int
    first_cited_at: Optional[str] = None
    last_cited_at: Optional[str] = None
    included: bool


class PublishedUrlVariantsOut(BaseModel):
    published_url_id: UUID
    variants: List[PublishedUrlVariantRow]
    pending_count: int


class PublishedUrlPromptRef(BaseModel):
    client_prompt_id: UUID
    client_prompt_text: str
    topic_name: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    citation_count: int


class PublishedUrlResponseRef(BaseModel):
    result_id: int
    task_id: UUID
    client_prompt_text: str
    platform: Optional[str] = None
    country: Optional[str] = None
    executed_at: Optional[str] = None
    source_position: Optional[int] = None
    source_label: Optional[str] = None
    response_excerpt: Optional[str] = None


class PublishedUrlTrackingDetailOut(BaseModel):
    published_url_id: UUID
    title: str
    published_url: str
    normalized_url: str
    channel: str
    publish_status: str
    citation_category: Optional[str] = None
    trend_7d: List[dict]
    trend_14d: List[dict]
    trend_30d: List[dict]
    topics: List[dict]
    platforms: List[dict]
    countries: List[dict]
    prompts: List[PublishedUrlPromptRef]
    prompts_total: int
    prompt_limit: int
    prompt_offset: int
    responses: List[PublishedUrlResponseRef]
    responses_total: int
    response_limit: int
    response_offset: int


def _build_filters(
    client_id: UUID,
    date_from: Optional[str],
    date_to: Optional[str],
    topic_id: Optional[str],
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    citation_intent_names: List[str],
    products: Optional[str],
    prompt_id: Optional[str],
    prompt_ids: Optional[str],
) -> tuple[str, Dict[str, object], date, date]:
    start_date, end_date = parse_date_range(date_from, date_to)
    where_parts = [
        "c.client_id = :client_id",
        "cp.client_id = :client_id",
        "cp.is_active = TRUE",
        date_range_filter_expr("c.executed_at", "start_date", "end_date"),
    ]
    params: Dict[str, object] = {
        "client_id": client_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    target_filter = build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        prefix="published_target",
    )
    if target_filter.clause:
        where_parts.append(target_filter.clause)
        params.update(target_filter.params)

    if topic_id:
        where_parts.append("cp.topic_id = :topic_id")
        params["topic_id"] = topic_id
    if topic_ids:
        tid_list = [t.strip() for t in topic_ids.split(",") if t.strip()]
        if tid_list:
            placeholders = ",".join(f":tid_{idx}" for idx in range(len(tid_list)))
            where_parts.append(f"cp.topic_id IN ({placeholders})")
            for idx, tid in enumerate(tid_list):
                params[f"tid_{idx}"] = tid

    platform_list = parse_multi_value(platform)
    if platform_list:
        placeholders = ",".join(f":platform_{idx}" for idx in range(len(platform_list)))
        where_parts.append(f"cp.platform IN ({placeholders})")
        for idx, value in enumerate(platform_list):
            params[f"platform_{idx}"] = value

    country_list = parse_multi_value(country)
    if country_list:
        placeholders = ",".join(f":country_{idx}" for idx in range(len(country_list)))
        where_parts.append(f"cp.country IN ({placeholders})")
        for idx, value in enumerate(country_list):
            params[f"country_{idx}"] = value

    if citation_intent_names:
        placeholders = ",".join(
            f":intent_{idx}" for idx in range(len(citation_intent_names))
        )
        where_parts.append(f"cp.intent IN ({placeholders})")
        for idx, value in enumerate(citation_intent_names):
            params[f"intent_{idx}"] = value

    return " AND ".join(where_parts), params, start_date, end_date


async def _resolve_citation_intent_names(prompt_type: Optional[str]) -> List[str]:
    """Resolve the same Citation intent scope used by the cited-pages endpoint."""
    type_list = parse_multi_value(prompt_type)
    if type_list:
        params: Dict[str, object] = {}
        type_clauses = []
        for idx, category in enumerate(type_list):
            type_clauses.append(f"categories @> :pt_{idx}::jsonb")
            params[f"pt_{idx}"] = f'["{category}"]'
        rows = await database.fetch_all(
            f"""
            SELECT intent_name
            FROM geo_global_intents
            WHERE is_active = TRUE
              AND ({' OR '.join(type_clauses)})
            """,
            params,
        )
    else:
        rows = await database.fetch_all(
            """
            SELECT intent_name
            FROM geo_global_intents
            WHERE is_active = TRUE
              AND categories @> '["Citation"]'::jsonb
            """
        )
    return [str(row["intent_name"]) for row in rows]


def _validate_target_filter_inputs(
    products: Optional[str],
    prompt_id: Optional[str],
    prompt_ids: Optional[str],
) -> None:
    """Keep invalid target filters from causing a database round trip."""
    build_target_filter(
        products=products,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        prefix="published_target",
    )


def _date_series(start_date: date, end_date: date, counts: Dict[date, int]) -> List[dict]:
    days = (end_date - start_date).days
    return [
        {"date": (start_date + timedelta(days=idx)).isoformat(), "citation_count": counts.get(start_date + timedelta(days=idx), 0)}
        for idx in range(days + 1)
    ]


async def _load_url_match_mappings(
    client_id: UUID,
    published_url_ids: list[UUID],
) -> list[dict]:
    if not published_url_ids:
        return []
    rows = await database.fetch_all(
        """
        SELECT
            published_url_id,
            citation_url,
            citation_match_key,
            status
        FROM geo_published_url_citation_matches
        WHERE client_id = :client_id
          AND published_url_id = ANY(:published_url_ids::uuid[])
        """,
        {"client_id": client_id, "published_url_ids": published_url_ids},
    )
    return [dict(row) for row in rows]


@router.get("/published-url-tracking", response_model=PublishedUrlTrackingOut)
async def get_published_url_tracking(
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
    status: Optional[str] = None,
    channel: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PublishedUrlTrackingOut:
    resolved_sort = resolve_sort_or_422("published_url_tracking", sort_by, sort_order)
    started_at = time.perf_counter()
    limit = int(limit) if isinstance(limit, int) else 20
    offset = int(offset) if isinstance(offset, int) else 0
    _validate_target_filter_inputs(products, prompt_id, prompt_ids)
    citation_intent_names = await _resolve_citation_intent_names(prompt_type)
    citation_where, citation_params, start_date, end_date = _build_filters(
        client_id, date_from, date_to, topic_id, topic_ids, platform, country,
        citation_intent_names,
        products, prompt_id, prompt_ids,
    )
    period_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    prev_citation_where, prev_citation_params, _, _ = _build_filters(
        client_id,
        prev_start.isoformat(),
        prev_end.isoformat(),
        topic_id,
        topic_ids,
        platform,
        country,
        citation_intent_names,
        products,
        prompt_id,
        prompt_ids,
    )

    published_where = [
        "pu.client_id = :client_id",
        "pu.is_active = TRUE",
        "pu.publish_status = 'published'",
    ]
    published_params: Dict[str, object] = {"client_id": client_id}
    if search:
        published_where.append(
            "(pu.title ILIKE :search OR pu.published_url ILIKE :search OR pu.channel ILIKE :search)"
        )
        published_params["search"] = f"%{search}%"
    if status:
        published_where.append("pu.publish_status = :status")
        published_params["status"] = status
    if channel:
        published_where.append("pu.channel = :channel")
        published_params["channel"] = channel

    published_where_sql = " AND ".join(published_where)
    published_rows = await database.fetch_all(
        f"""
        SELECT
            pu.id, pu.title, pu.published_url, pu.normalized_url,
            pu.channel, pu.publish_status, pu.published_at
        FROM geo_published_urls pu
        WHERE {published_where_sql}
        ORDER BY pu.published_at DESC, pu.updated_at DESC
        """,
        published_params,
    )
    if not published_rows:
        return PublishedUrlTrackingOut(
            items=[],
            total=0,
            total_citations=0,
            limit=limit,
            offset=offset,
        )

    published_ids = [row["id"] for row in published_rows]
    mapping_rows = await _load_url_match_mappings(client_id, published_ids)
    candidate_url_where, candidate_url_params = build_candidate_url_predicate(
        published_rows=published_rows,
        mapping_rows=mapping_rows,
        prefix="published_candidate",
    )

    total_citations = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE {citation_where}
          AND c.source_url IS NOT NULL
        """,
        citation_params,
    ) or 0
    prev_total_citations = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE {prev_citation_where}
          AND c.source_url IS NOT NULL
        """,
        prev_citation_params,
    ) or 0

    current_match_rows = []
    triggered_topic_rows = []
    previous_match_rows = []
    if candidate_url_where != "FALSE":
        url_filter_params = {**citation_params, **candidate_url_params}
        current_match_rows = await database.fetch_all(
            f"""
            SELECT
                c.source_url,
                c.domain_category,
                COUNT(*) AS citation_count,
                MAX(c.executed_at) AS last_cited_at
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            WHERE {citation_where}
              AND {candidate_url_where}
            GROUP BY c.source_url, c.domain_category
            """,
            url_filter_params,
        )
        triggered_topic_rows = await database.fetch_all(
            f"""
            SELECT
                c.source_url,
                ct.id AS topic_id,
                ct.topic_name,
                COUNT(*) AS citation_count
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            LEFT JOIN geo_client_topics ct
              ON ct.id = cp.topic_id
             AND ct.client_id = cp.client_id
            WHERE {citation_where}
              AND {candidate_url_where}
              AND ct.id IS NOT NULL
            GROUP BY c.source_url, ct.id, ct.topic_name
            ORDER BY COUNT(*) DESC, ct.topic_name
            """,
            url_filter_params,
        )
        previous_match_rows = await database.fetch_all(
            f"""
            SELECT
                c.source_url,
                COUNT(*) AS citation_count
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            WHERE {prev_citation_where}
              AND {candidate_url_where}
            GROUP BY c.source_url
            """,
            {**prev_citation_params, **candidate_url_params},
        )

    current_resolution = resolve_published_url_variants(
        published_rows=published_rows,
        citation_rows=current_match_rows,
        mapping_rows=mapping_rows,
    )
    previous_resolution = resolve_published_url_variants(
        published_rows=published_rows,
        citation_rows=previous_match_rows,
        mapping_rows=mapping_rows,
    )
    published_id_values = {str(value): value for value in published_ids}
    url_to_ids = {
        source_url: {
            published_id_values[page_id]
            for page_id in page_ids
            if page_id in published_id_values
        }
        for source_url, page_ids in current_resolution.published_ids_by_source_url.items()
    }
    previous_url_to_ids = {
        source_url: {
            published_id_values[page_id]
            for page_id in page_ids
            if page_id in published_id_values
        }
        for source_url, page_ids in previous_resolution.published_ids_by_source_url.items()
    }

    topic_rows = await database.fetch_all(
        """
        SELECT
            put.published_url_id,
            ct.id AS topic_id,
            ct.topic_name
        FROM geo_published_url_topics put
        JOIN geo_client_topics ct
          ON ct.id = put.topic_id
         AND ct.client_id = put.client_id
        WHERE put.client_id = :client_id
          AND put.published_url_id = ANY(:published_ids::uuid[])
        """,
        {"client_id": client_id, "published_ids": published_ids},
    )
    topics_by_url: Dict[UUID, List[dict]] = defaultdict(list)
    for row in topic_rows:
        topics_by_url[row["published_url_id"]].append(
            {"id": row["topic_id"], "topic_name": row["topic_name"]}
        )
    triggered_topic_counts_by_url: Dict[UUID, Dict[tuple[str, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for row in triggered_topic_rows:
        for published_url_id in url_to_ids.get(row["source_url"], set()):
            topic_key = (str(row["topic_id"]), str(row["topic_name"] or ""))
            triggered_topic_counts_by_url[published_url_id][topic_key] += int(
                row["citation_count"] or 0
            )
    triggered_topics_by_url: Dict[UUID, List[dict]] = {
        published_url_id: [
            {
                "id": topic_id_value,
                "topic_name": topic_name,
                "citation_count": citation_count,
            }
            for (topic_id_value, topic_name), citation_count in sorted(
                topic_counts.items(),
                key=lambda item: (-item[1], item[0][1], item[0][0]),
            )
        ]
        for published_url_id, topic_counts in triggered_topic_counts_by_url.items()
    }

    current_by_url: Dict[UUID, dict] = defaultdict(
        lambda: {
            "citation_count": 0,
            "last_cited_at": None,
            "category_counts": defaultdict(int),
        }
    )
    for row in current_match_rows:
        citation_count = int(row["citation_count"] or 0)
        for published_url_id in url_to_ids.get(row["source_url"], set()):
            metrics = current_by_url[published_url_id]
            metrics["citation_count"] += citation_count
            last_cited = row["last_cited_at"]
            if last_cited and (
                metrics["last_cited_at"] is None or last_cited > metrics["last_cited_at"]
            ):
                metrics["last_cited_at"] = last_cited
            if row["domain_category"]:
                metrics["category_counts"][str(row["domain_category"])] += citation_count

    previous_by_url: Dict[UUID, int] = defaultdict(int)
    for row in previous_match_rows:
        citation_count = int(row["citation_count"] or 0)
        for published_url_id in previous_url_to_ids.get(row["source_url"], set()):
            previous_by_url[published_url_id] += citation_count

    all_items: List[PublishedUrlTrackingRow] = []
    has_citation_scope_filter = any(
        [topic_id, topic_ids, platform, country, prompt_type, products, prompt_id, prompt_ids]
    )
    for row in published_rows:
        current_metrics = current_by_url.get(row["id"], {})
        citation_count = int(current_metrics.get("citation_count") or 0)
        if has_citation_scope_filter and citation_count <= 0:
            continue
        previous_citation_count = previous_by_url.get(row["id"], 0)
        last_cited = current_metrics.get("last_cited_at")
        category_counts = current_metrics.get("category_counts") or {}
        citation_category = None
        if category_counts:
            citation_category = sorted(
                category_counts.items(), key=lambda item: (-item[1], item[0])
            )[0][0]
        share_pct = round(citation_count / total_citations * 100, 2) if total_citations else 0
        previous_share_pct = (
            round(previous_citation_count / prev_total_citations * 100, 2)
            if prev_total_citations else 0
        )
        all_items.append(
            PublishedUrlTrackingRow(
                rank=0,
                published_url_id=row["id"],
                title=row["title"],
                published_url=row["published_url"],
                normalized_url=row["normalized_url"],
                channel=row["channel"],
                publish_status=row["publish_status"],
                citation_category=citation_category,
                published_at=row["published_at"],
                citation_count=citation_count,
                share_pct=share_pct,
                previous_citation_count=previous_citation_count,
                change_count=citation_count - previous_citation_count,
                previous_share_pct=previous_share_pct,
                change_share_pct=round(share_pct - previous_share_pct, 2),
                last_cited_at=last_cited.isoformat() if last_cited else None,
                candidate_count=current_resolution.pending_count_by_published_id.get(str(row["id"]), 0),
                topics=topics_by_url.get(row["id"], []),
                triggered_topics=triggered_topics_by_url.get(row["id"], []),
            )
        )
    all_items.sort(key=lambda item: (-item.citation_count, item.published_url.lower()))
    for idx, item in enumerate(all_items, start=1):
        item.rank = idx
    all_items = sort_complete_rows(
        "published_url_tracking", all_items, resolved_sort.sort_by, resolved_sort.sort_order
    )
    items = all_items[offset:offset + limit]
    total_published = len(all_items)

    logger.info(
        "published_url_tracking_list client_id=%s total_published=%s total_citations=%s returned=%s elapsed_ms=%.1f",
        client_id,
        total_published,
        total_citations,
        len(items),
        (time.perf_counter() - started_at) * 1000,
    )
    return PublishedUrlTrackingOut(
        items=items,
        total=total_published,
        total_citations=total_citations,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/published-url-tracking/{published_url_id}/url-variants",
    response_model=PublishedUrlVariantsOut,
)
async def get_published_url_tracking_variants(
    published_url_id: UUID,
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
) -> PublishedUrlVariantsOut:
    _validate_target_filter_inputs(products, prompt_id, prompt_ids)
    citation_intent_names = await _resolve_citation_intent_names(prompt_type)
    citation_where, citation_params, _, _ = _build_filters(
        client_id, date_from, date_to, topic_id, topic_ids, platform, country,
        citation_intent_names,
        products, prompt_id, prompt_ids,
    )
    published = await database.fetch_one(
        """
        SELECT id, published_url, normalized_url
        FROM geo_published_urls
        WHERE client_id = :client_id
          AND id = :published_url_id
          AND is_active = TRUE
          AND publish_status = 'published'
        """,
        {"client_id": client_id, "published_url_id": published_url_id},
    )
    if not published:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Published URL not found")

    published_rows = [published]
    mapping_rows = await _load_url_match_mappings(client_id, [published_url_id])
    candidate_where, candidate_params = build_candidate_url_predicate(
        published_rows=published_rows,
        mapping_rows=mapping_rows,
        prefix="variant_candidate",
    )
    candidate_rows = await database.fetch_all(
        f"""
        SELECT
            c.source_url,
            COUNT(*) AS citation_count,
            MIN(c.executed_at) AS first_cited_at,
            MAX(c.executed_at) AS last_cited_at
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE {citation_where}
          AND {candidate_where}
        GROUP BY c.source_url
        """,
        {**citation_params, **candidate_params},
    ) if candidate_where != "FALSE" else []
    resolution = resolve_published_url_variants(
        published_rows=published_rows,
        citation_rows=candidate_rows,
        mapping_rows=mapping_rows,
    )
    source_metadata = {str(row["source_url"]): row for row in candidate_rows}
    status_order = {"pending": 0, "confirmed": 1, "automatic": 2, "exact": 3, "rejected": 4}
    variants: list[PublishedUrlVariantRow] = []
    for item in resolution.variants_by_published_id.get(str(published_url_id), []):
        metadata = source_metadata.get(item.source_url, {})
        first_cited_at = metadata.get("first_cited_at") if hasattr(metadata, "get") else None
        last_cited_at = metadata.get("last_cited_at") if hasattr(metadata, "get") else None
        variants.append(PublishedUrlVariantRow(
            source_url=item.source_url,
            match_key=item.match_key,
            status=item.status,
            citation_count=item.citation_count,
            first_cited_at=first_cited_at.isoformat() if first_cited_at else None,
            last_cited_at=last_cited_at.isoformat() if last_cited_at else None,
            included=item.status in {"exact", "automatic", "confirmed"},
        ))
    variants.sort(key=lambda item: (
        status_order.get(item.status, 99),
        -item.citation_count,
        item.source_url.lower(),
    ))
    return PublishedUrlVariantsOut(
        published_url_id=published_url_id,
        variants=variants,
        pending_count=resolution.pending_count_by_published_id.get(str(published_url_id), 0),
    )


@router.get("/published-url-tracking/{published_url_id}", response_model=PublishedUrlTrackingDetailOut)
async def get_published_url_tracking_detail(
    published_url_id: UUID,
    client_id: UUID,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    prompt_type: Optional[str] = None,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    prompt_limit: int = Query(10, ge=1, le=50),
    prompt_offset: int = Query(0, ge=0),
    response_limit: int = Query(10, ge=1, le=50),
    response_offset: int = Query(0, ge=0),
    response_platform: Optional[str] = None,
    response_country: Optional[str] = None,
    response_topic_id: Optional[str] = None,
    prompt_platform: Optional[str] = None,
    prompt_country: Optional[str] = None,
    prompt_topic_id: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    prompt_sort_by: Optional[str] = None,
    prompt_sort_order: Optional[str] = None,
    topic_sort_by: Optional[str] = None,
    topic_sort_order: Optional[str] = None,
    platform_sort_by: Optional[str] = None,
    platform_sort_order: Optional[str] = None,
    country_sort_by: Optional[str] = None,
    country_sort_order: Optional[str] = None,
) -> PublishedUrlTrackingDetailOut:
    effective_prompt_sort_by = prompt_sort_by if prompt_sort_by is not None else sort_by
    effective_prompt_sort_order = prompt_sort_order if prompt_sort_order is not None else sort_order
    effective_topic_sort_by = topic_sort_by
    effective_topic_sort_order = topic_sort_order
    effective_platform_sort_by = platform_sort_by
    effective_platform_sort_order = platform_sort_order
    effective_country_sort_by = country_sort_by
    effective_country_sort_order = country_sort_order
    resolved_prompt_sort = resolve_sort_or_422("published_url_prompts", effective_prompt_sort_by, effective_prompt_sort_order)
    resolved_topic_sort = resolve_sort_or_422("published_url_topics", effective_topic_sort_by, effective_topic_sort_order)
    resolved_platform_sort = resolve_sort_or_422("published_url_platforms", effective_platform_sort_by, effective_platform_sort_order)
    resolved_country_sort = resolve_sort_or_422("published_url_countries", effective_country_sort_by, effective_country_sort_order)
    started_at = time.perf_counter()
    _validate_target_filter_inputs(products, prompt_id, prompt_ids)
    citation_intent_names = await _resolve_citation_intent_names(prompt_type)
    citation_where, citation_params, start_date, end_date = _build_filters(
        client_id, date_from, date_to, topic_id, topic_ids, platform, country,
        citation_intent_names,
        products, prompt_id, prompt_ids,
    )
    published = await database.fetch_one(
        """
        SELECT
            id, title, published_url, normalized_url, channel, publish_status
        FROM geo_published_urls
        WHERE client_id = :client_id
          AND id = :published_url_id
        """,
        {"client_id": client_id, "published_url_id": published_url_id},
    )
    if not published:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Published URL not found")

    mapping_rows = await _load_url_match_mappings(client_id, [published_url_id])
    candidate_where, candidate_params = build_candidate_url_predicate(
        published_rows=[published],
        mapping_rows=mapping_rows,
        prefix="detail_candidate",
    )
    candidate_rows = await database.fetch_all(
        f"""
        SELECT
            c.source_url,
            COUNT(*) AS citation_count,
            MIN(c.executed_at) AS first_cited_at,
            MAX(c.executed_at) AS last_cited_at
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE {citation_where}
          AND {candidate_where}
        GROUP BY c.source_url
        """,
        {**citation_params, **candidate_params},
    ) if candidate_where != "FALSE" else []
    resolution = resolve_published_url_variants(
        published_rows=[published],
        citation_rows=candidate_rows,
        mapping_rows=mapping_rows,
    )
    matched_source_urls = sorted(
        resolution.matched_source_urls_by_published_id.get(str(published_url_id), set())
    )
    url_params = {
        **citation_params,
        "matched_source_urls": matched_source_urls,
    }
    match_where = f"""
        {citation_where}
        AND c.source_url = ANY(:matched_source_urls::text[])
    """
    response_where = match_where
    response_params = dict(url_params)
    prompt_where = match_where
    prompt_params = dict(url_params)
    if response_platform:
        response_where += " AND cp.platform = :response_platform"
        response_params["response_platform"] = response_platform
    if response_country:
        response_where += " AND cp.country = :response_country"
        response_params["response_country"] = response_country
    if response_topic_id:
        response_where += " AND cp.topic_id = :response_topic_id"
        response_params["response_topic_id"] = response_topic_id
    if prompt_platform:
        prompt_where += " AND cp.platform = :prompt_platform"
        prompt_params["prompt_platform"] = prompt_platform
    if prompt_country:
        prompt_where += " AND cp.country = :prompt_country"
        prompt_params["prompt_country"] = prompt_country
    if prompt_topic_id:
        prompt_where += " AND cp.topic_id = :prompt_topic_id"
        prompt_params["prompt_topic_id"] = prompt_topic_id

    local_day = local_date_expr("c.executed_at")
    metrics_rows = await database.fetch_all(
        f"""
        SELECT
            {local_day} AS citation_day,
            c.domain_category,
            cp.platform,
            cp.country,
            ct.id AS topic_id,
            ct.topic_name,
            COUNT(*) AS citation_count
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        LEFT JOIN geo_client_topics ct
          ON ct.id = cp.topic_id
         AND ct.client_id = cp.client_id
        WHERE {match_where}
        GROUP BY citation_day, c.domain_category, cp.platform, cp.country, ct.id, ct.topic_name
        """,
        url_params,
    )

    counts_by_day: Dict[date, int] = defaultdict(int)
    platforms: Dict[str, int] = defaultdict(int)
    countries: Dict[str, int] = defaultdict(int)
    topics: Dict[tuple[str, str], int] = defaultdict(int)
    categories: Dict[str, int] = defaultdict(int)
    total_matches = 0
    for row in metrics_rows:
        citation_count = int(row["citation_count"] or 0)
        total_matches += citation_count
        citation_day = row["citation_day"]
        if citation_day:
            counts_by_day[citation_day] += citation_count
        if row["platform"]:
            platforms[str(row["platform"])] += citation_count
        if row["country"]:
            countries[str(row["country"])] += citation_count
        if row["topic_id"]:
            topics[(str(row["topic_id"]), str(row["topic_name"] or ""))] += citation_count
        if row["domain_category"]:
            categories[str(row["domain_category"])] += citation_count

    prompt_total = await database.fetch_val(
        f"""
        SELECT COUNT(*) FROM (
            SELECT 1
            FROM geo_citations c
            JOIN geo_client_prompts cp
              ON cp.id = c.client_prompt_id
             AND cp.client_id = c.client_id
            WHERE {prompt_where}
            GROUP BY LOWER(BTRIM(cp.text)), cp.topic_id
        ) prompt_groups
        """,
        prompt_params,
    ) or 0

    prompt_rows = await database.fetch_all(
        f"""
        SELECT
            MIN(cp.id::text) AS client_prompt_id,
            MIN(cp.text) AS client_prompt_text,
            MIN(ct.topic_name) AS topic_name,
            ARRAY_AGG(DISTINCT cp.platform ORDER BY cp.platform)
                FILTER (WHERE cp.platform IS NOT NULL) AS platforms,
            ARRAY_AGG(DISTINCT cp.country ORDER BY cp.country)
                FILTER (WHERE cp.country IS NOT NULL) AS countries,
            COUNT(*) AS citation_count
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        LEFT JOIN geo_client_topics ct
          ON ct.id = cp.topic_id
         AND ct.client_id = cp.client_id
        WHERE {prompt_where}
        GROUP BY LOWER(BTRIM(cp.text)), cp.topic_id
        ORDER BY {resolved_prompt_sort.order_by_sql}
        LIMIT :prompt_limit OFFSET :prompt_offset
        """,
        {**prompt_params, "prompt_limit": prompt_limit, "prompt_offset": prompt_offset},
    )
    prompts = [
        PublishedUrlPromptRef(
            client_prompt_id=row["client_prompt_id"],
            client_prompt_text=row["client_prompt_text"],
            topic_name=row["topic_name"],
            platforms=list(row["platforms"] or []),
            countries=list(row["countries"] or []),
            citation_count=int(row["citation_count"] or 0),
        )
        for row in prompt_rows
    ]

    response_total = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE {response_where}
        """,
        response_params,
    ) or 0

    response_rows = await database.fetch_all(
        f"""
        SELECT
            c.result_id,
            c.task_id,
            c.source_position,
            c.source_label,
            c.executed_at,
            cp.text AS client_prompt_text,
            cp.platform,
            cp.country,
            gr.text AS response_text
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        LEFT JOIN geo_results gr
          ON gr.result_id = c.result_id
         AND gr.client_id = c.client_id
        WHERE {response_where}
        ORDER BY c.executed_at DESC NULLS LAST,
                 c.source_position ASC NULLS LAST,
                 c.result_id DESC
        LIMIT :response_limit OFFSET :response_offset
        """,
        {**response_params, "response_limit": response_limit, "response_offset": response_offset},
    )
    responses = []
    for row in response_rows:
        response_text = row["response_text"] or ""
        executed_at = row["executed_at"]
        responses.append(
            PublishedUrlResponseRef(
                result_id=row["result_id"],
                task_id=row["task_id"],
                client_prompt_text=row["client_prompt_text"],
                platform=row["platform"],
                country=row["country"],
                executed_at=executed_at.isoformat() if executed_at else None,
                source_position=row["source_position"],
                source_label=row["source_label"],
                response_excerpt=response_text[:500] if response_text else None,
            )
        )

    dominant_category = None
    if categories:
        dominant_category = sorted(categories.items(), key=lambda item: (-item[1], item[0]))[0][0]

    topic_items = [
            {"id": topic_id_value, "topic_name": topic_name, "citation_count": value}
            for (topic_id_value, topic_name), value in sorted(topics.items(), key=lambda item: (-item[1], item[0][1]))
    ]
    platform_items = [{"platform": key, "citation_count": value} for key, value in sorted(platforms.items())]
    country_items = [{"country": key, "citation_count": value} for key, value in sorted(countries.items())]
    if effective_topic_sort_by is not None or effective_topic_sort_order is not None:
        topic_items = sort_complete_rows("published_url_topics", topic_items, resolved_topic_sort.sort_by, resolved_topic_sort.sort_order)
    if effective_platform_sort_by is not None or effective_platform_sort_order is not None:
        platform_items = sort_complete_rows("published_url_platforms", platform_items, resolved_platform_sort.sort_by, resolved_platform_sort.sort_order)
    if effective_country_sort_by is not None or effective_country_sort_order is not None:
        country_items = sort_complete_rows("published_url_countries", country_items, resolved_country_sort.sort_by, resolved_country_sort.sort_order)

    result = PublishedUrlTrackingDetailOut(
        published_url_id=published["id"],
        title=published["title"],
        published_url=published["published_url"],
        normalized_url=published["normalized_url"],
        channel=published["channel"],
        publish_status=published["publish_status"],
        citation_category=dominant_category,
        trend_7d=_date_series(max(start_date, end_date - timedelta(days=6)), end_date, counts_by_day),
        trend_14d=_date_series(max(start_date, end_date - timedelta(days=13)), end_date, counts_by_day),
        trend_30d=_date_series(max(start_date, end_date - timedelta(days=29)), end_date, counts_by_day),
        topics=topic_items,
        platforms=platform_items,
        countries=country_items,
        prompts=prompts,
        prompts_total=int(prompt_total),
        prompt_limit=prompt_limit,
        prompt_offset=prompt_offset,
        responses=responses,
        responses_total=int(response_total),
        response_limit=response_limit,
        response_offset=response_offset,
    )
    logger.info(
        "published_url_tracking_detail client_id=%s published_url_id=%s matches=%s prompts=%s/%s responses=%s/%s elapsed_ms=%.1f",
        client_id,
        published_url_id,
        total_matches,
        len(prompts),
        prompt_total,
        len(responses),
        response_total,
        (time.perf_counter() - started_at) * 1000,
    )
    return result
