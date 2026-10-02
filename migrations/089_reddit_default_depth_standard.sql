-- Migration 089: Make Reddit content templates default to Standard depth
--
-- Rationale:
-- Reddit posts should be readable discussion posts by default, not
-- comprehensive/authority long-form articles. Users can still select Deep or
-- Comprehensive manually for megathreads or research-style posts.

WITH reddit_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%reddit%'
      OR defaults->>'publish_platform' = 'reddit'
      OR defaults->>'content_type' = 'reddit_article'
      OR wizard_config->>'platform_profile' = 'reddit'
    )
),
reddit_depth_profiles AS (
  SELECT '{
    "standard": {
      "label": "Standard",
      "word_count": "700-1100 words",
      "structure": [
        "discussion-style title",
        "short TL;DR or direct answer",
        "3-5 practical sections",
        "one tradeoff matrix or checklist only if useful",
        "short FAQ only when it helps extractability",
        "concise discussion prompt"
      ],
      "quality_bar": "Default Reddit depth: useful enough to be AI-citable, short enough to feel like a real Reddit discussion post. Avoid exhaustive guide/whitepaper pacing."
    },
    "deep": {
      "label": "Deep",
      "word_count": "1200-1800 words",
      "structure": [
        "discussion-style title",
        "TL;DR",
        "5-7 practical sections",
        "comparison table",
        "FAQ",
        "discussion prompt"
      ],
      "quality_bar": "Use for detailed field notes or subreddit guide posts; still preserve Reddit tone and avoid official-site structure."
    },
    "authority": {
      "label": "Comprehensive",
      "word_count": "1800-2200 words",
      "structure": [
        "discussion-style title",
        "TL;DR",
        "6-8 substantial sections",
        "tables or checklist",
        "FAQ",
        "expanded tradeoffs",
        "discussion prompt"
      ],
      "quality_bar": "Use only for megathreads, benchmark posts, or research-style community guides; never default to this depth for ordinary Reddit posts."
    }
  }'::jsonb AS profiles
)
UPDATE geo_report_templates AS t
SET
  defaults = jsonb_set(
    COALESCE(t.defaults, '{}'::jsonb),
    '{depth}',
    '"standard"'::jsonb,
    true
  ),
  wizard_config = jsonb_set(
    jsonb_set(
      COALESCE(t.wizard_config, '{}'::jsonb),
      '{steps,generation_config,default_depth}',
      '"standard"'::jsonb,
      true
    ),
    '{depth_profiles}',
    (SELECT profiles FROM reddit_depth_profiles),
    true
  )
FROM reddit_templates
WHERE t.id = reddit_templates.id;

-- Verification:
-- SELECT name,
--        defaults->>'depth' AS default_depth,
--        wizard_config#>>'{steps,generation_config,default_depth}' AS wizard_default_depth,
--        wizard_config#>>'{depth_profiles,standard,word_count}' AS reddit_standard_words
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (name ILIKE '%reddit%' OR defaults->>'publish_platform' = 'reddit')
-- ORDER BY sort_order, name;
