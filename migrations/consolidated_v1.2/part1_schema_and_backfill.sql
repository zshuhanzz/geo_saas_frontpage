-- ========================================================================
-- v1.2 Dual-Mode Tracking — Part 1: Schema Setup + Backfill + Legacy Cleanup
-- ========================================================================
-- Concat of migrations 040..045. Run during maintenance window only.
-- Each embedded migration preserves its own BEGIN/COMMIT so one can be
-- rerun independently from its source file if needed.
-- 
-- ⚠️ Destructive operations included:
--   * 042: RENAME geo_company_mentions → geo_brand_mentions
--   * 044: DROP deprecated columns on multiple tables
--   * 045: TRUNCATE agent_sessions (explicit user approval required)
-- ========================================================================

-- ──── 040_v12_new_tables.sql ────
-- ============================================================
-- Migration 040: Dual-Mode Tracking v1.2 - 新建 7 张表 + 1 trigger
-- ============================================================
-- Spec: docs/superpowers/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md §4
--
-- 执行前置:
--   - Cloud SQL 快照已备份
--   - Analyzer / Collector Cloud Run Job 已暂停
--
-- 此 migration 只 CREATE,不改现有表。可安全执行。
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. geo_client_brands(Own + Shadow 统一管理)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_client_brands (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id   UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    brand_name  TEXT NOT NULL,
    aliases     TEXT[] NOT NULL DEFAULT '{}',
    is_shadow   BOOLEAN NOT NULL DEFAULT false,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, brand_name)
);

CREATE INDEX IF NOT EXISTS idx_geo_client_brands_client
    ON geo_client_brands(client_id) WHERE is_active = true;

COMMENT ON TABLE geo_client_brands IS 'Own + Shadow Brands 统一管理(v1.2)';
COMMENT ON COLUMN geo_client_brands.is_shadow IS 'true=经销渠道品牌(Shadow),false=自营品牌(Own)';


