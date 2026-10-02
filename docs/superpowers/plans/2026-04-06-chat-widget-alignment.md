# Chat-Mode Widget Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align chat-mode widget slot-filling flows with the latest Analyzer (Mode A + Mode B) and Content workflows.

**Architecture:** Three slot-filler nodes (opportunity, analysis, content) with updated widget definitions, system prompts, and graph routing. No schema changes, no frontend changes.

**Tech Stack:** Python (FastAPI/LangGraph), google-genai SDK, asyncpg

**Spec:** `docs/superpowers/specs/2026-04-06-chat-widget-alignment.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `geo_agent/src/graphs/analyze.py` | Modify | Split slot_filler into opportunity_slot_filler + analysis_slot_filler; update widgets, prompts, graph |
| `geo_agent/src/graphs/action.py` | Modify | Restructure CONTENT_WIDGETS to goal-first; update prompt; update confirmation |
| `geo_agent/src/models/state.py` | No change | Existing state schema handles all new fields via task_inputs dict |
| `geo_agent/src/graphs/supervisor.py` | No change | "analyze" and "action" intents unchanged |

---

### Task 1: Analyze Sub-graph — Intent Router 3-Way Split

**Files:**
- Modify: `geo_agent/src/graphs/analyze.py:162-172` (INTENT_ROUTER_SYSTEM)
- Modify: `geo_agent/src/graphs/analyze.py:552-587` (analyze_intent_router + route_analyze_mode)
- Modify: `geo_agent/src/graphs/analyze.py:745-772` (build_analyze_graph)

- [ ] **Step 1: Update INTENT_ROUTER_SYSTEM prompt for 3-way classification**

Replace the current 2-mode prompt (lines 162-172) with:

```python
INTENT_ROUTER_SYSTEM = """Classify this analysis request into one of three modes. Reply with ONLY the mode name, nothing else.

Modes:
- direct: The user is asking a specific data question that can be answered with a single SQL query + chart.
  Examples: "show me brand visibility trends", "最近7天的提及量变化", "which competitor has the most citations", "SOV趋势"
- opportunity: The user wants to discover content optimization opportunities, find weak spots, or identify what content to create/improve.
  Examples: "帮我找优化机会", "哪些内容可以优化", "有什么提升空间", "content opportunity", "薄弱环节", "发现机会", "优化机会发现", "内容机会"
- analysis: The user wants to configure a full analysis task, run a report, or their request is vague/broad.
  Examples: "帮我做一个分析", "运行分析报告", "竞品对标", "趋势诊断", "全面健康检查", "情感分析"

Message: {message}

Mode:"""
```

- [ ] **Step 2: Update analyze_intent_router to return 3 modes**

Replace lines 552-581:

```python
async def analyze_intent_router(state: AnalyzeState) -> dict:
    """Classify: direct NL2SQL, opportunity discovery, or guided analysis."""
    existing_inputs = state.get("task_inputs", {})
    if existing_inputs:
        # Slot-filling in progress — check which flow we're in
        if existing_inputs.get("_flow") == "opportunity":
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
    elif "guided" in raw or "analysis" in raw:
        mode = "analysis"
    else:
        mode = "direct"
    logger.info(f"[ANALYZE] Intent router: mode={mode} (message: {user_message[:60]})")
    return {"_mode": mode}
```

- [ ] **Step 3: Update route_analyze_mode for 3 branches**

Replace lines 584-587:

```python
def route_analyze_mode(state: AnalyzeState) -> str:
    """Route based on _mode field set by intent router."""
    mode = state.get("_mode", "direct")
    if mode == "opportunity":
        return "opportunity"
    elif mode == "analysis":
        return "analysis"
    return "direct"
```

- [ ] **Step 4: Update build_analyze_graph with 3 guided branches**

Replace lines 745-772:

```python
def build_analyze_graph() -> StateGraph:
    """Build the Analyze Agent sub-graph with three modes.

    Mode Direct: specific question -> NL2SQL pipeline -> immediate results
    Mode Opportunity: guided -> opportunity slot-filling -> task_ready (opportunity_discovery)
    Mode Analysis: guided -> analysis slot-filling -> task_ready (analysis)
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
        {"direct": "nl2sql_generator", "opportunity": "opportunity_slot_filler", "analysis": "analysis_slot_filler"},
    )
    graph.add_edge("nl2sql_generator", "query_executor")
    graph.add_edge("query_executor", "chart_builder")
    graph.add_edge("chart_builder", "synthesizer")
    graph.add_edge("synthesizer", END)
    graph.add_edge("opportunity_slot_filler", END)
    graph.add_edge("analysis_slot_filler", END)

    return graph
```

- [ ] **Step 5: Run linter check**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_agent && python -c "from api.graphs.analyze import build_analyze_graph; print('OK')"`
Expected: Fails because opportunity_slot_filler_node and analysis_slot_filler_node don't exist yet (they're built in Tasks 2 and 3).

- [ ] **Step 6: Commit**

```bash
git add geo_agent/src/graphs/analyze.py
git commit -m "refactor(analyze): 3-way intent routing for direct/opportunity/analysis"
```

---

### Task 2: Opportunity Slot-Filler Node (3-Step Flow)

**Files:**
- Modify: `geo_agent/src/graphs/analyze.py` — add OPPORTUNITY_WIDGETS, OPPORTUNITY_SLOT_FILL_SYSTEM, _build_opportunity_widgets, opportunity_slot_filler_node

- [ ] **Step 1: Add OPPORTUNITY_WIDGETS definition**

Insert after the existing ANALYZE_WIDGETS dict (after line ~81):

```python
# ─────────────────────────────────────────────────────────────
# Opportunity Discovery widgets (3 nodes, lightweight)
# ─────────────────────────────────────────────────────────────

OPPORTUNITY_WIDGETS = {
    1: {  # Platforms (optional)
        "widget_type": "multi_select",
        "field": "platforms",
        "label": "AI 平台筛选",
        "description": "不选 = 全部平台",
        "options": "__DYNAMIC_PLATFORMS__",
        "required": False,
        "default_value": None,
    },
    2: {  # Date Range
        "widget_type": "date_range",
        "field": "date_range",
        "label": "分析时间范围",
        "required": True,
        "default_value": {"preset": "last_30_days"},
    },
    3: None,  # Confirm — generated dynamically
}
```

- [ ] **Step 2: Add OPPORTUNITY_SLOT_FILL_SYSTEM prompt**

Insert after the OPPORTUNITY_WIDGETS dict:

```python
OPPORTUNITY_SLOT_FILL_SYSTEM = """You are Anthony, a GEO analytics assistant for the AnswerX platform.
You are helping the user configure an **Optimization Opportunity Discovery** task.
This task performs a full diagnostic of the brand's AI search performance to find content optimization opportunities.

