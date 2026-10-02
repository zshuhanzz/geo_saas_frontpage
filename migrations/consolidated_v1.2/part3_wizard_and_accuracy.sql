-- ========================================================================
-- v1.2 Dual-Mode Tracking — Part 3: Wizard B3/B4 + Data Accuracy
-- ========================================================================
-- Concat of migrations 051..054 (this session's additions).
--   051: Mode Gate step (B-3)
--   052: Content wizard reorder + data_scope consolidation (B-4)
--   053: citation_by_citation_role metric (unclassified bucket)
--   054: Content RAFT defaults — every template gets 4 metrics + 9 sub-goals
-- ========================================================================

-- ──── 051_v12_mode_gate_step.sql ────
-- 051_v12_mode_gate_step.sql
-- v1.2 B-3: Mode Gate step for content_generation wizard.
--
-- Adds a new wizard step (mode_gate, num=0) that lets users choose between:
--   manual      — "我来定" (user picks content_type / topic / prompts themselves)
--   ai_discover — "AI 帮我发现" (B-5 preselect endpoint auto-fills defaults)
--
-- num=0 places this step BEFORE the existing step 1 (analysis_import) without
-- renumbering downstream steps. B-4 (migration 052) will handle the full
-- reorder + data_scope consolidation.
--
-- Rollback:
--   DELETE FROM geo_workflow_config WHERE scope='content_generation'
--       AND ((config_type='workflow_step' AND key='mode_gate')
--         OR (config_type='mode_option'   AND key IN ('manual','ai_discover')));
--   UPDATE geo_report_templates
--     SET wizard_config = wizard_config #- '{steps,mode_gate}'
--     WHERE task_type='content_generation';

BEGIN;

-- 1. Add mode_option config rows (enum values for Mode Gate).
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES
  (
    'mode_option',
    'content_generation',
    'manual',
    jsonb_build_object(
      'label', '我来定',
      'description', '我自己挑内容类型、话题和 prompts，完全手动配置',
      'icon', '✍️'
    ),
    0,
    true
  ),
  (
    'mode_option',
    'content_generation',
    'ai_discover',
    jsonb_build_object(
      'label', 'AI 帮我发现',
      'description', 'AI 根据数据推荐最该优化的内容类型、话题和表现最差的 prompts，我只要 review',
      'icon', '✨'
    ),
    1,
    true
  )
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value, sort_order = EXCLUDED.sort_order, is_active = true;

-- 2. Register the Mode Gate workflow_step (num=0 so it lives before current step 1).
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES (
  'workflow_step',
  'content_generation',
  'mode_gate',
  jsonb_build_object(
    'num', 0,
    'label', '生成模式 (Mode Gate)',
    'description', '选择由你手动配置内容生成，还是让 AI 根据 GEO 数据帮你自动挑选最该优化的目标',
    'fields', jsonb_build_array(
      jsonb_build_object(
        'key', 'mode_choice',
        'type', 'mode_gate_picker',
        'label', '生成模式',
        'ref_scope', 'content_generation',
        'ref_config_type', 'mode_option',
        'description', '我来定 = 自己挑每一项；AI 帮我发现 = AI 基于可见度/引用/情感数据预选最弱的目标，你可以调整'
      )
    )
  ),
  0,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value, sort_order = EXCLUDED.sort_order, is_active = true;

-- 3. Backfill mode_gate step into every content_generation template's wizard_config.
-- Default mode is "manual" to preserve existing behaviour.
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
  COALESCE(wizard_config, '{}'::jsonb),
  '{steps,mode_gate}',
  jsonb_build_object(
    'enabled', true,
    'default_mode_choice', 'manual'
  ),
  true
)
WHERE task_type = 'content_generation';

-- 4. Verification — should return 1 row with num=0 and 2 mode options.
--   SELECT value->>'num' AS num, value->>'label' AS label
--   FROM geo_workflow_config
--   WHERE scope='content_generation' AND config_type='workflow_step' AND key='mode_gate';
--
--   SELECT key, value->>'label' FROM geo_workflow_config
--   WHERE scope='content_generation' AND config_type='mode_option' ORDER BY sort_order;
--
--   SELECT name, wizard_config->'steps'->'mode_gate' FROM geo_report_templates
--   WHERE task_type='content_generation';

COMMIT;

-- ──── 052_v12_content_wizard_reorder.sql ────
-- 052_v12_content_wizard_reorder.sql
-- v1.2 B-4: Content Generation wizard reorder + data_scope consolidation.
--
-- User decision: "每一步的实现方式都不需要大的变化，本质就是调顺序"
-- (Spec §4.6 / SESSION_HANDOFF_2026-04-20_v2 §2.4)
--
-- Old order:
--   1. analysis_import      (Analyzer import — was top-of-funnel)
--   2. content_goal         (RAFT sub-goals)
--   3. content_type         (FAQ / AEO / ...)
--   4. content_strategy
--   5. generation_config
--   6. prompt_link          (prompt picker, depended on analysis_import)
--   7. confirm_execute
--
-- New order:
--   0. mode_gate            (B-3, added by migration 051)
--   1. content_type         (user picks content_type first)
--   2. data_scope           (renamed prompt_link + topic_ids + analyzer widget inline)
--   3. content_goal
--   4. content_strategy
--   5. generation_config
--   6. confirm_execute
--  10. analysis_import      (demoted + disabled; kept so DRAFT tasks don't 404)
--
-- Rollback is non-trivial — best path is to restore from backup. Partial
-- rollback SQL at the bottom.

BEGIN;

-- 1) Renumber existing steps to the new positions.
UPDATE geo_workflow_config
   SET value = jsonb_set(value, '{num}', '1'::jsonb)
 WHERE scope='content_generation' AND config_type='workflow_step' AND key='content_type';

UPDATE geo_workflow_config
   SET value = jsonb_set(value, '{num}', '3'::jsonb)
 WHERE scope='content_generation' AND config_type='workflow_step' AND key='content_goal';

UPDATE geo_workflow_config
   SET value = jsonb_set(value, '{num}', '6'::jsonb)
 WHERE scope='content_generation' AND config_type='workflow_step' AND key='confirm_execute';

-- 2) Demote analysis_import to num=10 so it sits at the end when enabled.
--    Actual visibility is controlled per-template via wizard_config.steps.analysis_import.enabled.
UPDATE geo_workflow_config
   SET value = jsonb_set(value, '{num}', '10'::jsonb)
 WHERE scope='content_generation' AND config_type='workflow_step' AND key='analysis_import';

