"""
High-level section builders for the HTML report renderer.

Dispatches to task_type-specific renderers (analysis / content_generation /
opportunity_discovery / generic), and provides the helper renderers for
scoring cards, recommendations, content plans, etc.

Extracted from ``routers/tasks.py`` in Phase 3A refactor (2026-04-25).
"""

from __future__ import annotations

from .charts import build_chart_svg, svg_grouped_bar, svg_scatter, PLATFORM_COLORS
from .markdown import escape, inline_md, md_to_html, strip_content_artifacts

__all__ = ["build_output_sections", "section"]


# ───────── Chinese label maps ─────────

SECTION_TITLES_ZH = {
    "insights_markdown": "洞察报告",
    "quality_score": "质量评分",
    "charts": "图表",
    "variables": "数据变量",
    "faqs": "FAQ 内容",
    "content_markdown": "正文内容",
    "recommendations": "优化建议",
    "title": "标题",
    "meta_description": "Meta 描述",
    "raft_scores": "RAFT 质量评分",
    "strengths": "内容优势",
    "improvement_suggestions": "改进建议",
    "target_prompts": "目标 Prompts",
    "target_keywords": "目标关键词",
    "content_plan": "内容规划",
    "content_type": "内容类型",
    "strategy_context": "策略背景",
    "brief_title": "Brief 标题",
    "objective": "目标",
    "target_audience": "目标受众",
    "key_messages": "核心信息",
    "content_requirements": "内容要求",
    "geo_optimization_tips": "GEO 优化建议",
    "success_metrics": "成功指标",
}

RAFT_DIM_ZH = {
    "readability": "可读性",
    "answerability": "可回答性",
    "trustworthiness": "可信度",
    "timeliness": "时效性",
}

CONTENT_TYPE_ZH = {
    "faq": "FAQ 问答",
    "article": "文章",
    "aeo_article": "AEO 文章",
    "recommendations": "优化建议",
    "brief": "内容 Brief",
}

QUALITY_DIMS_ZH = {
    "data_accuracy_score": "数据准确性",
    "consistency_score": "逻辑一致性",
    "completeness_score": "内容完整性",
    "overall_score": "综合评分",
}

QUADRANT_COLORS_HTML = {
    "强势": {"bg": "#f0fdf4", "border": "#10b981", "text": "#065f46"},
    "薄弱": {"bg": "#fef2f2", "border": "#ef4444", "text": "#991b1b"},
    "待挖掘": {"bg": "#fffbeb", "border": "#f59e0b", "text": "#92400e"},
    "新兴": {"bg": "#eff6ff", "border": "#3b82f6", "text": "#1e40af"},
}
QUADRANT_ACTIONS = {"强势": "维护", "薄弱": "修复", "待挖掘": "进攻", "新兴": "抢占"}
QUADRANT_DESC = {
    "强势": "品牌已被 AI 引用，需维护",
    "薄弱": "有内容但未被引用，需修复",
    "待挖掘": "缺乏内容覆盖，需进攻",
    "新兴": "搜索趋势上升，需抢占",
}


# ───────── Dispatchers ─────────

def section(title: str, body: str) -> str:
    return f'<div class="section"><h2>{escape(title)}</h2>\n{body}\n</div>'


def build_output_sections(output: dict, task_type: str) -> str:
    """Convert task output JSON into styled HTML sections, with proper markdown
    rendering and Chinese labels. Dispatches to type-specific builders."""
    if not isinstance(output, dict) or not output:
        return '<div class="section"><p>暂无报告数据。</p></div>'

    if task_type == "analysis":
        return _build_analysis_sections(output)
    elif task_type == "content_generation":
        return _build_content_sections(output)
    elif task_type == "opportunity_discovery":
        return _build_opportunity_sections(output)
    else:
        return _build_generic_sections(output)


# ───────── Analysis ─────────

