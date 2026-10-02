-- =============================================================================
-- Migration 029: Goal dictionary + RATF (content) + DDPP (analysis) + data
--                disclosure toggle + step rename + sentiment-repair template
-- =============================================================================
--
-- Context
-- -------
-- Fixes structural gaps in the 028 schema-driven wizard AND introduces the
-- two framework layers that run parallel to business goals:
--   · Content side  — RATF (Readability / Answerability / Trustworthy / Freshness)
--   · Analysis side — Gartner DDPP (Descriptive / Diagnostic / Predictive / Prescriptive)
--
-- Gap 1 — Orphan analysis goals
--   Migration 026 dropped scope='analysis' goal rows ("new wizard uses
--   methodology_snippet selector"). But analysis templates still carry
--   hardcoded defaults.goal keys (health / benchmark / trend) that now
--   point at nothing. Fix: re-seed a proper 5-row analysis goal dictionary.
--
-- Gap 2 — Dead `methodology_snippet / analysis` namespace
--   The 7 rows in this namespace (SOV 计算口径 / SOV 对比分析 / 趋势拐点
--   分析 / 正负面主题拆解 / 三维度综合评分 / 平台差异分析 / 竞品优势识别)
--   are **never read by analysis_pipeline.py** — grep for methodology_snippet
--   in geo_agent/api returns zero hits. They're a mix of calc rules +
--   diagnostic lenses + analytical ops; not a coherent framework.
--   Replace with Gartner's 4-level analytics hierarchy (Descriptive /
--   Diagnostic / Predictive / Prescriptive), seeded as a new
--   config_type='analysis_lens' dictionary. This is the industry-standard
--   analytical-depth framework and maps cleanly onto how the LLM should
--   reason through each report section.
--
-- Gap 3 — Dead content methodology_snippet namespace
--   Same story on content side: the 7 rows (4 content_raft_* + 3
--   content_strategy_*) were an ad-hoc mix that matched neither the RAFT
--   academic paper nor the industry RATF framework. Replace with the
--   proper 4-metric × 9-sub-goal RATF dictionary:
--
--     Top-level quality metrics (config_type='content_metric'):
--       · readability     可读性      (BookOpen)
--       · answerability   可做答案性   (MessageCircleQuestion)
--       · trustworthy     可信赖性    (ShieldCheck)    — binds to E-E-A-T
--       · freshness       时效性      (Clock)
--
--     Sub-goals (config_type='content_sub_goal', 2-level via parent_key):
--       · readability   → content_understandability, machine_readability
--       · answerability → information_presentation, audience_fit, platform_fit
--       · trustworthy   → authority_eeat, verifiability
--       · freshness     → trending_relevance, publish_timeliness
--
--   Business goals (visibility_boost / citation_optimize / sentiment_repair /
--   full_optimize) are ORTHOGONAL to RATF — they answer "why we're creating
--   this content" (outcome), while RATF answers "what quality bar must it
--   meet" (methodology). Exposed as two independently-toggleable wizard
--   steps. Same pattern is mirrored on the analysis side:
--   analysis_goal (business) + analysis_framework (DDPP methodology).
--
-- Gap 4 — Wizard steps need restructuring
--   a) analysis_goal: drop dead `default_methodology_snippets` field, make
--      step label bilingual
--   b) INSERT new analysis_framework step at analysis num=2 (between
--      analysis_goal and data_selection). Shift subsequent steps'
--      num + sort_order by 1.
--   c) analysis prompt_edit: add disable_user_edit + include_data_disclosure
--      fields
--   d) content goal_config → output_config rename + add include_data_disclosure
--   e) INSERT content_framework step at content num=2 (RATF multi-select)
--   f) Bilingual labels on framework steps and their dictionaries:
--      "分析框架 (Analysis Framework)", DDPP rows carry both Chinese and
--      English labels; "内容质量框架 (Content Framework)", RATF sub-goal
--      rows gain English too.
--
-- Gap 5 — sentiment_repair business goal has no template using it
--   Create a new builtin 情绪修复内容 template.
--
--
-- High-level order of operations
-- ------------------------------
--   A. Re-seed analysis `goal` dictionary (5 rows)
--   B. Drop old content methodology_snippet rows (7 rows)
--   C. Seed content_metric dictionary (4 rows, bilingual)
--   D. Seed content_sub_goal dictionary (9 rows, bilingual)
--   E. Drop dead methodology_snippet/analysis rows (7 rows)
--   F. Seed analysis_lens dictionary (4 Gartner DDPP rows, bilingual)
--   G. UPDATE analysis_goal step schema (strip default_methodology_snippets)
--   H. INSERT analysis_framework step + shift subsequent analysis step nums
--      + UPDATE analysis prompt_edit schema (disable_user_edit, disclosure)
--   I. Replace ALL content_generation workflow_step rows (8 rows, key
--      renames, content_framework insert, bilingual labels)
--   J. Backfill analysis templates (default_goal, default_lenses, prompt_edit
--      fields, strip dead default_methodology_snippets)
--   K. Backfill content templates (wizard_config key rename, default_goal,
--      content_framework defaults, include_data_disclosure per content_type)
--   L. INSERT new 情绪修复内容 template
--
-- Safe to re-run: DELETE-then-INSERT for dictionaries and for the full
-- content workflow_step block; surgical UPDATE/INSERT for the analysis
-- workflow_step block; deterministic UPDATEs in template backfill; the new
-- template uses a NOT EXISTS guard. Wrapped in one transaction.
-- =============================================================================

