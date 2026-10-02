"""
Report Templates Router - CRUD for geo_report_templates.

Manages AI analysis report templates for the Analysis & Insights workflow.
Phase 2.5b (2026-04-26): SQL fully migrated off SQLAlchemy.
"""
import json
import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from geo_common.services import WorkspaceWriteCoordinator
from pydantic import BaseModel, ConfigDict

from db import _named_to_positional, database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis/templates", tags=["Report Templates"])

SAAS_API_URL = os.environ.get("SAAS_API_URL", "")
SERVICE_ACCOUNT_EMAIL = os.environ.get("INVOKER_SERVICE_ACCOUNT", "")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")


GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
SCHEDULER_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Shanghai")




# ============================================================================
# Pydantic Models
# ============================================================================

class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    icon: str = "📊"
    data_domains: List[str] = []
    default_prompt: Optional[str] = None
    client_id: Optional[UUID] = None
    is_builtin: bool = False
    is_active: bool = True
    sort_order: int = 0
    task_type: str = "analysis"
    defaults: Optional[dict] = None
    wizard_config: Optional[dict] = None
    cron_expression: Optional[str] = None
    cron_timezone: Optional[str] = "Asia/Shanghai"
    schedule_enabled: bool = False


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    data_domains: Optional[List[str]] = None
    default_prompt: Optional[str] = None
    is_active: Optional[bool] = None
    is_builtin: Optional[bool] = None
    sort_order: Optional[int] = None
    task_type: Optional[str] = None
    defaults: Optional[dict] = None
    wizard_config: Optional[dict] = None
    cron_expression: Optional[str] = None
    cron_timezone: Optional[str] = None
    schedule_enabled: Optional[bool] = None


# ─── Output models ─────────────────────────────────────────────────────────


class WorkflowConfigItemOut(BaseModel):
    id: Optional[str] = None
    config_type: str
    scope: str
    key: str
    parent_key: Optional[str] = None
    value: Optional[Any] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TemplateOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    data_domains: Optional[List[str]] = None
    default_prompt: Optional[str] = None
    is_builtin: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    task_type: Optional[str] = None
    defaults: Optional[Dict[str, Any]] = None
    wizard_config: Optional[Dict[str, Any]] = None
    client_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TemplatePagination(BaseModel):
    page: int
    total: int
    pages: int


class TemplateListOut(BaseModel):
    data: List[TemplateOut]
    pagination: TemplatePagination


_TEMPLATE_COLUMNS = (
    "id, name, description, icon, data_domains, default_prompt, "
    "is_builtin, is_active, sort_order, task_type, defaults, wizard_config, "
    "client_id, created_at, updated_at"
)

_WORKFLOW_CONFIG_COLUMNS = (
    "id, config_type, scope, key, parent_key, value, sort_order, "
    "is_active, created_at"
)


def _stringify_id(d: dict) -> dict:
    """Stringify UUID id field if present."""
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    return d


# ============================================================================
# Endpoints
# ============================================================================

# IMPORTANT: /workflow-config MUST be defined before /{template_id}
# to prevent FastAPI from treating "workflow-config" as a UUID.

@router.get("/workflow-config", response_model=Dict[str, List[WorkflowConfigItemOut]])
async def get_workflow_config(
    scope: str, config_type: Optional[str] = None
) -> Dict[str, List[WorkflowConfigItemOut]]:
    """Fetch workflow configuration items as dropdown options for template forms."""
    where_parts = ["scope IN (:scope, 'shared')", "is_active = TRUE"]
    params: dict = {"scope": scope}
    if config_type:
        where_parts.append("config_type = :config_type")
        params["config_type"] = config_type

    rows = await database.fetch_all(
        f"""
        SELECT {_WORKFLOW_CONFIG_COLUMNS}
        FROM geo_workflow_config
        WHERE {' AND '.join(where_parts)}
        ORDER BY config_type, sort_order
        """,
        params,
    )

    grouped: Dict[str, List[WorkflowConfigItemOut]] = {}
    for row in rows:
        r = _stringify_id(dict(row))
        ct = r["config_type"]
        if ct not in grouped:
            grouped[ct] = []
        grouped[ct].append(WorkflowConfigItemOut(**r))

    return grouped


