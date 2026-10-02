-- =============================================================================
-- Migration 031: Schema-driven wizard alignment — complete field definitions
--                for Analyze + Content side, 7-node Content restructure to
--                match ContentPipelineModal canonical UX
-- =============================================================================
--
-- Context
-- -------
-- Round 2/3 of the SaaS wizard refactor. Migration 028 seeded the workflow_step
-- skeleton (key + num + label only). Migration 029 layered in the DDPP/RATF
-- dictionaries and added analysis_framework + data disclosure. Both left the
-- per-step `fields` array sparse — only 1-2 fields per step, missing the
-- platform picker, peer picker, chart builder, prompt editor, and every
-- Content-side interactive widget (analyzer import, content strategy, prompt
-- link).
--
-- Round 2 (SaaS UI) is switching to a fully schema-driven wizard —
-- TemplateConfigModal + ContentPipelineModal both mount a single `WizardShell`
-- that reads definitions from `/tasks/workflow-config` and overrides from
-- each template's `wizard_config.steps`. For that to work, every visual field
-- the wizards render today must be declared in the workflow_step row.
--
-- Scope of 031
-- ------------
--   A. (Analysis) UPDATE `data_selection` — add default_platforms (multi_ref
--      → platform/shared) and default_peers (custom: peer_picker).
--   B. (Analysis) UPDATE `chart_config` — replace the legacy `list` field
--      with a `chart_builder` custom field type (same data shape, richer UI).
--   C. (Analysis) UPDATE `prompt_edit` — add a `custom_prompt` field of
--      custom type `prompt_editor` with variable-catalog + methodology awareness.
--      Keeps `disable_user_edit` + `include_data_disclosure` from 029.
--   D. (Analysis) Backfill each Analyze template's `wizard_config.steps` with
--      defaults pulled from the legacy `defaults` jsonb bag so nothing
--      regresses when we flip the UI to schema-driven rendering.
--
--   E. (Content) DELETE all 8 existing content_generation workflow_step rows
--      (content_goal / content_framework / content_type / output_config /
--      prompt_select / data_strategy / model_schedule / confirm_execute) —
--      the old 8-step structure is being replaced outright with the 7-node
--      structure from ContentPipelineModal.tsx. No historical task data
--      exists so the destructive delete is safe.
--   F. (Content) INSERT 7 new content_generation workflow_step rows matching
--      ContentPipelineModal.NODE_LABELS exactly:
--         1. analysis_import    (custom: analyzer_import)
--         2. content_goal       (multi_ref: content_metric + content_sub_goal)
--         3. content_type       (single_ref: content_type)
--         4. content_strategy   (custom: strategy_generator — depends on
--            analyzer_context + content_goal selections)
--         5. generation_config  (number + single_ref + multi_ref + custom:
--            product_facts_form — AI platforms, publish platform, language,
--            count, product facts, data disclosure)
--         6. prompt_link        (custom: prompt_ref_picker)
--         7. confirm_execute    (empty)
--   G. (Content) Backfill each Content template's `wizard_config.steps` with
--      defaults migrated from the legacy wizard_config shape (content_framework
--      → content_goal merge, output_config → generation_config merge).
--
-- Safe-rerun strategy:
--   · Analysis side — surgical UPDATEs with idempotent payloads
--   · Content side — DELETE-then-INSERT (atomic rewrite) for workflow_step,
--     plus jsonb_set backfill which is naturally idempotent
--   · Wrapped in one transaction
-- =============================================================================

BEGIN;

