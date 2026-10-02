-- Migration 097: Repair content template neutralization and block LLM process artifacts
--
-- Context:
--   Migration 096 intentionally removed AI-video/Dreamina residue from generic
--   Reddit and Official Website templates, but some replacements were too broad:
--   domain config such as instagram.com became "the target platform.com", and
--   several Reddit playbook examples still described AI-video/Reels workflows.
--
-- Purpose:
--   1. Repair the over-broad 096 replacements.
--   2. Neutralize remaining AI-video/Reels workflow examples in Reddit/Official
--      content templates.
--   3. Add a template-configured Quality Gate blocker for leaked LLM process
--      text such as "Let's double check the rules".
--
-- Safe to re-run:
--   Yes. The Quality Gate rule is de-duplicated by id before being appended.

BEGIN;

CREATE OR REPLACE FUNCTION pg_temp.ax_repair_content_template_text(input_text text)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
  result text := COALESCE(input_text, '');
BEGIN
  -- Repair 096 domain corruption.
  result := replace(result, 'the target platform.com', 'instagram.com');
  result := replace(result, 'about.instagram.com', 'about.instagram.com');
  result := replace(result, 'business.instagram.com', 'business.instagram.com');
  result := replace(result, 'creators.instagram.com', 'creators.instagram.com');
  result := replace(result, 'help.instagram.com', 'help.instagram.com');

  -- Smooth awkward generic wording introduced by 096.
  result := replace(result, 'an the selected category generator for social content', 'a selected-category solution for the target use case');
  result := replace(result, 'the selected category generator for social content', 'a selected-category solution for the target use case');
  result := replace(result, 'dominates the the target platform', 'dominates the target platform');

  -- Remove remaining AI-video/Reels-specific playbook examples without tying the
  -- templates to a new vertical.
  result := replace(
    result,
    'AI slop vs production assistant, a familiar category tool friction vs automation, phone footage vs AI, disclosure, product-demo accuracy vs stylized B-roll',
    'manual workflow vs automation, buying criteria vs hands-on proof, implementation cost, disclosure, accuracy vs polish'
  );
  result := replace(
    result,
    'daily workflows, scene replacement, format-specific B-roll, caption/audio sync, visual consistency, or prompt re-roll cost',
    'daily workflows, setup friction, handoff quality, consistency, review loops, or iteration cost'
  );
  result := replace(
    result,
    'editing-first, prompt-to-output, and product-video workflows',
    'manual-first, automation-assisted, and buyer-research workflows'
  );
  result := replace(
    result,
    'prompt-to-polish, timeline-heavy editing, avatar-led explainers, local/open-source node workflows, and native social editing',
    'manual research, workflow automation, evaluation checklists, lightweight tools, and enterprise workflows'
  );
  result := replace(
    result,
    'target platform compression can be rough on AI footage; low-effort AI content tends to lose retention; most creator workflows I am seeing favor workflow-specific',
    'platform context can change how users evaluate a recommendation; low-effort content tends to lose trust; most durable workflows favor specific use cases'
  );
  result := replace(
    result,
    'the target platform compression can be rough on AI footage; low-effort AI content tends to lose retention; most creator workflows I am seeing favor workflow-specific',
    'platform context can change how users evaluate a recommendation; low-effort content tends to lose trust; most durable workflows favor specific use cases'
  );
  result := replace(result, 'product-video workflows', 'buyer-research workflows');
  result := replace(result, 'stylized B-roll', 'polished output');
  result := replace(result, 'caption/audio sync', 'workflow handoff');
  result := replace(result, 'phone footage vs AI', 'manual proof vs automation');
  result := replace(result, 'AI footage', 'automated output');
  result := replace(result, 'AI content', 'low-effort content');
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
  default_prompt = pg_temp.ax_repair_content_template_text(t.default_prompt),
  wizard_config = pg_temp.ax_repair_content_template_text(COALESCE(t.wizard_config, '{}'::jsonb)::text)::jsonb
FROM target_templates
WHERE t.id = target_templates.id;

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
),
existing_rules AS (
  SELECT
    t.id,
    COALESCE(
      jsonb_agg(rule ORDER BY ord) FILTER (
        WHERE rule IS NOT NULL AND rule->>'id' IS DISTINCT FROM 'llm_process_artifacts'
      ),
      '[]'::jsonb
    ) AS rules
  FROM geo_report_templates AS t
  JOIN target_templates ON target_templates.id = t.id
  LEFT JOIN LATERAL jsonb_array_elements(COALESCE(t.wizard_config#>'{quality_gate,rules}', '[]'::jsonb))
    WITH ORDINALITY AS r(rule, ord) ON true
  GROUP BY t.id
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate,rules}',
  existing_rules.rules || jsonb_build_array(jsonb_build_object(
    'id', 'llm_process_artifacts',
    'type', 'forbidden_patterns',
    'severity', 'blocker',
    'patterns', jsonb_build_array(
      '^\\s*RSThe search results confirm',
      'Let''s double check the rules',
      'The prompt says:',
      'The primary brand to mention is',
      'The failure is `',
      'Re-evaluating the text',
      'Let''s review the',
      'Let''s refine',
      'Looks solid\\.\\s*#'
    ),
    'message', 'Remove leaked model reasoning, self-check notes, or revision-process text; final output must contain publishable Markdown only.'
  )),
  true
)
FROM existing_rules
WHERE t.id = existing_rules.id;

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
),
existing_guidance AS (
  SELECT
    t.id,
    COALESCE(
      jsonb_agg(line ORDER BY ord) FILTER (
        WHERE line IS NOT NULL
          AND line_txt <> 'Return final publishable Markdown only. Delete any reasoning transcript, self-check, search-result notes, prompt analysis, or Quality Gate debugging text.'
      ),
      '[]'::jsonb
    ) AS general_lines
  FROM geo_report_templates AS t
  JOIN target_templates ON target_templates.id = t.id
  LEFT JOIN LATERAL jsonb_array_elements(
    CASE
      WHEN jsonb_typeof(t.wizard_config#>'{quality_gate,revision_guidance,general}') = 'array'
        THEN t.wizard_config#>'{quality_gate,revision_guidance,general}'
      ELSE '[]'::jsonb
    END
  ) WITH ORDINALITY AS g(line, ord) ON true
  CROSS JOIN LATERAL (SELECT trim(both '"' from line::text) AS line_txt) AS normalized
  GROUP BY t.id
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate,revision_guidance,general}',
  existing_guidance.general_lines || jsonb_build_array(
    'Return final publishable Markdown only. Delete any reasoning transcript, self-check, search-result notes, prompt analysis, or Quality Gate debugging text.'
  ),
  true
)
FROM existing_guidance
WHERE t.id = existing_guidance.id;

COMMIT;

-- Verification:
-- SELECT
--   name,
--   wizard_config#>>'{steps,citation_analysis,citation_exclude_domains}' AS citation_exclude_domains,
--   (COALESCE(default_prompt, '') || ' ' || COALESCE(wizard_config::text, '')) ~*
--     '(dreamina|ai video|reels?|9:16|video generator|text-to-video|image-to-video|capcut|the target platform\\.com)' AS still_has_problematic_residue,
--   EXISTS (
--     SELECT 1
--     FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,rules}', '[]'::jsonb)) AS rule
--     WHERE rule->>'id' = 'llm_process_artifacts'
--   ) AS has_process_artifact_gate
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
