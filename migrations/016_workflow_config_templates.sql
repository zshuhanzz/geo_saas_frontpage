-- =============================================================================
-- Migration 016: Template-Driven Workflow Configuration
-- Run: psql $DATABASE_URL -f migrations/016_workflow_config_templates.sql
-- =============================================================================
-- Extracts ALL hardcoded workflow configuration from frontend TSX into database:
--   1. geo_workflow_config  — Shared config items (goals, content types, platforms,
--      domains, depth options, methodology snippets, recommended charts, workflow steps)
--   2. Enriches geo_report_templates with a `defaults` JSONB column for per-template
--      pre-selections (goal, content_type, platforms, depth, domains, etc.)
--   3. Re-inserts ALL analysis + content templates (including blank templates)
-- =============================================================================


-- ============================================================
-- 1. geo_workflow_config — Flexible typed config store
-- ============================================================
-- One row per config item. Frontend fetches by (scope, config_type).
-- parent_key links child items to a parent (e.g. recommended_chart → goal).

DROP TABLE IF EXISTS geo_workflow_config CASCADE;

CREATE TABLE geo_workflow_config (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_type  TEXT NOT NULL,        -- 'goal' | 'content_type' | 'domain' | 'platform'
                                       -- | 'depth' | 'methodology_snippet' | 'recommended_chart'
                                       -- | 'workflow_step' | 'sort_option'
    scope        TEXT NOT NULL,        -- 'analysis' | 'content_generation' | 'shared'
    key          TEXT NOT NULL,        -- Unique identifier within (scope, config_type)
    parent_key   TEXT,                 -- For hierarchy: e.g. snippet category, chart→goal
    value        JSONB NOT NULL,       -- All properties for this config item
    sort_order   INTEGER DEFAULT 0,
    is_active    BOOLEAN DEFAULT true,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_wf_config_unique ON geo_workflow_config (scope, config_type, key)
    WHERE parent_key IS NULL;
CREATE INDEX idx_wf_config_scope_type ON geo_workflow_config (scope, config_type, sort_order);
CREATE INDEX idx_wf_config_parent ON geo_workflow_config (scope, config_type, parent_key);


-- ============================================================
-- 2. Enrich geo_report_templates with defaults JSONB
-- ============================================================
ALTER TABLE geo_report_templates
    ADD COLUMN IF NOT EXISTS defaults JSONB DEFAULT '{}';

-- Comment: defaults stores per-template pre-selections, e.g.:
-- Analysis: {"goal": "benchmark", "platforms": ["chatgpt","gemini"], "depth": "standard"}
-- Content:  {"goal": "visibility_boost", "content_type": "faq", "count": 5, "depth": "standard"}


-- ============================================================
-- 3. Shared Config: Domains
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('domain', 'shared', 'visibility',
 '{"label": "可见度", "color": "bg-blue-500/10 text-blue-400 border-blue-500/20", "icon": "🔍"}', 1),
('domain', 'shared', 'citation',
 '{"label": "引用", "color": "bg-purple-500/10 text-purple-400 border-purple-500/20", "icon": "📎"}', 2),
('domain', 'shared', 'sentiment',
 '{"label": "情绪", "color": "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", "icon": "💬"}', 3);


-- ============================================================
-- 4. Shared Config: Platforms
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('platform', 'shared', 'chatgpt',
 '{"label": "ChatGPT", "icon": "🤖", "color": "text-emerald-400 border-emerald-500/30 bg-emerald-500/5"}', 1),
('platform', 'shared', 'gemini',
 '{"label": "Gemini", "icon": "✨", "color": "text-indigo-400 border-indigo-500/30 bg-indigo-500/5"}', 2),
('platform', 'shared', 'aimode',
 '{"label": "AI Mode", "icon": "🔍", "color": "text-amber-400 border-amber-500/30 bg-amber-500/5"}', 3);


-- ============================================================
-- 5. Analysis Config: Goals
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('goal', 'analysis', 'benchmark',
 '{
   "label": "竞品对标",
   "description": "对比自有品牌与竞品在 AI 搜索引擎中的表现差异",
   "icon": "Target",
   "recommended_domains": ["visibility", "citation"],
   "color": "text-blue-400 border-blue-500/30 bg-blue-500/5"
 }', 1),
('goal', 'analysis', 'trend',
 '{
   "label": "趋势诊断",
   "description": "分析品牌在 AI 引擎中的可见度、引用和情绪变化趋势",
   "icon": "TrendingUp",
   "recommended_domains": ["visibility", "citation", "sentiment"],
   "color": "text-emerald-400 border-emerald-500/30 bg-emerald-500/5"
 }', 2),
('goal', 'analysis', 'opportunity',
 '{
   "label": "优化机会发现",
   "description": "识别品牌在低分 Prompt 中的优化空间，聚焦 RAFT 评分提升",
   "icon": "Search",
   "recommended_domains": ["visibility", "citation"],
   "color": "text-amber-400 border-amber-500/30 bg-amber-500/5"
 }', 3),
('goal', 'analysis', 'health',
 '{
   "label": "全面健康检查",
   "description": "全域扫描品牌在所有 AI 引擎中的综合表现",
   "icon": "Shield",
   "recommended_domains": ["visibility", "citation", "sentiment"],
   "color": "text-purple-400 border-purple-500/30 bg-purple-500/5"
 }', 4);


-- ============================================================
-- 6. Analysis Config: Recommended Charts (per goal)
-- ============================================================
-- parent_key = goal key
INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order) VALUES
-- benchmark
('recommended_chart', 'analysis', 'benchmark_chart_1', 'benchmark',
 '{"nl_query": "各品牌在所有 AI 平台的总提及次数对比（柱状图）", "chart_type": "bar"}', 1),
