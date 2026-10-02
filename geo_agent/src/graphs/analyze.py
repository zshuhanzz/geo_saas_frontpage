"""
Analyze Agent Sub-graph (NL2SQL architecture + slot-filling).

Three modes:
  A. Direct question (specific enough for NL2SQL) -> pipeline runs immediately
  B. Opportunity discovery -> lightweight slot-filling (platform + date),
     then emits task_ready for 3 diagnostics (topic quadrant, topic mining, platform-citation)
  C. Full analysis task -> 6-step slot-filling collects analysis params,
     then emits task_ready for background task

Flow A: intent_router -> nl2sql_generator -> query_executor -> chart_builder -> synthesizer -> END
Flow B: intent_router -> opportunity_slot_filler -> END (emits task_ready SSE event)
Flow C: intent_router -> analysis_slot_filler -> END (emits task_ready SSE event)
"""
import json
import logging
from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage, HumanMessage
from google.genai import types

from models.state import AnalyzeState
from llm.client import get_genai_client, get_model_id, generate_content
from tools.data_tools import execute_sql, ALLOWED_TABLES
from context.pruner import get_prune_max_turns, prune_messages
from services.workflow_config import (
    build_confirm_widget,
    build_summary_display,
    build_widget_from_step,
    load_template_required,
    load_workflow_steps,
)

logger = logging.getLogger(__name__)


# Builtin template names used when the user hasn't picked a template yet.
# These rows in geo_report_templates have empty defaults but every step
# enabled — i.e. "show me the full configuration UI". The chat engine
# resolves them on the first turn and reuses the resolved id thereafter.
DEFAULT_ANALYSIS_TEMPLATE_NAME = "自定义分析"
DEFAULT_CONTENT_TEMPLATE_NAME = "自定义内容"


# ─────────────────────────────────────────────────────────────
# Widget definitions for opportunity discovery (3 nodes)
# ─────────────────────────────────────────────────────────────

OPPORTUNITY_WIDGETS = {
    1: {
        "widget_type": "multi_select",
        "field": "platforms",
        "label": "AI 平台筛选",
        "description": "不选 = 全部平台",
        "options": "__DYNAMIC_PLATFORMS__",
        "required": False,
        "default_value": None,
    },
    2: {
        "widget_type": "date_range",
        "field": "date_range",
        "label": "分析时间范围",
        "required": True,
        "default_value": {"preset": "last_30_days"},
    },
    3: None,  # Confirm — generated dynamically
}


# ─────────────────────────────────────────────────────────────
# Slot-filling system prompt: Opportunity Discovery (3 steps)
# ─────────────────────────────────────────────────────────────

OPPORTUNITY_SLOT_FILL_SYSTEM = """You are Anthony, a GEO analytics assistant for the AnswerX platform.

**重要 — 始终使用用户最近一条消息的语言回复**：如果用户用中文，你必须用中文；如果用户用英文，你必须用英文。Widget 选项的英文 ID（如 "health"、"visibility"）不算用户消息，不要被它们影响语言判断。
**Important — Always reply in the language of the user's MOST RECENT message.** If the user writes in Chinese, you must respond in Chinese. If the user writes in English, you must respond in English. Widget response payloads (English IDs like "health", "visibility") are NOT user messages — never let them flip your output language.

Your job is to help the user configure an "Opportunity Discovery" task in 3 simple steps.

## What this task does
优化机会发现 runs 3 automated diagnostics on the user's GEO data:
1. **Topic 四象限定位** — maps topics by visibility x sentiment into 4 quadrants (star, opportunity, risk, blind spot)
2. **选题机会挖掘** — finds topics where competitors are visible but the brand is missing or weak
3. **平台-AI引擎引用关系** — analyzes which platforms cite which source types most

## Workflow Nodes (3 steps)

### Node 1: Platform Filter (AI 平台筛选) — OPTIONAL
Which AI platforms to include? If the user skips, all platforms are used.
Common platforms: chatgpt, gemini, ai_mode.

### Node 2: Date Range (分析时间范围) — REQUIRED
Analysis date range. Accept relative ("最近7天", "最近30天") or absolute dates.
Default: last 30 days

### Node 3: Confirm (确认执行)
Summarize the configuration and set is_ready=true.

{brand_context}

## Handling widget responses
When the user sends a message that starts with '{{"type": "widget_response"', it is a structured widget response.
Extract the "field" and "value" fields. Use these to populate the corresponding task input directly.
Then immediately advance to the next node.

## Your behavior:
- At the very first turn, briefly introduce the 3 diagnostics, then begin Node 1.
- Track which node you are currently on via the "current_node" field
- Collect ONE node per turn. After the user answers, move to the next node
- Be concise and friendly, use Chinese if the user writes in Chinese
- If the user provides info for multiple nodes at once, extract all of them and jump ahead
- When all nodes are done, move to Node 3 (confirm) and set is_ready=true

## Output format (JSON):
{{
  "message": "Your response to the user (in their language)",
  "current_node": 1-3,
  "task_inputs": {{
    "platforms": ["chatgpt", "gemini", "ai_mode"],
    "date_from": "2026-03-01",
    "date_to": "2026-03-31"
  }},
  "is_ready": true/false,
  "missing_fields": ["field1"]
}}"""


# ─────────────────────────────────────────────────────────────
# Slot-filling system prompt: Full Analysis (DB-driven steps)
# ─────────────────────────────────────────────────────────────
# This template is rendered with the actual step list pulled from
# ``geo_workflow_config`` at runtime — see ``analysis_slot_filler_node`` for
# the rendering logic. The Chat engine never invents step names or labels;
# everything below ``{step_specs}`` is sourced from the DB.

