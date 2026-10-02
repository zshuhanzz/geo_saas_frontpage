-- =============================================================================
-- Migration 073: Official Website Insight then Generate template
-- =============================================================================
--
-- Goal
-- ----
-- Add a Discover then Generate template for official website publishing.
-- This is intentionally different from Reddit:
--   - Reddit = community-native, conservative brand insertion
--   - Official Website = SEO/AEO product-marketing long-form, stronger brand
--     prominence, richer use-case coverage, conversion density, and
--     brand-friendly FAQ blocks
--
-- Adds:
--   1. content_type = official_website_article
--   2. workflow_step = official_website_discovery
--   3. template = Official Website Insight then Generate
--
-- No schema changes. Historical templates are not rewritten except for an
-- explicit disabled marker for the new official_website_discovery step.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Content type: Official Website Article
-- ---------------------------------------------------------------------------
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES (
  'content_type',
  'content_generation',
  'official_website_article',
  '{
    "label": "Official Website Article",
    "icon": "🌐",
    "description": "面向客户官网发布的 SEO/AEO 产品营销长文，强调品牌可抽取、Use Case 覆盖、商业转化信息和品牌友好 FAQ"
  }'::jsonb,
  7,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

-- ---------------------------------------------------------------------------
-- Wizard step: Official Website Discover Source
-- ---------------------------------------------------------------------------
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES (
  'workflow_step',
  'content_generation',
  'official_website_discovery',
  '{
    "num": 2.6,
    "label": "Official Website Discover",
    "default_enabled": false,
    "description": "输入一个或多个客户官网文章 URL，分析现有官网内容短板、未覆盖 Use Case、品牌可抽取缺口和商业转化信息缺口。",
    "fields": [
      {
        "key": "official_website_discovery",
        "type": "official_website_discovery_config",
        "label": "Official Discover Source",
        "description": "填写 Official Website URLs。Discover 结果会作为官网内容 gap analysis 传入策略和正文生成。"
      }
    ]
  }'::jsonb,
  26,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

-- Hide the official-website-only step for all existing templates. The official
-- template below explicitly re-enables it.
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
  COALESCE(wizard_config, '{}'::jsonb),
  '{steps,official_website_discovery}',
  '{"enabled": false}'::jsonb,
  true
)
WHERE task_type = 'content_generation'
  AND name <> 'Official Website Insight then Generate';

