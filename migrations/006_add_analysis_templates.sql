-- =============================================================
-- Migration 006: Analysis & Insights Templates
-- Run: psql $DATABASE_URL -f migrations/006_add_analysis_templates.sql
-- =============================================================
-- Creates three new tables:
--   1. geo_analysis_metrics      — Indicator/variable catalog per domain (Admin-managed)
--   2. geo_report_templates      — Report template definitions with default prompts (Admin+User)
--   3. geo_report_runs           — Persistent run history with outputs (one row per execution)
-- Also inserts:
--   - Initial metrics for Visibility, Citation, Sentiment domains
--   - 5 built-in report templates (Custom blank + 4 predefined)
--   - REPORT_MODEL_ID_LIST into geo_global_settings
-- =============================================================


-- ============================================================
-- 1. geo_analysis_metrics
-- ============================================================
CREATE TABLE IF NOT EXISTS geo_analysis_metrics (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain           TEXT NOT NULL,          -- 'visibility' | 'citation' | 'sentiment'
    variable_name    TEXT NOT NULL UNIQUE,   -- Used in {{variable_name}} in prompts
    display_name     TEXT NOT NULL,          -- Human-readable label shown in UI
    description      TEXT,                   -- Shown to users as tooltip / helper text
    calculation_hint TEXT,                   -- Natural language for Gemini to generate SQL from
    sql_override     TEXT,                   -- Optional: hard-coded SQL (takes priority over AI gen)
    unit             TEXT,                   -- Optional display unit, e.g. '%', 'count', '分'
    is_active        BOOLEAN DEFAULT true,
    sort_order       INTEGER DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_analysis_metrics_domain
    ON geo_analysis_metrics (domain);


-- ============================================================
-- 2. geo_report_templates
-- ============================================================
CREATE TABLE IF NOT EXISTS geo_report_templates (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name             TEXT NOT NULL,
    description      TEXT,
    icon             TEXT DEFAULT '📊',
    data_domains     TEXT[] DEFAULT '{}',     -- e.g. ['visibility', 'citation']
    default_prompt   TEXT,
    is_builtin       BOOLEAN DEFAULT false,   -- true = system template, cannot be deleted
    is_active        BOOLEAN DEFAULT true,
    sort_order       INTEGER DEFAULT 0,
    -- Ownership: NULL client_id + is_builtin=true means system built-in
    client_id        UUID,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_report_templates_client
    ON geo_report_templates (client_id);
CREATE INDEX IF NOT EXISTS idx_geo_report_templates_builtin
    ON geo_report_templates (is_builtin, is_active);


-- ============================================================
-- 3. geo_report_runs
-- ============================================================
CREATE TABLE IF NOT EXISTS geo_report_runs (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_id      UUID REFERENCES geo_report_templates(id) ON DELETE SET NULL,
    client_id        UUID NOT NULL,
    run_name         TEXT,                    -- Display name (defaults to template name + timestamp)
    status           TEXT DEFAULT 'RUNNING'   -- 'RUNNING' | 'COMPLETED' | 'FAILED' | 'SAVED'
                     CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'SAVED')),
    -- Configuration snapshot at time of run
    domains          TEXT[] DEFAULT '{}',
    filters          JSONB DEFAULT '{}',      -- {start_date, end_date, topics, platforms}
    chart_requests   JSONB DEFAULT '[]',      -- [{nl_query, chart_type}]
    prompt_used      TEXT,
    model_used       TEXT,
    -- Output
    report_output    JSONB,                   -- {charts: [...], insights_markdown: "..."}
    error_message    TEXT,
    -- Provenance
    triggered_by     TEXT DEFAULT 'manual'    -- 'manual' | 'cron'
                     CHECK (triggered_by IN ('manual', 'cron')),
    -- Scheduling fields for Tasks
    cron_expression       TEXT,              
    cron_timezone         TEXT DEFAULT 'Asia/Shanghai',
    scheduler_job_name    TEXT,              
    schedule_enabled      BOOLEAN DEFAULT false,
    started_at       TIMESTAMPTZ DEFAULT NOW(),
    completed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_geo_report_runs_client
    ON geo_report_runs (client_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_geo_report_runs_template
    ON geo_report_runs (template_id);
CREATE INDEX IF NOT EXISTS idx_geo_report_runs_status
    ON geo_report_runs (status);


-- ============================================================
-- 4. geo_global_settings: REPORT_MODEL_ID_LIST
-- ============================================================
INSERT INTO geo_global_settings (key, value, description)
VALUES (
    'report_model_id_list',
    'gemini-3.1-pro-preview,gemini-3-flash-preview',
    'Comma-separated list of Vertex AI model IDs available for Analysis & Insights report generation. First entry is the default.'
)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;

INSERT INTO geo_global_settings (key, value, description)
VALUES (
    'nl2sql_model_id',
    'gemini-3.1-pro-preview',
    'The Gemini model specifically designated for Natural Language to SQL generation.'
)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;


-- ============================================================
-- 5. Initial Metrics: Visibility Domain
-- ============================================================
INSERT INTO geo_analysis_metrics (domain, variable_name, display_name, description, calculation_hint, sort_order) VALUES

('visibility', 'visibility_score',
 '可见性得分',
 '自有品牌在所有 AI 回答中出现的平均加权得分（100分制）',
 'Calculate a weighted visibility score for the own brand (is_own_brand=true) from geo_company_mentions for the given client and date range. Weight by inverse mention_position so rank 1 = highest score. Normalize to 100.', 10),

('visibility', 'visibility_wow_change',
 '可见性周环比变化(%)',
 '本周与上周相比，可见性得分的变化百分比。正数为上升，负数为下降。',
 'Compare the weighted visibility score of the current period vs. the previous period of equal length. Return the percentage change rounded to 2 decimal places.', 20),

('visibility', 'visibility_direction',
 '可见性趋势方向',
 '本周可见性得分是上升（increased）还是下降（decreased）',
 'Return "increased" if visibility_score is higher than last period, else "decreased".', 30),

('visibility', 'visibility_rank',
 '自有品牌排名',
 '自有品牌在所有被提及品牌中的平均提及位次（1=最常被提及）',
 'Calculate the average mention_position for the own brand (is_own_brand=true) across all results in the geo_company_mentions table for the given client and date range.', 40),

('visibility', 'share_of_voice',
 '品牌声量占比(SOV)',
 '自有品牌提及次数占所有品牌总提及次数的百分比',
 'Divide total own brand mention counts by total mention counts across all brands for the client in the date range. Return as a percentage.', 50),

('visibility', 'sov_wow_change',
 'SOV 周环比变化(%)',
 '品牌声量占比与上期相比的变化百分比',
 'Compare share_of_voice of current period vs previous period. Return percentage change rounded to 2 decimal places.', 60),

('visibility', 'top_brand_table',
 '品牌排名 Markdown 表格',
 '按提及次数排名的前10品牌，含各自提及次数和平均位次，格式为 Markdown 表格',
 'Query geo_company_mentions for the given client and date range. Group by company_name, count total mentions and calculate average mention_position. Order by count DESC, return top 10. Format as Markdown table with columns: Brand | Mentions | Avg Position.', 70),

('visibility', 'visibility_by_platform',
 '各平台可见性得分 Markdown 表格',
 '自有品牌在每个 AI 平台上的可见性得分，格式为 Markdown 表格',
 'Join geo_company_mentions with geo_results on result_id to get the platform field. Filter to own brand only. Group by platform, calculate weighted visibility score per platform. Return as Markdown table: Platform | Visibility Score.', 80),

('visibility', 'total_mention_count',
 '总提及次数',
 '在选定时间范围和筛选条件内，自有品牌被提及的总次数',
 'Count total rows in geo_company_mentions where is_own_brand=true for the given client and date range.', 90),

('visibility', 'mention_count_wow_change',
 '提及次数周环比变化(%)',
 '本期内自有品牌提及次数相比上一同等时长周期的变化百分比',
 'Compare total_mention_count of current period vs previous period. Return percentage change.', 100),

('visibility', 'top_visibility_prompt',
 '可见性最高的 Prompt',
 '哪条 Prompt 带来了最高的可见性得分',
 'Join geo_company_mentions with geo_client_prompts on client_prompt_id. Filter to own brand. Group by prompt text, rank by average weighted visibility score. Return the top 1 prompt text.', 110),

('visibility', 'platform_breakdown_json',
 '各平台明细数据 (JSON)',
 '各平台提及次数和可见性得分的结构化 JSON 数据，供图表使用',
 'Group geo_company_mentions by platform (via join with geo_results), calculate count and avg position for own brand. Return as JSON array: [{platform, count, avg_position, visibility_score}].', 120)

ON CONFLICT (variable_name) DO NOTHING;


-- ============================================================
-- 6. Initial Metrics: Citation Domain
-- ============================================================
INSERT INTO geo_analysis_metrics (domain, variable_name, display_name, description, calculation_hint, sort_order) VALUES

('citation', 'citation_share',
 '引用占比(%)',
 '自有域名被引用次数占所有引用来源总次数的百分比',
 'Count citations where source_domain matches any of the client owned domains (geo_client_domains). Divide by total citation count for the client in the date range. Return as percentage.', 10),

('citation', 'citation_share_wow_change',
 '引用占比周环比变化(%)',
 '本期引用占比与上一同等时长周期的变化百分比',
 'Compare citation_share of current period vs previous period. Return percentage change rounded to 2 decimal places.', 20),

('citation', 'citation_direction',
 '引用趋势方向',
 '引用占比是上升（increased）还是下降（decreased）',
 'Return "increased" if citation_share is higher than last period, else "decreased".', 30),

('citation', 'total_citation_count',
 '总引用次数',
 '所有来源的引用总次数（非去重）',
 'Count total rows in geo_citations for the given client and date range.', 40),

('citation', 'own_domain_citation_count',
 '自有域名引用次数',
 '自有域名被引用的总次数',
 'Count rows in geo_citations where source_domain matches any geo_client_domains entry for the given client.', 50),

('citation', 'top_citation_table',
 '头部引用域名 Markdown 表格',
 '按被引用次数排名的前20个域名，含各自引用次数、类型和是否为自有域名，格式为 Markdown 表格',
 'Group geo_citations by source_domain for the given client and date range. Count citations per domain. Mark if domain is in geo_client_domains. Order by count DESC. Return top 20 as Markdown table: Domain | Citations | Category | Own Domain.', 60),

('citation', 'citation_by_platform',
 '各平台引用占比 Markdown 表格',
 '自有域名在各 AI 平台上的引用占比，格式为 Markdown 表格',
 'Join geo_citations with geo_results on result_id. Filter to own domains. Group by platform. Calculate citation share per platform. Return as Markdown table: Platform | Own Domain Citations | Total Citations | Share %.', 70),

('citation', 'citation_pill_count',
 '高优引用源次数',
 'is_citation_pill=true 的引用次数，代表 AI 引擎主动推荐的高优引用',
 'Count rows in geo_citations where is_citation_pill=true for the given client and date range.', 80),

('citation', 'new_domains_this_period',
 '本期新增引用域名数',
 '本期内首次出现、上期没有出现的新引用域名数量',
 'Find domains in geo_citations for the current period that were NOT present in geo_citations for the previous period of equal length, for the given client.', 90),

('citation', 'dropped_domains_this_period',
 '本期流失引用域名数',
 '上期有但本期消失的引用域名数量',
 'Find domains present in geo_citations for the previous period that are NOT present in the current period, for the given client.', 100),

('citation', 'category_breakdown_table',
 '引用域名分类分布 Markdown 表格',
 '按域名分类（如 Media、Brand、Social）统计引用次数分布，格式为 Markdown 表格',
 'Join geo_citations with geo_domain_categories on source_domain. Group by category. Count citations per category. Order by count DESC. Return as Markdown table: Category | Citation Count | Share %.', 110),

('citation', 'citation_trend_json',
 '引用趋势 JSON 数据',
 '按时间分组的引用次数趋势数据，供折线图使用',
 'Group geo_citations by date (using executed_at truncated to day/week/month based on interval parameter). Count total and own-domain citations per period. Return as JSON array: [{date, total_citations, own_domain_citations}].', 120)

ON CONFLICT (variable_name) DO NOTHING;


-- ============================================================
-- 7. Initial Metrics: Sentiment Domain
-- ============================================================
INSERT INTO geo_analysis_metrics (domain, variable_name, display_name, description, calculation_hint, sort_order) VALUES

('sentiment', 'positive_ratio',
 '正面情感占比(%)',
 '情感标注为 Positive 的结果占所有情感分析结果的百分比',
 'Count rows in geo_sentiment_results where sentiment=''Positive'' and client_id matches, divided by total rows for that client in the date range. Return as percentage.', 10),

('sentiment', 'negative_ratio',
 '负面情感占比(%)',
 '情感标注为 Negative 的结果占所有情感分析结果的百分比',
 'Count rows in geo_sentiment_results where sentiment=''Negative'' divided by total rows. Return as percentage.', 20),

('sentiment', 'sentiment_wow_change',
 '正面情感周环比变化(%)',
 '本期正面情感占比相比上期的变化百分比',
 'Compare positive_ratio of current period vs previous period. Return percentage change rounded to 2 decimal places.', 30),

('sentiment', 'sentiment_direction',
 '情感趋势方向',
 '正面情感占比是上升还是下降',
 'Return "improved" if positive_ratio increased compared to previous period, else "worsened".', 40),

('sentiment', 'total_sentiment_count',
 '情感分析总数',
 '选定时间范围内完成情感分析的结果总数',
 'Count total rows in geo_sentiment_results for the given client and date range.', 50),

('sentiment', 'avg_confidence',
 '平均情感置信度',
 '情感标注的平均置信度分数（0-1）',
 'Calculate AVG(confidence) from geo_sentiment_results for the given client and date range. Round to 3 decimal places.', 60),

('sentiment', 'top_positive_themes',
 '热门正面主题 Markdown 表格',
 '出现频率最高的正面情感主题，含各主题出现次数，格式为 Markdown 表格',
 'Query geo_sentiment_themes where sentiment=''Positive'' and client_id matches the given client in the date range. Group by theme_name, count occurrences, order by count DESC, return top 10 as Markdown table: Theme | Mentions.', 70),

('sentiment', 'top_negative_themes',
 '热门负面主题 Markdown 表格',
 '出现频率最高的负面情感主题，含各主题出现次数，格式为 Markdown 表格',
 'Query geo_sentiment_themes where sentiment=''Negative'' and client_id matches the given client in the date range. Group by theme_name, count occurrences, order by count DESC, return top 10 as Markdown table: Theme | Mentions.', 80),

('sentiment', 'sentiment_trend_table',
 '情感趋势 Markdown 表格',
 '按时间分组的正负面情感占比变化，格式为 Markdown 表格',
 'Group geo_sentiment_results by date range interval (day/week/month). Calculate positive and negative ratios per time period. Return as Markdown table: Period | Positive % | Negative %.', 90),

('sentiment', 'sentiment_by_platform',
 '各平台情感分布 Markdown 表格',
 '各 AI 平台上的正面情感占比，格式为 Markdown 表格',
 'Join geo_sentiment_results with geo_results on result_id to get platform. Group by platform. Calculate positive ratio per platform. Return as Markdown table: Platform | Positive % | Negative % | Total Analyzed.', 100),

('sentiment', 'sentiment_by_topic',
 '各 Topic 情感分布 Markdown 表格',
 '各 Topic 下的正面情感占比，格式为 Markdown 表格',
 'Join geo_sentiment_results with geo_results on result_id, then join with geo_tasks on task_id to get topic_name. Group by topic_name. Return as Markdown table: Topic | Positive % | Negative % | Count.', 110),

('sentiment', 'sentiment_trend_json',
 '情感趋势 JSON 数据',
 '按时间分组的情感数据，供折线图或面积图使用',
 'Group geo_sentiment_results by time interval. Return JSON array: [{date, positive_count, negative_count, positive_ratio}].', 120),

('sentiment', 'concern_themes_excerpt',
 '需关注的负面主题摘录',
 '最重要的负面主题及相关原文摘录，便于大模型撰写改进建议',
 'Query geo_sentiment_themes where sentiment=''Negative'' for the client and date range, ordered by occurrence count DESC. Return top 5 themes with their excerpt text from the same row. Format as text.', 130)

ON CONFLICT (variable_name) DO NOTHING;


-- ============================================================
-- 8. Built-in Report Templates (5 templates)
-- ============================================================

-- Template 1: Visibility Analysis
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, is_builtin, is_active, sort_order, default_prompt
) VALUES (
    uuid_generate_v4(),
    '品牌可见度分析',
    '深入分析品牌在 AI 引擎中的可见性得分、品牌声量和竞品对比',
    '👁️',
    ARRAY['visibility'],
    true,
    true,
    1,
    E'You are Anthony, a GEO (Generative Engine Optimization) analyst. Your task is to generate a concise brand visibility report based on the following data inputs.\n\nDo not fabricate data. Only interpret what is provided.\n\nInputs:\n- visibility_score: {{visibility_score}}\n  The current period''s weighted visibility score (0-100)\n- visibility_wow_change: {{visibility_wow_change}}\n  Week-over-week change in visibility score\n- visibility_direction: {{visibility_direction}}\n  Whether visibility has "increased" or "decreased"\n- share_of_voice: {{share_of_voice}}\n  Brand''s share of voice among all mentioned brands\n- sov_wow_change: {{sov_wow_change}}\n  Week-over-week change in share of voice\n- total_mention_count: {{total_mention_count}}\n  Total own brand mention count in the period\n- top_brand_table: {{top_brand_table}}\n  Markdown table of top mentioned brands\n- visibility_by_platform: {{visibility_by_platform}}\n  Markdown table of visibility scores by AI platform\n\n====\n\nOutput Structure (use these exact headings):\n\n## Brand Visibility Report — [Current Period]\n\n### Visibility Score\nWoW Change: Visibility has {{visibility_direction}} by {{visibility_wow_change}} since last period.\nCurrent Score: {{visibility_score}} / 100\n\nWrite 1-2 sentences interpreting the overall visibility trend. Neutral, analytical tone. No recommendations.\n\n### Share of Voice\nCurrent SOV: {{share_of_voice}}\nWoW Change: {{sov_wow_change}}\n\nInclude {{top_brand_table}} without modification.\n\n### Visibility by Platform\n{{visibility_by_platform}}\n\n### Summary\nWrite 2-3 sentences summarizing the overall visibility position. Include the most notable observation.\n\n====\nFormatting: Markdown only. No extra sections. No speculation. No next steps.'
);

-- Template 2: Citation Analysis
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, is_builtin, is_active, sort_order, default_prompt
) VALUES (
    uuid_generate_v4(),
    '引用来源分析',
    '分析品牌域名在 AI 引擎引用中的占比、趋势与竞争格局',
    '🔗',
    ARRAY['citation'],
    true,
    true,
    2,
    E'You are Anthony, a GEO citation analyst. Generate a concise citation share report based on the data provided.\n\nDo not fabricate data. Only interpret what is provided.\n\nInputs:\n- citation_share: {{citation_share}}\n  Own domain''s percentage of all citations\n- citation_share_wow_change: {{citation_share_wow_change}}\n  Week-over-week change in citation share\n- citation_direction: {{citation_direction}}\n  Whether citation share has "increased" or "decreased"\n- total_citation_count: {{total_citation_count}}\n  Total citations across all domains\n- own_domain_citation_count: {{own_domain_citation_count}}\n  Number of times own domains were cited\n- citation_pill_count: {{citation_pill_count}}\n  Number of high-priority (citation pill) references\n- new_domains_this_period: {{new_domains_this_period}}\n  New domains appearing this period\n- dropped_domains_this_period: {{dropped_domains_this_period}}\n  Domains that dropped out this period\n- top_citation_table: {{top_citation_table}}\n  Markdown table of top cited domains\n- category_breakdown_table: {{category_breakdown_table}}\n  Citation distribution by domain category\n\n====\n\nOutput Structure:\n\n## Citation Share Report — [Current Period]\n\n### Citation Share\nWoW Change: Citation share has {{citation_direction}} by {{citation_share_wow_change}} since last period.\nCurrent Share: {{citation_share}}\n\nWrite 1 sentence summarizing the citation share trend.\n\n### Top Cited Domains\n{{top_citation_table}}\n\nNote new domains: +{{new_domains_this_period}} new | -{{dropped_domains_this_period}} dropped.\n\n### Citation Category Breakdown\n{{category_breakdown_table}}\n\n### Summary\n2 sentences on the overall citation landscape and position stability.\n\n====\nFormatting: Markdown only. No extra sections. No recommendations.'
);

