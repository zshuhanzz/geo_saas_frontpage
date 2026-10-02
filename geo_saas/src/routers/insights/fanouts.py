"""
Fanouts endpoint — Paginated task list.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import database

router = APIRouter()


class FanoutRow(BaseModel):
    """Mirror of ``geo_tasks`` row, with UUID/datetime stringified upstream."""

    task_id: str
    client_prompt_id: str
    client_id: str
    topic_id: str
    topic: Optional[str] = None
    product: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    client_prompt_text: Optional[str] = None
    final_prompt: Optional[str] = None
    calls_per_prompt: Optional[int] = None
    dispatched_count: Optional[int] = None
    completed_count: Optional[int] = None
    status: Optional[str] = None
    batch_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FanoutPagination(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class FanoutsOut(BaseModel):
    data: List[FanoutRow]
    pagination: FanoutPagination


@router.get("/fanouts", response_model=FanoutsOut)
async def get_fanouts(
    client_id: UUID,
    topic_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> FanoutsOut:
    """Get Query Fanouts mapping to geo_tasks (dispatched prompts)."""
    where_sql = "client_id = :client_id"
    params: dict = {"client_id": client_id}
    if topic_id:
        where_sql += " AND topic_id = :topic_id"
        params["topic_id"] = topic_id

    total_count = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_tasks WHERE {where_sql}",
        params,
    ) or 0

    offset = (page - 1) * limit
    rows = await database.fetch_all(
        f"""
        SELECT *
        FROM geo_tasks
        WHERE {where_sql}
        ORDER BY created_at DESC
        OFFSET :offset
        LIMIT :limit
        """,
        {**params, "offset": offset, "limit": limit},
    )

    results = []
    for row in rows:
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, UUID):
                d[k] = str(v)
            elif hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        results.append(d)

    return FanoutsOut(
        data=[FanoutRow(**r) for r in results],
        pagination=FanoutPagination(
            page=page,
            limit=limit,
            total=total_count,
            pages=(total_count + limit - 1) // limit if total_count > 0 else 1,
        ),
    )