It does three things:
1. Topic 四象限定位 — classify topics by brand coverage, AI citation patterns, and trend direction
2. 选题机会挖掘 — discover content topic angles from citation data, ranked by priority
3. 平台-AI引擎引用关系 — map which publishing platforms' content gets cited by which AI engines

## Workflow (3 steps, fast)

### Node 1: AI Platform Filter (AI 平台筛选) — OPTIONAL
Which AI platforms to analyze? Leave empty for all platforms.
Common platforms: chatgpt, gemini, ai_mode.
Default: all (null)

### Node 2: Date Range (时间范围) — REQUIRED
Analysis date range. Accept relative ("最近7天", "最近30天") or absolute dates.
Default: last 30 days

### Node 3: Confirm (确认执行)
Summarize the configuration and set is_ready=true.

{brand_context}

## Handling widget responses
When the user sends a message starting with '{{"type": "widget_response"', extract field/value and advance.

## Your behavior:
- At the first turn, briefly explain what this task does (the 3 diagnostics above), then ask about platform filter.
- Be concise. This is a lightweight flow — 3 steps maximum.
- If the user says "跳过" or "skip" for platforms, use null (all platforms).
- When both steps are done, show summary and set is_ready=true.
- If the user provides all info at once, skip ahead.
- Respond in the user's language.

