"""
SVG chart rendering helpers used by the report renderer.

Pure functions (no external state) that return inline SVG strings for bar /
area / pie / scatter / grouped-bar charts. Extracted from ``routers/tasks.py``
in Phase 3A refactor (2026-04-25).
"""

from __future__ import annotations

import math
import re as _re

from .markdown import escape

__all__ = [
    "build_chart_svg",
    "svg_bar",
    "svg_area",
    "svg_pie",
    "svg_scatter",
    "svg_grouped_bar",
    "CHART_PALETTE",
    "PLATFORM_COLORS",
    "series_color",
    "fmt_num",
    "fmt_tick",
    "is_numeric",
    "nice_max",
]


CHART_PALETTE = [
    "#6366f1", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#ec4899", "#14b8a6", "#3b82f6",
]
PLATFORM_COLORS = {
    "chatgpt": "#10b981",
    "gemini": "#6366f1",
    "aimode": "#f59e0b",
    "ai_mode": "#f59e0b",
}


def series_color(key: str, idx: int) -> str:
    lk = key.lower().replace(" ", "").replace("_", "").replace("-", "")
    for p, c in PLATFORM_COLORS.items():
        if p.replace("_", "") in lk:
            return c
    return CHART_PALETTE[idx % len(CHART_PALETTE)]


def fmt_num(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:,.2f}" if v != int(v) else f"{int(v):,}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def fmt_tick(v) -> str:
    s = str(v)
    if len(s) > 10 and _re.match(r'\d{4}-\d{2}-\d{2}', s):
        return s[5:10]
    if len(s) > 12:
        return s[:10] + "…"
    return s


def is_numeric(v) -> bool:
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except (ValueError, TypeError):
            return False
    return False


def nice_max(v: float) -> float:
    """Round up to a nice axis maximum."""
    if v <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(v))
    normalized = v / mag
    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10
    return nice * mag


def build_chart_svg(columns: list, rows: list, chart_type: str, title: str) -> str:
    """Build an inline SVG chart from columns + rows data."""
    if not columns or not rows:
        return ""

    x_key = columns[0]

    col1_is_category = (
        len(columns) >= 3
        and all(isinstance(r[1], str) for r in rows)
        and any(not is_numeric(r[1]) for r in rows)
    )
    is_multi_series = (
        col1_is_category
        and any(is_numeric(r[2]) if len(r) > 2 else False for r in rows)
    )

    if is_multi_series:
        groups = list(dict.fromkeys(str(r[1]) for r in rows))
        x_values = list(dict.fromkeys(str(r[0]) for r in rows))
        if x_values and _re.match(r'\d{4}-\d{2}', x_values[0]):
            x_values.sort()
        series_keys = groups
        chart_data = []
        for xv in x_values:
            point = {x_key: xv}
            for g in groups:
                match = next((r for r in rows if str(r[0]) == xv and str(r[1]) == g), None)
                point[g] = float(match[2]) if match and is_numeric(match[2]) else 0
            chart_data.append(point)
    else:
        chart_data = []
        for row in rows:
            point = {}
            for i, col in enumerate(columns):
                point[col] = row[i] if i < len(row) else None
            chart_data.append(point)
        x_sample = chart_data[0].get(x_key) if chart_data else None
        if isinstance(x_sample, str) and _re.match(r'\d{4}-\d{2}', x_sample):
            chart_data.sort(key=lambda p: str(p.get(x_key, "")))
        series_keys = [c for c in columns[1:] if chart_data and is_numeric(chart_data[0].get(c))]
        if not series_keys:
            series_keys = columns[1:]

    if not chart_data or not series_keys:
        return ""

    ct = chart_type.lower() if chart_type else "auto"
    if ct in ("pie", "donut"):
        detected = "pie"
    elif ct == "bar":
        detected = "bar"
    elif ct in ("area", "line"):
        detected = "area"
    elif ct == "auto":
        x_sample = chart_data[0].get(x_key)
        x_is_date = isinstance(x_sample, str) and bool(_re.match(r'\d{4}-\d{2}', str(x_sample)))
        if x_is_date:
            detected = "area"
        elif len(chart_data) <= 8:
            detected = "bar"
        else:
            detected = "area"
    else:
        detected = "bar"

    if detected == "pie":
        return svg_pie(chart_data, x_key, series_keys)
    elif detected == "area":
        return svg_area(chart_data, x_key, series_keys)
    else:
        return svg_bar(chart_data, x_key, series_keys)


