"""
Task HTML export router.

Extracted from ``routers/tasks.py`` in Phase 3A refactor (2026-04-25). The
HTTP-shell layer here is intentionally thin — all rendering is delegated to
``services.report_renderer.render_task_html``.

Endpoint (mounted under ``/api/agent/tasks``):
    - GET /{task_id}/export?client_id=...&view=true|false  — export HTML report

NOTE on route ordering: this router MUST be ``include_router``ed before
``routers.tasks`` so that ``/{task_id}/export`` matches before the more
generic ``/{task_id}`` task-detail endpoint.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from database import get_pool
from services.report_renderer import render_task_html

from .tasks import _row_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/tasks", tags=["tasks", "export"])


# Non-JSON response — response_model= n/a (returns HTMLResponse).
@router.get("/{task_id}/export")
async def export_task_html(task_id: str, client_id: str, view: bool = False):
    """Export a completed task as a styled HTML report.

    Pulls task + brand info from DB, hydrates prompt UUIDs to text for
    opportunity reports, and delegates rendering to
    ``services.report_renderer.render_task_html``.

    :param task_id: UUID of the task to export.
    :param client_id: Client UUID (required for tenant isolation).
    :param view: If ``True``, response renders inline; if ``False`` (default),
                 sets a ``Content-Disposition: attachment`` header so the
                 browser downloads it as ``report-<id>.html``.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT t.*, c.name AS client_name
           FROM geo_agent_tasks t
           LEFT JOIN geo_clients c ON t.client_id = c.id
           WHERE t.id = $1::uuid AND t.client_id = $2::uuid""",
        task_id, client_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _row_to_dict(row)
    if task.get("status") != "COMPLETED":
        raise HTTPException(status_code=400, detail="Task must be completed before export")

    output = task.get("output") or {}
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            output = {}

    # Resolve prompt UUIDs to text for opportunity reports
    task_type_raw = task.get("task_type", "analysis")
    if task_type_raw == "opportunity_discovery":
        prompt_ids = set()
        for opp in (output.get("content_opportunities") or []):
            for pid in (opp.get("related_prompts") or []):
                prompt_ids.add(str(pid))
        if prompt_ids:
            prompt_rows = await pool.fetch(
                "SELECT id::text, text FROM geo_client_prompts WHERE id = ANY($1::uuid[])",
                list(prompt_ids),
            )
            output["_prompt_map"] = {r["id"]: r["text"] for r in prompt_rows}

    # Brand info
    brand_row = await pool.fetchrow(
        "SELECT brand_name, tone_of_voice FROM geo_brand_profiles WHERE client_id = $1::uuid",
        client_id,
    )
    brand_name = brand_row["brand_name"] if brand_row else (row.get("client_name") or "AnswerX")

    # Re-attach the (possibly-augmented) output so renderer sees _prompt_map.
    task["output"] = output

    html = render_task_html(task, brand_name)

    headers = {}
    if not view:
        headers["Content-Disposition"] = f'attachment; filename="report-{task_id[:8]}.html"'
    return HTMLResponse(content=html, headers=headers)
