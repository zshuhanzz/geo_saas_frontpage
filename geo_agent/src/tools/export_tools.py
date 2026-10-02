"""
Export Tools — Generate HTML reports from chat analysis conversations.

Aggregates insights, charts, and markdown content from agent_messages
for a given thread and renders a styled HTML report using the same
renderers as the Task export pipeline.
"""
import json
import logging
import re as _re
from datetime import datetime, timezone, timedelta

from database import get_pool

logger = logging.getLogger(__name__)

# Filler lines to strip from exported HTML
_FILLER_PATTERNS = [
    _re.compile(r"已为您整理本次对话中的分析内容.*"),
    _re.compile(r"如需导出本次分析为\s*HTML\s*报告.*"),
    _re.compile(r"请点击下方.*下载.*"),
]


# ── Chart normalization ────────────────────────────────────────────────

def _normalize_chart(chart: dict) -> dict:
    """Convert chart_builder format to columns+rows format for _build_chart_svg.

    chart_builder produces: {type, title, data: [{k:v,...}], xKey, yKeys}
    _build_chart_svg expects: {columns: [str], rows: [[val]], chart_type, title}
    """
    # Already in columns+rows format
    if "columns" in chart and ("rows" in chart):
        return chart

    data = chart.get("data", [])
    x_key = chart.get("xKey", "")
    y_keys = chart.get("yKeys", [])
    chart_type = chart.get("type", chart.get("chart_type", "auto"))
    title = chart.get("title", "")

    if not data or not isinstance(data, list):
        return chart

    # If data is list of dicts, convert to columns+rows
    if isinstance(data[0], dict):
        if x_key and y_keys:
            columns = [x_key] + y_keys
        else:
            columns = list(data[0].keys())

        rows = []
        for item in data:
            row = [item.get(col) for col in columns]
            rows.append(row)

        return {
            "columns": columns,
            "rows": rows,
            "chart_type": chart_type,
            "title": title,
        }

    return chart


# ── Aggregation ────────────────────────────────────────────────────────

async def aggregate_chat_analysis(thread_id: str, client_id: str) -> dict:
    """Read AI messages from a thread and extract analysis content.

    Returns a structured dict:
    {
        "turns": [
            {
                "content": "markdown text",
                "charts": [...],
                "created_at": "2026-04-02T...",
            },
            ...
        ],
        "has_content": bool,
        "turn_count": int,
        "chart_count": int,
    }
    """
    pool = await get_pool()

    rows = await pool.fetch(
        """SELECT role, content, tool_results, created_at
           FROM agent_messages
           WHERE thread_id = $1
           ORDER BY created_at ASC""",
        thread_id,
    )

    turns: list[dict] = []
    chart_count = 0

    for r in rows:
        if r["role"] != "ai":
            continue
        content = r["content"] or ""

        # Strip filler lines from content
        lines = content.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if any(p.search(stripped) for p in _FILLER_PATTERNS):
                continue
            cleaned_lines.append(line)
        content = "\n".join(cleaned_lines).strip()

        # Parse tool_results JSONB → extract charts
        charts = []
        raw_tr = r["tool_results"]
        if raw_tr:
            if isinstance(raw_tr, str):
                try:
                    raw_tr = json.loads(raw_tr)
                except (json.JSONDecodeError, TypeError):
                    raw_tr = []
            if isinstance(raw_tr, list):
                for item in raw_tr:
                    if isinstance(item, dict) and item.get("type") not in ("thinking", "widgets"):
                        # Normalize chart format: chart_builder uses
                        # {type, title, data: [{k:v}], xKey, yKeys}
                        # but _build_chart_svg expects columns + rows (list of lists).
                        charts.append(_normalize_chart(item))

        # Skip turns that are purely widget/slot-filling with no real insight
        if not content and not charts:
            continue

        chart_count += len(charts)
        turns.append({
            "content": content,
            "charts": charts,
            "created_at": str(r["created_at"]) if r["created_at"] else "",
        })

    return {
        "turns": turns,
        "has_content": len(turns) > 0 and (chart_count > 0 or any(len(t["content"]) > 50 for t in turns)),
        "turn_count": len(turns),
        "chart_count": chart_count,
    }


# ── HTML Rendering ─────────────────────────────────────────────────────

async def render_chat_analysis_html(thread_id: str, client_id: str) -> str:
    """Generate a complete HTML report from chat analysis turns.

    Reuses the SVG chart renderer and markdown-to-HTML converter
    from routers/tasks.py.
    """
    # Import renderers from tasks module (same process, lazy import to avoid circular)
    from routers.tasks import (
        _md_to_html, _build_chart_svg, _escape, _REPORT_HTML_TEMPLATE,
    )

    pool = await get_pool()
    agg = await aggregate_chat_analysis(thread_id, client_id)

    if not agg["has_content"]:
        return ""

    # Load brand info for header
    brand_row = await pool.fetchrow(
        "SELECT brand_name FROM geo_brand_profiles WHERE client_id = $1::uuid",
        client_id,
    )
    client_row = await pool.fetchrow(
        "SELECT name FROM geo_clients WHERE id = $1::uuid",
        client_id,
    )
    brand_name = (brand_row["brand_name"] if brand_row else None) or \
                 (client_row["name"] if client_row else None) or "AnswerX"

    # Build HTML sections — one per analysis turn
    sections_html_parts: list[str] = []

    for idx, turn in enumerate(agg["turns"]):
        turn_parts: list[str] = []

        # Render charts for this turn
        if turn["charts"]:
            for chart in turn["charts"]:
                if not isinstance(chart, dict):
                    continue
                columns = chart.get("columns", [])
                data_rows = chart.get("rows") or chart.get("data", [])
                chart_type = chart.get("chart_type") or chart.get("type", "auto")
                title = chart.get("title", "")

                svg = _build_chart_svg(columns, data_rows, chart_type, title)
                if svg:
                    turn_parts.append(
                        f'<div class="chart-card">'
                        f'<h4>{_escape(title)}</h4>'
                        f'{svg}'
                        f'</div>'
                    )

        # Render markdown content
        md_content = turn["content"].strip()
        if md_content:
            turn_parts.append(_md_to_html(md_content))

        if turn_parts:
            # Use timestamp as section header (optional, for multi-turn)
            ts = turn.get("created_at", "")[:16]
            if len(agg["turns"]) > 1 and ts:
                header = f"分析 #{idx + 1}"
                sections_html_parts.append(
                    f'<div class="section"><h2>{_escape(header)}</h2>\n'
                    + "\n".join(turn_parts)
                    + "\n</div>"
                )
            else:
                sections_html_parts.append(
                    f'<div class="section">\n'
                    + "\n".join(turn_parts)
                    + "\n</div>"
                )

    if not sections_html_parts:
        return ""

    # Timestamp for report
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    completed_at = now.strftime("%Y-%m-%d %H:%M")

    # Assemble summary line
    summary = f"共 {agg['turn_count']} 轮分析"
    if agg["chart_count"]:
        summary += f"，{agg['chart_count']} 个图表"

    html = _REPORT_HTML_TEMPLATE.format(
        title="对话分析报告",
        brand_name=_escape(brand_name),
        task_type=summary,
        completed_at=completed_at,
        sections="\n".join(sections_html_parts),
    )

    return html
