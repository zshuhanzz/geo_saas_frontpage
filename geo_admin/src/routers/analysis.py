"""
Analysis Router (v1.2 SaaS) - Query geo_brand_mentions and geo_citations.

v1.2 dual-mode tracking: geo_company_mentions renamed to geo_brand_mentions
(column rename: company_name → brand_name; column drop: is_own_brand;
column add: brand_role ('own' | 'shadow' | 'peer')). Uses client_id and
joins with geo_client_prompts to filter by topic, platform, and country.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import database

router = APIRouter(prefix="/analysis", tags=["Analysis"])


# ─── Pydantic models ───────────────────────────────────────────────────────


class AnalysisStatusOut(BaseModel):
    client_id: str
    topic_id: Optional[str] = None
    total_results: int
    analyzed_results: int
    pending_results: int
    can_analyze: bool


class PaginationOut(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class BrandMentionRow(BaseModel):
    id: str
    client_prompt_id: str
    task_id: Optional[str] = None
    result_id: Optional[int] = None
    client_id: str
    brand_name: Optional[str] = None
    brand_role: Optional[str] = None
    mention_position: Optional[int] = None
    executed_at: Optional[str] = None
    created_at: Optional[str] = None
    client_prompt_text: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None


class BrandMentionListOut(BaseModel):
    data: list[BrandMentionRow]
    pagination: PaginationOut


class CitationRow(BaseModel):
    id: str
    client_prompt_id: str
    task_id: Optional[str] = None
    result_id: Optional[int] = None
    client_id: str
    source_url: Optional[str] = None
    source_domain: Optional[str] = None
    source_position: Optional[int] = None
    source_label: Optional[str] = None
    is_citation_pill: Optional[bool] = None
    domain_category: Optional[str] = None
    citation_role: Optional[str] = None
    matched_brand_id: Optional[str] = None
    matched_product_id: Optional[str] = None
    matched_peer_id: Optional[str] = None
    executed_at: Optional[str] = None
    created_at: Optional[str] = None
    client_prompt_text: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None


class CitationListOut(BaseModel):
    data: list[CitationRow]
    pagination: PaginationOut


@router.get("/status/{client_id}", response_model=AnalysisStatusOut)
async def get_analysis_status(
    client_id: UUID, topic_id: Optional[UUID] = None
) -> AnalysisStatusOut:
    """Get analysis status for a client. Returns total / analyzed / pending."""
    where_parts = ["client_id = :client_id"]
    params: dict = {"client_id": client_id}
    if topic_id:
        where_parts.append(
            "client_prompt_id IN ("
            "  SELECT id FROM geo_client_prompts WHERE topic_id = :topic_id"
            ")"
        )
        params["topic_id"] = topic_id
    where_sql = " AND ".join(where_parts)

    total_count = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_results WHERE {where_sql}", params
    ) or 0
    analyzed_count = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_results WHERE {where_sql} AND analyzed_at IS NOT NULL",
        params,
    ) or 0
    pending_count = total_count - analyzed_count

    return AnalysisStatusOut(
        client_id=str(client_id),
        topic_id=str(topic_id) if topic_id else None,
        total_results=total_count,
        analyzed_results=analyzed_count,
        pending_results=pending_count,
        can_analyze=pending_count > 0,
    )


@router.get("/mentions", response_model=BrandMentionListOut)
async def get_mentions(
    client_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    topic_id: Optional[UUID] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
) -> BrandMentionListOut:
    """Get brand mentions for a client with pagination and filtering."""
    where_parts = ["bm.client_id = :client_id"]
    params: dict = {"client_id": client_id}
    if topic_id:
        where_parts.append("cp.topic_id = :topic_id")
        params["topic_id"] = topic_id
    if platform:
        where_parts.append("cp.platform = :platform")
        params["platform"] = platform
    if country:
        where_parts.append("cp.country = :country")
        params["country"] = country
    where_sql = " AND ".join(where_parts)

    total_count = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp ON bm.client_prompt_id = cp.id
        WHERE {where_sql}
        """,
        params,
    ) or 0

    offset = (page - 1) * limit

    rows = await database.fetch_all(
        f"""
        SELECT
            bm.*,
            cp.text AS client_prompt_text,
            cp.platform,
            cp.country
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp ON bm.client_prompt_id = cp.id
        WHERE {where_sql}
        ORDER BY bm.created_at DESC, bm.mention_position ASC
        OFFSET :offset
        LIMIT :limit
        """,
        {**params, "offset": offset, "limit": limit},
    )

    results = []
    for row in rows:
        d = dict(row)
        d["id"] = str(d["id"])
        d["client_prompt_id"] = str(d["client_prompt_id"])
        d["task_id"] = str(d["task_id"]) if d["task_id"] else None
        d["client_id"] = str(d["client_id"])
        d["executed_at"] = d["executed_at"].isoformat() if d["executed_at"] else None
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        results.append(d)

    return BrandMentionListOut(
        data=[BrandMentionRow(**d) for d in results],
        pagination=PaginationOut(
            page=page,
            limit=limit,
            total=total_count,
            pages=(total_count + limit - 1) // limit if total_count > 0 else 1,
        ),
    )


@router.get("/citations", response_model=CitationListOut)
async def get_citations(
    client_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    topic_id: Optional[UUID] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
) -> CitationListOut:
    """Get citations for a client with pagination and filtering."""
    where_parts = ["c.client_id = :client_id"]
    params: dict = {"client_id": client_id}
    if topic_id:
        where_parts.append("cp.topic_id = :topic_id")
        params["topic_id"] = topic_id
    if platform:
        where_parts.append("cp.platform = :platform")
        params["platform"] = platform
    if country:
        where_parts.append("cp.country = :country")
        params["country"] = country
    where_sql = " AND ".join(where_parts)

    total_count = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM geo_citations c
        JOIN geo_client_prompts cp ON c.client_prompt_id = cp.id
        WHERE {where_sql}
        """,
        params,
    ) or 0

    offset = (page - 1) * limit

    rows = await database.fetch_all(
        f"""
        SELECT
            c.*,
            cp.text AS client_prompt_text,
            cp.platform,
            cp.country
        FROM geo_citations c
        JOIN geo_client_prompts cp ON c.client_prompt_id = cp.id
        WHERE {where_sql}
        ORDER BY c.created_at DESC, c.source_position ASC
        OFFSET :offset
        LIMIT :limit
        """,
        {**params, "offset": offset, "limit": limit},
    )

    results = []
    for row in rows:
        d = dict(row)
        d["id"] = str(d["id"])
        d["client_prompt_id"] = str(d["client_prompt_id"])
        d["task_id"] = str(d["task_id"]) if d["task_id"] else None
        d["client_id"] = str(d["client_id"])
        for fk in ("matched_brand_id", "matched_product_id", "matched_peer_id"):
            if d.get(fk) is not None:
                d[fk] = str(d[fk])
        d["executed_at"] = d["executed_at"].isoformat() if d["executed_at"] else None
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        results.append(d)

    return CitationListOut(
        data=[CitationRow(**d) for d in results],
        pagination=PaginationOut(
            page=page,
            limit=limit,
            total=total_count,
            pages=(total_count + limit - 1) // limit if total_count > 0 else 1,
        ),
    )
