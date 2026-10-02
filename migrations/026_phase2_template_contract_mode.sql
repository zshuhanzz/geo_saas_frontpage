-- =============================================================
-- Migration 026: Phase 2 — Template × Wizard 2D Config + Content Contract Parity
-- Run: psql $DATABASE_URL -f migrations/026_phase2_template_contract_mode.sql
-- =============================================================
-- This migration is the single atomic unit for Phase 2 of the 2026-04-11 roadmap.
-- See: docs/roadmap_20260411.md § 3 (Phase 2)
--
-- Summary of changes:
--   1. Clear history geo_agent_tasks (no data to preserve, per user confirmation)
--   2. Recreate geo_analysis_metrics with improved schema (no sql_override, with
--      relevant_tables + null_behavior + sample_question)
--   3. Seed 10 initial analysis metrics covering visibility/citation/sentiment
--   4. Add wizard_config JSONB column to geo_report_templates
--   5. Rename + reconfigure 5 analysis templates (drop 1: 优化机会发现)
--   6. Update 6 content templates with wizard_config contracts
--   7. Clean up workflow_config: drop recommended_chart rows, drop RAFT analysis
--      snippets, drop analysis goal rows, add 3 new analysis methodology snippets
-- =============================================================

BEGIN;

-- =============================================================
-- STEP 1: Clear historical geo_agent_tasks
-- =============================================================
-- User confirmed the table only contains 'analysis' and 'content_generation'
-- task types. Historical data has no preservation value.
--
-- NOTE: We use DELETE instead of TRUNCATE because `geo_content_assets.content_task_id`
-- holds a FK `REFERENCES geo_agent_tasks(id) ON DELETE SET NULL` (see migration 023).
-- PostgreSQL rejects TRUNCATE on any table referenced by an FK, even when the referencing
-- side is `ON DELETE SET NULL`. DELETE respects the cascade rule — child rows in
-- geo_content_assets are preserved with their content_task_id set to NULL.

DELETE FROM geo_agent_tasks;


-- =============================================================
-- STEP 2: Recreate geo_analysis_metrics
-- =============================================================
-- Previously dropped in migration 018 when pipeline switched to dynamic
-- discovery. We are reintroducing it in contract mode, with agent-friendly
-- metadata instead of hardcoded SQL.

DROP TABLE IF EXISTS geo_analysis_metrics CASCADE;

