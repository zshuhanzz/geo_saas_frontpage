-- =============================================================================
-- Migration 070: Reddit template simplification and priority reset
-- =============================================================================
--
-- Goal
-- ----
-- Pull the Reddit templates back to a stable shape:
-- community experience post + extractable brand fit + conservative evidence.
--
-- This intentionally reduces report/benchmark pressure from previous
-- refinements. It updates only:
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- No schema changes. No historical non-Reddit templates are touched.
-- =============================================================================

BEGIN;

WITH reddit_stable_playbook AS (
  SELECT
    '[
      "Write as a Reddit community experience post or practical workflow note, not a market report, analyst benchmark, SEO article, or product comparison landing page.",
      "Lead with the user problem, tradeoff, or workflow pain. The reader should feel this was written by someone solving the same problem.",
      "Use first-person only when the task provides enough evidence for a test/workflow narrative; otherwise use transparent phrasing such as field notes, practical workflow, or what I would test.",
      "Keep the structure practical: problem, what failed, what workflow works, where the brand fits, tradeoffs, checklist, short FAQ, one discussion prompt.",
      "Do not over-optimize for exhaustive coverage if it makes the post sound corporate or like a benchmark report."
    ]'::jsonb AS stable_reddit_shape,
    '{
      "must": [
        "Use the runtime date accurately; do not imply a month or period has ended while it is still in progress.",
        "Mention the primary brand naturally and include an explicit Brand Fit Summary when a brand name is available.",
        "The Brand Fit Summary must state best-fit user, use case, workflow stage, bottleneck solved, and honest limitation.",
        "Use conservative evidence language unless facts are provided by Product Facts, Analyzer context, Reddit Discover, or Search Grounding.",
        "Do not invent benchmark sample sizes, hours tested, prompt counts, blind review, community consensus, engagement data, pricing, policy, or release facts.",
        "The final article must contain complete sentences and complete paragraphs; no dangling sentence before a heading, no cut-off paragraph, no repeated conclusion."
      ],
      "prefer": [
        "Use Reddit-native titles: first-person workflow, field notes, tradeoff framing, or a concrete community question.",
        "Add one real debate angle: AI slop vs production assistant, CapCut friction vs automation, phone footage vs AI, disclosure, product-demo accuracy vs stylized B-roll.",
        "Use concrete creator scenarios such as daily Reels, scene replacement, 9:16 B-roll, caption/audio sync, visual consistency, or prompt re-roll cost.",
        "Use a compact table only when it clarifies tradeoffs; do not create a fake data table."
      ],
      "avoid": [
        "Report voice: market landscape, benchmark results, the data tells a clear story, industry-leading, current community consensus.",
        "Blog/SEO voice: ultimate guide, top tools, everything you need to know, best ever, guaranteed viral.",
        "Hard sell or brand-first framing.",
        "Overly technical category names that Reddit readers would not naturally use unless immediately explained."
      ]
    }'::jsonb AS priority_rules,
    '[
      "If the article did not actually run a measured test, do not claim tested for 40 hours, 50 prompts, benchmark, blind review, or data-backed.",
      "Acceptable alternatives: practical workflow notes, field notes, hands-on workflow review, what I would test, current working approach.",
      "If a test claim is made, include the test scope and limitations in the same section."
    ]'::jsonb AS anti_fake_benchmark_rules,
    '[
      "Before final output, check: complete title, complete paragraphs, no dangling sentence before any H2/H3 heading, no repeated ending, Brand Fit Summary present, no fake benchmark language, evidence language conservative.",
      "If any check fails, revise before outputting. Do not rely on the downstream quality review to fix it."
    ]'::jsonb AS final_output_gate
)
UPDATE geo_report_templates t
SET
  default_prompt = CASE
    WHEN t.name = 'Reddit Article' THEN
      'Write a Reddit-native community experience post or practical workflow note. The article should answer the reader problem first, include conservative evidence language, naturally mention the client brand, and provide an extractable Brand Fit Summary without sounding like a report or hard sell.'
    WHEN t.name = 'Reddit Insight then Generate' THEN
      'Use the Reddit insight to choose the strongest community pain point, then write a Reddit-native workflow note that answers that pain point, uses conservative evidence language, naturally mentions the client brand, and provides an extractable Brand Fit Summary without sounding like a report or hard sell.'
    ELSE t.default_prompt
  END,
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          COALESCE(t.wizard_config, '{}'::jsonb),
          '{platform_playbook,stable_reddit_shape}',
          reddit_stable_playbook.stable_reddit_shape,
          true
        ),
        '{platform_playbook,priority_rules}',
        reddit_stable_playbook.priority_rules,
        true
      ),
      '{platform_playbook,anti_fake_benchmark_rules}',
      reddit_stable_playbook.anti_fake_benchmark_rules,
      true
    ),
    '{platform_playbook,final_output_gate}',
    reddit_stable_playbook.final_output_gate,
    true
  )
FROM reddit_stable_playbook
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        default_prompt,
--        wizard_config#>'{platform_playbook,stable_reddit_shape}' AS stable_reddit_shape,
--        wizard_config#>'{platform_playbook,priority_rules}' AS priority_rules,
--        wizard_config#>'{platform_playbook,anti_fake_benchmark_rules}' AS anti_fake_benchmark_rules,
--        wizard_config#>'{platform_playbook,final_output_gate}' AS final_output_gate
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