-- 3) Rename prompt_link → data_scope and augment with topic_ids + optional analyzer widget.
--    Note: UNIQUE index (scope, config_type, key) means we UPDATE in place, not INSERT+DELETE.
UPDATE geo_workflow_config
   SET key   = 'data_scope',
       value = jsonb_build_object(
         'num', 2,
         'label', '数据范围 (Data Scope)',
         'description', '选定本次内容要对应的话题、prompts 与（可选）参考的 analyzer 报告。生成的内容会标注这些 ID 以便后续追踪',
         'fields', jsonb_build_array(
           jsonb_build_object(
             'key', 'topic_ids',
             'type', 'topic_ref_picker',
             'label', '目标话题',
             'config', jsonb_build_object(
               'single', false,
               'auto_prefill_count', 3,
               'allow_empty', true
             ),
             'description', '按「可见度 / 引用 / 情感」维度展示表现最差的话题 — 可一键自动勾选最差的 3 个'
           ),
           jsonb_build_object(
             'key', 'prompt_ids',
             'type', 'prompt_ref_picker',
             'label', '目标 Prompts',
             'config', jsonb_build_object(
               'max_count', 20,
               'min_count', 1,
               'allow_empty', false
             ),
             'depends_on', jsonb_build_array('analyzer_task_id','default_sort','topic_ids'),
             'description', '按 visibility / citation 得分排序 — 自动勾选表现最差的 5 个 prompts'
           ),
           jsonb_build_object(
             'key', 'default_sort',
             'type', 'single_ref',
             'label', '排序维度',
             'ref_scope', 'content_generation',
             'ref_config_type', 'sort_option',
             'description', '优先处理 Visibility / Citation / Sentiment 最差的 Topic / Prompt'
           ),
           jsonb_build_object(
             'key', 'analyzer_task_id',
             'type', 'analyzer_import',
             'label', 'Analyzer 报告（可选）',
             'required', false,
             'config', jsonb_build_object(
               'require_status', 'succeeded',
               'compatible_task_types', jsonb_build_array('analyzer','opportunity_discovery')
             ),
             'description', '选择一个已完成的 Analyzer 任务作为上下文。选择后 prompt 列表会锁定到该报告中标注的 prompts'
           )
         )
       )
 WHERE scope='content_generation' AND config_type='workflow_step' AND key='prompt_link';

