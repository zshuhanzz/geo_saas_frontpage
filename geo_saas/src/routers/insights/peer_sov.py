"""
Peer SOV (via peers-list membership, correctness fix per Spec §7.3).

The legacy metric used ``brand_role='peer'`` as the Peer filter. In v1.2 this
misses brands that live in the ``geo_client_brands`` table as Shadow rows
AND in ``geo_client_peers`` as Peer rows simultaneously (Roborock competitor
RC is the concrete example).

The correct definition is "brand_name matches any row in
``geo_client_peers`` for this tenant (primary_name OR aliases)". This
endpoint implements that membership test via ``EXISTS`` — see the inline
subquery below.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from db import database

from ._helpers import parse_date_range

router = APIRouter()


class PeerSovRow(BaseModel):
    brand_name: Optional[str] = None
    mention_count: int
    sov_pct: float
    avg_position: Optional[float] = None


class PeerSovFilters(BaseModel):
    date_from: str
    date_to: str


class PeerSovOut(BaseModel):
    """Empty branch: ``{data: [], reason: "no_data"}``. Populated branch:
    ``{total_mentions, data, filters}``."""

    data: List[PeerSovRow] = []
    reason: Optional[str] = None
    total_mentions: Optional[int] = None
    filters: Optional[PeerSovFilters] = None


@router.get("/peer-sov-via-list", response_model=PeerSovOut)
async def peer_sov_via_list(
    client_id: UUID,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> PeerSovOut:
    start_date, end_date = parse_date_range(date_from, date_to)

    # Two EXISTS filters baked in:
    #   1) ``peer_membership`` — brand_name matches a peers-list row
    #      (primary_name or aliases). Spec §7.3 correctness fix.
    #   2) ``prompt_still_active`` — drops orphan mentions whose
    #      client_prompt_id was deactivated or deleted (consistency fix
    #      against /visibility's INNER JOIN behaviour, 2026-04-20).
    rows = await database.fetch_all(
        """
        SELECT
            bm.brand_name,
            COUNT(*) AS mention_count,
            AVG(bm.mention_position) AS avg_position
        FROM geo_brand_mentions bm
        WHERE bm.client_id = :client_id
          AND bm.executed_at::date >= :start_date
          AND bm.executed_at::date <= :end_date
          AND EXISTS (
              SELECT 1 FROM geo_client_peers p
              WHERE p.client_id = bm.client_id
                AND (
                    p.primary_name ILIKE bm.brand_name
                    OR bm.brand_name = ANY(p.aliases)
                )
          )
          AND EXISTS (
              SELECT 1 FROM geo_client_prompts cp
              WHERE cp.id = bm.client_prompt_id
                AND cp.is_active = TRUE
          )
        GROUP BY bm.brand_name
        ORDER BY COUNT(*) DESC
        LIMIT 50
        """,
        {
            "client_id": client_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    if not rows:
        return PeerSovOut(data=[], reason="no_data")

    total = sum(r["mention_count"] for r in rows) or 0
    data: List[PeerSovRow] = []
    for r in rows:
        pct = round((r["mention_count"] / total * 100), 2) if total > 0 else 0
        data.append(PeerSovRow(
            brand_name=r["brand_name"],
            mention_count=r["mention_count"],
            sov_pct=pct,
            avg_position=round(float(r["avg_position"]), 1) if r["avg_position"] else None,
        ))

    return PeerSovOut(
        total_mentions=total,
        data=data,
        filters=PeerSovFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        ),
    )
