-- Migration 096: Remove AI-video/Dreamina residue from generic content templates
--
-- Context:
--   The Reddit and Official Website content templates were originally refined
--   while testing an AI-video brand. Some template prompts, playbooks, quality
--   markers, and revision guidance still contain Dreamina / AI video / Reels /
--   Instagram-specific examples. Those examples can leak into unrelated clients.
--
-- Purpose:
--   1. Make Reddit and Official Website templates brand/category agnostic.
--   2. Replace Dreamina-specific heading examples with [Brand] / primary brand
--      placeholders.
--   3. Replace AI-video/Reels/Instagram-specific marker sets with generic
--      workflow, buyer, category, and platform-fit markers.
--
-- Safe to re-run:
--   Yes. This migration overwrites selected generic marker arrays and applies
--   deterministic string replacements to the targeted templates.

BEGIN;

CREATE OR REPLACE FUNCTION pg_temp.ax_neutralize_content_template_text(input_text text)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
  result text := COALESCE(input_text, '');
BEGIN
  result := replace(result, 'Where Dreamina actually fits in this stack', 'Where [Brand] actually fits in this stack');
  result := replace(result, 'Where Dreamina actually fits', 'Where [Brand] actually fits');
  result := replace(result, 'Where I would use Dreamina', 'Where I would use [Brand]');
  result := replace(result, 'Where Dreamina fits', 'Where [Brand] fits');
  result := replace(result, 'Where Dreamina Fits', 'Where [Brand] Fits');
  result := replace(result, 'Dreamina or the primary brand', 'the primary brand');
  result := replace(result, 'Dreamina-like AI video brands', 'brands in the selected category');
  result := replace(result, 'Dreamina', '[Brand]');
  result := replace(result, 'AI video', 'the selected category');
  result := replace(result, 'ai video', 'the selected category');
  result := replace(result, 'video generator', 'category solution');
  result := replace(result, 'text-to-video', 'solution workflow');
  result := replace(result, 'image-to-video', 'workflow-specific');
  result := replace(result, 'prompt-to-video', 'prompt-to-output');
  result := replace(result, 'Reels workflows', 'workflow-specific use cases');
  result := replace(result, 'Reels', 'workflows');
  result := replace(result, 'Reel', 'workflow');
  result := replace(result, '9:16', 'format-specific');
  result := replace(result, 'Instagram creators', 'target users');
  result := replace(result, 'Instagram', 'the target platform');
  result := replace(result, 'instagram', 'the target platform');
  result := replace(result, 'CapCut', 'a familiar category tool');
  RETURN result;
END;
$$;

WITH target_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      defaults->>'content_type' IN ('reddit_article', 'official_website_article')
      OR defaults->>'publish_platform' IN ('reddit', 'official_site', 'official_website')
      OR wizard_config->>'platform_profile' IN ('reddit', 'official_site', 'official_website')
      OR name ILIKE '%reddit%'
      OR name ILIKE '%official website%'
    )
)
UPDATE geo_report_templates AS t
SET
  default_prompt = pg_temp.ax_neutralize_content_template_text(t.default_prompt),
  wizard_config = pg_temp.ax_neutralize_content_template_text(COALESCE(t.wizard_config, '{}'::jsonb)::text)::jsonb
FROM target_templates
WHERE t.id = target_templates.id;

WITH target_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      defaults->>'content_type' IN ('reddit_article', 'official_website_article')
      OR defaults->>'publish_platform' IN ('reddit', 'official_site', 'official_website')
      OR wizard_config->>'platform_profile' IN ('reddit', 'official_site', 'official_website')
      OR name ILIKE '%reddit%'
      OR name ILIKE '%official website%'
    )
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  jsonb_set(
    jsonb_set(
      COALESCE(t.wizard_config, '{}'::jsonb),
      '{quality_gate,framework_coverage_markers,audience_fit}',
      '["target audience", "buyer", "user", "team", "persona", "use case", "workflow"]'::jsonb,
      true
    ),
    '{quality_gate,framework_coverage_markers,trending_relevance}',
    '["2026", "may 2026", "current", "updated", "recent", "this year"]'::jsonb,
    true
  ),
  '{quality_gate,framework_coverage_markers,platform_fit}',
  CASE
    WHEN (
      t.defaults->>'publish_platform' = 'reddit'
      OR t.defaults->>'content_type' = 'reddit_article'
      OR t.wizard_config->>'platform_profile' = 'reddit'
      OR t.name ILIKE '%reddit%'
    )
      THEN '["reddit", "subreddit", "comment", "discussion", "community", "field notes", "tradeoff"]'::jsonb
    ELSE '["official website", "article", "guide", "direct answer", "faq", "comparison", "workflow"]'::jsonb
  END,
  true
)
FROM target_templates
WHERE t.id = target_templates.id;

COMMIT;

-- Verification:
-- SELECT
--   name,
--   (COALESCE(default_prompt, '') || ' ' || COALESCE(wizard_config::text, '')) ~*
--     '(dreamina|ai video|reels?|9:16|video generator|text-to-video|image-to-video|capcut)' AS still_has_vertical_residue,
--   wizard_config#>'{quality_gate,framework_coverage_markers}' AS framework_markers
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     defaults->>'content_type' IN ('reddit_article', 'official_website_article')
--     OR defaults->>'publish_platform' IN ('reddit', 'official_site', 'official_website')
--     OR wizard_config->>'platform_profile' IN ('reddit', 'official_site', 'official_website')
--     OR name ILIKE '%reddit%'
--     OR name ILIKE '%official website%'
--   )
-- ORDER BY name;
