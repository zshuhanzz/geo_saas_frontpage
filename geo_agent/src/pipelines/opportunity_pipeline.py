"""
Opportunity Discovery Pipeline — upgraded 4-step workflow.

Steps:
  1. Topic 四象限定位 — Classify each Topic into quadrants (强势/薄弱/待挖掘/新兴)
  2. 选题机会挖掘     — Discover content angles with opportunity scores
  3. 平台引用关系分析  — Analyze platform-engine citation relationships
  4. 综合输出         — Synthesize structured JSON + markdown report

Output: structured JSON with topic_quadrants, content_opportunities, platform_recommendations
plus an insights_markdown for display.
"""
import json
import logging
import asyncio
from typing import Any
from datetime import datetime, timezone

from google.genai import types

from llm.client import get_genai_client, get_model_id
from pipelines.base import WorkflowStep, run_pipeline, append_status_log
from database import get_pool
from routers.tasks import register_pipeline

logger = logging.getLogger(__name__)


# ─── LLM helper ─────────────────────────────────────────────────────

async def _llm_json(client, model_id: str, prompt: str, label: str = "llm") -> dict:
    """Call Gemini and parse JSON from response. Retries up to 3 times."""
    for attempt in range(1, 4):
        try:
            response = await client.aio.models.generate_content(
                model=model_id, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as e:
            logger.warning(f"[OPPORTUNITY] {label} attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(2)
    raise RuntimeError(f"{label} failed after 3 attempts")


async def _llm_text(client, model_id: str, prompt: str, label: str = "llm") -> str:
    """Call Gemini and return text. Retries up to 3 times."""
    for attempt in range(1, 4):
        try:
            response = await client.aio.models.generate_content(
                model=model_id, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=8192,
                ),
            )
            return response.text or ""
        except Exception as e:
            logger.warning(f"[OPPORTUNITY] {label} attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(2)
    raise RuntimeError(f"{label} failed after 3 attempts")


# ─── Step 1: Topic Quadrant Classification ───────────────────────────

async def step_topic_quadrant(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Classify each Topic into quadrants based on visibility, citation, and trend data."""
    await append_status_log(pool, task_id, {"step": 1, "event": "detail", "label": "正在查询 Topic 数据..."})

    # Fetch all active topics for client.
    # v1.2: geo_client_topics.products TEXT[] was dropped — Own products
    # now live in geo_client_topic_products WHERE product_role='own'.
    # Aggregate to a TEXT[] inline so downstream code keeps the same shape.
    topics = await pool.fetch(
        """SELECT ct.id, ct.topic_name,
                  COALESCE(
                    (SELECT ARRAY_AGG(tp.product_name ORDER BY tp.product_name)
                     FROM geo_client_topic_products tp
                     WHERE tp.topic_id = ct.id
                       AND tp.client_id = ct.client_id
                       AND tp.product_role = 'own'
                       AND tp.is_active = true),
                    ARRAY[]::TEXT[]
                  ) AS products
           FROM geo_client_topics ct
           WHERE ct.client_id = $1::uuid""",
        client_id,
    )
    if not topics:
        return {"topic_quadrants": [], "_topic_data": {}}

    # For each topic, compute: own brand visibility, competitor citations, trend
    topic_data = {}
    for t in topics:
        topic_name = t["topic_name"]

        # Own brand mention rate.
        # v1.2: geo_company_mentions → geo_brand_mentions; is_own_brand →
        # brand_role='own'.
        own_mentions = await pool.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE bm.brand_role = 'own') AS own_count,
                 COUNT(*) AS total_prompts,
                 AVG(bm.mention_position) FILTER (WHERE bm.brand_role = 'own') AS avg_pos
               FROM geo_client_prompts cp
               LEFT JOIN geo_brand_mentions bm ON bm.client_prompt_id = cp.id
               WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid AND cp.is_active = true""",
            client_id, t["id"],
        )

        # Competitor citation rate
        competitor_cites = await pool.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE gcd.id IS NULL) AS competitor_cite_count,
                 COUNT(*) FILTER (WHERE gcd.id IS NOT NULL) AS own_cite_count,
                 COUNT(*) AS total_citations
               FROM geo_citations gc
               JOIN geo_client_prompts cp ON gc.client_prompt_id = cp.id
               LEFT JOIN geo_client_domains gcd ON gc.source_domain = gcd.domain AND gcd.client_id = cp.client_id
               WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid""",
            client_id, t["id"],
        )

        # Trend: compare recent 2 weeks vs prior 2 weeks
        trend_data = await pool.fetchrow(
            """WITH recent AS (
                 SELECT COUNT(*) AS cnt FROM geo_results gr
                 JOIN geo_client_prompts cp ON gr.client_prompt_id = cp.id
                 WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid
                   AND gr.ingested_at >= NOW() - INTERVAL '14 days'
               ), prior AS (
                 SELECT COUNT(*) AS cnt FROM geo_results gr
                 JOIN geo_client_prompts cp ON gr.client_prompt_id = cp.id
                 WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid
                   AND gr.ingested_at >= NOW() - INTERVAL '28 days'
                   AND gr.ingested_at < NOW() - INTERVAL '14 days'
               )
               SELECT recent.cnt AS recent_cnt, prior.cnt AS prior_cnt
               FROM recent, prior""",
            client_id, t["id"],
        )

        own_count = own_mentions["own_count"] or 0 if own_mentions else 0
        total_prompts = own_mentions["total_prompts"] or 0 if own_mentions else 0
        comp_cite = competitor_cites["competitor_cite_count"] or 0 if competitor_cites else 0
        own_cite = competitor_cites["own_cite_count"] or 0 if competitor_cites else 0
        recent_cnt = trend_data["recent_cnt"] or 0 if trend_data else 0
        prior_cnt = trend_data["prior_cnt"] or 0 if trend_data else 0

        has_content = own_count > 0
        ai_cites_brand = own_cite > 0
        trend_rising = recent_cnt > prior_cnt * 1.2 if prior_cnt > 0 else recent_cnt > 5

        # Decision tree for primary quadrant
        if trend_rising:
            primary = "新兴"
            action = "抢占"
        elif has_content and ai_cites_brand:
            primary = "强势"
            action = "维护"
        elif has_content and not ai_cites_brand:
            primary = "薄弱"
            action = "修复"
        else:
            primary = "待挖掘"
            action = "进攻"

        # Optional secondary tag
        secondary = None
        if primary != "新兴" and trend_rising:
            secondary = "新兴"
        elif primary == "待挖掘" and trend_rising:
            secondary = "趋势上升"

        visibility_score = round(own_count / total_prompts, 2) if total_prompts > 0 else 0
        total_cites = (competitor_cites["total_citations"] or 0) if competitor_cites else 0
        citation_rate = round(own_cite / total_cites, 2) if total_cites > 0 else 0
        comp_citation_rate = round(comp_cite / total_cites, 2) if total_cites > 0 else 0

        # products is TEXT[] — join into a comma-separated string
        products_list = t["products"] or []
        product_str = ", ".join(products_list) if products_list else ""

        topic_data[topic_name] = {
            "topic": topic_name,
            "product": product_str,
            "topic_id": str(t["id"]),
            "primary_quadrant": primary,
            "secondary_quadrant": secondary,
            "action": action,
            "metrics": {
                "visibility_score": visibility_score,
                "citation_rate": citation_rate,
                "competitor_citation_rate": comp_citation_rate,
                "trend_direction": "rising" if trend_rising else "stable",
                "own_mention_count": own_count,
                "total_prompts": total_prompts,
            },
        }

    quadrants = list(topic_data.values())
    await append_status_log(pool, task_id, {
        "step": 1, "event": "detail",
        "label": f"已分析 {len(quadrants)} 个 Topic 的四象限定位",
    })

    return {"topic_quadrants": quadrants, "_topic_data": topic_data}


# ─── Step 2: Content Opportunity Discovery ───────────────────────────

async def step_content_opportunities(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Use LLM to discover content angles based on quadrant data and citation analysis."""
    topic_quadrants = inputs.get("topic_quadrants", [])
    if not topic_quadrants:
        return {"content_opportunities": []}

    await append_status_log(pool, task_id, {"step": 2, "event": "detail", "label": "正在分析引用内容，挖掘选题机会..."})

    # Gather citation data for actionable topics (not 强势)
    actionable = [t for t in topic_quadrants if t["primary_quadrant"] != "强势"]
    if not actionable:
        actionable = topic_quadrants[:3]  # fallback: analyze top 3

    citation_context = []
    for t in actionable:
        topic_id = t.get("topic_id", "")
        if not topic_id:
            continue
        # Get competitor cited URLs and content
        comp_cites = await pool.fetch(
            """SELECT gc.source_url, gc.source_domain, gc.source_label, gc.domain_category,
                      cp.text AS prompt_text
               FROM geo_citations gc
               JOIN geo_client_prompts cp ON gc.client_prompt_id = cp.id
               LEFT JOIN geo_client_domains gcd ON gc.source_domain = gcd.domain AND gcd.client_id = cp.client_id
               WHERE cp.client_id = $1::uuid AND cp.topic_id = $2::uuid
                 AND gcd.id IS NULL
               ORDER BY gc.source_position ASC
               LIMIT 20""",
            client_id, topic_id,
        )
        citation_context.append({
            "topic": t["topic"],
            "quadrant": t["primary_quadrant"],
            "action": t["action"],
            "competitor_citations": [
                {"url": r["source_url"], "domain": r["source_domain"],
                 "label": r["source_label"], "category": r["domain_category"],
                 "prompt": r["prompt_text"]}
                for r in comp_cites
            ],
        })

    # Also gather prompts related to these topics for linking
    # Deduplicate by prompt text, aggregate platforms
    prompt_map = {}
    for t in actionable:
        topic_id = t.get("topic_id", "")
        if not topic_id:
            continue
        prompts = await pool.fetch(
            """SELECT id, text, platform, intent
               FROM geo_client_prompts
               WHERE client_id = $1::uuid AND topic_id = $2::uuid AND is_active = true
               ORDER BY text, platform
               LIMIT 30""",
            client_id, topic_id,
        )
        # Deduplicate: group by text, keep first id, collect all platforms
        seen_texts: dict[str, dict] = {}
        for p in prompts:
            txt = p["text"]
            if txt in seen_texts:
                if p["platform"] not in seen_texts[txt]["platforms"]:
                    seen_texts[txt]["platforms"].append(p["platform"])
            else:
                seen_texts[txt] = {"id": str(p["id"]), "text": txt, "platforms": [p["platform"]]}
        prompt_map[t["topic"]] = list(seen_texts.values())

    # Brand profile for context
    bp_row = await pool.fetchrow(
        "SELECT brand_name, target_audience, key_messages FROM geo_brand_profiles WHERE client_id = $1::uuid",
        client_id,
    )
    brand_name = bp_row["brand_name"] if bp_row else "品牌"

    # LLM call to discover content opportunities
    model_id = await get_model_id("pro")
    client_llm = await get_genai_client(model_id, role="pro")

    prompt = f"""你是 GEO（Generative Engine Optimization）内容策略专家。
基于以下品牌 "{brand_name}" 的 Topic 四象限诊断和竞品引用数据，挖掘具体的内容选题机会。

## Topic 四象限诊断

{json.dumps(topic_quadrants, ensure_ascii=False, indent=2)}

## 竞品引用数据

{json.dumps(citation_context, ensure_ascii=False, indent=2)}

## 任务

对每个可行动的 Topic（非"强势"的 Topic），产出 2-3 个内容选题机会。每个选题机会包含：
1. angle: 推荐的内容切入角度（一句话标题）
2. opportunity_score: 机会评分 1-10（搜索量 × 品牌覆盖缺口）
3. competitor_refs: 竞品在这个角度的引用参考（1-2句话描述）
4. recommended_metrics: 推荐优化的 metrics（从 readability/answerability/trustworthy/freshness 中选）
5. recommended_subgoals: 推荐的 sub-goals（从 content_understandability/machine_readability/information_presentation/audience_fit/platform_fit/authority_eeat/verifiability/trending_relevance/publish_timeliness 中选）
6. source_quadrant: 来自哪个象限

输出 JSON 数组，每个元素包含上述字段和 topic（Topic 名称）。按 opportunity_score 降序排列。"""

    opportunities_raw = await _llm_json(client_llm, model_id, prompt, "content_opportunities")

    # Attach related_prompts and products from DB data
    opportunities = opportunities_raw if isinstance(opportunities_raw, list) else opportunities_raw.get("opportunities", [])
    # Build topic→products lookup from quadrant data
    topic_products = {t.get("topic", ""): t.get("product", "") for t in topic_quadrants}
    for opp in opportunities:
        topic = opp.get("topic", "")
        related = prompt_map.get(topic, [])
        opp["related_prompts"] = [p["id"] for p in related[:10]]
        # Store deduplicated prompt details (text + platforms) for report rendering
        opp["related_prompt_details"] = [
            {"text": p["text"], "platforms": p["platforms"]}
            for p in related[:10]
        ]
        opp["products"] = topic_products.get(topic, "")

    await append_status_log(pool, task_id, {
        "step": 2, "event": "detail",
        "label": f"已发现 {len(opportunities)} 个内容选题机会",
    })

    return {"content_opportunities": opportunities}


# ─── Step 3: Platform-Engine Citation Analysis ───────────────────────

async def step_platform_analysis(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Analyze which publishing platforms get cited by which AI engines."""
    await append_status_log(pool, task_id, {"step": 3, "event": "detail", "label": "正在分析平台-AI引擎引用关系..."})

    # Aggregate citation data by domain_category × platform
    rows = await pool.fetch(
        """SELECT
             COALESCE(gc.domain_category, '其他') AS platform_type,
             gr.platform AS ai_engine,
             COUNT(*) AS cite_count
           FROM geo_citations gc
           JOIN geo_client_prompts cp ON gc.client_prompt_id = cp.id
           JOIN geo_results gr ON gc.result_id = gr.result_id
           WHERE cp.client_id = $1::uuid
           GROUP BY COALESCE(gc.domain_category, '其他'), gr.platform
           ORDER BY cite_count DESC""",
        client_id,
    )

    if not rows:
        return {"platform_recommendations": []}

    # Build platform × engine matrix
    from collections import defaultdict
    platform_engine = defaultdict(lambda: defaultdict(int))
    platform_total = defaultdict(int)
    engine_total = defaultdict(int)

    for r in rows:
        pt = r["platform_type"]
        engine = r["ai_engine"]
        cnt = r["cite_count"]
        platform_engine[pt][engine] += cnt
        platform_total[pt] += cnt
        engine_total[engine] += cnt

    grand_total = sum(platform_total.values()) or 1

    recommendations = []
    for pt in sorted(platform_total.keys(), key=lambda k: platform_total[k], reverse=True):
        engines_sorted = sorted(platform_engine[pt].items(), key=lambda x: x[1], reverse=True)
        top_engines = [e[0] for e in engines_sorted[:3]]
        citation_share = round(platform_total[pt] / grand_total, 2)
        priority = "high" if citation_share >= 0.2 else ("medium" if citation_share >= 0.1 else "low")
        recommendations.append({
            "platform_type": pt,
            "engines": top_engines,
            "citation_share": citation_share,
            "priority": priority,
            "engine_breakdown": {e: c for e, c in engines_sorted},
        })

    await append_status_log(pool, task_id, {
        "step": 3, "event": "detail",
        "label": f"已分析 {len(recommendations)} 个发布平台的引用关系",
    })

    return {"platform_recommendations": recommendations}


# ─── Step 4: Synthesize Output ───────────────────────────────────────

async def step_synthesize_output(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Generate markdown report + combine structured JSON output."""
    topic_quadrants = inputs.get("topic_quadrants", [])
    content_opportunities = inputs.get("content_opportunities", [])
    platform_recommendations = inputs.get("platform_recommendations", [])

    await append_status_log(pool, task_id, {"step": 4, "event": "detail", "label": "正在生成综合分析报告..."})

    # Brand name
    bp_row = await pool.fetchrow(
        "SELECT brand_name FROM geo_brand_profiles WHERE client_id = $1::uuid", client_id,
    )
    brand_name = bp_row["brand_name"] if bp_row else "品牌"

    # LLM: generate insights markdown
    model_id = await get_model_id("pro")
    client_llm = await get_genai_client(model_id, role="pro")

    prompt = f"""你是 GEO 分析报告撰写专家。基于以下结构化分析数据，为品牌 "{brand_name}" 生成一份优化机会分析报告。

## Topic 四象限诊断
{json.dumps(topic_quadrants, ensure_ascii=False, indent=2)}

## 选题机会
{json.dumps(content_opportunities, ensure_ascii=False, indent=2)}

## 平台引用关系
{json.dumps(platform_recommendations, ensure_ascii=False, indent=2)}

## 报告要求
1. 用 Markdown 格式输出
2. 包含四象限诊断总结（每个象限有多少 Topic，重点关注哪些）
3. 选题机会优先级排序和行动建议
4. 平台分发策略建议
5. 语言：简洁商业风格，数据驱动
6. 报告中所有日期必须使用实际的当前日期（今天是 {datetime.now(timezone.utc).strftime('%Y年%m月%d日')}），不要使用任何示例日期或占位日期"""

    insights_md = await _llm_text(client_llm, model_id, prompt, "synthesize_report")

    # Build final structured output
    output = {
        "analysis_task_id": task_id,
        "client_id": client_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic_quadrants": topic_quadrants,
        "content_opportunities": content_opportunities,
        "platform_recommendations": platform_recommendations,
        "insights_markdown": insights_md,
        "model_used": model_id,
    }

    return {"_output": output, "model_used": model_id}


# ─── Pipeline Registration ───────────────────────────────────────────

OPPORTUNITY_STEPS = [
    WorkflowStep(1, "topic_quadrant", "Topic 四象限定位", step_topic_quadrant),
    WorkflowStep(2, "content_opportunities", "选题机会挖掘", step_content_opportunities),
    WorkflowStep(3, "platform_analysis", "平台引用关系分析", step_platform_analysis),
    WorkflowStep(4, "synthesize_output", "综合输出", step_synthesize_output),
]


async def run_opportunity_pipeline(task_id: str, inputs: dict, client_id: str):
    await run_pipeline(task_id, OPPORTUNITY_STEPS, inputs, client_id)


register_pipeline("opportunity_discovery", run_opportunity_pipeline)