('recommended_chart', 'analysis', 'benchmark_chart_2', 'benchmark',
 '{"nl_query": "自有品牌 vs 竞品的 SOV（Share of Voice）趋势对比", "chart_type": "line"}', 2),
('recommended_chart', 'analysis', 'benchmark_chart_3', 'benchmark',
 '{"nl_query": "各品牌被引用为推荐来源的次数对比", "chart_type": "bar"}', 3),
-- trend
('recommended_chart', 'analysis', 'trend_chart_1', 'trend',
 '{"nl_query": "过去时间范围内，自有品牌每日可见度提及次数趋势", "chart_type": "line"}', 1),
('recommended_chart', 'analysis', 'trend_chart_2', 'trend',
 '{"nl_query": "各 AI 平台的品牌引用率变化趋势", "chart_type": "line"}', 2),
('recommended_chart', 'analysis', 'trend_chart_3', 'trend',
 '{"nl_query": "品牌情绪评分（正面/中性/负面）随时间变化趋势", "chart_type": "line"}', 3),
-- opportunity
('recommended_chart', 'analysis', 'opportunity_chart_1', 'opportunity',
 '{"nl_query": "品牌可见度最低的 Top 10 Prompt（需要优化）", "chart_type": "bar"}', 1),
('recommended_chart', 'analysis', 'opportunity_chart_2', 'opportunity',
 '{"nl_query": "各 AI 平台中品牌未被提及的 Prompt 数量", "chart_type": "bar"}', 2),
('recommended_chart', 'analysis', 'opportunity_chart_3', 'opportunity',
 '{"nl_query": "品牌在不同平台的平均提及位置排名", "chart_type": "bar"}', 3),
-- health
('recommended_chart', 'analysis', 'health_chart_1', 'health',
 '{"nl_query": "自有品牌在各 AI 平台的提及次数分布（饼图）", "chart_type": "pie"}', 1),
