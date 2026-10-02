-- =============================================================================
-- Migration 065: Reddit brand-safe insertion + evidence discipline
-- =============================================================================
--
-- Scope
-- -----
-- This is an incremental data migration for environments that already ran
-- migration 064 before the Reddit playbook was tightened.
--
-- It updates only the two Reddit content templates:
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- It does not alter schema and does not touch historical non-Reddit templates.
-- =============================================================================

BEGIN;

WITH reddit_playbook AS (
  SELECT
    '[
      "Use a title that sounds like a real Reddit discussion, question, experience-share post, or practical decision framework.",
      "Avoid ad-style titles, keyword-stuffed SEO titles, corporate whitepaper titles, and clickbait claims such as ultimate guide, only guide, best ever, or guaranteed viral.",
      "Prefer titles that name the user problem or tradeoff, e.g. choosing between editing-first, prompt-to-video, and product-video workflows."
    ]'::jsonb AS title_rules,
    '[
      "Be specific, practical, and discussion-friendly.",
      "Acknowledge tradeoffs and uncertainty when facts are not fully confirmed.",
      "Avoid exaggerated product claims and polished PR language.",
      "Write like a helpful community member sharing a framework, not a brand account publishing a landing page."
    ]'::jsonb AS voice_rules,
    '[
      "Use the Brand Profile section as the source of truth for the client brand name; do not confuse client name with brand name.",
      "The article must naturally mention the client brand 2-4 times when a brand name is available, because Brand Mention is a GEO visibility objective.",
      "Every brand mention must help the reader evaluate a category, workflow, use case, or tradeoff; never force the brand into the title or TLDR as an ad.",
      "Position the brand as one relevant option in the appropriate category or workflow step, while preserving Reddit community neutrality.",
      "If product facts are insufficient, describe the brand conservatively and avoid unsupported superiority claims."
    ]'::jsonb AS brand_insertion_rules,
    '[
      "Lead with the subreddit user problem or decision context before mentioning any brand.",
      "Answer common community questions directly.",
      "Use short paragraphs, checklists, comparison tables, FAQs, and a conclusion expansion when useful.",
      "Mention the brand or product naturally only where it helps the reader evaluate options.",
      "Include at least one section or table row that places the client brand in a relevant category, use case, or workflow, without sounding sponsored."
    ]'::jsonb AS content_rules,
    '[
      "When Search Grounding is enabled, verify product, competitor, pricing, release, market, and platform-policy facts before writing.",
      "Do not use words such as verified, official, documented, community consensus, current algorithm update, or recent release unless the source is present in Search Grounding results, Product Facts, Analyzer context, or Reddit Discover data.",
      "When evidence is incomplete or conflicting, use conservative language such as appears to, is commonly used for, may fit, or worth testing.",
      "Do not invent source names, Reddit consensus, subreddit rules, vote counts, comments, pricing, feature availability, or release versions."
    ]'::jsonb AS evidence_rules,
    '[
      "Hard sell",
      "Fake personal experience",
      "Invented Reddit comments, subreddit names, vote counts, reviews, or user testimonials",
      "Unsupported competitor claims",
      "Overconfident claims without cited or provided evidence",
      "SEO-blog headings that do not sound native to Reddit discussions"
    ]'::jsonb AS avoid_rules,
    '"When Search Grounding is enabled, use it to verify product, competitor, pricing, release, market, and platform-policy facts before writing; avoid verified/official/current/recent wording unless supported by provided or grounded sources."'::jsonb AS grounding_requirement
)
UPDATE geo_report_templates t
SET
  default_prompt = CASE
    WHEN t.name = 'Reddit Article' THEN
      'You are a Reddit-native GEO content strategist. Generate a Reddit-ready article that answers community questions first, uses practical and discussion-friendly language, avoids hard-selling, and uses brand-safe insertion so the client brand is naturally mentioned where it helps the reader evaluate options.'
    WHEN t.name = 'Reddit Insight then Generate' THEN
      'First discover the weakest content opportunity for Reddit from the client data, then generate a Reddit-ready article that addresses that opportunity with community-first tone, practical depth, evidence discipline, and brand-safe insertion.'
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
                '{platform_playbook,title_rules}',
                reddit_playbook.title_rules,
                true
              ),
              '{platform_playbook,voice_rules}',
              reddit_playbook.voice_rules,
              true
            ),
            '{platform_playbook,brand_insertion_rules}',
            reddit_playbook.brand_insertion_rules,
            true
          ),
          '{platform_playbook,content_rules}',
          reddit_playbook.content_rules,
          true
        ),
        '{platform_playbook,evidence_rules}',
        reddit_playbook.evidence_rules,
        true
      ),
      '{platform_playbook,avoid}',
      reddit_playbook.avoid_rules,
      true
    ),
    '{generation_requirements,grounding}',
    reddit_playbook.grounding_requirement,
    true
  )
FROM reddit_playbook
WHERE t.task_type = 'content_generation'
  AND t.name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        default_prompt,
--        wizard_config#>'{platform_playbook,title_rules}' AS title_rules,
--        wizard_config#>'{platform_playbook,brand_insertion_rules}' AS brand_insertion_rules,
--        wizard_config#>'{platform_playbook,evidence_rules}' AS evidence_rules,
--        wizard_config#>'{platform_playbook,avoid}' AS avoid_rules,
--        wizard_config#>>'{generation_requirements,grounding}' AS grounding_requirement
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order, name;