-- 4) Update per-template wizard_config.steps:
--    - rename steps.prompt_link → steps.data_scope (preserving enabled / defaults)
--    - disable steps.analysis_import (so demoted step stays hidden by default)
UPDATE geo_report_templates
   SET wizard_config = jsonb_set(
     CASE
       WHEN wizard_config -> 'steps' ? 'prompt_link'
         THEN (wizard_config #- '{steps,prompt_link}')
                || jsonb_build_object(
                     'steps',
                     COALESCE(wizard_config->'steps', '{}'::jsonb)
                       - 'prompt_link'
                       || jsonb_build_object(
                            'data_scope',
                            wizard_config->'steps'->'prompt_link'
                          )
                   )
       ELSE wizard_config
     END,
     '{steps,analysis_import,enabled}',
     'false'::jsonb,
     true
   )
 WHERE task_type='content_generation';

-- 5) Verification queries (run after migration):
--   SELECT key, (value->>'num')::int AS num
--     FROM geo_workflow_config
--     WHERE scope='content_generation' AND config_type='workflow_step'
--     ORDER BY (value->>'num')::int;
--
--   SELECT name,
--          wizard_config->'steps' ? 'data_scope'      AS has_data_scope,
--          wizard_config->'steps' ? 'prompt_link'     AS has_prompt_link_stale,
--          wizard_config->'steps'->'analysis_import'->>'enabled' AS analysis_import_enabled
--     FROM geo_report_templates
--     WHERE task_type='content_generation';

COMMIT;

-- Rollback (partial — restore num values; recovering full template JSONB requires a backup):
--   UPDATE geo_workflow_config SET key='prompt_link',
--       value = value - 'fields' || jsonb_build_object(
--         'fields', jsonb_build_array(
--           jsonb_build_object('key','prompt_ids','type','prompt_ref_picker','label','目标 Prompts',
--             'config', jsonb_build_object('max_count',20,'min_count',1,'allow_empty',false),
--             'depends_on', jsonb_build_array('analyzer_task_id','default_sort')),
--           jsonb_build_object('key','default_sort','type','single_ref','label','默认排序',
--             'ref_scope','content_generation','ref_config_type','sort_option')
--         ),
--         'num', 6, 'label','Prompt 关联 (Prompt Link)'
--       )
--     WHERE scope='content_generation' AND config_type='workflow_step' AND key='data_scope';
--   UPDATE geo_workflow_config SET value = jsonb_set(value, '{num}', '3'::jsonb)
--     WHERE scope='content_generation' AND key='content_type';
--   UPDATE geo_workflow_config SET value = jsonb_set(value, '{num}', '2'::jsonb)
--     WHERE scope='content_generation' AND key='content_goal';
--   UPDATE geo_workflow_config SET value = jsonb_set(value, '{num}', '7'::jsonb)
--     WHERE scope='content_generation' AND key='confirm_execute';
--   UPDATE geo_workflow_config SET value = jsonb_set(value, '{num}', '1'::jsonb)
--     WHERE scope='content_generation' AND key='analysis_import';

