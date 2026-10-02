-- 119_dashboard_hot_path_indexes_concurrently.sql
-- Purpose: add indexes for dashboard hot paths that filter by Shanghai-local
-- dates and then look up citations by URL/domain or published URL metadata.
--
-- IMPORTANT:
-- - Execute this file outside an explicit transaction.
-- - CREATE INDEX CONCURRENTLY avoids blocking normal writes, but it still
--   consumes CPU/IO while building. Run during a quiet window.
--
-- These complement migration 114. Migration 114 is optimized for:
--   client_id + local date + prompt filters + source_url/source_domain
-- This file adds the inverse order needed by published URL tracking:
--   client_id + source_url + local date + prompt filters

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_citations_client_source_url_shdate_prompt
    ON geo_citations (
        client_id,
        source_url,
        ((executed_at AT TIME ZONE 'Asia/Shanghai')::date),
        client_prompt_id
    )
    WHERE source_url IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_citations_client_source_domain_shdate_prompt
    ON geo_citations (
        client_id,
        source_domain,
        ((executed_at AT TIME ZONE 'Asia/Shanghai')::date),
        client_prompt_id
    )
    WHERE source_domain IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_published_urls_client_active_status_published_at
    ON geo_published_urls (
        client_id,
        is_active,
        publish_status,
        published_at DESC,
        updated_at DESC
    )
    INCLUDE (id, title, published_url, normalized_url, channel);

-- Rollback, also outside an explicit transaction:
-- DROP INDEX CONCURRENTLY IF EXISTS idx_geo_citations_client_source_url_shdate_prompt;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_geo_citations_client_source_domain_shdate_prompt;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_geo_published_urls_client_active_status_published_at;
