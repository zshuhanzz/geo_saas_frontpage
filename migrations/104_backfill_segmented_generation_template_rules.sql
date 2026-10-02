-- Migration 104: Backfill segmented-generation prompt rules
--
-- Context:
--   Migration 103 introduced wizard_config.segmented_generation.* rules, but
--   environments where the segmented_generation parent object did not already
--   exist can keep those nested keys empty. This repair migration writes the
--   segmented-generation object directly and is safe to run after 103.
--
-- Purpose:
--   1. Ensure all content_generation templates have configurable outline_rules.
--   2. Ensure Reddit templates omit FAQ from segmented outline prompts.
--   3. Ensure Official Website templates keep FAQ optional, not mandatory.
--
-- Safe to re-run:
--   Yes. This migration overwrites only wizard_config.segmented_generation.

BEGIN;

WITH generic_rules AS (
  SELECT jsonb_build_object(
    'outline_rules', jsonb_build_array(
      '生成一个逻辑完整、可发布的长文结构。',
      'sections 数量必须符合当前深度配置。',
      '每个 section 必须有稳定 id，例如 s1、s2、s3。',
      '每个 section 必须只承担一个清晰论点，避免章节之间重复。',
      '章节结构必须服从模板的 platform_playbook、generation_requirements 和 depth_profiles。'
    ),
    'faq_outline_mode', 'optional',
    'faq_outline_rule', 'Only include FAQ items when the reader problem naturally requires recurring questions; otherwise use an empty array.'
  ) AS segmented_generation
),
content_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
    COALESCE(t.wizard_config, '{}'::jsonb),
    '{segmented_generation}',
    generic_rules.segmented_generation,
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
    COALESCE(t.wizard_config, '{}'::jsonb),
    '{segmented_generation}',
    jsonb_build_object(
      'outline_rules', jsonb_build_array(
        '生成一个像真实 Reddit 长帖的结构，而不是博客、白皮书或官网文章结构。',
        'sections 数量必须符合当前深度配置。',
        '每个 section 必须有稳定 id，例如 s1、s2、s3。',
        '每个 section 必须只承担一个清晰的社区讨论点、workflow tension、tradeoff 或 caveat。',
        '不要规划 Markdown table、comparison matrix、Brand Fit Summary、Where [Brand] Fits、Helpful Resources 或默认 FAQ section。',
        '如果需要问答，只能作为自然段落或讨论问题，不要生成独立 FAQ 章节。',
        '结尾必须规划一个真实讨论问题，引导用户分享经验或反例。'
      ),
      'faq_outline_mode', 'omit',
      'faq_outline_rule', ''
    ),
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
    COALESCE(t.wizard_config, '{}'::jsonb),
    '{segmented_generation}',
    jsonb_build_object(
      'outline_rules', jsonb_build_array(
        '生成一个逻辑完整、可发布的官网长文结构。',
        'sections 数量必须符合当前深度配置。',
        '每个 section 必须有稳定 id，例如 s1、s2、s3。',
        '每个 section 必须只承担一个清晰的读者决策点、criteria、workflow、use case、limitation 或 implementation consideration。',
        '可以规划 FAQ，但只有当 topic 确实存在真实 recurring questions 时才使用。',
        '不要规划 Brand Fit Summary、Value/Dream/Mini-benefits、Feature-to-Benefit Mapping 或其他内部框架标题。',
        'Helpful Resources 只能在有 verified URL 时规划；没有 verified URL 时不要规划资源章节。'
      ),
      'faq_outline_mode', 'optional',
      'faq_outline_rule', 'Only include FAQ items when the topic has genuine recurring reader questions; use an empty array otherwise.'
    ),
    true
  )
FROM official_templates
WHERE t.id = official_templates.id;

COMMIT;

-- Verification:
-- SELECT
--   name,
--   wizard_config#>>'{segmented_generation,faq_outline_mode}' AS faq_outline_mode,
--   jsonb_pretty(wizard_config#>'{segmented_generation,outline_rules}') AS outline_rules
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     name ILIKE '%reddit%'
--     OR name ILIKE '%official website%'
--     OR defaults->>'content_type' IN ('reddit_article', 'official_website_article')
--   )
-- ORDER BY sort_order, name;