-- ──── 053_v12_data_accuracy_fixes.sql ────
-- 053_v12_data_accuracy_fixes.sql
-- v1.2 data accuracy pass (v2 late-session, 2026-04-20):
--
--   Bug #3: `citation_by_citation_role` metric silently dropped the NULL
--   `citation_role` rows (via `AND citation_role IS NOT NULL`). For OEM
--   customers (Tmax) this hid 5611 citations as "待分类 / unclassified"
--   — making it look like they only had 6 own-domain citations when in
--   reality there were 5617 total. The unclassified bucket is a signal,
--   not noise: it tells the customer "these domains aren't in your
--   Settings yet — consider adding them".
--
--   Fix: COALESCE NULL → 'unclassified' in both SELECT and GROUP BY, and
--   drop the `IS NOT NULL` filter.
--
-- Other bugs (code-only, no SQL):
--   Bug #1: /api/insights/peer-sov-via-list returned orphan mentions
--     whose client_prompt_id pointed at deleted prompts — inconsistent
--     with /visibility. Fixed in geo_saas/api/routers/insights/peer_sov.py
--     by adding an EXISTS join on geo_client_prompts.is_active.
--   Bug #2: NL2SQL LLM emitted 'positive'/'negative'/'owned' enum
--     literals (lower / wrong). Fixed in geo_agent/api/pipelines/
--     analysis_pipeline.py via (a) stronger METRIC_SQL_HEADER enum
--     guardrails and (b) normalize_enum_literals() post-processor.
--
-- Rollback:
--   UPDATE geo_analysis_metrics SET calculation_hint =
--     'SELECT citation_role, COUNT(*) AS citations FROM geo_citations
--      WHERE client_id = $1 AND executed_at BETWEEN $2 AND $3
--      AND citation_role IS NOT NULL GROUP BY citation_role
--      ORDER BY citations DESC'
--   WHERE metric_name='citation_by_citation_role';

BEGIN;

UPDATE geo_analysis_metrics
   SET calculation_hint = 'SELECT COALESCE(citation_role, ''unclassified'') AS citation_role, COUNT(*) AS citations FROM geo_citations WHERE client_id = $1 AND executed_at BETWEEN $2 AND $3 GROUP BY COALESCE(citation_role, ''unclassified'') ORDER BY citations DESC',
       updated_at = now()
 WHERE metric_name = 'citation_by_citation_role';

-- Verification: should return the updated calculation_hint with COALESCE.
--   SELECT metric_name, calculation_hint FROM geo_analysis_metrics
--     WHERE metric_name='citation_by_citation_role';

COMMIT;

-- ──── 054_v12_content_raft_defaults_all.sql ────
-- 054_v12_content_raft_defaults_all.sql
-- v1.2 content_generation default RAFT coverage (v2 late-session, 2026-04-20):
--
-- Decision (user, reviewing 'FAQ 内容生成' wizard in v2 session):
--   "RAFT 的四象限 (Readability / Answerability / Trustworthy / Freshness)
--   是 GEO 内容生成必须兼顾的，任何模板都应该默认全选 — 哪怕 AI 挑模板
--   也应把 4 顶层 + 9 sub_goals 全勾上。它们呈现在 UI 上是给用户传递
--   '这四象限是 GEO 内容的完整检查清单' 的心智；AI 不应该自作主张少选。"
--
-- Before this migration:
--   - FAQ template: default_metrics=[], default_sub_goals=[4 sub-goals under R/A/T]
--   - Other templates: varying subsets, most with default_metrics=[]
-- After this migration:
--   - EVERY content_generation template has
--       default_metrics      = ['readability','answerability','trustworthy','freshness']
--       default_sub_goals    = ALL 9 sub-goal keys from geo_workflow_config
--   - required_metrics / required_subgoals (the "hard must" for each template)
--     are left untouched — they stay template-specific.
--
-- Rollback is lossy since we overwrite per-template defaults. Restore from
-- pg_dump taken before applying this migration.

BEGIN;

UPDATE geo_report_templates
   SET wizard_config = jsonb_set(
     jsonb_set(
       wizard_config,
       '{steps,content_goal,default_metrics}',
       (
         SELECT to_jsonb(array_agg(key ORDER BY sort_order))
         FROM geo_workflow_config
         WHERE scope='content_generation'
           AND config_type='content_metric'
           AND (parent_key IS NULL OR parent_key = '')
           AND is_active
       ),
       true
     ),
     '{steps,content_goal,default_sub_goals}',
     (
       SELECT to_jsonb(array_agg(key ORDER BY parent_key, sort_order))
       FROM geo_workflow_config
       WHERE scope='content_generation'
         AND config_type='content_sub_goal'
         AND parent_key IS NOT NULL AND parent_key <> ''
         AND is_active
     ),
     true
   )
 WHERE task_type = 'content_generation';

-- Verification:
--   SELECT name,
--          wizard_config->'steps'->'content_goal'->>'default_metrics' AS metrics,
--          jsonb_array_length(wizard_config->'steps'->'content_goal'->'default_sub_goals') AS subgoal_count
--     FROM geo_report_templates
--     WHERE task_type='content_generation';
--   Expect: metrics = 4-item array, subgoal_count = 9 for every row.

COMMIT;