('recommended_chart', 'analysis', 'health_chart_2', 'health',
 '{"nl_query": "品牌可见度、引用率综合趋势（每日）", "chart_type": "line"}', 2),
('recommended_chart', 'analysis', 'health_chart_3', 'health',
 '{"nl_query": "品牌 vs 竞品在各平台的 SOV 对比", "chart_type": "bar"}', 3),
('recommended_chart', 'analysis', 'health_chart_4', 'health',
 '{"nl_query": "品牌情绪评分分布（正面/中性/负面）", "chart_type": "pie"}', 4);


-- ============================================================
-- 7. Analysis Config: Methodology Snippets
-- ============================================================
-- parent_key = category name
INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order) VALUES
-- RAFT 框架
('methodology_snippet', 'analysis', 'raft_retrievability', 'RAFT 框架',
 '{"label": "Retrievability（可检索性）", "snippet": "请分析品牌在AI搜索引擎中的可检索性，包括被提及的频率、位置排名和覆盖的Prompt范围。"}', 1),
('methodology_snippet', 'analysis', 'raft_accuracy', 'RAFT 框架',
 '{"label": "Accuracy（准确性）", "snippet": "请评估AI引擎对品牌信息描述的准确性，识别错误或过时的品牌描述。"}', 2),
('methodology_snippet', 'analysis', 'raft_fluency', 'RAFT 框架',
 '{"label": "Fluency（流畅度）", "snippet": "请分析AI引擎在推荐品牌时的语言流畅度和自然度，评估品牌融入回答的质量。"}', 3),
('methodology_snippet', 'analysis', 'raft_trustworthiness', 'RAFT 框架',
 '{"label": "Trustworthiness（可信度）", "snippet": "请评估AI引擎引用品牌时的可信度，包括引用来源质量和推荐语气强度。"}', 4),
-- 竞品分析
('methodology_snippet', 'analysis', 'competitor_sov', '竞品分析',
 '{"label": "SOV 对比分析", "snippet": "请对比自有品牌与竞品的 Share of Voice，分析各品牌在AI搜索中的声量占比差异。"}', 1),
('methodology_snippet', 'analysis', 'competitor_advantage', '竞品分析',
 '{"label": "竞品优势识别", "snippet": "请识别竞品在哪些Prompt和平台上表现优于自有品牌，分析其优势原因。"}', 2),
-- 趋势洞察
('methodology_snippet', 'analysis', 'trend_inflection', '趋势洞察',
 '{"label": "趋势拐点分析", "snippet": "请识别品牌可见度/引用率的关键拐点，分析造成变化的可能原因。"}', 1),
('methodology_snippet', 'analysis', 'trend_platform_diff', '趋势洞察',
 '{"label": "平台差异分析", "snippet": "请对比品牌在不同AI平台（ChatGPT/Gemini/AI Mode）的表现差异，识别平台偏好。"}', 2);


-- ============================================================
-- 8. Analysis Config: Depth Options
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('depth', 'analysis', 'quick',
 '{"label": "快速概览", "description": "精简输出，聚焦 Top 3 发现", "icon": "⚡"}', 1),
('depth', 'analysis', 'standard',
 '{"label": "标准分析", "description": "完整报告，覆盖全部领域", "icon": "📊"}', 2),
('depth', 'analysis', 'deep',
 '{"label": "深度诊断", "description": "逐 Prompt 逐平台拆解分析", "icon": "🔬"}', 3);


-- ============================================================
-- 9. Analysis Config: Workflow Steps
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('workflow_step', 'analysis', 'goal',
 '{"num": 1, "label": "分析目标"}', 1),
('workflow_step', 'analysis', 'data',
 '{"num": 2, "label": "数据选择"}', 2),
('workflow_step', 'analysis', 'charts',
 '{"num": 3, "label": "配置图表"}', 3),
('workflow_step', 'analysis', 'prompt',
 '{"num": 4, "label": "Prompt 编辑"}', 4),
