-- =============================================================================
-- Migration 064: Reddit content templates + platform/depth runtime config
-- =============================================================================
--
-- Scope
-- -----
-- 1. Add a Reddit-specific content type.
-- 2. Add a Comprehensive display option backed by the stable internal
--    depth key 'authority', and clarify Standard / Deep word-count
--    expectations for content generation.
-- 3. Seed two built-in content templates:
--    - Reddit Article                 (Generate by Template)
--    - Reddit Insight then Generate   (Discover then Generate)
--
-- This migration only changes configuration rows. It does not alter schema.
-- The content pipeline reads the platform_playbook / depth_profiles JSONB
-- from geo_report_templates.wizard_config at runtime. Reddit Discover P0/P1
-- is exposed as a schema-driven wizard step and hidden for non-Reddit
-- templates by default.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Content type: Reddit Article
-- ---------------------------------------------------------------------------
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES (
  'content_type',
  'content_generation',
  'reddit_article',
  '{
    "label": "Reddit Article",
    "icon": "💬",
    "description": "面向 Reddit 社区语境的讨论帖 / 经验帖 / 问题回应型长文，避免硬广和官网白皮书语气"
  }'::jsonb,
  6,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

-- ---------------------------------------------------------------------------
-- Wizard step: Reddit Discover Source
-- ---------------------------------------------------------------------------
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES (
  'workflow_step',
  'content_generation',
  'reddit_discovery',
  '{
    "num": 2.5,
    "label": "Reddit Discover",
    "default_enabled": false,
    "description": "选择 Reddit 发现路径，并输入 Reddit URL、Subreddit 或关键词。P0 使用 Web Search + Search Grounding；P1 预留 Reddit 官方 API。",
    "fields": [
      {
        "key": "reddit_discovery",
        "type": "reddit_discovery_config",
        "label": "Reddit Discover Source",
        "description": "Discover 结果会作为平台外部语境传入内容策略和正文生成。"
      }
    ]
  }'::jsonb,
  25,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

-- Hide the Reddit-only step for existing non-Reddit templates. The two
-- Reddit templates below explicitly re-enable it.
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
  COALESCE(wizard_config, '{}'::jsonb),
  '{steps,reddit_discovery}',
  '{"enabled": false}'::jsonb,
  true
)
WHERE task_type = 'content_generation'
  AND name NOT IN ('Reddit Article', 'Reddit Insight then Generate');

-- ---------------------------------------------------------------------------
-- Depth controls
-- ---------------------------------------------------------------------------
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES
  (
    'depth',
    'content_generation',
    'standard',
    '{
      "label": "Standard",
      "description": "文章类内容建议 900-1200 words，覆盖核心章节、FAQ 和简短结论",
      "icon": "📊"
    }'::jsonb,
    2,
    true
  ),
  (
    'depth',
    'content_generation',
    'deep',
    '{
      "label": "Deep",
      "description": "文章类内容建议 1800-2500 words，包含更完整的小节、示例、表格、FAQ 和可执行建议",
      "icon": "🔬"
    }'::jsonb,
    3,
    true
  ),
  (
    'depth',
    'content_generation',
    'authority',
    '{
      "label": "Comprehensive",
      "description": "Long-form, evidence-organized content. For Reddit this means a comprehensive community guide, not an official, hard-sell, or corporate authority voice.",
      "icon": "🏛️"
    }'::jsonb,
    4,
    true
  )
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