ANALYZE_SLOT_FILL_SYSTEM = """You are Anthony, a GEO analytics assistant for the AnswerX platform.

**重要 — 始终使用用户最近一条消息的语言回复**：如果用户用中文，你必须用中文；如果用户用英文，你必须用英文。Widget 选项的英文 ID（如 "health"、"visibility"）不算用户消息，不要被它们影响语言判断。
**Important — Always reply in the language of the user's MOST RECENT message.** If the user writes in Chinese, you must respond in Chinese. If the user writes in English, you must respond in English. Widget response payloads (English IDs like "health", "visibility") are NOT user messages — never let them flip your output language.

Your job is to help the user configure an analysis task by collecting information step by step.

## Workflow Steps (DB-driven, {step_count} enabled)

Guide the user through these steps **one at a time**, in the listed order.
At the very first turn, briefly tell the user the step list, then begin with the first step.
If the user says "跳过" or "skip" on an OPTIONAL step, use the default value and move on.

{step_specs}

{brand_context}

## Handling widget responses
When the user sends a message that starts with '{{"type": "widget_response"', it is a structured widget response.
Extract the "field" and "value" fields. Use these to populate the corresponding task input directly.
Then immediately advance to the next step.

## Your behavior:
- Show the user the option list for the current step rather than just naming the step.
- Track which step you are on via "current_step_key" — must be one of: {step_keys_csv}.
- Collect ONE step per turn unless the user provides multiple values upfront.
- Be concise and friendly, use Chinese if the user writes in Chinese.
- When the last step is reached and all required values are filled, set is_ready=true and stop asking.
- For text/textarea fields the user can either type a free-form answer or skip with the default.

## Output format (JSON):
{{
  "message": "Your response to the user (in their language)",
  "current_step_key": "<one of the step keys above>",
  "task_inputs": {{ ... arbitrary collected fields keyed by the step's field key ... }},
  "is_ready": true/false,
  "missing_fields": ["field_key", ...]
}}"""


INTENT_ROUTER_SYSTEM = """Classify this analysis request into one of three modes. Reply with ONLY the mode name, nothing else.

Modes:
- direct: The user is asking a specific data question that can be answered with a single SQL query + chart.
  Examples: "show me brand visibility trends", "最近7天的提及量变化", "which competitor has the most citations", "SOV趋势"
- opportunity: The user wants to find content optimization opportunities, weak spots, or areas to improve.
  Examples: "哪些话题我们做得不好", "找找优化机会", "竞品在哪些话题上超过我们", "有什么可以改进的", "find weak spots"
- analysis: The user wants to configure a full analysis task, run a report, or their request is vague/broad.
  Examples: "帮我做一个分析", "运行分析报告", "我想分析品牌数据", "generate an analysis report", "帮我看看最近的数据情况"

Message: {message}

Mode:"""


# ─────────────────────────────────────────────────────────────
# Schema context for NL2SQL (embedded, no extra DB call needed)
# ─────────────────────────────────────────────────────────────

SCHEMA_CONTEXT = """
DATABASE SCHEMA (PostgreSQL) — v1.2 dual-mode tracking:

-- Brand mentions in AI engine responses (v1.2 renamed from geo_company_mentions)
--   brand_role enum: 'own' | 'shadow' | 'peer'
geo_brand_mentions(id UUID, client_id UUID, client_prompt_id UUID, task_id UUID, result_id INT,
                   brand_name TEXT, brand_role TEXT, mention_position INT, executed_at TIMESTAMPTZ)

-- Product-level mentions (v1.2 new)
--   product_role enum: 'own' | 'shadow_brand_product' | 'peer'
--   shadow_sub_role enum (only when product_role='shadow_brand_product'): 'native' | 'resale' | NULL
--   owner_brand_id / owner_peer_id point at the owning brand / peer; owner_*_name are denormalized
geo_product_mentions(id UUID, client_id UUID, client_prompt_id UUID, task_id UUID, result_id INT,
                     product_id UUID, product_name TEXT, product_role TEXT, shadow_sub_role TEXT,
                     owner_brand_id UUID, owner_brand_name TEXT,
                     owner_peer_id UUID, owner_peer_name TEXT,
                     mention_position INT, executed_at TIMESTAMPTZ)

-- Citation sources with v1.2 attribution fields
--   citation_role enum: 'own_domain' | 'own_product' | 'shadow_product_native' |
--                       'shadow_product_resale' | 'shadow_product' | 'shadow_other' |
--                       'peer_product' | 'peer_channel' | 'earned' | 'social' | 'agency' | 'other'
geo_citations(id UUID, client_id UUID, result_id INT, source_url TEXT, source_domain TEXT,
              source_position INT, domain_category TEXT,
              citation_role TEXT, matched_brand_id UUID, matched_product_id UUID, matched_peer_id UUID,
              executed_at TIMESTAMPTZ)

-- Sentiment analysis per response. Positive/Mixed/Negative rates use only rated
-- rows; exclude 'Insufficient Evidence' from that denominator.
geo_sentiment_results(id UUID, client_id UUID, client_prompt_id UUID, task_id UUID, result_id INT,
                      sentiment TEXT['Positive','Mixed/Neutral','Negative','Insufficient Evidence'],
                      confidence FLOAT, classifier_version TEXT, model_id TEXT,
                      reason_code TEXT, evidence JSONB, executed_at TIMESTAMPTZ)

-- Sentiment themes extracted from responses
geo_sentiment_themes(id UUID, client_id UUID, client_prompt_id UUID, task_id UUID, result_id INT, theme_name TEXT,
                     sentiment TEXT['Positive','Mixed/Neutral','Negative'], excerpt TEXT, executed_at TIMESTAMPTZ)

-- Raw AI engine responses (join table)
geo_results(result_id SERIAL, task_id UUID, client_id UUID, platform TEXT, topic_name TEXT, ingested_at TIMESTAMPTZ)

-- Data collection tasks (join table for platform/country/language)
geo_tasks(task_id UUID, client_id UUID, platform TEXT['chatgpt','gemini','aimode'], country TEXT, language TEXT, intent TEXT, topic_name TEXT, created_at TIMESTAMPTZ)

-- Client prompt definitions and Global Config intent metric scopes
geo_client_prompts(id UUID, client_id UUID, intent TEXT, is_active BOOL)
geo_global_intents(intent_name TEXT, categories JSONB, is_active BOOL)

-- Own + Shadow (OEM/distributor) brands (v1.2 new)
geo_client_brands(id UUID, client_id UUID, brand_name TEXT, aliases TEXT[], is_shadow BOOL, is_active BOOL)

-- Competitor definitions. v1.2: is_own_brand column DROPPED — every row is a Peer.
geo_client_peers(id UUID, client_id UUID, primary_name TEXT, aliases TEXT[])

-- Client-scoped domains (Own / Shadow / Peer) with attribution metadata
--   domain_scope: 'whole' | 'path-prefix'
--   exactly one of brand_id / peer_id is non-NULL (both NULL = client-level unattributed)
geo_client_domains(id UUID, client_id UUID, domain TEXT, is_primary BOOL,
                   domain_scope TEXT, brand_id UUID, peer_id UUID)

-- Client topics. v1.2: products TEXT[] column DROPPED — products now in geo_client_topic_products.
geo_client_topics(id UUID, client_id UUID, topic_name TEXT, topic_type TEXT)

-- Product rows under a topic (v1.2 new)
geo_client_topic_products(id UUID, client_id UUID, topic_id UUID, product_name TEXT,
                          match_variants TEXT[], product_role TEXT, shadow_sub_role TEXT,
                          owner_brand_id UUID, owner_peer_id UUID, is_active BOOL)

-- Product ↔ Shadow-Brand sales-channel declarations (v1.2 new, composite PK)
geo_product_sales_channels(product_id UUID, brand_id UUID, client_id UUID, notes TEXT)

-- Product-level tracked URLs (v1.2 new)
--   url_scope: 'exact' | 'path-prefix'; exactly one of brand_id / peer_id is non-NULL
geo_product_tracked_urls(id UUID, client_id UUID, product_id UUID, url TEXT, url_scope TEXT,
                         brand_id UUID, peer_id UUID)

-- AI-discovered settings candidates (v1.2 new)
geo_settings_candidates(id UUID, client_id UUID, candidate_string TEXT, candidate_type TEXT,
                        source TEXT, frequency INT, status TEXT, sample_response_ids INT[])

KEY RELATIONSHIPS:
- geo_brand_mentions.result_id → geo_results.result_id
- geo_product_mentions.result_id → geo_results.result_id
- geo_citations.result_id → geo_results.result_id
- geo_sentiment_results.result_id → geo_results.result_id
- geo_results.task_id → geo_tasks.task_id
- geo_client_topic_products.owner_brand_id → geo_client_brands.id
- geo_client_topic_products.owner_peer_id → geo_client_peers.id
- All tables have client_id for tenant isolation.

COMMON PATTERNS:
- Metric scope must follow Global Config:
  * Visibility queries join the fact table's client_prompt_id to geo_client_prompts cp,
    join geo_global_intents gi ON gi.intent_name = cp.intent, and require
    cp.is_active = true AND gi.is_active = true AND gi.categories @> '["Visibility"]'::jsonb.
  * Citation queries use the same joins and require gi.categories @> '["Citation"]'::jsonb.
  * Sentiment result queries use the same joins. Theme queries join directly with
    cp.id = geo_sentiment_themes.client_prompt_id and matching client_id. Both require
    cp.is_active = true AND gi.is_active = true AND gi.categories @> '["Sentiment"]'::jsonb.
  * Apply this to all numerator/denominator/total CTEs. Do not fall back to all
    intents if a metric category is not configured.
- SOV (Share of Voice) = COUNT(*) of own brand mentions / total mentions * 100.
  Own brand filter: WHERE brand_role = 'own'.
- Peer SOV (CORRECTNESS FIX): do NOT filter by brand_role = 'peer' alone — a
  brand that is both Shadow and Peer is only emitted as brand_role='shadow'
  by the parser. Use peer-list membership instead:
      WHERE EXISTS (
        SELECT 1 FROM geo_client_peers p
        WHERE p.client_id = bm.client_id
          AND (p.primary_name ILIKE bm.brand_name OR bm.brand_name = ANY(p.aliases))
      )
- Visibility trend over time: GROUP BY DATE(bm.executed_at), partition by brand_role.
- Citation rate by attribution: GROUP BY citation_role (not just domain_category).
- Platform comparison: JOIN geo_results → geo_tasks to get platform field.
- mention_position: lower number = mentioned earlier = better ranking.
- Product-level SOV: aggregate geo_product_mentions filtered by product_role.
"""