-- Template 3: Sentiment Analysis
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, is_builtin, is_active, sort_order, default_prompt
) VALUES (
    uuid_generate_v4(),
    '品牌情感分析',
    '分析 AI 引擎回答中对品牌的情感倾向、正负面主题与趋势变化',
    '❤️',
    ARRAY['sentiment'],
    true,
    true,
    3,
    E'You are Anthony, a GEO sentiment analyst. Generate a concise sentiment report based on the data provided.\n\nDo not fabricate data. Only interpret what is provided.\n\nInputs:\n- positive_ratio: {{positive_ratio}}\n  Percentage of AI responses with positive brand sentiment\n- negative_ratio: {{negative_ratio}}\n  Percentage of AI responses with negative brand sentiment\n- sentiment_wow_change: {{sentiment_wow_change}}\n  Week-over-week change in positive sentiment ratio\n- sentiment_direction: {{sentiment_direction}}\n  Whether sentiment has "improved" or "worsened"\n- total_sentiment_count: {{total_sentiment_count}}\n  Total results analyzed for sentiment\n- avg_confidence: {{avg_confidence}}\n  Average confidence score of sentiment labels (0-1)\n- top_positive_themes: {{top_positive_themes}}\n  Markdown table of top positive themes\n- top_negative_themes: {{top_negative_themes}}\n  Markdown table of top negative themes\n- sentiment_by_platform: {{sentiment_by_platform}}\n  Sentiment distribution by AI platform\n- concern_themes_excerpt: {{concern_themes_excerpt}}\n  Top negative themes with text excerpts\n\n====\n\nOutput Structure:\n\n## Brand Sentiment Report — [Current Period]\n\n### Sentiment Overview\nPositive: {{positive_ratio}} | Negative: {{negative_ratio}}\nWoW Change: Sentiment has {{sentiment_direction}} by {{sentiment_wow_change}} since last period.\n\nWrite 1 sentence on the overall sentiment signal.\n\n### Top Positive Themes\n{{top_positive_themes}}\n\n### Top Negative Themes\n{{top_negative_themes}}\n\n### Sentiment by Platform\n{{sentiment_by_platform}}\n\n### Areas of Concern\nBased on the following excerpts:\n{{concern_themes_excerpt}}\n\nWrite 2-3 sentences on the most significant negative themes.\n\n### Summary\n2 sentences on overall brand sentiment health.\n\n====\nFormatting: Markdown only. No speculation. No next steps.'
);

