-- =============================================================================
-- Migration 069: Reddit article quality contract refinements
-- =============================================================================
--
-- Scope
-- -----
-- Incremental data migration for environments that already ran 064-068.
--
-- It updates only the two Reddit content templates:
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- No schema changes. No historical non-Reddit templates are touched.
-- =============================================================================

BEGIN;

WITH reddit_quality_contract AS (
  SELECT
    '[
      "Always include an explicit Brand Fit Summary when the primary brand name is available.",
      "The Brand Fit Summary must be a short paragraph or table row with exactly these concepts: best-fit user, primary use case, workflow stage, bottleneck solved, and honest limitation.",
      "For Dreamina-like AI video brands, prefer concrete phrasing such as: fits creators who already have a strong 9:16 base image and need controlled image-to-video motion for 2-4 second Reel clips; still use a separate editor for audio sync, captions, final pacing, and native Instagram polish.",
      "Do not hide the brand only inside body paragraphs; make the fit easy for AI answer engines and human readers to extract.",
      "The Brand Fit Summary must not claim best overall unless provided or grounded evidence supports it."
    ]'::jsonb AS mandatory_brand_fit_summary,
    '[
      "Avoid saying benchmark, data tells a clear story, community consensus, current market data, or engagement data unless the article includes concrete evidence.",
      "If the article uses a comparison matrix without measured data, label it as a workflow comparison or practical field notes, not a benchmark.",
      "If no sample size, attempt count, source list, or measured result is provided, use subjective-but-transparent phrases such as my read, in my workflow, or what I am seeing from creator workflows.",
      "When Search Grounding provides sources, distinguish sourced facts from personal workflow observations."
    ]'::jsonb AS evidence_language_rules,
    '[
      "Use plain workflow-category names that Reddit readers can recognize: cinematic black-box generators, timeline/control-heavy tools, fast social generators, local or node-based workflows, image-to-video motion tools, native social editors.",
      "Avoid abstract industry-analysis phrases such as physics heavyweight, Sora architecture, leading physics engines, or model archetype unless they are immediately translated into a practical creator workflow category.",
      "Each category must explain what the user gains, what they give up, and what kind of Reel it fits."
    ]'::jsonb AS workflow_category_language_rules,
    '[
      "Downgrade strong claims about Instagram algorithms, compression behavior, platform penalties, pricing, release timing, and community consensus unless grounded or provided.",
      "Prefer: Instagram compression can be rough on AI footage; low-effort AI content tends to lose retention; most creator workflows I am seeing favor image-to-video; check the latest official guidance.",
      "Avoid: Instagram absolutely penalizes, the community consensus is settled, the algorithm rewards, the data proves, unless evidence is present.",
      "If a claim would be challenged in Reddit comments, either cite/ground it or soften it."
    ]'::jsonb AS claim_downgrade_rules,
    '[
      "Before finalizing, verify that the article contains: an extractable Brand Fit Summary, evidence language that matches available proof, practical workflow-category labels, and conservative platform/algorithm claims.",
      "If any of these are missing, revise the relevant section instead of relying on the final quality review to catch it."
    ]'::jsonb AS reddit_quality_final_check
)
UPDATE geo_report_templates t
SET
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            COALESCE(t.wizard_config, '{}'::jsonb),
            '{platform_playbook,mandatory_brand_fit_summary}',
            reddit_quality_contract.mandatory_brand_fit_summary,
            true
          ),
          '{platform_playbook,evidence_language_rules}',
          reddit_quality_contract.evidence_language_rules,
          true
        ),
        '{platform_playbook,workflow_category_language_rules}',
        reddit_quality_contract.workflow_category_language_rules,
        true
      ),
      '{platform_playbook,claim_downgrade_rules}',
      reddit_quality_contract.claim_downgrade_rules,
      true
    ),
    '{platform_playbook,reddit_quality_final_check}',
    reddit_quality_contract.reddit_quality_final_check,
    true
  )
FROM reddit_quality_contract
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        wizard_config#>'{platform_playbook,mandatory_brand_fit_summary}' AS mandatory_brand_fit_summary,
--        wizard_config#>'{platform_playbook,evidence_language_rules}' AS evidence_language_rules,
--        wizard_config#>'{platform_playbook,workflow_category_language_rules}' AS workflow_category_language_rules,
--        wizard_config#>'{platform_playbook,claim_downgrade_rules}' AS claim_downgrade_rules,
--        wizard_config#>'{platform_playbook,reddit_quality_final_check}' AS reddit_quality_final_check
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