('workflow_step', 'analysis', 'confirm',
 '{"num": 5, "label": "确认执行"}', 5);


-- ============================================================
-- 10. Content Config: Goals
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('goal', 'content_generation', 'visibility_boost',
 '{
   "label": "可见度提升",
   "description": "提升品牌在 AI 搜索中被提及的频率和位置排名",
   "icon": "Target",
   "recommended_types": ["faq", "aeo_article"],
   "recommended_domains": ["visibility", "citation"],
   "default_sort": "visibility",
   "color": "text-blue-400 border-blue-500/30 bg-blue-500/5"
 }', 1),
('goal', 'content_generation', 'citation_optimize',
 '{
   "label": "引用优化",
   "description": "增加品牌被 AI 引擎作为推荐来源引用的次数",
   "icon": "TrendingUp",
   "recommended_types": ["aeo_article", "brief"],
   "recommended_domains": ["citation", "visibility"],
   "default_sort": "citation",
   "color": "text-purple-400 border-purple-500/30 bg-purple-500/5"
 }', 2),
('goal', 'content_generation', 'sentiment_repair',
 '{
   "label": "情绪修复",
   "description": "改善品牌在 AI 引擎回答中的负面描述和情感倾向",
   "icon": "MessageSquare",
   "recommended_types": ["recommendations", "faq"],
   "recommended_domains": ["sentiment", "citation"],
   "default_sort": "sentiment",
   "color": "text-amber-400 border-amber-500/30 bg-amber-500/5"
 }', 3),
('goal', 'content_generation', 'full_optimize',
 '{
   "label": "全面内容优化",
   "description": "多维度提升品牌在 AI 搜索中的综合表现",
   "icon": "Shield",
   "recommended_types": ["faq", "aeo_article", "article", "recommendations", "brief"],
   "recommended_domains": ["visibility", "citation", "sentiment"],
   "default_sort": "visibility",
   "color": "text-emerald-400 border-emerald-500/30 bg-emerald-500/5"
 }', 4);


-- ============================================================
-- 11. Content Config: Content Types
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('content_type', 'content_generation', 'faq',
 '{"label": "FAQ 内容", "icon": "📋", "description": "生成常见问题与回答，提升品牌在 AI 搜索中的结构化信息"}', 1),
('content_type', 'content_generation', 'aeo_article',
 '{"label": "AEO 文章", "icon": "🤖", "description": "AI 引擎优化文章，针对 AI 搜索引擎的引用和推荐优化"}', 2),
('content_type', 'content_generation', 'article',
 '{"label": "SEO 文章", "icon": "✍️", "description": "搜索引擎优化文章，提升传统搜索和 AI 搜索的可见度"}', 3),
('content_type', 'content_generation', 'recommendations',
 '{"label": "优化建议", "icon": "💡", "description": "基于数据分析的内容优化建议和行动计划"}', 4),
('content_type', 'content_generation', 'brief',
 '{"label": "Content Brief", "icon": "📝", "description": "内容简报，为内容团队提供创作方向和关键信息"}', 5);


-- ============================================================
-- 12. Content Config: RAFT Methodology Snippets
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order) VALUES
-- RAFT 四维度
('methodology_snippet', 'content_generation', 'content_raft_retrievability', 'RAFT 四维度',
 '{"label": "Retrievability（可检索性）", "snippet": "确保内容包含目标关键词和语义变体，使AI搜索引擎能够准确检索并关联到品牌。"}', 1),
('methodology_snippet', 'content_generation', 'content_raft_accuracy', 'RAFT 四维度',
 '{"label": "Accuracy（准确性）", "snippet": "内容必须基于产品真实规格和事实，避免夸大或不实描述，确保AI引擎引用时信息准确。"}', 2),
