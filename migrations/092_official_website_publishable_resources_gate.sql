-- Migration 092: Keep official-website resource/link guidance publishable
--
-- Context:
--   Official-site templates previously required "Internal Linking Suggestions".
--   Backend post-processing renamed that heading to "Related {Brand} Resources",
--   but the generated body could still contain editor-facing SEO/AEO operations
--   such as "Anchor Text", "Destination", and "strategically placing links".
--
-- Purpose:
--   1. Stop requiring editor-facing internal-link sections in official articles.
--   2. Allow only reader-facing Helpful Resources / Further Reading style links.
--   3. Add deterministic Quality Gate blockers for editor artifacts leaking into
--      publishable official-site body copy.
--   4. Configure official-site resource link policy: citation URLs are learning
--      examples, not automatic outbound links; Helpful Resources should use
--      owned/customer domains unless the source is a neutral authority.
--
-- Safe to re-run:
--   Yes. Existing old internal-link required rules and this migration's rules
--   are de-duped by rule id before the new rules are appended.

BEGIN;

WITH target_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%official website%'
      OR defaults->>'publish_platform' IN ('official_site', 'official_website')
      OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
    )
),
filtered_rules AS (
  SELECT
    id,
    COALESCE(
      (
        SELECT jsonb_agg(rule)
        FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,rules}', '[]'::jsonb)) AS rule
        WHERE COALESCE(rule->>'id', '') NOT IN (
          'internal_linking_suggestions',
          'official_internal_linking_required',
          'official_internal_linking_suggestions',
          'official_internal_linking_plan',
          'official_editor_resource_artifacts',
          'official_brand_stuffed_resource_heading'
        )
      ),
      '[]'::jsonb
    ) AS rules
  FROM target_templates
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate,rules}',
  filtered_rules.rules || '[
    {
      "id": "official_editor_resource_artifacts",
      "type": "forbidden_patterns",
      "severity": "blocker",
      "patterns": [
        "Anchor Text\\s*:",
        "Target Page\\s*:",
        "Destination\\s*:",
        "we recommend integrating the following internal links",
        "consider adding the following internal links",
        "Strategically placing these links",
        "SEO and AEO visibility of this guide",
        "\\[Insert Official[^\\]]*\\]",
        "Insert [A-Za-z ]+ URL"
      ]
    },
    {
      "id": "official_brand_stuffed_resource_heading",
      "type": "forbidden_patterns",
      "severity": "warning",
      "patterns": [
        "^\\s{0,3}#{2,6}\\s+Related\\s+[A-Za-z0-9][A-Za-z0-9._-]*\\s+Resources\\s*$"
      ]
    }
  ]'::jsonb,
  true
)
FROM filtered_rules
WHERE t.id = filtered_rules.id;

UPDATE geo_report_templates AS t
SET default_prompt = replace(
  replace(
    replace(
      COALESCE(default_prompt, ''),
      'Internal Linking Suggestions',
      'reader-facing Helpful Resources with real URLs only when useful'
    ),
    'Related Resources',
    'Helpful Resources'
  ),
  'related resources',
  'helpful resources'
)
WHERE task_type = 'content_generation'
  AND (
    name ILIKE '%official website%'
    OR defaults->>'publish_platform' IN ('official_site', 'official_website')
    OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
  );

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{resource_link_policy}',
  COALESCE(t.wizard_config->'resource_link_policy', '{}'::jsonb) || '{
    "helpful_resources_owned_domains_only": true,
    "citation_sources_are_learning_examples": true,
    "competitor_or_tool_sites_as_resources": "blocker",
    "neutral_authority_external_links": "warning",
    "allowed_domains": [],
    "neutral_authority_domains": [
      "about.instagram.com",
      "business.instagram.com",
      "creators.instagram.com",
      "developers.facebook.com",
      "help.instagram.com",
      "instagram.com",
      "meta.com",
      "transparency.meta.com"
    ]
  }'::jsonb,
  true
)
WHERE task_type = 'content_generation'
  AND (
    name ILIKE '%official website%'
    OR defaults->>'publish_platform' IN ('official_site', 'official_website')
    OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
  );

UPDATE geo_report_templates AS t
SET wizard_config = replace(
  replace(
    replace(
      replace(
        COALESCE(wizard_config, '{}'::jsonb)::text,
        'Internal Linking Suggestions',
        'Helpful Resources'
      ),
      'Related Resources',
      'Helpful Resources'
    ),
    'If internal linking appears as an editor instruction, convert it into reader-facing Helpful Resources with real URLs.',
    'If internal linking appears as an editor instruction, remove the editor instruction; keep only natural reader-facing links with real URLs, or remove the section entirely.'
  ),
  'missing Helpful Resources',
  'missing Helpful Resources only when useful'
)::jsonb
WHERE task_type = 'content_generation'
  AND (
    name ILIKE '%official website%'
    OR defaults->>'publish_platform' IN ('official_site', 'official_website')
    OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
  );

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate,revision_guidance,general}',
  COALESCE(t.wizard_config#>'{quality_gate,revision_guidance,general}', '[]'::jsonb)
  || '[
    "Citation source URLs are learning examples for structure and extractability; do not automatically list them as Helpful Resources in the official article.",
    "Helpful Resources should use customer owned domains or configured brand ecosystem domains. External neutral authority links may be used only for factual support; competitor/tool/vendor links should be removed from the resource list."
  ]'::jsonb,
  true
)
WHERE task_type = 'content_generation'
  AND (
    name ILIKE '%official website%'
    OR defaults->>'publish_platform' IN ('official_site', 'official_website')
    OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
  );

COMMIT;

-- Verification:
-- SELECT
--   name,
--   default_prompt LIKE '%Internal Linking Suggestions%' AS prompt_still_has_internal_linking,
--   wizard_config::text LIKE '%Internal Linking Suggestions%' AS config_still_has_internal_linking,
--   wizard_config#>'{resource_link_policy}' AS resource_link_policy,
--   wizard_config#>'{quality_gate,rules}' AS rules
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     name ILIKE '%official website%'
--     OR defaults->>'publish_platform' IN ('official_site', 'official_website')
--     OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
--   )
-- ORDER BY name;
