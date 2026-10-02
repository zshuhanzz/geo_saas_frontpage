-- =============================================================================
-- Migration 035: Unify wizard_config step enabled key → `enabled`
-- Run:   psql $DATABASE_URL -f migrations/035_unify_enabled_key.sql
-- =============================================================================
--
-- Context
-- -------
-- The admin UI wrote `__enabled` (double-underscore prefix) while some
-- templates already had `enabled` (no prefix). This caused conflicts where
-- a step had BOTH keys with different values (e.g. SEO 优化文章's
-- analysis_import: enabled=false + __enabled=true).
--
-- Decision: unify on `enabled` (no prefix). This migration:
--   1. For every step that has `__enabled` but NOT `enabled`:
--      copy __enabled → enabled, then remove __enabled
--   2. For every step that has BOTH `__enabled` AND `enabled`:
--      keep `enabled` (the original), remove `__enabled`
--   3. Steps that only have `enabled` are already correct — no-op
--
-- Safe to re-run: idempotent.
-- =============================================================================

BEGIN;

-- Helper: For each template, iterate over wizard_config.steps keys and
-- normalize __enabled → enabled.
--
-- We use a DO block with dynamic SQL because jsonb_each doesn't easily
-- let us update nested keys across an unknown set of step names.

DO $$
DECLARE
    tmpl RECORD;
    step_key TEXT;
    step_val JSONB;
    new_steps JSONB;
    has_enabled BOOLEAN;
    has_dunder BOOLEAN;
BEGIN
    FOR tmpl IN
        SELECT id, wizard_config
        FROM geo_report_templates
        WHERE wizard_config IS NOT NULL
          AND wizard_config->'steps' IS NOT NULL
    LOOP
        new_steps := tmpl.wizard_config->'steps';

        FOR step_key, step_val IN
            SELECT * FROM jsonb_each(tmpl.wizard_config->'steps')
        LOOP
            has_enabled := step_val ? 'enabled';
            has_dunder  := step_val ? '__enabled';

            IF has_dunder AND NOT has_enabled THEN
                -- Case 1: only __enabled → copy to enabled, remove __enabled
                step_val := jsonb_set(step_val, '{enabled}', step_val->'__enabled');
                step_val := step_val - '__enabled';
                new_steps := jsonb_set(new_steps, ARRAY[step_key], step_val);

            ELSIF has_dunder AND has_enabled THEN
                -- Case 2: both exist → keep enabled, remove __enabled
                step_val := step_val - '__enabled';
                new_steps := jsonb_set(new_steps, ARRAY[step_key], step_val);
            END IF;
            -- Case 3: only enabled or neither → no change
        END LOOP;

        -- Write back if changed
        IF new_steps IS DISTINCT FROM tmpl.wizard_config->'steps' THEN
            UPDATE geo_report_templates
            SET wizard_config = jsonb_set(wizard_config, '{steps}', new_steps),
                updated_at = NOW()
            WHERE id = tmpl.id;
        END IF;
    END LOOP;
END;
$$;

COMMIT;

-- =============================================================================
-- Verification
-- =============================================================================
--
-- Check no __enabled keys remain:
--
-- SELECT t.name, s.key AS step_key, s.value
-- FROM geo_report_templates t,
--      jsonb_each(t.wizard_config->'steps') AS s(key, value)
-- WHERE s.value ? '__enabled'
-- ORDER BY t.name, s.key;
--
-- Expected: 0 rows
