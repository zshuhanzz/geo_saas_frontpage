-- ============================================================
-- Migration 125: Frozen Static Report List Blobs
-- ============================================================
-- Purpose:
--   - Persist one immutable JSONB payload per report/list type.
--   - Keep static-report sorting frozen without row-per-item write/index load.
--   - Let Cloud Run filter, sort, and paginate the point-read payload in memory.
--
-- Execution:
--   - Run manually in Cloud SQL. Application code never executes this DDL.
--   - This supersedes the unexecuted row-per-item draft of Migration 125.
-- ============================================================

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_static_reports_id_client_unique
    ON geo_static_reports (id, client_id);

CREATE TABLE IF NOT EXISTS geo_static_report_lists (
    report_id       UUID NOT NULL,
    client_id       UUID NOT NULL,
    list_type       TEXT NOT NULL,
    list_version    TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    rows_payload    JSONB NOT NULL,
    materialized_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT geo_static_report_lists_pkey PRIMARY KEY (
        report_id,
        client_id,
        list_type
    ),
    CONSTRAINT geo_static_report_lists_report_client_fkey FOREIGN KEY (
        report_id,
        client_id
    ) REFERENCES geo_static_reports (id, client_id) ON DELETE CASCADE,
    CONSTRAINT geo_static_report_lists_list_type_not_blank CHECK (
        btrim(list_type) <> ''
    ),
    CONSTRAINT geo_static_report_lists_list_version_not_blank CHECK (
        btrim(list_version) <> ''
    ),
    CONSTRAINT geo_static_report_lists_payload_array CHECK (
        jsonb_typeof(rows_payload) = 'array'
    ),
    CONSTRAINT geo_static_report_lists_row_count_matches CHECK (
        row_count >= 0
        AND row_count <= 25000
        AND row_count = jsonb_array_length(rows_payload)
    )
);

COMMENT ON TABLE geo_static_report_lists IS
    'One frozen JSONB list payload per static report and list type; application memory owns filtering, sorting, and pagination.';
COMMENT ON COLUMN geo_static_report_lists.rows_payload IS
    'Canonical complete list rows in deterministic default order.';
COMMENT ON COLUMN geo_static_report_lists.list_version IS
    'Snapshot/list contract version required by the application reader.';

COMMIT;

-- ============================================================
-- Manual read-only verification after execution
-- ============================================================
-- The result must contain zero rows.
-- WITH expected(column_name, data_type, is_nullable) AS (
--     VALUES
--         ('report_id', 'uuid', 'NO'),
--         ('client_id', 'uuid', 'NO'),
--         ('list_type', 'text', 'NO'),
--         ('list_version', 'text', 'NO'),
--         ('row_count', 'integer', 'NO'),
--         ('rows_payload', 'jsonb', 'NO'),
--         ('materialized_at', 'timestamp with time zone', 'NO')
-- ), actual AS (
--     SELECT column_name, data_type, is_nullable
--     FROM information_schema.columns
--     WHERE table_schema = 'public'
--       AND table_name = 'geo_static_report_lists'
-- )
-- (SELECT 'missing_or_mismatch' AS issue, * FROM expected
--  EXCEPT SELECT 'missing_or_mismatch', * FROM actual)
-- UNION ALL
-- (SELECT 'unexpected_or_mismatch' AS issue, * FROM actual
--  EXCEPT SELECT 'unexpected_or_mismatch', * FROM expected)
-- ORDER BY column_name, issue;
--
-- The result must be one primary key in exactly this order.
-- SELECT pg_get_constraintdef(oid, false)
-- FROM pg_constraint
-- WHERE conrelid = 'geo_static_report_lists'::regclass
--   AND conname = 'geo_static_report_lists_pkey';
-- Expected:
-- PRIMARY KEY (report_id, client_id, list_type)
--
-- These definitions must include the composite cascading foreign key and all
-- payload integrity checks, including the 25,000-row ceiling.
-- SELECT conname, pg_get_constraintdef(oid, false)
-- FROM pg_constraint
-- WHERE conrelid = 'geo_static_report_lists'::regclass
--   AND conname IN (
--       'geo_static_report_lists_report_client_fkey',
--       'geo_static_report_lists_payload_array',
--       'geo_static_report_lists_row_count_matches'
--   )
-- ORDER BY conname;
--
-- The result must be zero. This includes completed v5 reports with no child
-- rows, and validates every exact registered type at the current version.
-- WITH expected_types(list_type) AS (
--     VALUES
--         ('visibility.brand_visibility'),
--         ('visibility.brand_sov'),
--         ('visibility.brand_position'),
--         ('visibility.topic'),
--         ('visibility.product'),
--         ('visibility.topic_prompt'),
--         ('visibility.product_prompt'),
--         ('visibility.topic_brand'),
--         ('visibility.product_brand'),
--         ('visibility.topic_prompt_brand'),
--         ('visibility.product_prompt_brand'),
--         ('citation.domain'),
--         ('citation.page'),
--         ('citation.category'),
--         ('sentiment.theme'),
--         ('prompt.ranking'),
--         ('topic.ranking')
-- ), completed_v5 AS (
--     SELECT id, client_id
--     FROM geo_static_reports
--     WHERE status = 'COMPLETED'
--       AND snapshot_version = 'static-report-v5'
-- )
-- SELECT r.id AS report_id, r.client_id, COUNT(l.list_type) AS valid_list_count
-- FROM completed_v5 r
-- CROSS JOIN expected_types e
-- LEFT JOIN geo_static_report_lists l
--   ON l.report_id = r.id
--  AND l.client_id = r.client_id
--  AND l.list_type = e.list_type
--  AND l.list_version = 'static-report-v5'
-- GROUP BY r.id, r.client_id
-- HAVING COUNT(l.list_type) <> 17;
--
-- The result must also be zero; it detects extra/unknown types and stale list
-- versions even when all 17 expected rows are present. Citation Page/Domain
-- may additionally persist compact global-sort position indexes in this same
-- table; these are derived from the canonical frozen rows and do not duplicate
-- the full payload.
-- WITH expected_types(list_type) AS (
--     VALUES
--         ('visibility.brand_visibility'), ('visibility.brand_sov'),
--         ('visibility.brand_position'), ('visibility.topic'),
--         ('visibility.product'), ('visibility.topic_prompt'),
--         ('visibility.product_prompt'), ('visibility.topic_brand'),
--         ('visibility.product_brand'), ('visibility.topic_prompt_brand'),
--         ('visibility.product_prompt_brand'), ('citation.domain'),
--         ('citation.page'), ('citation.category'), ('sentiment.theme'),
--         ('prompt.ranking'), ('topic.ranking')
-- )
-- SELECT l.report_id, l.client_id, l.list_type, l.list_version
-- FROM geo_static_report_lists l
-- LEFT JOIN expected_types e ON e.list_type = l.list_type
-- WHERE (
--       e.list_type IS NULL
--       AND l.list_type !~ '^citation\.(page|domain)@sort\.(citation_count|share_pct|change_pct)\.(asc|desc)(::[0-9]{6})?$'
--   )
--    OR l.list_version <> 'static-report-v5';