-- ---------------------------------------------------------------------------
-- Shared Reddit playbook JSONB used by both templates.
-- ---------------------------------------------------------------------------
WITH reddit_config AS (
  SELECT
    '{
      "platform": "reddit",
      "positioning": "community-first discussion content, not promotional landing-page copy",
      "title_rules": [
        "Use a title that sounds like a real Reddit discussion, question, experience-share post, or practical decision framework.",
        "Avoid ad-style titles, keyword-stuffed SEO titles, corporate whitepaper titles, and clickbait claims such as ultimate guide, only guide, best ever, or guaranteed viral.",
        "Prefer titles that name the user problem or tradeoff, e.g. choosing between editing-first, prompt-to-video, and product-video workflows."
      ],
      "voice_rules": [
        "Be specific, practical, and discussion-friendly.",
        "Acknowledge tradeoffs and uncertainty when facts are not fully confirmed.",
        "Avoid exaggerated product claims and polished PR language.",
        "Write like a helpful community member sharing a framework, not a brand account publishing a landing page."
      ],
      "brand_insertion_rules": [
        "Use the Brand Profile section as the source of truth for the client brand name; do not confuse client name with brand name.",
        "The article must naturally mention the client brand 2-4 times when a brand name is available, because Brand Mention is a GEO visibility objective.",
        "Every brand mention must help the reader evaluate a category, workflow, use case, or tradeoff; never force the brand into the title or TLDR as an ad.",
        "Position the brand as one relevant option in the appropriate category or workflow step, while preserving Reddit community neutrality.",
        "If product facts are insufficient, describe the brand conservatively and avoid unsupported superiority claims."
      ],
      "content_rules": [
        "Lead with the subreddit user problem or decision context before mentioning any brand.",
        "Answer common community questions directly.",
        "Use short paragraphs, checklists, comparison tables, FAQs, and a conclusion expansion when useful.",
        "Mention the brand or product naturally only where it helps the reader evaluate options.",
        "Include at least one section or table row that places the client brand in a relevant category, use case, or workflow, without sounding sponsored."
      ],
      "evidence_rules": [
        "When Search Grounding is enabled, verify product, competitor, pricing, release, market, and platform-policy facts before writing.",
        "Do not use words such as verified, official, documented, community consensus, current algorithm update, or recent release unless the source is present in Search Grounding results, Product Facts, Analyzer context, or Reddit Discover data.",
        "When evidence is incomplete or conflicting, use conservative language such as appears to, is commonly used for, may fit, or worth testing.",
        "Do not invent source names, Reddit consensus, subreddit rules, vote counts, comments, pricing, feature availability, or release versions."
      ],
      "avoid": [
        "Hard sell",
        "Fake personal experience",
        "Invented Reddit comments, subreddit names, vote counts, reviews, or user testimonials",
        "Unsupported competitor claims",
        "Overconfident claims without cited or provided evidence",
        "SEO-blog headings that do not sound native to Reddit discussions"
      ]
    }'::jsonb AS platform_playbook,
    '{
      "standard": {
        "label": "Standard",
        "word_count": "900-1200 words",
        "structure": ["discussion-style title", "direct answer intro", "4-6 practical sections", "short FAQ", "concise conclusion"]
      },
      "deep": {
        "label": "Deep",
        "word_count": "1800-2500 words",
        "structure": ["discussion-style title", "direct answer intro", "6-9 practical sections", "comparison table", "FAQ", "expanded conclusion"]
      },
      "authority": {
        "label": "Comprehensive",
        "word_count": "2200+ words",
        "structure": ["discussion-style title", "direct answer intro", "8+ substantial sections", "tables", "FAQ", "platform-specific publishing notes", "expanded conclusion"],
        "quality_bar": "Match the depth of a comprehensive community guide while preserving Reddit tone; do not use official, hard-sell, PR, or corporate authority voice."
      }
    }'::jsonb AS depth_profiles,
    '{
      "format": "Markdown only",
      "public_disclosure": "Do not append an internal Data Sources section to Reddit-ready posts unless the user explicitly enables it.",
      "grounding": "When Search Grounding is enabled, use it to verify product, competitor, pricing, release, market, and platform-policy facts before writing; avoid verified/official/current/recent wording unless supported by provided or grounded sources."
    }'::jsonb AS generation_requirements
)

