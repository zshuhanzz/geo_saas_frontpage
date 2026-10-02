-- Migration 091: Template-specific Quality Gate Revise guidance
--
-- Context:
--   Quality Gate rules, thresholds, blockers, and max revise attempts are
--   already loaded from geo_report_templates.wizard_config. Before this
--   migration, the Revise prompt also injected template platform/playbook
--   instructions, but its round-specific guidance was mostly code-level
--   fallback text.
--
-- Purpose:
--   Add data-driven revision_guidance so Reddit and official-site templates
--   can steer Revise differently while sharing the same execution engine.
--
-- Safe to re-run:
--   Yes. This migration merges JSONB keys into existing built-in templates.

BEGIN;

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate}',
  COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || '{
    "revision_guidance": {
      "general": [
        "Keep the Reddit post useful, debatable, conservative, and community-native; do not turn the revision into an official marketing article.",
        "Preserve the first-person / field-notes tone when it exists, and keep brand mentions sparse and practical.",
        "Use Citation Analysis as evidence for structure and gaps, but do not mention internal terms like Citation Analysis or GEO visibility in the Reddit-facing post."
      ],
      "round_1": [
        "Repair structural blockers first: duplicate headings, multiple FAQ sections, missing natural brand-fit section, missing workflow/table/checklist structure, or weak citation-gap response.",
        "If Brand Fit Summary is required internally, convert the public heading to a natural Reddit heading such as Where Dreamina actually fits in this stack or Where I would use Dreamina.",
        "If the post is too promotional, rewrite brand references as a practical workflow fit with limitations and trade-offs."
      ],
      "round_2": [
        "Only clean residual publishability issues: unfinished sentences, repeated endings, duplicate FAQ, duplicate Conclusion, and excess brand density.",
        "Do not add new benchmark claims, fake testing claims, unsupported version claims, or platform policy certainty.",
        "Keep the final Reddit title as a proper Markdown H1 and make it sound like a real community post, not an SEO headline."
      ]
    }
  }'::jsonb,
  true
)
WHERE t.task_type = 'content_generation'
  AND (
    t.name ILIKE '%reddit%'
    OR t.defaults->>'publish_platform' = 'reddit'
    OR t.defaults->>'content_type' = 'reddit_article'
    OR t.wizard_config->>'platform_profile' = 'reddit'
  );

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate}',
  COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || '{
    "revision_guidance": {
      "general": [
        "Keep the official article credible, answer-first, commercially useful, and suitable for publication on the customer website.",
        "Preserve extractable modules that support GEO visibility: Direct Answer, Brand Fit Summary, Value/Dream/Mini-benefits, Feature-to-Benefit Mapping, Related Resources, and FAQ.",
        "Use Citation Analysis as a source of truth for citable structure and missing brand coverage, but do not expose internal workflow terms to readers."
      ],
      "round_1": [
        "Repair missing required modules, weak direct answer, weak Brand Fit Summary, weak feature-to-benefit mapping, missing Related Resources, or weak citation-gap response.",
        "Make competitor/category comparisons conservative and evidence-aware; avoid unsupported superlatives or invented benchmark numbers.",
        "If internal linking appears as an editor instruction, convert it into reader-facing Related Resources with real URLs."
      ],
      "round_2": [
        "Clean residual publishability issues: unfinished sentences, repeated FAQ, repeated Conclusion, duplicate Direct Answer, editor artifacts, placeholder URLs, and excess brand density.",
        "Reduce brand repetition by using category terms, pronouns, and workflow-stage descriptions while keeping the brand extractable.",
        "Remove high-risk marketing terms such as ultimate, definitive, guaranteed, viral-ready, and algorithm-ready unless directly supported by provided evidence."
      ]
    }
  }'::jsonb,
  true
)
WHERE t.task_type = 'content_generation'
  AND (
    t.name ILIKE '%official website%'
    OR t.defaults->>'publish_platform' IN ('official_site', 'official_website')
    OR t.wizard_config->>'platform_profile' IN ('official_site', 'official_website')
  );

COMMIT;

-- Verification:
-- SELECT
--   name,
--   wizard_config#>'{quality_gate,revision_guidance}' AS revision_guidance
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     name IN ('Reddit AI Citable Post Generator', 'Official Website AI Citable Article')
--     OR name ILIKE '%reddit%'
--     OR name ILIKE '%official website%'
--   )
-- ORDER BY name;
