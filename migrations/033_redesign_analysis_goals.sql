-- =============================================================================
-- Migration 033: Redesign analysis goals — 5 goals → 4 goals
-- Run:   psql $DATABASE_URL -f migrations/033_redesign_analysis_goals.sql
-- =============================================================================
--
-- Changes
-- -------
-- 1. Deactivate `benchmark` and `opportunity` goals from workflow_config
-- 2. Add new `competitive` goal (replaces benchmark with clearer name)
-- 3. Rename `sentiment_deep` → `sentiment` (simpler, no need for deep/shallow)
-- 4. Keep `health` and `trend` as-is (updated descriptions)
-- 5. Update template wizard_config references:
--    - 竞品对标分析 template: default_goal benchmark → competitive
--    - 情感分析 template: default_goal sentiment_deep → sentiment
-- 6. Update template defaults.goal references for consistency
-- 7. Update analysis_framework default_lenses for new goal keys
--
-- Final 4 goals:
--   health      — 品牌健康诊断 (visibility + citation + sentiment)
--   competitive — 竞品对标分析 (visibility + citation, requires peer_picker)
--   sentiment   — 品牌情感洞察 (sentiment)
--   trend       — 趋势追踪     (visibility + citation, longer time range)
--
-- Safe to re-run: idempotent.
-- =============================================================================

BEGIN;

-- ============================================================
-- A. Deactivate old goals
-- ============================================================

UPDATE geo_workflow_config
SET is_active = false, value = jsonb_set(value, '{deprecated}', '"replaced by competitive in migration 033"')
WHERE config_type = 'goal' AND scope = 'analysis' AND key = 'benchmark';

UPDATE geo_workflow_config
SET is_active = false, value = jsonb_set(value, '{deprecated}', '"removed — opportunity is a pipeline, not an analysis goal"')
WHERE config_type = 'goal' AND scope = 'analysis' AND key = 'opportunity';


-- ============================================================
-- B. Update existing goals
-- ============================================================

-- B.1 — health: update description to be more precise
UPDATE geo_workflow_config
SET value = '{"icon":"Shield","color":"text-emerald-400 border-emerald-500/30 bg-emerald-500/5","label":"品牌健康诊断","description":"可见度 / 引用 / 情感 三维度综合健康评估","recommended_domains":["visibility","citation","sentiment"]}'::jsonb,
    sort_order = 1
WHERE config_type = 'goal' AND scope = 'analysis' AND key = 'health';

-- B.2 — trend: update description
UPDATE geo_workflow_config
SET value = '{"icon":"TrendingUp","color":"text-purple-400 border-purple-500/30 bg-purple-500/5","label":"趋势追踪","description":"时间序列变化、关键拐点识别、前瞻趋势判断","recommended_domains":["visibility","citation"]}'::jsonb,
    sort_order = 4
WHERE config_type = 'goal' AND scope = 'analysis' AND key = 'trend';

-- B.3 — sentiment_deep → sentiment: rename key + update value
-- First deactivate the old key
UPDATE geo_workflow_config
SET is_active = false
WHERE config_type = 'goal' AND scope = 'analysis' AND key = 'sentiment_deep';

-- Insert new sentiment key (delete first for idempotency)
DELETE FROM geo_workflow_config
WHERE config_type = 'goal' AND scope = 'analysis' AND key = 'sentiment';

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES (
    'goal', 'analysis', 'sentiment', '',
    '{"icon":"MessageSquare","color":"text-pink-400 border-pink-500/30 bg-pink-500/5","label":"品牌情感洞察","description":"AI 搜索中的品牌情感分布、负面主题拆解、平台差异分析","recommended_domains":["sentiment"]}'::jsonb,
    3, true
);


-- ============================================================
-- C. Add new competitive goal
-- ============================================================

DELETE FROM geo_workflow_config
WHERE config_type = 'goal' AND scope = 'analysis' AND key = 'competitive';

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES (
    'goal', 'analysis', 'competitive', '',
    '{"icon":"Target","color":"text-blue-400 border-blue-500/30 bg-blue-500/5","label":"竞品对标分析","description":"与竞品在 AI 搜索中的 SOV、引用、可见度差异对比","recommended_domains":["visibility","citation"]}'::jsonb,
    2, true
);


-- ============================================================
-- D. Update template wizard_config references
-- ============================================================

-- D.1 — 竞品对标分析: benchmark → competitive
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_goal,default_goal}',
    '"competitive"'::jsonb
),
    defaults = jsonb_set(COALESCE(defaults, '{}'::jsonb), '{goal}', '"competitive"'::jsonb),
    updated_at = NOW()
WHERE task_type = 'analysis' AND name = '竞品对标分析';

-- D.2 — 情感分析: sentiment_deep → sentiment
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_goal,default_goal}',
    '"sentiment"'::jsonb
),
    defaults = jsonb_set(COALESCE(defaults, '{}'::jsonb), '{goal}', '"sentiment"'::jsonb),
    updated_at = NOW()
WHERE task_type = 'analysis' AND name = '情感分析';

-- D.3 — Update analysis_framework default_lenses for renamed goals
-- competitive uses same lenses as old benchmark (descriptive + diagnostic)
-- (no change needed — the 竞品对标分析 template's lenses were already set)

-- sentiment uses same lenses as old sentiment_deep
-- (no change needed — the 情感分析 template's lenses were already set)


-- ============================================================
-- E. Update workflow_step description for analysis_goal
-- ============================================================
-- The step's field description used to list all 5 goals — update to list 4
UPDATE geo_workflow_config
SET value = jsonb_set(
    value,
    '{fields}',
    (
        SELECT jsonb_agg(
            CASE
                WHEN f->>'key' = 'default_goal'
                THEN jsonb_set(f, '{description}', '"健康诊断 / 竞品对标 / 情感洞察 / 趋势追踪"')
                ELSE f
            END
        )
        FROM jsonb_array_elements(value->'fields') AS f
    )
)
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'analysis_goal'
  AND value->'fields' IS NOT NULL;


COMMIT;

-- =============================================================================
-- Verification queries
-- =============================================================================
--
-- 1. Check active analysis goals (should be 4)
-- SELECT key, value->>'label' AS label, sort_order, is_active
-- FROM geo_workflow_config
-- WHERE config_type = 'goal' AND scope = 'analysis'
-- ORDER BY sort_order;
--
-- 2. Check template default_goal references
-- SELECT name, wizard_config#>>'{steps,analysis_goal,default_goal}' AS default_goal
-- FROM geo_report_templates
-- WHERE task_type = 'analysis' AND is_active = true
-- ORDER BY sort_order;