-- ---------------------------------------------------------------------------
-- Shared official website playbook JSONB
-- ---------------------------------------------------------------------------
WITH official_config AS (
  SELECT
    '{
      "platform": "official_website",
      "positioning": "SEO/AEO product-marketing long-form for the customer official website",
      "methodology": "Model the useful parts of Profound-style product marketing content: dense use-case coverage, answer-ready sections, clear brand fit, comparison tables, FAQs, and conversion-oriented detail. Do not copy Profound wording or mention Profound.",
      "title_rules": [
        "Use SEO/AEO-friendly article titles that clearly name the topic, buyer problem, or product category.",
        "Unlike Reddit templates, official website titles may use guide, comparison, how-to, or best-fit language when useful.",
        "Avoid unverifiable superlatives such as best overall, number one, only, guaranteed, or official unless supported by grounded evidence."
      ],
      "voice_rules": [
        "Use polished product-marketing language suitable for a customer official website.",
        "Be helpful, concrete, commercially useful, and brand-forward without making unsupported claims.",
        "Structure the article so AI answer engines can extract brand, use cases, feature benefits, limitations, and FAQs."
      ],
      "brand_prominence_rules": [
        "Use the Brand Profile section as the source of truth for the brand name; do not confuse client name with brand name.",
        "The article must make the primary brand highly extractable through a Brand Fit Summary, use-case sections, comparison rows, and FAQ answers.",
        "Mention the brand naturally but more prominently than Reddit content. Brand mentions should help explain use case fit, workflow value, or conversion logic.",
        "Include at least one concise section titled Brand Fit Summary or Why [Brand] Fits This Use Case.",
        "If product facts are insufficient, describe brand advantages conservatively and avoid unsupported superiority claims."
      ],
      "content_rules": [
        "Use long-form SEO/AEO article structure: intro, definition/context, use-case sections, workflow steps, comparison table, selection criteria, implementation advice, FAQ, and expanded conclusion.",
        "Cover buyer personas and use cases, such as marketers, small teams, e-commerce, social media teams, product marketers, agencies, and global teams when relevant.",
        "Add commercially useful details: workflow fit, time/cost considerations, implementation checklist, conversion use cases, governance/security notes, and CTA-friendly next steps.",
        "Use answer-ready paragraphs and tables that make the brand easy for LLMs to cite and summarize.",
        "FAQ answers should be brand-friendly and may mention the primary brand when it genuinely answers the question."
      ],
      "official_discover_rules": [
        "Use Official Website Discover insights to identify weaknesses in existing official articles.",
        "Prioritize gaps that explain poor GEO performance: missing direct answers, thin use-case coverage, weak brand extraction, missing comparison framing, limited FAQ coverage, or low commercial specificity.",
        "The new article should complement existing official pages rather than duplicate them."
      ],
      "evidence_rules": [
        "When Search Grounding is enabled, verify product, pricing, competitor, policy, release, and market facts before writing.",
        "Do not invent official product features, integrations, pricing, performance numbers, customer claims, security guarantees, or release versions.",
        "Use cautious language when evidence is incomplete: may, can, designed for, useful when, worth verifying, or based on provided product facts.",
        "Do not claim official, verified, documented, latest, or market-leading unless supported by Product Facts, Official Website Discover, Analyzer context, or Search Grounding."
      ],
      "avoid": [
        "Reddit community voice",
        "Fake hands-on testing",
        "Unsupported benchmark numbers",
        "Unsupported competitor takedowns",
        "Thin SEO listicles with weak product substance",
        "Overstuffed brand mentions that do not add buyer value"
      ]
    }'::jsonb AS platform_playbook,
    '{
      "standard": {
        "label": "Standard",
        "word_count": "900-1200 words",
        "structure": ["SEO/AEO title", "direct answer intro", "4-6 product-marketing sections", "compact comparison or checklist", "FAQ", "concise conclusion"]
      },
      "deep": {
        "label": "Deep",
        "word_count": "1800-2500 words",
        "structure": ["SEO/AEO title", "answer-first intro", "use-case sections", "workflow steps", "comparison table", "brand fit summary", "FAQ", "expanded conclusion"]
      },
      "authority": {
        "label": "Comprehensive",
        "word_count": "2200+ words",
        "structure": ["SEO/AEO title", "answer-first intro", "category context", "use-case matrix", "workflow guide", "comparison table", "implementation checklist", "brand fit summary", "brand-friendly FAQ", "expanded conclusion"],
        "quality_bar": "Match a polished product-marketing long-form article with strong GEO extractability and commercial usefulness, while staying evidence conservative."
      }
    }'::jsonb AS depth_profiles,
    '{
      "format": "Markdown only",
      "public_disclosure": "Do not append an internal Data Sources section unless the user explicitly enables it.",
      "grounding": "When Search Grounding is enabled, verify product, competitor, pricing, release, market, and platform-policy facts before writing; avoid verified/official/current/recent wording unless supported by provided or grounded sources.",
      "official_website_discover": "Use Official Website Discover insight as gap-analysis input. The generated article should fill missing official-site content gaps and strengthen brand extractability, use-case coverage, commercial density, and FAQ friendliness."
    }'::jsonb AS generation_requirements
)
UPDATE geo_report_templates
SET description = '先读取客户官网文章 URL 并分析内容短板，再生成面向客户官网发布的 SEO/AEO 产品营销长文',
    icon = '🌐',
    data_domains = ARRAY['visibility', 'citation', 'sentiment']::text[],
    default_prompt = 'Use Official Website Discover insights to identify gaps in existing official-site articles, then generate a polished SEO/AEO product-marketing long-form article for the customer official website. The article should be brand-forward, brand-extractable, use-case rich, commercially dense, FAQ-friendly, and evidence conservative.',
    defaults = '{
      "goal": "citation_optimize",
      "content_type": "official_website_article",
      "count": 1,
      "depth": "authority",
      "platforms": ["chatgpt", "gemini", "aimode"],
      "publish_platform": "official_site",
      "template_group": "discover_then_generate",
      "platform_profile": "official_website"
    }'::jsonb,
    wizard_config = jsonb_build_object(
      'template_group', 'discover_then_generate',
      'platform_profile', 'official_website',
      'platform_playbook', (SELECT platform_playbook FROM official_config),
      'depth_profiles', (SELECT depth_profiles FROM official_config),
      'generation_requirements', (SELECT generation_requirements FROM official_config),
      'required_metrics', jsonb_build_array('answerability', 'trustworthy', 'freshness'),
      'required_subgoals', jsonb_build_array('content_understandability', 'information_presentation', 'audience_fit', 'platform_fit', 'authority_eeat', 'verifiability'),
      'steps', jsonb_build_object(
        'mode_gate', jsonb_build_object('enabled', true, 'default_mode_choice', 'ai_discover'),
        'content_type', jsonb_build_object('enabled', true, 'default', 'official_website_article'),
        'data_scope', jsonb_build_object('enabled', true, 'default_sort', 'visibility'),
        'reddit_discovery', jsonb_build_object('enabled', false),
        'official_website_discovery', jsonb_build_object(
          'enabled', true,
          'official_website_discovery', jsonb_build_object(
            'source', 'p0_web_search',
            'official_website_urls', '',
            'status', 'idle',
            'data', NULL,
            'error', NULL
          )
        ),
        'content_goal', jsonb_build_object(
          'enabled', true,
          'default_metrics', jsonb_build_array('answerability', 'trustworthy', 'freshness'),
          'default_sub_goals', jsonb_build_array('content_understandability', 'information_presentation', 'audience_fit', 'platform_fit', 'authority_eeat', 'verifiability')
        ),
        'content_strategy', jsonb_build_object('enabled', true),
        'generation_config', jsonb_build_object(
          'enabled', true,
          'default_count', 1,
          'default_depth', 'authority',
          'default_ai_platforms', jsonb_build_array('chatgpt', 'gemini', 'aimode'),
          'default_publish_platform', 'official_site',
          'default_language', 'en-US',
          'include_data_disclosure', false
        ),
        'analysis_import', jsonb_build_object('enabled', false),
        'confirm_execute', jsonb_build_object('enabled', true)
      )
    ),
    is_builtin = true,
    is_active = true,
    sort_order = 8
