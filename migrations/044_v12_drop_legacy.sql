-- ============================================================
-- Migration 044: Dual-Mode Tracking v1.2 - 删除旧字段
-- ============================================================
-- Spec §4.3
--
-- ⚠️ 执行前必须:
--   - 043 数据迁移已验证(geo_client_topic_products 已装载完整)
--   - 042 rename 已验证(geo_brand_mentions 所有行已有 brand_role)
-- ⚠️ 此 migration 不可逆:删列数据无法恢复!
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. 删除 geo_client_peers.is_own_brand
--    (全库 0 个 true,纯遗留列)
-- ------------------------------------------------------------
ALTER TABLE geo_client_peers DROP COLUMN IF EXISTS is_own_brand;


-- ------------------------------------------------------------
-- 2. 删除 geo_client_topics.products TEXT[]
--    (数据已迁移到 geo_client_topic_products)
-- ------------------------------------------------------------
ALTER TABLE geo_client_topics DROP COLUMN IF EXISTS products;


COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='geo_client_peers' AND column_name='is_own_brand';
-- 期望:0 行

-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='geo_client_topics' AND column_name='products';
-- 期望:0 行