('methodology_snippet', 'content_generation', 'content_raft_fluency', 'RAFT 四维度',
 '{"label": "Fluency（流畅度）", "snippet": "内容应自然流畅，易于AI引擎在回答中无缝引用和整合，避免生硬的营销语言。"}', 3),
('methodology_snippet', 'content_generation', 'content_raft_trustworthiness', 'RAFT 四维度',
 '{"label": "Trustworthiness（可信度）", "snippet": "引用可信来源和数据支撑论点，使用专业语气，提升AI引擎对品牌信息的信任度评分。"}', 4),
-- 内容策略
('methodology_snippet', 'content_generation', 'content_strategy_faq', '内容策略',
 '{"label": "结构化 FAQ", "snippet": "使用问答对格式组织内容，每个问题聚焦一个用户场景，答案精准引用产品事实。"}', 1),
('methodology_snippet', 'content_generation', 'content_strategy_diff', '内容策略',
 '{"label": "竞品差异化", "snippet": "在内容中自然融入品牌与竞品的关键差异点，突出自有品牌的独特优势。"}', 2),
('methodology_snippet', 'content_generation', 'content_strategy_multiplatform', '内容策略',
 '{"label": "多平台适配", "snippet": "考虑不同AI平台的回答风格差异，内容需兼顾简洁性（ChatGPT）和详细性（Perplexity）。"}', 3);


-- ============================================================
-- 13. Content Config: Depth Options
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('depth', 'content_generation', 'quick',
 '{"label": "快速生成", "description": "简明扼要，适合快速产出", "icon": "⚡"}', 1),
('depth', 'content_generation', 'standard',
 '{"label": "标准生成", "description": "完整内容，覆盖 RAFT 四维度", "icon": "📊"}', 2),
('depth', 'content_generation', 'deep',
 '{"label": "深度优化", "description": "逐 Prompt 定制，多轮打磨", "icon": "🔬"}', 3);


-- ============================================================
-- 14. Content Config: Sort Options (for prompt ranking)
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('sort_option', 'content_generation', 'visibility',
 '{"label": "Visibility 最差"}', 1),
('sort_option', 'content_generation', 'citation',
 '{"label": "Citation 最差"}', 2),
('sort_option', 'content_generation', 'sentiment',
 '{"label": "Sentiment 最差"}', 3);


-- ============================================================
-- 15. Content Config: Workflow Steps
-- ============================================================
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order) VALUES
('workflow_step', 'content_generation', 'goal',
 '{"num": 1, "label": "内容目标"}', 1),
('workflow_step', 'content_generation', 'type',
 '{"num": 2, "label": "内容类型"}', 2),
('workflow_step', 'content_generation', 'config',
 '{"num": 3, "label": "目标配置"}', 3),
('workflow_step', 'content_generation', 'prompts',
 '{"num": 4, "label": "Prompt 选择"}', 4),
('workflow_step', 'content_generation', 'strategy',
 '{"num": 5, "label": "数据 & 策略"}', 5),
('workflow_step', 'content_generation', 'model',
 '{"num": 6, "label": "模型 & 定时"}', 6),
('workflow_step', 'content_generation', 'confirm',
 '{"num": 7, "label": "确认执行"}', 7);


-- ============================================================
-- 16. Re-insert ALL templates (DELETE existing built-in first)
-- ============================================================
-- Only delete system built-in templates; preserve user-created custom templates
DELETE FROM geo_report_templates WHERE is_builtin = true;

-- ────────────────────────────────────────────────────────────
-- 16a. Analysis Templates
-- ────────────────────────────────────────────────────────────

-- Blank analysis template (sort_order=0 → appears first)
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    '自定义分析',
    '不预选任何选项，完全自定义所有分析配置',
    '✨',
    ARRAY[]::TEXT[],
    '',
    true, true, 0, 'analysis',
    '{}'::jsonb
);

