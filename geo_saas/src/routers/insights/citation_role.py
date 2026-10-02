"""
Citation breakdown by ``citation_role`` (Spec §7.2 ``citation_by_citation_role``).

Returns the count and share of each citation_role bucket within the client's
recent citation data. ``citation_role`` is NULL for legacy rows — those are
surfaced under ``role = 'unclassified'`` so callers can see the tail.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from db import database

from ._helpers import parse_date_range

router = APIRouter()


class CitationByRoleRow(BaseModel):
    citation_role: str
    citation_count: int
    share_pct: float


class CitationByRoleFilters(BaseModel):
    date_from: str
    date_to: str


class CitationByRoleOut(BaseModel):
    """Two shapes: empty-data branch returns ``{data: [], reason: "no_data"}``;
    populated branch returns ``{total_citations, data, filters}``. The model
    keeps the union explicit so both paths validate."""

    data: List[CitationByRoleRow] = []
    reason: Optional[str] = None
    total_citations: Optional[int] = None
    filters: Optional[CitationByRoleFilters] = None


@router.get("/citation-by-role", response_model=CitationByRoleOut)
async def citation_by_role(
    client_id: UUID,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> CitationByRoleOut:
    start_date, end_date = parse_date_range(date_from, date_to)

    # Consistency fix (2026-04-20): Exclude orphan citations whose result_id
    # points to a deleted geo_results row. Without this, /citation-by-role
    # reports seed-data leftovers (e.g. 5604 unclassified rows whose parent
    # geo_results were replaced by a re-ingest) while the Agent pipeline
    # (which adds a platform EXISTS filter on geo_results) correctly drops
    # them — the two surfaces showed inconsistent totals for the same customer.
    rows = await database.fetch_all(
        """
        SELECT
            COALESCE(c.citation_role, 'unclassified') AS citation_role,
            COUNT(*) AS citation_count
        FROM geo_citations c
        WHERE c.client_id = :client_id
          AND c.executed_at::date >= :start_date
          AND c.executed_at::date <= :end_date
          AND EXISTS (
              SELECT 1 FROM geo_results r
              WHERE r.result_id = c.result_id
                AND r.client_id = c.client_id
          )
        GROUP BY COALESCE(c.citation_role, 'unclassified')
        ORDER BY COUNT(*) DESC
        """,
        {
            "client_id": client_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    )

    if not rows:
        return CitationByRoleOut(data=[], reason="no_data")

    total = sum(r["citation_count"] for r in rows) or 0
    data = []
    for r in rows:
        pct = round((r["citation_count"] / total * 100), 2) if total > 0 else 0
        data.append(CitationByRoleRow(
            citation_role=r["citation_role"],
            citation_count=r["citation_count"],
            share_pct=pct,
        ))

    return CitationByRoleOut(
        total_citations=total,
        data=data,
        filters=CitationByRoleFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        ),
    )
