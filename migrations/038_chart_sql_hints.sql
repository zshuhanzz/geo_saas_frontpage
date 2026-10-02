-- Migration 038: Add sql_hint to chart_requests for accurate chart SQL generation
--
-- Problem: Chart SQL is generated via NL2SQL with only the nl_query text,
-- causing Gemini to interpret "品牌可见度" as per-result coverage (50-95%)
-- rather than aggregate SOV (brand mentions / all mentions ≈ 26%).
--
-- Fix: Add sql_hint field to chart_request objects. The pipeline injects
-- the hint as a REFERENCE SQL block in the NL2SQL prompt, constraining
-- Gemini to use the exact formula from the static dashboard.
--
-- Affected templates:
--   综合健康度 (2ce092cd): "品牌可见度、引用率综合趋势" + "品牌 vs 竞品在各平台的 SOV 对比"
--   竞品对标 (first template with SOV charts)

-- ── 综合健康度 ──────────────────────────────────────────────────────────

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

-- ── 竞品对标 ────────────────────────────────────────────────────────────
-- Template with "自有品牌 vs 竞品的 SOV 趋势对比"

UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{steps,chart_config,default_charts}',
    jsonb_build_array(
        jsonb_build_object(
            'nl_query', '各品牌在所有 AI 平台的总提及次数对比',
            'chart_type', 'bar'
        ),
        jsonb_build_object(
            'nl_query', '自有品牌 vs 竞品的 SOV 趋势对比（每日）',
            'chart_type', 'line',
            'sql_hint', E'每日每个品牌的 SOV:\nWITH daily_total AS (\n  SELECT DATE(cm.executed_at) AS d, COUNT(*) AS total\n  FROM geo_company_mentions cm\n  JOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\n  WHERE cm.client_id = $1 AND gr.client_id = $1\n  GROUP BY DATE(cm.executed_at)\n),\nown_daily AS (\n  SELECT DATE(cm.executed_at) AS d,\n    SUM(CASE WHEN cm.is_own_brand THEN 1 ELSE 0 END) AS own_cnt\n  FROM geo_company_mentions cm\n  JOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\n  WHERE cm.client_id = $1 AND gr.client_id = $1\n  GROUP BY DATE(cm.executed_at)\n)\nSELECT dt.d AS 日期,\n  ROUND(od.own_cnt::numeric / NULLIF(dt.total, 0) * 100, 2) AS \"自有品牌SOV(%)\"\nFROM daily_total dt\nJOIN own_daily od ON dt.d = od.d\nORDER BY 1;\nCRITICAL: SOV 分母 = 当日 ALL mentions COUNT(*)。'
        )
    )
),
updated_at = NOW()
WHERE id = '5388ed34-dfa1-4616-895a-84c40d19c882';