NL2SQL_SYSTEM = f"""You are a PostgreSQL expert for a GEO (Generative Engine Optimization) analytics platform.

Your job: given a user's natural language question, generate a SQL query and choose the right chart type.

{SCHEMA_CONTEXT}

RULES:
1. Always filter by client_id = $1 (tenant isolation, mandatory)
2. SELECT only — no INSERT, UPDATE, DELETE, DDL
3. Only use tables listed in the schema above
4. For time-series / trends: GROUP BY DATE(executed_at) and ORDER BY date
5. For comparisons / rankings: GROUP BY the comparison dimension, ORDER BY metric DESC
6. For distributions: COUNT/SUM grouped by category
7. LIMIT 200 max
8. Use ROUND() for decimal values
9. NEVER use CURRENT_DATE or NOW() — derive dates from the data itself (e.g. MAX(DATE(executed_at)))
10. When filtering by date range (e.g. "past 30 days"), use:
    WHERE executed_at >= (SELECT MAX(DATE(executed_at)) FROM <table> WHERE client_id = $1) - INTERVAL '${{days}} days'
11. End SQL with semicolon
12. Keep SQL concise — prefer simple JOINs over complex CTEs. Avoid unnecessary subqueries.

CHART TYPE — choose based on the user's intent:
- "line": trends over time, changes, 趋势, daily/weekly
- "bar": comparisons, rankings, 对比, top N
- "pie": distributions, proportions, 占比, breakdown

Respond with JSON:
{{
  "sql": "SELECT ...",
  "chart_type": "line|bar|pie",
  "chart_title": "Human readable chart title",
  "x_key": "column name for X axis",
  "y_keys": ["column names for Y axis values"],
  "explanation": "Brief explanation of what the query does (1 sentence)"
}}"""

SYNTHESIZER_SYSTEM_TEMPLATE = """You are Anthony, the AI analytics assistant for AnswerX GEO platform.
You help brands understand their visibility, citations, and sentiment across AI search engines.

Given the user's question, the SQL query executed, and the result data, provide a clear, insightful analysis.

Guidelines:
- Be specific with numbers — cite actual values from the data
- Compare own brand vs competitors when applicable
- Highlight actionable insights (what's going well, what needs attention)
- Use markdown formatting for readability
- Keep the analysis concise but thorough (3-5 paragraphs)
- Respond in the same language as the user's question
- IMPORTANT: When your response includes charts or data insights, you MUST place the following line as the very last line of your response, after ALL analysis text, insights, and chart descriptions:
  **如需导出本次分析为 HTML 报告，可以说 <mark>「导出分析报告」</mark>。**
  This export suggestion must always be the final paragraph. Never place any analysis content after it.
  Only add this when there is substantial analysis content (charts, data comparisons). Do not repeat it every turn.

{brand_context}"""


# ─────────────────────────────────────────────────────────────
# Helper: Generate widgets for opportunity flow
# ─────────────────────────────────────────────────────────────

PLATFORM_ICONS = {"chatgpt": "🤖", "gemini": "✨", "ai_mode": "🔎"}
PLATFORM_LABELS = {"chatgpt": "ChatGPT", "gemini": "Gemini", "ai_mode": "AI Mode"}


