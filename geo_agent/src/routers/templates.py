"""
Template + workflow-config router.

Extracted from ``routers/tasks.py`` in Phase 3A refactor (2026-04-25).
Owns the read-only endpoints that surface ``geo_report_templates`` rows and
``geo_workflow_config`` step/dictionary data to the SaaS schema-driven wizard.

Endpoints (mounted under ``/api/agent/tasks``):
    - GET  /templates                — list templates (filterable by task_type)
    - GET  /templates/{template_id}  — single-template detail with full wizard_config
    - GET  /workflow-config          — workflow_step rows + referenced dictionary rows for a scope
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/tasks", tags=["tasks", "templates"])


# ─── Response models ──────────────────────────────────────────────────


class TemplateOut(BaseModel):
    """One row of ``geo_report_templates``, hydrated with parsed jsonb columns
    (matches ``_template_row_to_dict`` exactly)."""

    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    data_domains: list[str] = Field(default_factory=list)
    default_prompt: Optional[str] = None
    is_builtin: Optional[bool] = None
    task_type: str
    wizard_config: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)


class WorkflowEntry(BaseModel):
    """A single dictionary or workflow_step row from ``geo_workflow_config``."""

    config_type: str
    scope: str
    key: str
    parent_key: str = ""
    value: dict[str, Any] = Field(default_factory=dict)
    sort_order: Optional[int] = None


class WorkflowConfigOut(BaseModel):
    """Bundle returned by ``GET /workflow-config`` — the SaaS schema-driven
    wizard hits this single endpoint to get everything it needs to render a
    template's steps + resolve ``ref_*`` fields against dictionary rows."""

    scope: str
    steps: list[WorkflowEntry] = Field(default_factory=list)
    dictionary: dict[str, list[WorkflowEntry]] = Field(default_factory=dict)


