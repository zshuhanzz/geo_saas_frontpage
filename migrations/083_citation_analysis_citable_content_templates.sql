-- =============================================================================
-- Migration 083: Citation Analysis config + AI-citable content templates
-- =============================================================================
--
-- Goal
-- ----
-- Add a configuration-driven Citation Analysis layer for content generation,
-- without changing existing template behavior by default.
--
-- Adds:
--   1. Workflow dictionaries for citation source scope, brand triage policy,
--      and content action decision.
--   2. A new content_generation workflow_step: citation_analysis.
--   3. Disabled citation_analysis defaults for all existing content templates.
--   4. Two new built-in templates that default-enable citation analysis:
--        - Reddit AI Citable Post Generator
--        - Official Website AI Citable Article
--
-- Important implementation note
-- -----------------------------
-- This migration is the data/config layer. Runtime code consumes these fields in:
--   - SaaS wizard task input mapping,
--   - geo_agent strategy generation,
--   - geo_agent content generation,
--   - citation fetching + brand mention triage,
--   - quality review / revise.
--
-- The workflow step deliberately uses existing primitive field types so the
-- Admin/SaaS wizard can render it without a custom frontend component.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Citation Analysis dictionaries
-- ---------------------------------------------------------------------------

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES
(
  'citation_source_scope',
  'content_generation',
  'auto_by_template',
  '{
    "label": "Auto by Template",
    "description": "根据当前模板的平台自动选择 Citation 样本。Reddit 模板优先 Reddit URLs；官网模板优先高引用的官网、评测、榜单、对比和教程页面。"
  }'::jsonb,
  10,
  true
),
(
  'citation_source_scope',
  'content_generation',
  'reddit_citations',
  '{
    "label": "Reddit Citations",
    "description": "优先分析被 AI 引用的 Reddit 页面，用于学习 AI 更容易引用的 Reddit 讨论结构、证据密度和表达方式。"
  }'::jsonb,
  20,
  true
),
(
  'citation_source_scope',
  'content_generation',
  'official_article_citations',
  '{
    "label": "Official / Article Citations",
    "description": "优先分析被 AI 引用的官网、产品页、博客、评测、榜单、教程和对比文章，用于优化官网内容的可抽取性。"
  }'::jsonb,
  30,
  true
),
(
  'citation_source_scope',
  'content_generation',
  'all_prompt_citations',
  '{
    "label": "All Prompt Citations",
    "description": "分析当前 Prompt / Topic 下所有高引用页面，并在分析阶段按平台、域名、品牌提及状态和内容动作分类。"
  }'::jsonb,
  40,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES
(
  'citation_brand_mention_policy',
  'content_generation',
  'triage_all',
  '{
    "label": "Triage All Brand States",
    "description": "同时识别未提及、正面/中立提及、负面/错误提及，并据此决定新写、放大、修正或补充。"
  }'::jsonb,
  10,
  true
),
(
  'citation_brand_mention_policy',
  'content_generation',
  'prioritize_unmentioned',
  '{
    "label": "Prioritize Unmentioned",
    "description": "优先学习未提及客户品牌但被 AI 高频引用的页面，作为新内容的写法样本和品牌切入机会。"
  }'::jsonb,
  20,
  true
),
(
  'citation_brand_mention_policy',
  'content_generation',
  'amplify_positive_neutral',
  '{
    "label": "Amplify Positive / Neutral Mentions",
    "description": "优先利用已经正面或中立提及客户品牌的 Citation asset，做相邻 Prompt、内链、官网补充页或三方内容放大。"
  }'::jsonb,
  30,
  true
),
(
  'citation_brand_mention_policy',
  'content_generation',
  'clarify_negative_misleading',
  '{
    "label": "Clarify Negative / Misleading Mentions",
    "description": "优先识别负面、过时或潜在误导的品牌提及，生成 clarification、rebuttal、comparison 或 troubleshooting 类型内容。"
  }'::jsonb,
  40,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES
(
  'citation_action_strategy',
  'content_generation',
  'auto',
  '{
    "label": "Auto Decide",
    "description": "由 Brand Mention Triage 自动决定内容动作：新写、刷新、补充、澄清、对比或内链。"
  }'::jsonb,
  10,
  true
),
(
  'citation_action_strategy',
  'content_generation',
  'new_content_gap',
  '{
    "label": "New Content Gap",
    "description": "当高引用页面未提及客户品牌时，生成新内容补足品牌切入和答案证据。"
  }'::jsonb,
  20,
  true
),
(
  'citation_action_strategy',
  'content_generation',
  'refresh_extractability',
  '{
    "label": "Refresh Extractability",
    "description": "当已有内容或已有正面/中立提及存在但可抽取性弱时，优先重构、刷新或补充结构。"
  }'::jsonb,
  30,
  true
),
(
  'citation_action_strategy',
  'content_generation',
  'clarification_rebuttal',
  '{
    "label": "Clarification / Rebuttal",
    "description": "当 Citation 中存在负面、过时或误导信息时，生成澄清、反驳、对比或故障排查型内容。"
  }'::jsonb,
  40,
  true
),
(
  'citation_action_strategy',
  'content_generation',
  'internal_linking',
  '{
    "label": "Internal Linking / Support Page",
    "description": "当品牌已有 Citation asset 时，优先规划官网补充页、FAQ、术语页、对比页和内部链接。"
  }'::jsonb,
  50,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

-- ---------------------------------------------------------------------------
-- 2) Workflow step: Citation Analysis
-- ---------------------------------------------------------------------------
-- Uses only existing primitive/ref field types. A richer custom UI can replace
-- this later without changing the template contract.

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES (
  'workflow_step',
  'content_generation',
  'citation_analysis',
  '{
    "num": 2.7,
    "label": "Citation Analysis",
    "default_enabled": false,
    "description": "基于 Citation data 选择 AI 已经愿意引用的页面，进行 Brand Mention Triage、Content Action Decision 和 Citation-grounded Brief 生成。",
    "fields": [
      {
        "key": "citation_source_scope",
        "type": "single_ref",
        "label": "Citation Source Scope",
        "ref_config_type": "citation_source_scope",
        "ref_scope": "content_generation",
        "required": true,
        "description": "选择本次 Citation Analysis 要参考的来源范围。"
      },
      {
        "key": "citation_brand_mention_policy",
        "type": "single_ref",
        "label": "Brand Mention Triage Policy",
        "ref_config_type": "citation_brand_mention_policy",
        "ref_scope": "content_generation",
        "required": true,
        "description": "配置如何处理未提及、正面/中立提及、负面/错误提及客户品牌的 Citation 页面。"
      },
      {
        "key": "citation_action_strategy",
        "type": "single_ref",
        "label": "Content Action Decision",
        "ref_config_type": "citation_action_strategy",
        "ref_scope": "content_generation",
        "required": true,
        "description": "配置 Citation Analysis 后优先采取的内容动作。"
      },
      {
        "key": "citation_max_sources",
        "type": "number",
        "label": "Max Citation Pages",
        "description": "最多分析多少个 Citation 页面。建议 8-12，避免上下文过载。"
      },
      {
        "key": "citation_fetch_full_pages",
        "type": "boolean",
        "label": "Fetch Full Web Pages",
        "description": "开启后抓取 Citation URL 正文进行 P1 网页分析；关闭时仅使用数据库中的 URL、域名、引用次数和上下文片段。"
      },
      {
        "key": "citation_include_domains",
        "type": "text",
        "label": "Include Domains",
        "description": "可选。逗号分隔域名白名单，例如 reddit.com, youtube.com。留空则按模板自动选择。"
      },
      {
        "key": "citation_exclude_domains",
        "type": "text",
        "label": "Exclude Domains",
        "description": "可选。逗号分隔域名黑名单，例如 youtube.com, instagram.com。"
      },
      {
        "key": "citation_query_override",
        "type": "textarea",
        "label": "Citation Query Override",
        "description": "可选。手动指定要用于 Citation 检索的 Prompt / Topic / Query 关键词；留空则使用用户选中的 Prompt 和 Topic。"
      }
    ]
  }'::jsonb,
  27,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

-- ---------------------------------------------------------------------------
-- 3) Default citation_analysis config for every existing content template
-- ---------------------------------------------------------------------------