## Output format (JSON):
{{
  "message": "Your response to the user",
  "current_node": 1-3,
  "task_inputs": {{
    "platforms": ["chatgpt", "gemini"] or null,
    "date_from": "2026-03-07",
    "date_to": "2026-04-06"
  }},
  "is_ready": true/false,
  "missing_fields": ["field1"]
}}"""
```

- [ ] **Step 3: Add _build_opportunity_widgets function**

```python
def _build_opportunity_widgets(current_node: int, task_inputs: dict, client_platforms: list[str] | None = None) -> list[dict]:
    """Generate widgets for opportunity discovery flow."""
    import uuid as _uuid

    if current_node == 3:
        summary = {"分析类型": "优化机会发现"}
        platforms = task_inputs.get("platforms")
        if platforms:
            summary["AI 平台"] = ", ".join(PLATFORM_LABELS.get(p, p) for p in platforms)
        else:
            summary["AI 平台"] = "全部"
        if task_inputs.get("date_from") and task_inputs.get("date_to"):
            summary["时间范围"] = f"{task_inputs['date_from']} ~ {task_inputs['date_to']}"
        elif task_inputs.get("date_from"):
            summary["时间范围"] = f"{task_inputs['date_from']} ~ 至今"
        return [{
            "widget_id": f"opp_confirm_{_uuid.uuid4().hex[:8]}",
            "widget_type": "task_confirm",
            "field": "confirm",
            "label": "确认机会发现配置",
            "summary": summary,
            "confirm_label": "开始分析",
            "task_type": "opportunity_discovery",
            "task_name_template": "优化机会发现 - {date}",
        }]

    widget_def = OPPORTUNITY_WIDGETS.get(current_node)
    if widget_def:
        w = dict(widget_def)
        w["widget_id"] = f"opp_{w['field']}_{_uuid.uuid4().hex[:8]}"
        platforms = client_platforms or ["chatgpt", "gemini", "ai_mode"]
        if w.get("options") == "__DYNAMIC_PLATFORMS__":
            w["options"] = [
                {"id": p, "label": PLATFORM_LABELS.get(p, p), "icon": PLATFORM_ICONS.get(p, "🌐")}
                for p in platforms
            ]
        return [w]
    return []
```

- [ ] **Step 4: Add opportunity_slot_filler_node function**

```python
async def opportunity_slot_filler_node(state: AnalyzeState) -> dict:
    """Guided slot-filling for opportunity discovery (3-step lightweight flow)."""
    model_id = await get_model_id("flash")
    client = await get_genai_client(model_id, role="flash")

    user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    existing_inputs = state.get("task_inputs", {})
    existing_inputs["_flow"] = "opportunity"  # Tag for intent_router re-entry

    # Parse widget responses
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

    # Brand context
    brand_profile = state.get("brand_profile")
    brand_parts = []
    if brand_profile:
        if brand_profile.get("brand_name"):
            brand_parts.append(f"Brand: {brand_profile['brand_name']}")
    brand_context = "Brand context: " + ", ".join(brand_parts) if brand_parts else ""

    persisted_node = existing_inputs.pop("_current_node", 1)

    # Build conversation history
    contents = []
    for msg in state["messages"]:
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
            max_output_tokens=1024,
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
                "我来帮你发现内容优化机会！这个任务会进行 3 项诊断：\n"
                "1️⃣ Topic 四象限定位\n2️⃣ 选题机会挖掘\n3️⃣ 平台-引擎引用关系\n\n"
                "只需简单 3 步配置。首先，您想分析哪些 AI 平台？（不选则分析全部）"
            ),
            "current_node": 1,
            "task_inputs": existing_inputs,
            "is_ready": False,
            **result,
        }

    message_text = result.get("message", "")
    task_inputs = result.get("task_inputs", {})
    is_ready = result.get("is_ready", False)
    current_node = result.get("current_node", 1)

    merged_inputs = {**existing_inputs}
    for k, v in task_inputs.items():
        if v is not None and v != "" and v != []:
            merged_inputs[k] = v

    # Inject fixed fields for opportunity discovery
    merged_inputs["_flow"] = "opportunity"
    merged_inputs["_current_node"] = current_node
    merged_inputs["domains"] = ["visibility", "citation"]
    merged_inputs["analysis_goal"] = "opportunity"

    # Load client platforms
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

    logger.info(f"[ANALYZE] Opportunity slot-fill: node={current_node}, ready={is_ready}")

    return {
        "task_inputs": merged_inputs,
        "task_ready": is_ready,
        "messages": [AIMessage(content=message_text)],
        "widgets": widgets,
    }
```

- [ ] **Step 5: Verify syntax**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_agent && python -c "import ast; ast.parse(open('api/graphs/analyze.py').read()); print('Syntax OK')"`
Expected: "Syntax OK"

- [ ] **Step 6: Commit**

```bash
git add geo_agent/src/graphs/analyze.py
git commit -m "feat(analyze): add opportunity_slot_filler_node with 3-step widget flow"
```

---

### Task 3: Analysis Slot-Filler Node (6-Step Flow with Metrics)

**Files:**
- Modify: `geo_agent/src/graphs/analyze.py` — rename slot_filler to analysis_slot_filler_node, update ANALYZE_WIDGETS, update ANALYZE_SLOT_FILL_SYSTEM, update _build_widgets_for_node

- [ ] **Step 1: Update ANALYZE_WIDGETS with sentiment + metrics node**

Replace the current ANALYZE_WIDGETS dict (lines 29-81):

```python
ANALYZE_WIDGETS = {
    1: {  # Goal
        "widget_type": "single_select",
        "field": "goal",
        "label": "分析视角",
        "options": [
            {"id": "benchmark", "label": "竞品对标", "description": "对比品牌与竞品在AI平台的表现", "icon": "Target"},
            {"id": "trend", "label": "趋势诊断", "description": "分析品牌数据的时间变化趋势", "icon": "TrendingUp"},
            {"id": "health", "label": "全面健康检查", "description": "全方位评估品牌GEO表现", "icon": "Shield"},
            {"id": "sentiment", "label": "情感分析", "description": "深度分析品牌情感维度，识别正面和负面主题", "icon": "MessageSquare"},
        ],
        "required": True,
    },
    2: {  # Metrics + Subgoals (NEW)
        "widget_type": "multi_select",
        "field": "metrics",
        "label": "优化维度",
        "description": "选择关注的优化指标和子目标（可跳过）",
        "options": "__DYNAMIC_METRICS__",
        "required": False,
        "default_value": None,
        "subgoals_field": "subgoals",
        "subgoals_options": "__DYNAMIC_SUBGOALS__",
    },
    3: {  # Domains + Platforms (merged)
        "widget_type": "compound",
        "fields": [
            {
                "widget_type": "multi_select",
                "field": "domains",
                "label": "数据维度",
                "options": [
                    {"id": "visibility", "label": "可见度 (Visibility)", "description": "品牌在AI回答中的提及和排名"},
                    {"id": "citation", "label": "引用 (Citation)", "description": "品牌网站在AI回答中的引用情况"},
                    {"id": "sentiment", "label": "情感 (Sentiment)", "description": "AI回答中对品牌的情感倾向"},
                ],
                "required": True,
                "default_value": ["visibility", "citation", "sentiment"],
            },
            {
                "widget_type": "multi_select",
                "field": "platforms",
                "label": "分析平台",
                "options": "__DYNAMIC_PLATFORMS__",
                "required": True,
                "default_value": "__DYNAMIC_PLATFORMS__",
            },
        ],
    },
    4: {  # Date Range
        "widget_type": "date_range",
        "field": "date_range",
        "label": "分析时间范围",
        "required": True,
        "default_value": {"preset": "last_30_days"},
    },
    5: {  # Depth
        "widget_type": "single_select",
        "field": "depth",
        "label": "分析深度",
        "options": [
            {"id": "quick", "label": "快速概览", "description": "核心指标概览，5分钟生成"},
            {"id": "standard", "label": "标准分析", "description": "多维度分析+图表，10-15分钟"},
            {"id": "deep", "label": "深度诊断", "description": "全面深度分析+洞察建议，20-30分钟"},
        ],
        "required": True,
        "default_value": "standard",
    },
    6: None,  # Confirm — generated dynamically
}

# Goal -> recommended domains mapping
GOAL_RECOMMENDED_DOMAINS = {
    "benchmark": ["visibility", "citation"],
    "trend": ["visibility", "citation", "sentiment"],
    "health": ["visibility", "citation", "sentiment"],
    "sentiment": ["sentiment"],
}
```

- [ ] **Step 2: Update ANALYZE_SLOT_FILL_SYSTEM for 6-step flow with metrics**

Replace the current prompt (lines 88-159):

```python
ANALYZE_SLOT_FILL_SYSTEM = """You are Anthony, a GEO analytics assistant for the AnswerX platform.
Your job is to help the user configure an analysis task by collecting information step by step.

