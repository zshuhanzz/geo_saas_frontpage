-- Migration 103: Move Citation Brief and segmented-outline rules into template config
--
-- Context:
--   Two prompt fragments still carried template-specific writing rules in code:
--   1. Citation Analysis hardcoded official-site framework sections such as
--      Brand Fit Summary, Value/Dream/Mini-benefits, and Feature-to-Benefit
--      Mapping.
--   2. Segmented long-form generation hardcoded a FAQ outline rule that
--      conflicted with Reddit templates where FAQ sections are forbidden by
--      default.
--
-- Purpose:
--   1. Store Citation Brief rules under wizard_config.citation_analysis.brief_rules.
--   2. Store long-form outline rules under wizard_config.segmented_generation.
--   3. Give Reddit templates community-first, no-table, no-default-FAQ rules.
--   4. Give Official Website templates natural owned-site rules without formula
--      framework headings.
--
-- Safe to re-run:
--   Yes. This migration overwrites only the targeted config subkeys.

BEGIN;

WITH generic_rules AS (
  SELECT
    '[
      "Citation data is a source of truth for structure, extractability patterns, and content gaps; do not copy cited pages.",
      "If sources are unmentioned: learn the structure and add a relevant, evidence-conservative brand angle.",
      "If sources are positive/neutral: treat them as citation assets; prefer adjacent prompts, refresh, internal linking, or support pages.",
      "If sources are negative/misleading: Do not imitate; write clarification, comparison, rebuttal, troubleshooting, or evidence-correcting content."
    ]'::jsonb AS citation_brief_rules,
    '[
      "生成一个逻辑完整、可发布的长文结构。",
      "sections 数量必须符合当前深度配置。",
      "每个 section 必须有稳定 id，例如 s1、s2、s3。",
      "每个 section 必须只承担一个清晰论点，避免章节之间重复。",
      "章节结构必须服从模板的 platform_playbook、generation_requirements 和 depth_profiles。"
    ]'::jsonb AS outline_rules,
    '"optional"'::jsonb AS faq_outline_mode,
    '"Only include FAQ items when the reader problem naturally requires recurring questions; otherwise use an empty array."'::jsonb AS faq_outline_rule
),
content_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          COALESCE(t.wizard_config, '{}'::jsonb),
          '{citation_analysis,brief_rules}',
          generic_rules.citation_brief_rules,
          true
        ),
        '{segmented_generation,outline_rules}',
        generic_rules.outline_rules,
        true
      ),
      '{segmented_generation,faq_outline_mode}',
      generic_rules.faq_outline_mode,
      true
    ),
    '{segmented_generation,faq_outline_rule}',
    generic_rules.faq_outline_rule,
    true
  )
FROM content_templates, generic_rules
WHERE t.id = content_templates.id;

WITH reddit_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%reddit%'
      OR defaults->>'content_type' = 'reddit_article'
      OR defaults->>'publish_platform' = 'reddit'
      OR wizard_config->>'platform_profile' = 'reddit'
    )
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          COALESCE(t.wizard_config, '{}'::jsonb),
          '{citation_analysis,brief_rules}',
          '[
            "Citation data supplies recurring community questions, objections, and answer patterns; do not copy cited pages.",
            "For Reddit, citation patterns must not override community fit: keep a natural peer-to-peer voice, practical tradeoffs, limitations, and a real discussion angle.",
            "Use citation gaps to decide what workflow tension or decision problem to discuss, not to create SEO sections, tables, matrices, or brand blocks.",
            "Mention the primary brand only where it naturally clarifies a workflow or option; keep claims conservative and non-promotional."
          ]'::jsonb,
          true
        ),
        '{segmented_generation,outline_rules}',
        '[
          "生成一个像真实 Reddit 长帖的结构，而不是博客、白皮书或官网文章结构。",
          "sections 数量必须符合当前深度配置。",
          "每个 section 必须有稳定 id，例如 s1、s2、s3。",
          "每个 section 必须只承担一个清晰的社区讨论点、workflow tension、tradeoff 或 caveat。",
          "不要规划 Markdown table、comparison matrix、Brand Fit Summary、Where [Brand] Fits、Helpful Resources 或默认 FAQ section。",
          "如果需要问答，只能作为自然段落或讨论问题，不要生成独立 FAQ 章节。",
          "结尾必须规划一个真实讨论问题，引导用户分享经验或反例。"
        ]'::jsonb,
        true
      ),
      '{segmented_generation,faq_outline_mode}',
      '"omit"'::jsonb,
      true
    ),
    '{segmented_generation,faq_outline_rule}',
    '""'::jsonb,
    true
  )
FROM reddit_templates
WHERE t.id = reddit_templates.id;

WITH official_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%official website%'
      OR defaults->>'content_type' = 'official_website_article'
      OR defaults->>'publish_platform' IN ('official_site', 'official_website')
      OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
    )
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          COALESCE(t.wizard_config, '{}'::jsonb),
          '{citation_analysis,brief_rules}',
          '[
            "Citation data supplies structure, extractability patterns, reader questions, and content gaps; do not copy cited pages.",
            "For official website articles, translate citation patterns into natural reader-facing sections such as evaluation criteria, workflows, use cases, limitations, or implementation guidance.",
            "Do not require or expose internal framework headings such as Brand Fit Summary, Value/Dream/Mini-benefits, Feature-to-Benefit Mapping, Citation Analysis, Quality Gate, RAFT, or strategy brief.",
            "Helpful Resources are optional and may only use exact URLs verified by Official Website Discovery.",
            "Use brand context conservatively and avoid unsupported hype or hard-sell CTA language."
          ]'::jsonb,
          true
        ),
        '{segmented_generation,outline_rules}',
        '[
          "生成一个逻辑完整、可发布的官网长文结构。",
          "sections 数量必须符合当前深度配置。",
          "每个 section 必须有稳定 id，例如 s1、s2、s3。",
          "每个 section 必须只承担一个清晰的读者决策点、criteria、workflow、use case、limitation 或 implementation consideration。",
          "可以规划 FAQ，但只有当 topic 确实存在真实 recurring questions 时才使用。",
          "不要规划 Brand Fit Summary、Value/Dream/Mini-benefits、Feature-to-Benefit Mapping 或其他内部框架标题。",
          "Helpful Resources 只能在有 verified URL 时规划；没有 verified URL 时不要规划资源章节。"
        ]'::jsonb,
        true
      ),
      '{segmented_generation,faq_outline_mode}',
      '"optional"'::jsonb,
      true
    ),
    '{segmented_generation,faq_outline_rule}',
    '"Only include FAQ items when the topic has genuine recurring reader questions; use an empty array otherwise."'::jsonb,
    true
  )
FROM official_templates
WHERE t.id = official_templates.id;

COMMIT;

-- Verification:
-- SELECT
--   name,
--   jsonb_pretty(wizard_config#>'{citation_analysis,brief_rules}') AS citation_brief_rules,
--   jsonb_pretty(wizard_config#>'{segmented_generation,outline_rules}') AS outline_rules
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     name ILIKE '%reddit%'
--     OR name ILIKE '%official website%'
--     OR defaults->>'content_type' IN ('reddit_article', 'official_website_article')
--   )
-- ORDER BY sort_order, name;
