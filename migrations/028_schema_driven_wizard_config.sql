-- =============================================================================
-- Migration 028: Schema-Driven Wizard Steps + New Shared Config Types
-- Run:   psql $DATABASE_URL -f migrations/028_schema_driven_wizard_config.sql
-- =============================================================================
-- WHY
-- ---
-- Before this migration, `geo_workflow_config.workflow_step` held PHASE-1 short
-- keys (goal/data/charts/prompt/confirm for analysis, goal/type/config/... for
-- content). But both the SaaS UI and migration 026's template wizard_config
-- already use PHASE-2 LONG keys (analysis_goal, data_selection, chart_config,
-- prompt_edit, confirm_execute / content_goal, content_type, ...). The short
-- keys are unreferenced zombies — they only cause "orphan step" warnings in
-- the admin WizardConfigEditor and offer no schema guidance.
--
-- This migration does four things:
--
--   1. Purges the obsolete short-key workflow_step rows and reseeds all 5
--      analysis steps + 7 content_generation steps with their PHASE-2 LONG
--      keys matching what the SaaS wizard actually reads.
--
--   2. Extends each workflow_step row's `value` JSONB with a `fields[]` array
--      that DECLARES every sensed field for that step (text / textarea /
--      number / single_ref / multi_ref / list). The admin WizardConfigEditor
--      consumes this schema to render real forms instead of JSON textareas.
--
--   3. Introduces two brand-new shared config_types used by those field refs:
--        - chart_type  (auto / line / bar / pie / table)
--        - date_range  (last_7d / last_30d / last_90d / last_180d / last_365d)
--      These were previously hardcoded enums in SaaS TSX (see
--      TemplateConfigModal.tsx:945 for chart_type); migrating them to the
--      dictionary lets admins add new options without a code deploy.
--
--   4. Leaves every other row (domain, platform, goal, depth, content_type,
--      sort_option, methodology_snippet) untouched. Their scopes and shapes
--      are already correct — no existing item needed a scope reassignment.
--      The earlier "AI Platform mis-scoped as analysis-only" display bug was
--      a pure frontend bug in WorkflowConfigManager.jsx (fixed separately).
--
-- SAFETY
-- ------
-- This migration is SAFE TO RE-RUN. Each seed section deletes its own rows
-- first so the end state is fully deterministic. No existing template data
-- is touched (templates reference workflow steps by KEY, and those keys
-- already match migration 026's long-key contract — see the verification
-- block at the bottom of this file).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Value-schema reference (for reviewers)
-- -----------------------------------------------------------------------------
-- workflow_step.value shape:
--   {
--     "num": <int>,              -- 1-based step order within its scope
--     "label": <string>,         -- Chinese display name; this is what admins see
--     "description": <string>,   -- helper text under the label
--     "fields": [                -- declarative schema for sensed defaults
--       {
--         "key": <string>,           -- key inside wizard_config.steps.<step>.*
--         "label": <string>,         -- Chinese field label
--         "type": "text"             -- scalar string
--               | "textarea"         -- long string (multi-line)
--               | "number"           -- numeric
--               | "single_ref"       -- dropdown from another config_type
--               | "multi_ref"        -- multi-select from another config_type
--               | "list"             -- array of objects w/ item_fields[] schema
--         "description": <string>,   -- tooltip / inline help
--         -- single_ref / multi_ref only:
--         "ref_config_type": <string>,   -- target config_type (e.g. "domain")
--         "ref_scope": <string>,         -- "shared" | "analysis" | "content_generation"
--         -- list only:
--         "item_fields": [<field>, ...]  -- recursive schema for each row
--         -- textarea only:
--         "rows": <int>              -- default row count
--       },
--       ...
--     ]
--   }


-- ============================================================================
-- 1. Purge all existing workflow_step rows (both scopes)
-- ============================================================================
-- We rebuild from scratch below. Re-running this migration is idempotent
-- because of this clean-slate DELETE.
DELETE FROM geo_workflow_config
 WHERE config_type = 'workflow_step';


