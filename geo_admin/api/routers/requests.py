"""
Requests Router - CRUD for geo_requests
"""
import uuid
import subprocess
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, insert, func, desc
from database import database, geo_requests, geo_tasks

logger = logging.getLogger(__name__)
router = APIRouter()


class RequestCreate(BaseModel):
    """Schema for creating a new request."""
    client_name: str
    peers: Optional[str] = None
    topic: Optional[str] = None
    product: Optional[str] = None
    country: str = "US"
    platform: str = "chatgpt"
    intent: str = "Solution Discovery"
    prompts_per_request: int = 20
    calls_per_prompt: int = 3


class RequestResponse(BaseModel):
    """Schema for request response."""
    request_id: str
    batch_id: Optional[str]
    client_name: str
    peers: Optional[str]
    topic: Optional[str]
    product: Optional[str]
    country: str
    platform: str
    intent: Optional[str]
    prompts_per_request: int
    calls_per_prompt: int
    status: str
    created_at: str
    task_count: int = 0


@router.get("/requests")
async def list_requests(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
):
    """List all requests with pagination."""
    offset = (page - 1) * limit
    
    # Build query
    query = select(geo_requests).order_by(desc(geo_requests.c.created_at))
    
    if status:
        query = query.where(geo_requests.c.status == status)
    
    query = query.offset(offset).limit(limit)
    
    rows = await database.fetch_all(query)
    
    # Get task counts for each request
    results = []
    for row in rows:
        task_count = await database.fetch_one(
            select(func.count()).select_from(geo_tasks).where(
                geo_tasks.c.request_id == row["request_id"]
            )
        )
        results.append({
            **dict(row),
            "request_id": str(row["request_id"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "task_count": task_count[0] if task_count else 0,
        })
    
    # Get total count
    total_query = select(func.count()).select_from(geo_requests)
    if status:
        total_query = total_query.where(geo_requests.c.status == status)
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


@router.get("/requests/{request_id}")
async def get_request(request_id: str):
    """Get a single request by ID."""
    row = await database.fetch_one(
        select(geo_requests).where(geo_requests.c.request_id == request_id)
    )
    
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    
    task_count = await database.fetch_one(
        select(func.count()).select_from(geo_tasks).where(
            geo_tasks.c.request_id == request_id
        )
    )
    
    return {
        **dict(row),
        "request_id": str(row["request_id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "task_count": task_count[0] if task_count else 0,
    }


@router.post("/requests")
async def create_request(req: RequestCreate):
    """Create a new request."""
    request_id = str(uuid.uuid4())
    batch_id = f"admin-{request_id[:8]}"
    
    await database.execute(
        insert(geo_requests).values(
            request_id=request_id,
            batch_id=batch_id,
            client_name=req.client_name,
            peers=req.peers,
            topic=req.topic,
            product=req.product,
            country=req.country,
            platform=req.platform,
            intent=req.intent,
            prompts_per_request=req.prompts_per_request,
            calls_per_prompt=req.calls_per_prompt,
            status="PENDING",
        )
    )
    
    return {
        "status": "created",
        "request_id": request_id,
        "batch_id": batch_id,
    }


@router.post("/requests/trigger")
async def trigger_expander():
    """
    Trigger the prompt expander job to process the oldest pending request.
    """
    # Check if there are pending requests
    pending = await database.fetch_one(
        select(geo_requests)
        .where(geo_requests.c.status == "PENDING")
        .order_by(geo_requests.c.created_at.asc())
        .limit(1)
    )
    
    if not pending:
        return {"status": "no_pending", "message": "No pending requests to process"}
    
    # Trigger Cloud Run Job
    try:
        result = subprocess.run(
            [
                "gcloud", "run", "jobs", "execute",
                "geo-prompt-expander",
                "--region", "us-central1",
                "--async"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info(f"Triggered expander job: {result.stdout}")
            return {
                "status": "triggered",
                "oldest_pending_request": str(pending["request_id"]),
                "message": "Expander job triggered successfully",
            }
        else:
            logger.error(f"Failed to trigger job: {result.stderr}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to trigger job: {result.stderr}"
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Trigger command timed out")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="gcloud CLI not found")
