-- Migration 039b: Add sql_hint for chart "品牌情感评分分布"
--
-- Problem: Chart 3 shows all zeros because Gemini generates SQL with
-- lowercase sentiment values ('positive', 'negative') but the DB stores
-- capitalized values ('Positive', 'Negative').
--
-- Fix: Add sql_hint with correct capitalization and proper JOIN pattern.
-- Also updates the other two charts' sql_hints to keep the full array intact.

UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,chart_config,default_charts}',
    jsonb_build_array(
        jsonb_build_object(
            'nl_query', '品牌可见度(SOV)与引用率综合趋势（每日）',
            'chart_type', 'line',
            'sql_hint', E'必须使用 CTE 分别计算 SOV 和引用率，再 JOIN。不得用相关子查询。\nREFERENCE SQL:\nWITH daily_sov AS (\n  SELECT DATE(cm.executed_at) AS d,\n    ROUND(SUM(CASE WHEN cm.is_own_brand = true THEN 1 ELSE 0 END)::numeric\n          / NULLIF(COUNT(*), 0) * 100, 2) AS sov\n  FROM geo_company_mentions cm\n  JOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\n  WHERE cm.client_id = $1 AND gr.client_id = $1\n  GROUP BY DATE(cm.executed_at)\n),\ndaily_citation AS (\n  SELECT DATE(c.executed_at) AS d,\n    ROUND(\n      SUM(CASE WHEN EXISTS (SELECT 1 FROM geo_client_domains cd WHERE cd.domain = c.source_domain AND cd.client_id = $1) THEN 1 ELSE 0 END)::numeric\n      / NULLIF(COUNT(*), 0) * 100, 2\n    ) AS citation_rate\n  FROM geo_citations c\n  JOIN geo_results gr ON c.result_id = gr.result_id AND c.client_id = gr.client_id\n  WHERE c.client_id = $1 AND gr.client_id = $1\n  GROUP BY DATE(c.executed_at)\n)\nSELECT s.d AS 日期, s.sov AS \"品牌可见度(%)\", COALESCE(ci.citation_rate, 0) AS \"引用率(%)\"\nFROM daily_sov s\nLEFT JOIN daily_citation ci ON s.d = ci.d\nORDER BY s.d;\nCRITICAL: 品牌可见度 = SOV = own_brand_mentions / ALL_mentions * 100。分母是 COUNT(*) 所有品牌，不是 per-result 粒度。引用率 = own_domain_citations / total_citations * 100。'
        ),
        jsonb_build_object(
            'nl_query', '品牌 vs 竞品在各平台的 SOV 对比',
            'chart_type', 'bar',
            'sql_hint', E'SOV per platform per brand:\nWITH brand_platform AS (\n  SELECT gr.platform,\n    SUM(CASE WHEN cm.is_own_brand = true THEN 1 ELSE 0 END) AS own_count,\n    COUNT(*) AS total_count\n  FROM geo_company_mentions cm\n  JOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\n  WHERE cm.client_id = $1 AND gr.client_id = $1\n  GROUP BY gr.platform\n)\nSELECT platform,\n  ROUND(own_count::numeric / NULLIF(total_count, 0) * 100, 2) AS \"SOV(%)\"\nFROM brand_platform ORDER BY \"SOV(%)\" DESC;\nCRITICAL: SOV = own / total * 100，分母 total 是该平台所有 mentions。'
        ),
        jsonb_build_object(
            'nl_query', '品牌情感评分分布',
            'chart_type', 'pie',
            'sql_hint', E'REFERENCE SQL:\nSELECT cm.company_name,\n  SUM(CASE WHEN sr.sentiment = ''Positive'' THEN 1 ELSE 0 END) AS positive,\n  SUM(CASE WHEN sr.sentiment = ''Negative'' THEN 1 ELSE 0 END) AS negative,\n  COUNT(*) AS total\nFROM geo_company_mentions cm\nJOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\nJOIN geo_sentiment_results sr ON sr.result_id = gr.result_id AND sr.client_id = gr.client_id\nWHERE cm.client_id = $1 AND gr.client_id = $1 AND sr.client_id = $1\nGROUP BY cm.company_name\nORDER BY total DESC\nLIMIT 15;\nCRITICAL: sentiment 值必须首字母大写: ''Positive'', ''Negative''（不是 lowercase）。JOIN 用 result_id + client_id，不要用 task_id（可能为 NULL）。'
        )
    )
),
updated_at = NOW()
WHERE id = '2ce092cd-8479-4cdc-b19a-208084c9e15b';
