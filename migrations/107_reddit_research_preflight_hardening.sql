-- Migration 107: Reddit Research preflight hardening
--
-- Purpose:
--   Tighten the Reddit Research preflight flow so Reddit-native templates
--   require confirmed Wizard artifacts during final generation, require
--   manual handling for unavailable subreddit rules, and keep all behavior
--   template-config driven.
--
-- Safe to re-run:
--   Yes. JSONB merges preserve existing operator edits where practical.

BEGIN;

WITH reddit_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      defaults->>'platform_profile' = 'reddit'
      OR wizard_config->>'platform_profile' = 'reddit'
      OR defaults->>'publish_platform' = 'reddit'
      OR wizard_config#>>'{steps,generation_config,default_publish_platform}' = 'reddit'
      OR name IN (
        'Reddit Article',
        'Reddit Insight then Generate',
        'Reddit AI Citable Post Generator'
      )
    )
)
UPDATE geo_report_templates AS t
SET wizard_config =
  jsonb_set(
    jsonb_set(
      jsonb_set(
        COALESCE(t.wizard_config, '{}'::jsonb),
        '{reddit_research,reddit_discovery,rules_policy}',
        to_jsonb('verified_or_user_reviewed'::text),
        true
      ),
      '{reddit_research,reddit_discovery,unavailable_rules_behavior}',
      to_jsonb('require_manual_rules_or_confirmed_skip'::text),
      true
    ),
    '{reddit_research,artifact_preparation,allow_runtime_generation}',
    'false'::jsonb,
    true
  )
WHERE t.id IN (SELECT id FROM reddit_templates);

COMMIT;
