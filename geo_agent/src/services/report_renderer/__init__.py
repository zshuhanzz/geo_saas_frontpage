"""
report_renderer — convert a completed geo_agent_tasks output into styled HTML.

Extracted from ``routers/tasks.py`` in Phase 3A refactor (2026-04-25). The HTML
export endpoint now delegates all rendering to this subpackage; the renderer
itself is framework-agnostic (no FastAPI imports) and can be reused from
future PDF / email / SSR surfaces.

Public API::

    from services.report_renderer import render_task_html

    html = render_task_html(
        task_dict,          # dict from routers/tasks._row_to_dict
        brand_name="...",   # from geo_brand_profiles or fallback
    )

Module layout:
    - ``markdown``     — markdown → HTML (escape, inline formatting, lists, tables)
    - ``charts``       — SVG chart rendering (bar / area / pie / scatter / grouped-bar)
    - ``sections``     — High-level section builders per task_type
    - ``html_template`` — the outer HTML shell (``_REPORT_HTML_TEMPLATE``)
"""

from __future__ import annotations

from datetime import timedelta, timezone

from .html_template import REPORT_HTML_TEMPLATE
from .markdown import escape as _escape
from .sections import build_output_sections

__all__ = ["render_task_html", "build_output_sections"]


_TASK_TYPE_ZH = {
    "analysis": "数据分析报告",
    "content_generation": "内容生成报告",
    "opportunity_discovery": "机会发现报告",
}
_SHANGHAI_TZ = timezone(timedelta(hours=8))


def render_task_html(task: dict, brand_name: str) -> str:
    """Render a completed task to a full HTML document.

    :param task: task row serialized via ``_row_to_dict`` (output already parsed).
    :param brand_name: resolved brand display name (caller decides fallback).
    :return: a full HTML document as a string (UTF-8 encoded when written).
    """
    task_type_raw = task.get("task_type", "analysis")
    output = task.get("output") or {}
    if isinstance(output, str):
        import json as _json
        try:
            output = _json.loads(output)
        except (_json.JSONDecodeError, TypeError):
            output = {}

    sections_html = build_output_sections(output, task_type_raw)

    completed_raw = task.get("completed_at")
    if completed_raw:
        try:
            completed_sha = completed_raw.astimezone(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            completed_sha = str(completed_raw)[:19]
    else:
        completed_sha = ""

    return REPORT_HTML_TEMPLATE.format(
        title=_escape(task.get("task_name") or "报告"),
        brand_name=_escape(brand_name),
        task_type=_escape(_TASK_TYPE_ZH.get(task_type_raw, task_type_raw)),
        completed_at=completed_sha,
        sections=sections_html,
    )