def _build_opportunity_widgets(current_node: int, task_inputs: dict, client_platforms: list[str] | None = None) -> list[dict]:
    """Generate widgets for the opportunity discovery flow (3 nodes)."""
    import uuid as _uuid

    platforms = client_platforms or ["chatgpt", "gemini", "ai_mode"]

    if current_node == 3:
        # Confirm node — build task_confirm widget
        summary = {"分析类型": "优化机会发现"}
        if task_inputs.get("platforms"):
            summary["AI 平台"] = ", ".join(task_inputs["platforms"])
        else:
            summary["AI 平台"] = "全部"
        if task_inputs.get("date_from") and task_inputs.get("date_to"):
            summary["时间范围"] = f"{task_inputs['date_from']} ~ {task_inputs['date_to']}"
        elif task_inputs.get("date_from"):
            summary["时间范围"] = f"{task_inputs['date_from']} ~ 至今"
        from datetime import date as _date
        return [{
            "widget_id": f"opportunity_confirm_{_uuid.uuid4().hex[:8]}",
            "widget_type": "task_confirm",
            "field": "confirm",
            "label": "确认优化机会发现配置",
            "summary": summary,
            "confirm_label": "开始分析",
            "task_type": "opportunity_discovery",
            "task_name_template": f"优化机会发现 - {_date.today().isoformat()}",
        }]

    widget_def = OPPORTUNITY_WIDGETS.get(current_node)
    if widget_def:
        w = dict(widget_def)
        w["widget_id"] = f"opportunity_{w['field']}_{_uuid.uuid4().hex[:8]}"
        if w.get("options") == "__DYNAMIC_PLATFORMS__":
            w["options"] = [
                {"id": p, "label": PLATFORM_LABELS.get(p, p), "icon": PLATFORM_ICONS.get(p, "🌐")}
                for p in platforms
            ]
        return [w]
    return []


# ─────────────────────────────────────────────────────────────
# Helper: Resolve template_id (default to "自定义分析"/"自定义内容" builtins)
# ─────────────────────────────────────────────────────────────

async def _resolve_template_id(
    pool, scope: str, task_inputs: dict, default_name: str,
) -> str:
    """Find which template the user is configuring against.

    Priority:
      1. task_inputs["_template_id"] — user-picked or carried from previous turn
      2. The active builtin template named ``default_name`` for the scope
    """
    tid = task_inputs.get("_template_id")
    if isinstance(tid, str) and tid:
        return tid
    task_type = "analysis" if scope == "analysis" else "content_generation"
    row = await pool.fetchrow(
        """
        SELECT id FROM geo_report_templates
        WHERE name = $1 AND task_type = $2 AND is_active = true
        ORDER BY is_builtin DESC, sort_order LIMIT 1
        """,
        default_name, task_type,
    )
    if not row:
        raise RuntimeError(
            f"No active {task_type!r} template named {default_name!r}; "
            "Anthony Chat needs at least the builtin fallback template "
            "seeded before it can render the wizard."
        )
    return str(row["id"])


# ─────────────────────────────────────────────────────────────
# Helper: Build widgets for the current step (DB-driven)
# ─────────────────────────────────────────────────────────────

async def build_widgets_from_config(
    *,
    scope: str,
    template_id: str,
    pool,
    current_step_key: str,
    task_inputs: dict,
    confirm_summary_builder=None,
) -> tuple[list[dict], list, str | None]:
    """Resolve the workflow for ``scope`` + ``template_id``, then emit widgets
    for the step matching ``current_step_key``.

    Returns ``(widgets, all_steps, next_step_key)``. ``next_step_key`` is the
    key of the step *after* the current one (or None when the current step is
    the last). Caller uses it to advance the LLM's "current_step_key".

    The confirm step is rendered specially via :func:`build_confirm_widget`
    using the optional ``confirm_summary_builder`` callback (taking
    ``task_inputs`` + ``all_steps``) — the chat engine knows what summary
    keys belong on the confirmation card.
    """
    all_steps = await load_workflow_steps(scope=scope, template_id=template_id, pool=pool)
    enabled = [s for s in all_steps if s.enabled]
    keys = [s.key for s in enabled]

    if current_step_key not in keys:
        # Default to the first enabled step
        current_step_key = keys[0] if keys else ""

    cur = next((s for s in enabled if s.key == current_step_key), None)
    if cur is None:
        return [], all_steps, None

    is_confirm = cur.key == "confirm_execute" or any(
        f.type == "execution_preview" for f in cur.fields
    )
    if is_confirm:
        summary = confirm_summary_builder(task_inputs, all_steps) if confirm_summary_builder else {}
        widgets = [build_confirm_widget(
            cur,
            summary=summary,
            confirm_label="开始分析" if scope == "analysis" else "开始生成",
            task_type="analysis" if scope == "analysis" else "content_generation",
        )]
    else:
        widgets = build_widget_from_step(cur)

    idx = keys.index(cur.key)
    next_key = keys[idx + 1] if idx + 1 < len(keys) else None
    return widgets, all_steps, next_key


# ─────────────────────────────────────────────────────────────
# Node: NL2SQL Generator
# ─────────────────────────────────────────────────────────────

async def nl2sql_generator_node(state: AnalyzeState) -> dict:
    """Generate SQL + chart config from user's natural language question."""
    model_id = await get_model_id("pro")
    client = await get_genai_client(model_id, role="pro")

    # Extract user's question
    user_question = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_question = msg.content
            break

    response = await generate_content(
        client, model_id,
        contents=user_question,
        config=types.GenerateContentConfig(
            system_instruction=NL2SQL_SYSTEM,
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=8192,
        ),
    )

    raw_text = response.text or ""
    try:
        plan = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        logger.error(f"[ANALYZE] NL2SQL returned invalid JSON (len={len(raw_text)}): {raw_text[:300]}")
        plan = {
            "sql": """
                SELECT bm.brand_name, bm.brand_role,
                       COUNT(*) AS mention_count,
                       ROUND(AVG(bm.mention_position)::numeric, 2) AS avg_position
                FROM geo_brand_mentions bm
                WHERE bm.client_id = $1
                GROUP BY bm.brand_name, bm.brand_role
                ORDER BY mention_count DESC
                LIMIT 20;
            """,
            "chart_type": "bar",
            "chart_title": "Brand Visibility Overview",
            "x_key": "brand_name",
            "y_keys": ["mention_count"],
            "explanation": "Fallback query: overall brand mention counts by brand_role",
        }

    logger.info(f"[ANALYZE] NL2SQL plan: chart_type={plan.get('chart_type')}, explanation={plan.get('explanation')}")
    return {"nl2sql_plan": plan}