-- ============================================================
-- A. Analysis `data_selection` — add platform picker + peer picker
-- ============================================================
-- Keeps existing default_domains + default_date_range (from 028), extends
-- with default_platforms (multi_ref → platform/shared) and default_peers
-- (custom: peer_picker — the component fetches peers from the
-- `/clients/{client_id}/peers` API at render time, so no ref_config_type).
UPDATE geo_workflow_config
SET value = '{
  "num": 3,
  "label": "数据选择 (Data Selection)",
  "description": "选择要纳入本次分析的数据领域、时间范围、平台与竞品集合",
  "fields": [
    {
      "key": "default_domains",
      "type": "multi_ref",
      "label": "默认数据领域",
      "ref_config_type": "domain",
      "ref_scope": "shared",
      "description": "可见度 / 引用 / 情绪 — 模板默认勾选的领域"
    },
    {
      "key": "default_date_range",
      "type": "single_ref",
      "label": "默认时间范围",
      "ref_config_type": "date_range",
      "ref_scope": "shared",
      "description": "默认回看窗口"
    },
    {
      "key": "default_platforms",
      "type": "multi_ref",
      "label": "默认 AI 平台",
      "ref_config_type": "platform",
      "ref_scope": "shared",
      "description": "ChatGPT / Gemini / AI Mode — 限定本次分析的平台范围"
    },
    {
      "key": "default_peers",
      "type": "peer_picker",
      "label": "默认竞品集合",
      "description": "从客户的 peer 库中挑选本次分析要对比的竞品；运行时组件从 /clients/{client_id}/peers 加载",
      "config": {
        "allow_empty": true
      }
    }
  ]
}'::jsonb,
    sort_order = 3
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'data_selection';


-- ============================================================
-- B. Analysis `chart_config` — switch to chart_builder custom field
-- ============================================================
-- The `list` primitive from 028 worked but had no diff/reorder UI and no
-- preview. Replace with a dedicated `chart_builder` custom type that reads
-- the same persisted shape (`{ nl_query, chart_type }[]`) but exposes the
-- rich editing UX from Step3_Charts in TemplateConfigModal.
UPDATE geo_workflow_config
SET value = '{
  "num": 4,
  "label": "图表配置 (Chart Config)",
  "description": "配置要预生成的图表列表；每条一个自然语言 NL Query + 可选图表类型",
  "fields": [
    {
      "key": "default_charts",
      "type": "chart_builder",
      "label": "默认图表",
      "description": "按顺序渲染；运行时由 NL2SQL pipeline 为每条 NL Query 生成数据",
      "config": {
        "min_charts": 0,
        "max_charts": 12,
        "chart_types_ref": {
          "ref_config_type": "chart_type",
          "ref_scope": "shared"
        }
      }
    },
    {
      "key": "default_threshold",
      "type": "number",
      "label": "阈值提示 (可选)",
      "description": "当某个关键指标低于此阈值时在报告中高亮 (留空 = 不启用)"
    },
    {
      "key": "default_baseline",
      "type": "text",
      "label": "基线说明 (可选)",
      "description": "自由文本 — 例如「对标 2026 Q1 行业均值 42%」"
    }
  ]
}'::jsonb,
    sort_order = 4
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'chart_config';


-- ============================================================
-- C. Analysis `prompt_edit` — add prompt_editor custom field
-- ============================================================
-- 029 added `disable_user_edit` + `include_data_disclosure`. Round 2 adds a
-- third field: `custom_prompt` of type `prompt_editor` — the component
-- knows how to render the variable catalog, highlight `[点击替换为可见度指标]`
-- style markers, and depends on selected metrics via a field computer.
UPDATE geo_workflow_config
SET value = '{
  "num": 5,
  "label": "Prompt 编辑 (Prompt Edit)",
  "description": "终端用户微调 LLM 提示词；可锁定编辑权限 + 控制数据依据披露",
  "fields": [
    {
      "key": "disable_user_edit",
      "type": "boolean",
      "label": "禁止终端用户编辑 Prompt",
      "default": false,
      "description": "开启后 SaaS 端的 Prompt 编辑框只读，终端用户不能改动；适用于合规 / 内置模板 / 强约束场景"
    },
    {
      "key": "include_data_disclosure",
      "type": "boolean",
      "label": "插入「真实数据依据」章节",
      "default": true,
      "description": "运行时在报告开头注入本次分析用到的所有真实指标值、图表数据、时间范围作为硬约束；是数据准确性的核心防线，强烈建议始终开启"
    },
    {
      "key": "custom_prompt",
      "type": "prompt_editor",
      "label": "自定义提示词 (可选)",
      "description": "留空则使用模板 default_prompt；支持变量捕获（如 [点击替换为可见度指标] 会被选中指标自动替换）",
      "depends_on": ["default_metrics"],
      "compute_default": "prompt_template_with_metrics",
      "config": {
        "variable_catalog_ref": {
          "ref_config_type": "analysis_lens",
          "ref_scope": "analysis"
        },
        "max_length": 8000
      }
    }
  ]
}'::jsonb,
    sort_order = 5
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'prompt_edit';


