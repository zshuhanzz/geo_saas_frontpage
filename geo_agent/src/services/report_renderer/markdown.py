"""
Markdown → HTML rendering helpers used by the report renderer.

All functions are pure (no I/O, no FastAPI imports). Extracted from
``routers/tasks.py`` in Phase 3A refactor (2026-04-25).
"""

from __future__ import annotations

import html as _html
import re as _re

__all__ = [
    "escape",
    "strip_content_artifacts",
    "md_to_html",
    "inline_md",
    "render_md_table",
    "close_lists",
]


def escape(s) -> str:
    return _html.escape(str(s)) if s else ""


def strip_content_artifacts(text: str) -> str:
    """Strip HTML/Schema Markup artifacts from content before rendering."""
    if not text:
        return text
    text = _re.sub(r'```html\s*\n.*?```', '', text, flags=_re.DOTALL)
    text = _re.sub(r'<!--\s*Schema\s*Markup\s*-->.*?</script>', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r'<script[^>]*>.*?</script>', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r'<(?!br\s*/?>)/?[a-zA-Z][^>]*>', '', text)
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def close_lists(parts: list, in_ul: bool, in_ol: bool):
    if in_ul:
        parts.append('</ul>')
    if in_ol:
        parts.append('</ol>')


def inline_md(text: str) -> str:
    """Handle inline markdown: **bold**, *italic*, `code`, [link](url), <br>."""
    text = text.replace("&lt;br&gt;", "<br/>").replace("&lt;br/&gt;", "<br/>").replace("&lt;br /&gt;", "<br/>")
    text = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = _re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = _re.sub(r'`(.+?)`', r'<code>\1</code>', text)

    def _safe_link(m):
        label, url = m.group(1), m.group(2)
        if _re.match(r'(?i)^(javascript|data|vbscript):', url):
            return label
        return f'<a href="{_html.escape(url)}">{label}</a>'

    text = _re.sub(r'\[(.+?)\]\((.+?)\)', _safe_link, text)
    return text


def render_md_table(lines: list[str]) -> str:
    """Convert markdown table lines into an HTML table."""
    rows = []
    separator_idx = -1

    for i, line in enumerate(lines):
        stripped = line.strip().strip("|")
        if _re.match(r'^[\s\-:|]+$', stripped):
            separator_idx = i
            continue
        cells = [c.strip() for c in stripped.split("|")]
        rows.append(cells)

    if not rows:
        return ""

    html = '<div class="table-wrap"><table>'
    if separator_idx >= 0 and rows:
        header = rows[0]
        html += "<thead><tr>"
        for cell in header:
            html += f"<th>{inline_md(escape(cell))}</th>"
        html += "</tr></thead>"
        data_rows = rows[1:]
    else:
        data_rows = rows

    html += "<tbody>"
    for row in data_rows:
        html += "<tr>"
        for cell in row:
            html += f"<td>{inline_md(escape(cell))}</td>"
        html += "</tr>"
    html += "</tbody></table></div>"
    return html


def md_to_html(text: str) -> str:
    """Convert markdown text to HTML. Handles headers, bold, italic, lists,
    numbered lists, code blocks, tables, and paragraphs."""
    if not text or not text.strip():
        return ""

    lines = text.split("\n")
    html_parts = []
    in_list = False
    in_ol = False
    in_code = False
    in_table = False
    code_buf: list[str] = []
    table_buf: list[str] = []

    def _flush_table():
        nonlocal in_table, table_buf
        if table_buf:
            html_parts.append(render_md_table(table_buf))
            table_buf = []
        in_table = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_table:
                _flush_table()
            if in_code:
                html_parts.append(f'<pre><code>{escape(chr(10).join(code_buf))}</code></pre>')
                code_buf = []
                in_code = False
            else:
                close_lists(html_parts, in_list, in_ol)
                in_list = in_ol = False
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue

        if "|" in stripped and stripped.startswith("|"):
            if _re.match(r'^\|[\s\-:|]+\|$', stripped):
                table_buf.append(stripped)
                in_table = True
                continue
            if in_table or (table_buf and len(table_buf) == 1):
                table_buf.append(stripped)
                in_table = True
                continue
            close_lists(html_parts, in_list, in_ol)
            in_list = in_ol = False
            table_buf = [stripped]
            continue

        if table_buf:
            if len(table_buf) >= 2:
                _flush_table()
            else:
                html_parts.append(f'<p>{inline_md(escape(table_buf[0]))}</p>')
                table_buf = []
                in_table = False

        if not stripped:
            close_lists(html_parts, in_list, in_ol)
            in_list = in_ol = False
            continue

        if _re.match(r'^[-*_]{3,}$', stripped):
            close_lists(html_parts, in_list, in_ol)
            in_list = in_ol = False
            html_parts.append('<hr/>')
            continue

        hdr_match = _re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if hdr_match:
            close_lists(html_parts, in_list, in_ol)
            in_list = in_ol = False
            level = min(len(hdr_match.group(1)) + 1, 5)
            html_parts.append(f'<h{level}>{inline_md(escape(hdr_match.group(2)))}</h{level}>')
            continue

        if _re.match(r'^[-*]\s+', stripped):
            if not in_list:
                close_lists(html_parts, False, in_ol)
                in_ol = False
                html_parts.append('<ul>')
                in_list = True
            content = _re.sub(r'^[-*]\s+', '', stripped)
            html_parts.append(f'<li>{inline_md(escape(content))}</li>')
            continue

        ol_match = _re.match(r'^(\d+)[.)]\s+(.+)$', stripped)
        if ol_match:
            if not in_ol:
                close_lists(html_parts, in_list, False)
                in_list = False
                html_parts.append('<ol>')
                in_ol = True
            html_parts.append(f'<li>{inline_md(escape(ol_match.group(2)))}</li>')
            continue

        close_lists(html_parts, in_list, in_ol)
        in_list = in_ol = False
        html_parts.append(f'<p>{inline_md(escape(stripped))}</p>')

    if table_buf and len(table_buf) >= 2:
        _flush_table()
    close_lists(html_parts, in_list, in_ol)
    if in_code and code_buf:
        html_parts.append(f'<pre><code>{escape(chr(10).join(code_buf))}</code></pre>')

    return "\n".join(html_parts)
