-- ============================================================
-- Migration 050: 渠道表现分析 (Channel Performance) support
-- ============================================================
-- Two fixes for the 渠道表现分析 (channel performance) analysis
-- template that was added for OEM clients but shipped half-complete:
--
--   1. Add a matching `channel_performance` analysis_goal to
--      geo_workflow_config so the Wizard Step 1 dropdown has a
--      semantically-correct option. Without this, the template's
--      default_goal has no matching row and the LLM downstream
--      doesn't know what "channel performance" means.
--
--   2. Complete the template's wizard_config. Currently only
--      chart_config is filled in; analysis_goal / analysis_framework /
--      data_selection are missing, which means:
--        - Wizard Step 1 has no default_goal
--        - Wizard Step 2 has no default_lenses
--        - Wizard Step 3 has no default_domains/platforms/date_range
--      Fix by backfilling sensible defaults aligned with other
--      built-in templates (e.g. 综合分析).
--
-- Non-OEM clients must NOT see this template — that is enforced
-- frontend-side via wizard_config.visibility_condition.has_shadow_brands,
-- which is already set. The bug was that AgentAnalysis.tsx didn't
-- honour the flag; fixed in a separate frontend patch.
-- ============================================================

BEGIN;

-- ── 1. New analysis goal: channel_performance ───────────────────

INSERT INTO geo_workflow_config (scope, config_type, key, value, sort_order, is_active)
VALUES (
    'analysis',
    'goal',
    'channel_performance',
    jsonb_build_object(
        'label', '渠道表现分析',
        'description', '(OEM/ODM 专用) 分析 shadow brand 与 own product 在 AI 答案中的共现、产品在不同经销渠道的声量对比、以及 citation_role 引用归因'
    ),
    6,
    TRUE
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
    SET value = EXCLUDED.value,
        sort_order = EXCLUDED.sort_order,
        is_active = TRUE;

-- ── 2. Complete 渠道表现分析 wizard_config ──────────────────────
--
-- Strategy: keep chart_config + visibility_condition + required_metrics
-- intact, add the three missing step stanzas with sensible defaults.

UPDATE geo_report_templates
SET wizard_config = jsonb_build_object(
    'steps', jsonb_build_object(
        'analysis_goal', jsonb_build_object(
            'enabled', true,
            'default_goal', 'channel_performance'
        ),
        'analysis_framework', jsonb_build_object(
            'enabled', true,
            -- OEM performance analysis needs current-state reading +
            -- gap diagnosis + action recommendations.
            'default_lenses', jsonb_build_array('descriptive', 'diagnostic', 'prescriptive')
        ),
        'data_selection', jsonb_build_object(
            'enabled', true,
            'default_peers', jsonb_build_array(),
            'default_domains', jsonb_build_array('visibility', 'citation'),
            'default_platforms', jsonb_build_array('chatgpt', 'gemini', 'aimode'),
            'default_date_range', 'last_30d'
        ),
        'chart_config', wizard_config->'steps'->'chart_config'
    ),
    'required_metrics', wizard_config->'required_metrics',
    'visibility_condition', wizard_config->'visibility_condition'
)
WHERE name = '渠道表现分析' AND is_builtin = TRUE;

COMMIT;

-- ============================================================
-- Verify
-- ============================================================
-- SELECT scope, key, value->>'label' AS label, sort_order
--   FROM geo_workflow_config
--   WHERE scope='analysis' AND config_type='goal'
--   ORDER BY sort_order;
-- Expect to see `channel_performance | 渠道表现分析 | 6`
--
-- SELECT jsonb_object_keys(wizard_config->'steps')
--   FROM geo_report_templates WHERE name='渠道表现分析';
-- Expect: analysis_goal, analysis_framework, data_selection, chart_config