# ─────────────────────────────────────────────────────────────
# Node: Query Executor
# ─────────────────────────────────────────────────────────────

async def query_executor_node(state: AnalyzeState) -> dict:
    """Execute the generated SQL query with tenant isolation."""
    plan = state.get("nl2sql_plan", {})
    sql = plan.get("sql", "")
    client_id = state["client_id"]

    if not sql:
        return {
            "query_results": [],
            "query_sql": "",
        }

    result = await execute_sql.ainvoke({
        "client_id": client_id,
        "sql": sql,
    })

    if "error" in result:
        logger.error(f"[ANALYZE] SQL execution failed: {result['error']}")
        return {
            "query_results": [],
            "query_sql": result.get("sql", sql),
        }

    logger.info(f"[ANALYZE] Query returned {result['row_count']} rows")
    return {
        "query_results": result.get("rows", []),
        "query_sql": result.get("sql", sql),
    }


# ─────────────────────────────────────────────────────────────
# Node: Chart Builder
# ─────────────────────────────────────────────────────────────

async def chart_builder_node(state: AnalyzeState) -> dict:
    """Build Recharts-compatible chart config from query results."""
    plan = state.get("nl2sql_plan", {})
    rows = state.get("query_results", [])

    if not rows:
        return {"charts": []}

    chart_type = plan.get("chart_type", "bar")
    chart_title = plan.get("chart_title", "Query Results")
    x_key = plan.get("x_key", "")
    y_keys = plan.get("y_keys", [])

    # Auto-detect keys from result columns if not specified
    if rows and (not x_key or not y_keys):
        columns = list(rows[0].keys())
        if not x_key and columns:
            x_key = columns[0]
        if not y_keys and len(columns) > 1:
            y_keys = [
                c for c in columns[1:]
                if isinstance(rows[0].get(c), (int, float))
            ]
            if not y_keys:
                y_keys = columns[1:2]

    chart = {
        "type": chart_type,
        "title": chart_title,
        "data": rows,
        "xKey": x_key,
        "yKeys": y_keys,
    }

    if chart_type == "pie":
        chart["nameKey"] = x_key
        chart["valueKey"] = y_keys[0] if y_keys else "value"

    logger.info(f"[ANALYZE] Built {chart_type} chart: {chart_title}")
    return {"charts": [chart]}


# ─────────────────────────────────────────────────────────────
# Node: Synthesizer
# ─────────────────────────────────────────────────────────────

def _build_synthesizer_prompt(state: AnalyzeState) -> str:
    """Build synthesizer system prompt with optional brand context."""
    parts = []
    client_name = state.get("client_name", "")
    if client_name:
        parts.append(f"Current client: {client_name}")

    bp = state.get("brand_profile")
    if bp:
        if bp.get("brand_name"):
            parts.append(f"Brand: {bp['brand_name']}")
        if bp.get("tone_of_voice"):
            parts.append(f"Brand tone: {bp['tone_of_voice']}")
        if bp.get("target_audience"):
            parts.append(f"Target audience: {bp['target_audience']}")
        if bp.get("key_messages"):
            msgs = bp["key_messages"]
            if isinstance(msgs, list):
                parts.append(f"Key messages: {', '.join(msgs)}")

    # Inject cross-session memory if available
    if bp and bp.get("_memory_context"):
        parts.append(f"\n{bp['_memory_context']}")

    brand_context = "\n".join(parts) if parts else ""
    return SYNTHESIZER_SYSTEM_TEMPLATE.format(brand_context=brand_context)


async def synthesizer_node(state: AnalyzeState) -> dict:
    """Synthesize insights from query results using Gemini Pro."""
    model_id = await get_model_id("pro")
    client = await get_genai_client(model_id, role="pro")

    system_prompt = _build_synthesizer_prompt(state)

    user_question = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_question = msg.content
            break

    rows = state.get("query_results", [])
    sql = state.get("query_sql", "")

    data_str = json.dumps(rows[:100], ensure_ascii=False, default=str)
    if len(data_str) > 8000:
        data_str = data_str[:8000] + "... (truncated)"

    prompt = f"""User question: {user_question}

SQL executed:
{sql}

Query results ({len(rows)} rows):
{data_str}

Please analyze this data and provide insights."""

    response = await generate_content(
        client, model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            max_output_tokens=4096,
        ),
    )

    insights = response.text or ""
    logger.info(f"[ANALYZE] Synthesized {len(insights)} chars of insights")

    return {
        "insights": insights,
        "messages": [AIMessage(content=insights)],
    }


# ─────────────────────────────────────────────────────────────
# Node: Intent Router (direct / opportunity / analysis)
# ─────────────────────────────────────────────────────────────

async def analyze_intent_router(state: AnalyzeState) -> dict:
    """Classify whether to run direct NL2SQL, opportunity discovery, or full analysis."""
    # If slot-filling is already in progress, continue the same flow
    existing_inputs = state.get("task_inputs", {})
    if existing_inputs:
        flow = existing_inputs.get("_flow")
        if flow == "opportunity":
            return {"_mode": "opportunity"}
        return {"_mode": "analysis"}

    user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    model_id = await get_model_id("flash")
    client = await get_genai_client(model_id, role="flash")

    prompt = INTENT_ROUTER_SYSTEM.format(message=user_message)
    response = await generate_content(
        client, model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=256,
        ),
    )

    raw = (response.text or "").strip().lower()
    if "opportunity" in raw:
        mode = "opportunity"
    elif "analysis" in raw:
        mode = "analysis"
    else:
        mode = "direct"
    logger.info(f"[ANALYZE] Intent router: mode={mode} (message: {user_message[:60]})")
    return {"_mode": mode}


def route_analyze_mode(state: AnalyzeState) -> str:
    """Route based on _mode field set by intent router."""
    mode = state.get("_mode", "direct")
    if mode == "opportunity":
        return "opportunity"
    if mode == "analysis":
        return "analysis"
    return "direct"


# ─────────────────────────────────────────────────────────────
# Node: Opportunity Slot Filler (3 nodes + widgets)
# ─────────────────────────────────────────────────────────────

