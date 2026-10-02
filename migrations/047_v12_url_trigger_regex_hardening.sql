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
