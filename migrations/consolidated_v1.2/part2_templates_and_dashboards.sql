-- ========================================================================
-- v1.2 Dual-Mode Tracking — Part 2: Templates, Dashboards, Discovery Cron
-- ========================================================================
-- Concat of migrations 046..050. Safe to run after Part 1 settles.
-- ========================================================================

-- ──── 046_v12_metrics_templates_rewrite.sql ────
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

-- ──── 046b_v12_brand_sentiment_breakdown_fix.sql ────
-- ============================================================
-- Migration 046b: Hotfix brand_sentiment_breakdown metric 的 is_own_brand 引用
-- ============================================================
-- 问题:046 主迁移里的简单 replace() 只覆盖了 WHERE is_own_brand = true/false,
--   没覆盖 `cm.is_own_brand` 作为 SELECT 列 / GROUP BY key / ORDER BY key 的情况
-- 这里做一次针对性替换:
--   cm.is_own_brand → (cm.brand_role = 'own') AS is_own_brand (在 SELECT 里派生,保持列名不变)
--   或直接替换为 cm.brand_role(如果下游消费方已适配)
--
-- 为了最小影响下游消费(前端/Agent 可能预期 is_own_brand 列名),此处用派生列方式
-- ============================================================

BEGIN;

UPDATE geo_analysis_metrics
   SET calculation_hint = replace(
                            replace(
                              replace(
                                replace(
                                  calculation_hint,
                                  'GROUP BY cm.brand_name, cm.is_own_brand',
                                  'GROUP BY cm.brand_name, cm.brand_role'
                                ),
                                'cm.is_own_brand,',
                                '(cm.brand_role = ''own'') AS is_own_brand,'
                              ),
                              'GROUP BY brand_name, is_own_brand',
                              'GROUP BY brand_name, is_own_brand'  -- 已经用派生列 alias,无需改
                            ),
                            'ORDER BY is_own_brand DESC',
                            'ORDER BY is_own_brand DESC'  -- 派生列 alias 可正常排序
                          ),
       description = replace(description,
                             'JOIN geo_brand_mentions 获取 brand_name 和 is_own_brand',
                             'JOIN geo_brand_mentions 获取 brand_name 和 brand_role(派生 is_own_brand)'),
       updated_at = NOW()
 WHERE metric_name = 'brand_sentiment_breakdown';

COMMIT;

-- 验证:残留的 cm.is_own_brand 应为 0
-- SELECT COUNT(*) FROM geo_analysis_metrics WHERE calculation_hint LIKE '%cm.is_own_brand%';
-- 期望:0

-- SELECT calculation_hint FROM geo_analysis_metrics WHERE metric_name='brand_sentiment_breakdown';
-- 检查:SELECT 子句应含 (cm.brand_role = 'own') AS is_own_brand

-- ──── 047_v12_url_trigger_regex_hardening.sql ────
-- ============================================================
-- Migration 047: Hotfix — validate_tracked_url_ownership host-extraction regex
-- ============================================================
-- 问题:migration 040 里 host 提取只处理了 scheme + 第一个 '/',不能
-- 正确解析以下 edge cases:
--
--   1. URL 带端口:          https://example.com:8080/path
--      原函数保留端口 → host='example.com:8080'(与无端口登记不匹配)
--
--   2. URL 只有 query:       https://example.com?q=1
--      原函数不剥离 '?' → host='example.com?q=1'
--
--   3. URL 只有 fragment:    https://example.com#section
--      原函数不剥离 '#' → host='example.com#section'
--
--   4. URL 带 userinfo:      https://user:pass@example.com/path
--      原函数不剥离 userinfo → host='user:pass@example.com'
--
-- 本 migration 用 CREATE OR REPLACE FUNCTION 重定义函数体,
-- 保持函数签名 (validate_tracked_url_ownership / RETURNS TRIGGER)
-- 和 trigger 绑定 (trg_validate_tracked_url_ownership) 不变,无需 DROP+CREATE。
--
-- 这是 hotfix,不引入新表 / 列 / 约束,执行安全。
-- ============================================================

BEGIN;

CREATE OR REPLACE FUNCTION validate_tracked_url_ownership()
RETURNS TRIGGER AS $$
DECLARE
    host_from_url            TEXT;
    owner_brand_from_domains UUID;
    owner_peer_from_domains  UUID;
