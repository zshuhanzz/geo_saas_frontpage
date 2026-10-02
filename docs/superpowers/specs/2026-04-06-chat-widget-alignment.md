# Chat-Mode Widget Alignment with Latest Workflows

> Product Design Spec  
> Date: 2026-04-06  
> Status: Draft

---

## 1. Background & Problem

Chat-mode (Anthony) uses slot-filling widgets to guide users through task creation conversationally.
These widget flows were designed before the recent Analyzer and Content workflow redesigns, and are
now out of sync with the latest Modal workflows.

**Key misalignments:**

| Area | Chat Widget (Current) | Modal (Latest) | Gap |
|------|-----------------------|-----------------|-----|
| Analyzer goals | benchmark, trend, health (3) | benchmark, trend, health, sentiment (4) + dedicated Mode A | Missing sentiment; no opportunity path |
| Analyzer metrics | None | Step 2: metrics + subgoals | Missing entirely |
| Analyzer peers | None | Step 3: peer selection | Missing |
| Content flow order | Type-first (content_type -> topic -> platforms -> ...) | Goal-first (metrics/subgoals -> content_type -> strategy -> ...) | Reversed priority |
| Content strategy | Manual text input (strategy_prompt) | Auto-generated from metrics via API | Different mechanism |
| Content product facts | None | Node 4: specs/features/differentiators | Missing |
| Content publish platform | None | Node 4: publish_platform | Missing |
| Content analyzer import | None | Node 0: link to analyzer task | Missing |

---

## 2. Design Principles

1. **Chat = lightweight express lane.** Cover core fields only. Advanced config (charts, prompt editing, cron, model selection, baseline) stays Modal-only.
2. **Parity on task inputs.** The task created by chat MUST be runnable by the same pipeline. Missing optional fields use sensible defaults.
3. **Hint to Modal.** When the user might benefit from fine-grained control, the LLM should suggest "如需精细配置，可使用模板入口".
4. **Consistent semantics.** Same field names, same option IDs, same task_type as Modal.

---

## 3. Analyzer Chat Flow Redesign

### 3.1 Two Sub-Intents within Analyze Sub-graph

The Analyze sub-graph currently routes between `direct` (NL2SQL) and `guided` (slot-filling).
After this redesign, the `guided` path further branches into two flows:

| Sub-Intent | Task Type | Description | Widget Nodes |
|------------|-----------|-------------|--------------|
| **opportunity** | `opportunity_discovery` | Lightweight diagnostic: Topic quadrant, content opportunities, platform-engine mapping | 3 nodes |
| **analysis** | `analysis` | Configurable analysis: benchmark/trend/health/sentiment with metrics | 6 nodes |

**Routing logic (intent_router):**

```
User message
  -> direct? (specific SQL-answerable question) -> NL2SQL pipeline
  -> guided?
       -> opportunity-related keywords? -> opportunity_slot_filler
       -> otherwise -> analysis_slot_filler
```

**Opportunity keywords (for LLM classification):**
- "优化机会", "机会发现", "内容机会", "哪些内容可以优化", "opportunity", "找机会",
  "content opportunity", "what to optimize", "薄弱环节", "提升空间"

**Supervisor change:** None. Supervisor intent "analyze" stays the same.
The sub-classification happens inside the Analyze sub-graph's intent_router.

### 3.2 Opportunity Flow (3 nodes)

Aligned with OpportunityAnalysisModal. Lightweight, express path.

| Node | Field | Widget Type | Label | Options | Required | Default |
|------|-------|-------------|-------|---------|----------|---------|
| 1 | platforms | multi_select | AI 平台筛选 | __DYNAMIC_PLATFORMS__ | No | All (null = all) |
| 2 | date_range | date_range | 分析时间范围 | preset: last_30_days | Yes | 30 days |
| 3 | confirm | task_confirm | 确认机会发现配置 | Summary | - | - |

**Fixed inputs (not collected via widget):**
- `domains`: `["visibility", "citation"]` (hardcoded, same as OpportunityAnalysisModal)
- `analysis_goal`: `"opportunity"` (hardcoded)
- `task_type`: `"opportunity_discovery"`

**Task name:** `"优化机会发现 - {date}"`

### 3.3 Analysis Flow (6 nodes)

Aligned with TemplateConfigModal (Mode B), lightweight version.

