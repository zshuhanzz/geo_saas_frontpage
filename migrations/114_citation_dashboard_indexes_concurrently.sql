-- 114_citation_dashboard_indexes_concurrently.sql
-- Citation dashboard lookup acceleration for large geo_citations datasets.
--
-- IMPORTANT:
-- This file must be executed outside an explicit transaction.
-- Do not run it through SQL tools that wrap the entire script in a transaction.
--
-- Why CONCURRENTLY:
-- geo_citations receives production writes from the analyzer/ingestion pipeline.
-- Creating these indexes concurrently avoids blocking normal reads/writes while
-- PostgreSQL builds the indexes.
--
-- Why the Asia/Shanghai expression:
-- Current citation dashboard endpoints filter dates with:
--   (c.executed_at AT TIME ZONE 'Asia/Shanghai')::date
-- These expression indexes match the existing query shape without requiring an
-- application query rewrite.
--
-- Rollback, if needed, must also be run outside an explicit transaction:
--   DROP INDEX CONCURRENTLY IF EXISTS idx_geo_citations_client_shdate_prompt_domain;
--   DROP INDEX CONCURRENTLY IF EXISTS idx_geo_citations_client_shdate_prompt_url;
--   DROP INDEX CONCURRENTLY IF EXISTS idx_geo_client_prompts_citation_filters;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_citations_client_shdate_prompt_domain
    ON geo_citations (
        client_id,
        ((executed_at AT TIME ZONE 'Asia/Shanghai')::date),
        client_prompt_id,
        source_domain
    );

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_citations_client_shdate_prompt_url
    ON geo_citations (
        client_id,
        ((executed_at AT TIME ZONE 'Asia/Shanghai')::date),
        client_prompt_id,
        source_url
    );

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_client_prompts_citation_filters
    ON geo_client_prompts (
        client_id,
        topic_id,
        platform,
        country,
        intent,
        id
    );
