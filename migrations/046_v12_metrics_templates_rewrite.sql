-- ============================================================
-- Migration 046: Dual-Mode Tracking v1.2 - Metrics + Templates 重写 + 新 metrics seed
-- ============================================================
-- Spec §7.1 / §7.2 / §7.3 / §7.4
--
-- 内容:
--   1. 批量替换现有 geo_analysis_metrics.calculation_hint / relevant_tables
--   2. 批量替换 geo_report_templates.wizard_config 中的旧 schema
--   3. Peer SOV 正确性修复(基于 peers_list 而非 brand_role='peer')
--   4. Seed 6 个新 metrics(§7.2)
--   5. 新建 "渠道表现分析" 模板(OEM 专属)
-- ============================================================

BEGIN;

-- ============================================================
-- Part 1:批量替换 geo_analysis_metrics.calculation_hint
-- ============================================================

-- 1.1 geo_company_mentions → geo_brand_mentions(所有引用)
UPDATE geo_analysis_metrics
   SET calculation_hint = replace(calculation_hint,
                                  'geo_company_mentions', 'geo_brand_mentions'),
       updated_at = NOW()
 WHERE calculation_hint LIKE '%geo_company_mentions%';

-- 1.2 is_own_brand = true → brand_role = 'own'
UPDATE geo_analysis_metrics
   SET calculation_hint = replace(calculation_hint,
                                  'is_own_brand = true', 'brand_role = ''own'''),
       updated_at = NOW()
 WHERE calculation_hint LIKE '%is_own_brand = true%';

-- 1.3 is_own_brand = false → 基于 peers_list 的 EXISTS(正确性修复)
-- 注意:这里需要针对不同上下文分别处理,简单 replace 可能不完全 accurate
-- 策略:先用占位符替换,详细 metric 由后续 seed 覆盖
UPDATE geo_analysis_metrics
   SET calculation_hint = replace(calculation_hint,
                                  'is_own_brand = false',
                                  'EXISTS (SELECT 1 FROM geo_client_peers p WHERE p.client_id = bm.client_id AND (p.primary_name ILIKE bm.brand_name OR bm.brand_name = ANY(p.aliases)))'),
       updated_at = NOW()
 WHERE calculation_hint LIKE '%is_own_brand = false%';

-- 1.4 company_name → brand_name
UPDATE geo_analysis_metrics
   SET calculation_hint = replace(calculation_hint,
                                  'company_name', 'brand_name'),
       updated_at = NOW()
 WHERE calculation_hint LIKE '%company_name%';

-- 1.5 relevant_tables 数组更新
UPDATE geo_analysis_metrics
   SET relevant_tables = array_replace(relevant_tables,
                                       'geo_company_mentions', 'geo_brand_mentions')
 WHERE 'geo_company_mentions' = ANY(relevant_tables);


-- ============================================================
-- Part 2:批量替换 geo_report_templates.wizard_config(JSONB)
-- ============================================================
UPDATE geo_report_templates
   SET wizard_config = (replace(
                          replace(
                            replace(
                              replace(
                                wizard_config::text,
                                'geo_company_mentions', 'geo_brand_mentions'
                              ),
                              'is_own_brand = true', 'brand_role = ''own'''
                            ),
                            'cm.is_own_brand', 'cm.brand_role'
                          ),
                          'company_name', 'brand_name'
                        ))::jsonb,
       updated_at = NOW()
 WHERE wizard_config::text LIKE '%geo_company_mentions%'
    OR wizard_config::text LIKE '%is_own_brand%'
    OR wizard_config::text LIKE '%company_name%';


-- ============================================================
-- Part 3:Seed 6 个新 metrics(§7.2)
-- 使用实际 schema: (metric_name, display_name_zh, display_name_en, domain,
--                    description, calculation_hint, relevant_tables,
--                    null_behavior, sort_order, is_active)
-- ============================================================

-- 3.1 product_sov_own — 自家产品声量占比
INSERT INTO geo_analysis_metrics
    (metric_name, display_name_zh, display_name_en, domain, description,
     calculation_hint, relevant_tables, null_behavior, sort_order, is_active)
