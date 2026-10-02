"""
Agent Tasks Router (Admin) — Global Management of GEO Agent Tasks and Scheduling.

Reads from geo_agent_tasks (unified table for analysis & content_generation).

Phase 2.5b (2026-04-26): SQL fully migrated off SQLAlchemy.
"""
import json
import logging
import os
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from services.workspace_lifecycle import long_workspace_lifecycle_session
from pydantic import BaseModel

from db import database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-tasks", tags=["Agent Tasks"])


# ─── Pydantic models ───────────────────────────────────────────────────────


class AgentTaskListRow(BaseModel):
    id: str
    client_id: str
    user_id: Optional[str] = None
    task_type: Optional[str] = None
    task_name: Optional[str] = None
    status: Optional[str] = None
    workflow_steps: Optional[Any] = None
    current_step: Optional[int] = None
    inputs: Optional[Any] = None
    template_id: Optional[str] = None
    status_logs: Optional[Any] = None
    error_message: Optional[str] = None
    thread_id: Optional[str] = None
    triggered_by: Optional[str] = None
    model_used: Optional[str] = None
    cron_expression: Optional[str] = None
    cron_timezone: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    scheduler_job_name: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    customer_name: Optional[str] = None
    domains: List[Any] = []


class AgentTaskPagination(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class AgentTaskListOut(BaseModel):
    data: List[AgentTaskListRow]
    pagination: AgentTaskPagination


class ScheduleToggleOut(BaseModel):
    status: str
    schedule_enabled: bool
    scheduler_job_name: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Cloud Scheduler Synchronization
# ─────────────────────────────────────────────────────────────────────────────
def _get_task_job_name(task_id: str) -> str:
    t_short = str(task_id).split('-')[0]
    GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "profound-384110")
    GCP_REGION = os.getenv("GCP_REGION", "us-central1")
    return f"projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}/jobs/geo-task-{t_short}"


async def _sync_task_scheduler(
    task_id: str,
    cron_expression: Optional[str],
    timezone: str = "Asia/Shanghai",
) -> Optional[str]:
    """Create, update, or delete Cloud Scheduler job for an agent task."""
    from google.cloud import scheduler_v1

    try:
        scheduler_client = scheduler_v1.CloudSchedulerClient()
    except Exception as e:
        logger.warning(f"CloudSchedulerClient not available: {e}. Skipping cron setup.")
        return None

    job_name = _get_task_job_name(task_id)

    if not cron_expression:
        try:
            scheduler_client.delete_job(name=job_name)
            logger.info(f"Deleted task scheduler job: {job_name}")
        except Exception:
            pass
        return None

    AGENT_API_URL = (
        os.getenv("AGENT_API_URL")
        or os.getenv("SAAS_API_URL")
        or "https://api.profound.com"
    ).rstrip("/")
    SERVICE_ACCOUNT_EMAIL = os.getenv("SERVICE_ACCOUNT_EMAIL") or os.getenv("INVOKER_SERVICE_ACCOUNT")
    GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "profound-384110")
    GCP_REGION = os.getenv("GCP_REGION", "us-central1")

    uri = f"{AGENT_API_URL}/api/agent/tasks/{task_id}/trigger_cron?triggered_by=cron"

    job = scheduler_v1.Job(
        name=job_name,
        description=f"GEO Agent Task: {task_id}",
        schedule=cron_expression,
        time_zone=timezone,
        http_target=scheduler_v1.HttpTarget(
            uri=uri,
            http_method=scheduler_v1.HttpMethod.POST,
            oidc_token=scheduler_v1.OidcToken(
                service_account_email=SERVICE_ACCOUNT_EMAIL,
                audience=AGENT_API_URL,
            ) if SERVICE_ACCOUNT_EMAIL else None
        )
    )

    try:
        scheduler_client.get_job(name=job_name)
        scheduler_client.update_job(
            job=job,
            update_mask={"paths": ["schedule", "http_target", "description", "time_zone"]}
        )
        logger.info(f"Updated task scheduler job: {job_name}")
        return job_name
    except Exception:
        parent = f"projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}"
        try:
            scheduler_client.create_job(parent=parent, job=job)
            logger.info(f"Created task scheduler job: {job_name}")
            return job_name
        except Exception as create_err:
            logger.error(f"Failed to create scheduler job {job_name}: {create_err}")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

