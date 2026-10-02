-- =============================================================================
-- Migration 068: Reddit review contract refinements
-- =============================================================================
--
-- Scope
-- -----
-- Incremental data migration for environments that already ran 064-067.
--
-- It updates only the two Reddit content templates:
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- No schema changes. No historical non-Reddit templates are touched.
-- =============================================================================

BEGIN;

WITH reddit_review_contract AS (
  SELECT
    '[
      "If the runtime month is still May 2026, do not write Post-May 2026, after May 2026, or similar wording that implies the month has already ended.",
      "Prefer current-month field-test titles such as May 2026 field test, My May 2026 workflow, or I tested X in May 2026.",
      "Use historical or post-period wording only when the runtime date is after that period or the user explicitly requests a retrospective.",
      "The title must make the Reddit discussion context clear without overpromising a definitive market ranking."
    ]'::jsonb AS temporal_title_rules,
    '[
      "Keep the testing methodology internally consistent from baseline prompt to failed attempts to winning workflow to conclusion.",
      "Do not switch test objects mid-article, e.g. latte art/cafe in methodology but desk creator in failed attempts, unless the article explicitly says there were multiple scenarios.",
      "If multiple scenarios are tested, name them upfront and keep results mapped to each scenario.",
      "The final answer must not claim a controlled experiment unless the article contains clear criteria, tested scenarios, and comparable observations."
    ]'::jsonb AS methodology_consistency_rules,
    '[
      "Do not use data-backed, statistically tested, engagement data, community consensus, or benchmark language unless concrete data is included.",
      "If using data-backed language, include a compact evidence table with at least: test item, what was tracked, sample size or number of attempts, observation, and limitation.",
      "If concrete data is not available, use candid workflow review, field notes, observed workflow, or practical testing notes instead.",
      "Avoid invented render times, costs, success rates, and engagement outcomes."
    ]'::jsonb AS data_backing_rules,
    '[
      "Include a clearly labeled Brand Fit Summary or equivalent table row for the primary brand.",
      "The Brand Fit Summary must include: best-fit user, use case, workflow stage, bottleneck solved, and honest limitation.",
      "Example: Dreamina fits creators who need fast prompt-to-polish B-roll from structured 3-5 second shot prompts; it belongs in the generation stage, while audio sync, captions, and final pacing still need a timeline or native editor.",
      "This section must be specific enough that an AI answer engine can extract when and why the brand should be considered."
    ]'::jsonb AS extractable_brand_fit_rules,
    '[
      "Strong factual claims about platform algorithms, pricing, policies, release timing, community consensus, or engagement outcomes require provided or grounded evidence.",
      "When evidence is incomplete, downgrade language to observation, assumption, or recommendation to test.",
      "Use phrases such as in my workflow, from creator reports I have seen, worth testing on your account, or check the latest official guidance.",
      "Never imply that Reddit, Instagram, Meta, or a creator community has a settled consensus unless the source is present."
    ]'::jsonb AS claim_strength_rules,
    '[
      "Before finalizing, run a review contract check: title temporal precision, methodology consistency, evidence table if data-backed, extractable Brand Fit Summary, conservative evidence language, no artificial truncation, no duplicated ending.",
      "If any review contract item fails, revise the relevant section before outputting the final article."
    ]'::jsonb AS final_review_contract
)
UPDATE geo_report_templates t
SET
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              COALESCE(t.wizard_config, '{}'::jsonb),
              '{platform_playbook,temporal_title_rules}',
              reddit_review_contract.temporal_title_rules,
              true
            ),
            '{platform_playbook,methodology_consistency_rules}',
            reddit_review_contract.methodology_consistency_rules,
            true
          ),
          '{platform_playbook,data_backing_rules}',
          reddit_review_contract.data_backing_rules,
          true
        ),
        '{platform_playbook,extractable_brand_fit_rules}',
        reddit_review_contract.extractable_brand_fit_rules,
        true
      ),
      '{platform_playbook,claim_strength_rules}',
      reddit_review_contract.claim_strength_rules,
      true
    ),
    '{platform_playbook,final_review_contract}',
    reddit_review_contract.final_review_contract,
    true
  )
FROM reddit_review_contract
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        wizard_config#>'{platform_playbook,temporal_title_rules}' AS temporal_title_rules,
--        wizard_config#>'{platform_playbook,methodology_consistency_rules}' AS methodology_consistency_rules,
--        wizard_config#>'{platform_playbook,data_backing_rules}' AS data_backing_rules,
--        wizard_config#>'{platform_playbook,extractable_brand_fit_rules}' AS extractable_brand_fit_rules,
--        wizard_config#>'{platform_playbook,claim_strength_rules}' AS claim_strength_rules,
--        wizard_config#>'{platform_playbook,final_review_contract}' AS final_review_contract
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