CREATE TABLE geo_analysis_metrics (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    metric_name      TEXT NOT NULL UNIQUE,
    display_name_zh  TEXT NOT NULL,
    display_name_en  TEXT,
    domain           TEXT NOT NULL CHECK (domain IN ('visibility','citation','sentiment','custom')),
    description      TEXT NOT NULL,
    calculation_hint TEXT NOT NULL,
    relevant_tables  TEXT[] NOT NULL DEFAULT '{}',
    sample_question  TEXT,
    null_behavior    TEXT NOT NULL DEFAULT 'return_null'
                     CHECK (null_behavior IN ('return_null','return_zero','raise')),
    unit             TEXT,
    is_active        BOOLEAN DEFAULT true,
    sort_order       INTEGER DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_geo_analysis_metrics_domain
    ON geo_analysis_metrics (domain);
CREATE INDEX idx_geo_analysis_metrics_active
    ON geo_analysis_metrics (is_active);


-- =============================================================
-- STEP 3: Seed 10 initial analysis metrics
-- =============================================================
-- These cover the required_metrics needs of all 5 analysis templates
-- and the content templates' grounding needs.
--
-- NOTE: relevant_tables values are my best guess from repo schema
-- reading. Before running, verify against actual schema.sql and adjust
-- the list. This is only a hint for the Agent's NL2SQL step; it will
-- still introspect live schema.

INSERT INTO geo_analysis_metrics
    (metric_name, display_name_zh, display_name_en, domain, description,
     calculation_hint, relevant_tables, sample_question, null_behavior, unit, sort_order)
VALUES
  ('sov_trend',
   'Share of Voice 趋势', 'Share of Voice Trend', 'visibility',
   '自有品牌 mention 数占 (自有品牌 + 所有 peers) mention 数的比例，按时间序列展开',
   '把 geo_company_mentions 和 geo_results 按 result_id + client_id join，按 DATE(executed_at) 分组；分子 = is_own_brand=true 的 mention 次数，分母 = is_own_brand=true 或 brand_name ∈ peers 的 mention 次数',
   ARRAY['geo_company_mentions','geo_results','geo_client_peers'],
   '过去 30 天内，每一天我方品牌的 mention 占所有被追踪品牌 mention 总量的比例是多少？',
   'return_zero', '%', 1),

  ('visibility_rank_vs_peers',
   '可见度排名 (vs 竞品)', 'Visibility Rank vs Peers', 'visibility',
   '自有品牌在 peer 列表中的 mention count 排名；若客户未配置 peers 则返回 null',
   '从 geo_company_mentions 拉取 is_own_brand=true 和 brand_name ∈ (SELECT peer_brand FROM geo_client_peers WHERE client_id=$1) 的行，按 brand_name 聚合计数，按数量 DESC 排名，返回自有品牌名次和总参与品牌数',
   ARRAY['geo_company_mentions','geo_client_peers'],
   '在自有品牌 + 已配置的 peer 品牌中，按 mention count 排名，自有品牌是第几名？',
   'return_null', NULL, 2),

  ('prompt_coverage_rate',
   'Prompt 覆盖率', 'Prompt Coverage Rate', 'visibility',
   '自有品牌出现过至少一次 mention 的 prompt 占所有监控 prompt 的比例',
   '分母 = SELECT COUNT(*) FROM geo_client_prompts WHERE client_id=$1；分子 = 通过 geo_results.prompt_id 关联 geo_company_mentions 且 is_own_brand=true 的 distinct prompt_id 数量',
   ARRAY['geo_client_prompts','geo_company_mentions','geo_results'],
   '我方品牌在多少比例的监控 prompt 里被至少提到过一次？',
   'return_zero', '%', 3),

  ('platform_visibility_breakdown',
   '各平台可见度分布', 'Platform Visibility Breakdown', 'visibility',
   '按 AI 平台 (chatgpt/gemini/aimode) 分组统计自有品牌 mention 次数',
   '把 geo_company_mentions 和 geo_results 按 result_id + client_id join，按 geo_results.platform 分组，统计 is_own_brand=true 的 mention 次数',
   ARRAY['geo_company_mentions','geo_results'],
   '自有品牌在 chatgpt / gemini / aimode 三个平台上分别被提到多少次？',
   'return_zero', 'count', 4),

  ('peer_citation_share',
   '竞品引用份额', 'Peer Citation Share', 'citation',
   '各竞品被作为 citation 来源的次数，以及占所有被追踪品牌 citation 总数的比例',
   '从 geo_citations 关联 geo_results 取到品牌引用数据，按 brand_name 分组计数，计算每个竞品和自有品牌的引用次数占比',
   ARRAY['geo_citations','geo_results','geo_client_peers'],
   '在被引用为推荐来源的场景里，每个竞品各被引用了多少次、占比多少？',
   'return_zero', '%', 5),

  ('citation_source_diversity',
   '引用来源多样性', 'Citation Source Diversity', 'citation',
   '自有品牌被引用时来源 domain 的去重数量和集中度 (HHI)',
   '从 geo_citations 抽取引用自有品牌的行，join geo_client_domains / geo_domain_categories 得到 source domain 分类，计算 distinct count 和 Herfindahl 集中度',
   ARRAY['geo_citations','geo_client_domains','geo_domain_categories'],
   '我方品牌被引用时，源域名有多少种？是集中在少数几个域名还是分布广泛？',
   'return_zero', NULL, 6),

  ('sentiment_distribution',
   '情感分布', 'Sentiment Distribution', 'sentiment',
   '自有品牌被提及时 positive / neutral / negative 的比例',
   '从 geo_sentiment_results 按 sentiment 字段分组统计，与 geo_company_mentions 关联过滤 is_own_brand=true，计算各类情感的占比',
   ARRAY['geo_sentiment_results','geo_company_mentions','geo_results'],
   '我方品牌被提到时，正面 / 中性 / 负面的比例各是多少？',
   'return_zero', '%', 7),

  ('sentiment_trend',
   '情感趋势', 'Sentiment Trend', 'sentiment',
   '自有品牌情感评分随时间的变化',
   '按 DATE(executed_at) 分组计算 geo_sentiment_results 中自有品牌的 positive/neutral/negative 占比或平均 confidence，返回时间序列',
   ARRAY['geo_sentiment_results','geo_results','geo_company_mentions'],
   '过去 30 天内，我方品牌的情感走势是变好还是变差？',
   'return_zero', NULL, 8),

  ('top_positive_themes',
   'Top 正面主题', 'Top Positive Themes', 'sentiment',
   '自有品牌正面提及中出现频率最高的 Top N 主题',
   '从 geo_sentiment_themes 过滤 sentiment=positive 且关联自有品牌的行，按 theme_name 分组计数，取 Top 10；theme 规范化用 geo_sentiment_theme_dictionary',
   ARRAY['geo_sentiment_themes','geo_sentiment_theme_dictionary','geo_company_mentions'],
   '我方品牌的正面提及都集中在哪些主题？',
   'return_null', NULL, 9),

  ('top_negative_themes',
   'Top 负面主题', 'Top Negative Themes', 'sentiment',
   '自有品牌负面提及中出现频率最高的 Top N 主题',
   '从 geo_sentiment_themes 过滤 sentiment=negative 且关联自有品牌的行，按 theme_name 分组计数，取 Top 10；theme 规范化用 geo_sentiment_theme_dictionary',
   ARRAY['geo_sentiment_themes','geo_sentiment_theme_dictionary','geo_company_mentions'],
   '我方品牌的负面提及都集中在哪些主题？',
   'return_null', NULL, 10);


-- =============================================================
-- STEP 4: Add wizard_config column to geo_report_templates
-- =============================================================

ALTER TABLE geo_report_templates
    ADD COLUMN IF NOT EXISTS wizard_config JSONB NOT NULL DEFAULT '{}'::jsonb;


-- =============================================================
-- STEP 5: Delete deprecated template (优化机会发现)
-- =============================================================

DELETE FROM geo_report_templates
WHERE id = '67c3d34a-8776-42aa-90d9-62067727b5e0';


-- =============================================================
-- STEP 6: Rename + reconfigure 5 analysis templates
-- =============================================================
-- Keep UUIDs stable (UPDATE by id), only change name/description and
-- load the wizard_config contract.

-- 6.1 — 竞品对标分析
UPDATE geo_report_templates SET
    name = '竞品对标分析',
    description = '对比自有品牌与竞品在 AI 搜索引擎中的可见度和引用表现差异',
    icon = '🎯',
    data_domains = ARRAY['visibility','citation']::text[],
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'analysis_goal',   jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY['competitor_sov','competitor_advantage']),
            'data_selection',  jsonb_build_object('enabled', true, 'default_domains', ARRAY['visibility','citation'], 'default_date_range', 'last_30d'),
            'chart_config',    jsonb_build_object('enabled', true, 'default_charts', jsonb_build_array(
                jsonb_build_object('nl_query', '各品牌在所有 AI 平台的总提及次数对比', 'chart_type', 'bar'),
                jsonb_build_object('nl_query', '自有品牌 vs 竞品的 SOV 趋势对比', 'chart_type', 'line')
            )),
            'prompt_edit',     jsonb_build_object('enabled', true),
            'confirm_execute', jsonb_build_object('enabled', true)
        ),
        'required_metrics', jsonb_build_array('sov_trend','visibility_rank_vs_peers','peer_citation_share','platform_visibility_breakdown'),
        'required_chapters', jsonb_build_array('visibility','citation')
    ),
    updated_at = NOW()