-- Template 4: Weekly GEO Report (all 3 domains)
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, is_builtin, is_active, sort_order, default_prompt
) VALUES (
    uuid_generate_v4(),
    '周度 GEO 简报',
    '综合品牌可见度、引用来源和情感分析数据，生成完整的 AI 搜索引擎周度复盘报告',
    '📊',
    ARRAY['visibility', 'citation', 'sentiment'],
    true,
    true,
    4,
    E'You are generating a concise weekly performance report for a brand''s visibility in AI-driven answer engines (AEO/GEO).\n\nA detailed citation table has already been generated and is to be included in this report.\n\nDo not recreate or summarize individual cited URLs.\n\nInputs you will receive:\n\nvisibility_change_percent: {{visibility_wow_change}}\n- The week-over-week percentage change in visibility score\n\nvisibility_direction: {{visibility_direction}}\n- "increased" or "decreased"\n\ncurrent_visibility_score: {{visibility_score}}\n- The most recent weekly average visibility score\n\ncitation_share_percent_change: {{citation_share_wow_change}}\n- Week over week percent change in citation share\n\ncitation_direction: {{citation_direction}}\n\ncurrent_citation_share: {{citation_share}}\n\nsentiment_direction: {{sentiment_direction}}\n\ncurrent_positive_ratio: {{positive_ratio}}\n\nsentiment_wow_change: {{sentiment_wow_change}}\n\ntop_brand_table: {{top_brand_table}}\n\ntop_citation_table: {{top_citation_table}}\n\nvisibility_by_platform: {{visibility_by_platform}}\n\nsentiment_by_platform: {{sentiment_by_platform}}\n\ntop_positive_themes: {{top_positive_themes}}\n\ntop_negative_themes: {{top_negative_themes}}\n\n====\n\nOutput requirements. Produce a report with the following structure:\n\n## Weekly AEO/GEO Performance Report — [Current Date]\n\n### Visibility Score\nWoW Change: Visibility has {{visibility_direction}} by {{visibility_wow_change}} since last week.\nCurrent Average: {{visibility_score}}/100\n\nThis week''s citation share has {{citation_direction}} by {{citation_share_wow_change}}.\n\nWrite one concise sentence (max 40 words) interpreting visibility and citation trends at a high level. Neutral, analytical tone. No speculation. No URLs. No mention of individual pages.\n\n### Brand Rankings\n{{top_brand_table}}\n\n### Visibility by Platform\n{{visibility_by_platform}}\n\n### Citation Share\nWoW Change: Citation share has {{citation_direction}} by {{citation_share_wow_change}} since last week.\nCurrent Average: {{citation_share}}\n\n### Top Cited Sources\n{{top_citation_table}}\n\n### Brand Sentiment\nPositive ratio {{sentiment_direction}} by {{sentiment_wow_change}}.\nCurrent positive ratio: {{positive_ratio}}\n\nTop positive themes:\n{{top_positive_themes}}\n\nTop negative themes:\n{{top_negative_themes}}\n\n### Sentiment by Platform\n{{sentiment_by_platform}}\n\n====\n\nFormatting rules:\n- Markdown only\n- Do not edit table content\n- Do not add extra sections\n- Do not include recommendations or next steps\n- Return only the formatted report'
);

