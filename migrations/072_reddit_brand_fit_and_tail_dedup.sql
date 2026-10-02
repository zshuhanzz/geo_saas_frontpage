-- =============================================================================
-- Migration 072: Reddit Brand Fit block and ending deduplication guardrails
-- =============================================================================
--
-- Goal
-- ----
-- Small refinement after reviewing outputs generated from Migration 071.
--
-- This update keeps the Reddit 0.7.0 direction stable and adds four narrow
-- quality guardrails:
--   1. Require one short Brand Fit / Where the brand fits block
--   2. Prevent duplicated TL;DR / Conclusion / discussion-ending sections
--   3. Further downgrade unsupported algorithm, policy, watermark, and
--      community-consensus claims
--   4. Keep debate angles, but frame them as questions or tradeoffs
--
-- Updates only:
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- No schema changes. No historical non-Reddit templates are touched.
-- =============================================================================

BEGIN;

WITH reddit_tail_guardrails AS (
  SELECT
    '[
      "Every Reddit article must include exactly one short section labeled either Brand Fit Summary or Where [Brand] fits.",
      "The section should be 2 to 4 sentences or one compact table row, not a promotional block.",
      "It must state: best-fit user, use case, workflow stage, bottleneck solved, and honest limitation.",
      "Preferred shape: [Brand] fits best when [user] needs [use case] during [workflow stage], especially when [bottleneck]. It is less ideal for [limitation].",
      "Do not repeat the same brand-fit claim in the FAQ and conclusion unless it adds a new limitation or use case."
    ]'::jsonb AS mandatory_brand_fit_block,
    '[
      "Use only one opening summary block. Do not include both a standalone TL;DR and another TL;DR-style section immediately after the intro.",
      "Use only one ending block. Do not include TL;DR & Let us Discuss plus FAQ plus a full Conclusion if they repeat the same takeaway.",
      "Preferred ending order: FAQ first if needed, then one short conclusion or discussion prompt. Never both Final Verdict and Conclusion with the same message.",
      "The final paragraph should end with one Reddit-native discussion prompt, not a repeated CTA.",
      "Remove repeated phrases such as no magic bullet, prompt-to-publish is dead, or AI is not a magic button if they appear more than twice."
    ]'::jsonb AS ending_dedup_rules,
    '[
      "Treat algorithm, policy, watermark, shadowban, recommendation eligibility, and community-consensus claims as high-risk claims.",
      "If these claims are not directly grounded, use softer language: may hurt reach, can create compliance risk, many creators worry about, worth verifying, or seems to be a common concern.",
      "Do not say Instagram actively buries, will penalize, will shadowban, algorithm rewards, algorithm favors, watermarks will hurt reach, or community standard unless direct evidence is provided.",
      "When discussing platform behavior, separate user behavior from platform enforcement: audiences may swipe away from low-quality AI visuals is safer than Instagram will bury AI spam.",
      "When no official source is present, add a verification cue such as check the current platform policy before publishing."
    ]'::jsonb AS high_risk_claim_downgrade_rules,
    '[
      "Keep one clear controversy, but write it as a question the community can answer.",
      "Replace final-sounding claims with discussion frames: Is CapCut still unavoidable? Are prompt-to-video tools finally good enough for daily Reels? Does AI disclosure hurt trust or build it? When is phone footage better than generated B-roll?",
      "A debate angle should invite replies, not declare a winner.",
      "If the article mentions the primary brand inside the debate, keep it as one option in the tradeoff, not the judge of the debate."
    ]'::jsonb AS debate_as_question_rules,
    '[
      "Final self-check before output: exactly one Brand Fit / Where the brand fits block, no duplicate TL;DR blocks, no duplicate conclusion blocks, high-risk claims downgraded unless grounded, controversy framed as a question, no incomplete sentence or paragraph.",
      "If the output fails any check, revise before returning."
    ]'::jsonb AS final_tail_quality_gate
)
UPDATE geo_report_templates t
SET
  default_prompt = CASE
    WHEN t.name = 'Reddit Article' THEN
      'Write a Reddit-native community experience post, not a complete guide or SEO article. Lead with a practical creator workflow problem, use conservative evidence language, naturally mention the primary brand, include exactly one short Brand Fit Summary or Where the brand fits section with best-fit use case and limitation, avoid duplicate TL;DR or conclusion sections, and frame one useful controversy as a community tradeoff question.'
    WHEN t.name = 'Reddit Insight then Generate' THEN
      'Use the Reddit insight to choose one concrete community pain point, then write a Reddit-native experience post. Do not write a market report or SEO guide. Use conservative evidence language, naturally mention the primary brand, include exactly one short Brand Fit Summary or Where the brand fits section with best-fit use case and limitation, avoid duplicate TL;DR or conclusion sections, and frame one useful controversy as a community tradeoff question.'
    ELSE t.default_prompt
  END,
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            COALESCE(t.wizard_config, '{}'::jsonb),
            '{platform_playbook,mandatory_brand_fit_block_v3}',
            reddit_tail_guardrails.mandatory_brand_fit_block,
            true
          ),
          '{platform_playbook,ending_dedup_rules_v3}',
          reddit_tail_guardrails.ending_dedup_rules,
          true
        ),
        '{platform_playbook,high_risk_claim_downgrade_rules_v3}',
        reddit_tail_guardrails.high_risk_claim_downgrade_rules,
        true
      ),
      '{platform_playbook,debate_as_question_rules_v3}',
      reddit_tail_guardrails.debate_as_question_rules,
      true
    ),
    '{platform_playbook,final_tail_quality_gate_v3}',
    reddit_tail_guardrails.final_tail_quality_gate,
    true
  )
FROM reddit_tail_guardrails
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        default_prompt,
--        wizard_config#>'{platform_playbook,mandatory_brand_fit_block_v3}' AS mandatory_brand_fit_block_v3,
--        wizard_config#>'{platform_playbook,ending_dedup_rules_v3}' AS ending_dedup_rules_v3,
--        wizard_config#>'{platform_playbook,high_risk_claim_downgrade_rules_v3}' AS high_risk_claim_downgrade_rules_v3,
--        wizard_config#>'{platform_playbook,debate_as_question_rules_v3}' AS debate_as_question_rules_v3,
--        wizard_config#>'{platform_playbook,final_tail_quality_gate_v3}' AS final_tail_quality_gate_v3
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