-- Generate by Template: Reddit Article
UPDATE geo_report_templates
SET description = '生成面向 Reddit 发布的社区语气长文，优先回应 Subreddit 常见问题，避免硬广和企业白皮书语气',
    icon = '💬',
    data_domains = ARRAY['visibility', 'citation', 'sentiment']::text[],
    default_prompt = 'You are a Reddit-native GEO content strategist. Generate a Reddit-ready article that answers community questions first, uses practical and discussion-friendly language, avoids hard-selling, and uses brand-safe insertion so the client brand is naturally mentioned where it helps the reader evaluate options.',
    defaults = '{
      "goal": "citation_optimize",
      "content_type": "reddit_article",
      "count": 1,
      "depth": "authority",
      "platforms": ["chatgpt", "gemini", "aimode"],
      "publish_platform": "reddit",
      "template_group": "generate_by_template",
      "platform_profile": "reddit"
    }'::jsonb,
    wizard_config = jsonb_build_object(
      'template_group', 'generate_by_template',
      'platform_profile', 'reddit',
      'platform_playbook', (SELECT platform_playbook FROM reddit_config),
      'depth_profiles', (SELECT depth_profiles FROM reddit_config),
      'generation_requirements', (SELECT generation_requirements FROM reddit_config),
      'required_metrics', jsonb_build_array('readability', 'answerability', 'trustworthy', 'freshness'),
      'required_subgoals', jsonb_build_array('audience_fit', 'platform_fit', 'information_presentation', 'authority_eeat', 'verifiability', 'trending_relevance'),
      'steps', jsonb_build_object(
        'mode_gate', jsonb_build_object('enabled', true, 'default_mode_choice', 'manual'),
        'content_type', jsonb_build_object('enabled', true, 'default', 'reddit_article'),
        'data_scope', jsonb_build_object('enabled', true, 'default_sort', 'visibility'),
        'reddit_discovery', jsonb_build_object(
          'enabled', false,
          'reddit_discovery', jsonb_build_object(
            'source', 'p0_web_search',
            'reddit_urls', '',
            'subreddits', '',
            'keywords', '',
            'status', 'idle',
            'data', NULL,
            'error', NULL
          )
        ),
        'content_goal', jsonb_build_object(
          'enabled', true,
          'default_metrics', jsonb_build_array('readability', 'answerability', 'trustworthy', 'freshness'),
          'default_sub_goals', jsonb_build_array('audience_fit', 'platform_fit', 'information_presentation', 'authority_eeat', 'verifiability', 'trending_relevance')
        ),
        'content_strategy', jsonb_build_object('enabled', true),
        'generation_config', jsonb_build_object(
          'enabled', true,
          'default_count', 1,
          'default_depth', 'authority',
          'default_ai_platforms', jsonb_build_array('chatgpt', 'gemini', 'aimode'),
          'default_publish_platform', 'reddit',
          'default_language', 'en-US',
          'include_data_disclosure', false
        ),
        'analysis_import', jsonb_build_object('enabled', false),
        'confirm_execute', jsonb_build_object('enabled', true)
      )
    ),
    is_builtin = true,
    is_active = true,
    sort_order = 6
WHERE task_type = 'content_generation'
  AND name = 'Reddit Article';