-- 竞品对标分析
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    '竞品对标分析',
    '对比自有品牌与竞品在 AI 搜索引擎中的可见度和引用表现差异',
    '🎯',
    ARRAY['visibility', 'citation']::TEXT[],
    '请基于以下品牌在各 AI 搜索平台的可见度和引用数据，进行竞品对标分析：

{{visibility_score}} {{share_of_voice}} {{top_brand_table}}
{{citation_share}} {{top_citation_table}}

分析要点：
1. 自有品牌 vs 竞品的 SOV 差距和变化趋势
2. 各平台上竞品的优势 Prompt 和内容策略
3. 品牌引用来源质量对比
4. 可执行的差距缩小策略建议

输出格式：结构化 Markdown 报告，含数据表格和具体建议。',
    true, true, 1, 'analysis',
    '{"goal": "benchmark", "platforms": ["chatgpt", "gemini", "aimode"], "depth": "standard"}'::jsonb
);

-- 趋势诊断分析
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    '趋势诊断分析',
    '分析品牌在 AI 引擎中的可见度、引用和情绪变化趋势，识别关键拐点',
    '📈',
    ARRAY['visibility', 'citation', 'sentiment']::TEXT[],
    '请基于以下品牌时序数据，进行趋势诊断分析：

{{visibility_score}} {{visibility_wow_change}} {{visibility_direction}}
{{citation_share}} {{citation_share_wow_change}} {{citation_direction}}
{{sentiment_overall}} {{sentiment_distribution}} {{sentiment_wow_change}}

分析要点：
1. 各维度的核心趋势方向和变化幅度
2. 识别关键拐点及可能的驱动因素
3. 跨平台趋势一致性分析
4. 下一周期预判和建议

输出格式：Markdown 报告，含趋势总结、拐点分析和前瞻建议。',
    true, true, 2, 'analysis',
    '{"goal": "trend", "platforms": ["chatgpt", "gemini", "aimode"], "depth": "standard", "baseline_type": "previous_period"}'::jsonb
);

-- 优化机会发现
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    '优化机会发现',
    '识别品牌在低分 Prompt 和平台中的优化空间，聚焦 RAFT 评分提升',
    '🔍',
    ARRAY['visibility', 'citation']::TEXT[],
    '请基于以下品牌在 AI 平台中的表现数据，进行优化机会发现分析：

{{visibility_score}} {{top_visibility_prompt}} {{platform_breakdown_json}}
{{citation_share}} {{top_citation_table}}

分析要点：
1. 品牌可见度最低的 Prompt 列表和优化优先级
2. 未被提及的高频用户问题（内容缺口）
3. 按 RAFT 四维度评估当前被引用内容的薄弱环节
4. Quick Win 机会识别（低投入高回报的优化项）
5. 具体的内容优化行动建议

输出格式：Markdown 报告，含优化机会矩阵（影响力 × 难度）、优先级排序和行动清单。',
    true, true, 3, 'analysis',
    '{"goal": "opportunity", "platforms": ["chatgpt", "gemini", "aimode"], "depth": "standard"}'::jsonb
);

-- 全面健康检查
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    '全面健康检查',
    '全域扫描品牌在所有 AI 引擎中的可见度、引用和情绪综合表现',
    '🛡️',
    ARRAY['visibility', 'citation', 'sentiment']::TEXT[],
    '请基于以下品牌全域数据，进行全面 GEO 健康检查：

{{visibility_score}} {{share_of_voice}} {{visibility_by_platform}} {{top_brand_table}}
{{citation_share}} {{own_domain_citation_count}} {{citation_by_platform}} {{top_citation_table}}
{{sentiment_overall}} {{sentiment_distribution}} {{sentiment_by_platform}}

分析要点：
1. GEO 健康评分卡：可见度 / 引用 / 情绪三维度综合得分
2. 各 AI 平台的表现差异和短板
3. 与上一周期的全面对比
4. Top 3 紧急改善项 + Top 3 持续优势项
5. 综合优化路线图建议

