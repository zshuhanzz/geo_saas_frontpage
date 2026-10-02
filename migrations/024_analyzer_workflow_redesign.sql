-- Migration 024: Analyzer Workflow Redesign
-- Date: 2026-04-06
-- Description:
--   1. Deactivate the "优化机会发现" template from geo_report_templates
--      (Mode A now has its own dedicated entry, no longer uses the generic template system)
--   2. No new tables needed — all framework tables (geo_optimization_metrics,
--      geo_optimization_subgoals, geo_strategies) were created in migration 023

-- ============================================================
-- 1. Deactivate "优化机会发现" template
--    (Keep the row for historical task references, just hide from template list)
-- ============================================================
UPDATE geo_report_templates
SET is_active = false,
    updated_at = NOW()
WHERE name = '优化机会发现'
  AND is_builtin = true
  AND task_type = 'analysis';

-- ============================================================
-- 2. Remove "opportunity" workflow config entry
--    (The opportunity flow is now handled by OpportunityAnalysisModal directly,
--     not through the TemplateConfigModal goal selection)
-- ============================================================
DELETE FROM geo_workflow_config
WHERE config_type = 'goal'
  AND scope = 'analysis'
  AND key = 'opportunity';
