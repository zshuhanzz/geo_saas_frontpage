-- Migration 090: Citation learning brief + two-pass Revise quality gate
--
-- Context:
--   The first AI-citable template runs proved Citation Analysis was running,
--   but the downstream generation still treated it too much like an action
--   selector. The intended contract is broader:
--     1) learn why currently cited pages are citable;
--     2) fill the customer visibility gaps those pages leave open.
--
-- Purpose:
--   Patch template configuration so the new code path uses two Revise passes,
--   evidence-based framework coverage, stronger integrity blockers, brand
--   density controls, and Reddit-natural Brand Fit output.
--
-- Safe to re-run:
--   Yes. This migration only merges JSONB keys into existing built-in
--   content_generation templates.

BEGIN;

-- ---------------------------------------------------------------------------
-- Shared quality gate defaults for the two AI-citable templates
-- ---------------------------------------------------------------------------

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate}',
  COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || '{
    "enabled": true,
    "min_overall_score": 8,
    "revise_below_score": true,
    "max_revise_attempts": 2,
    "content_integrity_as_blocker": true,
    "framework_coverage_as_blocker": true,
    "citation_alignment_as_blocker": true,
    "citation_alignment_review_mode": "hybrid",
    "citation_alignment_markers": {
      "new_content_gap": ["brand fit", "use case", "workflow", "citation gap", "missing coverage", "patterns to learn", "visibility gap"],
      "refresh_extractability": ["brand fit", "feature", "benefit", "faq", "internal link", "extractability", "adjacent prompt"],
      "clarification_rebuttal": ["clarification", "correct", "misleading", "comparison", "troubleshooting", "outdated"]
    },
    "framework_coverage_markers": {
      "readability": ["tl;dr", "step", "workflow", "checklist", "table", "short answer"],
      "answerability": ["direct answer", "the answer", "best", "how to", "workflow", "faq", "step"],
      "trustworthy": ["limitation", "tradeoff", "verify", "source", "citation", "not a magic", "caveat", "disclaimer"],
      "freshness": ["as of", "current", "updated", "2026", "may 2026", "this year"],
      "content_understandability": ["tl;dr", "step", "workflow", "example", "checklist"],
      "information_presentation": ["table", "matrix", "bullet", "faq", "comparison"],
      "audience_fit": ["creator", "social media manager", "reddit", "instagram", "reels", "workflow"],
      "platform_fit": ["reddit", "subreddit", "comment", "discussion", "instagram", "9:16", "reels"],
      "authority_eeat": ["limitation", "source", "evidence", "tested", "current", "verify", "not legal advice"],
      "verifiability": ["source", "citation", "verify", "fact", "limitation", "as of"],
      "trending_relevance": ["2026", "may 2026", "current", "short-form", "reels", "ai video"]
    },
    "llm_issue_blocker_patterns": ["重复结尾", "重复 FAQ", "残缺", "未完成句", "结构性错误", "品牌提及过密", "duplicate ending", "duplicate FAQ", "unfinished sentence", "structural error", "brand density"]
  }'::jsonb,
  true
)
WHERE t.task_type = 'content_generation'
  AND t.name IN (
    'Reddit AI Citable Post Generator',
    'Official Website AI Citable Article'
  );

-- ---------------------------------------------------------------------------
-- Reddit-specific: keep internal Brand Fit, but naturalize the visible output
-- ---------------------------------------------------------------------------