-- Template 5: Custom (blank placeholder — client_id NULL, is_builtin=true so it always appears)
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, is_builtin, is_active, sort_order, default_prompt
) VALUES (
    uuid_generate_v4(),
    '自定义模板',
    '从零开始，自由选择数据领域和配置分析指标',
    '➕',
    ARRAY[]::TEXT[],
    true,
    true,
    0,
    E'You are Anthony, a GEO analyst. The user has selected custom data domains and variables.\n\nBased on the data provided, generate a structured analytical report.\n\nInputs will vary based on user selection.\n\nOutput a well-structured Markdown report with:\n- An executive summary of the key findings\n- Data tables as provided\n- 2-3 key insights derived from the data\n- Any notable trends or anomalies\n\nTone: Neutral, analytical, data-driven. No recommendations unless explicitly requested.'
);

-- ============================================================
-- 9. DoD (Day-over-Day) Metrics — supplement to WoW metrics
--    Added to support daily GEO reporting. Does NOT replace WoW.
-- ============================================================
INSERT INTO geo_analysis_metrics
    (domain, variable_name, display_name, description, calculation_hint, sort_order)
VALUES

('visibility', 'visibility_dod_change',
 '可见性日环比变化(%)',
 '今日与昨日相比，可见性得分的变化百分比。正数为上升，负数为下降。',
 'Compare the weighted visibility score (100.0/NULLIF(mention_position,0)) of the most recent calendar day vs the calendar day immediately before it, using DATE(executed_at) to group by day. Use $1 for client_id, filter is_own_brand=true. Return the percentage change rounded to 2 decimal places.',
 21),

('visibility', 'sov_dod_change',
 'SOV 日环比变化(%)',
 '品牌声量占比（SOV）与昨日相比的变化百分比',
 'Compare share_of_voice (own brand mentions / total mentions) of the most recent calendar day vs the previous calendar day using DATE(executed_at). Use $1 for client_id. Return percentage change rounded to 2 decimal places.',
 61),

('citation', 'citation_share_dod_change',
 '引用占比日环比变化(%)',
 '今日引用占比相比昨日的变化百分比',
 'Compare citation_share (own domain citations / total citations using geo_client_domains for client $1) of the most recent calendar day vs the previous calendar day using DATE(executed_at). Return percentage change rounded to 2 decimal places.',
 21),

('sentiment', 'sentiment_dod_change',
 '正面情感日环比变化(%)',
 '今日正面情感占比相比昨日的变化百分比',
 'Compare positive_ratio (sentiment=''Positive'' count / total count) from geo_sentiment_results for the most recent calendar day vs the previous calendar day using DATE(executed_at). Use $1 for client_id. Return percentage change rounded to 2 decimal places.',
 31)

ON CONFLICT (variable_name) DO NOTHING;


-- ============================================================
-- 10. Template 6: Daily GEO Report (all 3 domains, DoD metrics)
-- ============================================================
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, is_builtin, is_active, sort_order, default_prompt
) VALUES (
    uuid_generate_v4(),
    '日度 GEO 简报',
    '综合品牌可见度、引用来源和情感分析数据，生成 AI 搜索引擎日度复盘报告（与昨日对比）',
    '📅',
    ARRAY['visibility', 'citation', 'sentiment'],
    true,
    true,
    5,
    E'You are generating a concise daily performance report for a brand''s visibility in AI-driven answer engines (AEO/GEO).\n\nCompare today''s performance against yesterday. Do not fabricate data. Only interpret what is provided.\n\nInputs:\n\nvisibility_dod_change: {{visibility_dod_change}}\n- The day-over-day percentage change in visibility score\n\nvisibility_direction: {{visibility_direction}}\n- "increased" or "decreased"\n\ncurrent_visibility_score: {{visibility_score}}\n- The most recent daily average visibility score\n\ncitation_share_dod_change: {{citation_share_dod_change}}\n- Day-over-day percent change in citation share\n\ncitation_direction: {{citation_direction}}\n\ncurrent_citation_share: {{citation_share}}\n\nsentiment_direction: {{sentiment_direction}}\n\ncurrent_positive_ratio: {{positive_ratio}}\n\nsentiment_dod_change: {{sentiment_dod_change}}\n\ntop_brand_table: {{top_brand_table}}\n\ntop_citation_table: {{top_citation_table}}\n\nvisibility_by_platform: {{visibility_by_platform}}\n\nsentiment_by_platform: {{sentiment_by_platform}}\n\ntop_positive_themes: {{top_positive_themes}}\n\ntop_negative_themes: {{top_negative_themes}}\n\n====\n\nOutput requirements. Produce a report with the following structure:\n\n## Daily AEO/GEO Performance Report — [Current Date]\n\n### Visibility Score\nDoD Change: Visibility has {{visibility_direction}} by {{visibility_dod_change}} since yesterday.\nCurrent Average: {{visibility_score}}/100\n\nThis day''s citation share has {{citation_direction}} by {{citation_share_dod_change}} since yesterday.\n\nWrite one concise sentence (max 40 words) interpreting visibility and citation trends. Neutral, analytical tone. No speculation. No URLs.\n\n### Brand Rankings\n{{top_brand_table}}\n\n### Visibility by Platform\n{{visibility_by_platform}}\n\n### Citation Share\nDoD Change: Citation share has {{citation_direction}} by {{citation_share_dod_change}} since yesterday.\nCurrent Average: {{citation_share}}\n\n### Top Cited Sources\n{{top_citation_table}}\n\n### Brand Sentiment\nPositive ratio {{sentiment_direction}} by {{sentiment_dod_change}}.\nCurrent positive ratio: {{positive_ratio}}\n\nTop positive themes:\n{{top_positive_themes}}\n\nTop negative themes:\n{{top_negative_themes}}\n\n### Sentiment by Platform\n{{sentiment_by_platform}}\n\n====\n\nFormatting rules:\n- Markdown only\n- Do not edit table content\n- Do not add extra sections\n- Do not include recommendations or next steps\n- Return only the formatted report'
);

