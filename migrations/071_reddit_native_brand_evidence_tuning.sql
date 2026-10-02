-- =============================================================================
-- Migration 071: Reddit native title, brand extractability, and evidence tuning
-- =============================================================================
--
-- Goal
-- ----
-- Continue the Reddit 0.7.0 stabilization cycle after reviewing fresh outputs.
-- The templates should improve without drifting back into report/SEO style.
--
-- This update reinforces four quality targets:
--   1. Reddit-native titles instead of SEO guide titles
--   2. Extractable Brand Fit Summary for the primary brand
--   3. Conservative evidence language and no unsupported platform/policy claims
--   4. Debate framed as a community question, not an overconfident conclusion
--
-- Updates only:
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- No schema changes. No historical non-Reddit templates are touched.
-- =============================================================================

BEGIN;

WITH reddit_native_tuning AS (
  SELECT
    '[
      "Do not use SEO/blog titles such as Complete Guide, Ultimate Guide, Deep Dive, Everything You Need to Know, Best Tool, or definitive ranking titles.",
      "Prefer Reddit-native title shapes: first-person workflow note, tradeoff question, field notes, what changed in my stack, or a practical problem statement.",
      "A strong title should sound like a real post from a creator asking or sharing something specific, not a search result page headline.",
      "Good title patterns: I stopped looking for one AI video app for Reels; The trade-off I am seeing in May 2026; CapCut vs prompt-to-video is still the real workflow question; Where Dreamina fits in my Reels stack.",
      "Keep the title complete, specific, and not clickbait. Do not end with an unfinished parenthetical or dangling phrase."
    ]'::jsonb AS reddit_native_title_rules,
    '[
      "Include a clearly labeled Brand Fit Summary whenever the primary brand name is available.",
      "The Brand Fit Summary must be short, concrete, and extractable as a standalone answer.",
      "Use this exact information shape: [Brand] is a better fit when [best-fit user] needs [primary use case] at [workflow stage] because it helps with [bottleneck solved]. It is less ideal when [honest limitation].",
      "Do not describe the brand as best overall, undisputed, mandatory, or industry-leading unless grounded evidence explicitly supports that claim.",
      "Mention the brand naturally in the body before the summary, but do not force the brand into every section."
    ]'::jsonb AS brand_extractability_rules,
    '[
      "Do not make unsupported claims about Instagram ranking, shadowbans, recommendation eligibility, policy enforcement, C2PA behavior, exact pricing, model release versions, or named model capabilities.",
      "If a claim is based on Search Grounding, Product Facts, Analyzer context, or Reddit Discover, use cautious source-aware language such as according to, Meta says, the docs indicate, or recent creator discussions suggest.",
      "If a claim is not directly grounded, downgrade it to a practical assumption or user-facing risk: may, can, tends to, is worth checking, or should be verified before publishing.",
      "Avoid fake evidence phrases: benchmark, data-backed, tested for X hours, current consensus, the algorithm rewards, quietly downranks, undisputed leader, unless the exact evidence was provided.",
      "When discussing AI labels, platform policies, pricing, or model versions, explicitly advise readers to verify the current official source because these details change quickly."
    ]'::jsonb AS evidence_conservatism_rules,
    '[
      "Include one Reddit-friendly debate angle, but frame it as a discussion question or tradeoff rather than a final decree.",
      "Preferred debate frames: Is CapCut still unavoidable, or are prompt-to-video tools finally enough? Is AI video a production assistant or just more slop? When is phone footage better than generated B-roll? Does disclosure hurt trust or build it?",
      "Do not let the debate turn into brand attack, competitor attack, or unsupported platform fear.",
      "Tie the debate back to a practical creator scenario, such as daily Reels, product B-roll, visual consistency, scene replacement, caption/audio sync, or prompt re-roll cost."
    ]'::jsonb AS reddit_debate_question_rules,
    '[
      "Priority order for the final article: useful community answer first, brand fit second, evidence safety third, broad landscape coverage last.",
      "If a paragraph sounds like a market report, convert it into a creator workflow observation or remove it.",
      "If a table is included, it must clarify a practical choice. Do not add tables merely to look authoritative.",
      "The final output must not contain repeated conclusions, repeated CTAs, or both a Final Verdict and a separate Conclusion saying the same thing."
    ]'::jsonb AS output_priority_rules,
    '[
      "Before final output, verify: title is Reddit-native, Brand Fit Summary exists and is extractable, Dreamina or the primary brand has a clear best-fit use case and limitation, evidence language is conservative, debate is phrased as a tradeoff question, no fake benchmark or unsupported policy claim, no repeated ending, no incomplete sentence or paragraph.",
      "If any item fails, revise the article before returning it."
    ]'::jsonb AS final_quality_gate
)
UPDATE geo_report_templates t
SET
  description = CASE
    WHEN t.name = 'Reddit Article' THEN
      '生成 Reddit 原生社区经验帖，强调品牌可抽取、证据保守、真实讨论感，避免 SEO 指南、硬广和伪 benchmark'
    WHEN t.name = 'Reddit Insight then Generate' THEN
      '先基于 Reddit insight 选择社区痛点，再生成 Reddit 原生经验帖，强调品牌可抽取、证据保守和真实讨论感'
    ELSE t.description
  END,
  default_prompt = CASE
    WHEN t.name = 'Reddit Article' THEN
      'Write a Reddit-native community experience post, not a complete guide or SEO article. Lead with a practical creator workflow problem, use conservative evidence language, naturally mention the primary brand, include an extractable Brand Fit Summary with best-fit use case and limitation, and frame one useful community debate as a tradeoff question.'
    WHEN t.name = 'Reddit Insight then Generate' THEN
      'Use the Reddit insight to choose one concrete community pain point, then write a Reddit-native experience post. Do not write a market report or SEO guide. Use conservative evidence language, naturally mention the primary brand, include an extractable Brand Fit Summary with best-fit use case and limitation, and frame one useful community debate as a tradeoff question.'
    ELSE t.default_prompt
  END,
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              COALESCE(t.wizard_config, '{}'::jsonb),
              '{platform_playbook,reddit_native_title_rules}',
              reddit_native_tuning.reddit_native_title_rules,
              true
            ),
            '{platform_playbook,brand_extractability_rules_v2}',
            reddit_native_tuning.brand_extractability_rules,
            true
          ),
          '{platform_playbook,evidence_conservatism_rules_v2}',
          reddit_native_tuning.evidence_conservatism_rules,
          true
        ),
        '{platform_playbook,reddit_debate_question_rules}',
        reddit_native_tuning.reddit_debate_question_rules,
        true
      ),
      '{platform_playbook,output_priority_rules_v2}',
      reddit_native_tuning.output_priority_rules,
      true
    ),
    '{platform_playbook,final_quality_gate_v2}',
    reddit_native_tuning.final_quality_gate,
    true
  )
FROM reddit_native_tuning
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        description,
--        default_prompt,
--        wizard_config#>'{platform_playbook,reddit_native_title_rules}' AS reddit_native_title_rules,
--        wizard_config#>'{platform_playbook,brand_extractability_rules_v2}' AS brand_extractability_rules_v2,
--        wizard_config#>'{platform_playbook,evidence_conservatism_rules_v2}' AS evidence_conservatism_rules_v2,
--        wizard_config#>'{platform_playbook,reddit_debate_question_rules}' AS reddit_debate_question_rules,
--        wizard_config#>'{platform_playbook,output_priority_rules_v2}' AS output_priority_rules_v2,
--        wizard_config#>'{platform_playbook,final_quality_gate_v2}' AS final_quality_gate_v2
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