UPDATE geo_report_templates AS t
SET
  default_prompt = 'Use Reddit Citation Analysis and Reddit insight to identify a concrete community pain point, then learn the patterns AI already cites and fill the missing brand/use-case gap. Write a Reddit-native experience post that is useful, debatable, conservative, and brand-aware without becoming promotional. Include exactly one short natural section such as "Where Dreamina actually fits in this stack" or "Where I would use Dreamina"; do not use a mechanical heading like "Brand Fit Summary" in the Reddit-facing output.',
  wizard_config =
    jsonb_set(
      jsonb_set(
        COALESCE(t.wizard_config, '{}'::jsonb),
        '{generation_requirements,reddit_brand_fit_output_policy}',
        '"Keep Brand Fit Summary as an internal requirement only. In the final Reddit post, the visible heading must be naturalized, for example: Where Dreamina actually fits, Where I would use Dreamina, or Where the brand fits in this workflow. Do not output a report-like H2 titled Brand Fit Summary."',
        true
      ),
      '{quality_gate}',
      (
        COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || '{
          "brand_density": {
            "enabled": true,
            "max_mentions": 5,
            "max_mentions_per_1000_words": 7
          },
          "revise_on_warning_rule_ids": ["multiple_faq_sections", "duplicate_h2_heading"]
        }'::jsonb
      ),
      true
    )
WHERE t.task_type = 'content_generation'
  AND t.name = 'Reddit AI Citable Post Generator';

-- Also patch older Reddit templates so future generations do not surface the
-- literal internal label as a community-facing H2.
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{generation_requirements,reddit_brand_fit_output_policy}',
  '"For Reddit, Brand Fit Summary is an internal extractability goal. The final visible heading must be natural and community-native, such as Where the brand fits, Where I would use [Brand], or Where [Brand] actually fits in the stack."',
  true
)
WHERE t.task_type = 'content_generation'
  AND (
    t.name ILIKE '%reddit%'
    OR t.defaults->>'publish_platform' = 'reddit'
    OR t.defaults->>'content_type' = 'reddit_article'
    OR t.wizard_config->>'platform_profile' = 'reddit'
  );

-- ---------------------------------------------------------------------------
-- Official Website-specific: brand density and stricter publishability
-- ---------------------------------------------------------------------------

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate}',
  COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || '{
    "brand_density": {
      "enabled": true,
      "max_mentions": 24,
      "max_mentions_per_1000_words": 12
    },
    "revise_on_warning_rule_ids": ["multiple_faq_sections", "duplicate_h2_heading", "final_thoughts_and_conclusion", "duplicate_direct_answer", "unsupported_hype_terms"]
  }'::jsonb,
  true
)
WHERE t.task_type = 'content_generation'
  AND t.name = 'Official Website AI Citable Article';

-- ---------------------------------------------------------------------------
-- Strengthen Citation Analysis playbook language for both templates
-- ---------------------------------------------------------------------------

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{generation_requirements,citation_learning_contract}',
  '"Citation Analysis has two mandatory jobs: (1) learn the advantages of already-cited pages, including structure, answer shape, evidence density, comparison criteria, workflow framing, community objections, and extractable FAQ/table patterns; (2) fill their visibility gaps, especially missing, incomplete, negative, or ambiguous customer-brand information. The final content must combine both: inherit useful citable patterns without copying source text, and add a conservative brand/use-case angle that improves GEO visibility."',
  true
)
WHERE t.task_type = 'content_generation'
  AND t.name IN (
    'Reddit AI Citable Post Generator',
    'Official Website AI Citable Article'
  );

COMMIT;

-- Verification:
-- SELECT
--   name,
--   wizard_config#>>'{quality_gate,max_revise_attempts}' AS max_revise_attempts,
--   wizard_config#>>'{quality_gate,content_integrity_as_blocker}' AS integrity_blocker,
--   wizard_config#>>'{quality_gate,framework_coverage_as_blocker}' AS framework_blocker,
--   wizard_config#>'{quality_gate,brand_density}' AS brand_density,
--   wizard_config#>>'{generation_requirements,reddit_brand_fit_output_policy}' AS reddit_brand_fit_policy,
--   wizard_config#>>'{generation_requirements,citation_learning_contract}' AS citation_learning_contract
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit AI Citable Post Generator', 'Official Website AI Citable Article')
-- ORDER BY name;