## Workflow Nodes (6 steps)

Guide the user through these 6 nodes **one at a time**.

### Node 1: Analysis Goal (分析视角) — REQUIRED
- "benchmark" — 竞品对标 (compare brand vs competitors)
- "trend" — 趋势诊断 (analyze trends over time)
- "health" — 全面健康检查 (comprehensive health check)
- "sentiment" — 情感分析 (deep sentiment dimension analysis)

### Node 2: Optimization Metrics (优化维度) — OPTIONAL, can skip
Select optimization metrics and sub-goals to focus the analysis.
The available options come from the system's metric catalog.
If the user says "跳过" or doesn't need specific metrics, skip this node.

### Node 3: Data Range (数据范围) — REQUIRED
- Data domains: visibility (可见度), citation (引用), sentiment (情感)
  Auto-recommend based on goal: benchmark→visibility+citation, trend→all, health→all, sentiment→sentiment
- AI platforms: depends on client config (chatgpt, gemini, ai_mode)
  Default: all configured platforms

### Node 4: Date Range (时间范围) — REQUIRED
Accept relative ("最近7天", "最近30天") or absolute dates.
Default: last 30 days

### Node 5: Analysis Depth (分析深度) — REQUIRED
- "quick" — 快速概览 (5 minutes)
- "standard" — 标准分析 (10-15 minutes)
- "deep" — 深度诊断 (20-30 minutes)
Default: standard

### Node 6: Confirm (确认执行)
Summarize ALL collected inputs and set is_ready=true.
Add hint: "如需自定义图表、Prompt 模板或定时任务，可使用「专项分析」模板入口进行精细配置。"

{brand_context}

## Handling widget responses
When the user sends a message starting with '{{"type": "widget_response"', extract field/value and advance.

## Behavior:
- First turn: briefly introduce all 6 nodes, then present Node 1 options.
- Collect ONE node per turn. After answer, move to next.
- Be concise, respond in user's language.
- If user provides info for multiple nodes, extract all and skip ahead.
- When done, set is_ready=true at Node 6.

