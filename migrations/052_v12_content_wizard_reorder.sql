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