-- ============================================================
-- 11. PATCH: Fix direction metrics + sentiment_by_platform sql_override
--     Problem 1: visibility_direction / citation_direction / sentiment_direction
--       used $2/$3 (UI date range), causing mismatch with *_dod_change metrics
--       which self-determine the two most recent calendar days.
--     Problem 2: Gemini-generated SQL for sentiment_by_platform had a missing
--       FROM clause, causing "column row_text does not exist" runtime error.
-- ============================================================

UPDATE geo_analysis_metrics
SET calculation_hint = 'Compare the weighted visibility score (100.0/NULLIF(mention_position,0)) of the most recent calendar day vs the previous calendar day, using DATE(executed_at) to group. Use only $1 for client_id, filter is_own_brand=true. Return ''increased'' if today > yesterday, else ''decreased''.',
    updated_at = NOW()
WHERE variable_name = 'visibility_direction';

UPDATE geo_analysis_metrics
SET calculation_hint = 'Compare citation_share (own domain citations / total citations, using geo_client_domains for client $1) of the most recent calendar day vs the previous calendar day using DATE(executed_at). Use only $1 for client_id. Return ''increased'' if today > yesterday, else ''decreased''.',
    updated_at = NOW()
WHERE variable_name = 'citation_direction';

UPDATE geo_analysis_metrics
SET calculation_hint = 'Compare positive_ratio (sentiment=''Positive'' count / total count) from geo_sentiment_results of the most recent calendar day vs the previous calendar day using DATE(executed_at). Use only $1 for client_id. Return ''increased'' if today > yesterday, else ''decreased''.',
    updated_at = NOW()
WHERE variable_name = 'sentiment_direction';

-- Fix sentiment_by_platform: return NULL when no data so _hydrate_prompt shows N/A
UPDATE geo_analysis_metrics
SET sql_override = 'WITH stats AS (
    SELECT
        r.platform,
        ROUND(COUNT(*) FILTER (WHERE sr.sentiment ILIKE ''positive'') * 100.0 / NULLIF(COUNT(*), 0), 2) AS pos_pct,
        ROUND(COUNT(*) FILTER (WHERE sr.sentiment ILIKE ''negative'') * 100.0 / NULLIF(COUNT(*), 0), 2) AS neg_pct,
        COUNT(*) AS total
    FROM geo_sentiment_results sr
    JOIN geo_results r ON sr.result_id = r.result_id AND r.client_id = sr.client_id
    WHERE sr.client_id = $1
      AND sr.executed_at >= $2
      AND sr.executed_at <= $3
    GROUP BY r.platform
)
SELECT
    CASE WHEN COUNT(*) = 0 THEN NULL
    ELSE
        ''| Platform | Positive % | Negative % | Total Analyzed |'' || CHR(10) ||
        ''|---|---|---|---|'' || CHR(10) ||
        string_agg(
            ''| '' || COALESCE(platform, ''Unknown'') || '' | '' ||
            COALESCE(pos_pct::text, ''0'') || ''% | '' ||
            COALESCE(neg_pct::text, ''0'') || ''% | '' ||
            total::text || '' |'',
            CHR(10)
            ORDER BY total DESC
        )
    END
FROM stats;',
    updated_at = NOW()
WHERE variable_name = 'sentiment_by_platform';


-- ============================================================
-- 12. FULL sql_override for ALL metrics (deterministic SQL, no Gemini needed)
--     Benefits: eliminates Gemini NL2SQL calls → much faster + no 429 errors.
--     Run this whenever regenerating the DB from scratch to apply all overrides.
-- ============================================================

-- ── VISIBILITY ───────────────────────────────────────────────

UPDATE geo_analysis_metrics SET sql_override =
'SELECT ROUND(COALESCE(AVG(100.0 / NULLIF(mention_position, 0)), 0)::numeric, 2)
FROM geo_company_mentions
WHERE client_id = $1 AND is_own_brand = true
  AND executed_at >= $2 AND executed_at <= $3;',
updated_at = NOW() WHERE variable_name = 'visibility_score';

UPDATE geo_analysis_metrics SET sql_override =
'WITH cp AS (
    SELECT COALESCE(AVG(100.0 / NULLIF(mention_position, 0)), 0) AS score
    FROM geo_company_mentions
    WHERE client_id = $1 AND is_own_brand = true AND executed_at >= $2 AND executed_at <= $3
), pp AS (
    SELECT COALESCE(AVG(100.0 / NULLIF(mention_position, 0)), 0) AS score
    FROM geo_company_mentions
    WHERE client_id = $1 AND is_own_brand = true
      AND executed_at >= $2 - ($3 - $2) AND executed_at < $2
)
SELECT ROUND(((cp.score - pp.score) / NULLIF(pp.score, 0) * 100.0)::numeric, 2)
FROM cp, pp;',
updated_at = NOW() WHERE variable_name = 'visibility_wow_change';

UPDATE geo_analysis_metrics SET sql_override =
'WITH daily AS (
    SELECT DATE(executed_at) AS dt, AVG(100.0 / NULLIF(mention_position, 0)) AS score
    FROM geo_company_mentions WHERE client_id = $1 AND is_own_brand = true
    GROUP BY DATE(executed_at) ORDER BY dt DESC LIMIT 2
), ranked AS (SELECT score, ROW_NUMBER() OVER (ORDER BY dt DESC) AS rn FROM daily)
SELECT CASE WHEN MAX(CASE WHEN rn=1 THEN score END) >= MAX(CASE WHEN rn=2 THEN score END)
            THEN ''increased'' ELSE ''decreased'' END FROM ranked;',
updated_at = NOW() WHERE variable_name = 'visibility_direction';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT ROUND(AVG(mention_position)::numeric, 2)
FROM geo_company_mentions
WHERE client_id = $1 AND is_own_brand = true
  AND executed_at >= $2 AND executed_at <= $3;',
updated_at = NOW() WHERE variable_name = 'visibility_rank';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT ROUND(
    COUNT(*) FILTER (WHERE is_own_brand = true) * 100.0 / NULLIF(COUNT(*), 0), 2)
FROM geo_company_mentions
WHERE client_id = $1 AND executed_at >= $2 AND executed_at <= $3;',
updated_at = NOW() WHERE variable_name = 'share_of_voice';