## Output format (JSON):
{{
  "message": "Your response",
  "current_node": 1-6,
  "task_inputs": {{
    "goal": "benchmark|trend|health|sentiment",
    "selected_metric_ids": ["id1"] or null,
    "selected_subgoal_ids": ["id1"] or null,
    "domains": ["visibility", "citation", "sentiment"],
    "platforms": ["chatgpt", "gemini", "ai_mode"],
    "date_from": "2026-03-01",
    "date_to": "2026-03-31",
    "depth": "quick|standard|deep"
  }},
  "is_ready": true/false,
  "missing_fields": ["field1"]
}}"""
```

- [ ] **Step 3: Update _build_widgets_for_node (rename to _build_analysis_widgets)**

Replace the existing function (lines 285-329):

```python
def _build_analysis_widgets(current_node: int, task_inputs: dict, client_platforms: list[str] | None = None, metrics_data: list | None = None, subgoals_data: list | None = None) -> list[dict]:
    """Generate widgets for analysis slot-filling flow."""
    import uuid as _uuid

    if current_node == 6:
        summary = {}
        goal_labels = {"benchmark": "竞品对标", "trend": "趋势诊断", "health": "全面健康检查", "sentiment": "情感分析"}
        depth_labels = {"quick": "快速概览", "standard": "标准分析", "deep": "深度诊断"}
        if task_inputs.get("goal"):
            summary["分析视角"] = goal_labels.get(task_inputs["goal"], task_inputs["goal"])
        if task_inputs.get("selected_metric_ids"):
            # Look up display names from metrics_data if available
            metric_names = []
            if metrics_data:
                id_to_name = {m["id"]: m.get("display_name", m["name"]) for m in metrics_data}
                metric_names = [id_to_name.get(mid, mid) for mid in task_inputs["selected_metric_ids"]]
            summary["优化维度"] = ", ".join(metric_names) if metric_names else f"{len(task_inputs['selected_metric_ids'])} 项指标"
        if task_inputs.get("domains"):
            domain_labels = {"visibility": "可见度", "citation": "引用", "sentiment": "情感"}
            summary["数据维度"] = ", ".join(domain_labels.get(d, d) for d in task_inputs["domains"])
        if task_inputs.get("platforms"):
            summary["分析平台"] = ", ".join(PLATFORM_LABELS.get(p, p) for p in task_inputs["platforms"])
        if task_inputs.get("date_from") and task_inputs.get("date_to"):
            summary["时间范围"] = f"{task_inputs['date_from']} ~ {task_inputs['date_to']}"
        elif task_inputs.get("date_from"):
            summary["时间范围"] = f"{task_inputs['date_from']} ~ 至今"
        if task_inputs.get("depth"):
            summary["分析深度"] = depth_labels.get(task_inputs["depth"], task_inputs["depth"])
        return [{
            "widget_id": f"analyze_confirm_{_uuid.uuid4().hex[:8]}",
            "widget_type": "task_confirm",
            "field": "confirm",
            "label": "确认分析配置",
            "summary": summary,
            "confirm_label": "开始分析",
        }]

    if current_node == 2:
        # Metrics + subgoals — dynamic from DB
        widgets = []
        metric_options = []
        if metrics_data:
            metric_options = [{"id": m["id"], "label": m.get("display_name", m["name"]), "description": m.get("description", "")} for m in metrics_data]
        widgets.append({
            "widget_id": f"analyze_metrics_{_uuid.uuid4().hex[:8]}",
            "widget_type": "multi_select",
            "field": "selected_metric_ids",
            "label": "优化指标",
            "description": "选择关注的优化指标（可跳过）",
            "options": metric_options,
            "required": False,
        })
        # Subgoals filtered by selected metrics
        selected_metrics = task_inputs.get("selected_metric_ids", [])
        subgoal_options = []
        if subgoals_data:
            filtered = subgoals_data if not selected_metrics else [s for s in subgoals_data if s.get("metric_id") in selected_metrics]
            subgoal_options = [{"id": s["id"], "label": s.get("display_name", s["name"]), "description": s.get("description", "")} for s in filtered]
        if subgoal_options:
            widgets.append({
                "widget_id": f"analyze_subgoals_{_uuid.uuid4().hex[:8]}",
                "widget_type": "multi_select",
                "field": "selected_subgoal_ids",
                "label": "优化子目标",
                "description": "进一步细化关注方向",
                "options": subgoal_options,
                "required": False,
            })
        return widgets

    if current_node == 3:
        # Compound: domains + platforms
        platforms = client_platforms or ["chatgpt", "gemini", "ai_mode"]
        goal = task_inputs.get("goal")
        recommended_domains = GOAL_RECOMMENDED_DOMAINS.get(goal, ["visibility", "citation", "sentiment"])
        return [
            {
                "widget_id": f"analyze_domains_{_uuid.uuid4().hex[:8]}",
                "widget_type": "multi_select",
                "field": "domains",
                "label": "数据维度",
                "options": [
                    {"id": "visibility", "label": "可见度 (Visibility)", "description": "品牌在AI回答中的提及和排名"},
                    {"id": "citation", "label": "引用 (Citation)", "description": "品牌网站在AI回答中的引用情况"},
                    {"id": "sentiment", "label": "情感 (Sentiment)", "description": "AI回答中对品牌的情感倾向"},
                ],
                "required": True,
                "default_value": recommended_domains,
            },
            {
                "widget_id": f"analyze_platforms_{_uuid.uuid4().hex[:8]}",
                "widget_type": "multi_select",
                "field": "platforms",
                "label": "分析平台",
                "options": [
                    {"id": p, "label": PLATFORM_LABELS.get(p, p), "icon": PLATFORM_ICONS.get(p, "🌐")}
                    for p in platforms
                ],
                "required": True,
                "default_value": platforms,
            },
        ]

    widget_def = ANALYZE_WIDGETS.get(current_node)
    if widget_def:
        w = dict(widget_def)
        w["widget_id"] = f"analyze_{w['field']}_{_uuid.uuid4().hex[:8]}"
        platforms = client_platforms or ["chatgpt", "gemini", "ai_mode"]
        if w.get("options") == "__DYNAMIC_PLATFORMS__":
            w["options"] = [
                {"id": p, "label": PLATFORM_LABELS.get(p, p), "icon": PLATFORM_ICONS.get(p, "🌐")}
                for p in platforms
            ]
        if w.get("default_value") == "__DYNAMIC_PLATFORMS__":
            w["default_value"] = platforms
        return [w]
    return []
```

- [ ] **Step 4: Rename analyze_slot_filler_node to analysis_slot_filler_node and add metrics fetching**

Rename the existing function and add metrics/subgoals fetching for Node 2 widgets.

Key changes inside the function:
1. Rename `analyze_slot_filler_node` → `analysis_slot_filler_node`
2. Add `_flow = "analysis"` tag in existing_inputs
3. Fetch metrics_data and subgoals_data from DB when building widgets for node 2
4. Pass metrics_data and subgoals_data to `_build_analysis_widgets`
5. Update goal_labels in confirmation to include "sentiment"

```python
async def analysis_slot_filler_node(state: AnalyzeState) -> dict:
    """Guided slot-filling for analysis task configuration (6-step flow)."""
    # ... (same structure as current analyze_slot_filler_node)
    # Key additions:

    existing_inputs["_flow"] = "analysis"  # Tag for intent_router re-entry

    # ... (LLM call stays the same, using updated ANALYZE_SLOT_FILL_SYSTEM)

    # Fetch metrics/subgoals for Node 2 widget building
    metrics_data = None
    subgoals_data = None
    try:
        from database import get_pool
        pool = await get_pool()
        metrics_rows = await pool.fetch(
            "SELECT id, name, display_name, description FROM geo_optimization_metrics WHERE is_active = true ORDER BY sort_order"
        )
        metrics_data = [dict(r) for r in metrics_rows]
        subgoals_rows = await pool.fetch(
            "SELECT id, metric_id, name, display_name, description FROM geo_optimization_subgoals WHERE is_active = true ORDER BY sort_order"
        )
        subgoals_data = [dict(r) for r in subgoals_rows]
    except Exception:
        pass

    widgets = _build_analysis_widgets(current_node, merged_inputs, client_platforms, metrics_data, subgoals_data)

    # ... (return same structure)
```

- [ ] **Step 5: Verify syntax**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_agent && python -c "import ast; ast.parse(open('api/graphs/analyze.py').read()); print('Syntax OK')"`
Expected: "Syntax OK"

- [ ] **Step 6: Verify graph builds**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_agent && python -c "from api.graphs.analyze import build_analyze_graph; g = build_analyze_graph(); print('Graph nodes:', list(g.nodes.keys()))"`
Expected: Graph nodes include intent_router, nl2sql_generator, query_executor, chart_builder, synthesizer, opportunity_slot_filler, analysis_slot_filler

- [ ] **Step 7: Commit**

```bash
git add geo_agent/src/graphs/analyze.py
git commit -m "feat(analyze): analysis_slot_filler with metrics/subgoals + sentiment goal"
```

---

### Task 4: Content Flow Restructure (Goal-First, 6 Nodes)

**Files:**
- Modify: `geo_agent/src/graphs/action.py:27-103` (CONTENT_WIDGETS)
- Modify: `geo_agent/src/graphs/action.py:106-180` (SLOT_FILL_SYSTEM)
- Modify: `geo_agent/src/graphs/action.py:191-240` (_build_content_widgets)
- Modify: `geo_agent/src/graphs/action.py:243-383` (action_planner_node)

- [ ] **Step 1: Replace CONTENT_WIDGETS with goal-first 6-node flow**

Replace lines 27-103:

```python
CONTENT_WIDGETS = {
    1: [  # Content Goals (metrics + subgoals)
        {
            "widget_type": "multi_select",
            "field": "selected_metrics",
            "label": "优化指标",
            "description": "选择内容需要优化的指标方向",
            "options": "__DYNAMIC_METRICS__",
            "required": True,
        },
    ],
    2: [  # Content Type
        {
            "widget_type": "single_select",
            "field": "content_type",
            "label": "内容类型",
            "options": [
                {"id": "faq", "label": "FAQ 内容", "icon": "HelpCircle", "description": "常见问题解答，适合品牌知识库"},
                {"id": "aeo_article", "label": "AEO 优化文章", "icon": "Bot", "description": "针对AI搜索引擎优化的文章"},
                {"id": "article", "label": "SEO 优化文章", "icon": "FileText", "description": "传统搜索引擎优化文章"},
                {"id": "recommendations", "label": "内容优化建议", "icon": "Lightbulb", "description": "基于GEO数据的内容优化建议"},
                {"id": "brief", "label": "Content Brief", "icon": "ClipboardList", "description": "内容创作指南和大纲"},
            ],
            "required": True,
        },
    ],
    3: [  # Platforms + Config
        {
            "widget_type": "multi_select",
            "field": "ai_platforms",
            "label": "目标 AI 平台",
            "options": "__DYNAMIC_PLATFORMS__",
            "required": True,
            "default_value": "__DYNAMIC_PLATFORMS__",
        },
        {
            "widget_type": "single_select",
            "field": "publish_platform",
            "label": "发布平台",
            "options": [
                {"id": "company_blog", "label": "企业博客", "description": "官方博客或新闻中心"},
                {"id": "knowledge_base", "label": "知识库/帮助中心", "description": "FAQ和产品知识库"},
                {"id": "social_media", "label": "社交媒体", "description": "社交平台内容"},
                {"id": "email", "label": "邮件营销", "description": "邮件内容和Newsletter"},
            ],
            "required": False,
        },
        {
            "widget_type": "structured_input",
            "field": "gen_config",
            "label": "生成配置",
            "inputs": [
                {"key": "count", "label": "生成数量", "type": "number", "placeholder": "5"},
                {"key": "language", "label": "输出语言", "type": "text", "placeholder": "en-US"},
            ],
            "required": False,
        },
    ],
    4: [  # Prompt Link (optional)
        {
            "widget_type": "text_input",
            "field": "target_prompt_ids",
            "label": "目标 Prompt（可选）",
            "required": False,
            "placeholder": "输入要优化的 Prompt ID，或描述目标 Prompt。留空则自动发现。",
        },
    ],
    5: [  # Product Facts (optional)
        {
            "widget_type": "structured_input",
            "field": "product_facts",
            "label": "产品信息（可选）",
            "description": "提供产品核心信息以生成更精准的内容",
            "inputs": [
                {"key": "specs", "label": "产品规格", "type": "text", "placeholder": "例: 5500Pa 吸力, LDS 导航"},
                {"key": "features", "label": "核心卖点", "type": "text", "placeholder": "例: 智能避障, 自清洁基站"},
                {"key": "differentiators", "label": "差异化优势", "type": "text", "placeholder": "例: 同价位段唯一支持 3D 结构光"},
            ],
            "required": False,
        },
    ],
    6: None,  # Confirm — generated dynamically
}
```

- [ ] **Step 2: Replace SLOT_FILL_SYSTEM with goal-first prompt**

Replace lines 106-180:

```python
SLOT_FILL_SYSTEM = """You are Anthony, a GEO content strategy assistant for the AnswerX platform.
Help the user configure a content generation task step by step.

