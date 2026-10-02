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