-- ------------------------------------------------------------
-- 2. geo_client_topic_products(Products 结构化,替代 geo_client_topics.products TEXT[])
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_client_topic_products (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic_id         UUID NOT NULL REFERENCES geo_client_topics(id) ON DELETE CASCADE,
    client_id        UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_name     TEXT NOT NULL,
    match_variants   TEXT[] NOT NULL DEFAULT '{}',
    product_role     TEXT NOT NULL DEFAULT 'own'
                     CHECK (product_role IN ('own','shadow_brand_product','peer')),
    shadow_sub_role  TEXT
                     CHECK (shadow_sub_role IS NULL
                            OR shadow_sub_role IN ('native','resale')),
    owner_brand_id   UUID REFERENCES geo_client_brands(id) ON DELETE SET NULL,
    owner_peer_id    UUID REFERENCES geo_client_peers(id)  ON DELETE SET NULL,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT product_role_owner_consistency CHECK (
        (product_role = 'own'
            AND owner_brand_id IS NULL
            AND owner_peer_id IS NULL
            AND shadow_sub_role IS NULL)
     OR (product_role = 'shadow_brand_product'
            AND owner_brand_id IS NOT NULL)
     OR (product_role = 'peer'
            AND owner_peer_id IS NOT NULL
            AND owner_brand_id IS NULL
            AND shadow_sub_role IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_geo_ctp_topic
    ON geo_client_topic_products(topic_id) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_geo_ctp_client
    ON geo_client_topic_products(client_id) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_geo_ctp_role
    ON geo_client_topic_products(client_id, product_role) WHERE is_active = true;

COMMENT ON TABLE geo_client_topic_products IS 'Products 结构化表(v1.2),从 geo_client_topics.products TEXT[] 迁出';
COMMENT ON COLUMN geo_client_topic_products.product_role IS 'own=自家产品 / shadow_brand_product=经销渠道上的产品 / peer=独立 Peer 渠道上的产品';
COMMENT ON COLUMN geo_client_topic_products.shadow_sub_role IS 'NULL=不确定 / native=渠道自家品牌线 / resale=渠道代理他人';


-- ------------------------------------------------------------
-- 3. geo_product_mentions(Product 级 mention 产出)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_product_mentions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_prompt_id    UUID NOT NULL,
    task_id             UUID,
    result_id           INTEGER NOT NULL,
    client_id           UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    product_id          UUID REFERENCES geo_client_topic_products(id) ON DELETE SET NULL,
    product_name        TEXT NOT NULL,
    product_role        TEXT NOT NULL
                        CHECK (product_role IN ('own','shadow_brand_product','peer')),
    shadow_sub_role     TEXT
                        CHECK (shadow_sub_role IS NULL OR shadow_sub_role IN ('native','resale')),
    owner_brand_id      UUID,
    owner_brand_name    TEXT,
    owner_peer_id       UUID,
    owner_peer_name     TEXT,
    mention_position    INTEGER,
    executed_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_pm_client ON geo_product_mentions(client_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_geo_pm_result ON geo_product_mentions(result_id, client_id);
CREATE INDEX IF NOT EXISTS idx_geo_pm_role ON geo_product_mentions(client_id, product_role);
CREATE INDEX IF NOT EXISTS idx_geo_pm_sub_role
    ON geo_product_mentions(client_id, shadow_sub_role) WHERE shadow_sub_role IS NOT NULL;

COMMENT ON TABLE geo_product_mentions IS 'Product 级 mention 记录(v1.2),denormalized owner 字段供 Dashboard 聚合';


-- ------------------------------------------------------------
-- 4. geo_product_sales_channels(Product↔Brand 业务关系)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_product_sales_channels (
    product_id  UUID NOT NULL REFERENCES geo_client_topic_products(id) ON DELETE CASCADE,
    brand_id    UUID NOT NULL REFERENCES geo_client_brands(id) ON DELETE CASCADE,
    client_id   UUID NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (product_id, brand_id)
);

CREATE INDEX IF NOT EXISTS idx_geo_psc_client ON geo_product_sales_channels(client_id);
CREATE INDEX IF NOT EXISTS idx_geo_psc_brand ON geo_product_sales_channels(brand_id);

COMMENT ON TABLE geo_product_sales_channels IS 'Product↔Brand 销售渠道声明(v1.2);独立于 URL 证据';


-- ------------------------------------------------------------
-- 5. geo_product_tracked_urls(Product 精确 URL 绑定)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_product_tracked_urls (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id   UUID NOT NULL,
    product_id  UUID NOT NULL REFERENCES geo_client_topic_products(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    url_scope   TEXT NOT NULL DEFAULT 'exact'
                CHECK (url_scope IN ('exact','path-prefix')),
    brand_id    UUID REFERENCES geo_client_brands(id),
    peer_id     UUID REFERENCES geo_client_peers(id),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, url, product_id),
    CONSTRAINT tracked_url_owner_exclusive CHECK (
        NOT (brand_id IS NOT NULL AND peer_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_geo_ptu_product ON geo_product_tracked_urls(product_id);
CREATE INDEX IF NOT EXISTS idx_geo_ptu_client_url ON geo_product_tracked_urls(client_id, url);

COMMENT ON TABLE geo_product_tracked_urls IS 'Product 精确/前缀 URL 绑定(v1.2),Citation Parser 的 Stage 1 查询目标';


-- ------------------------------------------------------------
-- 6. geo_settings_candidates(AI 发现的配置候选)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_settings_candidates (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id        UUID NOT NULL,
    candidate_string TEXT NOT NULL,
    candidate_type   TEXT NOT NULL CHECK (candidate_type IN (
        'brand', 'shadow_brand', 'peer',
        'own_product', 'shadow_product', 'peer_product',
        'tracked_url'
    )),
    suggested_target_topic_id  UUID,
    suggested_target_brand_id  UUID,
    suggested_target_peer_id   UUID,
    source TEXT NOT NULL CHECK (source IN (
        'n_gram', 'llm_batch', 'auto_discovery'
    )),
    frequency   INT DEFAULT 1,
    first_seen  TIMESTAMPTZ DEFAULT NOW(),
    last_seen   TIMESTAMPTZ DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','accepted','rejected','ignored')),
    sample_response_ids INT[],
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, candidate_string, candidate_type)
);

CREATE INDEX IF NOT EXISTS idx_geo_sc_client_status
    ON geo_settings_candidates(client_id, status);
CREATE INDEX IF NOT EXISTS idx_geo_sc_type
    ON geo_settings_candidates(client_id, candidate_type)
    WHERE status = 'pending';

COMMENT ON TABLE geo_settings_candidates IS 'AI 发现的配置候选(Brand/Product/URL/Peer/Topic)供人工 review 挑入';


-- ------------------------------------------------------------
-- 7. URL 归属校验 trigger(防错配)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION validate_tracked_url_ownership()
RETURNS TRIGGER AS $$
DECLARE
    host_from_url            TEXT;
    owner_brand_from_domains UUID;
    owner_peer_from_domains  UUID;
BEGIN
    -- 规范化提取 host(去 scheme / www)
    host_from_url := regexp_replace(
        regexp_replace(NEW.url, '^https?://', ''),
        '/.*$', ''
    );
    host_from_url := regexp_replace(host_from_url, '^www\.', '');
    host_from_url := LOWER(host_from_url);

    -- 查 geo_client_domains 该 host 归谁
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

DROP TRIGGER IF EXISTS trg_validate_tracked_url_ownership ON geo_product_tracked_urls;
CREATE TRIGGER trg_validate_tracked_url_ownership
    BEFORE INSERT OR UPDATE ON geo_product_tracked_urls
    FOR EACH ROW EXECUTE FUNCTION validate_tracked_url_ownership();


COMMIT;

-- ============================================================
-- 验证(执行后手动跑)
-- ============================================================
-- SELECT table_name FROM information_schema.tables
--  WHERE table_name IN ('geo_client_brands','geo_client_topic_products',
--    'geo_product_mentions','geo_product_sales_channels',
--    'geo_product_tracked_urls','geo_settings_candidates');
-- 期望:7 行(含 trigger function 不在此查询范围)

-- SELECT trigger_name FROM information_schema.triggers
--  WHERE trigger_name='trg_validate_tracked_url_ownership';
-- 期望:1 行

-- ──── 041_v12_extend_existing.sql ────
-- ============================================================
-- Migration 041: Dual-Mode Tracking v1.2 - 扩展现有表
-- ============================================================
-- Spec §4.2.7 / §4.2.8 / §4.2.10
--
-- 扩展:geo_client_domains / geo_citations / geo_clients
-- 前置:040 已执行(新表存在,因为 041 会 FK 引用 geo_client_brands / geo_client_peers)
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. geo_client_domains 扩展(加 scope + brand_id / peer_id FK)
-- ------------------------------------------------------------
ALTER TABLE geo_client_domains
    ADD COLUMN IF NOT EXISTS domain_scope TEXT NOT NULL DEFAULT 'whole'
        CHECK (domain_scope IN ('whole','path-prefix')),
    ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES geo_client_brands(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS peer_id  UUID REFERENCES geo_client_peers(id)  ON DELETE CASCADE;

-- brand_id 和 peer_id 至多一个非空
ALTER TABLE geo_client_domains
    DROP CONSTRAINT IF EXISTS domain_owner_exclusive;
ALTER TABLE geo_client_domains
    ADD CONSTRAINT domain_owner_exclusive CHECK (
        NOT (brand_id IS NOT NULL AND peer_id IS NOT NULL)
    );

COMMENT ON COLUMN geo_client_domains.domain_scope IS 'whole=整域 / path-prefix=路径前缀';
COMMENT ON COLUMN geo_client_domains.brand_id IS 'Brand 归属(Own 或 Shadow),和 peer_id 互斥';
COMMENT ON COLUMN geo_client_domains.peer_id IS 'Peer 归属,和 brand_id 互斥';


-- ------------------------------------------------------------
-- 2. geo_citations 扩展(citation_role + matched_*_id)
-- ------------------------------------------------------------
ALTER TABLE geo_citations
    ADD COLUMN IF NOT EXISTS citation_role TEXT CHECK (citation_role IN (
        'own_domain', 'own_product',
        'shadow_product_native', 'shadow_product_resale',
        'shadow_product', 'shadow_other',
        'peer_product', 'peer_channel',
        'earned', 'social', 'agency', 'other'
    )),
    ADD COLUMN IF NOT EXISTS matched_brand_id   UUID REFERENCES geo_client_brands(id),
    ADD COLUMN IF NOT EXISTS matched_product_id UUID REFERENCES geo_client_topic_products(id),
    ADD COLUMN IF NOT EXISTS matched_peer_id    UUID REFERENCES geo_client_peers(id);

CREATE INDEX IF NOT EXISTS idx_geo_citations_role
    ON geo_citations(client_id, citation_role) WHERE citation_role IS NOT NULL;

COMMENT ON COLUMN geo_citations.citation_role IS '本条 citation 的归因类型(v1.2)';


-- ------------------------------------------------------------
-- 3. geo_clients 扩展(Onboarding Wizard 状态)
-- ------------------------------------------------------------
ALTER TABLE geo_clients
    ADD COLUMN IF NOT EXISTS onboarding_wizard_completed BOOLEAN NOT NULL DEFAULT false;

-- 存量 client 视为已完成(避免对 Roborock 误弹)
UPDATE geo_clients
   SET onboarding_wizard_completed = true
 WHERE created_at < NOW();

COMMENT ON COLUMN geo_clients.onboarding_wizard_completed IS 'Onboarding Wizard 是否已完成(v1.2)';


COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- \d geo_client_domains
--   期望含:domain_scope / brand_id / peer_id
-- \d geo_citations
--   期望含:citation_role / matched_brand_id / matched_product_id / matched_peer_id
-- \d geo_clients
--   期望含:onboarding_wizard_completed

-- SELECT COUNT(*) FROM geo_clients WHERE onboarding_wizard_completed = true;
--   期望:= geo_clients 总行数

-- ──── 042_v12_rename_mentions.sql ────
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

-- ──── 043_v12_data_migration.sql ────
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

-- ──── 044_v12_drop_legacy.sql ────
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

-- ──── 045_v12_truncate_agent_state.sql ────
-- ============================================================
-- Migration 045: Dual-Mode Tracking v1.2 - 清空 Agent 运行态
-- ============================================================
-- Spec §11.3
--
-- 背景:产品无线上用户,agent 运行态(checkpoints / messages / memories /
-- agent_tasks)无保留价值。且历史内容含旧 schema 的 SQL 文本,
-- 若不清空,agent thread resume 时可能执行旧 SQL 报错。
--
-- ⚠️ 执行此文件前确认:Agent Cloud Run service 已停。
-- ============================================================

BEGIN;

TRUNCATE TABLE checkpoints;                       -- LangGraph state snapshots
TRUNCATE TABLE agent_messages;                     -- 聊天历史
TRUNCATE TABLE agent_memories;                     -- 跨会话记忆
TRUNCATE TABLE geo_agent_tasks CASCADE;            -- 历史 agent 任务产出(CASCADE 到 geo_content_assets 等引用表)

COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- SELECT 'checkpoints', COUNT(*) FROM checkpoints
-- UNION ALL SELECT 'agent_messages', COUNT(*) FROM agent_messages
-- UNION ALL SELECT 'agent_memories', COUNT(*) FROM agent_memories
-- UNION ALL SELECT 'geo_agent_tasks', COUNT(*) FROM geo_agent_tasks;
-- 期望:全部为 0