BEGIN;

-- ============================================================
-- A. Re-seed analysis-scope `goal` dictionary
-- ============================================================
DELETE FROM geo_workflow_config
WHERE config_type = 'goal' AND scope = 'analysis';

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES
  ('goal', 'analysis', 'health', '',
   '{"icon":"Shield","color":"text-emerald-400 border-emerald-500/30 bg-emerald-500/5","label":"全面健康检查","description":"可见度 / 引用 / 情感 三维度综合体检","recommended_domains":["visibility","citation","sentiment"]}'::jsonb,
   1, true),

  ('goal', 'analysis', 'benchmark', '',
   '{"icon":"Target","color":"text-blue-400 border-blue-500/30 bg-blue-500/5","label":"竞品对标","description":"与竞品在 AI 搜索中的 SOV / 引用 / 可见度差异对比","recommended_domains":["visibility","citation"]}'::jsonb,
   2, true),

  ('goal', 'analysis', 'trend', '',
   '{"icon":"TrendingUp","color":"text-purple-400 border-purple-500/30 bg-purple-500/5","label":"趋势诊断","description":"时序变化、关键拐点识别、前瞻判断","recommended_domains":["visibility","citation"]}'::jsonb,
   3, true),

  ('goal', 'analysis', 'opportunity', '',
   '{"icon":"Lightbulb","color":"text-amber-400 border-amber-500/30 bg-amber-500/5","label":"机会发现","description":"基于数据差距识别可优化的 Prompt / 主题（对接 opportunity pipeline）","recommended_domains":["visibility","citation"]}'::jsonb,
   4, true),

  ('goal', 'analysis', 'sentiment_deep', '',
   '{"icon":"MessageSquare","color":"text-pink-400 border-pink-500/30 bg-pink-500/5","label":"情感深度拆解","description":"正负面主题拆解、平台差异、改善信号识别","recommended_domains":["sentiment"]}'::jsonb,
   5, true);


-- ============================================================
-- B. Drop old content methodology_snippet rows (ad-hoc, replaced by RATF)
-- ============================================================
-- Old rows being dropped:
--   content_raft_retrievability / content_raft_accuracy
--   content_raft_fluency        / content_raft_trustworthiness
--   content_strategy_faq        / content_strategy_diff
--   content_strategy_multiplatform
DELETE FROM geo_workflow_config
WHERE config_type = 'methodology_snippet' AND scope = 'content_generation';


-- ============================================================
-- C. Seed content_metric dictionary (4 RATF top-level quality metrics)
--    Labels carry Chinese + English (exposed to UI directly)
-- ============================================================
DELETE FROM geo_workflow_config
WHERE config_type = 'content_metric' AND scope = 'content_generation';

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES
  ('content_metric', 'content_generation', 'readability', '',
   '{"icon":"BookOpen","color":"text-blue-400 border-blue-500/30 bg-blue-500/5","label":"可读性 (Readability)","description":"内容是否易于被人类读者和 AI 引擎顺畅理解与解析"}'::jsonb,
   1, true),

  ('content_metric', 'content_generation', 'answerability', '',
   '{"icon":"MessageCircleQuestion","color":"text-emerald-400 border-emerald-500/30 bg-emerald-500/5","label":"可做答案性 (Answerability)","description":"内容是否能作为 AI 回答用户问题时的直接答案来源"}'::jsonb,
   2, true),

  ('content_metric', 'content_generation', 'trustworthy', '',
   '{"icon":"ShieldCheck","color":"text-purple-400 border-purple-500/30 bg-purple-500/5","label":"可信赖性 (Trustworthy)","description":"E-E-A-T: 经验 / 专业 / 权威 / 可信，决定内容是否值得被 AI 引用"}'::jsonb,
   3, true),

  ('content_metric', 'content_generation', 'freshness', '',
   '{"icon":"Clock","color":"text-amber-400 border-amber-500/30 bg-amber-500/5","label":"时效性 (Freshness)","description":"内容是否保持最新状态与时事相关度，影响 AI 对内容的新鲜度评分"}'::jsonb,
   4, true);


