"""
Product-level visibility — SOV and time-series at the product level.

v1.2 (Spec §7.2 ``product_sov_own``): SOV is computed over
``geo_product_mentions`` filtered by ``product_role``. The endpoint accepts a
``product_role`` query param so the UI can surface three panels:

- ``product_role='own'``           → own-product SOV (default)
- ``product_role='shadow_brand_product'`` → shadow-brand products SOV
- ``product_role='peer'``          → peer-ecosystem products SOV

Empty-state behaviour: returns ``{"data": [], "reason": "no_data"}`` so the
frontend renders a friendly EmptyStateCard instead of guessing at an error.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import database

from ._helpers import (
    SHANGHAI_TZ,
    apply_common_filters,
    date_bucket_expr,
    date_range_filter_expr,
    iter_date_strings,
    parse_date_range,
    parse_multi_value,
)
from .sorting import resolve_sort_or_422, sort_complete_rows

router = APIRouter()


class ProductVisibilityRow(BaseModel):
    product_name: Optional[str] = None
    owner_brand_name: Optional[str] = None
    owner_peer_name: Optional[str] = None
    shadow_sub_role: Optional[str] = None
    mention_count: int
    response_count: int
    visibility_pct: float
    sov_pct: float
    avg_position: Optional[float] = None


class ProductVisibilityTimePoint(BaseModel):
    date: str
    total: int
    total_responses: int
    mentioned_responses: int
    visibility_score: float


class ProductVisibilitySummary(BaseModel):
    product_role: str
    total_mentions: int
    total_responses: int
    mentioned_responses: int
    visibility_score: float
    unique_products: int


class ProductVisibilityFilters(BaseModel):
    date_from: str
    date_to: str
    interval: str


class ProductVisibilityOut(BaseModel):
    """Branches: invalid_product_role, no_data, or full payload."""

    data: List[ProductVisibilityRow] = []
    reason: Optional[str] = None
    allowed: Optional[List[str]] = None
    summary: Optional[ProductVisibilitySummary] = None
    ranking: Optional[List[ProductVisibilityRow]] = None
    time_series: Optional[List[ProductVisibilityTimePoint]] = None
    filters: Optional[ProductVisibilityFilters] = None


_VALID_ROLES = {"own", "shadow_brand_product", "peer"}


def _product_identity(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("product_name") or ""),
        str(row.get("owner_brand_name") or ""),
        str(row.get("owner_peer_name") or ""),
        str(row.get("shadow_sub_role") or ""),
    )


async def _has_active_shadow_brand(client_id: UUID) -> bool:
    row = await database.fetch_one(
        """
        SELECT EXISTS (
            SELECT 1
            FROM geo_client_brands
            WHERE client_id = :client_id
              AND is_shadow = TRUE
              AND is_active = TRUE
        ) AS has_shadow_brand
        """,
        {"client_id": client_id},
    )
    return bool(row and row["has_shadow_brand"])


async def _configured_own_products(
    *,
    client_id: UUID,
    topic_id: Optional[str],
    topic_ids: Optional[str],
    prompt_id: Optional[str],
) -> list[dict]:
    where_parts = [
        "p.client_id = :client_id",
        "p.product_role = 'own'",
        "p.is_active = TRUE",
    ]
    params: dict = {"client_id": client_id}
    if topic_id:
        where_parts.append("p.topic_id = :configured_topic_id")
        params["configured_topic_id"] = topic_id
    if topic_ids:
        parsed_topic_ids = parse_multi_value(topic_ids)
        if parsed_topic_ids:
            placeholders = ", ".join(
                f":configured_topic_{index}" for index in range(len(parsed_topic_ids))
            )
            where_parts.append(f"p.topic_id IN ({placeholders})")
            for index, value in enumerate(parsed_topic_ids):
                params[f"configured_topic_{index}"] = value
    if prompt_id:
        where_parts.append(
            "p.topic_id = ("
            "SELECT selected.topic_id FROM geo_client_prompts selected "
            "WHERE selected.id = :configured_prompt_id "
            "AND selected.client_id = :client_id"
            ")"
        )
        params["configured_prompt_id"] = prompt_id

    rows = await database.fetch_all(
        f"""
        SELECT DISTINCT
            p.product_name,
            owner_brand.brand_name AS owner_brand_name,
            owner_peer.primary_name AS owner_peer_name,
            p.shadow_sub_role
        FROM geo_client_topic_products p
        LEFT JOIN geo_client_brands owner_brand ON owner_brand.id = p.owner_brand_id
        LEFT JOIN geo_client_peers owner_peer ON owner_peer.id = p.owner_peer_id
        WHERE {" AND ".join(where_parts)}
        """,
        params,
    )
    return [dict(row) for row in rows]


@router.get("/product-visibility", response_model=ProductVisibilityOut)
async def get_product_visibility(
    client_id: UUID,
    product_role: str = Query("own", description="'own' | 'shadow_brand_product' | 'peer'"),
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    prompt_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> ProductVisibilityOut:
    resolved_sort = resolve_sort_or_422("product_visibility", sort_by, sort_order)
    role = (product_role or "own").strip()
    if role not in _VALID_ROLES:
        return ProductVisibilityOut(
            data=[],
            reason="invalid_product_role",
            allowed=sorted(_VALID_ROLES),
        )

    start_date, end_date = parse_date_range(date_from, date_to)

    mention_where_parts = [
        "pm.client_id = :client_id",
        "pm.product_role = :role",
        date_range_filter_expr("pm.executed_at", "start_date", "end_date"),
    ]
    response_where_parts = [
        "gr.client_id = :client_id",
        date_range_filter_expr("gr.ingested_at", "start_date", "end_date"),
    ]
    params: dict = {
        "client_id": client_id,
        "role": role,
        "start_date": start_date,
        "end_date": end_date,
    }
    apply_common_filters(
        mention_where_parts, params,
        cp_alias="cp", mention_alias="pm",
        topic_id=topic_id, topic_ids=topic_ids, platform=platform,
        country=country, product=None, prompt_id=prompt_id,
    )
    apply_common_filters(
        response_where_parts, params,
        cp_alias="cp", mention_alias="gr",
        topic_id=topic_id, topic_ids=topic_ids, platform=platform,
        country=country, product=None, prompt_id=prompt_id,
    )

    visibility_intent_rows = await database.fetch_all(
        """
        SELECT intent_name
        FROM geo_global_intents
        WHERE is_active = TRUE
          AND categories @> '["Visibility"]'::jsonb
        """
    )
    visibility_intents = [row["intent_name"] for row in visibility_intent_rows]
    if visibility_intents:
        placeholders = ", ".join(
            f":visibility_intent_{index}" for index in range(len(visibility_intents))
        )
        mention_where_parts.append(f"cp.intent IN ({placeholders})")
        response_where_parts.append(f"cp.intent IN ({placeholders})")
        for index, intent_name in enumerate(visibility_intents):
            params[f"visibility_intent_{index}"] = intent_name
    else:
        mention_where_parts.append("1 = 0")
        response_where_parts.append("1 = 0")

    mention_where_sql = " AND ".join(mention_where_parts)
    response_where_sql = " AND ".join(response_where_parts)

    coverage_row = await database.fetch_one(
        f"""
        SELECT
            COUNT(DISTINCT gr.result_id) AS total_responses,
            COUNT(DISTINCT CASE WHEN pm.result_id IS NOT NULL THEN gr.result_id END)
                AS mentioned_responses
        FROM geo_results gr
        JOIN geo_client_prompts cp
          ON cp.id = gr.client_prompt_id
         AND cp.client_id = gr.client_id
        LEFT JOIN geo_product_mentions pm
          ON pm.result_id = gr.result_id
         AND pm.client_id = gr.client_id
         AND pm.product_role = :role
        WHERE {response_where_sql}
        """,
        params,
    )
    total_responses = int(coverage_row["total_responses"] or 0) if coverage_row else 0
    mentioned_responses = int(coverage_row["mentioned_responses"] or 0) if coverage_row else 0
    visibility_score = (
        round(mentioned_responses / total_responses * 100, 2)
        if total_responses > 0
        else 0
    )

    # Product visibility is response-level coverage. Product SOV remains
    # mention-volume share, so the two metrics answer different questions.
    rows = await database.fetch_all(
        f"""
        SELECT
            pm.product_name,
            pm.owner_brand_name,
            pm.owner_peer_name,
            pm.shadow_sub_role,
            COUNT(*) AS mention_count,
            COUNT(DISTINCT pm.result_id) AS response_count,
            AVG(pm.mention_position) AS avg_position
        FROM geo_product_mentions pm
        JOIN geo_client_prompts cp ON cp.id = pm.client_prompt_id
        WHERE {mention_where_sql}
        GROUP BY pm.product_name, pm.owner_brand_name, pm.owner_peer_name, pm.shadow_sub_role
        ORDER BY COUNT(*) DESC
        """,
        params,
    )

    total_mentions = sum(r["mention_count"] for r in rows)
    ranking = []
    for r in rows:
        sov_pct = round((r["mention_count"] / total_mentions * 100), 2) if total_mentions > 0 else 0
        response_count = int(r["response_count"] or 0)
        visibility_pct = (
            round(response_count / total_responses * 100, 2)
            if total_responses > 0
            else 0
        )
        ranking.append({
            "product_name": r["product_name"],
            "owner_brand_name": r["owner_brand_name"],
            "owner_peer_name": r["owner_peer_name"],
            "shadow_sub_role": r["shadow_sub_role"],
            "mention_count": r["mention_count"],
            "response_count": response_count,
            "visibility_pct": visibility_pct,
            "sov_pct": sov_pct,
            "avg_position": round(float(r["avg_position"]), 2) if r["avg_position"] else None,
        })

    # Configured zero rows are a dealer-mode affordance only. Standard
    # workspaces preserve the historic fact-driven list behavior.
    is_shadow_workspace = role == "own" and await _has_active_shadow_brand(client_id)
    if is_shadow_workspace:
        configured_products = await _configured_own_products(
            client_id=client_id,
            topic_id=topic_id,
            topic_ids=topic_ids,
            prompt_id=prompt_id,
        )
        existing = {_product_identity(row) for row in ranking}
        for configured in configured_products:
            identity = _product_identity(configured)
            if identity in existing:
                continue
            existing.add(identity)
            ranking.append({
                "product_name": configured.get("product_name"),
                "owner_brand_name": configured.get("owner_brand_name"),
                "owner_peer_name": configured.get("owner_peer_name"),
                "shadow_sub_role": configured.get("shadow_sub_role"),
                "mention_count": 0,
                "response_count": 0,
                "visibility_pct": 0,
                "sov_pct": 0,
                "avg_position": None,
            })
    ranking = sort_complete_rows(
        "product_visibility", ranking, resolved_sort.sort_by, resolved_sort.sort_order
    )

    # Response-level coverage trend, bucketed in the business timezone.
    bucket_sql = date_bucket_expr("gr.ingested_at", interval, timezone=SHANGHAI_TZ)
    ts_rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_sql} AS bucket,
            COUNT(pm.id) AS total,
            COUNT(DISTINCT gr.result_id) AS total_responses,
            COUNT(DISTINCT CASE WHEN pm.result_id IS NOT NULL THEN gr.result_id END)
                AS mentioned_responses
        FROM geo_results gr
        JOIN geo_client_prompts cp
          ON cp.id = gr.client_prompt_id
         AND cp.client_id = gr.client_id
        LEFT JOIN geo_product_mentions pm
          ON pm.result_id = gr.result_id
         AND pm.client_id = gr.client_id
         AND pm.product_role = :role
        WHERE {response_where_sql}
        GROUP BY {bucket_sql}
        ORDER BY {bucket_sql}
        """,
        params,
    )
    time_series = [
        {
            "date": r["bucket"].isoformat() if hasattr(r["bucket"], "isoformat") else str(r["bucket"]),
            "total": int(r["total"] or 0),
            "total_responses": int(r["total_responses"] or 0),
            "mentioned_responses": int(r["mentioned_responses"] or 0),
            "visibility_score": (
                round(int(r["mentioned_responses"] or 0) / int(r["total_responses"] or 0) * 100, 2)
                if int(r["total_responses"] or 0) > 0
                else 0
            ),
        }
        for r in ts_rows
    ]
    if is_shadow_workspace and ranking and interval == "daily":
        totals_by_date = {point["date"]: point for point in time_series}
        time_series = [
            totals_by_date.get(day, {
                "date": day,
                "total": 0,
                "total_responses": 0,
                "mentioned_responses": 0,
                "visibility_score": 0,
            })
            for day in iter_date_strings(start_date, end_date)
        ]

    if not ranking:
        return ProductVisibilityOut(data=[], reason="no_data")

    return ProductVisibilityOut(
        summary=ProductVisibilitySummary(
            product_role=role,
            total_mentions=total_mentions,
            total_responses=total_responses,
            mentioned_responses=mentioned_responses,
            visibility_score=visibility_score,
            unique_products=len(ranking),
        ),
        ranking=[ProductVisibilityRow(**r) for r in ranking],
        time_series=[ProductVisibilityTimePoint(**p) for p in time_series],
        filters=ProductVisibilityFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            interval=interval,
        ),
    )