def svg_bar(data: list, x_key: str, series: list) -> str:
    """Generate a bar chart SVG."""
    W, H = 700, 260
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 20, 16, 48
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    n = len(data)
    ns = len(series)
    if n == 0 or ns == 0:
        return ""

    max_val = 0
    for point in data:
        for s in series:
            v = point.get(s)
            if is_numeric(v):
                max_val = max(max_val, abs(float(v)))
    if max_val == 0:
        max_val = 1

    axis_max = nice_max(max_val)

    group_w = chart_w / n
    bar_gap = max(2, group_w * 0.15)
    bar_total_w = group_w - bar_gap
    bar_w = bar_total_w / ns

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="chart-svg">']

    svg.append("<defs>")
    for i, s in enumerate(series):
        color = series_color(s, i)
        svg.append(
            f'<linearGradient id="bg{i}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity="0.9"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0.5"/>'
            f'</linearGradient>'
        )
    svg.append("</defs>")

    for i in range(5):
        y = PAD_T + chart_h - (chart_h * i / 4)
        val = axis_max * i / 4
        svg.append(f'<line x1="{PAD_L}" y1="{y}" x2="{W - PAD_R}" y2="{y}" stroke="#e5e7eb" stroke-width="0.5"/>')
        svg.append(f'<text x="{PAD_L - 8}" y="{y + 4}" text-anchor="end" fill="#9ca3af" font-size="10">{fmt_num(val)}</text>')

    for di, point in enumerate(data):
        gx = PAD_L + di * group_w + bar_gap / 2
        for si, s in enumerate(series):
            v = point.get(s)
            val = float(v) if is_numeric(v) else 0
            bh = (val / axis_max) * chart_h if axis_max > 0 else 0
            bx = gx + si * bar_w
            by = PAD_T + chart_h - bh
            r = min(4, bar_w / 2)
            svg.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
                f'rx="{r}" fill="url(#bg{si})"/>'
            )

        lx = gx + bar_total_w / 2
        label = fmt_tick(point.get(x_key, ""))
        svg.append(
            f'<text x="{lx:.1f}" y="{H - 8}" text-anchor="middle" fill="#9ca3af" font-size="10">'
            f'{escape(label)}</text>'
        )

    if ns > 1:
        legend_x = PAD_L
        for i, s in enumerate(series):
            color = series_color(s, i)
            svg.append(f'<rect x="{legend_x}" y="{H - 24}" width="10" height="10" rx="2" fill="{color}"/>')
            svg.append(f'<text x="{legend_x + 14}" y="{H - 15}" fill="#6b7280" font-size="10">{escape(s)}</text>')
            legend_x += len(s) * 7 + 28

    svg.append("</svg>")
    return "\n".join(svg)