-- ============================================================
-- D. Seed content_sub_goal dictionary (9 second-level items, parent→metric)
--    Labels bilingual (Chinese + English)
-- ============================================================
DELETE FROM geo_workflow_config
WHERE config_type = 'content_sub_goal' AND scope = 'content_generation';

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES
  -- Readability
  ('content_sub_goal', 'content_generation', 'content_understandability', 'readability',
   '{"label":"内容可理解度 (Content Understandability)","description":"使用清晰结构、短句、明确标题，让人类读者快速抓住核心"}'::jsonb,
   1, true),
  ('content_sub_goal', 'content_generation', 'machine_readability', 'readability',
   '{"label":"机器可读性 (Machine Readability)","description":"使用 schema markup、语义化 HTML、清晰的 heading 层级，方便 AI 抽取"}'::jsonb,
   2, true),

  -- Answerability
  ('content_sub_goal', 'content_generation', 'information_presentation', 'answerability',
   '{"label":"信息呈现 (Information Presentation)","description":"关键答案前置，用列表 / 表格 / 摘要等高信息密度格式直接回答用户问题"}'::jsonb,
   3, true),
  ('content_sub_goal', 'content_generation', 'audience_fit', 'answerability',
   '{"label":"受众贴合度 (Audience Fit)","description":"匹配目标用户的知识水平、搜索意图和常见提问方式"}'::jsonb,
   4, true),
  ('content_sub_goal', 'content_generation', 'platform_fit', 'answerability',
   '{"label":"平台贴合度 (Platform Fit)","description":"针对 ChatGPT / Gemini / AI Mode 的回答风格差异进行格式适配"}'::jsonb,
   5, true),

  -- Trustworthy
  ('content_sub_goal', 'content_generation', 'authority_eeat', 'trustworthy',
   '{"label":"权威性 (Authority / E-E-A-T)","description":"展示作者经验、专业资质、机构背景，建立内容权威"}'::jsonb,
   6, true),
  ('content_sub_goal', 'content_generation', 'verifiability', 'trustworthy',
   '{"label":"可验证性 (Verifiability)","description":"引用权威来源、提供数据出处、支持事实核查"}'::jsonb,
   7, true),

  -- Freshness
  ('content_sub_goal', 'content_generation', 'trending_relevance', 'freshness',
   '{"label":"热点相关度 (Trending Relevance)","description":"关联当前行业热点、用户搜索趋势、时事新闻"}'::jsonb,
   8, true),
  ('content_sub_goal', 'content_generation', 'publish_timeliness', 'freshness',
   '{"label":"发布时效 (Publish Timeliness)","description":"保持更新频率、标注 Last Updated 日期，避免内容过期"}'::jsonb,
   9, true);


-- ============================================================
-- E. Drop dead methodology_snippet/analysis rows (replaced by analysis_lens)
-- ============================================================
-- Rows being dropped (all from migrations 016 + 026):
--   raft_retrievability / raft_accuracy / raft_fluency / raft_trustworthiness
--   (all already soft-deleted in 026), plus the still-active ones:
--   competitor_sov / competitor_advantage / trend_inflection / trend_platform_diff
--   sov_methodology / holistic_geo_health / sentiment_deep_dive
--
-- Grep confirmed zero reads in geo_agent/api — dead config.
DELETE FROM geo_workflow_config
WHERE config_type = 'methodology_snippet' AND scope = 'analysis';


