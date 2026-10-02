-- ============================================================
-- Migration 094: Static Report Window Days
-- ============================================================
-- Purpose:
--   - Allow multiple static report snapshots for the same client/report date
--     when they use different data windows (1/7/14/30 days).
--   - Preserve existing reports as 7-day reports.
--
-- Execution:
--   - Run manually in Cloud SQL after migration 093.
-- ============================================================

BEGIN;

ALTER TABLE geo_static_reports
    ADD COLUMN IF NOT EXISTS window_days INTEGER NOT NULL DEFAULT 7;

ALTER TABLE geo_static_reports
    DROP CONSTRAINT IF EXISTS geo_static_reports_unique_day;

ALTER TABLE geo_static_reports
    DROP CONSTRAINT IF EXISTS geo_static_reports_unique_day_window;

ALTER TABLE geo_static_reports
    ADD CONSTRAINT geo_static_reports_unique_day_window
    UNIQUE (client_id, report_date, window_days);

ALTER TABLE geo_static_reports
    DROP CONSTRAINT IF EXISTS geo_static_reports_window_days_check;

ALTER TABLE geo_static_reports
    ADD CONSTRAINT geo_static_reports_window_days_check
    CHECK (window_days IN (1, 7, 14, 30));

CREATE INDEX IF NOT EXISTS idx_geo_static_reports_client_date_window
    ON geo_static_reports (client_id, report_date DESC, window_days);

COMMENT ON COLUMN geo_static_reports.window_days IS 'Data window length used to materialize the static report snapshot. Existing reports default to 7 days.';

COMMIT;