async def opportunity_slot_filler_node(state: AnalyzeState) -> dict:
    """Lightweight slot-filling for opportunity discovery (3 steps).

    Uses LLM for conversational understanding + programmatic widget emission.
    """
    model_id = await get_model_id("flash")
    client = await get_genai_client(model_id, role="flash")

    user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    existing_inputs = state.get("task_inputs", {})
    # Tag this flow
    existing_inputs["_flow"] = "opportunity"

    # Check if this is a structured widget response (single or batch)
    try:
        parsed = json.loads(user_message)
        if parsed.get("type") == "widget_response":
            if "responses" in parsed:
                for r in parsed["responses"]:
                    if r.get("field") and r.get("value") is not None:
                        existing_inputs[r["field"]] = r["value"]
            elif parsed.get("field") and parsed.get("value") is not None:
                existing_inputs[parsed["field"]] = parsed["value"]
    except (json.JSONDecodeError, TypeError):
        pass

    # Decompose compound widget fields into flat keys the confirm node expects
    if "date_range" in existing_inputs and isinstance(existing_inputs["date_range"], dict):
        dr = existing_inputs["date_range"]
        if dr.get("from"):
            existing_inputs["date_from"] = dr["from"]
        if dr.get("to"):
            existing_inputs["date_to"] = dr["to"]

    # Build brand context
    brand_profile = state.get("brand_profile")
    brand_parts = []
    if brand_profile:
        if brand_profile.get("brand_name"):
            brand_parts.append(f"Brand: {brand_profile['brand_name']}")
        if brand_profile.get("tone_of_voice"):
            brand_parts.append(f"Tone: {brand_profile['tone_of_voice']}")
    brand_context = "Brand context: " + ", ".join(brand_parts) if brand_parts else ""
    if brand_profile and brand_profile.get("_memory_context"):
        brand_context += f"\n{brand_profile['_memory_context']}"

    persisted_node = existing_inputs.pop("_current_node", 1)

    # Build conversation history. Prune to the last N turns before sending to
    # the LLM — checkpoint state still holds the full history for UI replay.
    pruned = prune_messages(state["messages"], max_turns=await get_prune_max_turns())
    contents = []
    for msg in pruned:
        if isinstance(msg, HumanMessage):
            contents.append(types.Content(role="user", parts=[types.Part(text=msg.content)]))
        elif isinstance(msg, AIMessage) and msg.content:
            contents.append(types.Content(role="model", parts=[types.Part(text=msg.content)]))

    state_hint = (
        f"\n[SYSTEM STATE] current_node={persisted_node}, "
        f"collected_inputs={json.dumps(existing_inputs, ensure_ascii=False)}"
    )
    if contents and contents[-1].role == "user":
        last_text = contents[-1].parts[0].text
        contents[-1] = types.Content(role="user", parts=[types.Part(text=last_text + state_hint)])
    else:
        contents.append(types.Content(role="user", parts=[types.Part(text=state_hint)]))

    system = OPPORTUNITY_SLOT_FILL_SYSTEM.format(brand_context=brand_context)

    response = await generate_content(
        client, model_id,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=2048,
        ),
    )

    try:
        result = json.loads(response.text)
        if isinstance(result, list):
            result = result[0] if result and isinstance(result[0], dict) else {}
        if not isinstance(result, dict):
            result = {}
    except (json.JSONDecodeError, TypeError):
        result = {}

    if not result.get("message"):
        result = {
            "message": (
                "让我帮您发现优化机会！我会运行 3 项自动诊断：\n"
                "1. **Topic 四象限定位** — 按可见度 x 情感将话题分为明星、机会、风险、盲区\n"
                "2. **选题机会挖掘** — 找到竞品覆盖但品牌缺失的话题\n"
                "3. **平台-AI引擎引用关系** — 分析各平台最常引用的来源类型\n\n"
                "首先，请选择要分析的 AI 平台（不选 = 全部平台）："
            ),
            "current_node": 1,
            "task_inputs": existing_inputs,
            "is_ready": False,
            "missing_fields": [],
            **result,
        }

    message_text = result.get("message", "")
    task_inputs = result.get("task_inputs", {})
    is_ready = result.get("is_ready", False)
    current_node = result.get("current_node", 1)

    # Merge with existing inputs
    merged_inputs = {**existing_inputs}
    for k, v in task_inputs.items():
        if v is not None and v != "" and v != []:
            merged_inputs[k] = v

    # Inject fixed inputs for opportunity flow
    merged_inputs["_flow"] = "opportunity"
    merged_inputs["domains"] = ["visibility", "citation"]
    merged_inputs["analysis_goal"] = "opportunity"
    merged_inputs["_current_node"] = current_node

    # Load client's configured platforms from DB
    client_platforms = None
    try:
        from database import get_pool
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT config_platforms FROM geo_clients WHERE id = $1::uuid",
            state["client_id"],
        )
        if row and row["config_platforms"]:
            client_platforms = row["config_platforms"]
    except Exception:
        pass

    widgets = _build_opportunity_widgets(current_node, merged_inputs, client_platforms)

    logger.info(f"[ANALYZE] Opportunity slot-fill: node={current_node}, ready={is_ready}, widgets={len(widgets)}, inputs={json.dumps(merged_inputs, ensure_ascii=False)[:200]}")

    return {
        "task_inputs": merged_inputs,
        "task_ready": is_ready,
        "messages": [AIMessage(content=message_text)],
        "widgets": widgets,
    }


# ─────────────────────────────────────────────────────────────
# Helper: Build the analysis-confirm summary from collected inputs
# ─────────────────────────────────────────────────────────────

