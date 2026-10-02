-- Migration 086: Place AI-citable content templates under Discover then Generate
--
-- Context:
--   The SaaS content template picker groups templates by
--   wizard_config.template_group / defaults.template_group.
--   It currently recognizes:
--     - discover_then_generate / discover  -> Discover then Generate
--     - everything else                    -> By Template
--
-- Migration 083 introduced two citation-aware templates with
-- template_group = citation_then_generate. Because the UI does not use that
-- as a separate section, the templates fall back to By Template.
--
-- Product decision:
--   These two templates include Reddit Discover / Official Website Discover
--   plus Citation Analysis, so they should live under Discover then Generate.
--   Citation Analysis remains a configurable node/capability, not the
--   top-level section taxonomy.

BEGIN;

UPDATE geo_report_templates
SET
  defaults = jsonb_set(
    COALESCE(defaults, '{}'::jsonb),
    '{template_group}',
    '"discover_then_generate"'::jsonb,
    true
  ),
  wizard_config = jsonb_set(
    COALESCE(wizard_config, '{}'::jsonb),
    '{template_group}',
    '"discover_then_generate"'::jsonb,
    true
  ),
  updated_at = NOW()
WHERE task_type = 'content_generation'
  AND name IN (
    'Reddit AI Citable Post Generator',
    'Official Website AI Citable Article'
  );

COMMIT;

-- Verification:
-- SELECT
--   name,
--   defaults->>'template_group' AS defaults_template_group,
--   wizard_config->>'template_group' AS wizard_template_group,
--   (wizard_config->'steps'->'reddit_discover'->>'enabled') AS reddit_discover_enabled,
--   (wizard_config->'steps'->'official_website_discover'->>'enabled') AS official_discover_enabled,
--   (wizard_config->'steps'->'citation_analysis'->>'enabled') AS citation_analysis_enabled
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN (
--     'Reddit AI Citable Post Generator',
--     'Official Website AI Citable Article'
--   )
-- ORDER BY name;
