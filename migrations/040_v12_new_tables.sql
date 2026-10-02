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