输出格式：结构化 Markdown 报告，含评分卡、平台对比矩阵、问题清单和路线图。',
    true, true, 4, 'analysis',
    '{"goal": "health", "platforms": ["chatgpt", "gemini", "aimode"], "depth": "deep", "baseline_type": "previous_period"}'::jsonb
);


-- ────────────────────────────────────────────────────────────
-- 16b. Content Generation Templates
-- ────────────────────────────────────────────────────────────

-- Blank content template
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    '自定义内容',
    '不预选任何选项，完全自定义所有内容生成配置',
    '✨',
    ARRAY[]::TEXT[],
    '',
    true, true, 0, 'content_generation',
    '{}'::jsonb
);

-- FAQ 内容生成
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    'FAQ 内容生成',
    '生成针对 AI 平台检索优化的常见问题解答内容，提升品牌在问答场景中的引用率',
    '📋',
    ARRAY['visibility', 'citation']::TEXT[],
    '你是一位专业的 GEO（Generative Engine Optimization）内容策略师。请基于以下品牌数据和 AI 平台分析结果，生成一组高质量的 FAQ 内容。

要求：
1. **Retrievability（可检索性）**：每个问答必须包含用户在 AI 搜索中常用的自然语言提问方式，覆盖品牌核心关键词
2. **Accuracy（准确性）**：回答必须基于品牌官方数据和真实产品信息，不得编造
3. **Fluency（流畅性）**：回答风格自然、专业，符合品牌调性，适合被 AI 引擎直接引用
4. **Trustworthiness（可信度）**：引用具体数据、权威评测、用户评价等增强可信度

输出格式：Markdown，每个 FAQ 包含 Q（问题）和 A（回答），回答控制在 150-300 字。',
    true, true, 1, 'content_generation',
    '{"goal": "visibility_boost", "content_type": "faq", "count": 5, "depth": "standard", "platforms": ["chatgpt", "gemini"]}'::jsonb
);

-- AEO 优化文章
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    'AEO 优化文章',
    '生成针对 AI 搜索引擎引用优化的结构化文章，提升品牌在 ChatGPT/Gemini/AiMode 中的曝光',
    '🤖',
    ARRAY['visibility', 'citation', 'sentiment']::TEXT[],
    '你是一位专业的 AEO（Answer Engine Optimization）内容专家。请基于品牌的 GEO 分析数据，生成一篇针对 AI 搜索引擎优化的文章。

AEO 核心原则（区别于传统 SEO）：
- **结构化内容**：使用清晰的 H2/H3 标题层级，每段聚焦一个明确主题，方便 AI 引擎抽取
- **可引用片段**：在关键位置提供简洁、权威的总结性语句（50-80字），适合 AI 直接引用
- **数据驱动**：引入具体数字、对比数据、评测结论，增强 AI 对内容的信任度
- **问答嵌入**：在文中自然嵌入 Q&A 格式段落，匹配用户在 AI 平台的提问方式

RAFT 评分标准：
- R（Retrievability）：标题和首段必须包含核心查询词
- A（Accuracy）：所有数据点可追溯，无虚假声明
- F（Fluency）：符合品牌调性，语言自然流畅
- T（Trustworthiness）：引用权威来源，提供证据支撑

输出格式：Markdown 长文（800-1500 字），包含引言、2-3 个主题段落、总结。',
    true, true, 2, 'content_generation',
    '{"goal": "citation_optimize", "content_type": "aeo_article", "count": 1, "depth": "standard", "platforms": ["chatgpt", "gemini", "aimode"]}'::jsonb
);

-- SEO 优化文章
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    'SEO 优化文章',
    '生成传统搜索引擎优化的博客文章，提升品牌在 Google/Bing 自然搜索中的排名',
    '✍️',
    ARRAY['visibility']::TEXT[],
    '你是一位资深 SEO 内容写手。请基于品牌数据和关键词分析，生成一篇搜索引擎优化的博客文章。