def _build_analysis_sections(output: dict) -> str:
    """Render analysis report: quality score → charts → insights markdown."""
    parts = []

    qs = output.get("quality_score")
    if isinstance(qs, dict) and qs.get("overall_score") is not None:
        score_html = _render_quality_score(qs)
        parts.append(section("质量评审", score_html))

    charts = output.get("charts", [])
    if charts:
        charts_html = _render_analysis_charts(charts)
        if charts_html:
            parts.append(section("数据图表", charts_html))

    md = output.get("insights_markdown", "")
    if md:
        parts.append(section("洞察报告", md_to_html(md)))

    return "\n".join(parts) if parts else '<div class="section"><p>暂无报告数据。</p></div>'


def _render_quality_score(qs: dict) -> str:
    """Render analysis quality score with all 4 dimensions as a visual grid."""
    dims = ["data_accuracy_score", "consistency_score", "completeness_score", "overall_score"]
    cards = []
    for dim in dims:
        score = qs.get(dim)
        if score is None:
            continue
        label = QUALITY_DIMS_ZH.get(dim, dim)
        pct = int(float(score) / 5 * 100) if str(score).replace(".", "").isdigit() else 0
        cards.append(
            f'<div class="raft-card">'
            f'<div class="raft-label">{escape(label)}</div>'
            f'<div class="raft-score">{escape(str(score))}<span class="raft-max">/5</span></div>'
            f'<div class="raft-bar"><div class="raft-fill" style="width:{pct}%"></div></div>'
            f'</div>'
        )

    parts = []
    if cards:
        parts.append(f'<div class="raft-grid">{"".join(cards)}</div>')

    summary = qs.get("summary", "")
    if summary:
        parts.append(f'<p>{inline_md(escape(summary))}</p>')

    issues = qs.get("issues", [])
    if issues:
        parts.append('<h4>发现的问题</h4>')
        items = "".join(f'<li>{inline_md(escape(str(i)))}</li>' for i in issues)
        parts.append(f'<ul>{items}</ul>')

    return "\n".join(parts)


def _render_analysis_charts(charts: list) -> str:
    """Render analysis charts as inline SVG visualizations."""
    parts = []
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        nl_query = chart.get("nl_query", "")
        error = chart.get("error", "")
        columns = chart.get("columns", [])
        rows = chart.get("rows", [])

        if error:
            parts.append(
                f'<div class="card chart-card">'
                f'<h4>{escape(nl_query)}</h4>'
                f'<p class="chart-error">数据获取失败: {escape(error)}</p>'
                f'</div>'
            )
            continue

        if not columns or not rows:
            continue

        ct = chart.get("chart_type") or chart.get("type", "auto")
        svg = build_chart_svg(columns, rows, ct, nl_query)
        if svg:
            parts.append(
                f'<div class="chart-card">'
                f'<h4>{escape(nl_query)}</h4>'
                f'{svg}'
                f'</div>'
            )

    return "\n".join(parts)


# ───────── Content Generation ─────────

