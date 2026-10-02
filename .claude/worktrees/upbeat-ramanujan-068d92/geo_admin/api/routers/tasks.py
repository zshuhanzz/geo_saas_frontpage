"""
Tasks Router - View tasks and results
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func, desc
from database import database, geo_tasks, geo_results

router = APIRouter()


@router.get("/requests/{request_id}/tasks")
async def list_tasks_for_request(
    request_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
):
    """List all tasks for a specific request with pagination."""
    offset = (page - 1) * limit
    
    query = (
        select(geo_tasks)
        .where(geo_tasks.c.request_id == request_id)
        .order_by(geo_tasks.c.prompt_index.asc())
    )
    
    if status:
        query = query.where(geo_tasks.c.status == status)
    
    query = query.offset(offset).limit(limit)
    
    rows = await database.fetch_all(query)
    
    results = []
    for row in rows:
        results.append({
            **dict(row),
            "task_id": str(row["task_id"]),
            "request_id": str(row["request_id"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        })
    
    # Total count
    total_query = select(func.count()).select_from(geo_tasks).where(
        geo_tasks.c.request_id == request_id
    )
    if status:
        total_query = total_query.where(geo_tasks.c.status == status)
    total = await database.fetch_one(total_query)
    
    return {
        "data": results,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total[0] if total else 0,
            "pages": (total[0] // limit + 1) if total else 1,
        }
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a single task by ID."""
    row = await database.fetch_one(
        select(geo_tasks).where(geo_tasks.c.task_id == task_id)
    )
    
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {
        **dict(row),
        "task_id": str(row["task_id"]),
        "request_id": str(row["request_id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.get("/tasks/{task_id}/results")
async def list_results_for_task(
    task_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """List all results for a specific task with pagination."""
    offset = (page - 1) * limit
    
    query = (
        select(geo_results)
        .where(geo_results.c.task_id == task_id)
        .order_by(geo_results.c.call_index.asc())
        .offset(offset)
        .limit(limit)
    )
    
    rows = await database.fetch_all(query)
    
    results = []
    for row in rows:
        # Don't include full cloro_response in list view to save bandwidth
        row_dict = dict(row)
        row_dict["task_id"] = str(row["task_id"])
        # Handle ingested_at
        try:
            row_dict["ingested_at"] = row["ingested_at"].isoformat() if row["ingested_at"] else None
        except (KeyError, AttributeError):
            row_dict["ingested_at"] = None
        # Truncate large fields for list view
        if row_dict.get("text") and len(row_dict["text"]) > 500:
            row_dict["text_preview"] = row_dict["text"][:500] + "..."
            del row_dict["text"]
        if row_dict.get("cloro_response"):
            del row_dict["cloro_response"]  # Exclude from list
        results.append(row_dict)
    
    # Total count
    total = await database.fetch_one(
        select(func.count()).select_from(geo_results).where(
            geo_results.c.task_id == task_id
        )
    )
    
    return {
        "data": results,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total[0] if total else 0,
            "pages": (total[0] // limit + 1) if total else 1,
        }
    }


@router.get("/results/{result_id}")
async def get_result(result_id: int):
    """Get a single result by ID (includes full data)."""
    row = await database.fetch_one(
        select(geo_results).where(geo_results.c.result_id == result_id)
    )
    
    if not row:
        raise HTTPException(status_code=404, detail="Result not found")
    
    # Handle ingested_at
    try:
        ingested_at = row["ingested_at"].isoformat() if row["ingested_at"] else None
    except (KeyError, AttributeError):
        ingested_at = None
    
    return {
        **dict(row),
        "task_id": str(row["task_id"]),
        "ingested_at": ingested_at,
    }
