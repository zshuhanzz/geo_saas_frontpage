-- ============================================================
-- Migration 055: Chat wizard required-field gating
-- ============================================================
--
-- Background
-- ----------
-- The 「跳过剩余」 button on the chat step group lets users walk past
-- required fields. Root cause: the workflow_step rows in
-- geo_workflow_config did not flag `default_domains` as required, so the
-- UI couldn't gate the skip button.
--
-- Fix: stamp `"required": true` on the data_selection.default_domains
-- field. Once required, the chat 「跳过剩余」 button will hide and 「下一步」
-- will be disabled until the user picks at least one data domain.
--
-- Why this is enough (and we did NOT add a separate analysis_metrics step):
-- Metrics in geo_analysis_metrics are bound to `domain` (1:N). Once the
-- user picks domains in data_selection, the downstream Prompt Edit step
-- (custom_prompt field's `variable_catalog_ref`) and the analysis pipeline
-- itself derive metrics from domains automatically via
-- /api/agent/tasks/metrics/discover?domains=... — there is no need for a
-- separate metrics-selection step. The earlier draft of this migration
-- added one; we walked it back.
--
-- This migration is idempotent — re-running it is safe.

BEGIN;

-- ============================================================
-- Mark `default_domains` as required on the data_selection step
-- ============================================================
-- The chat 「跳过剩余」 button checks every widget's `required` flag and
-- only renders when EVERY widget in the step is optional. Marking
-- default_domains required forces the user to actually pick domains —
-- which transitively gives the pipeline the metric set it needs.

UPDATE geo_workflow_config
SET value = jsonb_set(
    value,
    '{fields}',
    (
        SELECT jsonb_agg(
            CASE
                WHEN f->>'key' = 'default_domains' THEN f || '{"required": true}'::jsonb
                ELSE f
            END
        )
        FROM jsonb_array_elements(value->'fields') f
    )
)
WHERE config_type = 'workflow_step'
  AND scope = 'analysis'
  AND key = 'data_selection';

COMMIT;


-- ============================================================
-- Verify
-- ============================================================
-- After running this migration, check:
--
--   SELECT jsonb_pretty(value->'fields')
--     FROM geo_workflow_config
--    WHERE config_type='workflow_step'
--      AND scope='analysis'
--      AND key='data_selection';
--
-- Expect: the `default_domains` field entry includes "required": true.