-- ============================================================================
-- 2. New shared config_type: chart_type
-- ============================================================================
-- Referenced by: workflow_step(analysis, 'chart_config').value.fields[]
--                 → default_charts[].chart_type
-- Matches the hardcoded enum in TemplateConfigModal.tsx:945 ("auto"|"line"|"bar"|"pie").
-- "table" is added for future NL-Query-to-table support.
DELETE FROM geo_workflow_config
 WHERE config_type = 'chart_type' AND scope = 'shared';

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('chart_type', 'shared', 'auto',
 '{"label": "自动选择", "icon": "✨", "description": "由 LLM 根据数据特征自动选择最合适的图表类型"}', 1),
('chart_type', 'shared', 'line',
 '{"label": "折线图", "icon": "📈", "description": "用于时序 / 趋势数据"}', 2),
('chart_type', 'shared', 'bar',
 '{"label": "柱状图", "icon": "📊", "description": "用于分类对比"}', 3),
('chart_type', 'shared', 'pie',
 '{"label": "饼图", "icon": "🥧", "description": "用于占比分布"}', 4),
('chart_type', 'shared', 'table',
 '{"label": "表格", "icon": "📋", "description": "用于多列详细数据"}', 5);


-- ============================================================================
-- 3. New shared config_type: date_range
-- ============================================================================
-- Referenced by: workflow_step(analysis, 'data_selection').value.fields[]
--                 → default_date_range
-- These keys match the existing SaaS convention (see migration 026 templates
-- where default_date_range = 'last_30d' is seeded).
DELETE FROM geo_workflow_config
 WHERE config_type = 'date_range' AND scope = 'shared';

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('date_range', 'shared', 'last_7d',
 '{"label": "最近 7 天", "description": "短期波动检测"}', 1),
('date_range', 'shared', 'last_30d',
 '{"label": "最近 30 天", "description": "标准分析窗口"}', 2),
('date_range', 'shared', 'last_90d',
 '{"label": "最近 90 天", "description": "季度趋势"}', 3),
('date_range', 'shared', 'last_180d',
 '{"label": "最近半年", "description": "中期趋势"}', 4),
('date_range', 'shared', 'last_365d',
 '{"label": "最近一年", "description": "长期趋势"}', 5);


-- ============================================================================
-- 4. Workflow Steps — Analysis scope (5 steps, long keys)
-- ============================================================================
-- These keys match exactly what TemplateConfigModal.tsx:32-50 declares in its
-- WizardConfig interface and what migration 026 writes into template rows.

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES

-- Step 1: 分析目标
('workflow_step', 'analysis', 'analysis_goal',
 jsonb_build_object(
   'num', 1,
   'label', '分析目标',
   'description', '选择分析视角 + 注入到 LLM 提示词的方法论片段',
   'fields', jsonb_build_array(
     jsonb_build_object(
       'key', 'default_methodology_snippets',
       'label', '默认方法论片段',
       'type', 'multi_ref',
       'ref_config_type', 'methodology_snippet',
       'ref_scope', 'analysis',
       'description', 'Pipeline 必须注入到 LLM 提示词的方法论片段（RAFT / 竞品分析 / 趋势洞察）'
     )
   )
 ), 1),

-- Step 2: 数据选择
('workflow_step', 'analysis', 'data_selection',
 jsonb_build_object(
   'num', 2,
   'label', '数据选择',
   'description', '选择要分析的数据领域 + 时间范围',
   'fields', jsonb_build_array(
     jsonb_build_object(
       'key', 'default_domains',
       'label', '默认数据领域',
       'type', 'multi_ref',
       'ref_config_type', 'domain',
       'ref_scope', 'shared',
       'description', '可见度 / 引用 / 情绪 — 模板默认勾选的领域'
     ),
     jsonb_build_object(
       'key', 'default_date_range',
       'label', '默认时间范围',
       'type', 'single_ref',
       'ref_config_type', 'date_range',
       'ref_scope', 'shared',
       'description', '默认回看窗口'
     )
   )
 ), 2),

-- Step 3: 配置图表
('workflow_step', 'analysis', 'chart_config',
 jsonb_build_object(
   'num', 3,
   'label', '配置图表',
   'description', '预配置的图表列表（NL Query → 图表类型）',
   'fields', jsonb_build_array(
     jsonb_build_object(
       'key', 'default_charts',
       'label', '默认图表',
       'type', 'list',
       'description', '按顺序渲染；每条一个自然语言查询 + 可选图表类型',
       'item_fields', jsonb_build_array(
         jsonb_build_object(
           'key', 'nl_query',
           'label', 'NL Query',
           'type', 'textarea',
           'rows', 2,
           'description', '描述这个图表要展示什么'
         ),
         jsonb_build_object(
           'key', 'chart_type',
           'label', '图表类型',
           'type', 'single_ref',
           'ref_config_type', 'chart_type',
           'ref_scope', 'shared',
           'description', '留空 = auto'
         )
       )
     )
   )
 ), 3),

