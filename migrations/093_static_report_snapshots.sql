-- ============================================================
-- Migration 093: Static Report Snapshots
-- ============================================================
-- Spec: docs/superpowers/specs/2026-05-27-static-report-snapshot-design.md
--
-- Purpose:
--   - Store one immutable static report snapshot per client per Shanghai date.
--   - Persist JSON report data generated from existing Analyzer outputs.
--   - Keep static reports decoupled from Collector and Analyzer execution.
--
-- Execution:
--   - Run manually in Cloud SQL.
--   - This migration creates schema objects only.
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS geo_static_reports (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id                UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    report_date              DATE NOT NULL,
    timezone                 TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    status                   TEXT NOT NULL,
    snapshot_version         TEXT NOT NULL,
    snapshot_json            JSONB,
    data_window_start        DATE NOT NULL,
    data_window_end          DATE NOT NULL,
    rendering_mode           TEXT NOT NULL,
    data_completeness        JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message            TEXT,
    materialized_by_user_id  UUID REFERENCES geo_users(id) ON DELETE SET NULL,
    materialized_at          TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT geo_static_reports_unique_day UNIQUE (client_id, report_date),
    CONSTRAINT geo_static_reports_status_check CHECK (
        status IN ('PENDING', 'MATERIALIZING', 'COMPLETED', 'NOT_READY', 'FAILED')
    ),
    CONSTRAINT geo_static_reports_rendering_mode_check CHECK (
        rendering_mode IN ('single_day', 'multi_day')
    ),
    CONSTRAINT geo_static_reports_timezone_check CHECK (btrim(timezone) <> ''),
    CONSTRAINT geo_static_reports_snapshot_version_check CHECK (btrim(snapshot_version) <> ''),
    CONSTRAINT geo_static_reports_window_check CHECK (data_window_start <= data_window_end)
);

CREATE INDEX IF NOT EXISTS idx_geo_static_reports_client_date
    ON geo_static_reports (client_id, report_date DESC);

CREATE INDEX IF NOT EXISTS idx_geo_static_reports_client_status
    ON geo_static_reports (client_id, status);

CREATE OR REPLACE FUNCTION set_geo_static_reports_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_geo_static_reports_updated_at ON geo_static_reports;
CREATE TRIGGER trg_geo_static_reports_updated_at
    BEFORE UPDATE ON geo_static_reports
    FOR EACH ROW EXECUTE FUNCTION set_geo_static_reports_updated_at();

COMMENT ON TABLE geo_static_reports IS 'One daily static GEO report snapshot per client, materialized from existing analyzed data.';
COMMENT ON COLUMN geo_static_reports.snapshot_json IS 'Canonical static report JSON. Report detail pages render this payload without calling live dashboard endpoints.';
COMMENT ON COLUMN geo_static_reports.report_date IS 'Shanghai local calendar date represented by the report.';

COMMIT;

-- Manual verification after execution:
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'geo_static_reports'
-- ORDER BY ordinal_position;