def _template_row_to_dict(r, has_task_type: bool) -> dict:
    """Serialize a geo_report_templates row into the SaaS wizard payload.

    Parses all jsonb columns so the frontend gets ready-to-use objects rather
    than serialized strings. Keeps column names stable across the list and
    single-template endpoints.
    """
    def _parse_jsonb(raw):
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None

    return {
        "id": str(r["id"]),
        "name": r["name"],
        "description": r["description"],
        "icon": r["icon"],
        "data_domains": r["data_domains"] or [],
        "default_prompt": r["default_prompt"],
        "is_builtin": r["is_builtin"],
        "task_type": r["task_type"] if has_task_type else "analysis",
        "wizard_config": _parse_jsonb(r["wizard_config"]) or {},
        "defaults": _parse_jsonb(r["defaults"]) or {},
    }


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(
    type: Optional[str] = None, client_id: Optional[str] = None
) -> list[TemplateOut]:
    """List task templates from geo_report_templates table, filtered by task_type."""
    pool = await get_pool()

    has_task_type = await pool.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM information_schema.columns
             WHERE table_name = 'geo_report_templates' AND column_name = 'task_type'
           )"""
    )

    if has_task_type:
        conditions = ["is_active = true", "(client_id IS NULL OR client_id = $1::uuid)"]
        params: list = [client_id]
        if type:
            conditions.append(f"COALESCE(task_type, 'analysis') = ${len(params) + 1}")
            params.append(type)
        where = " AND ".join(conditions)
        rows = await pool.fetch(
            f"""SELECT id, name, description, icon, data_domains, default_prompt,
                      is_builtin, is_active, sort_order, wizard_config, defaults,
                      COALESCE(task_type, 'analysis') AS task_type
               FROM geo_report_templates
               WHERE {where}
               ORDER BY task_type, sort_order""",
            *params,
        )
    else:
        if type and type != "analysis":
            return []
        rows = await pool.fetch(
            """SELECT id, name, description, icon, data_domains, default_prompt,
                      is_builtin, is_active, sort_order, wizard_config, defaults
               FROM geo_report_templates
               WHERE is_active = true
                 AND (client_id IS NULL OR client_id = $1::uuid)
               ORDER BY sort_order""",
            client_id,
        )

    return [TemplateOut(**_template_row_to_dict(r, has_task_type)) for r in rows]


@router.get("/templates/{template_id}", response_model=TemplateOut)
async def get_template(template_id: str) -> TemplateOut:
    """Fetch a single template with its full wizard_config payload.

    Used by SaaS wizards to load the schema-driven step configuration for a
    specific template when the user opens the per-template wizard.
    """
    pool = await get_pool()
    has_task_type = await pool.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM information_schema.columns
             WHERE table_name = 'geo_report_templates' AND column_name = 'task_type'
           )"""
    )

    if has_task_type:
        row = await pool.fetchrow(
            """SELECT id, name, description, icon, data_domains, default_prompt,
                      is_builtin, is_active, sort_order, wizard_config, defaults,
                      COALESCE(task_type, 'analysis') AS task_type
               FROM geo_report_templates
               WHERE id = $1::uuid""",
            template_id,
        )
    else:
        row = await pool.fetchrow(
            """SELECT id, name, description, icon, data_domains, default_prompt,
                      is_builtin, is_active, sort_order, wizard_config, defaults
               FROM geo_report_templates
               WHERE id = $1::uuid""",
            template_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateOut(**_template_row_to_dict(row, has_task_type))


@router.get("/workflow-config", response_model=WorkflowConfigOut)
async def get_workflow_config(
    scope: str,
    config_type: Optional[str] = None,
) -> WorkflowConfigOut:
    """Return workflow_step definitions + referenced dictionary rows for a scope.

    This is the single endpoint the SaaS schema-driven wizard hits to get
    everything it needs to render a template's steps:

      - `workflow_step` rows for the given scope, ordered by sort_order (the
        canonical list of steps, their field schemas, and default values)
      - All referenced dictionary rows (goal / analysis_lens / content_metric
        / content_sub_goal / domain / content_type / depth / sort_option /
        etc.) grouped by config_type so FieldRenderer can resolve `ref_*`
        fields against a single in-memory map.

    Params:
      - scope: required. 'analysis' | 'content_generation' | 'shared'
      - config_type: optional. If set, only return that config_type.

    Returns:
      {
        "scope": "analysis",
        "steps": [...],                 # workflow_step rows, sorted
        "dictionary": {                 # keyed by config_type
          "goal":          [{key, parent_key, value, sort_order}, ...],
          "analysis_lens": [...],
          ...
        }
      }
    """
    pool = await get_pool()

    if config_type:
        rows = await pool.fetch(
            """SELECT config_type, scope, key, parent_key, value, sort_order
               FROM geo_workflow_config
               WHERE is_active = true
                 AND config_type = $1
                 AND (scope = $2 OR scope = 'shared')
               ORDER BY config_type, sort_order, key""",
            config_type, scope,
        )
    else:
        rows = await pool.fetch(
            """SELECT config_type, scope, key, parent_key, value, sort_order
               FROM geo_workflow_config
               WHERE is_active = true
                 AND (scope = $1 OR scope = 'shared')
               ORDER BY config_type, sort_order, key""",
            scope,
        )

    steps: list[WorkflowEntry] = []
    dictionary: dict[str, list[WorkflowEntry]] = {}
    for r in rows:
        raw_val = r["value"]
        if isinstance(raw_val, str):
            try:
                val = json.loads(raw_val)
            except json.JSONDecodeError:
                val = {}
        else:
            val = raw_val or {}
        entry = WorkflowEntry(
            config_type=r["config_type"],
            scope=r["scope"],
            key=r["key"],
            parent_key=r["parent_key"] or "",
            value=val,
            sort_order=r["sort_order"],
        )
        if r["config_type"] == "workflow_step" and (r["scope"] == scope):
            steps.append(entry)
        else:
            dictionary.setdefault(r["config_type"], []).append(entry)

    steps.sort(key=lambda s: (s.sort_order or 0, s.key))
    return WorkflowConfigOut(scope=scope, steps=steps, dictionary=dictionary)