def svg_area(data: list, x_key: str, series: list) -> str:
    """Generate an area/line chart SVG."""
    W, H = 700, 260
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 20, 16, 48
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    n = len(data)
    ns = len(series)
    if n < 2 or ns == 0:
        return svg_bar(data, x_key, series)

    max_val = 0
    for point in data:
        for s in series:
            v = point.get(s)
            if is_numeric(v):
                max_val = max(max_val, abs(float(v)))
    if max_val == 0:
        max_val = 1
    axis_max = nice_max(max_val)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="chart-svg">']

    svg.append("<defs>")
    for i, s in enumerate(series):
        color = series_color(s, i)
        svg.append(
            f'<linearGradient id="ag{i}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="5%" stop-color="{color}" stop-opacity="0.2"/>'
            f'<stop offset="95%" stop-color="{color}" stop-opacity="0.02"/>'
            f'</linearGradient>'
        )
    svg.append("</defs>")

    for i in range(5):
        y = PAD_T + chart_h - (chart_h * i / 4)
        val = axis_max * i / 4
        svg.append(f'<line x1="{PAD_L}" y1="{y}" x2="{W - PAD_R}" y2="{y}" stroke="#e5e7eb" stroke-width="0.5"/>')
        svg.append(f'<text x="{PAD_L - 8}" y="{y + 4}" text-anchor="end" fill="#9ca3af" font-size="10">{fmt_num(val)}</text>')

    step = max(1, n // 8)
    for di in range(0, n, step):
        point = data[di]
        px = PAD_L + (di / (n - 1)) * chart_w
        label = fmt_tick(point.get(x_key, ""))
        svg.append(f'<text x="{px:.1f}" y="{H - 8}" text-anchor="middle" fill="#9ca3af" font-size="10">{escape(label)}</text>')

    for si, s in enumerate(series):
        color = series_color(s, si)
        points = []
        for di, point in enumerate(data):
            v = point.get(s)
            val = float(v) if is_numeric(v) else 0
            px = PAD_L + (di / (n - 1)) * chart_w
            py = PAD_T + chart_h - (val / axis_max) * chart_h
            points.append((px, py))

        if not points:
            continue

        path_d = f"M {points[0][0]:.1f},{points[0][1]:.1f}"
        for px, py in points[1:]:
            path_d += f" L {px:.1f},{py:.1f}"
        area_d = path_d + f" L {points[-1][0]:.1f},{PAD_T + chart_h:.1f} L {points[0][0]:.1f},{PAD_T + chart_h:.1f} Z"
        svg.append(f'<path d="{area_d}" fill="url(#ag{si})"/>')
        svg.append(f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
        for px, py in points:
            svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}" stroke="white" stroke-width="1.5"/>')

    if ns > 1:
        legend_x = PAD_L
        for i, s in enumerate(series):
            color = series_color(s, i)
            svg.append(f'<rect x="{legend_x}" y="{H - 24}" width="10" height="10" rx="2" fill="{color}"/>')
            svg.append(f'<text x="{legend_x + 14}" y="{H - 15}" fill="#6b7280" font-size="10">{escape(s)}</text>')
            legend_x += len(s) * 7 + 28

    svg.append("</svg>")
    return "\n".join(svg)


def svg_pie(data: list, x_key: str, series: list) -> str:
    """Generate a donut/pie chart SVG."""
    W, H = 400, 280
    CX, CY = 160, 130
    R_OUTER, R_INNER = 90, 55

    value_key = series[0] if series else ""
    if not value_key:
        return ""

    slices = []
    total = 0
    for point in data:
        v = point.get(value_key)
        val = float(v) if is_numeric(v) else 0
        label = str(point.get(x_key, ""))
        if val > 0:
            slices.append((label, val))
            total += val

    if total == 0 or not slices:
        return ""

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="chart-svg">']
    angle = -90

    for i, (label, val) in enumerate(slices):
        pct = val / total
        sweep = pct * 360
        color = series_color(label, i)

        if sweep >= 359.99:
            svg.append(f'<circle cx="{CX}" cy="{CY}" r="{R_OUTER}" fill="{color}" stroke="white" stroke-width="2"/>')
            svg.append(f'<circle cx="{CX}" cy="{CY}" r="{R_INNER}" fill="white"/>')
            angle += sweep
            continue

        start_rad = math.radians(angle)
        end_rad = math.radians(angle + sweep)

        x1_o = CX + R_OUTER * math.cos(start_rad)
        y1_o = CY + R_OUTER * math.sin(start_rad)
        x2_o = CX + R_OUTER * math.cos(end_rad)
        y2_o = CY + R_OUTER * math.sin(end_rad)
        x1_i = CX + R_INNER * math.cos(end_rad)
        y1_i = CY + R_INNER * math.sin(end_rad)
        x2_i = CX + R_INNER * math.cos(start_rad)
        y2_i = CY + R_INNER * math.sin(start_rad)

        large = 1 if sweep > 180 else 0

        d = (
            f"M {x1_o:.2f},{y1_o:.2f} "
            f"A {R_OUTER},{R_OUTER} 0 {large} 1 {x2_o:.2f},{y2_o:.2f} "
            f"L {x1_i:.2f},{y1_i:.2f} "
            f"A {R_INNER},{R_INNER} 0 {large} 0 {x2_i:.2f},{y2_i:.2f} Z"
        )
        svg.append(f'<path d="{d}" fill="{color}" stroke="white" stroke-width="2"/>')
        angle += sweep

    ly = 30
    for i, (label, val) in enumerate(slices):
        color = series_color(label, i)
        pct = val / total * 100
        svg.append(f'<rect x="280" y="{ly}" width="10" height="10" rx="2" fill="{color}"/>')
        svg.append(f'<text x="296" y="{ly + 9}" fill="#374151" font-size="11">{escape(label)}</text>')
        svg.append(f'<text x="296" y="{ly + 22}" fill="#9ca3af" font-size="10">{fmt_num(val)} ({pct:.1f}%)</text>')
        ly += 36

    svg.append("</svg>")
    return "\n".join(svg)


def svg_scatter(quadrants: list) -> str:
    """Generate an SVG scatter chart for topic quadrants (visibility × citation rate)."""
    if not quadrants:
        return ""

    W, H = 700, 320
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 20, 20, 40
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    points = []
    for tq in quadrants:
        m = tq.get("metrics", {})
        points.append({
            "topic": tq.get("topic", ""),
            "quadrant": tq.get("primary_quadrant", ""),
            "vis": m.get("visibility_score", 0),
            "cit": m.get("citation_rate", 0),
            "mentions": m.get("own_mention_count", 1),
        })

    max_vis = max(0.01, max(p["vis"] for p in points))
    max_cit = max(0.01, max(p["cit"] for p in points))
    max_vis *= 1.1
    max_cit *= 1.1
    mid_x = max_vis * 0.5
    mid_y = max_cit * 0.5

    Q_SVG_COLORS = {
        "强势": {"bg": "rgba(16,185,129,0.06)", "fill": "#10b981"},
        "薄弱": {"bg": "rgba(239,68,68,0.06)", "fill": "#ef4444"},
        "待挖掘": {"bg": "rgba(245,158,11,0.06)", "fill": "#f59e0b"},
        "新兴": {"bg": "rgba(59,130,246,0.06)", "fill": "#3b82f6"},
    }

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="chart-svg">']

    def _px(vis): return PAD_L + (vis / max_vis) * chart_w
    def _py(cit): return PAD_T + chart_h - (cit / max_cit) * chart_h

    svg.append(f'<rect x="{PAD_L}" y="{_py(mid_y)}" width="{_px(mid_x)-PAD_L}" height="{_py(0)-_py(mid_y)}" fill="{Q_SVG_COLORS["待挖掘"]["bg"]}"/>')
    svg.append(f'<rect x="{_px(mid_x)}" y="{_py(mid_y)}" width="{_px(max_vis)-_px(mid_x)}" height="{_py(0)-_py(mid_y)}" fill="{Q_SVG_COLORS["薄弱"]["bg"]}"/>')
    svg.append(f'<rect x="{PAD_L}" y="{PAD_T}" width="{_px(mid_x)-PAD_L}" height="{_py(mid_y)-PAD_T}" fill="{Q_SVG_COLORS["新兴"]["bg"]}"/>')
    svg.append(f'<rect x="{_px(mid_x)}" y="{PAD_T}" width="{_px(max_vis)-_px(mid_x)}" height="{_py(mid_y)-PAD_T}" fill="{Q_SVG_COLORS["强势"]["bg"]}"/>')

    for i in range(5):
        y = PAD_T + chart_h - (chart_h * i / 4)
        val = max_cit * i / 4
        svg.append(f'<line x1="{PAD_L}" y1="{y}" x2="{W-PAD_R}" y2="{y}" stroke="#e5e7eb" stroke-width="0.5"/>')
        svg.append(f'<text x="{PAD_L-8}" y="{y+4}" text-anchor="end" fill="#9ca3af" font-size="10">{round(val*100)}%</text>')
    for i in range(5):
        x = PAD_L + (chart_w * i / 4)
        val = max_vis * i / 4
        svg.append(f'<line x1="{x}" y1="{PAD_T}" x2="{x}" y2="{PAD_T+chart_h}" stroke="#e5e7eb" stroke-width="0.5"/>')
        svg.append(f'<text x="{x}" y="{H-8}" text-anchor="middle" fill="#9ca3af" font-size="10">{round(val*100)}%</text>')

    svg.append(f'<line x1="{_px(mid_x)}" y1="{PAD_T}" x2="{_px(mid_x)}" y2="{PAD_T+chart_h}" stroke="#d1d5db" stroke-width="1" stroke-dasharray="4,4"/>')
    svg.append(f'<line x1="{PAD_L}" y1="{_py(mid_y)}" x2="{W-PAD_R}" y2="{_py(mid_y)}" stroke="#d1d5db" stroke-width="1" stroke-dasharray="4,4"/>')

    svg.append(f'<text x="{PAD_L + chart_w/2}" y="{H-2}" text-anchor="middle" fill="#6b7280" font-size="11">可见度 (Visibility)</text>')
    svg.append(f'<text x="12" y="{PAD_T + chart_h/2}" text-anchor="middle" fill="#6b7280" font-size="11" transform="rotate(-90, 12, {PAD_T + chart_h/2})">引用率 (Citation)</text>')

    max_mentions = max(1, max(p["mentions"] for p in points))
    for p in points:
        cx = _px(p["vis"])
        cy = _py(p["cit"])
        r = 5 + (p["mentions"] / max_mentions) * 10
        color = Q_SVG_COLORS.get(p["quadrant"], {}).get("fill", "#6b7280")
        svg.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{color}" fill-opacity="0.7" stroke="{color}" stroke-width="1.5">'
            f'<title>{escape(p["topic"])} — 可见度 {round(p["vis"]*100)}%, 引用率 {round(p["cit"]*100)}%</title>'
            f'</circle>'
        )

    svg.append("</svg>")
    return "\n".join(svg)


