"""
Tasks Router (V2.5 SaaS) - View tasks and results.

Updated for V2.5 schema: uses client_id, topic_id, and client_prompt_id
instead of campaign_id.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db import database

router = APIRouter(tags=["Tasks"])


# ─── Pydantic models ───────────────────────────────────────────────────────


class TaskRow(BaseModel):
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


class TaskPagination(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class TaskListOut(BaseModel):
    data: List[TaskRow]
    pagination: TaskPagination


class ResultRow(BaseModel):
    result_id: int
    task_id: Optional[str] = None
    client_prompt_id: Optional[str] = None
    cloro_task_id: Optional[str] = None
    call_index: Optional[int] = None
    cloro_response: Optional[Any] = None
    http_status_code: Optional[int] = None
    latency_ms: Optional[int] = None
    text: Optional[str] = None
    text_preview: Optional[str] = None
    html: Optional[str] = None
    markdown: Optional[str] = None
    sources: Optional[Any] = None
    shopping_cards: Optional[Any] = None
    places: Optional[Any] = None
    entities: Optional[Any] = None
    search_queries: Optional[Any] = None
    citation_pills: Optional[Any] = None
    client_id: Optional[str] = None
    topic_id: Optional[str] = None
    topic_name: Optional[str] = None
    product: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    final_prompt: Optional[str] = None
    ingested_at: Optional[str] = None
    analyzed_at: Optional[str] = None


class ResultListOut(BaseModel):
    data: List[ResultRow]
    pagination: TaskPagination


class BatchSummaryRow(BaseModel):
    batch_id: str
    total_results: int = 0
    analyzed_results: int = 0
    unanalyzed_results: int = 0
    completed_tasks: int = 0
    dispatched_tasks: int = 0
    dispatch_failed_tasks: int = 0
    latest_ingested_at: Optional[str] = None
    latest_analyzed_at: Optional[str] = None
    is_default_selection: bool = False


# Allowed sort fields to prevent SQL injection
SORTABLE_FIELDS = {
    "task_id", "status", "platform", "country", "language",
    "topic", "product", "client_prompt_text", "final_prompt",
    "calls_per_prompt", "dispatched_count", "completed_count",
    "batch_id", "client_prompt_id", "created_at", "updated_at",
}


# ============================================================================
# Utility functions
# ============================================================================

def serialize_row(
    row,
    uuid_fields: Optional[List[str]] = None,
    datetime_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Convert an asyncpg row to a serializable dict (UUID/datetime aware)."""
    row_dict = dict(row)
    for field in (uuid_fields or []):
        if field in row_dict and row_dict[field] is not None:
            row_dict[field] = str(row_dict[field])
    for field in (datetime_fields or []):
        if field in row_dict and row_dict[field] is not None:
            try:
                row_dict[field] = row_dict[field].isoformat()
            except (AttributeError, KeyError):
                pass
    return row_dict


TASK_UUID_FIELDS = ["task_id", "client_id", "topic_id", "client_prompt_id"]
TASK_DATETIME_FIELDS = ["created_at", "updated_at"]
RESULT_UUID_FIELDS = ["task_id", "client_prompt_id", "client_id", "topic_id"]
RESULT_DATETIME_FIELDS = ["ingested_at", "analyzed_at"]


def _build_task_where(
    *,
    alias: str,
    base: list[str],
    base_params: dict,
    topic_id=None,
    client_prompt_id=None,
    status=None,
    batch_id=None,
) -> tuple[str, dict]:
    """Build a parameterized WHERE clause for geo_tasks queries.

    ``alias`` is the table alias used in caller's SQL (e.g. ``"t"`` for
    JOINed queries, ``""`` for plain ``FROM geo_tasks``). Empty alias
    emits column references without a prefix.
    """
    prefix = f"{alias}." if alias else ""
    parts = list(base)
    params = dict(base_params)
    if topic_id:
        parts.append(f"{prefix}topic_id = :topic_id")
        params["topic_id"] = topic_id
    if client_prompt_id:
        parts.append(f"{prefix}client_prompt_id = :client_prompt_id")
        params["client_prompt_id"] = client_prompt_id
    if status:
        parts.append(f"UPPER(TRIM({prefix}status)) = :status")
        params["status"] = str(status).strip().upper()
    if batch_id:
        parts.append(f"{prefix}batch_id = :batch_id")
        params["batch_id"] = batch_id
    return " AND ".join(parts), params


def _parse_uuid_csv(value: str) -> list[str]:
    ids = [item.strip() for item in value.split(",") if item.strip()]
    return [str(UUID(item)) for item in ids]


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/clients/{client_id}/batch-ids", response_model=List[str])
async def list_batch_ids(client_id: UUID) -> List[str]:
    """List all distinct batch_ids for a client, newest first."""
    rows = await database.fetch_all(
        """
        SELECT DISTINCT batch_id
        FROM geo_tasks
        WHERE client_id = :client_id AND batch_id IS NOT NULL
        ORDER BY batch_id DESC
        """,
        {"client_id": client_id},
    )
    return [row["batch_id"] for row in rows]