def _build_content_sections(output: dict) -> str:
    """Render content generation report with structured sections."""
    parts = []
    content_type = output.get("content_type", "")

    ct_label = CONTENT_TYPE_ZH.get(content_type, content_type)
    if ct_label:
        parts.append(f'<div class="type-badge">{escape(ct_label)}</div>')

    raft = output.get("raft_scores")
    qr = output.get("quality_review")
    if isinstance(raft, dict) and raft:
        parts.append(section("RAFT 质量评分", _render_raft_scores(raft)))
    elif isinstance(qr, dict) and qr:
        parts.append(section("质量评审", _render_quality_review(qr)))

    if content_type == "faq":
        faqs = output.get("faqs", [])
        if faqs:
            faq_html = []
            for i, faq in enumerate(faqs):
                if isinstance(faq, dict):
                    q = faq.get("question", "")
                    a = faq.get("answer", "")
                    faq_html.append(
                        f'<div class="card">'
                        f'<p class="faq-q"><strong>Q{i+1}:</strong> {inline_md(escape(q))}</p>'
                        f'<div class="faq-a">{md_to_html(a)}</div>'
                        f'</div>'
                    )
            parts.append(section("FAQ 内容", "\n".join(faq_html)))
        else:
            md = output.get("content_markdown", "") or output.get("content", "")
            if md:
                parts.append(section("FAQ 内容", md_to_html(strip_content_artifacts(md))))

    elif content_type in ("article", "aeo_article"):
        title = output.get("title", "")
        if title:
            parts.append(f'<div class="section"><h2>{escape(title)}</h2>')
            meta = output.get("meta_description", "")
            if meta:
                parts.append(f'<p class="meta-desc"><em>{escape(meta)}</em></p>')
            parts.append('</div>')
        md = output.get("content_markdown", "") or output.get("content", "")
        if md:
            parts.append(section("正文内容", md_to_html(strip_content_artifacts(md))))

    elif content_type == "recommendations":
        recs = output.get("recommendations", [])
        if recs:
            parts.append(section("优化建议", _render_recommendations(recs)))
        summary = output.get("summary", "")
        if summary:
            parts.append(section("总结", md_to_html(summary)))

    elif content_type == "brief":
        for key in ("brief_title", "objective", "target_audience"):
            val = output.get(key, "")
            if val:
                label = SECTION_TITLES_ZH.get(key, key)
                parts.append(section(label, f'<p>{inline_md(escape(str(val)))}</p>'))
        for key in ("key_messages", "geo_optimization_tips", "success_metrics"):
            vals = output.get(key, [])
            if vals and isinstance(vals, list):
                label = SECTION_TITLES_ZH.get(key, key)
                items = "".join(f'<li>{inline_md(escape(str(v)))}</li>' for v in vals)
                parts.append(section(label, f'<ul>{items}</ul>'))
        cr = output.get("content_requirements", [])
        if cr:
            cr_html = []
            for item in cr:
                if isinstance(item, dict):
                    cr_html.append(
                        f'<div class="card">'
                        f'<p><strong>{escape(item.get("section", ""))}</strong></p>'
                        f'<p>{escape(item.get("guidelines", ""))}</p>'
                        f'</div>'
                    )
            parts.append(section("内容要求", "\n".join(cr_html)))
        md = output.get("content_markdown", "")
        if md:
            parts.append(section("正文内容", md_to_html(strip_content_artifacts(md))))

    else:
        md = output.get("content_markdown", "") or output.get("content", "")
        if md:
            parts.append(section("正文内容", md_to_html(strip_content_artifacts(md))))

    strengths = output.get("strengths", [])
    if strengths and isinstance(strengths, list):
        items = "".join(f'<li>{inline_md(escape(str(s)))}</li>' for s in strengths)
        parts.append(section("内容优势", f'<ul>{items}</ul>'))

    suggestions = output.get("improvement_suggestions", [])
    if suggestions and isinstance(suggestions, list):
        items = "".join(f'<li>{inline_md(escape(str(s)))}</li>' for s in suggestions)
        parts.append(section("改进建议", f'<ul>{items}</ul>'))

    plan = output.get("content_plan")
    if isinstance(plan, dict) and plan:
        parts.append(section("内容规划", _render_content_plan(plan)))

    tp = output.get("target_prompts", [])
    if tp and isinstance(tp, list):
        items = "".join(f'<li>{escape(str(p))}</li>' for p in tp)
        parts.append(section("目标 Prompts", f'<ol>{items}</ol>'))

    kw = output.get("target_keywords", [])
    if kw and isinstance(kw, list):
        badges = " ".join(f'<span class="kw-badge">{escape(str(k))}</span>' for k in kw)
        parts.append(section("目标关键词", f'<div class="kw-list">{badges}</div>'))

    return "\n".join(parts) if parts else '<div class="section"><p>暂无报告数据。</p></div>'


def _render_raft_scores(raft: dict) -> str:
    """Render RAFT scores as a visual grid."""
    dims = ["readability", "answerability", "trustworthiness", "timeliness"]
    cards = []
    for dim in dims:
        score_data = raft.get(dim)
        if not score_data:
            continue
        if isinstance(score_data, dict):
            score = score_data.get("score", "?")
            note = score_data.get("note", "")
        else:
            score = score_data
            note = ""
        label = RAFT_DIM_ZH.get(dim, dim)
        pct = int(float(score) / 5 * 100) if str(score).replace(".", "").isdigit() else 0
        cards.append(
            f'<div class="raft-card">'
            f'<div class="raft-label">{escape(label)}</div>'
            f'<div class="raft-score">{escape(str(score))}<span class="raft-max">/5</span></div>'
            f'<div class="raft-bar"><div class="raft-fill" style="width:{pct}%"></div></div>'
            f'{"<div class=\"raft-note\">" + escape(note) + "</div>" if note else ""}'
            f'</div>'
        )
    overall = raft.get("overall")
    overall_html = ""
    if overall is not None:
        overall_html = f'<div class="raft-overall">综合评分: <strong>{escape(str(overall))}/5</strong></div>'
    return f'<div class="raft-grid">{"".join(cards)}</div>{overall_html}'