-- ============================================================
-- F. Seed analysis_lens dictionary (Gartner 4-level analytics hierarchy)
--    Labels bilingual; no sub-goals (levels are terminal)
-- ============================================================
DELETE FROM geo_workflow_config
WHERE config_type = 'analysis_lens' AND scope = 'analysis';

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES
  ('analysis_lens', 'analysis', 'descriptive', '',
   '{"icon":"BarChart3","color":"text-blue-400 border-blue-500/30 bg-blue-500/5","label":"描述性分析 (Descriptive)","description":"现状梳理 — 呈现 Visibility / Citation / Sentiment 的当前数据与基线"}'::jsonb,
   1, true),

  ('analysis_lens', 'analysis', 'diagnostic', '',
   '{"icon":"Search","color":"text-amber-400 border-amber-500/30 bg-amber-500/5","label":"诊断性分析 (Diagnostic)","description":"差距解释 — 平台差异 / 竞品差距 / 趋势拐点 / 根因分析"}'::jsonb,
   2, true),

  ('analysis_lens', 'analysis', 'predictive', '',
   '{"icon":"TrendingUp","color":"text-purple-400 border-purple-500/30 bg-purple-500/5","label":"预测性分析 (Predictive)","description":"未来预判 — 基于时序与行业信号预测走向与潜在风险"}'::jsonb,
   3, true),

  ('analysis_lens', 'analysis', 'prescriptive', '',
   '{"icon":"Target","color":"text-emerald-400 border-emerald-500/30 bg-emerald-500/5","label":"处方性分析 (Prescriptive)","description":"行动建议 — 输出可执行的优化动作与下一步优先级"}'::jsonb,
   4, true);


-- ============================================================
-- G. UPDATE analysis_goal step schema
--    - drop dead default_methodology_snippets field
--    - add bilingual label
-- ============================================================
UPDATE geo_workflow_config
SET value = '{
  "num": 1,
  "label": "分析目标 (Analysis Goal)",
  "description": "业务层面的分析目的 — 回答「为什么做这次分析」",
  "fields": [
    {
      "key": "default_goal",
      "type": "single_ref",
      "label": "默认分析目标",
      "ref_config_type": "goal",
      "ref_scope": "analysis",
      "description": "健康检查 / 竞品对标 / 趋势诊断 / 机会发现 / 情感深度"
    }
  ]
}'::jsonb
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'analysis_goal';


-- ============================================================
-- H. Restructure analysis workflow steps
--    - INSERT analysis_framework at num=2
--    - Shift data_selection (2→3), chart_config (3→4), prompt_edit (4→5),
--      confirm_execute (5→6) via jsonb_set on `num` + UPDATE sort_order
--    - UPDATE prompt_edit fields (disable_user_edit + include_data_disclosure)
-- ============================================================

-- H.1  Shift num/sort_order first so the new row at num=2 doesn't collide
UPDATE geo_workflow_config
SET value = jsonb_set(value, '{num}', '6'::jsonb),
    sort_order = 6
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'confirm_execute';

UPDATE geo_workflow_config
SET value = '{
  "num": 5,
  "label": "Prompt 编辑 (Prompt Edit)",
  "description": "终端用户微调 LLM 提示词；可锁定编辑权限 + 控制数据依据披露",
  "fields": [
    {
      "key": "disable_user_edit",
      "type": "boolean",
      "label": "禁止终端用户编辑 Prompt",
      "default": false,
      "description": "开启后 SaaS 端的 Prompt 编辑框只读，终端用户不能改动；适用于合规 / 内置模板 / 强约束场景"
    },
    {
      "key": "include_data_disclosure",
      "type": "boolean",
      "label": "插入「真实数据依据」章节",
      "default": true,
      "description": "运行时在报告开头注入本次分析用到的所有真实指标值、图表数据、时间范围作为硬约束；是数据准确性的核心防线，强烈建议始终开启"
    }
  ]
}'::jsonb,
    sort_order = 5
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'prompt_edit';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{num}', '4'::jsonb),
    sort_order = 4
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'chart_config';

UPDATE geo_workflow_config
SET value = jsonb_set(value, '{num}', '3'::jsonb),
    sort_order = 3
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'data_selection';

-- H.2  INSERT new analysis_framework step at num=2
DELETE FROM geo_workflow_config
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'analysis_framework';

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES
  ('workflow_step', 'analysis', 'analysis_framework', '',
   '{
     "num": 2,
     "label": "分析框架 (Analysis Framework)",
     "description": "方法论层面的分析深度 — 基于 Gartner DDPP 四级分析法，定义报告应覆盖的分析层级（现状 → 诊断 → 预测 → 行动）。与业务目标正交，两个 step 可独立 enable / disable",
     "fields": [
       {
         "key": "default_lenses",
         "type": "multi_ref",
         "label": "默认分析视角",
         "ref_config_type": "analysis_lens",
         "ref_scope": "analysis",
         "description": "Descriptive / Diagnostic / Predictive / Prescriptive 中选一个或多个，pipeline 会把对应方法论片段作为硬约束注入 LLM 提示词"
       }
     ]
   }'::jsonb, 2, true);