WITH reddit_config AS (
  SELECT
    '{
      "platform": "reddit",
      "positioning": "community-first discussion content, not promotional landing-page copy",
      "title_rules": [
        "Use a title that sounds like a real Reddit discussion, question, experience-share post, or practical decision framework.",
        "Avoid ad-style titles, keyword-stuffed SEO titles, corporate whitepaper titles, and clickbait claims such as ultimate guide, only guide, best ever, or guaranteed viral.",
        "Prefer titles that name the user problem or tradeoff, e.g. choosing between editing-first, prompt-to-video, and product-video workflows."
      ],
      "voice_rules": [
        "Be specific, practical, and discussion-friendly.",
        "Acknowledge tradeoffs and uncertainty when facts are not fully confirmed.",
        "Avoid exaggerated product claims and polished PR language.",
        "Write like a helpful community member sharing a framework, not a brand account publishing a landing page."
      ],
      "brand_insertion_rules": [
        "Use the Brand Profile section as the source of truth for the client brand name; do not confuse client name with brand name.",
        "The article must naturally mention the client brand 2-4 times when a brand name is available, because Brand Mention is a GEO visibility objective.",
        "Every brand mention must help the reader evaluate a category, workflow, use case, or tradeoff; never force the brand into the title or TLDR as an ad.",
        "Position the brand as one relevant option in the appropriate category or workflow step, while preserving Reddit community neutrality.",
        "If product facts are insufficient, describe the brand conservatively and avoid unsupported superiority claims."
      ],
      "content_rules": [
        "Lead with the subreddit user problem or decision context before mentioning any brand.",
        "Answer common community questions directly.",
        "Use short paragraphs, checklists, comparison tables, FAQs, and a conclusion expansion when useful.",
        "Mention the brand or product naturally only where it helps the reader evaluate options.",
        "Include at least one section or table row that places the client brand in a relevant category, use case, or workflow, without sounding sponsored."
      ],
      "evidence_rules": [
        "When Search Grounding is enabled, verify product, competitor, pricing, release, market, and platform-policy facts before writing.",
        "Do not use words such as verified, official, documented, community consensus, current algorithm update, or recent release unless the source is present in Search Grounding results, Product Facts, Analyzer context, or Reddit Discover data.",
        "When evidence is incomplete or conflicting, use conservative language such as appears to, is commonly used for, may fit, or worth testing.",
        "Do not invent source names, Reddit consensus, subreddit rules, vote counts, comments, pricing, feature availability, or release versions."
      ],
      "avoid": [
        "Hard sell",
        "Fake personal experience",
        "Invented Reddit comments, subreddit names, vote counts, reviews, or user testimonials",
        "Unsupported competitor claims",
        "Overconfident claims without cited or provided evidence",
        "SEO-blog headings that do not sound native to Reddit discussions"
      ]
    }'::jsonb AS platform_playbook,
    '{
      "standard": {
        "label": "Standard",
        "word_count": "900-1200 words",
        "structure": ["discussion-style title", "direct answer intro", "4-6 practical sections", "short FAQ", "concise conclusion"]
      },
      "deep": {
        "label": "Deep",
        "word_count": "1800-2500 words",
        "structure": ["discussion-style title", "direct answer intro", "6-9 practical sections", "comparison table", "FAQ", "expanded conclusion"]
      },
      "authority": {
        "label": "Comprehensive",
        "word_count": "2200+ words",
        "structure": ["discussion-style title", "direct answer intro", "8+ substantial sections", "tables", "FAQ", "platform-specific publishing notes", "expanded conclusion"],
        "quality_bar": "Match the depth of a comprehensive community guide while preserving Reddit tone; do not use official, hard-sell, PR, or corporate authority voice."
      }
    }'::jsonb AS depth_profiles,
    '{
      "format": "Markdown only",
      "public_disclosure": "Do not append an internal Data Sources section to Reddit-ready posts unless the user explicitly enables it.",
      "grounding": "When Search Grounding is enabled, use it to verify product, competitor, pricing, release, market, and platform-policy facts before writing; avoid verified/official/current/recent wording unless supported by provided or grounded sources."
    }'::jsonb AS generation_requirements
)
INSERT INTO geo_report_templates (
  id, name, description, icon, data_domains, default_prompt,
  is_builtin, is_active, sort_order, task_type, defaults, wizard_config
)
SELECT
  gen_random_uuid(),
  'Reddit Article',
  '生成面向 Reddit 发布的社区语气长文，优先回应 Subreddit 常见问题，避免硬广和企业白皮书语气',
  '💬',
  ARRAY['visibility', 'citation', 'sentiment']::text[],
  'You are a Reddit-native GEO content strategist. Generate a Reddit-ready article that answers community questions first, uses practical and discussion-friendly language, avoids hard-selling, and uses brand-safe insertion so the client brand is naturally mentioned where it helps the reader evaluate options.',
  true,
  true,
  6,
  'content_generation',
  '{
    "goal": "citation_optimize",
    "content_type": "reddit_article",
    "count": 1,
    "depth": "authority",
    "platforms": ["chatgpt", "gemini", "aimode"],
    "publish_platform": "reddit",
    "template_group": "generate_by_template",
    "platform_profile": "reddit"
  }'::jsonb,
  jsonb_build_object(
    'template_group', 'generate_by_template',
    'platform_profile', 'reddit',
    'platform_playbook', reddit_config.platform_playbook,
    'depth_profiles', reddit_config.depth_profiles,
    'generation_requirements', reddit_config.generation_requirements,
    'required_metrics', jsonb_build_array('readability', 'answerability', 'trustworthy', 'freshness'),
    'required_subgoals', jsonb_build_array('audience_fit', 'platform_fit', 'information_presentation', 'authority_eeat', 'verifiability', 'trending_relevance'),
    'steps', jsonb_build_object(
      'mode_gate', jsonb_build_object('enabled', true, 'default_mode_choice', 'manual'),
      'content_type', jsonb_build_object('enabled', true, 'default', 'reddit_article'),
      'data_scope', jsonb_build_object('enabled', true, 'default_sort', 'visibility'),
      'reddit_discovery', jsonb_build_object(
        'enabled', false,
        'reddit_discovery', jsonb_build_object(
          'source', 'p0_web_search',
          'reddit_urls', '',
          'subreddits', '',
          'keywords', '',
          'status', 'idle',
          'data', NULL,
          'error', NULL
        )
      ),
      'content_goal', jsonb_build_object(
        'enabled', true,
        'default_metrics', jsonb_build_array('readability', 'answerability', 'trustworthy', 'freshness'),
        'default_sub_goals', jsonb_build_array('audience_fit', 'platform_fit', 'information_presentation', 'authority_eeat', 'verifiability', 'trending_relevance')
      ),
      'content_strategy', jsonb_build_object('enabled', true),
      'generation_config', jsonb_build_object(
        'enabled', true,
        'default_count', 1,
        'default_depth', 'authority',
        'default_ai_platforms', jsonb_build_array('chatgpt', 'gemini', 'aimode'),
        'default_publish_platform', 'reddit',
        'default_language', 'en-US',
        'include_data_disclosure', false
      ),
      'analysis_import', jsonb_build_object('enabled', false),
      'confirm_execute', jsonb_build_object('enabled', true)
    )
  )
