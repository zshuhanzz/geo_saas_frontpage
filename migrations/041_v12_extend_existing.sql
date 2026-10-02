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
