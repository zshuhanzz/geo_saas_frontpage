"""
Reports Router - CRUD operations for geo_reports

Provides endpoints for managing analysis reports.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, insert, update, delete
from database import (
    database, 
    geo_reports, 
    geo_clients, 
    geo_client_peers, 
    geo_client_domains
)

router = APIRouter(prefix="/reports", tags=["Reports"])


# --- Pydantic Models ---

class ReportCreate(BaseModel):
    name: str
    client_id: UUID

class ReportUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None

class ReportResponse(BaseModel):
    id: UUID
    name: str
    client_id: Optional[UUID]
    client_name: str
    peers: List[str]
    owned_domains: List[str]
    status: str


# --- Report CRUD ---

@router.get("", response_model=List[ReportResponse])
async def list_reports(
    client_id: Optional[UUID] = None,
    status: Optional[str] = None
):
    """List all reports. Supports filtering by client_id and status."""
    query = select(geo_reports).order_by(geo_reports.c.created_at.desc())
    
    if client_id:
        query = query.where(geo_reports.c.client_id == client_id)
    if status:
        query = query.where(geo_reports.c.status == status)
    
    reports = await database.fetch_all(query)
    
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "client_id": r["client_id"],
            "client_name": r["client_name"],
            "peers": r["peers"] or [],
            "owned_domains": r["owned_domains"] or [],
            "status": r["status"]
        }
        for r in reports
    ]


@router.post("", response_model=ReportResponse, status_code=201)
async def create_report(data: ReportCreate):
    """Create a new report. Snapshots current client data (name, peers, domains)."""
    # Fetch client
    client = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.id == data.client_id)
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Fetch current peers
    peers_rows = await database.fetch_all(
        select(geo_client_peers.c.peer_name).where(
            geo_client_peers.c.client_id == data.client_id
        )
    )
    peers = [p["peer_name"] for p in peers_rows]
    
    # Fetch current domains
    domains_rows = await database.fetch_all(
        select(geo_client_domains.c.domain).where(
            geo_client_domains.c.client_id == data.client_id
        )
    )
    owned_domains = [d["domain"] for d in domains_rows]
    
    # Insert report with snapshot
    result = await database.fetch_one(
        insert(geo_reports).values(
            name=data.name,
            client_id=data.client_id,
            client_name=client["name"],
            peers=peers,
            owned_domains=owned_domains,
            status="draft"
        ).returning(geo_reports.c.id)
    )
    
    return {
        "id": result["id"],
        "name": data.name,
        "client_id": data.client_id,
        "client_name": client["name"],
        "peers": peers,
        "owned_domains": owned_domains,
        "status": "draft"
    }


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(report_id: UUID):
    """Get a single report by ID."""
    report = await database.fetch_one(
        select(geo_reports).where(geo_reports.c.id == report_id)
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return {
        "id": report["id"],
        "name": report["name"],
        "client_id": report["client_id"],
        "client_name": report["client_name"],
        "peers": report["peers"] or [],
        "owned_domains": report["owned_domains"] or [],
        "status": report["status"]
    }


@router.put("/{report_id}", response_model=ReportResponse)
async def update_report(report_id: UUID, data: ReportUpdate):
    """Update report name or status."""
    report = await database.fetch_one(
        select(geo_reports).where(geo_reports.c.id == report_id)
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    updates = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.status is not None:
        if data.status not in ["draft", "analyzing", "completed"]:
            raise HTTPException(status_code=400, detail="Invalid status")
        updates["status"] = data.status
    
    if updates:
        await database.execute(
            update(geo_reports).where(geo_reports.c.id == report_id).values(**updates)
        )
    
    return await get_report(report_id)


@router.delete("/{report_id}", status_code=204)
async def delete_report(report_id: UUID):
    """Delete a report."""
    report = await database.fetch_one(
        select(geo_reports).where(geo_reports.c.id == report_id)
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    await database.execute(
        delete(geo_reports).where(geo_reports.c.id == report_id)
    )
    return None


@router.post("/{report_id}/refresh-snapshot", response_model=ReportResponse)
async def refresh_snapshot(report_id: UUID):
    """Refresh the report's snapshot with current client data (peers, domains)."""
    report = await database.fetch_one(
        select(geo_reports).where(geo_reports.c.id == report_id)
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    if not report["client_id"]:
        raise HTTPException(status_code=400, detail="Report has no associated client")
    
    client_id = report["client_id"]
    
    # Fetch latest client data
    client = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.id == client_id)
    )
    if not client:
        raise HTTPException(status_code=404, detail="Associated client not found")
    
    # Fetch current peers
    peers_rows = await database.fetch_all(
        select(geo_client_peers.c.peer_name).where(
            geo_client_peers.c.client_id == client_id
        )
    )
    peers = [p["peer_name"] for p in peers_rows]
    
    # Fetch current domains
    domains_rows = await database.fetch_all(
        select(geo_client_domains.c.domain).where(
            geo_client_domains.c.client_id == client_id
        )
    )
    owned_domains = [d["domain"] for d in domains_rows]
    
    # Update report
    await database.execute(
        update(geo_reports).where(geo_reports.c.id == report_id).values(
            client_name=client["name"],
            peers=peers,
            owned_domains=owned_domains
        )
    )
    
    return await get_report(report_id)


@router.post("/{report_id}/analyze")
async def trigger_analysis(report_id: UUID):
    """
    Trigger analysis for a report.
    Calls geo-analyzer Cloud Run Job with REPORT_ID env var.
    """
    import subprocess
    import os
    
    # Verify report exists
    report = await database.fetch_one(
        select(geo_reports).where(geo_reports.c.id == report_id)
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Get region from env or default
    region = os.getenv("GCP_REGION", "us-central1")
    
    try:
        result = subprocess.run(
            [
                "gcloud", "run", "jobs", "execute", "geo-analyzer",
                "--region", region,
                "--update-env-vars", f"REPORT_ID={report_id}",
                "--async"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to trigger analyzer: {result.stderr}"
            )
        
        # Update report status to analyzing
        await database.execute(
            update(geo_reports).where(geo_reports.c.id == report_id).values(
                status="analyzing"
            )
        )
        
        return {
            "status": "triggered",
            "report_id": str(report_id),
            "message": "Analysis job started"
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout triggering analyzer")
    except FileNotFoundError:
        # gcloud not available - for local dev, just update status
        await database.execute(
            update(geo_reports).where(geo_reports.c.id == report_id).values(
                status="analyzing"
            )
        )
        return {
            "status": "triggered_local",
            "report_id": str(report_id),
            "message": "gcloud not available, status updated for local testing"
        }

