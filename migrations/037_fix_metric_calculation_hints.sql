-- Migration 037: Align ALL metric calculation_hints with static dashboard SQL
--
-- Root cause: NL2SQL hints were vague natural language, causing Gemini to
-- generate SQL with wrong tables, wrong denominators, and wrong joins.
-- Fix: Each hint now contains a REFERENCE SQL template that mirrors the
-- exact formula used in the static dashboard (geo_saas).
--
-- Changes per metric:
--   sov_trend: denominator = ALL mentions COUNT(*), not just own+peers
--   visibility_rank_vs_peers: subquery-per-peer, no JOIN inflation
--   platform_visibility_breakdown: explicit JOIN + platform filter
--   peer_citation_share: use geo_citations (source URLs), NOT geo_company_mentions
--   citation_source_diversity: ALL citations domain_category, not just own-domain
--   sentiment_distribution: explicit JOIN pattern matching dashboard
--   sentiment_trend: explicit JOIN + date grouping matching dashboard

-- 1. sov_trend
UPDATE geo_analysis_metrics
SET calculation_hint = E'REFERENCE SQL (与静态 dashboard 完全一致):\nSELECT DATE(cm.executed_at) AS date,\n  ROUND(SUM(CASE WHEN cm.is_own_brand = true THEN 1 ELSE 0 END)::numeric\n        / NULLIF(COUNT(*), 0) * 100, 2) AS sov\nFROM geo_company_mentions cm\nJOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\nWHERE cm.client_id = $1 AND gr.client_id = $1\n  AND cm.executed_at BETWEEN $2 AND $3\n  AND gr.platform IN ({platforms})\nGROUP BY DATE(cm.executed_at) ORDER BY 1;\nCRITICAL: 分母 = COUNT(*) 即所有品牌的 mention 总数（不仅是 own+peers）。不需要 JOIN geo_client_peers。返回 Markdown 表格: | Date | SOV |',
    updated_at = NOW()
WHERE metric_name = 'sov_trend';

-- 2. visibility_rank_vs_peers
UPDATE geo_analysis_metrics
SET calculation_hint = E'REFERENCE SQL:\nWITH own_brand_count AS (\n  SELECT COUNT(*) AS cnt\n  FROM geo_company_mentions cm\n  JOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\n  WHERE cm.client_id = $1 AND gr.client_id = $1\n    AND cm.executed_at BETWEEN $2 AND $3\n    AND cm.is_own_brand = true\n    AND gr.platform IN ({platforms})\n),\npeer_counts AS (\n  SELECT p.primary_name AS brand_label,\n    (SELECT COUNT(DISTINCT m.id) FROM geo_company_mentions m\n     JOIN geo_results gr ON m.result_id = gr.result_id AND m.client_id = gr.client_id\n     WHERE m.client_id = $1 AND gr.client_id = $1\n       AND m.executed_at BETWEEN $2 AND $3\n       AND m.is_own_brand = false\n       AND (m.company_name = p.primary_name OR m.company_name = ANY(p.aliases))\n       AND gr.platform IN ({platforms})\n    ) AS mention_count\n  FROM geo_client_peers p WHERE p.client_id = $1\n),\ncombined AS (\n  SELECT ''__OWN_BRAND__'' AS brand_label, cnt AS mention_count FROM own_brand_count\n  UNION ALL\n  SELECT brand_label, mention_count FROM peer_counts WHERE mention_count > 0\n),\nranked AS (\n  SELECT *, ROW_NUMBER() OVER (ORDER BY mention_count DESC) AS rk,\n    COUNT(*) OVER () AS total FROM combined\n)\nSELECT CASE WHEN NOT EXISTS (SELECT 1 FROM geo_client_peers WHERE client_id = $1) THEN NULL\n  ELSE (SELECT ''Own Brand Rank: '' || rk || '' / '' || total FROM ranked WHERE brand_label = ''__OWN_BRAND__'')\nEND;\nCRITICAL: 不用 LEFT JOIN unnest(aliases)，用子查询 + COUNT(DISTINCT m.id) 避免 JOIN 膨胀。',
    updated_at = NOW()
