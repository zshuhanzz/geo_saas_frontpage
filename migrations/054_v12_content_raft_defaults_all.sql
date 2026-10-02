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