-- ============================================================
-- I. Replace ALL content_generation workflow_step rows
--    (key renames, content_framework insert, default_methodology_snippets drop,
--     bilingual labels on Content Goal + Content Framework steps)
-- ============================================================
DELETE FROM geo_workflow_config
WHERE config_type = 'workflow_step' AND scope = 'content_generation';

INSERT INTO geo_workflow_config (config_type, scope, key, parent_key, value, sort_order, is_active)
VALUES

-- Step 1: 内容目标 (Content Goal) — 业务目标
('workflow_step', 'content_generation', 'content_goal', '',
 '{
   "num": 1,
   "label": "内容目标 (Content Goal)",
   "description": "业务层面的内容优化目标 — 回答「为什么做这次内容」",
   "fields": [
     {
       "key": "default_goal",
       "type": "single_ref",
       "label": "默认业务目标",
       "ref_config_type": "goal",
       "ref_scope": "content_generation",
       "description": "可见度提升 / 引用优化 / 情绪修复 / 全面优化"
     }
   ]
 }'::jsonb, 1, true),

-- Step 2: 内容质量框架 (Content Framework) — RATF 方法论
('workflow_step', 'content_generation', 'content_framework', '',
 '{
   "num": 2,
   "label": "内容质量框架 (Content Framework)",
   "description": "方法论层面的质量约束 — 回答「内容要满足哪些质量标准」。业界 GEO 内容质量四维度 RATF (Readability / Answerability / Trustworthy / Freshness)，每个维度下有 2-3 个具体子目标。与业务目标正交 — 两个 step 可独立 enable / disable",
   "fields": [
     {
       "key": "default_metrics",
       "type": "multi_ref",
       "label": "默认质量维度",
       "ref_config_type": "content_metric",
       "ref_scope": "content_generation",
       "description": "四个顶层维度（可读性 / 可做答案性 / 可信赖性 / 时效性）"
     },
     {
       "key": "default_sub_goals",
       "type": "multi_ref",
       "label": "默认子目标",
       "ref_config_type": "content_sub_goal",
       "ref_scope": "content_generation",
       "description": "9 个具体子目标，每个绑定到某个质量维度（二级选项）"
     }
   ]
 }'::jsonb, 2, true),

-- Step 3: 内容类型
('workflow_step', 'content_generation', 'content_type', '',
 '{
   "num": 3,
   "label": "内容类型",
   "description": "选择要生成的内容形态",
   "fields": [
     {
       "key": "default",
       "type": "single_ref",
       "label": "默认内容类型",
       "ref_config_type": "content_type",
       "ref_scope": "content_generation",
       "description": "FAQ / AEO 文章 / SEO 文章 / 优化建议 / Content Brief"
     }
   ]
 }'::jsonb, 3, true),

-- Step 4: 产出配置（renamed from goal_config — now holds count/depth/disclosure）
('workflow_step', 'content_generation', 'output_config', '',
 '{
   "num": 4,
   "label": "产出配置",
   "description": "生成数量、深度、数据依据披露开关（与「内容目标」无关，仅控制产出形态）",
   "fields": [
     {
       "key": "default_count",
       "type": "number",
       "label": "默认数量",
       "description": "单次生成的内容条数（FAQ 常用 5 条、文章 1 篇）"
     },
     {
       "key": "default_depth",
       "type": "single_ref",
       "label": "默认深度",
       "ref_config_type": "depth",
       "ref_scope": "content_generation",
       "description": "快速生成 / 标准生成 / 深度优化"
     },
     {
       "key": "include_data_disclosure",
       "type": "boolean",
       "label": "插入「真实数据依据」章节",
       "default": true,
       "description": "运行时在生成内容开头注入本次用到的真实指标与数据快照作为依据披露。FAQ / AEO / SEO 等面向终端读者的文章型内容建议关闭；优化建议 / Content Brief 等内部参考型内容建议开启"
     }
   ]
 }'::jsonb, 4, true),

-- Step 5: Prompt 选择
('workflow_step', 'content_generation', 'prompt_select', '',
 '{
   "num": 5,
   "label": "Prompt 选择",
   "description": "候选 Prompt 列表的排序维度",
   "fields": [
     {
       "key": "default_sort",
       "type": "single_ref",
       "label": "默认排序",
       "ref_config_type": "sort_option",
       "ref_scope": "content_generation",
       "description": "优先处理 Visibility / Citation / Sentiment 最差的 Prompt"
     }
   ]
 }'::jsonb, 5, true),