BEGIN
    -- -----------------------------------------------------------------
    -- 规范化提取 host — 依次剥离:
    --   (1) scheme     '^https?://'
    --   (2) userinfo   '^[^@/]*@'         (e.g. user:pass@)
    --   (3) path       '/.*$'
    --   (4) query      '\?.*$'
    --   (5) fragment   '#.*$'
    --   (6) port       ':[0-9]+$'
    --   (7) www prefix '^www\.'
    --   (8) lower-case
    -- 步骤 2 必须在步骤 3/4/5 之前 —— userinfo 段里可能含 '/'/'?'/'#',
    -- 否则路径会先把 userinfo 的尾部吃掉。
    -- -----------------------------------------------------------------
    host_from_url := NEW.url;
    host_from_url := regexp_replace(host_from_url, '^https?://', '');
    host_from_url := regexp_replace(host_from_url, '^[^@/]*@', '');
    host_from_url := regexp_replace(host_from_url, '/.*$', '');
    host_from_url := regexp_replace(host_from_url, '\?.*$', '');
    host_from_url := regexp_replace(host_from_url, '#.*$', '');
    host_from_url := regexp_replace(host_from_url, ':[0-9]+$', '');
    host_from_url := regexp_replace(host_from_url, '^www\.', '');
    host_from_url := LOWER(host_from_url);

    -- 查 geo_client_domains 该 host 归谁(仅认 domain_scope='whole')
    SELECT brand_id, peer_id
      INTO owner_brand_from_domains, owner_peer_from_domains
      FROM geo_client_domains
     WHERE client_id = NEW.client_id
       AND domain_scope = 'whole'
       AND LOWER(domain) = host_from_url
     LIMIT 1;

    IF owner_brand_from_domains IS NOT NULL OR owner_peer_from_domains IS NOT NULL THEN
        -- brand_id 校验
        IF NEW.brand_id IS NOT NULL AND NEW.brand_id IS DISTINCT FROM owner_brand_from_domains THEN
            RAISE EXCEPTION 'URL host % 已登记为其他 Brand。请检查 URL 是否正确。', host_from_url;
        END IF;
        -- peer_id 校验
        IF NEW.peer_id IS NOT NULL AND NEW.peer_id IS DISTINCT FROM owner_peer_from_domains THEN
            RAISE EXCEPTION 'URL host % 已登记为其他 Peer。请检查 URL 是否正确。', host_from_url;
        END IF;
        -- 用户未填 FK → 自动补
        IF NEW.brand_id IS NULL AND NEW.peer_id IS NULL THEN
            NEW.brand_id := owner_brand_from_domains;
            NEW.peer_id := owner_peer_from_domains;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMIT;

-- ============================================================
-- 验证(执行后手动跑)
-- ============================================================
-- -- 1. 带端口的 URL 应正确归属已登记的 host
-- --    假设 client X 已登记 geo_client_domains: domain='shop.brand.com',domain_scope='whole',brand_id=B
-- --    INSERT INTO geo_product_tracked_urls (..., url='https://shop.brand.com:8080/p/1', brand_id=B) 应成功
-- --    INSERT INTO geo_product_tracked_urls (..., url='https://shop.brand.com:8080/p/1', brand_id=OTHER_B) 应 RAISE
--
-- -- 2. 带 userinfo 的 URL
-- --    url='https://user:pass@shop.brand.com/path' 应被识别为 host='shop.brand.com'
--
-- -- 3. 只有 query 或 fragment 的 URL
-- --    url='https://shop.brand.com?utm=x' 或 'https://shop.brand.com#top' 应被识别为 'shop.brand.com'

-- ──── 048_v12_llm_discovery_model_seed.sql ────
-- ============================================================
-- Migration 048: Dual-Mode Tracking v1.2 - Phase 6 LLM Discovery model_id seed
-- ============================================================
-- 背景:Phase 6(LLM Batch Discovery)从 geo_global_settings 读 model_id,
-- key 为 'llm_batch_discovery_model_id'。此 key 在 v1.2 代码里有读取,
-- 但 migrations/046 没 seed。未 seed 时会 fallback 到硬编码 'gemini-2.0-flash',
-- 此模型在 GEO project 上无访问权(404)。
--
-- Layer 5b 本地验证时发现此问题(见 SESSION_HANDOFF_2026-04-20.md §5),
-- 本 migration 补 seed,保持和 sentiment_model_id / domain_classifier_model_id 一致。
-- ============================================================

BEGIN;

INSERT INTO geo_global_settings (key, value, description)
VALUES (
    'llm_batch_discovery_model_id',
    'gemini-3-flash-preview',
    'Phase 6 LLM Batch Discovery 使用的 Gemini model。保持和 sentiment/domain_classifier 同一模型,统一 model 升级/回滚。'
)
ON CONFLICT (key) DO UPDATE
  SET value = EXCLUDED.value,
      updated_at = NOW();

COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- SELECT key, value FROM geo_global_settings WHERE key = 'llm_batch_discovery_model_id';
-- 期望 value = 'gemini-3-flash-preview'

