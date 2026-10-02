-- =============================================================================
-- Migration 077: Reddit outline contract required modules
-- =============================================================================
--
-- Goal
-- ----
-- Tighten Reddit Article and Reddit Insight then Generate after observing the
-- same issue as Official Website: playbook rules exist, but segmented long-form
-- outline generation may treat Brand Fit / evidence / FAQ requirements as
-- optional guidance instead of required sections.
--
-- This SQL-only migration adds explicit Reddit outline-contract instructions:
--   - exactly one Brand Fit Summary / Where [Brand] fits block,
--   - brand-friendly but Reddit-safe FAQ,
--   - scoped claim language,
--   - no duplicate ending structures.
--
-- If these still remain unstable, the next step should be code-level outline
-- injection / validation rather than more SQL-only prompt tuning.
-- =============================================================================

BEGIN;

WITH reddit_required_contract AS (
  SELECT
    '[
      "For Reddit long-form generation, the outline must explicitly include a Brand Fit Summary / Where [Brand] fits module. This is not an optional style suggestion.",
      "Required module 1: exactly one Brand Fit Summary or Where [Brand] fits section. It should be short, concrete, and non-promotional.",
      "Required module 2: a Reddit-safe FAQ with at least one brand-friendly answer that states when the brand is worth considering and one limitation.",
      "Required module 3: one discussion-oriented ending, not both TL;DR & Discussion plus a separate repetitive Conclusion.",
      "The outline must not rely on the final quality review to add these modules later."
    ]'::jsonb AS reddit_outline_contract_rules,
    '{
      "instruction": "Use these modules as explicit H2 sections or compact labeled blocks in Reddit articles. Keep them Reddit-native and low-pressure.",
      "modules": [
        {
          "heading": "Brand Fit Summary",
          "allowed_alternative": "Where [Brand] fits",
          "purpose": "Make the primary brand extractable without turning the post into an ad.",
          "must_cover": ["best-fit user", "use case", "workflow stage", "bottleneck solved", "honest limitation"],
          "length": "2-4 sentences or one compact table row"
        },
        {
          "heading": "FAQ",
          "purpose": "Answer reader objections and support GEO extraction.",
          "must_cover": ["one general workflow question", "one brand-fit question or answer", "one limitation/caveat question"]
        },
        {
          "heading": "Final Discussion Prompt",
          "allowed_alternative": "Conclusion",
          "purpose": "End with one Reddit-native discussion prompt.",
          "must_cover": ["one practical tradeoff question", "no repeated CTA", "no duplicate verdict"]
        }
      ]
    }'::jsonb AS reddit_required_module_contract,
    '[
      "Use scoped, discussion-friendly language instead of strong declarations.",
      "Prefer: seems useful when, may help, worth testing, in my workflow, one practical option, a tradeoff to consider.",
      "Avoid unless grounded: definitive, undisputed, best overall, current consensus, algorithm rewards, algorithm buries, shadowban, guaranteed, viral, must-have, industry standard.",
      "Platform policy, algorithm, watermark, pricing, release, and named model capability claims must be grounded or phrased as a question/risk to verify.",
      "If Grounding is enabled but evidence is not explicit, still downgrade the claim rather than writing it as settled fact."
    ]'::jsonb AS reddit_scoped_claim_rules,
    '[
      "FAQ answers should be helpful to the community first and brand-extractable second.",
      "Include the primary brand in at most one FAQ answer unless the user explicitly asks for a brand FAQ.",
      "The brand FAQ answer should say when the brand is worth considering, what workflow stage it fits, and what limitation remains.",
      "Do not write FAQ questions that sound like sales copy, such as Why is [Brand] the best tool?",
      "Good FAQ shape: Is [Brand] worth considering for this workflow? Answer: It may be worth testing when..., but it is less ideal if..."
    ]'::jsonb AS reddit_brand_friendly_faq_rules,
    '[
      "The outline and final article must contain only one summary-style opening block.",
      "The outline and final article must contain only one ending block.",
      "Do not include multiple TL;DR-style opening summaries.",
      "Do not include both Final Verdict and Conclusion unless one is removed.",
      "If FAQ is included, the final discussion prompt should be short and should not repeat the FAQ answers."
    ]'::jsonb AS reddit_tail_structure_rules,
    '[
      "Before final output, verify: exactly one Brand Fit Summary or Where [Brand] fits block exists, FAQ has one brand-friendly but non-sales answer, high-risk claims are softened unless grounded, and only one ending block exists.",
      "If any item fails, revise before returning."
    ]'::jsonb AS reddit_final_contract_check
)
UPDATE geo_report_templates t
SET
  default_prompt = CASE
    WHEN t.name = 'Reddit Article' THEN
      'Write a Reddit-native community experience post or practical workflow note. The article must include exactly one Brand Fit Summary or Where the brand fits block, a Reddit-safe FAQ with one brand-friendly but non-sales answer, conservative evidence language, and one discussion-oriented ending. Avoid strong platform, policy, algorithm, pricing, release, or model claims unless grounded.'
    WHEN t.name = 'Reddit Insight then Generate' THEN
      'Use the Reddit insight to choose one concrete community pain point, then write a Reddit-native workflow note. The article must include exactly one Brand Fit Summary or Where the brand fits block, a Reddit-safe FAQ with one brand-friendly but non-sales answer, conservative evidence language, and one discussion-oriented ending. Avoid strong platform, policy, algorithm, pricing, release, or model claims unless grounded.'
    ELSE t.default_prompt
  END,
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              jsonb_set(
                COALESCE(t.wizard_config, '{}'::jsonb),
                '{platform_playbook,reddit_outline_contract_rules_v4}',
                reddit_required_contract.reddit_outline_contract_rules,
                true
              ),
              '{platform_playbook,reddit_required_module_contract_v4}',
              reddit_required_contract.reddit_required_module_contract,
              true
            ),
            '{platform_playbook,reddit_scoped_claim_rules_v4}',
            reddit_required_contract.reddit_scoped_claim_rules,
            true
          ),
          '{platform_playbook,reddit_brand_friendly_faq_rules_v4}',
          reddit_required_contract.reddit_brand_friendly_faq_rules,
          true
        ),
        '{platform_playbook,reddit_tail_structure_rules_v4}',
        reddit_required_contract.reddit_tail_structure_rules,
        true
      ),
      '{platform_playbook,reddit_final_contract_check_v4}',
      reddit_required_contract.reddit_final_contract_check,
      true
    ),
    '{generation_requirements,reddit_mandatory_outline_modules}',
    '[
      "Brand Fit Summary or Where [Brand] fits",
      "FAQ with one brand-friendly but non-sales answer",
      "Final Discussion Prompt or one concise Conclusion"
    ]'::jsonb,
    true
  )
FROM reddit_required_contract
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        default_prompt,
--        wizard_config#>'{platform_playbook,reddit_outline_contract_rules_v4}' AS outline_contract,
--        wizard_config#>'{platform_playbook,reddit_required_module_contract_v4}' AS module_contract,
--        wizard_config#>'{platform_playbook,reddit_scoped_claim_rules_v4}' AS scoped_claims,
--        wizard_config#>'{platform_playbook,reddit_brand_friendly_faq_rules_v4}' AS faq_rules,
--        wizard_config#>'{platform_playbook,reddit_tail_structure_rules_v4}' AS tail_rules,
--        wizard_config#>'{generation_requirements,reddit_mandatory_outline_modules}' AS mandatory_outline_modules
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