WITH default_cfg AS (
  SELECT
    '{
      "version": 1,
      "enabled": false,
      "mode": "citation_analysis_then_generate",
      "source_of_truth_priority": ["selected_prompt", "citation_data", "template_playbook", "discover_context", "product_facts", "search_grounding"],
      "source_selection": {
        "source_scope": "auto_by_template",
        "max_sources": 10,
        "min_citations": 1,
        "use_selected_prompt_or_topic": true,
        "fetch_full_pages": true,
        "dedupe_by_canonical_url": true,
        "prefer_recent_when_available": true
      },
      "brand_mention_triage": {
        "layer_1_rule_matching": true,
        "layer_2_llm_semantic_judgment": true,
        "layer_3_aggregate_strategy": true,
        "skip_llm_when": [
          "No page text is available and URL/title/domain already clearly indicate no brand mention.",
          "Exact brand alias match is present in title or extracted text and sentiment is not requested.",
          "The source is unreachable and database metadata is too thin for semantic judgment."
        ],
        "require_llm_when": [
          "Brand mention is ambiguous, misspelled, translated, abbreviated, or appears through a product name.",
          "The page may contain negative, outdated, incomplete, or misleading brand information.",
          "The page compares competitors and the customer brand may be absent from a relevant shortlist."
        ],
        "llm_output_schema": {
          "brand_mentioned": "boolean",
          "mention_state": "unmentioned | positive_neutral | negative_misleading | ambiguous",
          "evidence": ["short quoted or paraphrased evidence snippet"],
          "content_risk": "low | medium | high",
          "recommended_action": "new_content_gap | refresh_extractability | clarification_rebuttal | internal_linking | third_party_nurture"
        }
      },
      "content_action_decision": {
        "unmentioned": "Learn the citation page structure and generate a brand-relevant gap-filling article/post.",
        "positive_neutral": "Treat as a citation asset; amplify through adjacent prompts, internal linking, support pages, or third-party nurture.",
        "negative_misleading": "Do not imitate; generate clarification, comparison, rebuttal, troubleshooting, or evidence-correcting content.",
        "ambiguous": "Use conservative wording and route to human review when evidence is insufficient."
      },
      "citation_grounded_brief": {
        "show_to_user": true,
        "display_mode": "aggregate_summary",
        "include_sections": [
          "Citation Source Mix",
          "Brand Mention Triage",
          "Content Action Decision",
          "Patterns AI Already Cites",
          "Risks and Non-Claims",
          "Writing Constraints"
        ],
        "do_not_show_full_page_level_analysis_by_default": true
      }
    }'::jsonb AS top_level,
    '{
      "enabled": false,
      "citation_source_scope": "auto_by_template",
      "citation_brand_mention_policy": "triage_all",
      "citation_action_strategy": "auto",
      "citation_max_sources": 10,
      "citation_fetch_full_pages": true,
      "citation_include_domains": "",
      "citation_exclude_domains": "",
      "citation_query_override": ""
    }'::jsonb AS step_defaults
)
UPDATE geo_report_templates AS t
SET wizard_config =
  COALESCE(t.wizard_config, '{}'::jsonb)
  || jsonb_build_object(
    'citation_analysis',
    (COALESCE(t.wizard_config->'citation_analysis', '{}'::jsonb) || default_cfg.top_level),
    'steps',
    (
      COALESCE(t.wizard_config->'steps', '{}'::jsonb)
      || jsonb_build_object(
        'citation_analysis',
        (COALESCE(t.wizard_config#>'{steps,citation_analysis}', '{}'::jsonb) || default_cfg.step_defaults)
      )
    )
  )
FROM default_cfg
WHERE t.task_type = 'content_generation';

-- ---------------------------------------------------------------------------
-- 4) Insert new templates by cloning mature template baselines
-- ---------------------------------------------------------------------------

INSERT INTO geo_report_templates (
  id, name, description, icon, data_domains, default_prompt,
  is_builtin, is_active, sort_order, task_type, defaults, wizard_config
)
SELECT
  gen_random_uuid(),
  'Reddit AI Citable Post Generator',
  '基于 Citation data + Reddit insight 生成更容易被 AI 引用、同时保持 Reddit 社区原生感的经验帖',
  '🧭',
  ARRAY['visibility', 'citation', 'sentiment']::text[],
  base.default_prompt,
  true,
  true,
  9,
  'content_generation',
  base.defaults,
  base.wizard_config
FROM geo_report_templates AS base
WHERE base.task_type = 'content_generation'
  AND base.name = 'Reddit Insight then Generate'
  AND NOT EXISTS (
    SELECT 1 FROM geo_report_templates
    WHERE task_type = 'content_generation'
      AND name = 'Reddit AI Citable Post Generator'
  );

INSERT INTO geo_report_templates (
  id, name, description, icon, data_domains, default_prompt,
  is_builtin, is_active, sort_order, task_type, defaults, wizard_config
)
SELECT
  gen_random_uuid(),
  'Official Website AI Citable Article',
  '基于 Citation data + 官网内容 insight 生成更容易被 AI 引用和抽取的官网 SEO/AEO 长文',
  '🔗',
  ARRAY['visibility', 'citation', 'sentiment']::text[],
  base.default_prompt,
  true,
  true,
  10,
  'content_generation',
  base.defaults,
  base.wizard_config
FROM geo_report_templates AS base
WHERE base.task_type = 'content_generation'
  AND base.name = 'Official Website Insight then Generate'
  AND NOT EXISTS (
    SELECT 1 FROM geo_report_templates
    WHERE task_type = 'content_generation'
      AND name = 'Official Website AI Citable Article'
  );

-- ---------------------------------------------------------------------------
-- 5) Specialize the Reddit AI-citable template
-- ---------------------------------------------------------------------------