def _render_quality_review(qr: dict) -> str:
    """Render content pipeline quality_review as visual cards."""
    parts = []

    scores = qr.get("scores", [])
    if scores:
        cards = []
        for s in scores:
            if not isinstance(s, dict):
                continue
            name = s.get("subgoal_name") or s.get("metric_name", "")
            score = s.get("score", "?")
            comment = s.get("comment", "")
            pct = int(float(score) / 10 * 100) if str(score).replace(".", "").isdigit() else 0
            cards.append(
                f'<div class="raft-card">'
                f'<div class="raft-label">{escape(name)}</div>'
                f'<div class="raft-score">{escape(str(score))}<span class="raft-max">/10</span></div>'
                f'<div class="raft-bar"><div class="raft-fill" style="width:{pct}%"></div></div>'
                f'{"<div class=\"raft-note\">" + escape(comment) + "</div>" if comment else ""}'
                f'</div>'
            )
        if cards:
            parts.append(f'<div class="raft-grid">{"".join(cards)}</div>')

    overall = qr.get("overall_score")
    if overall is not None:
        parts.append(f'<div class="raft-overall">综合评分: <strong>{escape(str(overall))}</strong></div>')

    summary = qr.get("summary", "")
    if summary:
        parts.append(f'<p>{inline_md(escape(summary))}</p>')

    suggestions = qr.get("improvement_suggestions", [])
    if suggestions:
        items = "".join(f'<li>{inline_md(escape(str(s)))}</li>' for s in suggestions)
        parts.append(f'<h4>改进建议</h4><ul>{items}</ul>')

    return "\n".join(parts) if parts else "<p>评审数据未提供</p>"


def _render_recommendations(recs: list) -> str:
    """Render recommendation cards with priority badges."""
    _priority_class = {"high": "priority-high", "medium": "priority-med", "low": "priority-low"}
    cards = []
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        pri = rec.get("priority", "medium")
        cls = _priority_class.get(pri, "priority-med")
        cards.append(
            f'<div class="card rec-card">'
            f'<div class="rec-header">'
            f'<span class="rec-badge {cls}">{escape(pri.upper())}</span>'
            f'<strong>{escape(rec.get("title", ""))}</strong>'
            f'</div>'
            f'<p>{escape(rec.get("description", ""))}</p>'
            f'</div>'
        )
    return "\n".join(cards)


def _render_content_plan(plan: dict) -> str:
    """Render content plan as structured HTML."""
    parts = []
    summary = plan.get("plan_summary", "")
    if summary:
        parts.append(f'<p>{inline_md(escape(summary))}</p>')

    structure = plan.get("content_structure", [])
    if structure and isinstance(structure, list):
        parts.append('<div class="plan-structure">')
        for item in structure:
            if isinstance(item, dict):
                parts.append(
                    f'<div class="card">'
                    f'<p><strong>{escape(item.get("section", ""))}</strong></p>'
                    f'<p>{escape(item.get("purpose", ""))}</p>'
                    f'</div>'
                )
        parts.append('</div>')

    msgs = plan.get("key_messages", [])
    if msgs and isinstance(msgs, list):
        items = "".join(f'<li>{escape(str(m))}</li>' for m in msgs)
        parts.append(f'<h4>核心信息</h4><ul>{items}</ul>')

    raft_focus = plan.get("raft_focus")
    if isinstance(raft_focus, dict):
        primary = raft_focus.get("primary", "")
        notes = raft_focus.get("notes", "")
        label = RAFT_DIM_ZH.get(primary, primary)
        parts.append(f'<p><strong>RAFT 重点:</strong> {escape(label)}{" — " + escape(notes) if notes else ""}</p>')

    return "\n".join(parts) if parts else "<p>—</p>"


