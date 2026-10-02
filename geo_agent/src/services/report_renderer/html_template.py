"""
Outer HTML shell used by the report renderer.

The template is a single ``.format()`` string with 5 named placeholders:
``{title}``, ``{brand_name}``, ``{task_type}``, ``{completed_at}``, ``{sections}``.

All literal ``{`` and ``}`` in CSS and body are escaped as ``{{``/``}}``.
Extracted from ``routers/tasks.py`` in Phase 3A refactor (2026-04-25).
"""

from __future__ import annotations

__all__ = ["REPORT_HTML_TEMPLATE"]


REPORT_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — {brand_name}</title>
<style>
  :root {{
    --primary: #10b981;
    --primary-light: #d1fae5;
    --bg: #ffffff;
    --text: #1f2937;
    --text-muted: #6b7280;
    --border: #e5e7eb;
    --card-bg: #f9fafb;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
    color: var(--text);
    background: var(--bg);
    line-height: 1.7;
    padding: 0;
  }}
  .header {{
    position: relative;
    background: linear-gradient(135deg, #065f46 0%, #047857 100%);
    color: white;
    padding: 48px 40px 36px;
    text-align: center;
  }}
  .header-logo {{
    position: absolute;
    left: 40px;
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    font-weight: 600;
    opacity: 0.85;
  }}
  .header-logo-mark {{
    width: 24px;
    height: 24px;
    background: rgba(255,255,255,0.2);
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 700;
  }}
  .header h1 {{
    font-size: 28px;
    font-weight: 700;
    margin-bottom: 8px;
  }}
  .header .meta {{
    font-size: 13px;
    opacity: 0.8;
  }}
  .header .brand {{
    font-size: 14px;
    font-weight: 600;
    background: rgba(255,255,255,0.15);
    display: inline-block;
    padding: 4px 12px;
    border-radius: 6px;
    margin-bottom: 16px;
  }}
  .content {{
    max-width: 900px;
    margin: 0 auto;
    padding: 40px;
  }}
  .section {{
    margin-bottom: 32px;
  }}
  .section h2 {{
    font-size: 20px;
    font-weight: 600;
    color: var(--text);
    padding-bottom: 8px;
    border-bottom: 2px solid var(--primary);
    margin-bottom: 16px;
  }}
  .section h3 {{
    font-size: 16px;
    font-weight: 600;
    margin: 16px 0 8px;
  }}
  .section p {{
    margin-bottom: 12px;
    color: var(--text);
  }}
  .section ul {{
    margin: 8px 0 16px 24px;
  }}
  .section li {{
    margin-bottom: 6px;
  }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
  }}
  .card p {{
    margin-bottom: 6px;
    font-size: 14px;
  }}
  .card strong {{
    color: var(--text);
  }}
  .raft-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
    margin-bottom: 12px;
  }}
  .raft-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
  }}
  .raft-label {{
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 4px;
  }}
  .raft-score {{
    font-size: 24px;
    font-weight: 700;
    color: var(--primary);
  }}
  .raft-max {{
    font-size: 14px;
    font-weight: 400;
    color: var(--text-muted);
  }}
  .raft-bar {{
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    margin-top: 6px;
    overflow: hidden;
  }}
  .raft-fill {{
    height: 100%;
    background: var(--primary);
    border-radius: 2px;
    transition: width 0.3s;
  }}
  .raft-note {{
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 6px;
  }}
  .raft-overall {{
    text-align: center;
    font-size: 16px;
    padding: 12px;
    background: var(--primary-light);
    border-radius: 8px;
    margin-top: 8px;
  }}
  .type-badge {{
    display: inline-block;
    background: var(--primary-light);
    color: #065f46;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 14px;
    border-radius: 20px;
    margin-bottom: 24px;
  }}
  .faq-q {{
    font-size: 15px;
    margin-bottom: 8px !important;
  }}
  .faq-a {{
    color: var(--text);
    font-size: 14px;
  }}
  .faq-a p {{
    margin-bottom: 8px;
  }}
  .meta-desc {{
    font-size: 14px;
    color: var(--text-muted);
    margin-bottom: 16px !important;
  }}
  .rec-card {{
    border-left: 3px solid var(--border);
  }}
  .rec-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }}
  .rec-badge {{
    font-size: 10px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
    letter-spacing: 0.5px;
  }}
  .priority-high {{
    background: #fef2f2;
    color: #dc2626;
  }}
  .priority-med {{
    background: #fffbeb;
    color: #d97706;
  }}
  .priority-low {{
    background: #f0fdf4;
    color: #16a34a;
  }}
  .kw-list {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}
  .kw-badge {{
    display: inline-block;
    background: var(--card-bg);
    border: 1px solid var(--border);
    padding: 3px 10px;
    border-radius: 14px;
    font-size: 13px;
  }}
  .table-wrap {{
    overflow-x: auto;
    margin: 12px 0 16px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  thead {{
    background: var(--card-bg);
  }}
  th {{
    text-align: left;
    font-weight: 600;
    padding: 10px 12px;
    border-bottom: 2px solid var(--border);
    white-space: nowrap;
  }}
  td {{
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
  }}
  tbody tr:hover {{
    background: var(--card-bg);
  }}
  .chart-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .chart-card h4 {{
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 12px;
    color: var(--text);
  }}
  .chart-error {{
    color: #dc2626;
    font-size: 13px;
  }}
  .chart-svg {{
    width: 100%;
    height: auto;
    max-height: 280px;
  }}
  pre {{
    background: #1f2937;
    color: #e5e7eb;
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.5;
    margin: 12px 0;
  }}
  code {{
    font-family: "SF Mono", Menlo, Monaco, monospace;
  }}
  p code {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.9em;
  }}
  ol {{
    margin: 8px 0 16px 24px;
  }}
  ol li {{
    margin-bottom: 6px;
  }}
  h4 {{
    font-size: 14px;
    font-weight: 600;
    margin: 12px 0 6px;
  }}
  .footer {{
    text-align: center;
    padding: 24px 40px;
    font-size: 12px;
    color: var(--text-muted);
    border-top: 1px solid var(--border);
    margin-top: 40px;
  }}
  hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 24px 0;
  }}
  .quadrant-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
    margin-bottom: 20px;
  }}
  .quadrant-card {{
    border-radius: 8px;
    padding: 14px 16px;
  }}
  .opp-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
  }}
  .score-bar {{
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    flex: 1;
  }}
  .score-fill {{
    height: 100%;
    background: var(--primary);
    border-radius: 3px;
    transition: width 0.3s;
  }}
  .engine-bar {{
    height: 8px;
    background: var(--border);
    border-radius: 4px;
    overflow: hidden;
    display: flex;
    flex: 1;
  }}
  .metric-pill {{
    display: inline-block;
    background: var(--primary-light);
    color: #065f46;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 8px;
    border-radius: 12px;
    margin-right: 4px;
  }}
  .prompt-text {{
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.5;
  }}
  .platform-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 10px;
  }}
  @media print {{
    .header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    body {{ padding: 0; }}
    .content {{ padding: 20px; }}
  }}
</style>
</head>
<body>
<div class="header">
  <div class="header-logo">
    <div class="header-logo-mark">A</div>
    AnswerX
  </div>
  <div class="brand">{brand_name}</div>
  <h1>{title}</h1>
  <div class="meta">
    {task_type} &middot; 生成于 {completed_at}
  </div>
</div>
<div class="content">
  {sections}
</div>
<div class="footer">
  由 AnswerX GEO 平台生成 &middot; Powered by AI
</div>
</body>
</html>"""