WHERE id = '5388ed34-dfa1-4616-895a-84c40d19c882';

-- 6.2 — 可见度分析 (renamed from 趋势诊断分析)
UPDATE geo_report_templates SET
    name = '可见度分析',
    description = '聚焦自有品牌在 AI 搜索引擎中的可见度表现：SOV、排名、覆盖率、平台分布',
    icon = '📈',
    data_domains = ARRAY['visibility']::text[],
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'analysis_goal',   jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY['sov_methodology']),
            'data_selection',  jsonb_build_object('enabled', true, 'default_domains', ARRAY['visibility'], 'default_date_range', 'last_30d'),
            'chart_config',    jsonb_build_object('enabled', true, 'default_charts', jsonb_build_array(
                jsonb_build_object('nl_query', '自有品牌每日可见度提及次数趋势', 'chart_type', 'line'),
                jsonb_build_object('nl_query', '各 AI 平台的自有品牌可见度分布', 'chart_type', 'bar')
            )),
            'prompt_edit',     jsonb_build_object('enabled', true),
            'confirm_execute', jsonb_build_object('enabled', true)
        ),
        'required_metrics', jsonb_build_array('sov_trend','visibility_rank_vs_peers','prompt_coverage_rate','platform_visibility_breakdown'),
        'required_chapters', jsonb_build_array('visibility')
    ),
    updated_at = NOW()
