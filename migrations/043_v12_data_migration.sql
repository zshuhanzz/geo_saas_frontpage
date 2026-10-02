-- ============================================================
-- Migration 043: Dual-Mode Tracking v1.2 - 存量数据迁移
-- ============================================================
-- Spec §11.1 Step 1
--
-- 迁移内容:
--   1. geo_client_brands seed - 每个 client 一行 Own Brand
--   2. geo_client_topic_products 从 geo_client_topics.products TEXT[] 迁出
--   3. geo_client_domains.brand_id 回填到 Own Brand
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. Seed geo_client_brands - 每个存量 client 插入一行 Own Brand
-- ------------------------------------------------------------
INSERT INTO geo_client_brands (client_id, brand_name, aliases, is_shadow)
SELECT id, name, COALESCE(aliases, '{}'::text[]), false
  FROM geo_clients
  ON CONFLICT (client_id, brand_name) DO NOTHING;

-- 验证:每个 client 应有一个 Own Brand
-- SELECT c.name,
--        (SELECT COUNT(*) FROM geo_client_brands b
--          WHERE b.client_id = c.id AND b.is_shadow = false) AS own_count
--   FROM geo_clients c;
-- 期望:每行 own_count = 1


-- ------------------------------------------------------------
-- 2. Migrate geo_client_topics.products TEXT[] → geo_client_topic_products
-- ------------------------------------------------------------
INSERT INTO geo_client_topic_products
    (topic_id, client_id, product_name, match_variants, product_role)
SELECT
    t.id AS topic_id,
    t.client_id,
    unnest(t.products) AS product_name,
    ARRAY[unnest(t.products)] AS match_variants,
    'own'  -- 历史数据全部标 own(客户自家产品)
  FROM geo_client_topics t
 WHERE t.products IS NOT NULL AND array_length(t.products, 1) > 0;

-- 验证:所有原 products 数组都已迁移
-- SELECT t.topic_name,
--        COALESCE(array_length(t.products, 1), 0) AS orig_count,
--        (SELECT COUNT(*) FROM geo_client_topic_products p
--          WHERE p.topic_id = t.id) AS migrated_count
--   FROM geo_client_topics t
--  WHERE t.products IS NOT NULL;
-- 期望:每行 orig_count = migrated_count


-- ------------------------------------------------------------
-- 3. geo_client_domains.brand_id 回填到该 client 的 Own Brand
-- ------------------------------------------------------------
UPDATE geo_client_domains d
   SET brand_id = (
       SELECT id FROM geo_client_brands b
        WHERE b.client_id = d.client_id AND b.is_shadow = false
        LIMIT 1
   )
 WHERE d.brand_id IS NULL AND d.peer_id IS NULL;

-- 验证:全部 domain 记录都有 brand_id 或 peer_id
-- SELECT COUNT(*) FROM geo_client_domains
--  WHERE brand_id IS NULL AND peer_id IS NULL;
-- 期望:0(除非有特殊遗留)


COMMIT;

-- ============================================================
-- 综合验证
-- ============================================================
-- SELECT 'geo_client_brands', COUNT(*) FROM geo_client_brands
-- UNION ALL SELECT 'geo_client_topic_products', COUNT(*) FROM geo_client_topic_products
-- UNION ALL SELECT 'domains_with_brand', COUNT(*) FROM geo_client_domains WHERE brand_id IS NOT NULL
-- UNION ALL SELECT 'domains_with_peer', COUNT(*) FROM geo_client_domains WHERE peer_id IS NOT NULL;