WHERE metric_name = 'visibility_rank_vs_peers';

-- 3. prompt_coverage_rate
UPDATE geo_analysis_metrics
SET calculation_hint = E'REFERENCE SQL:\nSELECT ROUND(\n  (SELECT COUNT(DISTINCT cm.client_prompt_id)\n   FROM geo_company_mentions cm\n   JOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\n   WHERE cm.client_id = $1 AND gr.client_id = $1\n     AND cm.executed_at BETWEEN $2 AND $3\n     AND cm.is_own_brand = true\n     AND gr.platform IN ({platforms})\n  )::numeric\n  / NULLIF((SELECT COUNT(*) FROM geo_client_prompts WHERE client_id = $1 AND is_active = true), 0)\n  * 100, 2\n);\n返回单个百分比数字。',
    updated_at = NOW()
WHERE metric_name = 'prompt_coverage_rate';

-- 4. platform_visibility_breakdown
UPDATE geo_analysis_metrics
SET calculation_hint = E'REFERENCE SQL (与静态 dashboard 一致):\nSELECT gr.platform, COUNT(*) AS own_brand_mentions\nFROM geo_company_mentions cm\nJOIN geo_results gr ON cm.result_id = gr.result_id AND cm.client_id = gr.client_id\nWHERE cm.client_id = $1 AND gr.client_id = $1\n  AND cm.executed_at BETWEEN $2 AND $3\n  AND cm.is_own_brand = true\n  AND gr.platform IN ({platforms})\nGROUP BY gr.platform ORDER BY own_brand_mentions DESC;\n返回 Markdown 表格: | Platform | Own Brand Mentions |',
    updated_at = NOW()
WHERE metric_name = 'platform_visibility_breakdown';