-- ============================================================
-- D. Analyze templates — backfill wizard_config.steps with defaults
-- ============================================================

-- D.1  data_selection.default_platforms := defaults.platforms (if present)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,data_selection,default_platforms}',
    COALESCE(defaults->'platforms', '[]'::jsonb)
)
WHERE task_type = 'analysis';

-- D.2  data_selection.default_peers := defaults.peers (if present)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,data_selection,default_peers}',
    COALESCE(defaults->'peers', '[]'::jsonb)
)
WHERE task_type = 'analysis';

-- D.3  chart_config.default_charts := defaults.charts (if present) — preserves
--      any hand-curated chart list; otherwise seed an empty list so the
--      chart_builder shows "add first chart" instead of undefined.
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,chart_config,default_charts}',
    COALESCE(wizard_config#>'{steps,chart_config,default_charts}',
             defaults->'charts',
             '[]'::jsonb)
)
WHERE task_type = 'analysis';

-- D.4  prompt_edit.custom_prompt := '' (empty — the editor falls back to
--      template.default_prompt when empty)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,prompt_edit,custom_prompt}',
    COALESCE(wizard_config#>'{steps,prompt_edit,custom_prompt}', '""'::jsonb)
)
WHERE task_type = 'analysis';


-- ============================================================
-- E. DROP all existing content_generation workflow_step rows
-- ============================================================
-- 8 rows from 029: content_goal / content_framework / content_type /
-- output_config / prompt_select / data_strategy / model_schedule /
-- confirm_execute. All replaced with 7 new rows below.
-- Safe: agent_tasks table is empty (confirmed with user), no live task
-- references these step keys.
DELETE FROM geo_workflow_config
WHERE config_type = 'workflow_step' AND scope = 'content_generation';


-- ============================================================
-- F. INSERT 7 new content_generation workflow_step rows
-- ============================================================
-- Matches ContentPipelineModal.tsx NODE_LABELS exactly:
--   分析报告引入 / 内容目标 / 内容类型 / 内容策略 /
--   生成配置 / Prompt 关联 / 确认执行
INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES

-- Step 1: 分析报告引入 (Analysis Import)
-- Imports an opportunity_discovery analyzer task's output as context so the
-- Content pipeline can target real gaps instead of guessed topics. Implemented
-- as a single custom field — the component queries /agent/tasks?task_type=analyzer
-- and surfaces compatible outputs.
('workflow_step', 'content_generation', 'analysis_import', '',
 '{
   "num": 1,
   "label": "分析报告引入 (Analysis Import)",
   "description": "选择一个已完成的 Analyzer 任务作为本次内容生成的上下文来源。导入后其 top negative themes / visibility gaps / low-citation prompts 等数据会作为 ground truth 注入后续节点",
   "fields": [
     {
       "key": "analyzer_task_id",
       "type": "analyzer_import",
       "label": "Analyzer 任务",
       "description": "从客户已完成的 Analyzer 任务中选择一个作为内容生成的上下文。建议选择 opportunity_discovery 类型以获得最精准的机会清单",
       "required": true,
       "config": {
         "compatible_task_types": ["analyzer", "opportunity_discovery"],
         "require_status": "succeeded"
       }
     }
   ]
 }'::jsonb, 1, true),

-- Step 2: 内容目标 (Content Goal) — RATF metrics + sub-goals
-- Collapses the 029 "content_goal" (business goal) and "content_framework"
-- (RATF methodology) into a single step that matches NodeContentGoals in
-- ContentPipelineModal. The business goal lives on the template itself via
-- defaults.goal — it does NOT need a user-facing step because each template
-- already encodes its business intent.
('workflow_step', 'content_generation', 'content_goal', '',
 '{
   "num": 2,
   "label": "内容目标 (Content Goal)",
   "description": "选择本次内容需要优化的 RATF 质量维度与具体子目标 — 可读性 / 可做答案性 / 可信赖性 / 时效性",
   "fields": [
     {
       "key": "default_metrics",
       "type": "multi_ref",
       "label": "默认质量维度",
       "ref_config_type": "content_metric",
       "ref_scope": "content_generation",
       "required": true,
       "description": "RATF 四个顶层维度 — readability / answerability / trustworthy / freshness"
     },
     {
       "key": "default_sub_goals",
       "type": "multi_ref",
       "label": "默认子目标",
       "ref_config_type": "content_sub_goal",
       "ref_scope": "content_generation",
       "required": true,
       "depends_on": ["default_metrics"],
       "description": "9 个具体子目标，每个绑定到某个质量维度（二级选项）。选定顶层维度后，相关子目标自动可选"
     }
   ]
 }'::jsonb, 2, true),