class WorkflowConfigCreate(BaseModel):
    config_type: str
    scope: str
    key: str
    parent_key: Optional[str] = None
    value: dict
    sort_order: int = 0


class WorkflowConfigUpdate(BaseModel):
    value: Optional[dict] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    parent_key: Optional[str] = None


@router.post(
    "/workflow-config", status_code=201, response_model=WorkflowConfigItemOut
)
async def create_workflow_config_item(
    data: WorkflowConfigCreate,
) -> WorkflowConfigItemOut:
    """Create a new workflow configuration item."""
    result = await database.fetch_one(
        f"""
        INSERT INTO geo_workflow_config
            (config_type, scope, key, parent_key, value, sort_order)
        VALUES
            (:config_type, :scope, :key, :parent_key, :value::jsonb, :sort_order)
        RETURNING {_WORKFLOW_CONFIG_COLUMNS}
        """,
        {
            "config_type": data.config_type,
            "scope": data.scope,
            "key": data.key,
            "parent_key": data.parent_key,
            "value": json.dumps(data.value),
            "sort_order": data.sort_order,
        },
    )
    return WorkflowConfigItemOut(**_stringify_id(dict(result)))


@router.put("/workflow-config/{item_id}", response_model=WorkflowConfigItemOut)
async def update_workflow_config_item(
    item_id: UUID, data: WorkflowConfigUpdate
) -> WorkflowConfigItemOut:
    """Update a workflow configuration item."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_workflow_config WHERE id = :id",
        {"id": item_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Config item not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    allowed = {"value", "sort_order", "is_active", "parent_key"}
    sets = []
    params: dict = {"id": item_id}
    for col, val in updates.items():
        if col not in allowed:
            continue
        if col == "value":
            params[col] = json.dumps(val)
            sets.append(f"{col} = :{col}::jsonb")
        else:
            params[col] = val
            sets.append(f"{col} = :{col}")

    if sets:
        await database.execute(
            f"UPDATE geo_workflow_config SET {', '.join(sets)} WHERE id = :id",
            params,
        )

    row = await database.fetch_one(
        f"SELECT {_WORKFLOW_CONFIG_COLUMNS} FROM geo_workflow_config WHERE id = :id",
        {"id": item_id},
    )
    return WorkflowConfigItemOut(**_stringify_id(dict(row)))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/workflow-config/{item_id}", status_code=204)
async def delete_workflow_config_item(item_id: UUID) -> None:
    """Delete a workflow configuration item."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_workflow_config WHERE id = :id",
        {"id": item_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Config item not found")

    await database.execute(
        "DELETE FROM geo_workflow_config WHERE id = :id",
        {"id": item_id},
    )
    return None


@router.get("", response_model=TemplateListOut)
async def list_templates(
    client_id: Optional[UUID] = None,
    include_builtin: bool = True,
    active_only: bool = True,
    task_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> TemplateListOut:
    """List report templates."""
    where_parts: list[str] = []
    params: dict = {}
    if active_only:
        where_parts.append("is_active = TRUE")
    if task_type:
        where_parts.append("COALESCE(task_type, 'analysis') = :task_type")
        params["task_type"] = task_type

    if client_id:
        if include_builtin:
            where_parts.append("(is_builtin = TRUE OR client_id = :client_id)")
        else:
            where_parts.append("client_id = :client_id")
        params["client_id"] = client_id
    elif not include_builtin:
        where_parts.append("client_id IS NULL")

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_report_templates{where_sql}", params
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT {_TEMPLATE_COLUMNS} FROM geo_report_templates
        {where_sql}
        ORDER BY sort_order, created_at
        OFFSET :offset LIMIT :limit
        """,
        {**params, "offset": (page - 1) * limit, "limit": limit},
    )

    return TemplateListOut(
        data=[TemplateOut(**dict(r)) for r in rows],
        pagination=TemplatePagination(
            page=page,
            total=total,
            pages=math.ceil(total / limit) if total else 1,
        ),
    )


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(template_id: UUID) -> TemplateOut:
    """Get a single report template by UUID."""
    row = await database.fetch_one(
        f"SELECT {_TEMPLATE_COLUMNS} FROM geo_report_templates WHERE id = :id",
        {"id": template_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateOut(**dict(row))


@router.post("", status_code=201, response_model=TemplateOut)
async def create_template(data: TemplateCreate) -> TemplateOut:
    """Create a new report template (Admin-created or client custom templates)."""
    values = (
        data.name, data.description, data.icon, data.data_domains,
        data.default_prompt, data.client_id, data.is_builtin, data.is_active,
        data.sort_order, data.task_type, json.dumps(data.defaults or {}),
        json.dumps(data.wizard_config or {}), data.cron_expression,
        data.cron_timezone or "Asia/Shanghai", data.schedule_enabled,
    )
    sql = f"""
        INSERT INTO geo_report_templates (
            name, description, icon, data_domains, default_prompt,
            client_id, is_builtin, is_active, sort_order, task_type,
            defaults, wizard_config, cron_expression, cron_timezone, schedule_enabled
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11::jsonb, $12::jsonb, $13, $14, $15
        )
        RETURNING {_TEMPLATE_COLUMNS}
    """
    if data.client_id:
        async def operation(conn):
            return await conn.fetchrow(sql, *values)

        row = await WorkspaceWriteCoordinator(database.pool()).execute(
            str(data.client_id), operation
        )
    else:
        async with database.pool().acquire() as conn:
            row = await conn.fetchrow(sql, *values)
    return TemplateOut(**dict(row))


@router.put("/{template_id}", response_model=TemplateOut)
async def update_template(template_id: UUID, data: TemplateUpdate) -> TemplateOut:
    """Update a report template. Built-in templates have a restricted edit surface."""
    existing = await database.fetch_one(
        "SELECT is_builtin, client_id::text AS client_id FROM geo_report_templates WHERE id = :id",
        {"id": template_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}

    if existing["is_builtin"]:
        allowed_builtin = {
            "name", "description", "icon", "default_prompt", "data_domains",
            "defaults", "wizard_config", "sort_order", "is_active",
        }
        updates = {k: v for k, v in updates.items() if k in allowed_builtin}

    allowed_all = {
        "name", "description", "icon", "data_domains", "default_prompt",
        "is_active", "is_builtin", "sort_order", "task_type",
        "defaults", "wizard_config", "cron_expression", "cron_timezone",
        "schedule_enabled",
    }
    jsonb_cols = {"defaults", "wizard_config"}

    if updates:
        sets = []
        params: dict = {"id": template_id}
        for col, val in updates.items():
            if col not in allowed_all:
                continue
            if col in jsonb_cols:
                params[col] = json.dumps(val)
                sets.append(f"{col} = :{col}::jsonb")
            else:
                params[col] = val
                sets.append(f"{col} = :{col}")
        sets.append("updated_at = NOW()")
        update_sql, update_args = _named_to_positional(
            f"UPDATE geo_report_templates SET {', '.join(sets)} WHERE id = :id",
            params,
        )
        if existing["client_id"]:
            async def operation(conn):
                await conn.execute(update_sql, *update_args)

            await WorkspaceWriteCoordinator(database.pool()).execute(
                str(existing["client_id"]), operation
            )
        else:
            await database.execute(
                f"UPDATE geo_report_templates SET {', '.join(sets)} WHERE id = :id",
                params,
            )

    row = await database.fetch_one(
        f"SELECT {_TEMPLATE_COLUMNS} FROM geo_report_templates WHERE id = :id",
        {"id": template_id},
    )
    return TemplateOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: UUID) -> None:
    """Delete a report template. Built-in templates cannot be deleted."""
    existing = await database.fetch_one(
        "SELECT is_builtin, client_id::text AS client_id FROM geo_report_templates WHERE id = :id",
        {"id": template_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    if existing["is_builtin"]:
        raise HTTPException(status_code=403, detail="Built-in templates cannot be deleted. Disable them instead.")

    if existing["client_id"]:
        async def operation(conn):
            await conn.execute(
                "DELETE FROM geo_report_templates WHERE id = $1",
                template_id,
            )

        await WorkspaceWriteCoordinator(database.pool()).execute(
            str(existing["client_id"]), operation
        )
    else:
        # Global, non-built-in templates have no Workspace identity to fence.
        # Delete them directly in one transaction; never synthesize a
        # ``workspace-lifecycle:None`` advisory key.
        async with database.pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM geo_report_templates WHERE id = $1",
                    template_id,
                )
    return None