SEO 优化要点：
- **关键词布局**：标题、首段、小标题中自然融入目标关键词，关键词密度 1-2%
- **内容深度**：提供全面、有价值的信息，满足用户搜索意图
- **内链外链**：建议可插入的内部链接位置和外部权威引用
- **Meta 信息**：提供 SEO Title（60字符内）和 Meta Description（155字符内）
- **可读性**：短段落、列表、加粗重点，提升用户停留时间

输出格式：Markdown 长文（1000-2000 字），包含 SEO Title、Meta Description、正文。',
    true, true, 3, 'content_generation',
    '{"goal": "visibility_boost", "content_type": "article", "count": 1, "depth": "standard", "platforms": ["chatgpt"]}'::jsonb
);

-- 内容优化建议
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    '内容优化建议',
    '基于当前引用数据和竞品对比，给出提升品牌内容被 AI 引用率的具体建议',
    '💡',
    ARRAY['visibility', 'citation', 'sentiment']::TEXT[],
    '你是一位 GEO 策略顾问。请基于品牌在各 AI 平台的可见度、引用率和情感数据，生成一份内容优化建议报告。

分析维度：
1. **引用差距分析**：对比品牌与竞品在关键 Prompt 下的引用率差距，找出优化机会
2. **内容缺口识别**：哪些高频用户问题品牌内容尚未覆盖？
3. **RAFT 评分诊断**：对现有被引用内容按 R/A/F/T 四维度评分，找出薄弱环节
4. **优先级排序**：按影响力和实施难度排列优化建议，标注 Quick Win 项
5. **竞品策略参考**：分析表现优秀的竞品内容特征，提取可复用的策略

输出格式：Markdown 报告，包含数据摘要、问题诊断、优化建议（按优先级排序）、执行路线图。',
    true, true, 4, 'content_generation',
    '{"goal": "full_optimize", "content_type": "recommendations", "depth": "deep", "platforms": ["chatgpt", "gemini", "aimode"]}'::jsonb
);

-- Content Brief
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type, defaults
) VALUES (
    gen_random_uuid(),
    'Content Brief',
    '为内容团队生成完整的 GEO 内容简报与写作指南，确保产出内容符合 AI 引用优化标准',
    '📝',
    ARRAY['visibility', 'citation']::TEXT[],
    '你是一位 GEO 内容策略总监。请基于品牌数据和 AI 平台分析，生成一份完整的内容简报（Content Brief），供内容团队执行。

Content Brief 结构：
1. **目标概述**：本次内容的业务目标、目标平台、预期效果
2. **目标受众**：用户画像、搜索场景、常见提问方式
3. **核心主题与关键词**：主关键词、长尾关键词、语义相关词
4. **内容大纲**：建议的标题层级和每节要点
5. **RAFT 写作指南**：
   - R：必须包含的检索关键词和问答格式
   - A：需要引用的数据源和事实依据
   - F：品牌调性要求和语言风格指南
   - T：需要引用的权威来源和信任信号
6. **竞品参考**：表现优秀的竞品内容链接和策略分析
7. **发布建议**：推荐的发布渠道、格式、更新频率

输出格式：结构化 Markdown 文档，可直接作为写作任务分配给内容团队。',
    true, true, 5, 'content_generation',
    '{"goal": "citation_optimize", "content_type": "brief", "count": 1, "depth": "standard", "platforms": ["chatgpt", "gemini"]}'::jsonb
);


-- ============================================================
-- 17. Update schema.sql reference comment
-- ============================================================
-- Add to geo_global_settings for frontend config cache TTL (optional)
INSERT INTO geo_global_settings (key, value, description)
VALUES (
    'workflow_config_cache_ttl_seconds',
    '3600',
    'How long the frontend should cache geo_workflow_config data before re-fetching. Default: 1 hour.'
)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;
