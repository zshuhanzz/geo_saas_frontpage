-- 109_reddit_research_global_grounding_and_oauth.sql
-- Purpose:
--   Move Reddit Research grounding model/timeout into Global Config and keep
--   Reddit templates focused on workflow behavior. OAuth credentials are not
--   inserted here; they should be supplied after Reddit App creation and data
--   access approval.

BEGIN;

INSERT INTO geo_global_settings (key, value, description)
VALUES
  (
    'reddit_research_grounding_model_id',
    'gemini-3.5-flash',
    'Gemini model used by Reddit Research Subreddit Targeting with Google Search grounding.'
  ),
  (
    'reddit_research_grounding_timeout_seconds',
    '180',
    'Timeout in seconds for Reddit Research Google Search grounding calls.'
  )
ON CONFLICT (key) DO UPDATE
SET
  value = EXCLUDED.value,
  description = EXCLUDED.description,
  updated_at = NOW();

-- Remove infrastructure-level grounding model/timeout from Reddit templates.
-- The runtime still accepts legacy template values when the new global setting
-- is absent, but the desired data shape is global-config driven.
UPDATE geo_report_templates
SET wizard_config =
  jsonb_set(
    COALESCE(wizard_config, '{}'::jsonb),
    '{reddit_research,provider_config,web_grounded}',
    COALESCE(wizard_config#>'{reddit_research,provider_config,web_grounded}', '{}'::jsonb)
      - 'grounding_model_id'
      - 'request_timeout_seconds',
    true
  ),
  updated_at = NOW()
WHERE task_type = 'content_generation'
  AND (
    lower(name) LIKE '%reddit%'
    OR defaults->>'platform_profile' = 'reddit'
    OR wizard_config->>'platform_profile' = 'reddit'
    OR defaults->>'content_type' = 'reddit_article'
    OR defaults->>'publish_platform' = 'reddit'
    OR wizard_config#>>'{steps,generation_config,default_publish_platform}' = 'reddit'
    OR lower(COALESCE(wizard_config#>>'{defaults,publish_platform}', '')) = 'reddit'
    OR lower(COALESCE(wizard_config#>>'{defaults,content_type}', '')) LIKE '%reddit%'
    OR lower(COALESCE(wizard_config#>>'{steps,content_type,default}', '')) LIKE '%reddit%'
  )
  AND wizard_config ? 'reddit_research';

COMMIT;

-- Verification:
-- SELECT key, value FROM geo_global_settings
-- WHERE key IN ('reddit_research_grounding_model_id', 'reddit_research_grounding_timeout_seconds')
-- ORDER BY key;
--
-- SELECT name,
--        wizard_config#>>'{reddit_research,provider_config,web_grounded,grounding_model_id}' AS template_model,
--        wizard_config#>>'{reddit_research,provider_config,web_grounded,request_timeout_seconds}' AS template_timeout
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     lower(name) LIKE '%reddit%'
--     OR defaults->>'content_type' = 'reddit_article'
--     OR defaults->>'publish_platform' = 'reddit'
--     OR wizard_config#>>'{steps,generation_config,default_publish_platform}' = 'reddit'
--   );
