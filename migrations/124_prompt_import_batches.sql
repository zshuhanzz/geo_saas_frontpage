-- ============================================================
-- Migration 124: Prompt CSV Import Batch Audit Records
-- ============================================================
-- Purpose:
--   - Persist the tenant-scoped audit record for a committed Prompt CSV import.
--   - Retain only hashes, counts, and created Prompt IDs needed for safe Undo.
--   - Never persist raw Prompt content in this generic audit table.
--
-- Execution:
--   - Run manually in Cloud SQL.
--   - This migration creates schema objects only.
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS geo_prompt_import_batches (
    id                           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id                    UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    created_by_user_id           UUID REFERENCES geo_users(id) ON DELETE SET NULL,
    source_filename              TEXT NOT NULL,
    raw_csv_sha256               CHAR(64) NOT NULL,
    normalized_manifest_sha256   CHAR(64) NOT NULL,
    input_row_count              INTEGER NOT NULL,
    expanded_variant_count       INTEGER NOT NULL,
    create_count                 INTEGER NOT NULL,
    skip_count                   INTEGER NOT NULL,
    conflict_count               INTEGER NOT NULL,
    invalid_count                INTEGER NOT NULL,
    created_prompt_ids           UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
    status                       TEXT NOT NULL DEFAULT 'COMMITTED',
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reverted_at                  TIMESTAMPTZ,
    reverted_by_user_id          UUID REFERENCES geo_users(id) ON DELETE SET NULL,

    CONSTRAINT geo_prompt_import_batches_source_filename_not_blank CHECK (
        btrim(source_filename) <> ''
    ),
    CONSTRAINT geo_prompt_import_batches_raw_hash_check CHECK (
        raw_csv_sha256 ~ '^[0-9a-fA-F]{64}$'
    ),
    CONSTRAINT geo_prompt_import_batches_manifest_hash_check CHECK (
        normalized_manifest_sha256 ~ '^[0-9a-fA-F]{64}$'
    ),
    CONSTRAINT geo_prompt_import_batches_input_row_count_non_negative CHECK (
        input_row_count >= 0
    ),
    CONSTRAINT geo_prompt_import_batches_expanded_variant_count_non_negative CHECK (
        expanded_variant_count >= 0
    ),
    CONSTRAINT geo_prompt_import_batches_create_count_non_negative CHECK (
        create_count >= 0
    ),
    CONSTRAINT geo_prompt_import_batches_skip_count_non_negative CHECK (
        skip_count >= 0
    ),
    CONSTRAINT geo_prompt_import_batches_conflict_count_non_negative CHECK (
        conflict_count >= 0
    ),
    CONSTRAINT geo_prompt_import_batches_invalid_count_non_negative CHECK (
        invalid_count >= 0
    ),
    CONSTRAINT geo_prompt_import_batches_created_ids_match_create_count CHECK (
        cardinality(created_prompt_ids) = create_count
    ),
    CONSTRAINT geo_prompt_import_batches_status_check CHECK (
        status IN ('COMMITTED', 'REVERTING', 'REVERTED')
    ),
    CONSTRAINT geo_prompt_import_batches_reverted_state_check CHECK (
        (status = 'REVERTED' AND reverted_at IS NOT NULL)
        OR (status IN ('COMMITTED', 'REVERTING') AND reverted_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_geo_prompt_import_batches_client_created
    ON geo_prompt_import_batches (client_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_geo_prompt_import_batches_client_status_created
    ON geo_prompt_import_batches (client_id, status, created_at DESC);

COMMENT ON TABLE geo_prompt_import_batches IS
    'Tenant-scoped Prompt CSV import audit records and exact created Prompt IDs for safe Undo.';
COMMENT ON COLUMN geo_prompt_import_batches.raw_csv_sha256 IS
    'SHA-256 of the uploaded CSV bytes; raw Prompt content is not stored here.';
COMMENT ON COLUMN geo_prompt_import_batches.normalized_manifest_sha256 IS
    'SHA-256 of the canonical expanded Prompt variant manifest used for stale-preview detection.';
COMMENT ON COLUMN geo_prompt_import_batches.created_prompt_ids IS
    'Exact Prompt UUIDs inserted by this batch and therefore the only Prompt targets eligible for Undo.';

COMMIT;

-- ============================================================
-- Manual verification after execution (read-only)
-- ============================================================
-- Exact columns, types, array element type, CHAR length, nullability, and
-- defaults. The result must contain zero rows.
-- WITH expected(
--     column_name, data_type, udt_name, character_maximum_length,
--     is_nullable, column_default
-- ) AS (
--     VALUES
--         ('id', 'uuid', 'uuid', NULL::INTEGER, 'NO', 'uuid_generate_v4()'),
--         ('client_id', 'uuid', 'uuid', NULL, 'NO', NULL),
--         ('created_by_user_id', 'uuid', 'uuid', NULL, 'YES', NULL),
--         ('source_filename', 'text', 'text', NULL, 'NO', NULL),
--         ('raw_csv_sha256', 'character', 'bpchar', 64, 'NO', NULL),
--         ('normalized_manifest_sha256', 'character', 'bpchar', 64, 'NO', NULL),
--         ('input_row_count', 'integer', 'int4', NULL, 'NO', NULL),
--         ('expanded_variant_count', 'integer', 'int4', NULL, 'NO', NULL),
--         ('create_count', 'integer', 'int4', NULL, 'NO', NULL),
--         ('skip_count', 'integer', 'int4', NULL, 'NO', NULL),
--         ('conflict_count', 'integer', 'int4', NULL, 'NO', NULL),
--         ('invalid_count', 'integer', 'int4', NULL, 'NO', NULL),
--         ('created_prompt_ids', 'ARRAY', '_uuid', NULL, 'NO', 'ARRAY[]::uuid[]'),
--         ('status', 'text', 'text', NULL, 'NO', '''COMMITTED''::text'),
--         ('created_at', 'timestamp with time zone', 'timestamptz', NULL, 'NO', 'now()'),
--         ('reverted_at', 'timestamp with time zone', 'timestamptz', NULL, 'YES', NULL),
--         ('reverted_by_user_id', 'uuid', 'uuid', NULL, 'YES', NULL)
-- ), actual AS (
--     SELECT
--         column_name, data_type, udt_name, character_maximum_length,
--         is_nullable, column_default
--     FROM information_schema.columns
--     WHERE table_schema = 'public'
--       AND table_name = 'geo_prompt_import_batches'
-- )
-- (SELECT 'missing_or_mismatch' AS issue, * FROM expected
--  EXCEPT
--  SELECT 'missing_or_mismatch', * FROM actual)
-- UNION ALL
-- (SELECT 'unexpected_or_mismatch' AS issue, * FROM actual
--  EXCEPT
--  SELECT 'unexpected_or_mismatch', * FROM expected)
-- ORDER BY column_name, issue;
--
-- Exact constraint inventory. The result must contain zero rows; this catches
-- missing constraints, wrong types, and unexpected table constraints.
-- WITH expected(conname, contype) AS (
--     VALUES
--         ('geo_prompt_import_batches_pkey', 'p'::"char"),
--         ('geo_prompt_import_batches_client_id_fkey', 'f'::"char"),
--         ('geo_prompt_import_batches_created_by_user_id_fkey', 'f'::"char"),
--         ('geo_prompt_import_batches_reverted_by_user_id_fkey', 'f'::"char"),
--         ('geo_prompt_import_batches_source_filename_not_blank', 'c'::"char"),
--         ('geo_prompt_import_batches_raw_hash_check', 'c'::"char"),
--         ('geo_prompt_import_batches_manifest_hash_check', 'c'::"char"),
--         ('geo_prompt_import_batches_input_row_count_non_negative', 'c'::"char"),
--         ('geo_prompt_import_batches_expanded_variant_count_non_negative', 'c'::"char"),
--         ('geo_prompt_import_batches_create_count_non_negative', 'c'::"char"),
--         ('geo_prompt_import_batches_skip_count_non_negative', 'c'::"char"),
--         ('geo_prompt_import_batches_conflict_count_non_negative', 'c'::"char"),
--         ('geo_prompt_import_batches_invalid_count_non_negative', 'c'::"char"),
--         ('geo_prompt_import_batches_created_ids_match_create_count', 'c'::"char"),
--         ('geo_prompt_import_batches_status_check', 'c'::"char"),
--         ('geo_prompt_import_batches_reverted_state_check', 'c'::"char")
-- ), actual AS (
--     SELECT conname, contype
--     FROM pg_constraint
--     WHERE conrelid = 'geo_prompt_import_batches'::regclass
-- )
-- (SELECT 'missing_or_mismatch' AS issue, * FROM expected
--  EXCEPT SELECT 'missing_or_mismatch', * FROM actual)
-- UNION ALL
-- (SELECT 'unexpected_or_mismatch' AS issue, * FROM actual
--  EXCEPT SELECT 'unexpected_or_mismatch', * FROM expected)
-- ORDER BY conname, issue;
--
-- Exact primary-key columns. The result must contain zero rows.
-- WITH expected(conname, key_columns) AS (
--     VALUES ('geo_prompt_import_batches_pkey', ARRAY['id'])
-- ), actual AS (
--     SELECT
--         c.conname,
--         ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
--               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
--               ORDER BY k.ord)::TEXT[] AS key_columns
--     FROM pg_constraint c
--     WHERE c.conrelid = 'geo_prompt_import_batches'::regclass
--       AND c.contype = 'p'
-- )
-- (SELECT 'missing_or_mismatch' AS issue, * FROM expected
--  EXCEPT SELECT 'missing_or_mismatch', * FROM actual)
-- UNION ALL
-- (SELECT 'unexpected_or_mismatch' AS issue, * FROM actual
--  EXCEPT SELECT 'unexpected_or_mismatch', * FROM expected)
-- ORDER BY conname, issue;
--
-- Exact foreign-key column mappings and delete actions using catalog fields
-- rather than formatting-sensitive pg_get_constraintdef text.
-- WITH expected(conname, local_columns, foreign_table, foreign_columns, delete_action) AS (
--     VALUES
--         ('geo_prompt_import_batches_client_id_fkey', ARRAY['client_id'],
--          'geo_clients', ARRAY['id'], 'c'::"char"),
--         ('geo_prompt_import_batches_created_by_user_id_fkey', ARRAY['created_by_user_id'],
--          'geo_users', ARRAY['id'], 'n'::"char"),
--         ('geo_prompt_import_batches_reverted_by_user_id_fkey', ARRAY['reverted_by_user_id'],
--          'geo_users', ARRAY['id'], 'n'::"char")
-- ), actual AS (
--     SELECT
--         c.conname,
--         ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
--               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
--               ORDER BY k.ord)::TEXT[] AS local_columns,
--         conf_tbl.relname AS foreign_table,
--         ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
--               JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum
--               ORDER BY k.ord)::TEXT[] AS foreign_columns,
--         c.confdeltype AS delete_action
--     FROM pg_constraint c
--     JOIN pg_class conf_tbl ON conf_tbl.oid = c.confrelid
--     WHERE c.conrelid = 'geo_prompt_import_batches'::regclass
--       AND c.contype = 'f'
-- )
-- (SELECT 'missing_or_mismatch' AS issue, * FROM expected
--  EXCEPT SELECT 'missing_or_mismatch', * FROM actual)
-- UNION ALL
-- (SELECT 'unexpected_or_mismatch' AS issue, * FROM actual
--  EXCEPT SELECT 'unexpected_or_mismatch', * FROM expected)
-- ORDER BY conname, issue;
--
-- Exact, case-sensitive canonical check definitions. Run this verification on
-- the same Cloud SQL PostgreSQL version that applies this migration because
-- PostgreSQL's deparser formatting is version-specific. No normalization is
-- performed: grouping, casts, identifier/literal case, operators, and every
-- allowed status value must match exactly. The result must contain zero rows.
-- WITH expected(conname, canonical_definition) AS (
--     VALUES
--         ('geo_prompt_import_batches_source_filename_not_blank',
--          $$CHECK ((btrim(source_filename) <> ''::text))$$),
--         ('geo_prompt_import_batches_raw_hash_check',
--          $$CHECK (((raw_csv_sha256)::text ~ '^[0-9a-fA-F]{64}$'::text))$$),
--         ('geo_prompt_import_batches_manifest_hash_check',
--          $$CHECK (((normalized_manifest_sha256)::text ~ '^[0-9a-fA-F]{64}$'::text))$$),
--         ('geo_prompt_import_batches_input_row_count_non_negative',
--          $$CHECK ((input_row_count >= 0))$$),
--         ('geo_prompt_import_batches_expanded_variant_count_non_negative',
--          $$CHECK ((expanded_variant_count >= 0))$$),
--         ('geo_prompt_import_batches_create_count_non_negative',
--          $$CHECK ((create_count >= 0))$$),
--         ('geo_prompt_import_batches_skip_count_non_negative',
--          $$CHECK ((skip_count >= 0))$$),
--         ('geo_prompt_import_batches_conflict_count_non_negative',
--          $$CHECK ((conflict_count >= 0))$$),
--         ('geo_prompt_import_batches_invalid_count_non_negative',
--          $$CHECK ((invalid_count >= 0))$$),
--         ('geo_prompt_import_batches_created_ids_match_create_count',
--          $$CHECK ((cardinality(created_prompt_ids) = create_count))$$),
--         ('geo_prompt_import_batches_status_check',
--          $$CHECK ((status = ANY (ARRAY['COMMITTED'::text, 'REVERTING'::text, 'REVERTED'::text])))$$),
--         ('geo_prompt_import_batches_reverted_state_check',
--          $$CHECK ((((status = 'REVERTED'::text) AND (reverted_at IS NOT NULL)) OR ((status = ANY (ARRAY['COMMITTED'::text, 'REVERTING'::text])) AND (reverted_at IS NULL))))$$)
-- ), actual AS (
--     SELECT
--         conname,
--         pg_get_constraintdef(oid, false) AS canonical_definition
--     FROM pg_constraint
--     WHERE conrelid = 'geo_prompt_import_batches'::regclass AND contype = 'c'
-- )
-- (SELECT 'missing_or_mismatch' AS issue, * FROM expected
--  EXCEPT SELECT 'missing_or_mismatch', * FROM actual)
-- UNION ALL
-- (SELECT 'unexpected_or_mismatch' AS issue, * FROM actual
--  EXCEPT SELECT 'unexpected_or_mismatch', * FROM expected)
-- ORDER BY conname, issue;
--
-- Exact reporting-index definitions. The result must contain zero rows.
-- WITH expected(index_name, key_columns) AS (
--     VALUES
--         ('idx_geo_prompt_import_batches_client_created', ARRAY['client_id', 'created_at DESC']),
--         ('idx_geo_prompt_import_batches_client_status_created', ARRAY['client_id', 'status', 'created_at DESC'])
-- ), actual AS (
--     SELECT
--         idx.relname AS index_name,
--         ARRAY(SELECT pg_get_indexdef(i.indexrelid, pos, TRUE)
--               FROM generate_series(1, i.indnkeyatts) AS pos ORDER BY pos)::TEXT[] AS key_columns
--     FROM pg_index i
--     JOIN pg_class idx ON idx.oid = i.indexrelid
--     JOIN pg_am am ON am.oid = idx.relam
--     WHERE i.indrelid = 'geo_prompt_import_batches'::regclass
--       AND idx.relname IN (
--           'idx_geo_prompt_import_batches_client_created',
--           'idx_geo_prompt_import_batches_client_status_created'
--       )
--       AND i.indisvalid AND i.indisready
--       AND NOT i.indisunique
--       AND am.amname = 'btree'
--       AND i.indpred IS NULL AND i.indexprs IS NULL
--       AND i.indnatts = i.indnkeyatts
-- )
-- (SELECT 'missing_or_mismatch' AS issue, * FROM expected
--  EXCEPT SELECT 'missing_or_mismatch', * FROM actual)
-- UNION ALL
-- (SELECT 'unexpected_or_mismatch' AS issue, * FROM actual
--  EXCEPT SELECT 'unexpected_or_mismatch', * FROM expected)
-- ORDER BY index_name, issue;