FROM reddit_config
WHERE NOT EXISTS (
  SELECT 1 FROM geo_report_templates
  WHERE task_type = 'content_generation' AND name = 'Reddit Article'
);

-- Discover then Generate: Reddit Insight then Generate
WITH reddit_config AS (
  SELECT
    (SELECT wizard_config->'platform_playbook'
     FROM geo_report_templates
     WHERE task_type = 'content_generation' AND name = 'Reddit Article'
     LIMIT 1) AS platform_playbook,
    (SELECT wizard_config->'depth_profiles'
     FROM geo_report_templates
     WHERE task_type = 'content_generation' AND name = 'Reddit Article'
     LIMIT 1) AS depth_profiles,
    (SELECT wizard_config->'generation_requirements'
     FROM geo_report_templates
     WHERE task_type = 'content_generation' AND name = 'Reddit Article'
     LIMIT 1) AS generation_requirements
)
UPDATE geo_report_templates
SET description = '先基于可见度、引用和情感数据发现最值得切入的话题与 Prompts，再生成 Reddit 社区语气长文',
    icon = '🔎',
    data_domains = ARRAY['visibility', 'citation', 'sentiment']::text[],
    default_prompt = 'First discover the weakest content opportunity for Reddit from the client data, then generate a Reddit-ready article that addresses that opportunity with community-first tone, practical depth, evidence discipline, and brand-safe insertion.',
    defaults = '{
      "goal": "citation_optimize",
      "content_type": "reddit_article",
      "count": 1,
      "depth": "authority",
      "platforms": ["chatgpt", "gemini", "aimode"],
      "publish_platform": "reddit",
      "template_group": "discover_then_generate",
      "platform_profile": "reddit"
    }'::jsonb,
    wizard_config = jsonb_build_object(
      'template_group', 'discover_then_generate',
      'platform_profile', 'reddit',
      'platform_playbook', (SELECT platform_playbook FROM reddit_config),
      'depth_profiles', (SELECT depth_profiles FROM reddit_config),
      'generation_requirements', (SELECT generation_requirements FROM reddit_config),
      'required_metrics', jsonb_build_array('readability', 'answerability', 'trustworthy', 'freshness'),
      'required_subgoals', jsonb_build_array('audience_fit', 'platform_fit', 'information_presentation', 'authority_eeat', 'verifiability', 'trending_relevance'),
      'steps', jsonb_build_object(
        'mode_gate', jsonb_build_object('enabled', true, 'default_mode_choice', 'ai_discover'),
        'content_type', jsonb_build_object('enabled', true, 'default', 'reddit_article'),
        'data_scope', jsonb_build_object('enabled', true, 'default_sort', 'visibility'),
        'reddit_discovery', jsonb_build_object(
          'enabled', true,
          'reddit_discovery', jsonb_build_object(
            'source', 'p0_web_search',
            'reddit_urls', '',
            'subreddits', '',
            'keywords', '',
            'status', 'idle',
            'data', NULL,
            'error', NULL
          )
        ),
        'content_goal', jsonb_build_object(
          'enabled', true,
          'default_metrics', jsonb_build_array('readability', 'answerability', 'trustworthy', 'freshness'),
          'default_sub_goals', jsonb_build_array('audience_fit', 'platform_fit', 'information_presentation', 'authority_eeat', 'verifiability', 'trending_relevance')
        ),
        'content_strategy', jsonb_build_object('enabled', true),
        'generation_config', jsonb_build_object(
          'enabled', true,
          'default_count', 1,
          'default_depth', 'authority',
          'default_ai_platforms', jsonb_build_array('chatgpt', 'gemini', 'aimode'),
          'default_publish_platform', 'reddit',
          'default_language', 'en-US',
          'include_data_disclosure', false
        ),
        'analysis_import', jsonb_build_object('enabled', false),
        'confirm_execute', jsonb_build_object('enabled', true)
      )
    ),
    is_builtin = true,
    is_active = true,
    sort_order = 7