UPDATE geo_analysis_metrics SET sql_override =
'WITH cp AS (
    SELECT COUNT(*) FILTER (WHERE is_own_brand=true)*100.0/NULLIF(COUNT(*),0) AS sov
    FROM geo_company_mentions WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3
), pp AS (
    SELECT COUNT(*) FILTER (WHERE is_own_brand=true)*100.0/NULLIF(COUNT(*),0) AS sov
    FROM geo_company_mentions WHERE client_id=$1
      AND executed_at>=$2-($3-$2) AND executed_at<$2
)
SELECT ROUND(((cp.sov-pp.sov)/NULLIF(pp.sov,0)*100.0)::numeric,2) FROM cp,pp;',
updated_at = NOW() WHERE variable_name = 'sov_wow_change';

UPDATE geo_analysis_metrics SET sql_override =
'WITH daily AS (
    SELECT DATE(executed_at) AS dt,
           AVG(100.0 / NULLIF(mention_position, 0)) AS score
    FROM geo_company_mentions WHERE client_id=$1 AND is_own_brand=true
    GROUP BY DATE(executed_at) ORDER BY dt DESC LIMIT 2
), ranked AS (SELECT score, ROW_NUMBER() OVER (ORDER BY dt DESC) AS rn FROM daily)
SELECT ROUND(
    ((MAX(CASE WHEN rn=1 THEN score END) - MAX(CASE WHEN rn=2 THEN score END)) /
     NULLIF(MAX(CASE WHEN rn=2 THEN score END),0) * 100.0)::numeric, 2)
FROM ranked;',
updated_at = NOW() WHERE variable_name = 'visibility_dod_change';

UPDATE geo_analysis_metrics SET sql_override =
'WITH daily AS (
    SELECT DATE(executed_at) AS dt,
           COUNT(*) FILTER (WHERE is_own_brand=true)*100.0/NULLIF(COUNT(*),0) AS sov
    FROM geo_company_mentions WHERE client_id=$1
    GROUP BY DATE(executed_at) ORDER BY dt DESC LIMIT 2
), ranked AS (SELECT sov, ROW_NUMBER() OVER (ORDER BY dt DESC) AS rn FROM daily)
SELECT ROUND(
    ((MAX(CASE WHEN rn=1 THEN sov END)-MAX(CASE WHEN rn=2 THEN sov END)) /
     NULLIF(MAX(CASE WHEN rn=2 THEN sov END),0)*100.0)::numeric, 2)
FROM ranked;',
updated_at = NOW() WHERE variable_name = 'sov_dod_change';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COUNT(*) FROM geo_company_mentions
WHERE client_id=$1 AND is_own_brand=true AND executed_at>=$2 AND executed_at<=$3;',
updated_at = NOW() WHERE variable_name = 'total_mention_count';

UPDATE geo_analysis_metrics SET sql_override =
'WITH cp AS (SELECT COUNT(*) AS cnt FROM geo_company_mentions WHERE client_id=$1 AND is_own_brand=true AND executed_at>=$2 AND executed_at<=$3),
     pp AS (SELECT COUNT(*) AS cnt FROM geo_company_mentions WHERE client_id=$1 AND is_own_brand=true AND executed_at>=$2-($3-$2) AND executed_at<$2)
SELECT ROUND(((cp.cnt-pp.cnt)::numeric/NULLIF(pp.cnt,0)*100.0),2) FROM cp,pp;',
updated_at = NOW() WHERE variable_name = 'mention_count_wow_change';

UPDATE geo_analysis_metrics SET sql_override =
'WITH top_brands AS (
    SELECT COALESCE(company_name,''Unknown'') AS brand,
           COUNT(*) AS mentions,
           ROUND(AVG(mention_position)::numeric,2) AS avg_pos
    FROM geo_company_mentions
    WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3
    GROUP BY company_name ORDER BY mentions DESC LIMIT 10
)
SELECT ''| Brand | Mentions | Avg Position |'' || CHR(10) ||
       ''|---|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||brand||'' | ''||mentions::text||'' | ''||avg_pos::text||'' |'',
           CHR(10) ORDER BY mentions DESC), '''')
FROM top_brands;',
updated_at = NOW() WHERE variable_name = 'top_brand_table';

UPDATE geo_analysis_metrics SET sql_override =
'WITH ps AS (
    SELECT r.platform,
           ROUND(COALESCE(AVG(100.0/NULLIF(m.mention_position,0)),0)::numeric,2) AS score
    FROM geo_company_mentions m
    JOIN geo_results r ON m.result_id=r.result_id
    WHERE m.client_id=$1 AND m.is_own_brand=true AND m.executed_at>=$2 AND m.executed_at<=$3
    GROUP BY r.platform ORDER BY score DESC
)
SELECT ''| Platform | Visibility Score |'' || CHR(10) ||
       ''|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||COALESCE(platform,''Unknown'')||'' | ''||score::text||'' |'',
           CHR(10) ORDER BY score DESC), '''')
FROM ps;',
updated_at = NOW() WHERE variable_name = 'visibility_by_platform';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COALESCE(
    (SELECT gr.topic_name
     FROM geo_company_mentions m JOIN geo_results gr ON m.result_id=gr.result_id
     WHERE m.client_id=$1 AND m.is_own_brand=true AND m.executed_at>=$2 AND m.executed_at<=$3
     GROUP BY gr.topic_name
     ORDER BY AVG(100.0/NULLIF(m.mention_position,0)) DESC LIMIT 1),
    ''N/A'');',
updated_at = NOW() WHERE variable_name = 'top_visibility_prompt';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COALESCE(json_agg(json_build_object(
    ''platform'', platform, ''count'', cnt,
    ''avg_position'', avg_pos, ''visibility_score'', vis_score
) ORDER BY vis_score DESC)::text, ''[]'')
FROM (
    SELECT r.platform, COUNT(*) AS cnt,
           ROUND(AVG(m.mention_position)::numeric,2) AS avg_pos,
           ROUND(AVG(100.0/NULLIF(m.mention_position,0))::numeric,2) AS vis_score
    FROM geo_company_mentions m JOIN geo_results r ON m.result_id=r.result_id
    WHERE m.client_id=$1 AND m.is_own_brand=true AND m.executed_at>=$2 AND m.executed_at<=$3
    GROUP BY r.platform
) t;',
updated_at = NOW() WHERE variable_name = 'platform_breakdown_json';


-- ── CITATION ─────────────────────────────────────────────────

UPDATE geo_analysis_metrics SET sql_override =
'SELECT ROUND(COALESCE(
    COUNT(*) FILTER (WHERE source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1))
    * 100.0 / NULLIF(COUNT(*),0), 0)::numeric, 2)
FROM geo_citations WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3;',
updated_at = NOW() WHERE variable_name = 'citation_share';

UPDATE geo_analysis_metrics SET sql_override =
'WITH cp AS (
    SELECT COALESCE(
        COUNT(*) FILTER (WHERE source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1))
        *100.0/NULLIF(COUNT(*),0),0) AS share
    FROM geo_citations WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3
), pp AS (
    SELECT COALESCE(
        COUNT(*) FILTER (WHERE source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1))
        *100.0/NULLIF(COUNT(*),0),0) AS share
    FROM geo_citations WHERE client_id=$1 AND executed_at>=$2-($3-$2) AND executed_at<$2
)
SELECT ROUND(((cp.share-pp.share)/NULLIF(pp.share,0)*100.0)::numeric,2) FROM cp,pp;',
updated_at = NOW() WHERE variable_name = 'citation_share_wow_change';