# Column whitelist for the geo_agent_tasks list response. ``output`` is
# excluded from the list view — it's a wide JSONB blob fetched only by the
# detail endpoint (lives in a different router).
_AGENT_TASK_LIST_COLUMNS = (
    "id, client_id, user_id, task_type, task_name, status, workflow_steps, "
    "current_step, inputs, template_id, status_logs, error_message, thread_id, "
    "triggered_by, model_used, cron_expression, cron_timezone, schedule_enabled, "
    "scheduler_job_name, started_at, completed_at, created_at, updated_at"
)


@router.get("", response_model=AgentTaskListOut)
async def list_agent_tasks(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    client_id: Optional[UUID] = None,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
) -> AgentTaskListOut:
    """List all agent tasks globally (for admin management)."""
    offset = (page - 1) * limit

    where_parts: list[str] = []
    params: dict = {}
    if client_id:
        where_parts.append("t.client_id = :client_id")
        params["client_id"] = client_id
    if status:
        where_parts.append("t.status = :status")
        params["status"] = status
    if task_type:
        if task_type == "analysis":
            where_parts.append("t.task_type IN ('analysis', 'opportunity_discovery')")
        else:
            where_parts.append("t.task_type = :task_type")
            params["task_type"] = task_type
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total_count = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM geo_agent_tasks t
        LEFT JOIN geo_clients c ON t.client_id = c.id
        {where_sql}
        """,
        params,
    ) or 0

    # Build the projected column list with the ``t.`` alias.
    projected = ", ".join(f"t.{c.strip()}" for c in _AGENT_TASK_LIST_COLUMNS.split(","))
    rows = await database.fetch_all(
        f"""
        SELECT {projected}, c.name AS customer_name
        FROM geo_agent_tasks t
        LEFT JOIN geo_clients c ON t.client_id = c.id
        {where_sql}
        ORDER BY t.created_at DESC
        OFFSET :offset LIMIT :limit
        """,
        {**params, "offset": offset, "limit": limit},
    )

    results = []
    for row in rows:
        d = dict(row)
        for field in ("id", "template_id", "client_id"):
            if d.get(field):
                d[field] = str(d[field])
        for field in ("started_at", "completed_at", "created_at", "updated_at"):
            if d.get(field):
                d[field] = d[field].isoformat()
        # Extract domains from inputs JSONB for display.
        inputs = d.get("inputs") or {}
        if isinstance(inputs, str):
            try:
                inputs = json.loads(inputs)
            except Exception:
                inputs = {}
        d["domains"] = inputs.get("domains", [])
        results.append(d)

    return AgentTaskListOut(
        data=[AgentTaskListRow(**d) for d in results],
        pagination=AgentTaskPagination(
            page=page,
            limit=limit,
            total=total_count,
            pages=(total_count + limit - 1) // limit if total_count > 0 else 1,
        ),
    )


class ScheduleToggleRequest(BaseModel):
    schedule_enabled: bool


@router.patch("/{task_id}/schedule", response_model=ScheduleToggleOut)
async def toggle_task_schedule(
    task_id: UUID,
    payload: ScheduleToggleRequest,
) -> ScheduleToggleOut:
    """Toggle Cloud Scheduler for a specific agent task."""
    task = await database.fetch_one(
        """
        SELECT client_id::text AS client_id, cron_expression, cron_timezone
        FROM geo_agent_tasks
        WHERE id = :id
        """,
        {"id": task_id},
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    cron_expr = task["cron_expression"]
    timezone = task["cron_timezone"] or "Asia/Shanghai"

    if payload.schedule_enabled and not cron_expr:
        raise HTTPException(
            status_code=400,
            detail="Cannot enable schedule without a defined cron expression."
        )

    target_cron = cron_expr if payload.schedule_enabled else None
    async with long_workspace_lifecycle_session(database.pool(), str(task["client_id"])):
        job_name = await _sync_task_scheduler(
            task_id=str(task_id),
            cron_expression=target_cron,
            timezone=timezone,
        )

        await database.execute(
            """
            UPDATE geo_agent_tasks
            SET schedule_enabled = :schedule_enabled,
                scheduler_job_name = :scheduler_job_name
            WHERE id = :id
            """,
            {
                "schedule_enabled": payload.schedule_enabled,
                "scheduler_job_name": job_name,
                "id": task_id,
            },
        )

    return ScheduleToggleOut(
        status="success",
        schedule_enabled=payload.schedule_enabled,
        scheduler_job_name=job_name,
    )