-- Step 6: 数据 & 策略
('workflow_step', 'content_generation', 'data_strategy', '',
 '{
   "num": 6,
   "label": "数据 & 策略",
   "description": "为内容生成注入上下文的数据领域",
   "fields": [
     {
       "key": "default_domains",
       "type": "multi_ref",
       "label": "默认数据领域",
       "ref_config_type": "domain",
       "ref_scope": "shared",
       "description": "将这些领域的数据快照注入内容生成上下文"
     }
   ]
 }'::jsonb, 6, true),

-- Step 7: 模型 & 定时
('workflow_step', 'content_generation', 'model_schedule', '',
 '{
   "num": 7,
   "label": "模型 & 定时",
   "description": "模型选择 + 定时调度（预留，暂无默认字段）",
   "fields": []
 }'::jsonb, 7, true),

-- Step 8: 确认执行
('workflow_step', 'content_generation', 'confirm_execute', '',
 '{
   "num": 8,
   "label": "确认执行",
   "description": "复核配置后触发内容生成 — 无默认字段",
   "fields": []
 }'::jsonb, 8, true);


-- ============================================================
-- J. Backfill analysis templates
-- ============================================================

-- J.1  analysis_goal.default_goal := defaults.goal  (for templates that have one)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_goal,default_goal}',
    to_jsonb(defaults->>'goal')
)
WHERE task_type = 'analysis' AND defaults ? 'goal';

-- J.1a  情感分析 特例：defaults 是 {}, 手动设 sentiment_deep
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_goal,default_goal}',
    '"sentiment_deep"'::jsonb
)
WHERE task_type = 'analysis' AND name = '情感分析';

-- J.2  Strip dead default_methodology_snippets from analysis_goal
UPDATE geo_report_templates
SET wizard_config = wizard_config #- '{steps,analysis_goal,default_methodology_snippets}'
WHERE task_type = 'analysis';

-- J.3  Ensure analysis_framework step exists on every analysis template
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_framework}',
    COALESCE(wizard_config#>'{steps,analysis_framework}', '{"enabled":true}'::jsonb)
)
WHERE task_type = 'analysis';

-- J.4  Set default_lenses per business goal
--      (health/benchmark: descriptive+diagnostic,
--       trend: +predictive,
--       opportunity: diagnostic+prescriptive,
--       sentiment_deep: descriptive+diagnostic+prescriptive)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_framework,default_lenses}',
    CASE defaults->>'goal'
      WHEN 'health'      THEN '["descriptive","diagnostic"]'::jsonb
      WHEN 'benchmark'   THEN '["descriptive","diagnostic"]'::jsonb
      WHEN 'trend'       THEN '["descriptive","diagnostic","predictive"]'::jsonb
      WHEN 'opportunity' THEN '["diagnostic","prescriptive"]'::jsonb
      ELSE '[]'::jsonb
    END
)
WHERE task_type = 'analysis' AND defaults ? 'goal';

-- J.4a  情感分析 特例 (defaults={}) — all except predictive
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_framework,default_lenses}',
    '["descriptive","diagnostic","prescriptive"]'::jsonb
)
WHERE task_type = 'analysis' AND name = '情感分析';

-- J.4b  自定义分析 — leave empty so users pick at runtime
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,analysis_framework,default_lenses}',
    '[]'::jsonb
)
WHERE task_type = 'analysis' AND name = '自定义分析';

-- J.5  prompt_edit defaults — disable_user_edit=false, include_data_disclosure=true
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    jsonb_set(
        wizard_config,
        '{steps,prompt_edit,disable_user_edit}',
        'false'::jsonb
    ),
    '{steps,prompt_edit,include_data_disclosure}',
    'true'::jsonb
)
WHERE task_type = 'analysis';


-- ============================================================
-- K. Backfill content templates
-- ============================================================

-- K.1  Rename goal_config → output_config inside wizard_config.steps.
--      Copy the whole sub-object over, then drop the old key.
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,output_config}',
    COALESCE(wizard_config#>'{steps,goal_config}', '{"enabled":true}'::jsonb)
)
WHERE task_type = 'content_generation';

UPDATE geo_report_templates
SET wizard_config = wizard_config #- '{steps,goal_config}'
WHERE task_type = 'content_generation';

-- K.2  Remove old default_methodology_snippets from content_goal step
--      (the old methodology_snippet dictionary is gone as of section B)
UPDATE geo_report_templates
SET wizard_config = wizard_config #- '{steps,content_goal,default_methodology_snippets}'
WHERE task_type = 'content_generation';

