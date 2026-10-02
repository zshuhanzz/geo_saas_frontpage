-- =============================================================================
-- Migration 034: Replace Lucide icon names with emoji in geo_workflow_config
-- Run:   psql $DATABASE_URL -f migrations/034_icon_lucide_to_emoji.sql
-- =============================================================================
--
-- Context
-- -------
-- Several workflow_config rows store icon values as Lucide component names
-- (e.g. "Shield", "Target", "TrendingUp") instead of emoji. The admin UI
-- and SaaS wizard render value.icon as plain text, so these show up as
-- the literal string "Shield" instead of an icon.
--
-- This migration replaces all known Lucide icon names with their emoji
-- equivalents so icons render correctly without any code-side mapping.
--
-- Safe to re-run: idempotent (each UPDATE only matches exact string values).
-- =============================================================================

BEGIN;

-- Blanket update: for every row whose value->>'icon' matches a Lucide name,
-- replace it with the corresponding emoji.

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"🛡️"')
WHERE value->>'icon' = 'Shield';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"🎯"')
WHERE value->>'icon' = 'Target';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"📈"')
WHERE value->>'icon' = 'TrendingUp';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"💬"')
WHERE value->>'icon' = 'MessageSquare';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"💡"')
WHERE value->>'icon' = 'Lightbulb';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"📖"')
WHERE value->>'icon' = 'BookOpen';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"❓"')
WHERE value->>'icon' = 'MessageCircleQuestion';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"✅"')
WHERE value->>'icon' = 'ShieldCheck';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"⏰"')
WHERE value->>'icon' = 'Clock';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"📊"')
WHERE value->>'icon' = 'BarChart3';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{icon}', '"🔍"')
WHERE value->>'icon' = 'Search';

COMMIT;

-- =============================================================================
-- Verification
-- =============================================================================
--
-- Check no Lucide names remain:
-- SELECT key, value->>'icon' AS icon, value->>'label' AS label
-- FROM geo_workflow_config
-- WHERE value->>'icon' ~ '^[A-Z]'
-- ORDER BY config_type, scope, sort_order;