@router.get("/clients/{client_id}/batch-summaries", response_model=List[BatchSummaryRow])
async def list_batch_summaries(client_id: UUID) -> List[BatchSummaryRow]:
    """List batch health summaries for Admin Analyzer selection."""
    rows = await database.fetch_all(
        """
        WITH result_counts AS (
            SELECT
                batch_id,
                COUNT(*)::int AS total_results,
                COUNT(*) FILTER (WHERE analyzed_at IS NOT NULL)::int AS analyzed_results,
                COUNT(*) FILTER (WHERE analyzed_at IS NULL)::int AS unanalyzed_results,
                MAX(ingested_at) AS latest_ingested_at,
                MAX(analyzed_at) AS latest_analyzed_at
            FROM geo_results
            WHERE client_id = :client_id
              AND batch_id IS NOT NULL
            GROUP BY batch_id
        ),
        task_counts AS (
            SELECT
                batch_id,
                COUNT(*) FILTER (WHERE UPPER(TRIM(status)) = 'COMPLETED')::int AS completed_tasks,
                COUNT(*) FILTER (WHERE UPPER(TRIM(status)) = 'DISPATCHED')::int AS dispatched_tasks,
                COUNT(*) FILTER (WHERE UPPER(TRIM(status)) = 'DISPATCH_FAILED')::int AS dispatch_failed_tasks
            FROM geo_tasks
            WHERE client_id = :client_id
              AND batch_id IS NOT NULL
            GROUP BY batch_id
        )
        SELECT
            r.batch_id,
            r.total_results,
            r.analyzed_results,
            r.unanalyzed_results,
            COALESCE(t.completed_tasks, 0)::int AS completed_tasks,
            COALESCE(t.dispatched_tasks, 0)::int AS dispatched_tasks,
            COALESCE(t.dispatch_failed_tasks, 0)::int AS dispatch_failed_tasks,
            r.latest_ingested_at,
            r.latest_analyzed_at
        FROM result_counts r
        LEFT JOIN task_counts t ON t.batch_id = r.batch_id
        ORDER BY r.batch_id ASC
        """,
        {"client_id": client_id},
    )
    summaries: list[dict[str, Any]] = []
    default_batch_id: str | None = None
    for row in rows:
        row_dict = serialize_row(
            row,
            datetime_fields=["latest_ingested_at", "latest_analyzed_at"],
        )
        if default_batch_id is None and row_dict["unanalyzed_results"] > 0:
            default_batch_id = row_dict["batch_id"]
        summaries.append(row_dict)
    for row in summaries:
        row["is_default_selection"] = row["batch_id"] == default_batch_id
    return [BatchSummaryRow(**row) for row in summaries]


@router.get("/clients/{client_id}/tasks/by-prompts", response_model=TaskListOut)
async def list_tasks_for_prompt_ids(
    client_id: UUID,
    prompt_ids: str = Query(..., description="Comma-separated client prompt ids"),
    batch_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> TaskListOut:
    """List paginated tasks for a complete logical prompt concept."""
    parsed_prompt_ids = _parse_uuid_csv(prompt_ids)
    if not parsed_prompt_ids:
        return TaskListOut(
            data=[],
            pagination=TaskPagination(page=1, limit=limit, total=0, pages=1),
        )
    offset = (page - 1) * limit

    where_parts = [
        "t.client_id = :client_id",
        "t.client_prompt_id = ANY(:prompt_ids::uuid[])",
    ]
    params: dict[str, Any] = {
        "client_id": client_id,
        "prompt_ids": parsed_prompt_ids,
        "offset": offset,
        "limit": limit,
    }
    if batch_id:
        where_parts.append("t.batch_id = :batch_id")
        params["batch_id"] = batch_id

    where_sql = " AND ".join(where_parts)
    rows = await database.fetch_all(
        f"""
        SELECT
            t.*,
            cp.text AS client_prompt_text,
            cp.platform AS cp_platform,
            cp.country AS cp_country
        FROM geo_tasks t
        LEFT JOIN geo_client_prompts cp ON t.client_prompt_id = cp.id
        WHERE {where_sql}
        ORDER BY t.created_at DESC, t.platform ASC, t.country ASC
        OFFSET :offset
        LIMIT :limit
        """,
        params,
    )

    results = []
    for row in rows:
        d = serialize_row(row, TASK_UUID_FIELDS, TASK_DATETIME_FIELDS)
        if not d.get("platform") and d.get("cp_platform"):
            d["platform"] = d["cp_platform"]
        if not d.get("country") and d.get("cp_country"):
            d["country"] = d["cp_country"]
        d.pop("cp_platform", None)
        d.pop("cp_country", None)
        results.append(d)

    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_tasks t WHERE {where_sql}",
        {k: v for k, v in params.items() if k not in {"offset", "limit"}},
    ) or 0

    return TaskListOut(
        data=[TaskRow(**r) for r in results],
        pagination=TaskPagination(
            page=page,
            limit=limit,
            total=total,
            pages=(total + limit - 1) // limit if total > 0 else 1,
        ),
    )