-- K.3  content_goal.default_goal := defaults.goal  (for templates that have one)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_goal,default_goal}',
    to_jsonb(defaults->>'goal')
)
WHERE task_type = 'content_generation' AND defaults ? 'goal';

-- K.4  Ensure content_framework step exists with enabled=true
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_framework}',
    COALESCE(wizard_config#>'{steps,content_framework}', '{"enabled":true}'::jsonb)
)
WHERE task_type = 'content_generation';

-- K.5  Populate content_framework.default_sub_goals from required_subgoals
--      (reuses existing contract data — templates already declare which
--      sub-goals they require in wizard_config.required_subgoals)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_framework,default_sub_goals}',
    COALESCE(wizard_config->'required_subgoals', '[]'::jsonb)
)
WHERE task_type = 'content_generation';

-- K.6  Populate content_framework.default_metrics per template

-- SEO 优化文章 → readability + answerability + freshness
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_framework,default_metrics}',
    '["readability","answerability","freshness"]'::jsonb
)
WHERE name = 'SEO 优化文章';

-- 内容优化建议 → all 4
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_framework,default_metrics}',
    '["readability","answerability","trustworthy","freshness"]'::jsonb
)
WHERE name = '内容优化建议';

-- FAQ 内容生成 → readability + answerability + trustworthy
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_framework,default_metrics}',
    '["readability","answerability","trustworthy"]'::jsonb
)
WHERE name = 'FAQ 内容生成';

-- AEO 优化文章 → readability + answerability + trustworthy
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_framework,default_metrics}',
    '["readability","answerability","trustworthy"]'::jsonb
)
WHERE name = 'AEO 优化文章';

-- Content Brief → answerability + trustworthy
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_framework,default_metrics}',
    '["answerability","trustworthy"]'::jsonb
)
WHERE name = 'Content Brief';

-- 自定义内容 → empty (user picks at runtime)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,content_framework,default_metrics}',
    '[]'::jsonb
)
WHERE name = '自定义内容';

-- K.7  output_config.include_data_disclosure — per content_type default
-- FAQ / AEO / SEO 面向终端读者 → false
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,output_config,include_data_disclosure}',
    'false'::jsonb
)
WHERE task_type = 'content_generation'
  AND defaults->>'content_type' IN ('faq', 'aeo_article', 'article');

-- recommendations / brief / 自定义 (NULL) → true
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,output_config,include_data_disclosure}',
    'true'::jsonb
)
WHERE task_type = 'content_generation'
  AND (defaults->>'content_type' NOT IN ('faq', 'aeo_article', 'article')
       OR defaults->>'content_type' IS NULL);


-- ============================================================
-- L. Insert new 情绪修复内容 template (uses sentiment_repair goal)
-- ============================================================
INSERT INTO geo_report_templates
  (name, task_type, data_domains, defaults, wizard_config, default_prompt,
   description, icon, is_builtin, is_active, sort_order)
SELECT
  '情绪修复内容',
  'content_generation',
  ARRAY['sentiment','citation']::text[],
  '{"goal":"sentiment_repair","count":3,"depth":"standard","platforms":["chatgpt","gemini"],"content_type":"recommendations"}'::jsonb,
  '{
    "version": 1,
    "steps": {
      "content_goal":      {"enabled": true, "default_goal": "sentiment_repair"},
      "content_framework": {
        "enabled": true,
        "default_metrics":   ["readability","answerability","trustworthy"],
        "default_sub_goals": ["content_understandability","information_presentation","audience_fit","authority_eeat","verifiability"]
      },
      "content_type":      {"enabled": true, "default": "recommendations"},
      "output_config":     {"enabled": true, "default_count": 3, "default_depth": "standard", "include_data_disclosure": true},
      "prompt_select":     {"enabled": true, "default_sort": "sentiment"},
      "data_strategy":     {"enabled": true, "default_domains": ["sentiment","citation"]},
      "model_schedule":    {"enabled": true},
      "confirm_execute":   {"enabled": true}
    },
    "required_metrics":  ["sentiment_distribution","sentiment_trend","top_negative_themes"],
    "required_subgoals": ["content_understandability","information_presentation","audience_fit","authority_eeat","verifiability"]
  }'::jsonb,
  '你是一位品牌危机公关和 GEO 策略顾问。请基于以下品牌在 AI 引擎中的负面情绪数据，生成一份情绪修复内容策略，包含负面主题诊断、官方回应建议、正向反制内容建议。

## 分析输入
- 负面情绪主题 Top N（按数据提供）
- 涉及的 AI 平台和具体 Prompt
- 当前品牌正面 / 负面情绪比例与变化趋势

