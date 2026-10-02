-- ============================================================
-- Migration 127: Retire Frozen Static Report List Storage
-- ============================================================
-- Purpose:
--   - Delete the seven Dreamina v5 reports generated only for the 2026-07-15
--     local E2E/performance verification run.
--   - Remove geo_static_report_lists after the application has switched new
--     reports to dynamic-report-v1 and no other report depends on the table.
--
-- Safety:
--   - Run manually only after deploying the dynamic-report application code.
--   - The transaction aborts unless all seven exact reports exist and they are
--     the only reports represented in geo_static_report_lists.
--   - No production/customer report outside the explicit UUID allowlist can
--     be deleted by this migration.
-- ============================================================

BEGIN;

-- Serialize retirement against every legacy report completion/write. Deploy the
-- dynamic-report revision and drain older instances before running this file.
LOCK TABLE geo_static_reports IN ACCESS EXCLUSIVE MODE;
LOCK TABLE geo_static_report_lists IN ACCESS EXCLUSIVE MODE;

DO $$
DECLARE
    expected_report_ids CONSTANT UUID[] := ARRAY[
        'caa37862-44ed-4e4b-bd84-d11071a6bcb6'::UUID,
        'a4f44346-1af5-42ad-a6f9-317796274eaa'::UUID,
        '6d6d0681-4fcf-451a-a34d-e7401bb2c006'::UUID,
        '6238dad2-e1a8-456d-a23b-722b8dc5e8b9'::UUID,
        '8e26c66f-f3f0-4fb2-a23e-d4289960c84e'::UUID,
        'b816b10f-2a15-42c0-a240-482be101f697'::UUID,
        'd3923987-1a12-4431-aab0-6022f0aae2e6'::UUID
    ];
    dreamina_client_id CONSTANT UUID := 'b0e10518-5f70-426f-b09e-dbe025984ba1'::UUID;
    matched_reports INTEGER;
    deleted_reports INTEGER;
    unexpected_dependencies INTEGER;
    unexpected_v5_reports INTEGER;
BEGIN
    IF to_regclass('public.geo_static_report_lists') IS NULL THEN
        RAISE EXCEPTION 'geo_static_report_lists does not exist; migration 127 cannot validate dependencies';
    END IF;

    SELECT COUNT(*)
    INTO matched_reports
    FROM geo_static_reports
    WHERE id = ANY(expected_report_ids)
      AND client_id = dreamina_client_id
      AND snapshot_version = 'static-report-v5';

    IF matched_reports <> cardinality(expected_report_ids) THEN
        RAISE EXCEPTION
            'Expected exactly % Dreamina static-report-v5 test reports, found %',
            cardinality(expected_report_ids), matched_reports;
    END IF;

    SELECT COUNT(*)
    INTO unexpected_dependencies
    FROM geo_static_report_lists
    WHERE report_id <> ALL(expected_report_ids);

    IF unexpected_dependencies <> 0 THEN
        RAISE EXCEPTION
            'geo_static_report_lists still contains % rows owned by reports outside the seven-report allowlist',
            unexpected_dependencies;
    END IF;

    SELECT COUNT(*)
    INTO unexpected_v5_reports
    FROM geo_static_reports
    WHERE snapshot_version = 'static-report-v5'
      AND id <> ALL(expected_report_ids);

    IF unexpected_v5_reports <> 0 THEN
        RAISE EXCEPTION
            'Found % static-report-v5 reports outside the seven-report allowlist; refusing to retire their storage',
            unexpected_v5_reports;
    END IF;

    DELETE FROM geo_static_reports
    WHERE id = ANY(expected_report_ids)
      AND client_id = dreamina_client_id
      AND snapshot_version = 'static-report-v5';
    GET DIAGNOSTICS deleted_reports = ROW_COUNT;

    IF deleted_reports <> cardinality(expected_report_ids) THEN
        RAISE EXCEPTION
            'Expected to delete % test reports, deleted %',
            cardinality(expected_report_ids), deleted_reports;
    END IF;

    IF EXISTS (SELECT 1 FROM geo_static_report_lists) THEN
        RAISE EXCEPTION 'ON DELETE CASCADE did not empty geo_static_report_lists';
    END IF;
END $$;

DROP TABLE geo_static_report_lists;
DROP INDEX IF EXISTS idx_geo_static_reports_id_client_unique;

COMMIT;

-- Manual read-only verification after execution. Both rows must be false.
-- SELECT
--     to_regclass('public.geo_static_report_lists') IS NOT NULL AS list_table_still_exists,
--     to_regclass('public.idx_geo_static_reports_id_client_unique') IS NOT NULL AS support_index_still_exists;
--
-- All seven counts must be zero.
-- SELECT id, COUNT(*)
-- FROM geo_static_reports
-- WHERE id = ANY(ARRAY[
--     'caa37862-44ed-4e4b-bd84-d11071a6bcb6'::UUID,
--     'a4f44346-1af5-42ad-a6f9-317796274eaa'::UUID,
--     '6d6d0681-4fcf-451a-a34d-e7401bb2c006'::UUID,
--     '6238dad2-e1a8-456d-a23b-722b8dc5e8b9'::UUID,
--     '8e26c66f-f3f0-4fb2-a23e-d4289960c84e'::UUID,
--     'b816b10f-2a15-42c0-a240-482be101f697'::UUID,
--     'd3923987-1a12-4431-aab0-6022f0aae2e6'::UUID
-- ])
-- GROUP BY id;