@router.get("/clients/{client_id}/tasks", response_model=TaskListOut)
async def list_tasks_for_client(
    client_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    topic_id: Optional[UUID] = None,
    client_prompt_id: Optional[UUID] = None,
    status: Optional[str] = None,
    batch_id: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = Query(None, pattern="^(asc|desc)$"),
) -> TaskListOut:
    """List all tasks for a specific client with pagination and sorting."""
    offset = (page - 1) * limit

    where_sql, params = _build_task_where(
        alias="t",
        base=["t.client_id = :client_id"],
        base_params={"client_id": client_id},
        topic_id=topic_id,
        client_prompt_id=client_prompt_id,
        status=status,
        batch_id=batch_id,
    )

    # Sort whitelist guards SQL injection — only known geo_tasks columns.
    if sort_by and sort_by in SORTABLE_FIELDS:
        direction = "ASC" if sort_dir == "asc" else "DESC"
        order_sql = f"ORDER BY t.{sort_by} {direction}"
    else:
        order_sql = "ORDER BY t.created_at DESC"

    rows = await database.fetch_all(
        f"""
        SELECT
            t.*,
            cp.text AS client_prompt_text,
            cp.platform AS cp_platform,
            cp.country AS cp_country
        FROM geo_tasks t
        LEFT JOIN geo_client_prompts cp ON t.client_prompt_id = cp.id
        WHERE {where_sql}
        {order_sql}
        OFFSET :offset
        LIMIT :limit
        """,
        {**params, "offset": offset, "limit": limit},
    )

    # Merge cp_platform / cp_country into platform / country only when geo_tasks
    # didn't already carry them (legacy rows did, fresh rows do as well).
    results = []
    for row in rows:
        d = serialize_row(row, TASK_UUID_FIELDS, TASK_DATETIME_FIELDS)
        if not d.get("platform") and d.get("cp_platform"):
            d["platform"] = d["cp_platform"]
        if not d.get("country") and d.get("cp_country"):
            d["country"] = d["cp_country"]
        d.pop("cp_platform", None)
        d.pop("cp_country", None)
        results.append(d)

    # Re-build a count-only WHERE without the ``t.`` alias (no JOIN).
    count_where_sql, count_params = _build_task_where(
        alias="",
        base=["client_id = :client_id"],
        base_params={"client_id": client_id},
        topic_id=topic_id,
        client_prompt_id=client_prompt_id,
        status=status,
        batch_id=batch_id,
    )
    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_tasks WHERE {count_where_sql}",
        count_params,
    ) or 0

    return TaskListOut(
        data=[TaskRow(**r) for r in results],
        pagination=TaskPagination(
            page=page,
            limit=limit,
            total=total,
            pages=(total + limit - 1) // limit if total > 0 else 1,
        ),
    )


@router.get("/tasks/{task_id}", response_model=TaskRow)
async def get_task(task_id: UUID) -> TaskRow:
    """Get a single task by ID."""
    row = await database.fetch_one(
        "SELECT * FROM geo_tasks WHERE task_id = :task_id",
        {"task_id": task_id},
    )

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskRow(**serialize_row(row, TASK_UUID_FIELDS, TASK_DATETIME_FIELDS))


@router.get("/tasks/{task_id}/results", response_model=ResultListOut)
async def list_results_for_task(
    task_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> ResultListOut:
    """List all results for a specific task with pagination."""
    offset = (page - 1) * limit

    rows = await database.fetch_all(
        """
        SELECT * FROM geo_results
        WHERE task_id = :task_id
        ORDER BY call_index ASC
        OFFSET :offset
        LIMIT :limit
        """,
        {"task_id": task_id, "offset": offset, "limit": limit},
    )

    results = []
    for row in rows:
        row_dict = serialize_row(row, RESULT_UUID_FIELDS, RESULT_DATETIME_FIELDS)
        # Truncate large fields for the list endpoint.
        if row_dict.get("text") and len(row_dict["text"]) > 500:
            row_dict["text_preview"] = row_dict["text"][:500] + "..."
            del row_dict["text"]
        if row_dict.get("cloro_response"):
            del row_dict["cloro_response"]
        results.append(row_dict)

    total = await database.fetch_val(
        "SELECT COUNT(*) FROM geo_results WHERE task_id = :task_id",
        {"task_id": task_id},
    ) or 0

    return ResultListOut(
        data=[ResultRow(**r) for r in results],
        pagination=TaskPagination(
            page=page,
            limit=limit,
            total=total,
            pages=(total + limit - 1) // limit if total > 0 else 1,
        ),
    )


@router.get("/results/{result_id}", response_model=ResultRow)
async def get_result(result_id: int) -> ResultRow:
    """Get a single result by ID (includes full data)."""
    row = await database.fetch_one(
        "SELECT * FROM geo_results WHERE result_id = :result_id",
        {"result_id": result_id},
    )

    if not row:
        raise HTTPException(status_code=404, detail="Result not found")

    return ResultRow(**serialize_row(row, RESULT_UUID_FIELDS, RESULT_DATETIME_FIELDS))