UPDATE geo_analysis_metrics SET sql_override =
'WITH daily AS (
    SELECT DATE(executed_at) AS dt,
           COUNT(*) FILTER (WHERE source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1))
           *100.0/NULLIF(COUNT(*),0) AS share
    FROM geo_citations WHERE client_id=$1
    GROUP BY DATE(executed_at) ORDER BY dt DESC LIMIT 2
), ranked AS (SELECT share, ROW_NUMBER() OVER (ORDER BY dt DESC) AS rn FROM daily)
SELECT CASE WHEN MAX(CASE WHEN rn=1 THEN share END) >= MAX(CASE WHEN rn=2 THEN share END)
            THEN ''increased'' ELSE ''decreased'' END FROM ranked;',
updated_at = NOW() WHERE variable_name = 'citation_direction';

UPDATE geo_analysis_metrics SET sql_override =
'WITH daily AS (
    SELECT DATE(executed_at) AS dt,
           COUNT(*) FILTER (WHERE source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1))
           *100.0/NULLIF(COUNT(*),0) AS share
    FROM geo_citations WHERE client_id=$1
    GROUP BY DATE(executed_at) ORDER BY dt DESC LIMIT 2
), ranked AS (SELECT share, ROW_NUMBER() OVER (ORDER BY dt DESC) AS rn FROM daily)
SELECT ROUND(
    ((MAX(CASE WHEN rn=1 THEN share END)-MAX(CASE WHEN rn=2 THEN share END)) /
     NULLIF(MAX(CASE WHEN rn=2 THEN share END),0)*100.0)::numeric, 2)
FROM ranked;',
updated_at = NOW() WHERE variable_name = 'citation_share_dod_change';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COUNT(*) FROM geo_citations
WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3;',
updated_at = NOW() WHERE variable_name = 'total_citation_count';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COUNT(*) FROM geo_citations
WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3
  AND source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1);',
updated_at = NOW() WHERE variable_name = 'own_domain_citation_count';

UPDATE geo_analysis_metrics SET sql_override =
'WITH top_domains AS (
    SELECT c.source_domain,
           COUNT(*) AS citations,
           MAX(c.domain_category) AS category,
           CASE WHEN MAX(cd.domain) IS NOT NULL THEN ''Yes'' ELSE ''No'' END AS own_domain
    FROM geo_citations c
    LEFT JOIN geo_client_domains cd ON cd.client_id=$1 AND cd.domain=c.source_domain
    WHERE c.client_id=$1 AND c.executed_at>=$2 AND c.executed_at<=$3
    GROUP BY c.source_domain ORDER BY citations DESC LIMIT 20
)
SELECT ''| Domain | Citations | Category | Own Domain |'' || CHR(10) ||
       ''|---|---|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||COALESCE(source_domain,''Unknown'')||'' | ''||citations::text||
           '' | ''||COALESCE(category,''Unknown'')||'' | ''||own_domain||'' |'',
           CHR(10) ORDER BY citations DESC), '''')
FROM top_domains;',
updated_at = NOW() WHERE variable_name = 'top_citation_table';

UPDATE geo_analysis_metrics SET sql_override =
'WITH ps AS (
    SELECT r.platform,
           COUNT(*) FILTER (WHERE c.source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1)) AS own_cnt,
           COUNT(*) AS total_cnt,
           ROUND(COUNT(*) FILTER (WHERE c.source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1))*100.0/NULLIF(COUNT(*),0),2) AS share_pct
    FROM geo_citations c JOIN geo_results r ON c.result_id=r.result_id
    WHERE c.client_id=$1 AND c.executed_at>=$2 AND c.executed_at<=$3
    GROUP BY r.platform
)
SELECT ''| Platform | Own Citations | Total Citations | Share % |'' || CHR(10) ||
       ''|---|---|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||COALESCE(platform,''Unknown'')||'' | ''||own_cnt::text||
           '' | ''||total_cnt::text||'' | ''||share_pct::text||''% |'',
           CHR(10) ORDER BY total_cnt DESC), '''')
FROM ps;',
updated_at = NOW() WHERE variable_name = 'citation_by_platform';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COUNT(*) FROM geo_citations
WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3 AND is_citation_pill=true;',
updated_at = NOW() WHERE variable_name = 'citation_pill_count';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COUNT(DISTINCT c.source_domain) FROM geo_citations c
WHERE c.client_id=$1 AND c.executed_at>=$2 AND c.executed_at<=$3
  AND c.source_domain NOT IN (
      SELECT DISTINCT source_domain FROM geo_citations
      WHERE client_id=$1 AND executed_at>=$2-($3-$2) AND executed_at<$2);',
updated_at = NOW() WHERE variable_name = 'new_domains_this_period';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COUNT(DISTINCT c.source_domain) FROM geo_citations c
WHERE c.client_id=$1 AND c.executed_at>=$2-($3-$2) AND c.executed_at<$2
  AND c.source_domain NOT IN (
      SELECT DISTINCT source_domain FROM geo_citations
      WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3);',
updated_at = NOW() WHERE variable_name = 'dropped_domains_this_period';