-- Step 4: Prompt 编辑
('workflow_step', 'analysis', 'prompt_edit',
 jsonb_build_object(
   'num', 4,
   'label', 'Prompt 编辑',
   'description', '终端用户微调 LLM 提示词。当前无模板级默认字段；提示词由 geo_report_templates.default_prompt 直接提供',
   'fields', '[]'::jsonb
 ), 4),

-- Step 5: 确认执行
('workflow_step', 'analysis', 'confirm_execute',
 jsonb_build_object(
   'num', 5,
   'label', '确认执行',
   'description', '复核向导配置后触发执行 — 无默认字段',
   'fields', '[]'::jsonb
 ), 5);


-- ============================================================================
-- 5. Workflow Steps — Content Generation scope (7 steps, long keys)
-- ============================================================================
-- These keys match exactly what migration 026 writes into content templates'
-- wizard_config.steps (see migration 026 lines 328-335).

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES

-- Step 1: 内容目标
('workflow_step', 'content_generation', 'content_goal',
 jsonb_build_object(
   'num', 1,
   'label', '内容目标',
   'description', '选择内容优化目标 + 注入 pipeline 的方法论片段',
   'fields', jsonb_build_array(
     jsonb_build_object(
       'key', 'default_methodology_snippets',
       'label', '默认方法论片段',
       'type', 'multi_ref',
       'ref_config_type', 'methodology_snippet',
       'ref_scope', 'content_generation',
       'description', '内容生成 pipeline 注入的方法论片段（RAFT 四维度 / 内容策略）'
     )
   )
 ), 1),

-- Step 2: 内容类型
('workflow_step', 'content_generation', 'content_type',
 jsonb_build_object(
   'num', 2,
   'label', '内容类型',
   'description', '选择要生成的内容形态',
   'fields', jsonb_build_array(
     jsonb_build_object(
       'key', 'default',
       'label', '默认内容类型',
       'type', 'single_ref',
       'ref_config_type', 'content_type',
       'ref_scope', 'content_generation',
       'description', 'FAQ / AEO 文章 / SEO 文章 / 建议 / Brief'
     )
   )
 ), 2),

-- Step 3: 目标配置
('workflow_step', 'content_generation', 'goal_config',
 jsonb_build_object(
   'num', 3,
   'label', '目标配置',
   'description', '生成数量 + 深度',
   'fields', jsonb_build_array(
     jsonb_build_object(
       'key', 'default_count',
       'label', '默认数量',
       'type', 'number',
       'description', '单次生成的内容条数（例如 FAQ 默认 5 条，文章默认 1 篇）'
     ),
     jsonb_build_object(
       'key', 'default_depth',
       'label', '默认深度',
       'type', 'single_ref',
       'ref_config_type', 'depth',
       'ref_scope', 'content_generation',
       'description', '快速生成 / 标准生成 / 深度优化'
     )
   )
 ), 3),

-- Step 4: Prompt 选择
('workflow_step', 'content_generation', 'prompt_select',
 jsonb_build_object(
   'num', 4,
   'label', 'Prompt 选择',
   'description', '候选 Prompt 列表的排序维度',
   'fields', jsonb_build_array(
     jsonb_build_object(
       'key', 'default_sort',
       'label', '默认排序',
       'type', 'single_ref',
       'ref_config_type', 'sort_option',
       'ref_scope', 'content_generation',
       'description', '优先处理 Visibility / Citation / Sentiment 最差的 Prompt'
     )
   )
 ), 4),

-- Step 5: 数据 & 策略
('workflow_step', 'content_generation', 'data_strategy',
 jsonb_build_object(
   'num', 5,
   'label', '数据 & 策略',
   'description', '为内容生成注入上下文的数据领域',
   'fields', jsonb_build_array(
     jsonb_build_object(
       'key', 'default_domains',
       'label', '默认数据领域',
       'type', 'multi_ref',
       'ref_config_type', 'domain',
       'ref_scope', 'shared',
       'description', '将这些领域的数据快照注入内容生成上下文'
     )
   )
 ), 5),