VALUES
    ('product_sov_own',
     '自家产品声量占比',
     'Own Products SOV',
     'visibility',
     '按 Topic 切分,自家产品(product_role=own)的 mention 数占该 Topic 所有产品 mention 的百分比',
     'SELECT pm.product_name, COUNT(*) AS mentions, ' ||
     'ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY ctp.topic_id), 0), 2) AS sov_pct ' ||
     'FROM geo_product_mentions pm ' ||
     'JOIN geo_client_topic_products ctp ON ctp.id = pm.product_id ' ||
     'WHERE pm.client_id = $1 AND pm.product_role = ''own'' ' ||
     'AND pm.executed_at BETWEEN $2 AND $3 ' ||
     'GROUP BY pm.product_name, ctp.topic_id ORDER BY mentions DESC',
     ARRAY['geo_product_mentions','geo_client_topic_products'],
     'return_zero', 100, true)
  ON CONFLICT (metric_name) DO UPDATE SET
     calculation_hint = EXCLUDED.calculation_hint,
     relevant_tables = EXCLUDED.relevant_tables,
     description = EXCLUDED.description,
     updated_at = NOW();

-- 3.2 shadow_cooccurrence_own_product — 渠道×自家产品共现(诉求 3)
INSERT INTO geo_analysis_metrics
    (metric_name, display_name_zh, display_name_en, domain, description,
     calculation_hint, relevant_tables, null_behavior, sort_order, is_active)
VALUES
    ('shadow_cooccurrence_own_product',
     '经销渠道 × 自家产品共现',
     'Shadow Brand × Own Product Co-occurrence',
     'visibility',
     '同一条 AI response 里同时 mention 经销渠道品牌(shadow)和自家产品(own)的次数。OEM/代理销售模式下最核心的指标。',
     'SELECT DATE(bm.executed_at) AS date, bm.brand_name AS shadow_brand, ' ||
     'pm.product_name, COUNT(DISTINCT bm.result_id) AS cooccurrence ' ||
     'FROM geo_brand_mentions bm ' ||
     'JOIN geo_product_mentions pm ON pm.result_id = bm.result_id AND pm.client_id = bm.client_id ' ||
     'WHERE bm.client_id = $1 AND bm.brand_role = ''shadow'' AND pm.product_role = ''own'' ' ||
     'AND bm.executed_at BETWEEN $2 AND $3 ' ||
     'GROUP BY 1, 2, 3 ORDER BY 1, cooccurrence DESC',
     ARRAY['geo_brand_mentions','geo_product_mentions'],
     'return_zero', 101, true)
  ON CONFLICT (metric_name) DO UPDATE SET
     calculation_hint = EXCLUDED.calculation_hint,
     relevant_tables = EXCLUDED.relevant_tables,
     description = EXCLUDED.description,
     updated_at = NOW();

-- 3.3 shadow_cooccurrence_peer_product — 渠道×非我产品共现(诉求 4)
INSERT INTO geo_analysis_metrics
    (metric_name, display_name_zh, display_name_en, domain, description,
     calculation_hint, relevant_tables, null_behavior, sort_order, is_active)
VALUES
    ('shadow_cooccurrence_peer_product',
     '经销渠道 × 非我产品共现',
     'Shadow Brand × Non-own Product Co-occurrence',
     'visibility',
     '同一条 AI response 里同时 mention 经销渠道品牌和该渠道上的非我产品(shadow_brand_product)的次数。反映渠道内竞争格局。',
     'SELECT DATE(bm.executed_at) AS date, bm.brand_name AS shadow_brand, ' ||
     'pm.product_name, pm.shadow_sub_role, COUNT(DISTINCT bm.result_id) AS cooccurrence ' ||
     'FROM geo_brand_mentions bm ' ||
     'JOIN geo_product_mentions pm ON pm.result_id = bm.result_id AND pm.client_id = bm.client_id ' ||
     'WHERE bm.client_id = $1 AND bm.brand_role = ''shadow'' AND pm.product_role = ''shadow_brand_product'' ' ||
     'AND bm.executed_at BETWEEN $2 AND $3 ' ||
     'GROUP BY 1, 2, 3, 4 ORDER BY 1, cooccurrence DESC',
     ARRAY['geo_brand_mentions','geo_product_mentions'],
     'return_zero', 102, true)
  ON CONFLICT (metric_name) DO UPDATE SET
     calculation_hint = EXCLUDED.calculation_hint,
     description = EXCLUDED.description,
     updated_at = NOW();

