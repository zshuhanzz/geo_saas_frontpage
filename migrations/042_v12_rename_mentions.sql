-- ============================================================
-- Migration 042: Dual-Mode Tracking v1.2 - 重命名 + 升级 geo_company_mentions
-- ============================================================
-- Spec §4.2.3
--
-- geo_company_mentions (10,486 行) → geo_brand_mentions
--   - 字段 company_name → brand_name
--   - 字段 is_own_brand BOOLEAN → brand_role TEXT ENUM('own','shadow','peer')
--
-- 历史数据:is_own_brand=true → 'own',is_own_brand=false → 'peer'
-- (shadow 是 v1.2 后才产生,历史无此类别)
-- ============================================================

BEGIN;

-- Step 1: Rename 表
ALTER TABLE geo_company_mentions RENAME TO geo_brand_mentions;

-- Step 2: Rename 字段 company_name → brand_name
ALTER TABLE geo_brand_mentions RENAME COLUMN company_name TO brand_name;

-- Step 3: 加 brand_role 列(暂可空)
ALTER TABLE geo_brand_mentions
    ADD COLUMN brand_role TEXT
    CHECK (brand_role IN ('own','shadow','peer'));

-- Step 4: 数据迁移
UPDATE geo_brand_mentions
   SET brand_role = CASE
       WHEN is_own_brand = true THEN 'own'
       ELSE 'peer'
   END;

-- Step 5: 收紧为 NOT NULL
ALTER TABLE geo_brand_mentions ALTER COLUMN brand_role SET NOT NULL;

-- Step 6: 删除旧列 is_own_brand
ALTER TABLE geo_brand_mentions DROP COLUMN is_own_brand;

-- Step 7: 索引更新(如有旧索引名含 company_mentions,重建)
DROP INDEX IF EXISTS idx_geo_company_mentions_client;
DROP INDEX IF EXISTS idx_geo_company_mentions_result;

CREATE INDEX IF NOT EXISTS idx_geo_brand_mentions_client
    ON geo_brand_mentions(client_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_geo_brand_mentions_result
    ON geo_brand_mentions(result_id, client_id);
CREATE INDEX IF NOT EXISTS idx_geo_brand_mentions_role
    ON geo_brand_mentions(client_id, brand_role);

COMMENT ON TABLE geo_brand_mentions IS '品牌级 mention(v1.2,从 geo_company_mentions 重命名升级)';
COMMENT ON COLUMN geo_brand_mentions.brand_role IS 'own=自营品牌 / shadow=经销渠道品牌 / peer=独立竞品';


COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- SELECT brand_role, COUNT(*) FROM geo_brand_mentions GROUP BY brand_role;
--   期望:只有 'own' 和 'peer' 两个值(历史无 shadow)
--   期望:两行总和 = 原 geo_company_mentions 的 10,486 行

-- SELECT COUNT(*) FROM geo_brand_mentions;
--   期望:10,486