def _build_analysis_summary(task_inputs: dict, all_steps: list) -> dict:
    """Render a human-readable summary card for the analysis confirm step.

    Pulls option labels straight from the resolved step list (already
    sourced from DB) so we never hardcode the "竞品对标" → benchmark map
    in this file.
    """
    summary: dict[str, str] = {}

    def _label_for(step_key: str, field_key: str, value):
        step = next((s for s in all_steps if s.key == step_key), None)
        if step is None:
            return None
        f = next((f for f in step.fields if f.key == field_key), None)
        if f is None:
            return None
        # Multi-value: list of keys → list of labels
        if isinstance(value, list):
            keys = [str(v) for v in value]
            label_map = {o["key"]: o["label"] for o in f.options}
            return ", ".join(label_map.get(k, k) for k in keys)
        # Single value
        label_map = {o["key"]: o["label"] for o in f.options}
        return label_map.get(str(value), str(value))

    # analysis_goal step
    g = task_inputs.get("default_goal") or task_inputs.get("goal")
    if g:
        summary["分析目标"] = _label_for("analysis_goal", "default_goal", g) or str(g)

    # analysis_metrics step (Custom Analysis only — see migration 055)
    sel_metrics = task_inputs.get("selected_metrics") or task_inputs.get("metrics")
    if sel_metrics:
        summary["锁定指标"] = (
            _label_for("analysis_metrics", "selected_metrics", sel_metrics)
            or (", ".join(sel_metrics) if isinstance(sel_metrics, list) else str(sel_metrics))
        )

    # analysis_framework step
    lenses = task_inputs.get("default_lenses") or task_inputs.get("lenses")
    if lenses:
        summary["分析框架"] = _label_for("analysis_framework", "default_lenses", lenses) or ", ".join(lenses)

    # data_selection step
    domains = task_inputs.get("default_domains") or task_inputs.get("domains")
    if domains:
        summary["数据领域"] = _label_for("data_selection", "default_domains", domains) or ", ".join(domains)
    platforms = task_inputs.get("default_platforms") or task_inputs.get("platforms")
    if platforms:
        summary["AI 平台"] = _label_for("data_selection", "default_platforms", platforms) or ", ".join(platforms)
    date_range = task_inputs.get("default_date_range") or task_inputs.get("date_range")
    if isinstance(date_range, str) and date_range:
        summary["时间范围"] = _label_for("data_selection", "default_date_range", date_range) or date_range
    elif isinstance(date_range, dict):
        if date_range.get("from") and date_range.get("to"):
            summary["时间范围"] = f"{date_range['from']} ~ {date_range['to']}"
    elif task_inputs.get("date_from") and task_inputs.get("date_to"):
        summary["时间范围"] = f"{task_inputs['date_from']} ~ {task_inputs['date_to']}"

    # chart_config & prompt_edit are advanced — show counts only
    charts = task_inputs.get("default_charts")
    if isinstance(charts, list) and charts:
        summary["图表配置"] = f"{len(charts)} 张图表"

    return summary


# ─────────────────────────────────────────────────────────────
# Node: Analysis Slot Filler (DB-driven steps + widgets)
# ─────────────────────────────────────────────────────────────