WHERE task_type = 'content_generation'
  AND name = 'Reddit Insight then Generate';

WITH reddit_config AS (
  SELECT
    (SELECT wizard_config->'platform_playbook'
     FROM geo_report_templates
     WHERE task_type = 'content_generation' AND name = 'Reddit Article'
     LIMIT 1) AS platform_playbook,
    (SELECT wizard_config->'depth_profiles'
     FROM geo_report_templates
     WHERE task_type = 'content_generation' AND name = 'Reddit Article'
     LIMIT 1) AS depth_profiles,
    (SELECT wizard_config->'generation_requirements'
     FROM geo_report_templates
     WHERE task_type = 'content_generation' AND name = 'Reddit Article'
     LIMIT 1) AS generation_requirements
)
INSERT INTO geo_report_templates (
  id, name, description, icon, data_domains, default_prompt,
  is_builtin, is_active, sort_order, task_type, defaults, wizard_config
)
SELECT
  gen_random_uuid(),
  'Reddit Insight then Generate',
  '先基于可见度、引用和情感数据发现最值得切入的话题与 Prompts，再生成 Reddit 社区语气长文',
  '🔎',
  ARRAY['visibility', 'citation', 'sentiment']::text[],
  'First discover the weakest content opportunity for Reddit from the client data, then generate a Reddit-ready article that addresses that opportunity with community-first tone, practical depth, evidence discipline, and brand-safe insertion.',
  true,
  true,
  7,
  'content_generation',
  '{
    "goal": "citation_optimize",
    "content_type": "reddit_article",
    "count": 1,
    "depth": "authority",
    "platforms": ["chatgpt", "gemini", "aimode"],
    "publish_platform": "reddit",
    "template_group": "discover_then_generate",
    "platform_profile": "reddit"
  }'::jsonb,
  jsonb_build_object(
    'template_group', 'discover_then_generate',
    'platform_profile', 'reddit',
    'platform_playbook', reddit_config.platform_playbook,
    'depth_profiles', reddit_config.depth_profiles,
    'generation_requirements', reddit_config.generation_requirements,
    'required_metrics', jsonb_build_array('readability', 'answerability', 'trustworthy', 'freshness'),
    'required_subgoals', jsonb_build_array('audience_fit', 'platform_fit', 'information_presentation', 'authority_eeat', 'verifiability', 'trending_relevance'),
    'steps', jsonb_build_object(
      'mode_gate', jsonb_build_object('enabled', true, 'default_mode_choice', 'ai_discover'),
      'content_type', jsonb_build_object('enabled', true, 'default', 'reddit_article'),
      'data_scope', jsonb_build_object('enabled', true, 'default_sort', 'visibility'),
      'reddit_discovery', jsonb_build_object(
        'enabled', true,
        'reddit_discovery', jsonb_build_object(
          'source', 'p0_web_search',
          'reddit_urls', '',
          'subreddits', '',
          'keywords', '',
          'status', 'idle',
          'data', NULL,
          'error', NULL
        )
      ),
      'content_goal', jsonb_build_object(
        'enabled', true,
        'default_metrics', jsonb_build_array('readability', 'answerability', 'trustworthy', 'freshness'),
        'default_sub_goals', jsonb_build_array('audience_fit', 'platform_fit', 'information_presentation', 'authority_eeat', 'verifiability', 'trending_relevance')
      ),
      'content_strategy', jsonb_build_object('enabled', true),
      'generation_config', jsonb_build_object(
        'enabled', true,
        'default_count', 1,
        'default_depth', 'authority',
        'default_ai_platforms', jsonb_build_array('chatgpt', 'gemini', 'aimode'),
        'default_publish_platform', 'reddit',
        'default_language', 'en-US',
        'include_data_disclosure', false
      ),
      'analysis_import', jsonb_build_object('enabled', false),
      'confirm_execute', jsonb_build_object('enabled', true)
    )
  )
