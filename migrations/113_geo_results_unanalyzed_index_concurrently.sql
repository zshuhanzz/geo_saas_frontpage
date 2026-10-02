-- 113_geo_results_unanalyzed_index_concurrently.sql
-- Analyzer lookup acceleration for large geo_results batches.
--
-- IMPORTANT:
-- This file must be executed outside an explicit transaction.
-- Do not run it through SQL tools that wrap the entire script in a transaction.
--
-- geo_results receives Collector callback/ingestor writes, so the index is
-- created concurrently to avoid blocking production writes while the index is
-- built.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_results_client_batch_unanalyzed
    ON geo_results (client_id, batch_id, result_id)
    WHERE analyzed_at IS NULL;
