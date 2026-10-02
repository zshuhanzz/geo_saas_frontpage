-- Migration 038b: Fix chart 0 sql_hint — replace correlated subquery with CTE
--
-- Error from 038: "subquery uses ungrouped column cm.executed_at from outer query"
-- Root cause: correlated subquery referenced outer GROUP BY column, which PostgreSQL rejects.
-- Fix: Use two CTEs (daily_sov + daily_citation) joined on date.

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
        jsonb_build_object('nl_query', '品牌情感评分分布', 'chart_type', 'pie')
    )
),
updated_at = NOW()
WHERE id = '2ce092cd-8479-4cdc-b19a-208084c9e15b';
