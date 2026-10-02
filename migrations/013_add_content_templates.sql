-- 013_add_content_templates.sql
-- Adds task_type column to geo_report_templates to support both analysis and content_generation templates.
-- Then inserts 5 built-in content generation templates with strategy prompts.

-- Step 1: Add task_type column (defaults to 'analysis' for backward compat)
ALTER TABLE geo_report_templates
    ADD COLUMN IF NOT EXISTS task_type TEXT DEFAULT 'analysis';

-- Step 2: Insert content generation templates
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type
) VALUES
(
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
    true, true, 1, 'content_generation'
),
(
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
    true, true, 2, 'content_generation'
),
(
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
    true, true, 3, 'content_generation'
),
(
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
    true, true, 4, 'content_generation'
),
(
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
    true, true, 5, 'content_generation'
);