-- Step 6: 模型 & 定时
('workflow_step', 'content_generation', 'model_schedule',
 jsonb_build_object(
   'num', 6,
   'label', '模型 & 定时',
   'description', '模型选择 + 定时调度（预留，暂无默认字段）',
   'fields', '[]'::jsonb
 ), 6),

-- Step 7: 确认执行
('workflow_step', 'content_generation', 'confirm_execute',
 jsonb_build_object(
   'num', 7,
   'label', '确认执行',
   'description', '复核配置后触发内容生成 — 无默认字段',
   'fields', '[]'::jsonb
 ), 7);


-- ============================================================================
-- 6. Sanity checks — run as part of the migration so mistakes fail loudly
-- ============================================================================

-- 6.1 Every workflow_step row must have num + label + fields in its value
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

-- 6.2 Analysis must have exactly 5 steps and content_generation exactly 7
DO $$
DECLARE
  analysis_count INT;
  content_count INT;
BEGIN
  SELECT COUNT(*) INTO analysis_count FROM geo_workflow_config
   WHERE config_type = 'workflow_step' AND scope = 'analysis';
  SELECT COUNT(*) INTO content_count FROM geo_workflow_config
   WHERE config_type = 'workflow_step' AND scope = 'content_generation';

  IF analysis_count <> 5 THEN
    RAISE EXCEPTION 'Expected 5 analysis workflow_step rows, got %', analysis_count;
  END IF;
  IF content_count <> 7 THEN
    RAISE EXCEPTION 'Expected 7 content_generation workflow_step rows, got %', content_count;
  END IF;
END $$;

-- 6.3 Verify template wizard_config step keys match the new long keys.
-- Any template row whose wizard_config.steps has a key we don't recognize is
-- a data inconsistency. This should PASS immediately after migration 026.
DO $$
DECLARE
  orphan_rec RECORD;
  valid_keys TEXT[];
BEGIN
  valid_keys := ARRAY[
    -- analysis
    'analysis_goal', 'data_selection', 'chart_config', 'prompt_edit', 'confirm_execute',
    -- content_generation
    'content_goal', 'content_type', 'goal_config', 'prompt_select',
    'data_strategy', 'model_schedule'
    -- 'confirm_execute' already listed above (shared between scopes)
  ];

  FOR orphan_rec IN
    SELECT t.id, t.name, key AS step_key
      FROM geo_report_templates t,
           jsonb_object_keys(COALESCE(t.wizard_config->'steps', '{}'::jsonb)) AS key
     WHERE key NOT IN (SELECT unnest(valid_keys))
  LOOP
    RAISE WARNING
      'Template "%" (%) has unknown wizard_config step key: %',
      orphan_rec.name, orphan_rec.id, orphan_rec.step_key;
  END LOOP;
END $$;


COMMIT;

-- =============================================================================
-- Post-migration reminders for the admin app
-- =============================================================================
-- Frontend updates pair with this migration (both must ship together):
--
--   A. WizardConfigEditor.jsx — replace the JSON textarea fallback for per-step
--      defaults with a schema-driven form renderer that reads value.fields[]
--      from the workflow_step rows inserted above. Supported field types:
--      text, textarea, number, single_ref, multi_ref, list (+ item_fields[]).
--
--   B. WorkflowConfigManager.jsx — (1) remove the multi-scope badges from the
--      group header that made one config_type appear to belong to multiple
--      scopes, (2) render workflow_step rows using value.label + #num ordering
--      badges, (3) expose a JSON textarea for editing value.fields[] itself
--      (schema-of-schema; the last JSON left in the tool).
--
--   C. CONFIG_TYPE_META fixes in WorkflowConfigManager.jsx:
--      - goal.scopes: ['content_generation'] → ['analysis', 'content_generation']
--      - add entries for 'chart_type' and 'date_range' (both scopes: ['shared'])
--
-- After the above code changes land + this migration runs, the admin can
-- fully configure wizard_config via form controls alone — no hand-editing
-- JSON blobs. The only residual JSON is the value.fields[] editor itself,
-- which is inherently a schema-of-schema and reasonable to leave as JSON
-- until we grow a nested form builder.
-- =============================================================================