-- 3.4 peer_sov_via_peers_list — 竞品声量(正确性修复版)
INSERT INTO geo_analysis_metrics
    (metric_name, display_name_zh, display_name_en, domain, description,
     calculation_hint, relevant_tables, null_behavior, sort_order, is_active)
VALUES
    ('peer_sov_via_peers_list',
     '竞品声量分析',
     'Peer SOV (via peers list)',
     'visibility',
     '所有被标记为竞品的品牌的声量对比。基于 geo_client_peers 成员身份判定,覆盖 RC 既是经销渠道又是竞品的情况(此时 brand_role=shadow,旧的 brand_role=peer 过滤会漏掉)。',
     'SELECT bm.brand_name, COUNT(*) AS mentions ' ||
     'FROM geo_brand_mentions bm ' ||
     'WHERE bm.client_id = $1 AND bm.executed_at BETWEEN $2 AND $3 ' ||
     'AND EXISTS (SELECT 1 FROM geo_client_peers p ' ||
     '            WHERE p.client_id = bm.client_id ' ||
     '              AND (p.primary_name ILIKE bm.brand_name OR bm.brand_name = ANY(p.aliases))) ' ||
     'GROUP BY bm.brand_name ORDER BY mentions DESC',
     ARRAY['geo_brand_mentions','geo_client_peers'],
     'return_zero', 103, true)
  ON CONFLICT (metric_name) DO UPDATE SET
     calculation_hint = EXCLUDED.calculation_hint,
     relevant_tables = EXCLUDED.relevant_tables,
     description = EXCLUDED.description,
     updated_at = NOW();

-- 3.5 citation_by_citation_role — 引用分类分布
INSERT INTO geo_analysis_metrics
    (metric_name, display_name_zh, display_name_en, domain, description,
     calculation_hint, relevant_tables, null_behavior, sort_order, is_active)
VALUES
    ('citation_by_citation_role',
     '引用分布(按类型)',
     'Citation Breakdown by Role',
     'citation',
     '按 citation_role 分类的引用计数,涵盖 own_domain / shadow_product / peer_channel / earned / social 等所有归因类型',
     'SELECT citation_role, COUNT(*) AS citations ' ||
     'FROM geo_citations ' ||
     'WHERE client_id = $1 AND executed_at BETWEEN $2 AND $3 ' ||
     'AND citation_role IS NOT NULL ' ||
     'GROUP BY citation_role ORDER BY citations DESC',
     ARRAY['geo_citations'],
     'return_zero', 104, true)
  ON CONFLICT (metric_name) DO UPDATE SET
     calculation_hint = EXCLUDED.calculation_hint,
     relevant_tables = EXCLUDED.relevant_tables,
     description = EXCLUDED.description,
     updated_at = NOW();

-- 3.6 product_sentiment_by_role — 产品情感(按角色)
INSERT INTO geo_analysis_metrics
    (metric_name, display_name_zh, display_name_en, domain, description,
     calculation_hint, relevant_tables, null_behavior, sort_order, is_active)
VALUES
    ('product_sentiment_by_role',
     '产品情感分析(按角色)',
     'Product Sentiment by Role',
     'sentiment',
     'Entity-level sentiment,按 product_role(own / shadow / peer)切分',
     'SELECT pm.product_role, pm.shadow_sub_role, sr.sentiment, COUNT(*) AS cnt ' ||
     'FROM geo_sentiment_results sr ' ||
     'JOIN geo_product_mentions pm ON pm.result_id = sr.result_id AND pm.client_id = sr.client_id ' ||
     'WHERE pm.client_id = $1 AND pm.executed_at BETWEEN $2 AND $3 ' ||
     'GROUP BY 1, 2, 3',
     ARRAY['geo_sentiment_results','geo_product_mentions'],
     'return_zero', 105, true)
  ON CONFLICT (metric_name) DO UPDATE SET
     calculation_hint = EXCLUDED.calculation_hint,
     relevant_tables = EXCLUDED.relevant_tables,
     description = EXCLUDED.description,
     updated_at = NOW();