-- ──── 049_v12_cron_llm_discovery.sql ────
-- ============================================================
-- Migration 049: Dual-Mode Tracking v1.2 - Per-client LLM Discovery cron
-- ============================================================
-- 背景:Phase 6(LLM Batch Discovery)原设计是单一 global Cloud Scheduler
-- (见 geo_analyzer/terraform/suggestions.tf google_cloud_scheduler_job.geo_suggestions_daily)。
-- 真实运营中每个客户的数据量、上线节奏、Flash token 预算都不同,需要按客户独立调度。
--
-- 本 migration 为 geo_clients 增加 cron_llm_discovery 字段,复用现有
-- services/gcp_scheduler.sync_scheduler_job 机制(和 cron_collector / cron_analyzer 同构)
-- 由 Admin API 按客户动态创建/更新 Cloud Scheduler Job,指向
-- POST /api/clients/{client_id}/jobs/llm_discovery/run
-- 该 endpoint 会以 CLIENT_ID env override 方式触发
-- Cloud Run Job `geo-analyzer-llm-batch-discovery`。
-- ============================================================

BEGIN;

ALTER TABLE geo_clients
    ADD COLUMN IF NOT EXISTS cron_llm_discovery TEXT;

COMMENT ON COLUMN geo_clients.cron_llm_discovery IS
    'Per-client Cloud Scheduler cron for LLM Batch Discovery (Phase 6). '
    'NULL = no schedule (manual trigger only). Managed by Admin UI; '
    'sync_scheduler_job() creates/updates geo-llm_discovery-<short_id> Cloud Scheduler job.';

COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- \d geo_clients
-- 期望看到 cron_llm_discovery | text | | |

-- ──── 050_v12_channel_performance_goal_and_wizard_fix.sql ────
-- ============================================================
-- Migration 050: 渠道表现分析 (Channel Performance) support
-- ============================================================
-- Two fixes for the 渠道表现分析 (channel performance) analysis
-- template that was added for OEM clients but shipped half-complete:
--
--   1. Add a matching `channel_performance` analysis_goal to
--      geo_workflow_config so the Wizard Step 1 dropdown has a
--      semantically-correct option. Without this, the template's
--      default_goal has no matching row and the LLM downstream
--      doesn't know what "channel performance" means.
--
--   2. Complete the template's wizard_config. Currently only
--      chart_config is filled in; analysis_goal / analysis_framework /
--      data_selection are missing, which means:
--        - Wizard Step 1 has no default_goal
--        - Wizard Step 2 has no default_lenses
--        - Wizard Step 3 has no default_domains/platforms/date_range
--      Fix by backfilling sensible defaults aligned with other
--      built-in templates (e.g. 综合分析).
--
-- Non-OEM clients must NOT see this template — that is enforced
-- frontend-side via wizard_config.visibility_condition.has_shadow_brands,
-- which is already set. The bug was that AgentAnalysis.tsx didn't
-- honour the flag; fixed in a separate frontend patch.
-- ============================================================

BEGIN;

-- ── 1. New analysis goal: channel_performance ───────────────────

INSERT INTO geo_workflow_config (scope, config_type, key, value, sort_order, is_active)
VALUES (
    'analysis',
    'goal',
    'channel_performance',
    jsonb_build_object(
        'label', '渠道表现分析',
        'description', '(OEM/ODM 专用) 分析 shadow brand 与 own product 在 AI 答案中的共现、产品在不同经销渠道的声量对比、以及 citation_role 引用归因'
    ),
    6,
    TRUE
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
    SET value = EXCLUDED.value,
        sort_order = EXCLUDED.sort_order,
        is_active = TRUE;

-- ── 2. Complete 渠道表现分析 wizard_config ──────────────────────
--
-- Strategy: keep chart_config + visibility_condition + required_metrics
-- intact, add the three missing step stanzas with sensible defaults.

UPDATE geo_report_templates
SET wizard_config = jsonb_build_object(
    'steps', jsonb_build_object(
        'analysis_goal', jsonb_build_object(
            'enabled', true,
            'default_goal', 'channel_performance'
        ),
        'analysis_framework', jsonb_build_object(
            'enabled', true,
            -- OEM performance analysis needs current-state reading +
            -- gap diagnosis + action recommendations.
            'default_lenses', jsonb_build_array('descriptive', 'diagnostic', 'prescriptive')
        ),
        'data_selection', jsonb_build_object(
            'enabled', true,
            'default_peers', jsonb_build_array(),
            'default_domains', jsonb_build_array('visibility', 'citation'),
            'default_platforms', jsonb_build_array('chatgpt', 'gemini', 'aimode'),
            'default_date_range', 'last_30d'
        ),
        'chart_config', wizard_config->'steps'->'chart_config'
    ),
    'required_metrics', wizard_config->'required_metrics',
    'visibility_condition', wizard_config->'visibility_condition'
)
WHERE name = '渠道表现分析' AND is_builtin = TRUE;

COMMIT;

-- ============================================================
-- Verify
-- ============================================================
-- SELECT scope, key, value->>'label' AS label, sort_order
--   FROM geo_workflow_config
--   WHERE scope='analysis' AND config_type='goal'
--   ORDER BY sort_order;
-- Expect to see `channel_performance | 渠道表现分析 | 6`
--
-- SELECT jsonb_object_keys(wizard_config->'steps')
--   FROM geo_report_templates WHERE name='渠道表现分析';
-- Expect: analysis_goal, analysis_framework, data_selection, chart_config

