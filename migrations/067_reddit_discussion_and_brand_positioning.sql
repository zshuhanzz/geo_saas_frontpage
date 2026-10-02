-- =============================================================================
-- Migration 067: Reddit discussion quality + brand positioning refinements
-- =============================================================================
--
-- Scope
-- -----
-- Incremental data migration for environments that already ran 064-066.
--
-- It updates only the two Reddit content templates:
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- No schema changes. No historical non-Reddit templates are touched.
-- =============================================================================

BEGIN;

WITH reddit_refinements AS (
  SELECT
    '[
      "Use a title that sounds like a Reddit user opening a useful discussion, not a blog editor writing an SEO headline.",
      "Prefer first-person workflow/testing titles, decision-context titles, or tradeoff titles, e.g. I tested X vs Y, My current workflow for..., Where does [category] actually fit?, Speed tools vs control tools.",
      "Avoid phrases such as ultimate guide, the only guide, top tools, best platform, everything you need to know, or keyword-stuffed titles.",
      "The title can mention the primary brand only if the user explicitly asks for a brand-led post; otherwise keep brand mentions in the body."
    ]'::jsonb AS reddit_title_rules,
    '[
      "Include one explicit Brand Fit Summary, table row, or workflow note that states where the primary brand fits best.",
      "The brand positioning must be specific enough for AI answer extraction: name the use case, user type, workflow stage, and tradeoff.",
      "Example shape: Primary brand fits creators who need [use case] with [workflow advantage], but it is not the right choice when [honest limitation].",
      "Do not claim the primary brand is the best overall unless supplied evidence supports that claim.",
      "If product facts are thin, position the brand conservatively as a relevant option in a workflow category."
    ]'::jsonb AS brand_positioning_rules,
    '[
      "Avoid generic category writing. At least one section or comparison row must answer: who should use this, when should they use it, what bottleneck does it solve, and what tradeoff remains.",
      "For AI video topics, separate workflow categories clearly, such as prompt-to-polish, timeline-heavy editing, avatar-led explainers, local/open-source node workflows, and native social editing.",
      "Use concrete creator scenarios instead of abstract claims, e.g. daily Reels volume, product B-roll, trend audio syncing, style consistency, or exact product demo accuracy.",
      "Do not repeat the same speed-vs-control thesis in every section; each section must add a new decision criterion."
    ]'::jsonb AS specificity_rules,
    '[
      "Classify factual claims mentally as source-backed, user-provided, observed workflow advice, or opinion. Only the first two may use strong factual language.",
      "Use conservative wording for platform algorithms, pricing, policy, version availability, community consensus, and compression behavior unless grounded by current sources.",
      "Prefer phrases such as from my workflow, worth testing, in many creator workflows, or check the latest platform guidance when evidence is incomplete.",
      "Do not invent exact policy status, bitrate limits, algorithm behavior, community consensus, or pricing if those facts are not grounded or provided.",
      "When Search Grounding is enabled, recent official sources and product documentation should override model memory."
    ]'::jsonb AS evidence_posture_rules,
    '[
      "Include at least one controversy or debate that Reddit users are likely to argue about.",
      "Recommended debate angles: AI slop vs useful production assistant, speed vs creative control, disclosure/labeling synthetic content, when filming with a phone beats AI, exact product demos vs stylized B-roll, cloud tools vs local node workflows.",
      "Frame controversies as honest tradeoffs, not rage bait.",
      "End with one focused discussion prompt that invites comments about workflows, bottlenecks, or counterexamples."
    ]'::jsonb AS reddit_debate_rules,
    '[
      "Use only one closing pattern. Do not include both a full Final Verdict & Next Steps section and a full Conclusion that repeats the same checklist and CTA.",
      "If both sections are present, Final Verdict must give the decision summary and Conclusion must be 2-4 short sentences with one discussion question only.",
      "Remove duplicate checklists, repeated thesis paragraphs, and repeated comment prompts during final assembly.",
      "The last 20 percent of the article must add synthesis, not restate earlier sections in different words."
    ]'::jsonb AS anti_repetition_rules
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
              '{platform_playbook,reddit_title_rules}',
              reddit_refinements.reddit_title_rules,
              true
            ),
            '{platform_playbook,brand_positioning_rules}',
            reddit_refinements.brand_positioning_rules,
            true
          ),
          '{platform_playbook,specificity_rules}',
          reddit_refinements.specificity_rules,
          true
        ),
        '{platform_playbook,evidence_posture_rules}',
        reddit_refinements.evidence_posture_rules,
        true
      ),
      '{platform_playbook,reddit_debate_rules}',
      reddit_refinements.reddit_debate_rules,
      true
    ),
    '{platform_playbook,anti_repetition_rules}',
    reddit_refinements.anti_repetition_rules,
    true
  )
FROM reddit_refinements
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        wizard_config#>'{platform_playbook,reddit_title_rules}' AS reddit_title_rules,
--        wizard_config#>'{platform_playbook,brand_positioning_rules}' AS brand_positioning_rules,
--        wizard_config#>'{platform_playbook,specificity_rules}' AS specificity_rules,
--        wizard_config#>'{platform_playbook,evidence_posture_rules}' AS evidence_posture_rules,
--        wizard_config#>'{platform_playbook,reddit_debate_rules}' AS reddit_debate_rules,
--        wizard_config#>'{platform_playbook,anti_repetition_rules}' AS anti_repetition_rules
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