def svg_grouped_bar(platform_recs: list) -> str:
    """Generate an SVG grouped bar chart for platform engine breakdown."""
    has_breakdown = any(r.get("engine_breakdown") for r in platform_recs)
    if not has_breakdown:
        return ""

    W, H = 700, 270
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 20, 36, 32
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    all_engines: list[str] = []
    for rec in platform_recs:
        for e in (rec.get("engine_breakdown", {}) or {}).keys():
            if e not in all_engines:
                all_engines.append(e)

    n = len(platform_recs)
    ns = len(all_engines)
    if n == 0 or ns == 0:
        return ""

    normalized_recs = []
    for rec in platform_recs:
        bd = rec.get("engine_breakdown", {}) or {}
        total = sum(bd.values()) or 1
        normalized_recs.append({**rec, "_norm_breakdown": {e: c / total for e, c in bd.items()}})

    max_val = 0
    for rec in normalized_recs:
        for v in rec["_norm_breakdown"].values():
            max_val = max(max_val, float(v))
    if max_val == 0:
        max_val = 1
    axis_max = nice_max(max_val)

    group_w = chart_w / n
    bar_gap = max(2, group_w * 0.15)
    bar_total_w = group_w - bar_gap
    bar_w = bar_total_w / ns

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="chart-svg">']

    svg.append("<defs>")
    for i, eng in enumerate(all_engines):
        color = PLATFORM_COLORS.get(eng.lower(), CHART_PALETTE[i % len(CHART_PALETTE)])
        svg.append(
            f'<linearGradient id="eg{i}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity="0.9"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0.5"/>'
            f'</linearGradient>'
        )
    svg.append("</defs>")

    for i in range(5):
        y = PAD_T + chart_h - (chart_h * i / 4)
        val = axis_max * i / 4
        svg.append(f'<line x1="{PAD_L}" y1="{y}" x2="{W-PAD_R}" y2="{y}" stroke="#e5e7eb" stroke-width="0.5"/>')
        svg.append(f'<text x="{PAD_L-8}" y="{y+4}" text-anchor="end" fill="#9ca3af" font-size="10">{round(val*100)}%</text>')

    for di, rec in enumerate(normalized_recs):
        gx = PAD_L + di * group_w + bar_gap / 2
        bd = rec.get("_norm_breakdown", {})
        for si, eng in enumerate(all_engines):
            val = float(bd.get(eng, 0))
            bh = (val / axis_max) * chart_h if axis_max > 0 else 0
            bx = gx + si * bar_w
            by = PAD_T + chart_h - bh
            r = min(4, bar_w / 2)
            svg.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
                f'rx="{r}" fill="url(#eg{si})"/>'
            )

        lx = gx + bar_total_w / 2
        label = escape(rec.get("platform_type", "")[:10])
        svg.append(f'<text x="{lx:.1f}" y="{H-8}" text-anchor="middle" fill="#9ca3af" font-size="10">{label}</text>')

    legend_x = W - PAD_R
    for eng in reversed(all_engines):
        color = PLATFORM_COLORS.get(eng.lower(), CHART_PALETTE[all_engines.index(eng) % len(CHART_PALETTE)])
        text_w = len(eng) * 7 + 18
        legend_x -= text_w
        svg.append(f'<rect x="{legend_x}" y="8" width="10" height="10" rx="2" fill="{color}"/>')
        svg.append(f'<text x="{legend_x+14}" y="17" fill="#6b7280" font-size="10">{escape(eng)}</text>')

    svg.append("</svg>")
    return "\n".join(svg)
