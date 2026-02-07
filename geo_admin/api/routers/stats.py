"""
Stats Router - Overview statistics
"""
from fastapi import APIRouter
from sqlalchemy import select, func
from database import database, geo_requests, geo_tasks, geo_results

router = APIRouter()


@router.get("/stats")
async def get_stats():
    """Get overview statistics for dashboard."""
    
    # Count requests by status
    requests_count = await database.fetch_one(
        select(func.count()).select_from(geo_requests)
    )
    
    pending_requests = await database.fetch_one(
        select(func.count()).select_from(geo_requests).where(
            geo_requests.c.status == "PENDING"
        )
    )
    
    # Count tasks
    tasks_count = await database.fetch_one(
        select(func.count()).select_from(geo_tasks)
    )
    
    # Count results
    results_count = await database.fetch_one(
        select(func.count()).select_from(geo_results)
    )
    
    return {
        "requests": {
            "total": requests_count[0] if requests_count else 0,
            "pending": pending_requests[0] if pending_requests else 0,
        },
        "tasks": tasks_count[0] if tasks_count else 0,
        "results": results_count[0] if results_count else 0,
    }
