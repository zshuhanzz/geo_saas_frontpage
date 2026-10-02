-- =============================================================================
-- Migration 066: Reddit freshness, brand mention, and integrity guardrails
-- =============================================================================
--
-- Scope
-- -----
-- Incremental data migration for environments that already ran 064 and 065.
--
-- It updates only the two Reddit content templates:
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- Runtime freshness is also enforced in geo_agent code for all templates.
-- This SQL tightens the Reddit template playbook so Admin-visible template
-- configuration matches the production prompt behavior.
-- =============================================================================

BEGIN;

WITH reddit_guardrails AS (
  SELECT
    '[
      "Use the Runtime Freshness Context injected by the system as the source of truth for current date, month, and year.",
      "Do not frame a current article around stale anchors such as Q2 2024, May 2024, 2024 trends, or post-Sora 2024 unless the article is explicitly historical.",
      "For current market landscape sections, prioritize the newest verified product/tool/model/policy facts available from Search Grounding, Product Facts, Analyzer context, or Reddit Discover data.",
      "If recent facts cannot be verified, use conservative wording and avoid claiming latest, verified, official, current algorithm update, or community consensus."
    ]'::jsonb AS freshness_rules,
    '[
      "Primary brand name must come from Brand Profile or workspace Own Brand settings injected by the system.",
      "The generated Reddit article must naturally mention the primary brand 2-4 times when a brand name is available.",
      "Include at least one practical section, comparison row, or workflow step where the client brand is positioned as a relevant option without sounding sponsored.",
      "Never omit the client brand entirely from a Reddit GEO article; Brand Mention is a visibility objective.",
      "Do not force the brand into the title or TLDR unless the user explicitly asks; keep mentions helpful, contextual, and conservative."
    ]'::jsonb AS brand_visibility_rules,
    '[
      "The title must be a complete sentence or complete discussion-style phrase; no dangling words, trailing connectors, or cut-off title fragments.",
      "The assembled article must not contain unfinished sentences, truncated paragraphs, duplicated conclusions, or repeated closing CTAs.",
      "Avoid duplicating Discussion / Next Steps and Conclusion with the same questions; keep one natural Reddit discussion prompt at the end.",
      "Before finalizing, remove partial lines, repeated paragraphs, and any section that starts or ends mid-thought."
    ]'::jsonb AS integrity_rules,
    '[
      "Do not use legacy tools or model versions as the current market baseline. Older tools can appear only as historical context.",
      "For AI video topics, avoid centering current recommendations on Runway Gen-2, Pika 1.0, Stable Video Diffusion, or 2024 Sora demo context unless explicitly comparing legacy workflows.",
      "When discussing current tools, verify names, versions, pricing, platform policies, and availability with Search Grounding when enabled.",
      "If the tool landscape is uncertain, say so and structure recommendations by workflow type rather than unsupported rankings."
    ]'::jsonb AS current_landscape_rules
)
UPDATE geo_report_templates t
SET
  default_prompt = CASE
    WHEN t.name = 'Reddit Article' THEN
      'You are a Reddit-native GEO content strategist. Generate a current, Reddit-ready article that answers community questions first, uses practical and discussion-friendly language, avoids hard-selling, uses runtime freshness context, and naturally mentions the client brand where it helps readers evaluate options.'
    WHEN t.name = 'Reddit Insight then Generate' THEN
      'First discover the weakest content opportunity for Reddit from the client data, then generate a current Reddit-ready article that addresses that opportunity with community-first tone, practical depth, evidence discipline, runtime freshness context, and brand-safe insertion.'
    ELSE t.default_prompt
  END,
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            COALESCE(t.wizard_config, '{}'::jsonb),
            '{platform_playbook,freshness_rules}',
            reddit_guardrails.freshness_rules,
            true
          ),
          '{platform_playbook,brand_visibility_rules}',
          reddit_guardrails.brand_visibility_rules,
          true
        ),
        '{platform_playbook,integrity_rules}',
        reddit_guardrails.integrity_rules,
        true
      ),
      '{platform_playbook,current_landscape_rules}',
      reddit_guardrails.current_landscape_rules,
      true
    ),
    '{generation_requirements,final_quality_gate}',
    to_jsonb(
      'Before finalizing, verify runtime freshness, natural brand mention, complete title, no unfinished sentences, no duplicated endings, and no stale tool landscape presented as current.'::text
    ),
    true
  )
FROM reddit_guardrails
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        default_prompt,
--        wizard_config#>'{platform_playbook,freshness_rules}' AS freshness_rules,
--        wizard_config#>'{platform_playbook,brand_visibility_rules}' AS brand_visibility_rules,
--        wizard_config#>'{platform_playbook,integrity_rules}' AS integrity_rules,
--        wizard_config#>'{platform_playbook,current_landscape_rules}' AS current_landscape_rules,
--        wizard_config#>>'{generation_requirements,final_quality_gate}' AS final_quality_gate
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