WHERE id = '77d0c161-9fbf-4295-87b7-70827f58b74c';

-- 6.3 — 综合分析 (renamed from 全面健康检查)
UPDATE geo_report_templates SET
    name = '综合分析',
    description = '全域扫描品牌在所有 AI 引擎中的可见度、引用和情感三维度综合表现',
    icon = '🛡️',
    data_domains = ARRAY['visibility','citation','sentiment']::text[],
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'analysis_goal',   jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY['holistic_geo_health']),
            'data_selection',  jsonb_build_object('enabled', true, 'default_domains', ARRAY['visibility','citation','sentiment'], 'default_date_range', 'last_30d'),
            'chart_config',    jsonb_build_object('enabled', true, 'default_charts', jsonb_build_array(
                jsonb_build_object('nl_query', '品牌可见度、引用率综合趋势', 'chart_type', 'line'),
                jsonb_build_object('nl_query', '品牌 vs 竞品在各平台的 SOV 对比', 'chart_type', 'bar'),
                jsonb_build_object('nl_query', '品牌情感评分分布', 'chart_type', 'pie')
            )),
            'prompt_edit',     jsonb_build_object('enabled', true),
            'confirm_execute', jsonb_build_object('enabled', true)
        ),
        'required_metrics', jsonb_build_array(
            'sov_trend','visibility_rank_vs_peers','platform_visibility_breakdown',
            'peer_citation_share','citation_source_diversity',
            'sentiment_distribution','sentiment_trend'
        ),
        'required_chapters', jsonb_build_array('visibility','citation','sentiment')
    ),
    updated_at = NOW()
WHERE id = '2ce092cd-8479-4cdc-b19a-208084c9e15b';