FROM reddit_config
WHERE NOT EXISTS (
  SELECT 1 FROM geo_report_templates
  WHERE task_type = 'content_generation' AND name = 'Reddit Insight then Generate'
);

COMMIT;

-- Verification queries:
-- SELECT key, value->>'label' AS label, value->>'description' AS description
-- FROM geo_workflow_config
-- WHERE scope='content_generation' AND config_type IN ('content_type','depth')
--   AND key IN ('reddit_article','standard','deep','authority')
-- ORDER BY config_type, sort_order;
--
-- SELECT name,
--        wizard_config->>'template_group' AS template_group,
--        wizard_config->>'platform_profile' AS platform_profile,
--        wizard_config#>>'{steps,mode_gate,default_mode_choice}' AS mode,
--        wizard_config#>>'{steps,reddit_discovery,enabled}' AS reddit_discover_enabled,
--        wizard_config#>>'{steps,content_type,default}' AS content_type,
--        wizard_config#>>'{steps,generation_config,default_publish_platform}' AS publish_platform,
--        wizard_config#>>'{steps,generation_config,default_depth}' AS depth
-- FROM geo_report_templates
-- WHERE task_type='content_generation'
--   AND name IN ('Reddit Article', 'Reddit Insight then Generate')
-- ORDER BY sort_order;
