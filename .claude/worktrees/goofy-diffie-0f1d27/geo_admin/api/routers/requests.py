"""
Requests Router - CRUD for geo_requests

Updated for v2 schema with client_id, report_id, and peers as array.
"""
import uuid
import subprocess
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from uuid import UUID
from sqlalchemy import select, insert, func, desc
from database import (
    database, 
    geo_requests, 
    geo_tasks, 
    geo_clients,
    geo_client_peers,
    geo_client_domains,
    geo_reports
)

logger = logging.getLogger(__name__)
router = APIRouter()


class RequestCreate(BaseModel):
    """Schema for creating a new request."""
    # Client selection
    client_id: UUID
    peers: List[str] = []  # Selected peers for this request
    
    # Optional report association
    report_id: Optional[UUID] = None
    
    # Request parameters
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
    
    # Report
    report_id: Optional[str]
    report_name: Optional[str]
    
    # Client
    client_id: Optional[str]
    client_name: str
    peers: List[str]
    owned_domains: List[str]
    
    # Request params
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
    report_id: Optional[UUID] = None,
    client_id: Optional[UUID] = None,
):
    """List all requests with pagination."""
    offset = (page - 1) * limit
    
    # Build query
    query = select(geo_requests).order_by(desc(geo_requests.c.created_at))
    
    if status:
        query = query.where(geo_requests.c.status == status)
    if report_id:
        query = query.where(geo_requests.c.report_id == report_id)
    if client_id:
        query = query.where(geo_requests.c.client_id == client_id)
    
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
            "request_id": str(row["request_id"]),
            "batch_id": row["batch_id"],
            "report_id": str(row["report_id"]) if row["report_id"] else None,
            "report_name": row["report_name"],
            "client_id": str(row["client_id"]) if row["client_id"] else None,
            "client_name": row["client_name"],
            "peers": row["peers"] or [],
            "owned_domains": row["owned_domains"] or [],
            "topic": row["topic"],
            "product": row["product"],
            "country": row["country"],
            "platform": row["platform"],
            "intent": row["intent"],
            "prompts_per_request": row["prompts_per_request"],
            "calls_per_prompt": row["calls_per_prompt"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "task_count": task_count[0] if task_count else 0,
        })
    
    # Get total count
    total_query = select(func.count()).select_from(geo_requests)
    if status:
        total_query = total_query.where(geo_requests.c.status == status)
    if report_id:
        total_query = total_query.where(geo_requests.c.report_id == report_id)
    if client_id:
        total_query = total_query.where(geo_requests.c.client_id == client_id)
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
        "request_id": str(row["request_id"]),
        "batch_id": row["batch_id"],
        "report_id": str(row["report_id"]) if row["report_id"] else None,
        "report_name": row["report_name"],
        "client_id": str(row["client_id"]) if row["client_id"] else None,
        "client_name": row["client_name"],
        "peers": row["peers"] or [],
        "owned_domains": row["owned_domains"] or [],
        "topic": row["topic"],
        "product": row["product"],
        "country": row["country"],
        "platform": row["platform"],
        "intent": row["intent"],
        "prompts_per_request": row["prompts_per_request"],
        "calls_per_prompt": row["calls_per_prompt"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "task_count": task_count[0] if task_count else 0,
    }


@router.post("/requests")
async def create_request(req: RequestCreate):
    """Create a new request with client and optional report association."""
    # Fetch client
    client = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.id == req.client_id)
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Fetch client's domains
    domains_rows = await database.fetch_all(
        select(geo_client_domains.c.domain).where(
            geo_client_domains.c.client_id == req.client_id
        )
    )
    owned_domains = [d["domain"] for d in domains_rows]
    
    # Handle report association
    report_name = None
    if req.report_id:
        report = await database.fetch_one(
            select(geo_reports).where(geo_reports.c.id == req.report_id)
        )
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        report_name = report["name"]
    
    request_id = str(uuid.uuid4())
    batch_id = f"admin-{request_id[:8]}"
    
    await database.execute(
        insert(geo_requests).values(
            request_id=request_id,
            batch_id=batch_id,
            # Report
            report_id=req.report_id,
            report_name=report_name,
            # Client
            client_id=req.client_id,
            client_name=client["name"],
            peers=req.peers,
            owned_domains=owned_domains,
            # Request params
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
        "client_name": client["name"],
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