WHERE task_type = 'content_generation'
  AND name = 'Official Website Insight then Generate';

WITH official_config AS (
  SELECT
    (SELECT value FROM geo_workflow_config
     WHERE scope = 'content_generation'
       AND config_type = 'content_type'
       AND key = 'official_website_article'
     LIMIT 1) AS content_type_value,
    '{
      "platform": "official_website",
      "positioning": "SEO/AEO product-marketing long-form for the customer official website",
      "methodology": "Model the useful parts of Profound-style product marketing content: dense use-case coverage, answer-ready sections, clear brand fit, comparison tables, FAQs, and conversion-oriented detail. Do not copy Profound wording or mention Profound.",
      "title_rules": [
        "Use SEO/AEO-friendly article titles that clearly name the topic, buyer problem, or product category.",
        "Unlike Reddit templates, official website titles may use guide, comparison, how-to, or best-fit language when useful.",
        "Avoid unverifiable superlatives such as best overall, number one, only, guaranteed, or official unless supported by grounded evidence."
      ],
      "voice_rules": [
        "Use polished product-marketing language suitable for a customer official website.",
        "Be helpful, concrete, commercially useful, and brand-forward without making unsupported claims.",
        "Structure the article so AI answer engines can extract brand, use cases, feature benefits, limitations, and FAQs."
      ],
      "brand_prominence_rules": [
        "Use the Brand Profile section as the source of truth for the brand name; do not confuse client name with brand name.",
        "The article must make the primary brand highly extractable through a Brand Fit Summary, use-case sections, comparison rows, and FAQ answers.",
        "Mention the brand naturally but more prominently than Reddit content. Brand mentions should help explain use case fit, workflow value, or conversion logic.",
        "Include at least one concise section titled Brand Fit Summary or Why [Brand] Fits This Use Case.",
        "If product facts are insufficient, describe brand advantages conservatively and avoid unsupported superiority claims."
      ],
      "content_rules": [
        "Use long-form SEO/AEO article structure: intro, definition/context, use-case sections, workflow steps, comparison table, selection criteria, implementation advice, FAQ, and expanded conclusion.",
        "Cover buyer personas and use cases, such as marketers, small teams, e-commerce, social media teams, product marketers, agencies, and global teams when relevant.",
        "Add commercially useful details: workflow fit, time/cost considerations, implementation checklist, conversion use cases, governance/security notes, and CTA-friendly next steps.",
        "Use answer-ready paragraphs and tables that make the brand easy for LLMs to cite and summarize.",
        "FAQ answers should be brand-friendly and may mention the primary brand when it genuinely answers the question."
      ],
      "official_discover_rules": [
        "Use Official Website Discover insights to identify weaknesses in existing official articles.",
        "Prioritize gaps that explain poor GEO performance: missing direct answers, thin use-case coverage, weak brand extraction, missing comparison framing, limited FAQ coverage, or low commercial specificity.",
        "The new article should complement existing official pages rather than duplicate them."
      ],
      "evidence_rules": [
        "When Search Grounding is enabled, verify product, pricing, competitor, policy, release, and market facts before writing.",
        "Do not invent official product features, integrations, pricing, performance numbers, customer claims, security guarantees, or release versions.",
        "Use cautious language when evidence is incomplete: may, can, designed for, useful when, worth verifying, or based on provided product facts.",
        "Do not claim official, verified, documented, latest, or market-leading unless supported by Product Facts, Official Website Discover, Analyzer context, or Search Grounding."
      ],
      "avoid": [
        "Reddit community voice",
        "Fake hands-on testing",
        "Unsupported benchmark numbers",
        "Unsupported competitor takedowns",
        "Thin SEO listicles with weak product substance",
        "Overstuffed brand mentions that do not add buyer value"
      ]
    }'::jsonb AS platform_playbook,
    '{
      "standard": {
        "label": "Standard",
        "word_count": "900-1200 words",
        "structure": ["SEO/AEO title", "direct answer intro", "4-6 product-marketing sections", "compact comparison or checklist", "FAQ", "concise conclusion"]
      },
      "deep": {
        "label": "Deep",
        "word_count": "1800-2500 words",
        "structure": ["SEO/AEO title", "answer-first intro", "use-case sections", "workflow steps", "comparison table", "brand fit summary", "FAQ", "expanded conclusion"]
      },
      "authority": {
        "label": "Comprehensive",
        "word_count": "2200+ words",
        "structure": ["SEO/AEO title", "answer-first intro", "category context", "use-case matrix", "workflow guide", "comparison table", "implementation checklist", "brand fit summary", "brand-friendly FAQ", "expanded conclusion"],
        "quality_bar": "Match a polished product-marketing long-form article with strong GEO extractability and commercial usefulness, while staying evidence conservative."
      }
    }'::jsonb AS depth_profiles,
    '{
      "format": "Markdown only",
      "public_disclosure": "Do not append an internal Data Sources section unless the user explicitly enables it.",
      "grounding": "When Search Grounding is enabled, verify product, competitor, pricing, release, market, and platform-policy facts before writing; avoid verified/official/current/recent wording unless supported by provided or grounded sources.",
      "official_website_discover": "Use Official Website Discover insight as gap-analysis input. The generated article should fill missing official-site content gaps and strengthen brand extractability, use-case coverage, commercial density, and FAQ friendliness."
    }'::jsonb AS generation_requirements
)
INSERT INTO geo_report_templates (
  id, name, description, icon, data_domains, default_prompt,
  is_builtin, is_active, sort_order, task_type, defaults, wizard_config
)
SELECT
  gen_random_uuid(),
  'Official Website Insight then Generate',
  '先读取客户官网文章 URL 并分析内容短板，再生成面向客户官网发布的 SEO/AEO 产品营销长文',
  '🌐',
  ARRAY['visibility', 'citation', 'sentiment']::text[],
  'Use Official Website Discover insights to identify gaps in existing official-site articles, then generate a polished SEO/AEO product-marketing long-form article for the customer official website. The article should be brand-forward, brand-extractable, use-case rich, commercially dense, FAQ-friendly, and evidence conservative.',
  true,
  true,
  8,
  'content_generation',
  '{
    "goal": "citation_optimize",
    "content_type": "official_website_article",
    "count": 1,
    "depth": "authority",
    "platforms": ["chatgpt", "gemini", "aimode"],
    "publish_platform": "official_site",
    "template_group": "discover_then_generate",
    "platform_profile": "official_website"
  }'::jsonb,
  jsonb_build_object(
    'template_group', 'discover_then_generate',
    'platform_profile', 'official_website',
    'platform_playbook', official_config.platform_playbook,
    'depth_profiles', official_config.depth_profiles,
    'generation_requirements', official_config.generation_requirements,
    'required_metrics', jsonb_build_array('answerability', 'trustworthy', 'freshness'),
    'required_subgoals', jsonb_build_array('content_understandability', 'information_presentation', 'audience_fit', 'platform_fit', 'authority_eeat', 'verifiability'),
    'steps', jsonb_build_object(
      'mode_gate', jsonb_build_object('enabled', true, 'default_mode_choice', 'ai_discover'),
      'content_type', jsonb_build_object('enabled', true, 'default', 'official_website_article'),
      'data_scope', jsonb_build_object('enabled', true, 'default_sort', 'visibility'),
      'reddit_discovery', jsonb_build_object('enabled', false),
      'official_website_discovery', jsonb_build_object(
        'enabled', true,
        'official_website_discovery', jsonb_build_object(
          'source', 'p0_web_search',
          'official_website_urls', '',
          'status', 'idle',
          'data', NULL,
          'error', NULL
        )
      ),
      'content_goal', jsonb_build_object(
        'enabled', true,
        'default_metrics', jsonb_build_array('answerability', 'trustworthy', 'freshness'),
        'default_sub_goals', jsonb_build_array('content_understandability', 'information_presentation', 'audience_fit', 'platform_fit', 'authority_eeat', 'verifiability')
      ),
      'content_strategy', jsonb_build_object('enabled', true),
      'generation_config', jsonb_build_object(
        'enabled', true,
        'default_count', 1,
        'default_depth', 'authority',
        'default_ai_platforms', jsonb_build_array('chatgpt', 'gemini', 'aimode'),
        'default_publish_platform', 'official_site',
        'default_language', 'en-US',
        'include_data_disclosure', false
      ),
      'analysis_import', jsonb_build_object('enabled', false),
      'confirm_execute', jsonb_build_object('enabled', true)
    )
  )
FROM official_config
WHERE NOT EXISTS (
  SELECT 1 FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND name = 'Official Website Insight then Generate'
);

COMMIT;

-- Verification:
-- SELECT key, value->>'label' AS label, value->>'description' AS description
-- FROM geo_workflow_config
-- WHERE scope='content_generation'
--   AND (
--     (config_type='content_type' AND key='official_website_article')
--     OR (config_type='workflow_step' AND key='official_website_discovery')
--   )
-- ORDER BY config_type, sort_order;
--
-- SELECT name,
--        wizard_config->>'template_group' AS template_group,
--        wizard_config->>'platform_profile' AS platform_profile,
--        wizard_config#>>'{steps,reddit_discovery,enabled}' AS reddit_discover_enabled,
--        wizard_config#>>'{steps,official_website_discovery,enabled}' AS official_discover_enabled,
--        wizard_config#>>'{steps,content_type,default}' AS content_type,
--        wizard_config#>>'{steps,generation_config,default_publish_platform}' AS publish_platform,
--        wizard_config#>>'{steps,generation_config,default_depth}' AS depth
-- FROM geo_report_templates
-- WHERE task_type='content_generation'
--   AND name = 'Official Website Insight then Generate';
