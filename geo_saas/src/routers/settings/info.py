"""
Client info + global config + workflow_config router.

Phase 3A.2 refactor (2026-04-25): extracted from ``routers/settings.py``.
Owns the read-only "what does this client/server look like" endpoints.

Endpoints (mounted under ``/api/settings``):
    - GET /info             — client configuration row
    - GET /config           — single global config value by key
    - GET /workflow-config  — workflow_config rows for a scope, grouped by config_type
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import database

from ._helpers import serialize_row

router = APIRouter(tags=["Brand Settings - Info"])


class ClientInfoOut(BaseModel):
    """Mirror of ``geo_clients`` row. The table is wide and forward-evolving
    (cron columns, agent quotas, onboarding flags), so we allow extras."""

    model_config = {"extra": "allow"}


class ConfigValueOut(BaseModel):
    key: str
    value: str


class WorkflowConfigItemOut(BaseModel):
    model_config = {"extra": "allow"}


@router.get("/info", response_model=ClientInfoOut)
async def get_client_info(client_id: UUID) -> ClientInfoOut:
    """Get the client configuration dimensions allowed for this SaaS tenant."""
    row = await database.fetch_one(
        "SELECT * FROM geo_clients WHERE id = :client_id",
        {"client_id": client_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientInfoOut(**serialize_row(row))


@router.get("/config", response_model=ConfigValueOut)
async def get_global_config(key: str) -> ConfigValueOut:
    """Read a single global configuration value by key."""
    row = await database.fetch_one(
        "SELECT key, value FROM geo_global_settings WHERE key = :key",
        {"key": key},
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return ConfigValueOut(key=row["key"], value=row["value"])


@router.get(
    "/workflow-config", response_model=Dict[str, List[WorkflowConfigItemOut]]
)
async def get_workflow_config(
    scope: str, config_type: Optional[str] = None
) -> Dict[str, List[WorkflowConfigItemOut]]:
    """Fetch workflow configuration items grouped by config_type."""
    where_parts = ["scope IN (:scope, 'shared')", "is_active = TRUE"]
    params: dict = {"scope": scope}
    if config_type:
        where_parts.append("config_type = :config_type")
        params["config_type"] = config_type

    rows = await database.fetch_all(
        f"""
        SELECT * FROM geo_workflow_config
        WHERE {' AND '.join(where_parts)}
        ORDER BY config_type, sort_order
        """,
        params,
    )

    grouped: Dict[str, List[WorkflowConfigItemOut]] = {}
    for row in rows:
        r = serialize_row(row)
        ct = r["config_type"]
        grouped.setdefault(ct, []).append(WorkflowConfigItemOut(**r))

    return grouped