-- 6.4 — 情感分析
UPDATE geo_report_templates SET
    name = '情感分析',
    description = '深度拆解品牌在 AI 搜索引擎中的情感维度，识别正面和负面主题',
    icon = '💬',
    data_domains = ARRAY['sentiment']::text[],
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'analysis_goal',   jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY['sentiment_deep_dive']),
            'data_selection',  jsonb_build_object('enabled', true, 'default_domains', ARRAY['sentiment'], 'default_date_range', 'last_30d'),
            'chart_config',    jsonb_build_object('enabled', true, 'default_charts', jsonb_build_array(
                jsonb_build_object('nl_query', '各 AI 平台的情感分布', 'chart_type', 'bar'),
                jsonb_build_object('nl_query', '品牌正面情感主题 Top 10', 'chart_type', 'bar'),
                jsonb_build_object('nl_query', '品牌负面情感主题 Top 10', 'chart_type', 'bar')
            )),
            'prompt_edit',     jsonb_build_object('enabled', true),
            'confirm_execute', jsonb_build_object('enabled', true)
        ),
        'required_metrics', jsonb_build_array('sentiment_distribution','sentiment_trend','top_positive_themes','top_negative_themes'),
        'required_chapters', jsonb_build_array('sentiment')
    ),
    updated_at = NOW()
WHERE id = '634b218b-2912-408b-835a-03fe4e21e1fd';

-- 6.5 — 自定义分析
UPDATE geo_report_templates SET
    name = '自定义分析',
    description = '不预选任何选项，完全自定义所有分析配置（走动态 metric 发现）',
    icon = '✨',
    data_domains = ARRAY[]::text[],
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'analysis_goal',   jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY[]::text[]),
            'data_selection',  jsonb_build_object('enabled', true, 'default_domains', ARRAY[]::text[], 'default_date_range', 'last_30d'),
            'chart_config',    jsonb_build_object('enabled', true, 'default_charts', '[]'::jsonb),
            'prompt_edit',     jsonb_build_object('enabled', true),
            'confirm_execute', jsonb_build_object('enabled', true)
        ),
        'required_metrics',  '[]'::jsonb,
        'required_chapters', '[]'::jsonb
    ),
    updated_at = NOW()
WHERE id = '8b11e539-80ca-4125-9038-3b9963bfa880';


-- =============================================================
-- STEP 7: Content templates — wizard_config contracts
-- =============================================================
-- required_subgoals references geo_optimization_subgoals.id (slugs):
--   content_understandability, authority_eeat, information_presentation,
--   trending_relevance, publish_timeliness, machine_readability,
--   audience_fit, verifiability, platform_fit
-- Confirmed via `SELECT id, name_en, name_zh FROM geo_optimization_subgoals
-- ORDER BY sort_order;` before this migration was written.

-- 7.1 — FAQ 内容生成
UPDATE geo_report_templates SET
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'content_goal',     jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY['content_strategy_faq']),
            'content_type',     jsonb_build_object('enabled', true, 'default', 'faq'),
            'goal_config',      jsonb_build_object('enabled', true, 'default_count', 5, 'default_depth', 'standard'),
            'prompt_select',    jsonb_build_object('enabled', true, 'default_sort', 'visibility'),
            'data_strategy',    jsonb_build_object('enabled', true, 'default_domains', ARRAY['visibility','citation']),
            'model_schedule',   jsonb_build_object('enabled', true),
            'confirm_execute',  jsonb_build_object('enabled', true)
        ),
        'required_metrics',  jsonb_build_array('prompt_coverage_rate','visibility_rank_vs_peers'),
        'required_subgoals', jsonb_build_array(
            'information_presentation',
            'machine_readability',
            'content_understandability',
            'verifiability'
        )
    ),
    updated_at = NOW()
WHERE id = 'd19a8579-3b73-4672-80d7-6ae0f38b5c29';

-- 7.2 — AEO 优化文章
UPDATE geo_report_templates SET
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'content_goal',     jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY['content_raft_retrievability','content_raft_accuracy']),
            'content_type',     jsonb_build_object('enabled', true, 'default', 'aeo_article'),
            'goal_config',      jsonb_build_object('enabled', true, 'default_count', 1, 'default_depth', 'standard'),
            'prompt_select',    jsonb_build_object('enabled', true, 'default_sort', 'citation'),
            'data_strategy',    jsonb_build_object('enabled', true, 'default_domains', ARRAY['visibility','citation']),
            'model_schedule',   jsonb_build_object('enabled', true),
            'confirm_execute',  jsonb_build_object('enabled', true)
        ),
        'required_metrics',  jsonb_build_array('peer_citation_share','visibility_rank_vs_peers'),
        'required_subgoals', jsonb_build_array(
            'machine_readability',
            'authority_eeat',
            'verifiability',
            'information_presentation',
            'platform_fit'
        )
    ),
    updated_at = NOW()