| Node | Field | Widget Type | Label | Options | Required | Default |
|------|-------|-------------|-------|---------|----------|---------|
| 1 | goal | single_select | 分析视角 | benchmark, trend, health, sentiment (4 options) | Yes | - |
| 2 | metrics | multi_select | 优化维度 | __DYNAMIC_METRICS__ (from API) | No | Skip if empty |
| 3 | domains_platforms | compound | 数据范围 | domains (multi) + platforms (multi) | Yes | All domains, all platforms |
| 4 | date_range | date_range | 分析时间范围 | preset: last_30_days | Yes | 30 days |
| 5 | depth | single_select | 分析深度 | quick, standard, deep | Yes | standard |
| 6 | confirm | task_confirm | 确认分析配置 | Summary | - | - |

**Changes from current:**
- Node 1: Add `sentiment` option (4th goal, matching Modal)
- Node 2: **NEW** — metrics + subgoals selection (lightweight version of Modal Step 2)
  - Fetch from `getOptimizationMetrics` / `getOptimizationSubgoals` APIs
  - If user says "跳过", skip entirely (field is optional)
  - Subgoals filtered by selected metrics, same as Modal
- Node 3: **MERGED** — domains + platforms combined into one step (was separate nodes 2+3)
  - Domains auto-recommended based on goal (same logic as Modal Step 1)
  - Platforms from client config
- Node 4: Date range (was node 4, unchanged)
- Node 5: Depth (was node 5, unchanged)
- Node 6: Confirm (was node 6)

**Modal-only fields (NOT in chat, uses defaults):**
- `chart_requests`: Auto-generated from goal's recommended charts
- `prompt`: Default template based on goal + depth
- `model_id`: Default model
- `cron_expression`: null (no scheduling)
- `peer_ids`: null (no peer comparison)
- `baseline_type`: "none"
- `thresholds`: null
- `focus_tags`: null

**Hint message at confirm:** "如需自定义图表、Prompt 模板或定时任务，可使用「专项分析」模板入口进行精细配置。"

---

## 4. Content Chat Flow Redesign

### 4.1 New Node Order (Goal-First)

Aligned with ContentPipelineModal's 7-node flow, condensed to 6 chat nodes.

| Node | Field | Widget Type | Label | Options | Required | Default |
|------|-------|-------------|-------|---------|----------|---------|
| 1 | content_goals | multi_select | 优化目标 | __DYNAMIC_METRICS__ + subgoals | Yes | - |
| 2 | content_type | single_select | 内容类型 | faq, aeo_article, article, recommendations, brief | Yes | - |
| 3 | platforms_config | compound | 生成配置 | ai_platforms (multi) + publish_platform (single) + language + count | Yes | All AI platforms, en-US, 5 |
| 4 | prompt_link | text_input | 目标 Prompt | Prompt IDs or description (optional) | No | Auto-discover |
| 5 | product_facts | structured_input | 产品信息 | specs, features, differentiators (all optional) | No | Skip |
| 6 | confirm | task_confirm | 确认内容生成配置 | Summary | - | - |

**Changes from current:**
- **Node 1**: Was content_type+topic, now **content_goals** (metrics + subgoals)
  - Same API as Analyzer: `getOptimizationMetrics` / `getOptimizationSubgoals`
  - Replaces the old `data_domains` and `strategy_prompt` nodes
  - Strategy will be auto-generated by the pipeline based on selected goals
- **Node 2**: Content type (was part of old Node 1, now standalone)
  - `topic` field removed — topic is derived from selected metrics/subgoals by the pipeline
- **Node 3**: Platforms + config (was old Node 2, now expanded)
  - Added `publish_platform` (single_select: company_blog, knowledge_base, social_media, email)
  - `ai_platforms` replaces `platforms` (field name alignment with Modal)
- **Node 4**: Prompt link (was old Node 3, mostly unchanged)
- **Node 5**: **NEW** — Product facts (from Modal Node 4)
  - Optional structured input for specs, features, differentiators
  - If user says "跳过", skip entirely
- **Node 6**: Confirm

**Removed nodes:**
- Old Node 4 (data_domains) — replaced by metrics/subgoals in Node 1
- Old Node 5 (strategy_prompt) — replaced by auto-generated strategy from goals

**Modal-only fields (NOT in chat, uses defaults):**
- `analyzer_task_id` / `analyzer_context`: null (no analyzer linking in chat mode)
- `user_strategy_edits`: null (strategy auto-generated)

