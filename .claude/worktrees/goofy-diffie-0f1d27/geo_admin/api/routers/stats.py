"""
Stats Router - Overview statistics
"""
from fastapi import APIRouter
from sqlalchemy import select, func
from database import database, geo_requests, geo_tasks, geo_results, geo_clients, geo_reports

router = APIRouter()


@router.get("/stats")
async def get_stats():
    """Get overview statistics for dashboard."""
    
    # Count clients
    clients_count = await database.fetch_one(
        select(func.count()).select_from(geo_clients)
    )
    
    # Count reports by status
    reports_total = await database.fetch_one(
        select(func.count()).select_from(geo_reports)
    )
    
    reports_analyzing = await database.fetch_one(
        select(func.count()).select_from(geo_reports).where(
            geo_reports.c.status == "analyzing"
        )
    )
    
    reports_completed = await database.fetch_one(
        select(func.count()).select_from(geo_reports).where(
            geo_reports.c.status == "completed"
        )
    )
    
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
        "clients": clients_count[0] if clients_count else 0,
        "reports": {
            "total": reports_total[0] if reports_total else 0,
            "analyzing": reports_analyzing[0] if reports_analyzing else 0,
            "completed": reports_completed[0] if reports_completed else 0,
        },
        "requests": {
            "total": requests_count[0] if requests_count else 0,
            "pending": pending_requests[0] if pending_requests else 0,
        },
        "tasks": tasks_count[0] if tasks_count else 0,
        "results": results_count[0] if results_count else 0,
    }

