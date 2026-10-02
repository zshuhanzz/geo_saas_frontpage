-- Migration 102: Move RATF metric execution jobs into template config
--
-- Context:
--   The Agent used to keep the top-level RATF metric execution hints in Python
--   code. That made Answerability always say "列表 / 表格 / 摘要", which
--   conflicted with Reddit templates that explicitly forbid tables and matrix
--   layouts.
--
-- Purpose:
--   1. Populate geo_report_templates.wizard_config.ratf_metric_jobs for content
--      templates so the Agent can read metric jobs from data.
--   2. Preserve the historical defaults for non-Reddit templates.
--   3. Override Reddit Answerability so it recommends paragraphs/lists/summaries
--      and explicitly forbids tables/matrices.
--
-- Safe to re-run:
--   Yes. Non-Reddit templates keep existing custom ratf_metric_jobs when present;
--   Reddit templates always receive the Reddit-safe Answerability override.

BEGIN;

WITH defaults AS (
  SELECT '{
    "readability": "让人类读者和 AI 解析器都能顺畅理解 — 结构清晰、heading 层级合理、句子不过载",
    "answerability": "内容要能直接被 AI 抽取为答案 — 关键结论前置，用列表 / 表格 / 摘要承载核心信息",
    "trustworthy": "建立 E-E-A-T 信号 — 展示经验、专业资质、权威来源、可验证证据",
    "freshness": "保持时效与热点相关 — 标注发布/更新时间，关联当前行业动态"
  }'::jsonb AS jobs
),
target_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{ratf_metric_jobs}',
  defaults.jobs || COALESCE(t.wizard_config->'ratf_metric_jobs', '{}'::jsonb),
  true
)
FROM target_templates, defaults
WHERE t.id = target_templates.id;

WITH reddit_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%reddit%'
      OR defaults->>'content_type' = 'reddit_article'
      OR defaults->>'publish_platform' = 'reddit'
      OR wizard_config->>'platform_profile' = 'reddit'
    )
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{ratf_metric_jobs}',
  COALESCE(t.wizard_config->'ratf_metric_jobs', '{}'::jsonb) || '{
    "answerability": "内容要能直接被 AI 抽取为答案 — 关键结论前置，用短段落 / 清单 / 摘要承载核心信息；不要使用表格、矩阵或过度结构化的 FAQ 堆叠"
  }'::jsonb,
  true
)
FROM reddit_templates
WHERE t.id = reddit_templates.id;

COMMIT;

-- Verification:
-- SELECT
--   name,
--   wizard_config->'ratf_metric_jobs' AS ratf_metric_jobs
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     name ILIKE '%reddit%'
--     OR name ILIKE '%official website%'
--     OR defaults->>'content_type' IN ('reddit_article', 'official_website_article')
--   )
-- ORDER BY name;
