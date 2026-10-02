-- Migration 111: Preserve verified official body links during revision
--
-- Context:
--   Official Website content generation now restricts every Markdown link to
--   the Official Website Discovery verified URL pool. A production review
--   showed the Revise pass could satisfy that rule by downgrading valid,
--   verified Markdown links into plain text. That avoids fake links, but loses
--   the intended publishable internal-resource value.
--
-- Purpose:
--   1. Configure Official Website templates to preserve verified body links
--      during Revise.
--   2. Keep the deterministic safety rule: unverified links may be replaced
--      with an exact verified URL when semantically accurate, otherwise only
--      the unverified link is unwrapped to plain text.
--   3. Add a template-configured blocker rule for verified links removed by
--      post-revision review.
--
-- Safe to re-run:
--   Yes. This migration overwrites targeted resource_link_policy fields and
--   de-duplicates replaced revision guidance lines before appending the new
--   versions.

BEGIN;

WITH official_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%official website%'
      OR defaults->>'content_type' = 'official_website_article'
      OR defaults->>'publish_platform' IN ('official_site', 'official_website')
      OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
    )
),
official_guidance AS (
  SELECT
    id,
    COALESCE(
      (
        SELECT jsonb_agg(value)
        FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,revision_guidance,general}', '[]'::jsonb)) AS guidance(value)
        WHERE value NOT IN (
          '"All Markdown links in official-site articles must use exact URLs verified by Official Website Discovery; replace unverified links with verified URLs or plain text."'::jsonb,
          '"Helpful Resources must use exact URLs verified by Official Website Discovery; if no verified URL replacement exists, delete the resources section."'::jsonb,
          '"If there is no verified URL replacement, delete the Helpful Resources section instead of inventing a new link."'::jsonb,
          '"Do not remove verified Markdown links during Revise; only unwrap links that are outside the verified Official Website Discovery URL pool."'::jsonb
        )
      ),
      '[]'::jsonb
    ) AS retained_guidance
  FROM official_templates
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  jsonb_set(
    COALESCE(t.wizard_config, '{}'::jsonb),
    '{resource_link_policy}',
    COALESCE(t.wizard_config->'resource_link_policy', '{}'::jsonb) || jsonb_build_object(
      'enabled', true,
      'apply_to_content_types', jsonb_build_array('official_website_article'),
      'apply_to_publish_platforms', jsonb_build_array('official_site', 'official_website'),
      'apply_to_platform_profiles', jsonb_build_array('official_site', 'official_website'),
      'verified_url_source', 'official_website_discovery',
      'verified_url_match', 'exact',
      'link_scope', 'all_markdown_links',
      'sanitize_generated_content', true,
      'sanitize_inline_markdown_links', true,
      'preserve_verified_markdown_links', true,
      'preservation_instruction', 'Keep every existing Markdown link whose URL is in the verified Official Website Discovery URL pool; do not remove verified links and do not downgrade them to plain text. Only unverified links may be replaced with exact verified URLs or unwrapped to plain text.',
      'revision_instruction', 'For unverified Markdown links, replace with an exact verified URL only when the destination meaning remains accurate; otherwise unwrap only that unverified link and keep the anchor text as plain text. Preserve all already-verified Markdown links.',
      'generation_rules', jsonb_build_array(
        'Every Markdown link in the article body must use an exact URL from the verified URL pool below.',
        'Do not use owned-domain root URLs as fallback links unless the exact root URL appears in the verified URL pool.',
        'Do not invent same-domain paths, redirect guesses, or short vanity links.',
        'Citation Analysis URLs are learning examples for structure and content gaps; do not turn them into article links unless the exact URL is also verified by Official Website Discovery.',
        'If a useful sentence has no verified URL, keep the sentence as plain text rather than linking it.',
        'If a useful sentence already has a verified URL, keep it as a Markdown link instead of downgrading it to plain text.',
        'Helpful Resources / Further Reading / Related Resources / Learn More are optional and must use only verified exact URLs.'
      ),
      'verified_link_preservation_rule', jsonb_build_object(
        'id', 'official_verified_links_dropped',
        'type', 'official_resource_link_policy',
        'severity', 'blocker',
        'message', 'Official-site revision removed Markdown links that were already in the verified Official Website Discovery URL pool.'
      )
    ),
    true
  ),
  '{quality_gate,revision_guidance,general}',
  official_guidance.retained_guidance || '[
    "All Markdown links in official-site articles must use exact URLs verified by Official Website Discovery.",
    "Do not remove verified Markdown links during Revise; only unwrap links that are outside the verified Official Website Discovery URL pool.",
    "If an unverified Markdown link has no semantically accurate verified replacement, unwrap only that unverified link and keep the anchor text as plain text."
  ]'::jsonb,
  true
)
FROM official_guidance
WHERE t.id = official_guidance.id;

COMMIT;
