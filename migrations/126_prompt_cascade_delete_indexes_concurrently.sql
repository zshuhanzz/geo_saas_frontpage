-- ============================================================
-- Migration 126: Prompt Cascade Delete Indexes (Concurrent)
-- ============================================================
-- Purpose:
--   - Ensure every Prompt-owned fact table can resolve tenant-scoped cascade
--     deletion without sequential scans or long-held Admin pool connections.
--
-- Execution:
--   - Run manually in Cloud SQL during a quiet window.
--   - Execute this file outside an explicit transaction block because
--     concurrent index builds cannot run inside one.
--   - Prefer psql with ON_ERROR_STOP enabled so the run stops on the first
--     failed concurrent build instead of continuing with a partial result.
--   - These names intentionally match migration 063. IF NOT EXISTS only skips
--     a same-name index; it does not repair an invalid or mismatched definition.
--   - Run the read-only preflight below first. If a same-name index is invalid
--     or differs from (client_id, client_prompt_id), review the finding and
--     manually drop only that index with DROP INDEX CONCURRENTLY outside a
--     transaction, then rerun this migration. No automatic DROP is performed.
-- ============================================================

-- Read-only preflight. Existing target names must either be absent or be valid,
-- ready B-tree indexes with exactly the displayed two-key definition and no
-- predicate. Resolve every invalid/mismatched row before running CREATE INDEX.
-- SELECT
--     tbl.relname AS table_name,
--     idx.relname AS index_name,
--     am.amname AS index_method,
--     i.indisvalid,
--     i.indisready,
--     i.indnkeyatts,
--     i.indnatts,
--     i.indpred IS NULL AS has_no_predicate,
--     i.indexprs IS NULL AS has_no_expression,
--     pg_get_indexdef(i.indexrelid) AS index_definition
-- FROM pg_index i
-- JOIN pg_class idx ON idx.oid = i.indexrelid
-- JOIN pg_class tbl ON tbl.oid = i.indrelid
-- JOIN pg_namespace nsp ON nsp.oid = tbl.relnamespace
-- JOIN pg_am am ON am.oid = idx.relam
-- WHERE nsp.nspname = 'public'
--   AND idx.relname IN (
--       'idx_geo_tasks_client_prompt',
--       'idx_geo_results_client_prompt',
--       'idx_geo_citations_client_prompt',
--       'idx_geo_brand_mentions_client_prompt',
--       'idx_geo_product_mentions_client_prompt',
--       'idx_geo_sentiment_results_client_prompt',
--       'idx_geo_sentiment_themes_client_prompt'
--   )
-- ORDER BY tbl.relname, idx.relname;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_tasks_client_prompt
    ON geo_tasks (client_id, client_prompt_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_results_client_prompt
    ON geo_results (client_id, client_prompt_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_citations_client_prompt
    ON geo_citations (client_id, client_prompt_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_brand_mentions_client_prompt
    ON geo_brand_mentions (client_id, client_prompt_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_product_mentions_client_prompt
    ON geo_product_mentions (client_id, client_prompt_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_sentiment_results_client_prompt
    ON geo_sentiment_results (client_id, client_prompt_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_geo_sentiment_themes_client_prompt
    ON geo_sentiment_themes (client_id, client_prompt_id);

-- ============================================================
-- Manual verification after execution (read-only)
-- ============================================================
-- Exact seven-table contract. Both difference sets must be empty and the
-- summary must report expected_count=7, actual_count=7, contract_rows=7.
-- WITH expected(table_name, index_name, key_columns) AS (
--     VALUES
--         ('geo_tasks', 'idx_geo_tasks_client_prompt', ARRAY['client_id', 'client_prompt_id']),
--         ('geo_results', 'idx_geo_results_client_prompt', ARRAY['client_id', 'client_prompt_id']),
--         ('geo_citations', 'idx_geo_citations_client_prompt', ARRAY['client_id', 'client_prompt_id']),
--         ('geo_brand_mentions', 'idx_geo_brand_mentions_client_prompt', ARRAY['client_id', 'client_prompt_id']),
--         ('geo_product_mentions', 'idx_geo_product_mentions_client_prompt', ARRAY['client_id', 'client_prompt_id']),
--         ('geo_sentiment_results', 'idx_geo_sentiment_results_client_prompt', ARRAY['client_id', 'client_prompt_id']),
--         ('geo_sentiment_themes', 'idx_geo_sentiment_themes_client_prompt', ARRAY['client_id', 'client_prompt_id'])
-- ), actual AS (
--     SELECT
--         tbl.relname AS table_name,
--         idx.relname AS index_name,
--         ARRAY(SELECT pg_get_indexdef(i.indexrelid, pos, TRUE)
--               FROM generate_series(1, i.indnkeyatts) AS pos ORDER BY pos)::TEXT[] AS key_columns
--     FROM pg_index i
--     JOIN pg_class idx ON idx.oid = i.indexrelid
--     JOIN pg_class tbl ON tbl.oid = i.indrelid
--     JOIN pg_namespace nsp ON nsp.oid = tbl.relnamespace
--     JOIN pg_am am ON am.oid = idx.relam
--     WHERE nsp.nspname = 'public'
--       AND idx.relname IN (
--           'idx_geo_tasks_client_prompt',
--           'idx_geo_results_client_prompt',
--           'idx_geo_citations_client_prompt',
--           'idx_geo_brand_mentions_client_prompt',
--           'idx_geo_product_mentions_client_prompt',
--           'idx_geo_sentiment_results_client_prompt',
--           'idx_geo_sentiment_themes_client_prompt'
--       )
--       AND am.amname = 'btree'
--       AND i.indisvalid AND i.indisready
--       AND NOT i.indisunique
--       AND i.indnkeyatts = 2
--       AND i.indnatts = 2
--       AND i.indpred IS NULL
--       AND i.indexprs IS NULL
-- ), differences AS (
--     (SELECT 'missing_or_mismatch' AS issue, * FROM expected
--      EXCEPT SELECT 'missing_or_mismatch', * FROM actual)
--     UNION ALL
--     (SELECT 'unexpected_or_mismatch' AS issue, * FROM actual
--      EXCEPT SELECT 'unexpected_or_mismatch', * FROM expected)
-- )
-- SELECT * FROM differences ORDER BY table_name, index_name, issue;
--
-- WITH target_indexes AS (
--     SELECT i.*
--     FROM pg_index i
--     JOIN pg_class idx ON idx.oid = i.indexrelid
--     JOIN pg_namespace nsp ON nsp.oid = idx.relnamespace
--     WHERE nsp.nspname = 'public'
--       AND idx.relname IN (
--           'idx_geo_tasks_client_prompt',
--           'idx_geo_results_client_prompt',
--           'idx_geo_citations_client_prompt',
--           'idx_geo_brand_mentions_client_prompt',
--           'idx_geo_product_mentions_client_prompt',
--           'idx_geo_sentiment_results_client_prompt',
--           'idx_geo_sentiment_themes_client_prompt'
--       )
-- )
-- SELECT
--     7 AS expected_count,
--     COUNT(*) AS actual_count,
--     COUNT(*) FILTER (
--         WHERE indisvalid AND indisready AND NOT indisunique
--           AND indnkeyatts = 2 AND indnatts = 2
--           AND indpred IS NULL AND indexprs IS NULL
--     ) AS contract_rows
-- FROM target_indexes;
