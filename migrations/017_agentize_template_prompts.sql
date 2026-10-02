-- =============================================================
-- Migration 017: Agent-ize Template Prompts (v4)
-- Run: psql $DATABASE_URL -f migrations/017_agentize_template_prompts.sql
-- =============================================================
-- Replaces hardcoded metric names with [方括号占位符] placeholders.
-- Users click metrics from the "可用指标" catalog to replace placeholders.
-- =============================================================


-- ============================================================
-- 1. 竞品对标分析
-- ============================================================
UPDATE geo_report_templates
SET default_prompt = '请基于以下品牌在各 AI 搜索平台的可见度和引用数据，进行竞品对标分析。

数据指标（请从上方"可用指标"面板点选替换）：
可见度：[点击替换为可见度指标]
引用：[点击替换为引用指标]

分析要点：
1. 自有品牌 vs 竞品的 SOV 差距和变化趋势
2. 各平台上竞品的优势 Prompt 和内容策略
3. 品牌引用来源质量对比
4. 可执行的差距缩小策略建议

输出格式：结构化 Markdown 报告，含数据表格和具体建议。',
    updated_at = NOW()
WHERE name = '竞品对标分析' AND is_builtin = true AND task_type = 'analysis';


-- ============================================================
-- 2. 趋势诊断分析
-- ============================================================
UPDATE geo_report_templates
SET default_prompt = '请基于以下品牌时序数据，进行趋势诊断分析。

数据指标（请从上方"可用指标"面板点选替换）：
可见度：[点击替换为可见度指标]
引用：[点击替换为引用指标]
情感：[点击替换为情绪指标]

分析要点：
1. 各维度的核心趋势方向和变化幅度
2. 识别关键拐点及可能的驱动因素
3. 跨平台趋势一致性分析
4. 下一周期预判和建议

输出格式：Markdown 报告，含趋势总结、拐点分析和前瞻建议。',
    updated_at = NOW()
WHERE name = '趋势诊断分析' AND is_builtin = true AND task_type = 'analysis';


-- ============================================================
-- 3. 优化机会发现
-- ============================================================
UPDATE geo_report_templates
SET default_prompt = '请基于以下品牌在 AI 平台中的表现数据，进行优化机会发现分析。

数据指标（请从上方"可用指标"面板点选替换）：
可见度：[点击替换为可见度指标]
引用：[点击替换为引用指标]

分析要点：
1. 品牌可见度最低的 Prompt 列表和优化优先级
2. 未被提及的高频用户问题（内容缺口）
3. 按 RAFT 四维度评估当前被引用内容的薄弱环节
4. Quick Win 机会识别（低投入高回报的优化项）
5. 具体的内容优化行动建议

输出格式：Markdown 报告，含优化机会矩阵（影响力 × 难度）、优先级排序和行动清单。',
    updated_at = NOW()
WHERE name = '优化机会发现' AND is_builtin = true AND task_type = 'analysis';


-- ============================================================
-- 4. 全面健康检查
-- ============================================================
UPDATE geo_report_templates
SET default_prompt = '请基于以下品牌全域数据，进行全面 GEO 健康检查。

数据指标（请从上方"可用指标"面板点选替换）：
可见度：[点击替换为可见度指标]
引用：[点击替换为引用指标]
情感：[点击替换为情绪指标]

分析要点：
1. GEO 健康评分卡：可见度 / 引用 / 情绪三维度综合得分
2. 各 AI 平台的表现差异和短板
3. 与上一周期的全面对比
4. Top 3 紧急改善项 + Top 3 持续优势项
5. 综合优化路线图建议

输出格式：结构化 Markdown 报告，含评分卡、平台对比矩阵、问题清单和路线图。',
    updated_at = NOW()
WHERE name = '全面健康检查' AND is_builtin = true AND task_type = 'analysis';


-- ============================================================
-- 5. 自定义分析 (blank)
-- ============================================================
UPDATE geo_report_templates
SET default_prompt = '',
    updated_at = NOW()
WHERE name = '自定义分析' AND is_builtin = true AND task_type = 'analysis';


-- ============================================================
-- 6. Mark geo_analysis_metrics as deprecated (soft)
-- ============================================================
COMMENT ON TABLE geo_analysis_metrics IS 'DEPRECATED: Pipeline now uses dynamic metric discovery from live schema. This table is retained as reference data but no longer read by the analysis pipeline.';