## 输出要求
1. **负面主题诊断**：每个主题的核心诉求、用户情绪来源、影响范围评估
2. **官方回应建议**：针对每个主题给出回应模板（不删除、不否认，聚焦解决方案）
3. **正向反制内容**：建议 2-3 条可发布的正面选题，用事实与数据对冲负面叙事
4. **RATF 质量约束**：
   - 可理解度：语言清晰，不回避问题
   - 信息呈现：直接回答「品牌如何解决了这个问题」
   - 受众贴合：匹配原 Prompt 的用户关切点
   - 权威性 (E-E-A-T)：引用官方声明、第三方评测、真实案例
   - 可验证性：所有承诺必须可追溯到公开信息

输出格式：结构化 Markdown 文档，包含主题诊断、回应模板、正向内容建议三大板块。',
  '基于 AI 引擎中识别的负面情绪主题，生成修复性内容策略与回应建议',
  '🛠️',
  true,
  true,
  7
WHERE NOT EXISTS (
    SELECT 1 FROM geo_report_templates WHERE name = '情绪修复内容' AND is_builtin = true
);

COMMIT;

-- =============================================================================
-- Verification queries (run after commit)
-- =============================================================================
--
-- 1. Analysis goal dictionary should have 5 rows
-- SELECT key, value->>'label' FROM geo_workflow_config
--   WHERE config_type='goal' AND scope='analysis' ORDER BY sort_order;
--
-- 2. Analysis lens dictionary should have 4 rows (DDPP, bilingual)
-- SELECT key, value->>'label' FROM geo_workflow_config
--   WHERE config_type='analysis_lens' AND scope='analysis' ORDER BY sort_order;
--
-- 3. Dead methodology_snippet/analysis rows should be gone
-- SELECT COUNT(*) FROM geo_workflow_config
--   WHERE config_type='methodology_snippet' AND scope='analysis';
--   -- Expect 0
--
-- 4. Content RATF framework dictionaries (4 + 9 rows, all bilingual)
-- SELECT config_type, key, parent_key, value->>'label' FROM geo_workflow_config
--   WHERE config_type IN ('content_metric','content_sub_goal')
--   ORDER BY config_type, sort_order;
--
-- 5. Analysis wizard steps should be 6 rows (1..6), including analysis_framework at num=2
-- SELECT key, (value->>'num')::int AS num, value->>'label'
--   FROM geo_workflow_config
--   WHERE config_type='workflow_step' AND scope='analysis'
--   ORDER BY (value->>'num')::int;
--
-- 6. Content wizard steps should be 8 rows (1..8), including content_framework at num=2
-- SELECT key, (value->>'num')::int AS num, value->>'label'
--   FROM geo_workflow_config
--   WHERE config_type='workflow_step' AND scope='content_generation'
--   ORDER BY (value->>'num')::int;
--
-- 7. Per-template backfill sanity check (analysis)
-- SELECT name,
--   wizard_config#>>'{steps,analysis_goal,default_goal}'          AS default_goal,
--   wizard_config#>'{steps,analysis_framework,default_lenses}'    AS default_lenses,
--   wizard_config#>>'{steps,prompt_edit,include_data_disclosure}' AS analysis_disclosure
-- FROM geo_report_templates
-- WHERE task_type='analysis' AND is_active=true
-- ORDER BY name;
--
-- 8. Per-template backfill sanity check (content)
-- SELECT name,
--   wizard_config#>>'{steps,content_goal,default_goal}'           AS content_goal,
--   wizard_config#>'{steps,content_framework,default_metrics}'    AS metrics,
--   wizard_config#>'{steps,content_framework,default_sub_goals}'  AS sub_goals,
--   wizard_config#>>'{steps,output_config,include_data_disclosure}' AS content_disclosure
-- FROM geo_report_templates
-- WHERE task_type='content_generation' AND is_active=true
-- ORDER BY name;
--
-- 9. New sentiment-repair template exists
-- SELECT name, defaults, wizard_config#>'{steps,content_framework}'
-- FROM geo_report_templates WHERE name = '情绪修复内容';
--
-- 10. Stale keys should be gone
-- SELECT name,
--   wizard_config#>'{steps,goal_config}' AS should_be_null,
--   wizard_config#>'{steps,content_goal,default_methodology_snippets}' AS should_also_be_null,
--   wizard_config#>'{steps,analysis_goal,default_methodology_snippets}' AS and_this_too
-- FROM geo_report_templates;