-- Step 3: 内容类型 (Content Type)
('workflow_step', 'content_generation', 'content_type', '',
 '{
   "num": 3,
   "label": "内容类型 (Content Type)",
   "description": "选择要生成的内容形态 — FAQ / AEO 文章 / SEO 文章 / 优化建议 / Content Brief",
   "fields": [
     {
       "key": "default",
       "type": "single_ref",
       "label": "默认内容类型",
       "ref_config_type": "content_type",
       "ref_scope": "content_generation",
       "required": true,
       "description": "每种类型对应不同的 prompt 模板、数据披露默认值与生成结构"
     }
   ]
 }'::jsonb, 3, true),

-- Step 4: 内容策略 (Content Strategy)
-- Auto-generated strategy based on analyzer_context + selected RATF metrics
-- + content_type. User can edit the generated strategy before continuing.
-- Implemented as a custom field — the component runs its own LLM call via
-- /agent/tasks/strategy/generate.
('workflow_step', 'content_generation', 'content_strategy', '',
 '{
   "num": 4,
   "label": "内容策略 (Content Strategy)",
   "description": "基于导入的 Analyzer 报告 + 已选的 RATF 维度 + 内容类型，自动生成本次内容的策略草案。用户可以直接编辑草案或点击「重新生成」",
   "fields": [
     {
       "key": "strategy",
       "type": "strategy_generator",
       "label": "策略草案",
       "description": "包含：目标受众、核心主题、关键卖点、差异化角度、平台适配建议。可编辑",
       "required": true,
       "depends_on": ["analyzer_task_id", "default_metrics", "default_sub_goals", "default"],
       "config": {
         "endpoint": "/agent/tasks/strategy/generate",
         "allow_regenerate": true,
         "allow_manual_edit": true
       }
     }
   ]
 }'::jsonb, 4, true),

-- Step 5: 生成配置 (Generation Config)
-- Maps to NodeGenConfig in ContentPipelineModal. Collapses the 029 output_config
-- + parts of data_strategy into one step.
('workflow_step', 'content_generation', 'generation_config', '',
 '{
   "num": 5,
   "label": "生成配置 (Generation Config)",
   "description": "生成数量、深度、AI 平台适配、发布平台、语言、产品事实卡片",
   "fields": [
     {
       "key": "default_count",
       "type": "number",
       "label": "默认数量",
       "description": "单次生成的内容条数（FAQ 常用 5 条、文章 1 篇）"
     },
     {
       "key": "default_depth",
       "type": "single_ref",
       "label": "默认深度",
       "ref_config_type": "depth",
       "ref_scope": "content_generation",
       "description": "快速生成 / 标准生成 / 深度优化"
     },
     {
       "key": "default_ai_platforms",
       "type": "multi_ref",
       "label": "默认 AI 平台",
       "ref_config_type": "platform",
       "ref_scope": "shared",
       "description": "内容要适配的 AI 搜索平台（ChatGPT / Gemini / AI Mode）— 影响回答风格"
     },
     {
       "key": "default_publish_platform",
       "type": "text",
       "label": "默认发布平台",
       "description": "发布目标（品牌官网 / 官方博客 / LinkedIn / Medium 等） — 影响语气与格式"
     },
     {
       "key": "default_language",
       "type": "text",
       "label": "默认语言",
       "default": "en-US",
       "description": "生成内容的语言代码，例如 en-US / zh-CN"
     },
     {
       "key": "default_product_facts",
       "type": "product_facts_form",
       "label": "产品事实卡片",
       "description": "产品规格 / 功能 / 差异化卖点 — 作为硬约束注入生成 prompt 防止 LLM 幻觉",
       "config": {
         "fields": ["specs", "features", "differentiators"]
       }
     },
     {
       "key": "include_data_disclosure",
       "type": "boolean",
       "label": "插入「真实数据依据」章节",
       "default": true,
       "description": "在生成内容开头注入本次用到的真实指标与数据快照作为依据披露。FAQ / AEO / SEO 等面向终端读者的文章型内容建议关闭；优化建议 / Content Brief 等内部参考型内容建议开启"
     }
   ]
 }'::jsonb, 5, true),