-- ============================================================
-- Part 4:新建 "渠道表现分析" 模板(OEM 专属,触发条件 has_shadow_brands=true)
-- 使用实际 schema: (name, description, task_type, wizard_config,
--                    is_builtin, is_active, sort_order)
-- 注意:geo_report_templates 没有 UNIQUE 约束,采用 DELETE-then-INSERT 保证幂等
-- ============================================================

DELETE FROM geo_report_templates
 WHERE name = '渠道表现分析' AND task_type = 'analysis';

INSERT INTO geo_report_templates
    (name, description, task_type, wizard_config, is_builtin, is_active, sort_order)
VALUES
    ('渠道表现分析',
     '分析自家产品在经销渠道上的表现,以及经销渠道上的竞争格局。适合 OEM/ODM 客户或同时在第三方平台销售的自营品牌客户。仅在配置了至少一个经销渠道品牌(Shadow Brand)时可见。',
     'analysis',
     '{
       "visibility_condition": {"has_shadow_brands": true},
       "required_metrics": [
         "shadow_cooccurrence_own_product",
         "shadow_cooccurrence_peer_product",
         "product_sov_own",
         "citation_by_citation_role"
       ],
       "steps": {
         "chart_config": {
           "default_charts": [
             {
               "nl_query": "经销渠道与自家产品共现趋势(近 30 天)",
               "chart_type": "line",
               "sql_hint": "SELECT DATE(bm.executed_at) AS date, COUNT(DISTINCT bm.result_id) AS cooccurrence FROM geo_brand_mentions bm JOIN geo_product_mentions pm ON pm.result_id = bm.result_id AND pm.client_id = bm.client_id WHERE bm.client_id = $1 AND bm.brand_role = ''shadow'' AND pm.product_role = ''own'' AND bm.executed_at >= NOW() - INTERVAL ''30 days'' GROUP BY 1 ORDER BY 1"
             },
             {
               "nl_query": "经销渠道上的产品分布(按类型切分)",
               "chart_type": "bar",
               "sql_hint": "SELECT pm.shadow_sub_role, COUNT(*) AS mentions FROM geo_product_mentions pm WHERE pm.client_id = $1 AND pm.product_role = ''shadow_brand_product'' AND pm.executed_at BETWEEN $2 AND $3 GROUP BY pm.shadow_sub_role"
             },
             {
               "nl_query": "自家产品在不同经销渠道的声量对比",
               "chart_type": "bar",
               "sql_hint": "SELECT bm.brand_name AS channel, pm.product_name, COUNT(DISTINCT bm.result_id) AS cnt FROM geo_brand_mentions bm JOIN geo_product_mentions pm ON pm.result_id = bm.result_id AND pm.client_id = bm.client_id WHERE bm.client_id = $1 AND bm.brand_role = ''shadow'' AND pm.product_role = ''own'' AND bm.executed_at BETWEEN $2 AND $3 GROUP BY 1, 2 ORDER BY cnt DESC"
             },
             {
               "nl_query": "引用分布(按归因类型)",
               "chart_type": "pie",
               "sql_hint": "SELECT citation_role, COUNT(*) AS cnt FROM geo_citations WHERE client_id = $1 AND executed_at BETWEEN $2 AND $3 AND citation_role IS NOT NULL GROUP BY citation_role"
             }
           ]
         }
       }
     }'::jsonb,
     true, true, 50);


COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- SELECT metric_name FROM geo_analysis_metrics
--  WHERE metric_name IN ('product_sov_own','shadow_cooccurrence_own_product',
--    'shadow_cooccurrence_peer_product','peer_sov_via_peers_list',
--    'citation_by_citation_role','product_sentiment_by_role');
-- 期望:6 行

-- SELECT name, task_type FROM geo_report_templates WHERE name='渠道表现分析';
-- 期望:1 行

-- SELECT COUNT(*) FROM geo_analysis_metrics
--  WHERE calculation_hint LIKE '%geo_company_mentions%'
--     OR calculation_hint LIKE '%is_own_brand%'
--     OR calculation_hint LIKE '%company_name%';
-- 期望:0 行(全部替换完)
