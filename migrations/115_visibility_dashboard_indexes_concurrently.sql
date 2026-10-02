-- 115_visibility_dashboard_indexes_concurrently.sql
-- Purpose: speed up Visibility dashboard queries that filter by client and
-- Shanghai-local dashboard date.
--
-- IMPORTANT:
-- - Execute this file outside an explicit transaction.
-- - CREATE INDEX CONCURRENTLY avoids blocking normal reads/writes, but it can
--   still consume CPU/IO while the index is being built.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_bm_client_shdate_prompt_role_brand
    ON geo_brand_mentions (
        client_id,
        ((executed_at AT TIME ZONE 'Asia/Shanghai')::date),
        client_prompt_id,
        brand_role,
        brand_name
    );

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_bm_client_result_role_prompt
    ON geo_brand_mentions (
        client_id,
        result_id,
        brand_role,
        client_prompt_id
    );

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_results_client_shdate_prompt_result
    ON geo_results (
        client_id,
        ((ingested_at AT TIME ZONE 'Asia/Shanghai')::date),
        client_prompt_id,
        result_id
    );

-- Rollback, also outside an explicit transaction:
-- DROP INDEX CONCURRENTLY IF EXISTS idx_geo_bm_client_shdate_prompt_role_brand;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_geo_bm_client_result_role_prompt;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_geo_results_client_shdate_prompt_result;
