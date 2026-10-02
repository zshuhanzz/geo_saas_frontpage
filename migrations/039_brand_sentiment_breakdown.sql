-- Migration 039: Add brand_sentiment_breakdown metric
--
-- Problem: The report cited "Roborock 获得了 103 次正面评价和 3 次负面评价"
-- but NO source metric provides brand × sentiment cross-dimensional data.
-- sentiment_distribution only gives aggregate totals (895 positive / 22 negative).
-- The LLM fabricated the per-brand numbers.
--
-- Fix: Add a new metric that breaks down sentiment by brand (own + top peers),
-- so the LLM has real data for per-brand sentiment claims.
--
-- Also adds the metric to the 综合分析 and 情感分析 template contracts.

-- 1. Insert the new metric into geo_analysis_metrics
INSERT INTO geo_analysis_metrics
    (metric_name, display_name_zh, display_name_en, domain, description,
     calculation_hint, relevant_tables, sample_question, null_behavior, unit, sort_order)
VALUES
  ('brand_sentiment_breakdown',
   '品牌情感分布', 'Brand Sentiment Breakdown', 'sentiment',
   '自有品牌及主要竞品各自的 positive / negative 数量',
   E'REFERENCE SQL:\nWITH brand_sentiment AS (\n  SELECT cm.company_name,\n    cm.is_own_brand,\n    sr.sentiment,\n    COUNT(*) AS cnt\n  FROM geo_sentiment_results sr\n  JOIN geo_results gr ON gr.result_id = sr.result_id AND sr.client_id = gr.client_id\n  JOIN geo_company_mentions cm ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\n  WHERE sr.client_id = $1 AND gr.client_id = $1 AND cm.client_id = $1\n    AND sr.executed_at BETWEEN $2 AND $3\n    AND gr.platform IN ({platforms})\n  GROUP BY cm.company_name, cm.is_own_brand, sr.sentiment\n)\nSELECT company_name AS \"品牌\",\n  SUM(CASE WHEN sentiment = ''Positive'' THEN cnt ELSE 0 END) AS \"正面\",\n  SUM(CASE WHEN sentiment = ''Negative'' THEN cnt ELSE 0 END) AS \"负面\",\n  SUM(cnt) AS \"总计\",\n  ROUND(SUM(CASE WHEN sentiment = ''Positive'' THEN cnt ELSE 0 END)::numeric / NULLIF(SUM(cnt), 0) * 100, 1) AS \"正面率(%)\"\nFROM brand_sentiment\nGROUP BY company_name, is_own_brand\nORDER BY is_own_brand DESC, SUM(cnt) DESC\nLIMIT 10;\nCRITICAL: 必须 JOIN geo_company_mentions 获取 company_name 和 is_own_brand。返回 Markdown 表格: | 品牌 | 正面 | 负面 | 总计 | 正面率(%) |',
   ARRAY['geo_sentiment_results','geo_company_mentions','geo_results'],
   '我方品牌和竞品各自的正面/负面情感数量分别是多少？',
   'return_null', NULL, 11)
ON CONFLICT (metric_name) DO UPDATE SET
    calculation_hint = EXCLUDED.calculation_hint,
    relevant_tables = EXCLUDED.relevant_tables,
    display_name_zh = EXCLUDED.display_name_zh,
    display_name_en = EXCLUDED.display_name_en,
    updated_at = NOW();

-- 2. Add to 综合分析 template contract (wizard_config.steps.metric_config.required_metrics)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,metric_config,required_metrics}',
    (
        SELECT jsonb_agg(elem)
        FROM (
            SELECT elem
            FROM jsonb_array_elements(
                wizard_config->'steps'->'metric_config'->'required_metrics'
            ) AS elem
            UNION
            SELECT '"brand_sentiment_breakdown"'::jsonb
        ) sub
    )
),
updated_at = NOW()
WHERE id = '2ce092cd-8479-4cdc-b19a-208084c9e15b'
  AND NOT (wizard_config->'steps'->'metric_config'->'required_metrics' @> '"brand_sentiment_breakdown"');

-- 3. Add to 情感分析 template contract (if exists)
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,metric_config,required_metrics}',
    (
        SELECT jsonb_agg(elem)
        FROM (
            SELECT elem
            FROM jsonb_array_elements(
                wizard_config->'steps'->'metric_config'->'required_metrics'
            ) AS elem
            UNION
            SELECT '"brand_sentiment_breakdown"'::jsonb
        ) sub
    )
),
updated_at = NOW()
WHERE name = '情感分析'
  AND wizard_config->'steps'->'metric_config'->'required_metrics' IS NOT NULL
  AND NOT (wizard_config->'steps'->'metric_config'->'required_metrics' @> '"brand_sentiment_breakdown"');