UPDATE geo_analysis_metrics SET sql_override =
'WITH cat_stats AS (
    SELECT COALESCE(c.domain_category, dc.category, ''Unknown'') AS category,
           COUNT(*) AS cnt,
           ROUND(COUNT(*)*100.0/NULLIF(SUM(COUNT(*)) OVER (),0),2) AS share_pct
    FROM geo_citations c
    LEFT JOIN geo_domain_categories dc ON dc.domain=c.source_domain
    WHERE c.client_id=$1 AND c.executed_at>=$2 AND c.executed_at<=$3
    GROUP BY COALESCE(c.domain_category,dc.category,''Unknown'')
    ORDER BY cnt DESC
)
SELECT ''| Category | Citation Count | Share % |'' || CHR(10) ||
       ''|---|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||category||'' | ''||cnt::text||'' | ''||share_pct::text||''% |'',
           CHR(10) ORDER BY cnt DESC), '''')
FROM cat_stats;',
updated_at = NOW() WHERE variable_name = 'category_breakdown_table';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COALESCE(json_agg(json_build_object(
    ''date'', dt, ''total_citations'', total_cnt, ''own_domain_citations'', own_cnt
) ORDER BY dt)::text, ''[]'')
FROM (
    SELECT DATE(c.executed_at) AS dt,
           COUNT(*) AS total_cnt,
           COUNT(*) FILTER (WHERE c.source_domain IN (SELECT domain FROM geo_client_domains WHERE client_id=$1)) AS own_cnt
    FROM geo_citations c WHERE c.client_id=$1 AND c.executed_at>=$2 AND c.executed_at<=$3
    GROUP BY DATE(c.executed_at)
) t;',
updated_at = NOW() WHERE variable_name = 'citation_trend_json';


-- ── SENTIMENT ────────────────────────────────────────────────

UPDATE geo_analysis_metrics SET sql_override =
'SELECT ROUND(COALESCE(
    COUNT(*) FILTER (WHERE sentiment=''Positive'')*100.0/NULLIF(COUNT(*),0), 0)::numeric, 2)
FROM geo_sentiment_results WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3;',
updated_at = NOW() WHERE variable_name = 'positive_ratio';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT ROUND(COALESCE(
    COUNT(*) FILTER (WHERE sentiment=''Negative'')*100.0/NULLIF(COUNT(*),0), 0)::numeric, 2)
FROM geo_sentiment_results WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3;',
updated_at = NOW() WHERE variable_name = 'negative_ratio';

UPDATE geo_analysis_metrics SET sql_override =
'WITH cp AS (
    SELECT COALESCE(COUNT(*) FILTER (WHERE sentiment=''Positive'')*100.0/NULLIF(COUNT(*),0),0) AS ratio
    FROM geo_sentiment_results WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3
), pp AS (
    SELECT COALESCE(COUNT(*) FILTER (WHERE sentiment=''Positive'')*100.0/NULLIF(COUNT(*),0),0) AS ratio
    FROM geo_sentiment_results WHERE client_id=$1 AND executed_at>=$2-($3-$2) AND executed_at<$2
)
SELECT ROUND(((cp.ratio-pp.ratio)/NULLIF(pp.ratio,0)*100.0)::numeric,2) FROM cp,pp;',
updated_at = NOW() WHERE variable_name = 'sentiment_wow_change';

UPDATE geo_analysis_metrics SET sql_override =
'WITH daily AS (
    SELECT DATE(executed_at) AS dt,
           COUNT(*) FILTER (WHERE sentiment=''Positive'')*100.0/NULLIF(COUNT(*),0) AS ratio
    FROM geo_sentiment_results WHERE client_id=$1
    GROUP BY DATE(executed_at) ORDER BY dt DESC LIMIT 2
), ranked AS (SELECT ratio, ROW_NUMBER() OVER (ORDER BY dt DESC) AS rn FROM daily)
SELECT CASE WHEN MAX(CASE WHEN rn=1 THEN ratio END) >= MAX(CASE WHEN rn=2 THEN ratio END)
            THEN ''increased'' ELSE ''decreased'' END FROM ranked;',
updated_at = NOW() WHERE variable_name = 'sentiment_direction';

UPDATE geo_analysis_metrics SET sql_override =
'WITH daily AS (
    SELECT DATE(executed_at) AS dt,
           COUNT(*) FILTER (WHERE sentiment=''Positive'')*100.0/NULLIF(COUNT(*),0) AS ratio
    FROM geo_sentiment_results WHERE client_id=$1
    GROUP BY DATE(executed_at) ORDER BY dt DESC LIMIT 2
), ranked AS (SELECT ratio, ROW_NUMBER() OVER (ORDER BY dt DESC) AS rn FROM daily)
SELECT ROUND(
    ((MAX(CASE WHEN rn=1 THEN ratio END)-MAX(CASE WHEN rn=2 THEN ratio END)) /
     NULLIF(MAX(CASE WHEN rn=2 THEN ratio END),0)*100.0)::numeric, 2)
FROM ranked;',
updated_at = NOW() WHERE variable_name = 'sentiment_dod_change';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COUNT(*) FROM geo_sentiment_results
WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3;',
updated_at = NOW() WHERE variable_name = 'total_sentiment_count';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT ROUND(AVG(confidence)::numeric,3) FROM geo_sentiment_results
WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3;',
updated_at = NOW() WHERE variable_name = 'avg_confidence';

UPDATE geo_analysis_metrics SET sql_override =
'WITH top_themes AS (
    SELECT theme_name, COUNT(*) AS mentions
    FROM geo_sentiment_themes
    WHERE client_id=$1 AND sentiment=''Positive'' AND executed_at>=$2 AND executed_at<=$3
    GROUP BY theme_name ORDER BY mentions DESC LIMIT 10
)
SELECT ''| Theme | Mentions |'' || CHR(10) ||
       ''|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||theme_name||'' | ''||mentions::text||'' |'',
           CHR(10) ORDER BY mentions DESC), '''')
FROM top_themes;',
updated_at = NOW() WHERE variable_name = 'top_positive_themes';

UPDATE geo_analysis_metrics SET sql_override =
'WITH top_themes AS (
    SELECT theme_name, COUNT(*) AS mentions
    FROM geo_sentiment_themes
    WHERE client_id=$1 AND sentiment=''Negative'' AND executed_at>=$2 AND executed_at<=$3
    GROUP BY theme_name ORDER BY mentions DESC LIMIT 10
)
SELECT ''| Theme | Mentions |'' || CHR(10) ||
       ''|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||theme_name||'' | ''||mentions::text||'' |'',
           CHR(10) ORDER BY mentions DESC), '''')
FROM top_themes;',
updated_at = NOW() WHERE variable_name = 'top_negative_themes';

UPDATE geo_analysis_metrics SET sql_override =
'WITH trend AS (
    SELECT DATE(executed_at) AS period,
           ROUND(COUNT(*) FILTER (WHERE sentiment=''Positive'')*100.0/NULLIF(COUNT(*),0),2) AS pos_pct,
           ROUND(COUNT(*) FILTER (WHERE sentiment=''Negative'')*100.0/NULLIF(COUNT(*),0),2) AS neg_pct
    FROM geo_sentiment_results WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3
    GROUP BY DATE(executed_at) ORDER BY period
)
SELECT ''| Period | Positive % | Negative % |'' || CHR(10) ||
       ''|---|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||period::text||'' | ''||pos_pct::text||''% | ''||neg_pct::text||''% |'',
           CHR(10) ORDER BY period), '''')
FROM trend;',
updated_at = NOW() WHERE variable_name = 'sentiment_trend_table';

UPDATE geo_analysis_metrics SET sql_override =
'WITH topic_stats AS (
    SELECT gr.topic_name,
           ROUND(COUNT(*) FILTER (WHERE sr.sentiment=''Positive'')*100.0/NULLIF(COUNT(*),0),2) AS pos_pct,
           ROUND(COUNT(*) FILTER (WHERE sr.sentiment=''Negative'')*100.0/NULLIF(COUNT(*),0),2) AS neg_pct,
           COUNT(*) AS cnt
    FROM geo_sentiment_results sr
    JOIN geo_results gr ON sr.result_id=gr.result_id AND gr.client_id=sr.client_id
    WHERE sr.client_id=$1 AND sr.executed_at>=$2 AND sr.executed_at<=$3
    GROUP BY gr.topic_name ORDER BY cnt DESC
)
SELECT ''| Topic | Positive % | Negative % | Count |'' || CHR(10) ||
       ''|---|---|---|---|'' || CHR(10) ||
       COALESCE(STRING_AGG(
           ''| ''||COALESCE(topic_name,''Unknown'')||'' | ''||pos_pct::text||''% | ''||neg_pct::text||''% | ''||cnt::text||'' |'',
           CHR(10) ORDER BY cnt DESC), '''')
FROM topic_stats;',
updated_at = NOW() WHERE variable_name = 'sentiment_by_topic';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COALESCE(json_agg(json_build_object(
    ''date'', dt, ''positive_count'', pos_cnt,
    ''negative_count'', neg_cnt, ''positive_ratio'', pos_ratio
) ORDER BY dt)::text, ''[]'')
FROM (
    SELECT DATE(executed_at) AS dt,
           COUNT(*) FILTER (WHERE sentiment=''Positive'') AS pos_cnt,
           COUNT(*) FILTER (WHERE sentiment=''Negative'') AS neg_cnt,
           ROUND(COUNT(*) FILTER (WHERE sentiment=''Positive'')*100.0/NULLIF(COUNT(*),0),2) AS pos_ratio
    FROM geo_sentiment_results WHERE client_id=$1 AND executed_at>=$2 AND executed_at<=$3
    GROUP BY DATE(executed_at)
) t;',
updated_at = NOW() WHERE variable_name = 'sentiment_trend_json';

UPDATE geo_analysis_metrics SET sql_override =
'SELECT COALESCE(STRING_AGG(theme_name||'': ''||COALESCE(excerpt,''''), E''\n'' ORDER BY cnt DESC),
    ''No concerning themes found.'')
FROM (
    SELECT theme_name, COALESCE(excerpt,'''') AS excerpt, COUNT(*) AS cnt
    FROM geo_sentiment_themes
    WHERE client_id=$1 AND sentiment=''Negative'' AND executed_at>=$2 AND executed_at<=$3
    GROUP BY theme_name, excerpt ORDER BY cnt DESC LIMIT 5
) t;',
updated_at = NOW() WHERE variable_name = 'concern_themes_excerpt';
