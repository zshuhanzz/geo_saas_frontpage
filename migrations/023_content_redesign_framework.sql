-- migrations/023_content_redesign_framework.sql
-- Three-layer optimization framework + content assets for feedback loop

BEGIN;

-- ─── Layer 1 + 2: Optimization Metrics and Sub-goals ────────────────

CREATE TABLE IF NOT EXISTS geo_optimization_metrics (
    id          TEXT PRIMARY KEY,           -- 'readability', 'answerability', 'trustworthy', 'freshness'
    name_zh     TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    description TEXT NOT NULL,
    icon        TEXT DEFAULT '📊',
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS geo_optimization_subgoals (
    id          TEXT PRIMARY KEY,           -- 'content_understandability', 'machine_readability', etc.
    metric_id   TEXT NOT NULL REFERENCES geo_optimization_metrics(id),
    name_zh     TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    description TEXT NOT NULL,
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Layer 3: Strategy definitions ──────────────────────────────────

CREATE TABLE IF NOT EXISTS geo_strategies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT,
    dimensions      JSONB NOT NULL DEFAULT '{}',   -- {instruction, format, tone, constraints, enhancement_rules}
    source_metrics  TEXT[] DEFAULT '{}',            -- metric ids
    source_subgoals TEXT[] DEFAULT '{}',            -- subgoal ids
    content_type    TEXT,                           -- 'faq', 'aeo_article', etc. NULL = any
    generation_method TEXT DEFAULT 'llm_with_postprocess',
    is_seed         BOOLEAN DEFAULT true,          -- seed vs evolved
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Content Assets (feedback loop reservation) ─────────────────────

CREATE TABLE IF NOT EXISTS geo_content_assets (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    content_task_id   UUID REFERENCES geo_agent_tasks(id) ON DELETE SET NULL,
    published_url     TEXT,
    published_platform TEXT,                        -- 'reddit', 'official_site', 'wiki', etc.
    published_at      TIMESTAMPTZ,
    tracking_status   TEXT DEFAULT 'pending',       -- 'pending', 'tracking', 'completed'
    metadata          JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_assets_client ON geo_content_assets(client_id);
CREATE INDEX IF NOT EXISTS idx_content_assets_task ON geo_content_assets(content_task_id);

-- ─── Add analyzer_task_id to geo_agent_tasks for Content→Analyzer link ──

ALTER TABLE geo_agent_tasks ADD COLUMN IF NOT EXISTS analyzer_task_id UUID REFERENCES geo_agent_tasks(id);

-- ─── Seed Layer 1: Metrics ──────────────────────────────────────────

INSERT INTO geo_optimization_metrics (id, name_zh, name_en, description, icon, sort_order)
VALUES
    ('readability',    '可读性',     'Readability',    '内容是否容易被人类理解、被 AI 引擎解析', '📖', 1),
    ('answerability',  '可做答案性', 'Answerability',  '内容是否能直接成为 AI 回答的素材',       '🎯', 2),
    ('trustworthy',    '可信赖性',   'Trustworthy',    '内容是否具备权威性和可验证性',           '🛡️', 3),
    ('freshness',      '时效性',     'Freshness',      '内容是否紧跟热点且保持时效',             '⏰', 4)
ON CONFLICT (id) DO NOTHING;

-- ─── Seed Layer 2: Sub-goals ────────────────────────────────────────

INSERT INTO geo_optimization_subgoals (id, metric_id, name_zh, name_en, description, sort_order)
VALUES
    ('content_understandability', 'readability',   '内容可理解度', 'Content Understandability', '语言清晰、用词精准、目标受众能读懂', 1),
    ('machine_readability',      'readability',   '机器可读性',   'Machine Readability',       '结构清晰（heading hierarchy）、schema markup、AI 能提取干净的答案', 2),
    ('information_presentation', 'answerability', '信息呈现',     'Information Presentation',  '页面上是否直接呈现了 AI 需要的答案信息', 1),
    ('audience_fit',             'answerability', '受众贴合度',   'Audience Fit',              '内容的目的、调性、key message 是否匹配目标受众', 2),
    ('platform_fit',             'answerability', '平台贴合度',   'Platform Fit',              '内容格式/风格是否匹配发布平台（Wiki、Reddit、测评站等）', 3),
    ('authority_eeat',           'trustworthy',   '权威性 (E-E-A-T)', 'Authority (E-E-A-T)', '专业凭证、第一手经验、权威背书', 1),
    ('verifiability',            'trustworthy',   '可验证性',     'Verifiability',             '引用来源、数据有出处、claims 可被第三方验证', 2),
    ('trending_relevance',       'freshness',     '热点相关度',   'Trending Relevance',        '内容是否紧扣当下与品牌/产品相关的热点话题', 1),
    ('publish_timeliness',       'freshness',     '发布时效',     'Publish Timeliness',        '内容的发布/更新时间，用于评价存量内容', 2)
ON CONFLICT (id) DO NOTHING;

-- ─── Add "情感分析" template to geo_report_templates ────────────────

INSERT INTO geo_report_templates (id, name, description, icon, data_domains, default_prompt, is_builtin, is_active, sort_order, task_type)
VALUES (
    gen_random_uuid(),
    '情感分析',
    '专门针对品牌情感维度的深度分析，识别正面和负面情感主题',
    '💬',
    ARRAY['sentiment'],
    '你是一位品牌情感分析专家。请基于以下品牌在 AI 搜索引擎中的情感数据，进行深度分析。

## 分析要求

1. **情感概览**：正面/中性/负面比例分布
2. **主题拆解**：按情感主题（theme）分析，找出正面主题和负面主题的 Top 5
3. **平台差异**：不同 AI 平台（ChatGPT / Gemini / AI Mode）的情感表现差异
4. **趋势判断**：情感变化趋势，是否有恶化或改善信号
5. **可执行建议**：针对负面情感主题，给出具体的内容优化建议

## 数据指标
- 情绪正面率: {{sentiment_positive_ratio}}
- 情绪负面率: {{sentiment_negative_ratio}}
- 主要正面主题: {{sentiment_positive_themes}}
- 主要负面主题: {{sentiment_negative_themes}}

请用 Markdown 格式输出分析报告。',
    true,
    true,
    5,
    'analysis'
)
ON CONFLICT DO NOTHING;

-- ─── Seed recommended charts for 情感分析 via geo_workflow_config ────

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order)
VALUES
    ('recommended_chart', 'analysis', 'sentiment_distribution', 'sentiment',
     '{"nl_query": "各 AI 平台的情绪分布（正面/中性/负面占比）", "chart_type": "bar"}'::jsonb, 1),
    ('recommended_chart', 'analysis', 'sentiment_themes_pos', 'sentiment',
     '{"nl_query": "品牌正面情绪主题 Top 10", "chart_type": "bar"}'::jsonb, 2),
    ('recommended_chart', 'analysis', 'sentiment_themes_neg', 'sentiment',
     '{"nl_query": "品牌负面情绪主题 Top 10", "chart_type": "bar"}'::jsonb, 3),
    ('recommended_chart', 'analysis', 'sentiment_trend', 'sentiment',
     '{"nl_query": "品牌情绪评分随时间变化趋势", "chart_type": "line"}'::jsonb, 4)
ON CONFLICT DO NOTHING;

-- ─── Seed Layer 3: Strategies (from AgenticGEO paper 9 seed strategies + AnswerX additions) ──

INSERT INTO geo_strategies (name, description, dimensions, source_metrics, source_subgoals, content_type, generation_method, is_seed)
VALUES
    ('结构化问答优化', '以FAQ问答形式组织内容，优化标题层级和 schema markup',
     '{"instruction": "以FAQ问答形式组织，每个问题直接给出答案", "format": {"structure": "Q&A pairs with H2/H3 heading hierarchy", "schema_markup": "FAQPage JSON-LD", "word_count": "每条FAQ 80-150字"}, "tone": "权威但易读，避免行话", "constraints": ["答案首句必须直接回答问题", "每条FAQ包含至少一个可验证的数据点", "不使用模糊表述"], "enhancement_rules": ["生成后自动注入 JSON-LD structured data", "自动添加 internal linking 建议"]}'::jsonb,
     ARRAY['readability', 'answerability'], ARRAY['machine_readability', 'information_presentation'], 'faq', 'llm_with_postprocess', true),

    ('权威性强化', '采用权威专业语调，引用可信来源和数据',
     '{"instruction": "以行业专家视角撰写，强调第一手测试数据和专业分析", "format": {"structure": "论点→证据→结论", "schema_markup": "Article", "word_count": "800-1200字"}, "tone": "专业、权威、数据驱动", "constraints": ["每个核心论点必须有数据支撑", "引用至少2个权威第三方来源", "包含作者专业背景说明"], "enhancement_rules": ["自动补充引用标注格式", "检查数据点的完整性"]}'::jsonb,
     ARRAY['trustworthy'], ARRAY['authority_eeat', 'verifiability'], NULL, 'llm_with_postprocess', true),

    ('易懂性优化', '简化句子结构和用词，提高内容可读性',
     '{"instruction": "用清晰简单的语言解释复杂概念，面向非专业读者", "format": {"structure": "短段落，每段一个核心概念", "word_count": "段落不超过100字"}, "tone": "亲切、易懂、口语化", "constraints": ["避免专业术语或必须解释", "句子长度不超过25字", "使用类比和具体例子"], "enhancement_rules": ["自动检测复杂术语并添加解释"]}'::jsonb,
     ARRAY['readability'], ARRAY['content_understandability'], NULL, 'llm_with_postprocess', true),

    ('引用来源注入', '系统性地注入可信来源引用，提升内容可验证性',
     '{"instruction": "在内容中自然融入权威来源引用，增强可信度", "format": {"structure": "论述+引用穿插"}, "tone": "客观、可验证", "constraints": ["每200字至少一个来源引用", "优先引用行业报告和学术来源", "数据必须标注出处"], "enhancement_rules": ["自动格式化引用标注", "验证引用链接有效性"]}'::jsonb,
     ARRAY['trustworthy'], ARRAY['verifiability'], NULL, 'llm_with_postprocess', true),

    ('数据充实', '用具体数据和统计数字充实内容，提升说服力',
     '{"instruction": "在内容中嵌入具体的数据点、统计数字和对比数据", "format": {"structure": "数据驱动的论述结构"}, "tone": "精准、量化", "constraints": ["关键论点必须有数据支撑", "使用对比数据增强说服力", "标注数据时效性"], "enhancement_rules": ["检查数据点完整性", "建议补充缺失的关键数据"]}'::jsonb,
     ARRAY['trustworthy', 'answerability'], ARRAY['verifiability', 'information_presentation'], NULL, 'llm_with_postprocess', true),

    ('热点关联', '将内容与当前热点话题关联，提升时效性',
     '{"instruction": "在内容中自然关联当前热点事件和趋势", "format": {"structure": "热点引入→品牌关联→核心内容"}, "tone": "紧跟时事、有洞察", "constraints": ["热点必须与品牌/产品有自然关联", "避免强行蹭热点", "注明时间背景"], "enhancement_rules": ["标注内容时效性提醒"]}'::jsonb,
     ARRAY['freshness'], ARRAY['trending_relevance'], NULL, 'llm_with_postprocess', true),

    ('平台适配-Reddit', '针对Reddit平台特点优化内容格式和语调',
     '{"instruction": "以Reddit社区用户视角撰写，强调个人体验和真实评价", "format": {"structure": "故事开头→体验分享→对比总结", "word_count": "300-800字"}, "tone": "口语化、真实、社区感", "constraints": ["使用第一人称", "包含具体使用场景", "加入upvote-friendly的对比表格"], "enhancement_rules": ["检查Reddit格式规范", "优化标题吸引力"]}'::jsonb,
     ARRAY['answerability'], ARRAY['platform_fit'], 'platform_post', 'llm_with_postprocess', true),

    ('平台适配-官网', '针对品牌官网内容特点优化结构和SEO',
     '{"instruction": "以品牌官方视角撰写，专业严谨，含structured data", "format": {"structure": "H1→H2→H3层级清晰", "schema_markup": "Article + Product", "word_count": "800-1500字"}, "tone": "专业、品牌调性一致", "constraints": ["符合品牌voice guidelines", "包含内链建议", "SEO标题优化"], "enhancement_rules": ["自动注入schema markup", "生成meta description", "添加canonical URL建议"]}'::jsonb,
     ARRAY['readability', 'answerability'], ARRAY['machine_readability', 'platform_fit'], 'aeo_article', 'llm_with_postprocess', true),

    ('竞品差异化', '在内容中自然融入品牌与竞品的差异化优势',
     '{"instruction": "通过客观对比突出品牌独特优势，避免直接贬低竞品", "format": {"structure": "需求场景→多品牌对比→推荐结论"}, "tone": "客观、有理有据", "constraints": ["对比维度至少3个", "数据来源必须标注", "结论要有说服力"], "enhancement_rules": ["检查竞品信息准确性", "优化对比表格可读性"]}'::jsonb,
     ARRAY['answerability', 'trustworthy'], ARRAY['information_presentation', 'authority_eeat'], 'comparison', 'llm_with_postprocess', true);

COMMIT;