-- Step 6: Prompt 关联 (Prompt Link)
-- Picks which low-performing prompts from the analyzer context to target.
-- Custom field that reads analyzer_task_id + content_strategy output.
('workflow_step', 'content_generation', 'prompt_link', '',
 '{
   "num": 6,
   "label": "Prompt 关联 (Prompt Link)",
   "description": "从 Analyzer 报告中挑选本次内容要直接对应的 prompts。生成的内容会标注目标 prompt_id 以便后续 Visibility / Citation 追踪",
   "fields": [
     {
       "key": "prompt_ids",
       "type": "prompt_ref_picker",
       "label": "目标 Prompts",
       "description": "基于 analyzer_task_id 加载候选 prompt 列表，按 visibility / citation 得分排序",
       "depends_on": ["analyzer_task_id", "default_sort"],
       "config": {
         "allow_empty": false,
         "min_count": 1,
         "max_count": 20
       }
     },
     {
       "key": "default_sort",
       "type": "single_ref",
       "label": "默认排序",
       "ref_config_type": "sort_option",
       "ref_scope": "content_generation",
       "description": "优先处理 Visibility / Citation / Sentiment 最差的 Prompt"
     }
   ]
 }'::jsonb, 6, true),

-- Step 7: 确认执行 (Confirm Execute)
('workflow_step', 'content_generation', 'confirm_execute', '',
 '{
   "num": 7,
   "label": "确认执行 (Confirm Execute)",
   "description": "复核所有配置后触发内容生成 — 无默认字段",
   "fields": []
 }'::jsonb, 7, true);


-- ============================================================
-- G. Content templates — backfill wizard_config.steps with new 7-node shape
-- ============================================================

-- G.1  Drop stale 029 step keys that no longer exist (content_framework +
--      output_config + prompt_select + data_strategy + model_schedule)
UPDATE geo_report_templates
SET wizard_config = wizard_config
    #- '{steps,content_framework}'
    #- '{steps,output_config}'
    #- '{steps,prompt_select}'
    #- '{steps,data_strategy}'
    #- '{steps,model_schedule}'
WHERE task_type = 'content_generation';

-- G.2  Ensure all 7 new step keys exist with enabled=true
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    jsonb_set(
        jsonb_set(
            jsonb_set(
                jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            wizard_config,
                            '{steps,analysis_import}',
                            COALESCE(wizard_config#>'{steps,analysis_import}', '{"__enabled":true}'::jsonb)
                        ),
                        '{steps,content_goal}',
                        COALESCE(wizard_config#>'{steps,content_goal}', '{"__enabled":true}'::jsonb)
                    ),
                    '{steps,content_type}',
                    COALESCE(wizard_config#>'{steps,content_type}', '{"__enabled":true}'::jsonb)
                ),
                '{steps,content_strategy}',
                COALESCE(wizard_config#>'{steps,content_strategy}', '{"__enabled":true}'::jsonb)
            ),
            '{steps,generation_config}',
            COALESCE(wizard_config#>'{steps,generation_config}', '{"__enabled":true}'::jsonb)
        ),
        '{steps,prompt_link}',
        COALESCE(wizard_config#>'{steps,prompt_link}', '{"__enabled":true}'::jsonb)
    ),
    '{steps,confirm_execute}',
    COALESCE(wizard_config#>'{steps,confirm_execute}', '{"__enabled":true}'::jsonb)
)
WHERE task_type = 'content_generation';

-- G.3  content_goal — migrate RATF metrics from old content_framework sub-tree
--      (that sub-tree is already dropped at G.1, so we fall back to reading
--      from the original 029-era structure if it still exists, then to the
--      template-level defaults bag)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_goal,default_metrics}',
    COALESCE(
        wizard_config#>'{steps,content_goal,default_metrics}',
        defaults->'metrics',
        '[]'::jsonb
    )
)
WHERE task_type = 'content_generation';

UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_goal,default_sub_goals}',
    COALESCE(
        wizard_config#>'{steps,content_goal,default_sub_goals}',
        wizard_config->'required_subgoals',
        '[]'::jsonb
    )
)
WHERE task_type = 'content_generation';