-- 5. peer_citation_share (CRITICAL FIX: use geo_citations, NOT geo_company_mentions)
UPDATE geo_analysis_metrics
SET calculation_hint = E'IMPORTANT: 必须使用 geo_citations 表（AI 回答中引用的源 URL），\n绝对不能使用 geo_company_mentions（那是品牌名提及 = Visibility 指标）。\nREFERENCE SQL (与静态 dashboard 一致):\nWITH domain_stats AS (\n  SELECT c.source_domain,\n    COUNT(*) AS citation_count,\n    MIN(c.domain_category) AS domain_category\n  FROM geo_citations c\n  JOIN geo_client_prompts cp ON c.client_prompt_id = cp.id\n  JOIN geo_results gr ON c.result_id = gr.result_id AND c.client_id = gr.client_id\n  WHERE c.client_id = $1 AND gr.client_id = $1\n    AND c.executed_at BETWEEN $2 AND $3\n    AND gr.platform IN ({platforms})\n  GROUP BY c.source_domain ORDER BY citation_count DESC LIMIT 15\n),\ntotal AS (SELECT COUNT(*) AS cnt FROM geo_citations c\n  JOIN geo_results gr ON c.result_id = gr.result_id AND c.client_id = gr.client_id\n  WHERE c.client_id = $1 AND gr.client_id = $1\n    AND c.executed_at BETWEEN $2 AND $3 AND gr.platform IN ({platforms}))\nSELECT source_domain, citation_count,\n  ROUND(citation_count::numeric / NULLIF((SELECT cnt FROM total), 0) * 100, 2) AS share_pct,\n  CASE WHEN EXISTS (SELECT 1 FROM geo_client_domains d\n    WHERE d.domain = source_domain AND d.client_id = $1) THEN ''★ own'' ELSE '''' END AS is_own\nFROM domain_stats;\n''own'' 的判定：source_domain 存在于 geo_client_domains (WHERE client_id=$1) 中。返回 Markdown 表格: | Domain | Citations | Share% | Own |',
    updated_at = NOW()
WHERE metric_name = 'peer_citation_share';

-- 6. citation_source_diversity (FIX: ALL citations, not just own-domain)
UPDATE geo_analysis_metrics
SET calculation_hint = E'统计该客户 ALL 引用的类别多样性（不限于自有域名）。\nIMPORTANT: 不要 JOIN geo_client_domains 过滤 — 要看所有引用的类别分布。\nREFERENCE SQL (与静态 dashboard Citation Categories 一致):\nWITH categorized AS (\n  SELECT COALESCE(c.domain_category, ''Other'') AS category, COUNT(*) AS cnt\n  FROM geo_citations c\n  JOIN geo_results gr ON c.result_id = gr.result_id AND c.client_id = gr.client_id\n  WHERE c.client_id = $1 AND gr.client_id = $1\n    AND c.executed_at BETWEEN $2 AND $3\n    AND gr.platform IN ({platforms})\n  GROUP BY COALESCE(c.domain_category, ''Other'')\n),\ntotal AS (SELECT SUM(cnt) AS t FROM categorized)\nSELECT category, cnt AS citation_count,\n  ROUND(cnt::numeric / NULLIF((SELECT t FROM total), 0) * 100, 2) AS share_pct\nFROM categorized ORDER BY cnt DESC;\n注意：直接用 geo_citations.domain_category 列（已有分类），不需要 JOIN geo_domain_categories。返回 Markdown 表格: | Category | Citations | Share% |',
    updated_at = NOW()
WHERE metric_name = 'citation_source_diversity';

-- 7. sentiment_distribution
UPDATE geo_analysis_metrics
SET calculation_hint = E'REFERENCE SQL (与静态 dashboard 一致):\nSELECT sr.sentiment,\n  COUNT(*) AS count,\n  ROUND(COUNT(*)::numeric / NULLIF(SUM(COUNT(*)) OVER (), 0) * 100, 2) AS percentage\nFROM geo_sentiment_results sr\nJOIN geo_results gr ON gr.result_id = sr.result_id AND sr.client_id = gr.client_id\nWHERE sr.client_id = $1 AND gr.client_id = $1\n  AND sr.executed_at BETWEEN $2 AND $3\n  AND gr.platform IN ({platforms})\nGROUP BY sr.sentiment ORDER BY count DESC;\n返回 Markdown 表格: | Sentiment | Count | Percentage |',
    updated_at = NOW()
WHERE metric_name = 'sentiment_distribution';

-- 8. sentiment_trend
UPDATE geo_analysis_metrics
SET calculation_hint = E'REFERENCE SQL (与静态 dashboard 一致):\nSELECT DATE(sr.executed_at) AS date,\n  ROUND(SUM(CASE WHEN sr.sentiment = ''Positive'' THEN 1 ELSE 0 END)::numeric\n        / NULLIF(COUNT(*), 0) * 100, 2) AS positive_pct,\n  ROUND(SUM(CASE WHEN sr.sentiment = ''Neutral'' THEN 1 ELSE 0 END)::numeric\n        / NULLIF(COUNT(*), 0) * 100, 2) AS neutral_pct,\n  ROUND(SUM(CASE WHEN sr.sentiment = ''Negative'' THEN 1 ELSE 0 END)::numeric\n        / NULLIF(COUNT(*), 0) * 100, 2) AS negative_pct\nFROM geo_sentiment_results sr\nJOIN geo_results gr ON gr.result_id = sr.result_id AND sr.client_id = gr.client_id\nWHERE sr.client_id = $1 AND gr.client_id = $1\n  AND sr.executed_at BETWEEN $2 AND $3\n  AND gr.platform IN ({platforms})\nGROUP BY DATE(sr.executed_at) ORDER BY 1;\n返回 Markdown 表格: | Date | Positive% | Neutral% | Negative% |',
    updated_at = NOW()
WHERE metric_name = 'sentiment_trend';