async def analysis_slot_filler_node(state: AnalyzeState) -> dict:
    """Guided slot-filling for full analysis task configuration.

    Step list, labels, options and per-template defaults all come from the
    DB (``geo_workflow_config`` + ``geo_report_templates.wizard_config``).
    See :mod:`services.workflow_config` for the loader contract.
    """
    from database import get_pool
    pool = await get_pool()

    model_id = await get_model_id("flash")
    client = await get_genai_client(model_id, role="flash")

    user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    existing_inputs = dict(state.get("task_inputs") or {})
    existing_inputs["_flow"] = "analysis"

    # ── Parse widget responses ─────────────────────────────
    try:
        parsed = json.loads(user_message)
        if parsed.get("type") == "widget_response":
            if "responses" in parsed:
                for r in parsed["responses"]:
                    if r.get("field") and r.get("value") is not None:
                        existing_inputs[r["field"]] = r["value"]
            elif parsed.get("field") and parsed.get("value") is not None:
                existing_inputs[parsed["field"]] = parsed["value"]
    except (json.JSONDecodeError, TypeError):
        pass

    # ── Resolve template + load workflow steps ─────────────
    template_id = await _resolve_template_id(
        pool, "analysis", existing_inputs, DEFAULT_ANALYSIS_TEMPLATE_NAME,
    )
    existing_inputs["_template_id"] = template_id

    all_steps = await load_workflow_steps(scope="analysis", template_id=template_id, pool=pool)
    enabled_steps = [s for s in all_steps if s.enabled]
    if not enabled_steps:
        raise RuntimeError(
            "analysis template has no enabled wizard steps — check "
            f"template={template_id!r} wizard_config.steps."
        )
    step_keys = [s.key for s in enabled_steps]

    # ── Persisted current_step_key (default: first enabled step) ──
    persisted_key = existing_inputs.pop("_current_step_key", step_keys[0])
    if persisted_key not in step_keys:
        persisted_key = step_keys[0]

    # ── Build brand context for the LLM prompt ─────────────
    brand_profile = state.get("brand_profile")
    brand_parts = []
    if brand_profile:
        if brand_profile.get("brand_name"):
            brand_parts.append(f"Brand: {brand_profile['brand_name']}")
        if brand_profile.get("tone_of_voice"):
            brand_parts.append(f"Tone: {brand_profile['tone_of_voice']}")
    brand_context = "Brand context: " + ", ".join(brand_parts) if brand_parts else ""
    if brand_profile and brand_profile.get("_memory_context"):
        brand_context += f"\n{brand_profile['_memory_context']}"

    # ── Render step specs from DB rows (no hardcoded labels) ──
    step_specs_lines = []
    for s in enabled_steps:
        field_lines = []
        for f in s.fields:
            field_lines.append(
                f"  - field={f.key} type={f.type} required={f.required} "
                f"options={[o['key'] for o in f.options][:8]} "
                f"default={f.default_value!r}"
            )
        spec = (
            f"### Step #{s.num}: {s.label} (key={s.key})\n"
            f"{s.description}\n"
            + "\n".join(field_lines)
        )
        step_specs_lines.append(spec)
    step_specs = "\n\n".join(step_specs_lines)

    system = ANALYZE_SLOT_FILL_SYSTEM.format(
        brand_context=brand_context,
        step_count=len(enabled_steps),
        step_specs=step_specs,
        step_keys_csv=", ".join(step_keys),
    )

    # ── Build conversation history (pruned) ────────────────
    pruned = prune_messages(state["messages"], max_turns=await get_prune_max_turns())
    contents = []
    for msg in pruned:
        if isinstance(msg, HumanMessage):
            contents.append(types.Content(role="user", parts=[types.Part(text=msg.content)]))
        elif isinstance(msg, AIMessage) and msg.content:
            contents.append(types.Content(role="model", parts=[types.Part(text=msg.content)]))

    state_hint = (
        f"\n[SYSTEM STATE] current_step_key={persisted_key}, "
        f"collected_inputs={json.dumps({k: v for k, v in existing_inputs.items() if not k.startswith('_')}, ensure_ascii=False)}"
    )
    if contents and contents[-1].role == "user":
        last_text = contents[-1].parts[0].text
        contents[-1] = types.Content(role="user", parts=[types.Part(text=last_text + state_hint)])
    else:
        contents.append(types.Content(role="user", parts=[types.Part(text=state_hint)]))

    response = await generate_content(
        client, model_id,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=2048,
        ),
    )

    try:
        result = json.loads(response.text)
        if isinstance(result, list):
            result = result[0] if result and isinstance(result[0], dict) else {}
        if not isinstance(result, dict):
            result = {}
    except (json.JSONDecodeError, TypeError):
        result = {}

    # ── Cold-start fallback message ─────────────────────────
    if not result.get("message"):
        first = enabled_steps[0]
        intro_lines = "\n".join(
            f"{s.num + 1 if s.num == 0 else s.num}. **{s.label}** — {s.description}"
            for s in enabled_steps
        )
        result = {
            "message": (
                f"让我帮您配置分析任务！我们将分 {len(enabled_steps)} 步完成：\n"
                f"{intro_lines}\n\n"
                f"首先，{first.description or first.label}："
            ),
            "current_step_key": first.key,
            "task_inputs": {},
            "is_ready": False,
            "missing_fields": [f.key for f in first.fields if f.required],
            **result,
        }

    message_text = result.get("message", "")
    new_inputs = result.get("task_inputs", {}) or {}
    is_ready = bool(result.get("is_ready", False))
    current_step_key = result.get("current_step_key") or persisted_key
    if current_step_key not in step_keys:
        current_step_key = persisted_key

    # ── Merge collected inputs ─────────────────────────────
    merged_inputs = dict(existing_inputs)
    for k, v in new_inputs.items():
        if v is None or v == "" or v == []:
            continue
        merged_inputs[k] = v

    # NB: Keep `default_*` keys in LangGraph state — they match the
    # widget.field names the LLM sees in system prompt step_specs, so the
    # LLM keeps slot-filling correctly across turns. The chat→pipeline
    # rename happens at the SSE `task_ready` emit boundary in main.py
    # (`normalize_chat_inputs_to_pipeline_shape`), so DB inputs and
    # pipelines see plain keys without breaking the LLM's view.

    merged_inputs["_flow"] = "analysis"
    merged_inputs["_current_step_key"] = current_step_key
    merged_inputs["_template_id"] = template_id

    # ── Hidden defaults injection (Phase F) ────────────────
    # Required metrics/chapters never become widgets — they live on the
    # template and must be carried into final task_inputs so the
    # downstream pipeline can apply them as a hard contract.
    #
    # Custom Analysis (自定义分析) is special: its template's
    # `required_metrics` is empty by design. Migration 055 added an
    # opt-in `analysis_metrics` wizard step (multi_ref → metric dictionary)
    # that fills `selected_metrics` in task_inputs. When the template ships
    # no required_metrics, fall back to the user's wizard selection so the
    # downstream pipeline gets a non-empty metric set.
    if is_ready:
        required = await load_template_required(template_id, "analysis", pool)
        locked = list(required["required_metrics"] or [])
        if not locked:
            user_metrics = merged_inputs.get("selected_metrics") \
                or merged_inputs.get("default_metrics") \
                or merged_inputs.get("metrics") \
                or []
            if isinstance(user_metrics, list) and user_metrics:
                locked = [str(m) for m in user_metrics]
        merged_inputs["metrics_locked"] = locked
        merged_inputs["chapters_locked"] = required["required_chapters"]

    # ── Render widgets for the current step ────────────────
    # When ``is_ready=True`` we used to emit a TaskConfirmWidget here too
    # (with its own 「开始分析」 button). The chat frontend then turned the
    # subsequent ``task_ready`` SSE event into a SECOND ChatTaskCard with
    # ANOTHER 「开始执行」 button — a confusing two-card / two-button UX.
    #
    # Fix: when ready, emit ZERO widgets. main.py's ``task_ready`` SSE
    # event becomes the single confirmation surface (rendered as one
    # ChatTaskCard). All the summary information that used to live on the
    # TaskConfirmWidget is now shipped as ``_summary_display`` inside
    # task_inputs so ChatTaskCard can render Chinese-labeled rows directly.
    cur_step = next((s for s in enabled_steps if s.key == current_step_key), enabled_steps[0])
    is_confirm = cur_step.key == "confirm_execute" or any(
        f.type == "execution_preview" for f in cur_step.fields
    )
    if is_ready:
        merged_inputs["_summary_display"] = build_summary_display(merged_inputs, all_steps)
        widgets = []
    elif is_confirm:
        summary = _build_analysis_summary(merged_inputs, all_steps)
        summary_display = build_summary_display(merged_inputs, all_steps)
        widgets = [build_confirm_widget(
            cur_step,
            summary=summary,
            summary_display=summary_display,
            confirm_label="开始分析",
            task_type="analysis",
        )]
    else:
        widgets = build_widget_from_step(cur_step)

    logger.info(
        "[ANALYZE] Analysis slot-fill: step=%s ready=%s widgets=%d "
        "inputs=%s",
        current_step_key, is_ready, len(widgets),
        json.dumps({k: v for k, v in merged_inputs.items() if not k.startswith('_')}, ensure_ascii=False)[:200],
    )

    return {
        "task_inputs": merged_inputs,
        "task_ready": is_ready,
        "messages": [AIMessage(content=message_text)],
        "widgets": widgets,
    }


# ─────────────────────────────────────────────────────────────
# Graph Builder
# ─────────────────────────────────────────────────────────────

def build_analyze_graph() -> StateGraph:
    """Build the Analyze Agent sub-graph with three modes.

    Mode A (direct): specific question -> NL2SQL pipeline -> immediate results
    Mode B (opportunity): optimization opportunities -> lightweight slot-filling -> task_ready
    Mode C (analysis): full analysis task -> 6-step slot-filling -> task_ready
    """
    graph = StateGraph(AnalyzeState)

    graph.add_node("intent_router", analyze_intent_router)
    graph.add_node("nl2sql_generator", nl2sql_generator_node)
    graph.add_node("query_executor", query_executor_node)
    graph.add_node("chart_builder", chart_builder_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("opportunity_slot_filler", opportunity_slot_filler_node)
    graph.add_node("analysis_slot_filler", analysis_slot_filler_node)

    graph.set_entry_point("intent_router")
    graph.add_conditional_edges(
        "intent_router",
        route_analyze_mode,
        {
            "direct": "nl2sql_generator",
            "opportunity": "opportunity_slot_filler",
            "analysis": "analysis_slot_filler",
        },
    )
    graph.add_edge("nl2sql_generator", "query_executor")
    graph.add_edge("query_executor", "chart_builder")
    graph.add_edge("chart_builder", "synthesizer")
    graph.add_edge("synthesizer", END)
    graph.add_edge("opportunity_slot_filler", END)
    graph.add_edge("analysis_slot_filler", END)

    return graph