WHERE id = '31a92f45-74da-4794-8919-93366c86e10e';

-- 7.3 — SEO 优化文章
UPDATE geo_report_templates SET
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'content_goal',     jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY[]::text[]),
            'content_type',     jsonb_build_object('enabled', true, 'default', 'article'),
            'goal_config',      jsonb_build_object('enabled', true, 'default_count', 1, 'default_depth', 'standard'),
            'prompt_select',    jsonb_build_object('enabled', true, 'default_sort', 'visibility'),
            'data_strategy',    jsonb_build_object('enabled', true, 'default_domains', ARRAY['visibility']),
            'model_schedule',   jsonb_build_object('enabled', true),
            'confirm_execute',  jsonb_build_object('enabled', true)
        ),
        'required_metrics',  jsonb_build_array('prompt_coverage_rate'),
        'required_subgoals', jsonb_build_array(
            'content_understandability',
            'information_presentation',
            'trending_relevance',
            'publish_timeliness'
        )
    ),
    updated_at = NOW()
WHERE id = '94258615-2061-4a07-9a72-9f21c701057d';

-- 7.4 — 内容优化建议
UPDATE geo_report_templates SET
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'content_goal',     jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY['content_strategy_diff']),
            'content_type',     jsonb_build_object('enabled', true, 'default', 'recommendations'),
            'goal_config',      jsonb_build_object('enabled', true, 'default_count', 1, 'default_depth', 'deep'),
            'prompt_select',    jsonb_build_object('enabled', true, 'default_sort', 'citation'),
            'data_strategy',    jsonb_build_object('enabled', true, 'default_domains', ARRAY['visibility','citation','sentiment']),
            'model_schedule',   jsonb_build_object('enabled', true),
            'confirm_execute',  jsonb_build_object('enabled', true)
        ),
        'required_metrics',  jsonb_build_array('sov_trend','peer_citation_share','sentiment_distribution'),
        'required_subgoals', jsonb_build_array(
            'content_understandability',
            'authority_eeat',
            'information_presentation',
            'trending_relevance',
            'publish_timeliness',
            'machine_readability',
            'audience_fit',
            'verifiability',
            'platform_fit'
        )
    ),
    updated_at = NOW()
WHERE id = 'c0153b12-df21-45c5-97e1-2ffd1db970e5';

-- 7.5 — Content Brief
UPDATE geo_report_templates SET
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'content_goal',     jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY['content_raft_retrievability','content_raft_trustworthiness']),
            'content_type',     jsonb_build_object('enabled', true, 'default', 'brief'),
            'goal_config',      jsonb_build_object('enabled', true, 'default_count', 1, 'default_depth', 'standard'),
            'prompt_select',    jsonb_build_object('enabled', true, 'default_sort', 'citation'),
            'data_strategy',    jsonb_build_object('enabled', true, 'default_domains', ARRAY['visibility','citation']),
            'model_schedule',   jsonb_build_object('enabled', true),
            'confirm_execute',  jsonb_build_object('enabled', true)
        ),
        'required_metrics',  jsonb_build_array('prompt_coverage_rate','peer_citation_share'),
        'required_subgoals', jsonb_build_array(
            'information_presentation',
            'authority_eeat',
            'verifiability',
            'audience_fit',
            'platform_fit'
        )
    ),
    updated_at = NOW()
WHERE id = 'e826e06a-ff43-419b-922c-4d5ffafd3146';