## Workflow (6 steps, goal-first)

### Node 1: Content Goals (优化目标) — REQUIRED
Select optimization metrics and sub-goals that the content should target.
Available metrics come from the system's optimization catalog.
After the user selects metrics, show relevant sub-goals for further refinement.

### Node 2: Content Type (内容类型) — REQUIRED
- "faq" — FAQ 内容 (Q&A for brand knowledge base)
- "aeo_article" — AEO 优化文章 (optimized for AI search engines)
- "article" — SEO 优化文章 (traditional SEO article)
- "recommendations" — 内容优化建议 (data-driven optimization recommendations)
- "brief" — Content Brief (content creation guideline and outline)

### Node 3: Generation Config (生成配置) — REQUIRED
- AI platforms: which AI engines to target (chatgpt, gemini, ai_mode)
- Publish platform (optional): company_blog, knowledge_base, social_media, email
- Count: number of items to generate (default: 5)
- Language: output language (default: en-US)

### Node 4: Target Prompts (目标 Prompt) — OPTIONAL, can skip
Specify target prompt IDs or describe prompts to optimize for.
If skipped, the system auto-discovers low-performing prompts.

### Node 5: Product Facts (产品信息) — OPTIONAL, can skip
Provide product specs, features, and differentiators for more accurate content.
If skipped, the system uses existing brand profile data.