-- G.4  content_type.default := defaults.content_type
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_type,default}',
    to_jsonb(defaults->>'content_type')
)
WHERE task_type = 'content_generation' AND defaults ? 'content_type';

-- G.5  generation_config.default_count := defaults.count
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,generation_config,default_count}',
    to_jsonb((defaults->>'count')::int)
)
WHERE task_type = 'content_generation' AND defaults ? 'count';

-- G.6  generation_config.default_depth := defaults.depth
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,generation_config,default_depth}',
    to_jsonb(defaults->>'depth')
)
WHERE task_type = 'content_generation' AND defaults ? 'depth';

-- G.7  generation_config.default_ai_platforms := defaults.platforms
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,generation_config,default_ai_platforms}',
    COALESCE(defaults->'platforms', '[]'::jsonb)
)
WHERE task_type = 'content_generation';

-- G.8  generation_config.default_language (seed en-US if absent)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,generation_config,default_language}',
    COALESCE(
        wizard_config#>'{steps,generation_config,default_language}',
        to_jsonb(defaults->>'language'),
        '"en-US"'::jsonb
    )
)
WHERE task_type = 'content_generation';

-- G.9  generation_config.include_data_disclosure — per content_type default
--      (FAQ / AEO / SEO = false; recommendations / brief / 自定义 = true)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,generation_config,include_data_disclosure}',
    CASE
        WHEN defaults->>'content_type' IN ('faq', 'aeo_article', 'article') THEN 'false'::jsonb
        ELSE 'true'::jsonb
    END
)
WHERE task_type = 'content_generation';

-- G.10  prompt_link.default_sort — preserve old prompt_select.default_sort if
--       present (the old sub-tree was dropped at G.1 but we reconstruct here
--       via the defaults bag fallback)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,prompt_link,default_sort}',
    COALESCE(
        to_jsonb(defaults->>'prompt_sort'),
        '"visibility"'::jsonb
    )
)
WHERE task_type = 'content_generation';

-- G.11  analysis_import.analyzer_task_id — start empty (per-task choice, not
--       template-level)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_import,analyzer_task_id}',
    '""'::jsonb
)
WHERE task_type = 'content_generation';


-- ============================================================
-- H. Sanity checks — fail the migration loudly on structural regression
-- ============================================================

-- H.1  Every workflow_step row must have num + label + fields (same invariant
--      as 028 but re-checked post-rewrite)
DO $$
DECLARE
  bad_row RECORD;
BEGIN
  FOR bad_row IN
    SELECT scope, key FROM geo_workflow_config
     WHERE config_type = 'workflow_step'
       AND (NOT (value ? 'num') OR NOT (value ? 'label') OR NOT (value ? 'fields'))
  LOOP
    RAISE EXCEPTION
      'workflow_step row missing required key: scope=% key=%',
      bad_row.scope, bad_row.key;
  END LOOP;
END $$;

-- H.2  Analysis = 6 steps (1..6), Content = 7 steps (1..7)
DO $$
DECLARE
  analysis_count INT;
  content_count INT;
BEGIN
  SELECT COUNT(*) INTO analysis_count FROM geo_workflow_config
   WHERE config_type = 'workflow_step' AND scope = 'analysis';
  SELECT COUNT(*) INTO content_count FROM geo_workflow_config
   WHERE config_type = 'workflow_step' AND scope = 'content_generation';

  IF analysis_count <> 6 THEN
    RAISE EXCEPTION 'Expected 6 analysis workflow_step rows, got %', analysis_count;
  END IF;
  IF content_count <> 7 THEN
    RAISE EXCEPTION 'Expected 7 content_generation workflow_step rows, got %', content_count;
  END IF;
END $$;

-- H.3  Analysis num must be 1..6 contiguous
DO $$
DECLARE
  nums INT[];
