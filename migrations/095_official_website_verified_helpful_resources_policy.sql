-- Migration 095: Make official-site Helpful Resources use verified discovery URLs
--
-- Context:
--   Migration 092 moved the first publishable-resource rules into template
--   config. This migration tightens that template-owned policy so the Agent
--   can execute generic URL validation/cleanup without hardcoding the official
--   website prompt contract in Python.
--
-- Purpose:
--   1. Helpful Resources may only use exact URLs found by Official Website
--      Discovery.
--   2. Raw wizard input URLs and Citation Analysis source URLs are not treated
--      as publishable resources unless discovery verified the exact URL.
--   3. Revise should delete an invalid resources section when no verified URL
--      replacement exists, rather than inventing a new same-domain path.
--
-- Safe to re-run:
--   Yes. The resource_link_policy object is overwritten for the targeted keys,
--   while unrelated template config remains intact. Revision guidance is
--   de-duped before the new lines are appended.

BEGIN;

WITH target_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%official website%'
      OR defaults->>'publish_platform' IN ('official_site', 'official_website')
      OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
    )
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{resource_link_policy}',
  COALESCE(t.wizard_config->'resource_link_policy', '{}'::jsonb) || '{
    "enabled": true,
    "apply_to_content_types": ["official_website_article"],
    "apply_to_publish_platforms": ["official_site", "official_website"],
    "apply_to_platform_profiles": ["official_site", "official_website"],
    "verified_url_source": "official_website_discovery",
    "verified_url_match": "exact",
    "include_wizard_input_urls_without_discovery": false,
    "include_citation_source_urls_by_default": false,
    "sanitize_generated_content": true,
    "remove_section_when_no_verified_links": true,
    "section_headings": [
      "Helpful Resources",
      "Further Reading",
      "Related Resources",
      "Learn More"
    ],
    "output_heading": "Helpful Resources",
    "prompt_title": "Publishable Resource Link Policy",
    "no_verified_urls_instruction": "No exact URL has been verified by Official Website Discovery; do not generate a Helpful Resources / Further Reading / Related Resources / Learn More section.",
    "generation_rules": [
      "正文只能包含读者可直接阅读和发布的内容；不要输出编辑备注、SEO/AEO 操作说明或后台执行建议。",
      "禁止输出以下字段或措辞：Anchor Text、Destination、Target Page、Internal Linking Suggestions、Suggested Internal Links、Internal Linking Plan、SEO placement instruction、editor note、strategically placing these links、Insert Official、placeholder URL。",
      "如果需要推荐延伸阅读，只能使用 reader-facing 标题，例如 Helpful Resources 或 Further Reading；不要使用品牌堆叠式资源标题。",
      "Citation Analysis sources 只能用于学习结构、信息密度、FAQ 形态和内容缺口；不要默认把 Citation source URL 放进正文 Helpful Resources。",
      "Helpful Resources 只能引用 Official Website Discovery 已验证过的真实、精确 URL；同一个 owned domain 下未发现的路径也不能使用。",
      "中立权威外部来源可以用于事实支持，但不能放入 Helpful Resources，除非它也出现在精确 URL 列表里。",
      "不要编造外部 destination，不要把 Citation Analysis URL 自动改写成资源链接。",
      "如果没有可验证 URL，就不要生成 Helpful Resources / Further Reading / Related Resources / Learn More 资源列表；直接省略该部分。"
    ],
    "revision_instruction": "如果 Helpful Resources / Further Reading / Related Resources / Learn More 链接不符合 Quality Gate，只能使用 Official Website Discovery 已验证的精确 URL；没有可替换 URL 时删除整个资源列表，不要编造新链接。",
    "quality_gate_rule": {
      "id": "official_helpful_resources_unverified_links",
      "type": "official_resource_link_policy",
      "severity": "blocker",
      "message": "Helpful Resources contains links outside the verified Official Website Discovery URL pool."
    }
  }'::jsonb,
  true
)
FROM target_templates
WHERE t.id = target_templates.id;

WITH target_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%official website%'
      OR defaults->>'publish_platform' IN ('official_site', 'official_website')
      OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
    )
),
filtered_guidance AS (
  SELECT
    id,
    COALESCE(
      (
        SELECT jsonb_agg(value)
        FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,revision_guidance,general}', '[]'::jsonb)) AS guidance(value)
        WHERE value NOT IN (
          '"Citation source URLs are learning examples for structure and extractability; do not automatically list them as Helpful Resources in the official article."'::jsonb,
          '"Helpful Resources should use customer owned domains or configured brand ecosystem domains. External neutral authority links may be used only for factual support; competitor/tool/vendor links should be removed from the resource list."'::jsonb,
          '"Helpful Resources must use exact URLs verified by Official Website Discovery; same-domain guessed paths are not allowed."'::jsonb,
          '"If there is no verified URL replacement, delete the Helpful Resources section instead of inventing a new link."'::jsonb
        )
      ),
      '[]'::jsonb
    ) AS guidance
  FROM target_templates
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate,revision_guidance,general}',
  filtered_guidance.guidance || '[
    "Citation source URLs are learning examples for structure and extractability; do not automatically list them as Helpful Resources in the official article.",
    "Helpful Resources must use exact URLs verified by Official Website Discovery; same-domain guessed paths are not allowed.",
    "If there is no verified URL replacement, delete the Helpful Resources section instead of inventing a new link."
  ]'::jsonb,
  true
)
FROM filtered_guidance
WHERE t.id = filtered_guidance.id;

COMMIT;

-- Verification:
-- SELECT
--   name,
--   wizard_config#>'{resource_link_policy}' AS resource_link_policy,
--   wizard_config#>'{quality_gate,revision_guidance,general}' AS revision_guidance
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     name ILIKE '%official website%'
--     OR defaults->>'publish_platform' IN ('official_site', 'official_website')
--     OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
--   )
-- ORDER BY name;