### Node 6: Confirm (确认执行)
Summarize all inputs and set is_ready=true.
Add hint: "如需导入分析报告或自定义内容策略，可使用「内容生成」Pipeline 入口进行精细配置。"

{brand_context}

## Handling widget responses
When the user sends a message starting with '{{"type": "widget_response"', extract field/value and advance.

## Behavior:
- First turn: briefly introduce the goal-first flow, then present Node 1 (metrics selection).
- Collect ONE node per turn.
- For optional nodes (4, 5), proactively suggest skipping if the user seems impatient.
- Respond in the user's language.

## Output format (JSON):
{{
  "message": "Your response",
  "current_node": 1-6,
  "task_inputs": {{
    "selected_metrics": ["id1"],
    "selected_subgoals": ["id1"],
    "content_type": "faq|aeo_article|article|recommendations|brief",
    "ai_platforms": ["chatgpt", "gemini"],
    "publish_platform": "company_blog",
    "count": 5,
    "language": "en-US",
    "target_prompt_ids": ["id1"],
    "product_facts": {{"specs": "...", "features": "...", "differentiators": "..."}}
  }},
  "is_ready": true/false,
  "missing_fields": ["field1"]
}}"""
```

- [ ] **Step 3: Replace _build_content_widgets with goal-first confirmation**

Replace lines 191-240:

```python
def _build_content_widgets(current_node: int, task_inputs: dict, client_platforms: list[str] | None = None, metrics_data: list | None = None, subgoals_data: list | None = None) -> list[dict]:
    """Generate widgets for content generation flow (goal-first)."""
    import uuid as _uuid

    if current_node == 6:
        type_labels = {"faq": "FAQ 内容", "aeo_article": "AEO 文章", "article": "SEO 文章", "recommendations": "优化建议", "brief": "Content Brief"}
        publish_labels = {"company_blog": "企业博客", "knowledge_base": "知识库", "social_media": "社交媒体", "email": "邮件营销"}
        summary = {}
        # Metrics summary
        if task_inputs.get("selected_metrics"):
            metric_names = []
            if metrics_data:
                id_to_name = {m["id"]: m.get("display_name", m["name"]) for m in metrics_data}
                metric_names = [id_to_name.get(mid, mid) for mid in task_inputs["selected_metrics"]]
            summary["优化目标"] = ", ".join(metric_names) if metric_names else f"{len(task_inputs['selected_metrics'])} 项指标"
        if task_inputs.get("content_type"):
            summary["内容类型"] = type_labels.get(task_inputs["content_type"], task_inputs["content_type"])
        if task_inputs.get("ai_platforms"):
            summary["AI 平台"] = ", ".join(PLATFORM_LABELS.get(p, p) for p in task_inputs["ai_platforms"])
        if task_inputs.get("publish_platform"):
            summary["发布平台"] = publish_labels.get(task_inputs["publish_platform"], task_inputs["publish_platform"])
        count = task_inputs.get("count", 5)
        language = task_inputs.get("language", "en-US")
        summary["生成数量"] = str(count)
        summary["输出语言"] = language
        if task_inputs.get("target_prompt_ids"):
            summary["目标 Prompt"] = f"{len(task_inputs['target_prompt_ids'])} 个"
        if task_inputs.get("product_facts"):
            pf = task_inputs["product_facts"]
            filled = sum(1 for v in [pf.get("specs"), pf.get("features"), pf.get("differentiators")] if v)
            summary["产品信息"] = f"已填写 {filled}/3 项" if filled else "未填写"
        return [{
            "widget_id": f"content_confirm_{_uuid.uuid4().hex[:8]}",
            "widget_type": "task_confirm",
            "field": "confirm",
            "label": "确认内容生成配置",
            "summary": summary,
            "confirm_label": "开始生成",
        }]

    if current_node == 1:
        # Metrics + subgoals from DB
        widgets = []
        metric_options = []
        if metrics_data:
            metric_options = [{"id": m["id"], "label": m.get("display_name", m["name"]), "description": m.get("description", "")} for m in metrics_data]
        widgets.append({
            "widget_id": f"content_metrics_{_uuid.uuid4().hex[:8]}",
            "widget_type": "multi_select",
            "field": "selected_metrics",
            "label": "优化指标",
            "description": "选择内容需要优化的指标方向",
            "options": metric_options,
            "required": True,
        })
        selected_metrics = task_inputs.get("selected_metrics", [])
        subgoal_options = []
        if subgoals_data:
            filtered = subgoals_data if not selected_metrics else [s for s in subgoals_data if s.get("metric_id") in selected_metrics]
            subgoal_options = [{"id": s["id"], "label": s.get("display_name", s["name"]), "description": s.get("description", "")} for s in filtered]
        if subgoal_options:
            widgets.append({
                "widget_id": f"content_subgoals_{_uuid.uuid4().hex[:8]}",
                "widget_type": "multi_select",
                "field": "selected_subgoals",
                "label": "优化子目标",
                "description": "细化内容优化方向",
                "options": subgoal_options,
                "required": False,
            })
        return widgets

    widget_defs = CONTENT_WIDGETS.get(current_node)
    if widget_defs:
        platforms = client_platforms or ["chatgpt", "gemini", "ai_mode"]
        result = []
        for wd in widget_defs:
            w = dict(wd)
            w["widget_id"] = f"content_{w['field']}_{_uuid.uuid4().hex[:8]}"
            if w.get("options") == "__DYNAMIC_PLATFORMS__":
                w["options"] = [
                    {"id": p, "label": PLATFORM_LABELS.get(p, p), "icon": PLATFORM_ICONS.get(p, "🌐")}
                    for p in platforms
                ]
            if w.get("default_value") == "__DYNAMIC_PLATFORMS__":
                w["default_value"] = platforms
            result.append(w)
        return result
    return []
```

- [ ] **Step 4: Update action_planner_node to fetch metrics and use new field names**

Key changes to the function:
1. Add metrics_data and subgoals_data fetching (same as analysis_slot_filler_node)
2. Pass them to _build_content_widgets
3. Update return dict to use new field names (`content_type`, `action_topic` removed in favor of task_inputs only)

In the return statement, update:
```python
    return {
        "content_type": merged_inputs.get("content_type"),
        "task_inputs": merged_inputs,
        "task_ready": is_ready,
        "messages": [AIMessage(content=message_text)],
        "widgets": widgets,
    }
```

(Remove `action_topic` since `topic` is no longer collected — topic is derived from metrics/subgoals.)

- [ ] **Step 5: Verify syntax**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_agent && python -c "import ast; ast.parse(open('api/graphs/action.py').read()); print('Syntax OK')"`
Expected: "Syntax OK"

- [ ] **Step 6: Verify graph builds**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_agent && python -c "from api.graphs.action import build_action_graph; g = build_action_graph(); print('Graph nodes:', list(g.nodes.keys()))"`
Expected: Graph nodes: ['action_planner']

- [ ] **Step 7: Commit**

```bash
git add geo_agent/src/graphs/action.py
git commit -m "feat(action): restructure content widgets to goal-first flow aligned with ContentPipelineModal"
```

---

### Task 5: Frontend TaskConfirmCard — Handle task_type Override

**Files:**
- Modify: `geo_saas/web/src/pages/agents/AgentAnalysis.tsx` — the TaskConfirmCard component that handles the `task_confirm` widget's confirm button

The opportunity flow's confirm widget includes `task_type: "opportunity_discovery"` and `task_name_template`.
The frontend needs to read these fields when creating the task on confirm.

- [ ] **Step 1: Find the TaskConfirmCard handler in AgentAnalysis.tsx**

Read the component that handles the confirm button click — it calls `createAgentTask` with `task_type`.

- [ ] **Step 2: Update confirm handler to use widget's task_type if provided**

In the section where the chat-mode confirm creates a task (the `CreateTaskFromChat` or similar component):

```typescript
// Before:
const chatTaskType = "analysis";

// After:
const chatTaskType = msg.widgets?.[widgetIdx]?.task_type || "analysis";
```

And for task_name:
```typescript
// Use widget's task_name_template if available
const taskName = widget.task_name_template
    ? widget.task_name_template.replace("{date}", new Date().toLocaleDateString("zh-CN"))
    : `对话分析: ${GOAL_LABELS[inputs.goal] || inputs.goal || "自定义"}`;
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web && npx tsc --noEmit 2>&1 | head -20`

- [ ] **Step 4: Commit**

```bash
git add geo_saas/web/src/pages/agents/AgentAnalysis.tsx
git commit -m "feat(frontend): support task_type override from chat confirm widget"
```

---

### Task 6: Integration Verification

- [ ] **Step 1: Verify all Python imports resolve**

```bash
cd /Users/lancelot/Desktop/GEO_Demo/geo_agent
python -c "
from api.graphs.analyze import build_analyze_graph
from api.graphs.action import build_action_graph
from api.graphs.supervisor import build_supervisor_graph
print('All graphs build successfully')
ag = build_analyze_graph()
print('Analyze nodes:', list(ag.nodes.keys()))
acg = build_action_graph()
print('Action nodes:', list(acg.nodes.keys()))
"
```

Expected:
- Analyze nodes: intent_router, nl2sql_generator, query_executor, chart_builder, synthesizer, opportunity_slot_filler, analysis_slot_filler
- Action nodes: action_planner

- [ ] **Step 2: Verify frontend builds**

```bash
cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web && npm run build 2>&1 | tail -5
```

Expected: Build succeeds

- [ ] **Step 3: Commit (if any fixups needed)**

```bash
git add -A
git commit -m "fix: integration fixups for chat widget alignment"
```