-- 7.6 — 自定义内容
UPDATE geo_report_templates SET
    wizard_config = jsonb_build_object(
        'version', 1,
        'steps', jsonb_build_object(
            'content_goal',     jsonb_build_object('enabled', true, 'default_methodology_snippets', ARRAY[]::text[]),
            'content_type',     jsonb_build_object('enabled', true, 'default', NULL),
            'goal_config',      jsonb_build_object('enabled', true),
            'prompt_select',    jsonb_build_object('enabled', true),
            'data_strategy',    jsonb_build_object('enabled', true),
            'model_schedule',   jsonb_build_object('enabled', true),
            'confirm_execute',  jsonb_build_object('enabled', true)
        ),
        'required_metrics',  '[]'::jsonb,
        'required_subgoals', '[]'::jsonb
    ),
    updated_at = NOW()
WHERE id = 'a1cc66f6-97dd-4ea9-ae91-e4c14a0d16d2';


-- =============================================================
-- STEP 8: Clean up geo_workflow_config
-- =============================================================

-- 8.1 — Drop dead data: recommended_chart rows (frontend hardcoded these,
-- Phase 2 moves chart defaults into template.wizard_config.steps.chart_config.default_charts)
DELETE FROM geo_workflow_config WHERE config_type = 'recommended_chart';

-- 8.2 — Drop RAFT methodology snippets from analysis scope (RAFT belongs to content)
DELETE FROM geo_workflow_config
WHERE config_type = 'methodology_snippet'
  AND scope = 'analysis'
  AND key IN ('raft_retrievability','raft_accuracy','raft_fluency','raft_trustworthiness');

-- 8.3 — Drop goal rows from analysis scope (new wizard uses methodology_snippet selector, not goal)
DELETE FROM geo_workflow_config WHERE config_type = 'goal' AND scope = 'analysis';

-- 8.4 — Add 3 new analysis methodology snippets
INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES
  ('methodology_snippet', 'analysis', 'sov_methodology', '可见度方法论',
   '{"label":"SOV 计算口径","snippet":"请按照 Share of Voice = 自有品牌 mention 数 / (自有品牌 + 已配置 peers) mention 数 的口径分析可见度。"}'::jsonb,
   1, true),
  ('methodology_snippet', 'analysis', 'holistic_geo_health', '综合诊断',
   '{"label":"三维度综合评分","snippet":"请同时评估 Visibility, Citation, Sentiment 三个维度的表现，对每个维度独立打分并给出短板诊断。"}'::jsonb,
   1, true),
  ('methodology_snippet', 'analysis', 'sentiment_deep_dive', '情感拆解',
   '{"label":"正负面主题拆解","snippet":"请按 theme 分别列出正面和负面 mention 的 Top 主题，识别需要优先改进的 Top 负面主题。"}'::jsonb,
   1, true);


COMMIT;

-- =============================================================
-- Post-run verification queries (run these manually after migration):
-- =============================================================
-- 1. Confirm 5 analysis templates + 6 content templates exist:
--    SELECT name, task_type, is_active, wizard_config IS NOT NULL AS has_config
--    FROM geo_report_templates ORDER BY task_type, sort_order;
--
-- 2. Confirm 10 metrics seeded:
--    SELECT metric_name, domain, array_length(relevant_tables, 1)
--    FROM geo_analysis_metrics ORDER BY sort_order;
--
-- 3. Spot-check one template's contract:
--    SELECT name, wizard_config->'required_metrics', wizard_config->'required_chapters'
--    FROM geo_report_templates WHERE name = '综合分析';
--
-- 4. Confirm workflow_config cleanup:
--    SELECT config_type, scope, COUNT(*) FROM geo_workflow_config
--    GROUP BY config_type, scope ORDER BY config_type, scope;
--    -- expect: no 'recommended_chart' rows
--    -- expect: no 'goal' rows with scope='analysis'
--    -- expect: no 'raft_*' methodology snippets with scope='analysis'
--    -- expect: 3 new methodology snippets with scope='analysis'