WITH reddit_cfg AS (
  SELECT
    '{
      "version": 1,
      "enabled": true,
      "mode": "reddit_citation_analysis_then_generate",
      "platform": "reddit",
      "source_selection": {
        "source_scope": "reddit_citations",
        "required_domain_patterns": ["reddit.com"],
        "max_sources": 12,
        "min_citations": 1,
        "fetch_full_pages": true,
        "prefer_unmentioned_brand_pages_for_style_learning": true
      },
      "writing_policy": {
        "citation_is_source_of_truth_not_voice_replacement": true,
        "retain_reddit_platform_fit": true,
        "must_not_be_hard_sell": true,
        "must_include_personal_pov_or_field_notes": true,
        "must_include_one_debatable_tradeoff": true,
        "brand_insertion": "one natural Brand Fit Summary / Where the brand fits block, plus only necessary mentions elsewhere"
      }
    }'::jsonb AS top_level_patch,
    '{
      "enabled": true,
      "citation_source_scope": "reddit_citations",
      "citation_brand_mention_policy": "triage_all",
      "citation_action_strategy": "auto",
      "citation_max_sources": 12,
      "citation_fetch_full_pages": true,
      "citation_include_domains": "reddit.com",
      "citation_exclude_domains": "",
      "citation_query_override": ""
    }'::jsonb AS step_patch,
    '[
      "Use Citation Analysis to learn which Reddit pages AI already cites for the selected Prompt / Topic.",
      "Prefer unmentioned-brand Reddit citations as style-learning samples: structure, evidence density, objection framing, comment-worthy tension, and answer extractability.",
      "If a cited Reddit page already mentions the customer brand positively or neutrally, treat it as a citation asset and look for adjacent prompts, internal support content, or third-party nurture angles rather than duplicating the same post.",
      "If a cited Reddit page mentions the customer brand negatively, incorrectly, or incompletely, do not imitate it. Generate a clarification, comparison, troubleshooting, or evidence-correcting Reddit-native post.",
      "Citation style must not override Reddit fit: keep personal POV, practical tradeoffs, non-promotional brand mention, one clear debate question, conservative claims, and no fake benchmark posture."
    ]'::jsonb AS playbook_rules,
    'Use Citation Analysis as an additional source of truth. The final Reddit post must remain community-native: no hard-sell, no SEO guide tone, no fake hands-on testing, no unsupported benchmark claims. Learn from high-citation Reddit source patterns, but write a new post centered on the selected Prompt and the user/company context.' AS generation_requirement,
    '{
      "enabled": true,
      "min_overall_score": 8,
      "revise_below_score": true,
      "citation_alignment_as_blocker": true,
      "citation_alignment_review_mode": "hybrid",
      "citation_alignment_markers": {
        "new_content_gap": ["brand fit", "use case", "workflow", "citation gap", "missing coverage"],
        "refresh_extractability": ["brand fit", "feature", "benefit", "faq", "internal link", "extractability"],
        "clarification_rebuttal": ["clarification", "correct", "misleading", "comparison", "troubleshooting"]
      },
      "max_revise_attempts": 1,
      "blocker_score_cap": 6,
      "warning_score_cap": 8,
      "llm_issue_blocker_patterns": ["重复结尾", "重复 FAQ", "残缺", "未完成句", "结构性错误", "duplicate ending", "duplicate FAQ", "unfinished sentence", "structural error"],
      "revise_on_warning_rule_ids": ["multiple_faq_sections", "duplicate_h2_heading"],
      "rules": [
        {"id": "single_tldr", "type": "max_occurrences", "severity": "blocker", "pattern": "TL;DR", "max": 1},
        {"id": "fake_benchmark", "type": "forbidden_patterns", "severity": "blocker", "patterns": ["I spent \\\\d+ days testing", "master spreadsheet", "tested every major"]},
        {"id": "multiple_faq_sections", "type": "max_heading_occurrences", "severity": "warning", "heading_patterns": ["FAQ", "Frequently Asked Questions"], "max": 1},
        {"id": "duplicate_h2_heading", "type": "duplicate_heading", "level": 2, "severity": "warning"}
      ]
    }'::jsonb AS quality_gate_patch
)
UPDATE geo_report_templates AS t
SET
  description = '基于 Citation data + Reddit insight 生成更容易被 AI 引用、同时保持 Reddit 社区原生感的经验帖',
  default_prompt = 'Use Reddit Citation Analysis and Reddit insight to identify a concrete community pain point and the patterns AI already cites. Then write a Reddit-native experience post that is useful, debatable, conservative, and brand-aware without becoming promotional. Include exactly one short Brand Fit Summary / Where the brand fits section and keep the customer brand as one practical option inside the tradeoff.',
  defaults = COALESCE(t.defaults, '{}'::jsonb) || '{
    "goal": "citation_optimize",
    "content_type": "reddit_article",
    "count": 1,
    "depth": "authority",
    "platforms": ["chatgpt", "gemini", "aimode"],
    "publish_platform": "reddit",
    "template_group": "citation_then_generate",
    "platform_profile": "reddit"
  }'::jsonb,
  wizard_config =
    COALESCE(t.wizard_config, '{}'::jsonb)
    || jsonb_build_object(
      'template_group', 'citation_then_generate',
      'platform_profile', 'reddit',
      'citation_analysis', (COALESCE(t.wizard_config->'citation_analysis', '{}'::jsonb) || reddit_cfg.top_level_patch),
      'quality_gate', (COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || reddit_cfg.quality_gate_patch),
      'platform_playbook', (
        COALESCE(t.wizard_config->'platform_playbook', '{}'::jsonb)
        || jsonb_build_object('citation_analysis_rules', reddit_cfg.playbook_rules)
      ),
      'generation_requirements', (
        COALESCE(t.wizard_config->'generation_requirements', '{}'::jsonb)
        || jsonb_build_object('citation_grounding', reddit_cfg.generation_requirement)
      ),
      'steps', (
        COALESCE(t.wizard_config->'steps', '{}'::jsonb)
        || jsonb_build_object(
          'mode_gate',
          (COALESCE(t.wizard_config#>'{steps,mode_gate}', '{}'::jsonb) || '{"enabled": true, "default_mode_choice": "ai_discover"}'::jsonb),
          'citation_analysis',
          (COALESCE(t.wizard_config#>'{steps,citation_analysis}', '{}'::jsonb) || reddit_cfg.step_patch),
          'reddit_discovery',
          (COALESCE(t.wizard_config#>'{steps,reddit_discovery}', '{}'::jsonb) || '{"enabled": true}'::jsonb),
          'official_website_discovery',
          (COALESCE(t.wizard_config#>'{steps,official_website_discovery}', '{}'::jsonb) || '{"enabled": false}'::jsonb)
        )
      )
    ),
  is_builtin = true,
  is_active = true,
  sort_order = 9
FROM reddit_cfg
WHERE t.task_type = 'content_generation'
  AND t.name = 'Reddit AI Citable Post Generator';

-- ---------------------------------------------------------------------------
-- 6) Specialize the Official Website AI-citable template
-- ---------------------------------------------------------------------------

WITH official_cfg AS (
  SELECT
    '{
      "version": 1,
      "enabled": true,
      "mode": "official_website_citation_optimization_then_generate",
      "platform": "official_website",
      "source_selection": {
        "source_scope": "official_article_citations",
        "preferred_source_categories": ["owned_media", "earned_media", "agency", "other"],
        "preferred_page_types": ["official_page", "blog_article", "review", "comparison", "best_tools_list", "how_to_guide", "faq"],
        "max_sources": 12,
        "min_citations": 1,
        "fetch_full_pages": true,
        "avoid_social_threads_as_primary_style_source": true
      },
      "writing_policy": {
        "citation_is_source_of_truth_not_brand_claim_license": true,
        "optimize_for_brand_extractability": true,
        "must_include_brand_fit_summary": true,
        "must_include_feature_to_benefit_mapping": true,
        "must_include_internal_linking_suggestions": true,
        "must_include_value_dream_mini_benefits": true,
        "must_avoid_unsupported_superlatives": true
      }
    }'::jsonb AS top_level_patch,
    '{
      "enabled": true,
      "citation_source_scope": "official_article_citations",
      "citation_brand_mention_policy": "triage_all",
      "citation_action_strategy": "auto",
      "citation_max_sources": 12,
      "citation_fetch_full_pages": true,
      "citation_include_domains": "",
      "citation_exclude_domains": "youtube.com, instagram.com, tiktok.com",
      "citation_query_override": ""
    }'::jsonb AS step_patch,
    '[
      "Use Citation Analysis to identify high-citation pages that AI already trusts for the selected Prompt / Topic.",
      "For pages that do not mention the customer brand, learn their extractable structure: direct answer, comparison criteria, use-case framing, feature-benefit mapping, FAQ shape, definitions, tables, and source clarity. Then add a relevant customer-brand angle.",
      "For pages that mention the customer brand positively or neutrally, treat them as citation assets. Prefer refresh, internal linking, adjacent prompt coverage, support pages, and third-party nurture rather than duplicating the same theme.",
      "For pages that mention the customer brand negatively, incorrectly, or incompletely, generate clarification, comparison, rebuttal, troubleshooting, or evidence-correcting content with conservative claims.",
      "Official website output must be brand-extractable and commercially useful: Brand Fit Summary, Value / Dream / Mini-benefits, Feature-to-Benefit Mapping table, Internal Linking Suggestions, FAQ, and cautious evidence language."
    ]'::jsonb AS playbook_rules,
    'Use Citation Analysis as a first-class source of truth for article structure, extractability, and content gaps. The final official website article must still center on the selected Prompt and verified brand/product facts. Do not copy cited pages, do not overstate competitor weaknesses, and do not invent product features, pricing, benchmark numbers, platform algorithm facts, or customer outcomes.' AS generation_requirement,
    '{
      "enabled": true,
      "min_overall_score": 8,
      "revise_below_score": true,
      "citation_alignment_as_blocker": true,
      "citation_alignment_review_mode": "hybrid",
      "citation_alignment_markers": {
        "new_content_gap": ["brand fit", "use case", "workflow", "citation gap", "missing coverage"],
        "refresh_extractability": ["brand fit", "feature", "benefit", "faq", "internal link", "extractability"],
        "clarification_rebuttal": ["clarification", "correct", "misleading", "comparison", "troubleshooting"]
      },
      "max_revise_attempts": 1,
      "blocker_score_cap": 6,
      "warning_score_cap": 8,
      "llm_issue_blocker_patterns": ["重复结尾", "重复 FAQ", "残缺", "未完成句", "结构性错误", "duplicate ending", "duplicate FAQ", "unfinished sentence", "structural error"],
      "revise_on_warning_rule_ids": ["multiple_faq_sections", "duplicate_h2_heading", "final_thoughts_and_conclusion", "duplicate_direct_answer"],
      "rules": [
        {"id": "brand_fit_summary", "type": "required_heading", "severity": "blocker", "any_of": ["Brand Fit Summary", "Where Dreamina Fits", "Where the Brand Fits"]},
        {"id": "feature_to_benefit_mapping", "type": "required_table", "severity": "blocker", "near_heading_any_of": ["Feature-to-Benefit Mapping", "Feature to Benefit Mapping"]},
        {"id": "internal_linking_suggestions", "type": "required_heading", "severity": "blocker", "any_of": ["Internal Linking Suggestions", "Suggested Internal Links"]},
        {"id": "value_dream_mini_benefits", "type": "required_heading", "severity": "blocker", "any_of": ["Value, Dream, Mini-benefits", "Value / Dream / Mini-benefits", "Value Dream Mini-benefits"]},
        {"id": "unsupported_hype_terms", "type": "forbidden_terms", "severity": "warning", "terms": ["definitive", "guarantee", "guarantees", "viral-ready", "ultimate", "unparalleled"]},
        {"id": "multiple_faq_sections", "type": "max_heading_occurrences", "severity": "warning", "heading_patterns": ["FAQ", "Frequently Asked Questions"], "max": 1},
        {"id": "duplicate_h2_heading", "type": "duplicate_heading", "level": 2, "severity": "warning"},
        {"id": "final_thoughts_and_conclusion", "type": "cooccurring_headings", "severity": "warning", "heading_patterns": ["Final thoughts", "Conclusion"]},
        {"id": "duplicate_direct_answer", "type": "max_heading_occurrences", "severity": "warning", "heading_patterns": ["Direct Answer"], "max": 1}
      ]
    }'::jsonb AS quality_gate_patch
)
UPDATE geo_report_templates AS t
SET
  description = '基于 Citation data + 官网内容 insight 生成更容易被 AI 引用和抽取的官网 SEO/AEO 长文',
  default_prompt = 'Use Citation Analysis and Official Website Discover insights to generate an official website SEO/AEO article that improves AI citation readiness. The article should be prompt-first, brand-extractable, commercially useful, evidence-conservative, and structured with Brand Fit Summary, Value / Dream / Mini-benefits, Feature-to-Benefit Mapping, Internal Linking Suggestions, FAQ, and clear conversion-oriented next steps.',
  defaults = COALESCE(t.defaults, '{}'::jsonb) || '{
    "goal": "citation_optimize",
    "content_type": "official_website_article",
    "count": 1,
    "depth": "authority",
    "platforms": ["chatgpt", "gemini", "aimode"],
    "publish_platform": "official_site",
    "template_group": "citation_then_generate",
    "platform_profile": "official_website"
  }'::jsonb,
  wizard_config =
    COALESCE(t.wizard_config, '{}'::jsonb)
    || jsonb_build_object(
      'template_group', 'citation_then_generate',
      'platform_profile', 'official_website',
      'citation_analysis', (COALESCE(t.wizard_config->'citation_analysis', '{}'::jsonb) || official_cfg.top_level_patch),
      'quality_gate', (COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || official_cfg.quality_gate_patch),
      'platform_playbook', (
        COALESCE(t.wizard_config->'platform_playbook', '{}'::jsonb)
        || jsonb_build_object('citation_analysis_rules', official_cfg.playbook_rules)
      ),
      'generation_requirements', (
        COALESCE(t.wizard_config->'generation_requirements', '{}'::jsonb)
        || jsonb_build_object('citation_grounding', official_cfg.generation_requirement)
      ),
      'steps', (
        COALESCE(t.wizard_config->'steps', '{}'::jsonb)
        || jsonb_build_object(
          'mode_gate',
          (COALESCE(t.wizard_config#>'{steps,mode_gate}', '{}'::jsonb) || '{"enabled": true, "default_mode_choice": "ai_discover"}'::jsonb),
          'citation_analysis',
          (COALESCE(t.wizard_config#>'{steps,citation_analysis}', '{}'::jsonb) || official_cfg.step_patch),
          'reddit_discovery',
          (COALESCE(t.wizard_config#>'{steps,reddit_discovery}', '{}'::jsonb) || '{"enabled": false}'::jsonb),
          'official_website_discovery',
          (COALESCE(t.wizard_config#>'{steps,official_website_discovery}', '{}'::jsonb) || '{"enabled": true}'::jsonb)
        )
      )
    ),
  is_builtin = true,
  is_active = true,
  sort_order = 10
FROM official_cfg
WHERE t.task_type = 'content_generation'
  AND t.name = 'Official Website AI Citable Article';

COMMIT;

-- Verification:
-- SELECT sort_order,
--        name,
--        wizard_config->>'template_group' AS template_group,
--        wizard_config->>'platform_profile' AS platform_profile,
--        wizard_config#>>'{steps,citation_analysis,enabled}' AS citation_step_enabled,
--        wizard_config#>>'{citation_analysis,enabled}' AS citation_top_enabled,
--        wizard_config#>>'{steps,reddit_discovery,enabled}' AS reddit_discover_enabled,
--        wizard_config#>>'{steps,official_website_discovery,enabled}' AS official_discover_enabled
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
-- ORDER BY sort_order, name;
--
-- SELECT key, value
-- FROM geo_workflow_config
-- WHERE scope = 'content_generation'
--   AND config_type = 'workflow_step'
--   AND key = 'citation_analysis';