# ───────── Opportunity Discovery ─────────

def _build_opportunity_sections(output: dict) -> str:
    """Render opportunity discovery report: quadrant map, content opps, platform recs."""
    parts = []
    prompt_map = output.get("_prompt_map", {})

    quadrants = output.get("topic_quadrants", [])
    if quadrants:
        quad_counts: dict[str, int] = {}
        for tq in quadrants:
            q = tq.get("primary_quadrant", "")
            quad_counts[q] = quad_counts.get(q, 0) + 1

        legend_cards = []
        for q in ("强势", "薄弱", "待挖掘", "新兴"):
            c = QUADRANT_COLORS_HTML.get(q, {})
            count = quad_counts.get(q, 0)
            legend_cards.append(
                f'<div class="quadrant-card" style="border-left:4px solid {c.get("border","#ccc")}; background:{c.get("bg","#fff")};">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                f'<strong style="color:{c.get("text","#333")}">{escape(q)}</strong>'
                f'<span style="font-size:11px;color:{c.get("text","#666")}">策略：{QUADRANT_ACTIONS.get(q,"")}</span>'
                f'</div>'
                f'<p style="font-size:12px;color:{c.get("text","#666")};margin:0 0 4px">{QUADRANT_DESC.get(q,"")}</p>'
                f'<div style="font-size:12px;font-weight:600;color:{c.get("text","#333")}">{count} 个话题</div>'
                f'</div>'
            )
        legend_html = f'<div class="quadrant-grid">{"".join(legend_cards)}</div>'

        scatter_svg = svg_scatter(quadrants)

        rows_html = []
        for tq in quadrants:
            q = tq.get("primary_quadrant", "")
            c = QUADRANT_COLORS_HTML.get(q, {})
            metrics = tq.get("metrics", {})
            vis = metrics.get("visibility_score", 0)
            cit = metrics.get("citation_rate", 0)
            action = tq.get("action") or QUADRANT_ACTIONS.get(q, "")
            sec = tq.get("secondary_quadrant") or ""
            sec_html = f' <span class="metric-pill" style="font-size:10px">{escape(sec)}</span>' if sec else ""
            rows_html.append(
                f'<tr>'
                f'<td><span class="metric-pill" style="background:{c.get("bg","#f3f4f6")};color:{c.get("text","#333")};border:1px solid {c.get("border","#ddd")}">{escape(q)}</span>{sec_html}</td>'
                f'<td>{escape(tq.get("topic", ""))}</td>'
                f'<td>{escape(action)}</td>'
                f'<td>{round(vis * 100)}%</td>'
                f'<td>{round(cit * 100)}%</td>'
                f'</tr>'
            )
        table_html = (
            '<div class="table-wrap"><table>'
            '<thead><tr><th>象限</th><th>话题</th><th>策略</th><th>可见度</th><th>引用率</th></tr></thead>'
            f'<tbody>{"".join(rows_html)}</tbody>'
            '</table></div>'
        )

        parts.append(section("四象限定位模型", legend_html + scatter_svg + table_html))

    opps = output.get("content_opportunities", [])
    if opps:
        opp_cards = []
        for i, opp in enumerate(opps[:8]):
            raw_score = opp.get("opportunity_score") or opp.get("score", 0)
            score = raw_score * 10 if raw_score <= 10 else raw_score
            sq = opp.get("source_quadrant") or opp.get("quadrant", "")
            c = QUADRANT_COLORS_HTML.get(sq, {})
            score_color = "#10b981" if score >= 80 else "#f59e0b" if score >= 60 else "#ef4444"

            metrics_pills = ""
            rec_metrics = opp.get("recommended_metrics", [])
            if rec_metrics:
                pills = "".join(f'<span class="metric-pill">{escape(m)}</span>' for m in rec_metrics)
                metrics_pills = f'<div style="margin-top:6px">{pills}</div>'

            products_html = ""
            products_raw = opp.get("products") or opp.get("product", "")
            if products_raw:
                if isinstance(products_raw, list):
                    prod_pills = "".join(f'<span class="metric-pill" style="background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe">{escape(p)}</span>' for p in products_raw)
                elif isinstance(products_raw, str) and products_raw.strip():
                    prod_pills = "".join(f'<span class="metric-pill" style="background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe">{escape(p.strip())}</span>' for p in products_raw.split(",") if p.strip())
                else:
                    prod_pills = ""
                if prod_pills:
                    products_html = f'<div style="margin-top:6px"><div style="font-size:11px;color:#6b7280;margin-bottom:2px">关联产品：</div>{prod_pills}</div>'

            prompts_html = ""
            prompt_details = opp.get("related_prompt_details", [])
            if prompt_details:
                cards = []
                for pd in prompt_details[:5]:
                    txt = escape(pd.get("text", "")[:120])
                    platforms = pd.get("platforms", [])
                    plat_badges = "".join(
                        f'<span style="display:inline-block;background:#f3f4f6;color:#6b7280;font-size:10px;padding:1px 6px;border-radius:8px;margin-left:4px">{escape(p)}</span>'
                        for p in platforms
                    )
                    cards.append(
                        f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:8px 10px;font-size:12px;color:#374151;display:flex;align-items:center;justify-content:space-between;gap:8px">'
                        f'<span style="flex:1;min-width:0">{txt}</span>'
                        f'<span style="flex-shrink:0">{plat_badges}</span>'
                        f'</div>'
                    )
                prompts_html = f'<div style="margin-top:6px"><div style="font-size:11px;color:#6b7280;margin-bottom:4px">关联 Prompt：</div><div style="display:flex;flex-direction:column;gap:4px">{"".join(cards)}</div></div>'
            else:
                related = opp.get("related_prompts", [])
                if related and prompt_map:
                    resolved = [prompt_map.get(str(pid), "") for pid in related if prompt_map.get(str(pid))]
                    seen = set()
                    unique = []
                    for p in resolved:
                        if p not in seen:
                            seen.add(p)
                            unique.append(p)
                    if unique:
                        cards = "".join(
                            f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:8px 10px;font-size:12px;color:#374151">{escape(p[:120])}</div>'
                            for p in unique[:5]
                        )
                        prompts_html = f'<div style="margin-top:6px"><div style="font-size:11px;color:#6b7280;margin-bottom:4px">关联 Prompt：</div><div style="display:flex;flex-direction:column;gap:4px">{cards}</div></div>'

            comp_html = ""
            comp_refs = opp.get("competitor_refs", [])
            if comp_refs:
                comp_html = f'<span class="metric-pill" style="background:#fef2f2;color:#dc2626;border:1px solid #fca5a5">{len(comp_refs)} 竞品引用</span>'

            opp_cards.append(
                f'<div class="opp-card">'
                f'<div style="display:flex;align-items:center;gap:10px">'
                f'<div style="width:24px;height:24px;border-radius:50%;background:rgba(16,185,129,0.1);color:#10b981;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0">{i+1}</div>'
                f'<div style="flex:1;min-width:0">'
                f'<div style="font-size:14px;font-weight:600">{escape(opp.get("topic", ""))}</div>'
                f'<div style="font-size:13px;color:#6b7280;margin-top:2px">选题方向：{escape(opp.get("angle", ""))}</div>'
                f'</div>'
                f'<span class="metric-pill" style="background:{c.get("bg","#f3f4f6")};color:{c.get("text","#333")};border:1px solid {c.get("border","#ddd")}">{escape(sq)}</span>'
                f'{comp_html}'
                f'<div style="font-size:14px;font-weight:700;color:#10b981;width:36px;text-align:right">{score}</div>'
                f'</div>'
                f'<div class="score-bar" style="margin-top:8px"><div class="score-fill" style="width:{min(100, score)}%;background:{score_color}"></div></div>'
                f'{metrics_pills}{products_html}{prompts_html}'
                f'</div>'
            )
        parts.append(section(f"内容机会 TOP {len(opps[:8])}", "\n".join(opp_cards)))

    platform_recs = output.get("platform_recommendations", [])
    if platform_recs:
        bar_svg = svg_grouped_bar(platform_recs)

        rec_cards = []
        for rec in platform_recs:
            pt = rec.get("platform_type", "")
            engines = rec.get("engines", [])
            share = rec.get("citation_share", 0)
            priority = rec.get("priority", "")
            share_pct = round(share * 100)

            pri_style = (
                'background:#fef2f2;color:#dc2626' if priority == "high"
                else 'background:#fffbeb;color:#d97706' if priority == "medium"
                else 'background:#f0fdf4;color:#16a34a'
            )
            pri_label = "高优" if priority == "high" else "中优" if priority == "medium" else "低优"

            breakdown = rec.get("engine_breakdown", {})
            engine_bar_html = ""
            if breakdown:
                bd_total = sum(breakdown.values()) or 1
                bar_parts = []
                legend_parts = []
                for eng, eng_count in breakdown.items():
                    pct = eng_count / bd_total
                    color = PLATFORM_COLORS.get(eng.lower(), "#8b5cf6")
                    bar_parts.append(f'<div style="width:{round(pct*100)}%;height:100%;background:{color}"></div>')
                    legend_parts.append(f'<span style="font-size:10px;display:inline-flex;align-items:center;gap:2px"><span style="width:6px;height:6px;border-radius:50%;background:{color};display:inline-block"></span>{escape(eng)} {round(pct*100)}%</span>')
                engine_bar_html = (
                    f'<div style="display:flex;align-items:center;gap:8px;margin-top:4px">'
                    f'<span style="font-size:11px;color:#6b7280;flex-shrink:0;width:60px">引擎分布</span>'
                    f'<div class="engine-bar">{"".join(bar_parts)}</div>'
                    f'<div style="display:flex;gap:6px;flex-shrink:0">{"".join(legend_parts)}</div>'
                    f'</div>'
                )

            rec_cards.append(
                f'<div class="platform-card">'
                f'<div style="display:flex;align-items:center;gap:10px">'
                f'<span class="metric-pill" style="font-weight:600">{escape(pt)}</span>'
                f'<span style="flex:1;font-size:13px;color:#6b7280">AI 引擎：{escape(", ".join(engines) if engines else "—")}</span>'
                f'<span class="rec-badge" style="{pri_style}">{pri_label}</span>'
                f'</div>'
                f'<div style="display:flex;align-items:center;gap:8px;margin-top:6px">'
                f'<span style="font-size:11px;color:#6b7280;flex-shrink:0;width:60px">引用占比</span>'
                f'<div class="score-bar"><div class="score-fill" style="width:{share_pct}%"></div></div>'
                f'<span style="font-size:12px;font-weight:600;color:#10b981;width:36px;text-align:right">{share_pct}%</span>'
                f'</div>'
                f'{engine_bar_html}'
                f'</div>'
            )
        parts.append(section("平台引用矩阵", bar_svg + "\n".join(rec_cards)))

    md = output.get("insights_markdown", "")
    if md:
        parts.append(section("洞察报告", md_to_html(md)))

    return "\n".join(parts) if parts else '<div class="section"><p>暂无报告数据。</p></div>'


# ───────── Generic fallback ─────────

def _build_generic_sections(output: dict) -> str:
    """Fallback renderer for unknown task types."""
    parts = []
    for key, value in output.items():
        if key.startswith("_"):
            continue
        title = SECTION_TITLES_ZH.get(key, key.replace("_", " ").title())
        if isinstance(value, str):
            parts.append(section(title, md_to_html(value)))
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                cards = []
                for item in value:
                    inner = "".join(
                        f'<p><strong>{escape(k)}:</strong> {escape(str(v))}</p>'
                        for k, v in item.items() if not k.startswith("_")
                    )
                    cards.append(f'<div class="card">{inner}</div>')
                parts.append(section(title, "\n".join(cards)))
            else:
                items = "".join(f'<li>{escape(str(v))}</li>' for v in value)
                parts.append(section(title, f'<ul>{items}</ul>'))
        elif isinstance(value, dict):
            inner = "".join(
                f'<p><strong>{escape(k)}:</strong> {escape(str(v))}</p>'
                for k, v in value.items() if not k.startswith("_")
            )
            parts.append(section(title, f'<div class="card">{inner}</div>'))
    return "\n".join(parts) if parts else '<div class="section"><p>暂无报告数据。</p></div>'
