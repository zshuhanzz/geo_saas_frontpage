"""
Shadow × product co-occurrence analytics (Spec §7.2 metrics
``shadow_cooccurrence_own_product`` and ``shadow_cooccurrence_peer_product``).

Two endpoints:

- ``GET /api/insights/shadow-product-cooccurrence`` — for each Shadow brand
  mention, count co-occurring Own product mentions in the same ``result_id``.
  Answers诉求 3: "when the model mentions my OEM channel, is it also
  mentioning my product?".

- ``GET /api/insights/shadow-peer-product-cooccurrence`` — same idea but
  counts co-occurring Shadow-brand-level products (``product_role =
  'shadow_brand_product'``). Answers 诉求 4: "which competing SKUs are being
  recommended on the same channels?".

Both endpoints scope all queries by ``client_id`` and return a friendly
``{"data": [], "reason": "no_data"}`` when no rows match (no shadow brand
configured / no data yet).
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from db import database

from ._helpers import local_date_expr, parse_date_range

router = APIRouter()


async def _empty_reason(
    client_id: UUID,
    *,
    dimension: str,
    start_date,
    end_date,
) -> str:
    row = await database.fetch_one(
        f"""
        SELECT
            EXISTS (
                SELECT 1 FROM geo_client_brands
                WHERE client_id = :client_id
                  AND is_shadow = TRUE
                  AND is_active = TRUE
            ) AS has_shadow_brand,
            EXISTS (
                SELECT 1 FROM geo_client_brands
                WHERE client_id = :client_id
                  AND is_shadow = FALSE
                  AND is_active = TRUE
            ) AS has_own_brand,
            EXISTS (
                SELECT 1 FROM geo_client_topic_products
                WHERE client_id = :client_id
                  AND product_role = 'own'
                  AND is_active = TRUE
            ) AS has_own_product,
            EXISTS (
                SELECT 1 FROM geo_client_topics
                WHERE client_id = :client_id
            ) AS has_topic,
            EXISTS (
                SELECT 1
                FROM geo_product_mentions pm
                JOIN geo_client_prompts cp
                  ON cp.id = pm.client_prompt_id
                 AND cp.client_id = pm.client_id
                WHERE pm.client_id = :client_id
                  AND pm.product_role = 'own'
                  AND cp.is_active = TRUE
                  AND {local_date_expr("pm.executed_at")} >= :start_date
                  AND {local_date_expr("pm.executed_at")} <= :end_date
            ) AS has_product_mentions
        """,
        {"client_id": client_id, "start_date": start_date, "end_date": end_date},
    )
    flags = dict(row or {})
    if not flags.get("has_shadow_brand"):
        return "missing_shadow_brand_configuration"
    if dimension == "product":
        if not flags.get("has_own_product"):
            return "missing_own_product_configuration"
        if not flags.get("has_product_mentions"):
            return "no_analyzed_product_mentions"
    elif dimension == "brand" and not flags.get("has_own_brand"):
        return "missing_own_brand_configuration"
    elif dimension == "topic" and not flags.get("has_topic"):
        return "missing_topic_configuration"
    return "no_cooccurrence"


# ─── Output models ─────────────────────────────────────────────────────────


class _CooccurrenceFilters(BaseModel):
    date_from: str
    date_to: str


class ShadowProductCooccurrenceRow(BaseModel):
    shadow_brand_name: Optional[str] = None
    own_product_name: Optional[str] = None
    cooccurrence_count: int


class ShadowProductCooccurrenceOut(BaseModel):
    data: List[ShadowProductCooccurrenceRow] = []
    reason: Optional[str] = None
    filters: Optional[_CooccurrenceFilters] = None


class ShadowPeerProductRow(BaseModel):
    shadow_brand_name: Optional[str] = None
    product_name: Optional[str] = None
    owner_brand_name: Optional[str] = None
    shadow_sub_role: Optional[str] = None
    cooccurrence_count: int


class ShadowPeerProductOut(BaseModel):
    data: List[ShadowPeerProductRow] = []
    reason: Optional[str] = None
    filters: Optional[_CooccurrenceFilters] = None


class ShadowBrandCooccurrenceRow(BaseModel):
    shadow_brand_name: Optional[str] = None
    own_brand_name: Optional[str] = None
    cooccurrence_count: int


class ShadowBrandCooccurrenceOut(BaseModel):
    data: List[ShadowBrandCooccurrenceRow] = []
    reason: Optional[str] = None
    filters: Optional[_CooccurrenceFilters] = None


class ShadowTopicCooccurrenceRow(BaseModel):
    shadow_brand_name: Optional[str] = None
    topic_name: Optional[str] = None
    cooccurrence_count: int


class ShadowTopicCooccurrenceOut(BaseModel):
    data: List[ShadowTopicCooccurrenceRow] = []
    reason: Optional[str] = None
    filters: Optional[_CooccurrenceFilters] = None


@router.get("/shadow-product-cooccurrence", response_model=ShadowProductCooccurrenceOut)
async def shadow_product_cooccurrence(
    client_id: UUID,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> ShadowProductCooccurrenceOut:
    """Co-occurrence of Shadow brand × Own product within the same result.

    Implemented as a self-join on ``result_id`` inside the tenant scope:
        brand_mentions (brand_role='shadow')  ⨝  product_mentions (product_role='own')

    Returns a matrix [shadow_brand_name × own_product_name → count].
    """
    start_date, end_date = parse_date_range(date_from, date_to)

    rows = await database.fetch_all(
        f"""
        SELECT
            bm.brand_name AS shadow_brand_name,
            pm.product_name AS own_product_name,
            COUNT(DISTINCT bm.result_id) AS cooccurrence_count
        FROM geo_brand_mentions bm
        JOIN geo_product_mentions pm
          ON bm.result_id = pm.result_id
         AND bm.client_id = pm.client_id
        WHERE bm.client_id = :client_id
          AND bm.brand_role = 'shadow'
          AND pm.product_role = 'own'
          AND {local_date_expr("bm.executed_at")} >= :start_date
          AND {local_date_expr("bm.executed_at")} <= :end_date
        GROUP BY bm.brand_name, pm.product_name
        ORDER BY COUNT(DISTINCT bm.result_id) DESC
        LIMIT 200
        """,
        {"client_id": client_id, "start_date": start_date, "end_date": end_date},
    )
    if not rows:
        return ShadowProductCooccurrenceOut(
            data=[],
            reason=await _empty_reason(
                client_id,
                dimension="product",
                start_date=start_date,
                end_date=end_date,
            ),
        )

    return ShadowProductCooccurrenceOut(
        data=[
            ShadowProductCooccurrenceRow(
                shadow_brand_name=r["shadow_brand_name"],
                own_product_name=r["own_product_name"],
                cooccurrence_count=r["cooccurrence_count"],
            )
            for r in rows
        ],
        filters=_CooccurrenceFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        ),
    )


@router.get("/shadow-peer-product-cooccurrence", response_model=ShadowPeerProductOut)
async def shadow_peer_product_cooccurrence(
    client_id: UUID,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> ShadowPeerProductOut:
    """Co-occurrence of Shadow brand × Shadow-brand-level products."""
    start_date, end_date = parse_date_range(date_from, date_to)

    rows = await database.fetch_all(
        f"""
        SELECT
            bm.brand_name AS shadow_brand_name,
            pm.product_name AS product_name,
            pm.owner_brand_name AS owner_brand_name,
            pm.shadow_sub_role AS shadow_sub_role,
            COUNT(DISTINCT bm.result_id) AS cooccurrence_count
        FROM geo_brand_mentions bm
        JOIN geo_product_mentions pm
          ON bm.result_id = pm.result_id
         AND bm.client_id = pm.client_id
        WHERE bm.client_id = :client_id
          AND bm.brand_role = 'shadow'
          AND pm.product_role = 'shadow_brand_product'
          AND {local_date_expr("bm.executed_at")} >= :start_date
          AND {local_date_expr("bm.executed_at")} <= :end_date
        GROUP BY bm.brand_name, pm.product_name, pm.owner_brand_name, pm.shadow_sub_role
        ORDER BY COUNT(DISTINCT bm.result_id) DESC
        LIMIT 200
        """,
        {"client_id": client_id, "start_date": start_date, "end_date": end_date},
    )
    if not rows:
        return ShadowPeerProductOut(data=[], reason="no_data")

    return ShadowPeerProductOut(
        data=[
            ShadowPeerProductRow(
                shadow_brand_name=r["shadow_brand_name"],
                product_name=r["product_name"],
                owner_brand_name=r["owner_brand_name"],
                shadow_sub_role=r["shadow_sub_role"],
                cooccurrence_count=r["cooccurrence_count"],
            )
            for r in rows
        ],
        filters=_CooccurrenceFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        ),
    )


@router.get("/shadow-brand-cooccurrence", response_model=ShadowBrandCooccurrenceOut)
async def shadow_brand_cooccurrence(
    client_id: UUID,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> ShadowBrandCooccurrenceOut:
    """Co-occurrence of Shadow brand × Own brand within the same result."""
    start_date, end_date = parse_date_range(date_from, date_to)

    rows = await database.fetch_all(
        f"""
        SELECT
            sbm.brand_name AS shadow_brand_name,
            obm.brand_name AS own_brand_name,
            COUNT(DISTINCT sbm.result_id) AS cooccurrence_count
        FROM geo_brand_mentions sbm
        JOIN geo_brand_mentions obm
          ON sbm.result_id = obm.result_id
         AND sbm.client_id = obm.client_id
        WHERE sbm.client_id = :client_id
          AND sbm.brand_role = 'shadow'
          AND obm.brand_role = 'own'
          AND {local_date_expr("sbm.executed_at")} >= :start_date
          AND {local_date_expr("sbm.executed_at")} <= :end_date
        GROUP BY sbm.brand_name, obm.brand_name
        ORDER BY COUNT(DISTINCT sbm.result_id) DESC
        LIMIT 200
        """,
        {"client_id": client_id, "start_date": start_date, "end_date": end_date},
    )
    if not rows:
        return ShadowBrandCooccurrenceOut(
            data=[],
            reason=await _empty_reason(
                client_id,
                dimension="brand",
                start_date=start_date,
                end_date=end_date,
            ),
        )

    return ShadowBrandCooccurrenceOut(
        data=[
            ShadowBrandCooccurrenceRow(
                shadow_brand_name=r["shadow_brand_name"],
                own_brand_name=r["own_brand_name"],
                cooccurrence_count=r["cooccurrence_count"],
            )
            for r in rows
        ],
        filters=_CooccurrenceFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        ),
    )


@router.get("/shadow-topic-cooccurrence", response_model=ShadowTopicCooccurrenceOut)
async def shadow_topic_cooccurrence(
    client_id: UUID,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> ShadowTopicCooccurrenceOut:
    """Distribution of Shadow brand mentions across topics."""
    start_date, end_date = parse_date_range(date_from, date_to)

    rows = await database.fetch_all(
        f"""
        SELECT
            bm.brand_name AS shadow_brand_name,
            ct.topic_name AS topic_name,
            COUNT(*) AS cooccurrence_count
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp ON cp.id = bm.client_prompt_id
        JOIN geo_client_topics ct ON ct.id = cp.topic_id
        WHERE bm.client_id = :client_id
          AND bm.brand_role = 'shadow'
          AND cp.topic_id IS NOT NULL
          AND {local_date_expr("bm.executed_at")} >= :start_date
          AND {local_date_expr("bm.executed_at")} <= :end_date
        GROUP BY bm.brand_name, ct.topic_name
        ORDER BY COUNT(*) DESC
        LIMIT 200
        """,
        {"client_id": client_id, "start_date": start_date, "end_date": end_date},
    )
    if not rows:
        return ShadowTopicCooccurrenceOut(
            data=[],
            reason=await _empty_reason(
                client_id,
                dimension="topic",
                start_date=start_date,
                end_date=end_date,
            ),
        )

    return ShadowTopicCooccurrenceOut(
        data=[
            ShadowTopicCooccurrenceRow(
                shadow_brand_name=r["shadow_brand_name"],
                topic_name=r["topic_name"],
                cooccurrence_count=r["cooccurrence_count"],
            )
            for r in rows
        ],
        filters=_CooccurrenceFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        ),
    )