**Task inputs sent:**
```json
{
  "selected_metrics": ["metric1", "metric2"],
  "selected_subgoals": ["subgoal1"],
  "content_type": "faq",
  "ai_platforms": ["chatgpt", "gemini"],
  "publish_platform": "company_blog",
  "language": "en-US",
  "count": 5,
  "product_facts": { "specs": "...", "features": "...", "differentiators": "..." },
  "target_prompt_ids": ["prompt1"]
}
```

**Hint message at confirm:** "如需导入分析报告数据或自定义内容策略，可使用「内容生成」Pipeline 入口进行精细配置。"

---

## 5. Graph Architecture Changes

### 5.1 Analyze Sub-graph (analyze.py)

**Before:**
```
intent_router ─→ [direct] ─→ nl2sql_generator → query_executor → chart_builder → synthesizer → END
              └→ [guided] ─→ slot_filler → END
```

**After:**
```
intent_router ─→ [direct]      ─→ nl2sql_generator → query_executor → chart_builder → synthesizer → END
              ├→ [opportunity]  ─→ opportunity_slot_filler → END
              └→ [analysis]    ─→ analysis_slot_filler → END
```

- `intent_router` returns `_mode`: "direct" | "opportunity" | "analysis"
- `opportunity_slot_filler`: New node, 3-step flow, emits `task_type: "opportunity_discovery"`
- `analysis_slot_filler`: Renamed from `slot_filler`, updated to 6-step flow with metrics

### 5.2 Action Sub-graph (action.py)

**Before:**
```
action_planner → END
```

**After:**
```
action_planner → END  (same structure, single multi-turn node)
```

No graph structure change needed. Only the widget definitions and system prompt change.

### 5.3 Supervisor (supervisor.py)

No changes needed. The "analyze" and "action" intents stay the same.
Sub-classification happens within each sub-graph.

---

## 6. State Schema Changes

### AnalyzeState

No new fields needed. The existing `task_inputs` dict and `task_ready` bool handle everything.
The `_mode` field gains a third value: `"opportunity"`.

### ActionState

No new fields needed. `task_inputs` dict is flexible enough for the new field names.

---

## 7. Confirmation Widget Summary Fields

### Opportunity Confirm
| Key | Label |
|-----|-------|
| 分析类型 | 优化机会发现 |
| AI 平台 | ChatGPT, Gemini, ... (or "全部") |
| 时间范围 | 2026-03-07 ~ 2026-04-06 |

### Analysis Confirm
| Key | Label |
|-----|-------|
| 分析视角 | 竞品对标 / 趋势诊断 / 全面健康检查 / 情感分析 |
| 优化维度 | Metric A, Metric B (or "未选择") |
| 数据维度 | 可见度, 引用, 情感 |
| 分析平台 | ChatGPT, Gemini, ... |
| 时间范围 | 2026-03-07 ~ 2026-04-06 |
| 分析深度 | 快速概览 / 标准分析 / 深度诊断 |

### Content Confirm
| Key | Label |
|-----|-------|
| 优化目标 | Metric A > Subgoal 1, Subgoal 2 |
| 内容类型 | FAQ 内容 / AEO 文章 / ... |
| AI 平台 | ChatGPT, Gemini, ... |
| 发布平台 | 企业博客 / 知识库 / ... |
| 生成数量 | 5 |
| 输出语言 | en-US |
| 目标 Prompt | 3 prompts linked (or "自动发现") |
| 产品信息 | 已填写 / 未填写 |

---

## 8. Dynamic Widget Data Sources

Both Analyzer and Content flows need to fetch metrics/subgoals at runtime.
These are fetched from the same API endpoints the Modal uses:

- `GET /api/agent/optimization-metrics` → metric list
- `GET /api/agent/optimization-subgoals` → subgoal list (filterable by metric_id)

In the chat backend, these are fetched in the slot-filler node when building widgets for the metrics node.
The widget options are populated dynamically, similar to how `__DYNAMIC_PLATFORMS__` works today.

---

## 9. Migration Notes

- The change to `analyze.py` I already made (removing "opportunity" from ANALYZE_WIDGETS) needs to be **reverted and replaced** with the full redesign described here.
- No database schema changes required — all new fields fit within existing `task_inputs` JSONB.
- No frontend widget rendering changes required — all widget types (single_select, multi_select, date_range, structured_input, task_confirm) already exist.