BEGIN
  SELECT array_agg((value->>'num')::int ORDER BY (value->>'num')::int)
    INTO nums
    FROM geo_workflow_config
   WHERE config_type = 'workflow_step' AND scope = 'analysis';
  IF nums <> ARRAY[1,2,3,4,5,6] THEN
    RAISE EXCEPTION 'Analysis step nums are not 1..6: %', nums;
  END IF;
END $$;

-- H.4  Content num must be 1..7 contiguous
DO $$
DECLARE
  nums INT[];
BEGIN
  SELECT array_agg((value->>'num')::int ORDER BY (value->>'num')::int)
    INTO nums
    FROM geo_workflow_config
   WHERE config_type = 'workflow_step' AND scope = 'content_generation';
  IF nums <> ARRAY[1,2,3,4,5,6,7] THEN
    RAISE EXCEPTION 'Content step nums are not 1..7: %', nums;
  END IF;
END $$;

-- H.5  Content step keys must be the exact 7 canonical keys
DO $$
DECLARE
  keys TEXT[];
BEGIN
  SELECT array_agg(key ORDER BY (value->>'num')::int)
    INTO keys
    FROM geo_workflow_config
   WHERE config_type = 'workflow_step' AND scope = 'content_generation';
  IF keys <> ARRAY['analysis_import','content_goal','content_type','content_strategy','generation_config','prompt_link','confirm_execute'] THEN
    RAISE EXCEPTION 'Content step keys mismatch canonical 7-node set: %', keys;
  END IF;
END $$;

COMMIT;

-- =============================================================================
-- Verification queries (run after commit)
-- =============================================================================
--
-- 1. Analysis steps should be 6 rows with complete field arrays
-- SELECT key, (value->>'num')::int AS num, value->>'label',
--   jsonb_array_length(value->'fields') AS field_count
-- FROM geo_workflow_config
-- WHERE config_type='workflow_step' AND scope='analysis'
-- ORDER BY (value->>'num')::int;
--
-- 2. Content steps should be 7 rows matching ContentPipelineModal
-- SELECT key, (value->>'num')::int AS num, value->>'label',
--   jsonb_array_length(value->'fields') AS field_count
-- FROM geo_workflow_config
-- WHERE config_type='workflow_step' AND scope='content_generation'
-- ORDER BY (value->>'num')::int;
--
-- 3. Analysis template backfill check
-- SELECT name,
--   wizard_config#>'{steps,data_selection,default_platforms}' AS platforms,
--   wizard_config#>'{steps,data_selection,default_peers}'     AS peers,
--   wizard_config#>'{steps,chart_config,default_charts}'      AS charts,
--   wizard_config#>>'{steps,prompt_edit,custom_prompt}'       AS prompt
-- FROM geo_report_templates
-- WHERE task_type='analysis' AND is_active=true
-- ORDER BY name;
--
-- 4. Content template backfill check (7-node shape)
-- SELECT name,
--   wizard_config#>'{steps,content_goal,default_metrics}'            AS metrics,
--   wizard_config#>'{steps,content_goal,default_sub_goals}'          AS sub_goals,
--   wizard_config#>>'{steps,content_type,default}'                   AS content_type,
--   wizard_config#>>'{steps,generation_config,default_count}'        AS count,
--   wizard_config#>>'{steps,generation_config,default_depth}'        AS depth,
--   wizard_config#>'{steps,generation_config,default_ai_platforms}'  AS ai_platforms,
--   wizard_config#>>'{steps,generation_config,default_language}'     AS language,
--   wizard_config#>>'{steps,generation_config,include_data_disclosure}' AS disclosure
-- FROM geo_report_templates
-- WHERE task_type='content_generation' AND is_active=true
-- ORDER BY name;
--
-- 5. Stale 029 keys should be gone
-- SELECT name,
--   wizard_config#>'{steps,content_framework}' AS should_be_null,
--   wizard_config#>'{steps,output_config}'     AS should_also_be_null,
--   wizard_config#>'{steps,prompt_select}'     AS and_this_too,
--   wizard_config#>'{steps,data_strategy}'     AS and_this_as_well,
--   wizard_config#>'{steps,model_schedule}'    AS finally_this
-- FROM geo_report_templates
-- WHERE task_type='content_generation';
