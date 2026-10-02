-- 058_visibility_score_response_level_metric.sql
--
-- Clarify Visibility vs SOV in Geo Agent metric configuration.
--
-- Visibility Score:
--   How often the customer's own brand appears in AI responses.
--   Formula = distinct AI responses mentioning own brand / total AI responses.
--
-- Share of Voice:
--   How much of all brand mention volume belongs to the customer's own brand.
--   Formula = own brand mention rows / all brand mention rows.
--
-- This migration only updates geo_analysis_metrics configuration used by
-- Geo Agent NL2SQL. It does not touch collector/analyzer raw output.

INSERT INTO geo_analysis_metrics (
  metric_name,
  display_name_zh,
  display_name_en,
  domain,
  description,
  calculation_hint,
  relevant_tables,
  sample_question,
  null_behavior,
  unit,
  sort_order
)
VALUES (
  'visibility_score',
  '可见度分数',
  'Visibility Score',
  'visibility',
  '客户自有品牌被 AI response 提及的频率：提到自有品牌的去重 AI responses 数 / 总 AI responses 数。',
  'MANDATORY GLOBAL CONFIG INTENT SCOPE:
- This metric is dynamically scoped by Global Config; analyzer raw rows keep all prompts.
- Restrict denominator and numerator to prompts whose intent is enabled for the Visibility metric.
- Join geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id.
- Join geo_global_intents gi ON gi.intent_name = cp.intent.
- Add cp.client_id = $1, gi.is_active = true, and gi.categories @> ''["Visibility"]''::jsonb.
- Never fall back to all intents when no intent is configured for Visibility.

REFERENCE SQL:
WITH scoped_results AS (
  SELECT DISTINCT gr.result_id, gr.client_id, gr.platform, gr.ingested_at
  FROM geo_results gr
  JOIN geo_client_prompts cp
    ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
  JOIN geo_global_intents gi
    ON gi.intent_name = cp.intent
  WHERE gr.client_id = $1
    AND cp.client_id = $1
    AND gi.is_active = true
    AND gi.categories @> ''["Visibility"]''::jsonb
    AND gr.ingested_at BETWEEN $2 AND $3
    AND gr.platform IN ({platforms})
),
own_mentioned_results AS (
  SELECT DISTINCT sr.result_id
  FROM scoped_results sr
  JOIN geo_brand_mentions bm
    ON bm.result_id = sr.result_id AND bm.client_id = sr.client_id
  WHERE bm.brand_role = ''own''
)
SELECT ROUND(
  (SELECT COUNT(*) FROM own_mentioned_results)::numeric
  / NULLIF((SELECT COUNT(*) FROM scoped_results), 0)
  * 100, 2
) AS visibility_score;
CRITICAL: Visibility Score is response-level coverage. Use COUNT(DISTINCT result_id), not raw mention rows. This is NOT SOV. 返回单个百分比数字。',
  ARRAY['geo_results', 'geo_brand_mentions', 'geo_client_prompts', 'geo_global_intents'],
  '在配置为 Visibility 的 prompts 产生的 AI responses 中，有多少比例提到了我方品牌？',
  'return_zero',
  '%',
  0
)
ON CONFLICT (metric_name) DO UPDATE
SET
  display_name_zh = EXCLUDED.display_name_zh,
  display_name_en = EXCLUDED.display_name_en,
  domain = EXCLUDED.domain,
  description = EXCLUDED.description,
  calculation_hint = EXCLUDED.calculation_hint,
  relevant_tables = EXCLUDED.relevant_tables,
  sample_question = EXCLUDED.sample_question,
  null_behavior = EXCLUDED.null_behavior,
  unit = EXCLUDED.unit,
  sort_order = EXCLUDED.sort_order,
  is_active = TRUE,
  updated_at = NOW();

UPDATE geo_analysis_metrics
SET
  description = 'Share of Voice：自有品牌 mention 行数占所有品牌 mention 行数的比例，按时间序列展开。注意：这是 mention-volume share，不是 response-level Visibility Score。',
  calculation_hint = 'MANDATORY GLOBAL CONFIG INTENT SCOPE:
- This metric is dynamically scoped by Global Config; analyzer raw rows keep all prompts.
- Before aggregating, restrict fact rows to prompts whose intent is enabled for the Visibility metric.
- Join geo_client_prompts cp ON cp.id = cm.client_prompt_id AND cp.client_id = cm.client_id.
- Join geo_global_intents gi ON gi.intent_name = cp.intent.
- Add cp.client_id = $1, gi.is_active = true, and gi.categories @> ''["Visibility"]''::jsonb.
- Apply this filter to every numerator, denominator, total CTE, and subquery in the reference SQL.
- Never fall back to all intents when no intent is configured for Visibility.

REFERENCE SQL:
SELECT DATE(cm.executed_at) AS date,
  ROUND(SUM(CASE WHEN cm.brand_role = ''own'' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(*), 0) * 100, 2) AS sov
FROM geo_brand_mentions cm
JOIN geo_client_prompts cp
  ON cp.id = cm.client_prompt_id AND cp.client_id = cm.client_id
JOIN geo_global_intents gi
  ON gi.intent_name = cp.intent
JOIN geo_results gr
  ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id
WHERE cm.client_id = $1 AND gr.client_id = $1 AND cp.client_id = $1
  AND gi.is_active = true
  AND gi.categories @> ''["Visibility"]''::jsonb
  AND cm.executed_at BETWEEN $2 AND $3
  AND gr.platform IN ({platforms})
GROUP BY DATE(cm.executed_at) ORDER BY 1;
CRITICAL: SOV denominator = COUNT(*) of all brand mention rows in the scoped prompt set. This is NOT response-level Visibility Score. 返回 Markdown 表格: | Date | SOV |',
  relevant_tables = COALESCE(relevant_tables, ARRAY[]::text[])
    || CASE
      WHEN 'geo_client_prompts' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_client_prompts']::text[]
    END
    || CASE
      WHEN 'geo_global_intents' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_global_intents']::text[]
    END,
  sample_question = '过去 30 天内，每一天我方品牌 mention 行数占所有品牌 mention 行数的比例是多少？',
  unit = '%',
  updated_at = NOW()
WHERE metric_name = 'sov_trend';

UPDATE geo_analysis_metrics
SET
  description = 'Prompt 覆盖率：至少产生过一次自有品牌 mention 的 active Visibility prompts 占所有 active Visibility prompts 的比例。注意：这是 prompt-level 覆盖率，不是 response-level Visibility Score。',
  calculation_hint = 'MANDATORY GLOBAL CONFIG INTENT SCOPE:
- This metric is dynamically scoped by Global Config; analyzer raw rows keep all prompts.
- Denominator must include only active prompts whose intent is enabled for the Visibility metric.
- Numerator counts distinct active Visibility prompts that produced at least one own-brand mention in the date/platform window.
- Join geo_global_intents gi ON gi.intent_name = cp.intent.
- Add cp.client_id = $1, gi.is_active = true, and gi.categories @> ''["Visibility"]''::jsonb.
- Never fall back to all intents when no intent is configured for Visibility.

REFERENCE SQL:
WITH scoped_prompts AS (
  SELECT cp.id
  FROM geo_client_prompts cp
  JOIN geo_global_intents gi
    ON gi.intent_name = cp.intent
  WHERE cp.client_id = $1
    AND cp.is_active = true
    AND gi.is_active = true
    AND gi.categories @> ''["Visibility"]''::jsonb
),
covered_prompts AS (
  SELECT DISTINCT bm.client_prompt_id
  FROM geo_brand_mentions bm
  JOIN geo_results gr
    ON gr.result_id = bm.result_id AND gr.client_id = bm.client_id
  JOIN scoped_prompts sp
    ON sp.id = bm.client_prompt_id
  WHERE bm.client_id = $1
    AND bm.brand_role = ''own''
    AND bm.executed_at BETWEEN $2 AND $3
    AND gr.platform IN ({platforms})
)
SELECT ROUND(
  (SELECT COUNT(*) FROM covered_prompts)::numeric
  / NULLIF((SELECT COUNT(*) FROM scoped_prompts), 0)
  * 100, 2
) AS prompt_coverage_rate;
CRITICAL: Prompt Coverage is prompt-level. Visibility Score is response-level. SOV is mention-volume share. 返回单个百分比数字。',
  relevant_tables = COALESCE(relevant_tables, ARRAY[]::text[])
    || CASE
      WHEN 'geo_global_intents' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_global_intents']::text[]
    END,
  sample_question = '配置为 Visibility 的 active prompts 中，有多少比例至少产生过一次我方品牌提及？',
  unit = '%',
  updated_at = NOW()
WHERE metric_name = 'prompt_coverage_rate';
