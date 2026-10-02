-- =============================================================
-- Migration 018: Drop geo_analysis_metrics table
-- Run: psql $DATABASE_URL -f migrations/018_drop_analysis_metrics.sql
-- =============================================================
-- This table is no longer used by any active pipeline.
-- The agent pipeline now uses dynamic metric discovery from live schema
-- via Gemini (GET /api/agent/tasks/metrics/discover).
-- =============================================================

DROP INDEX IF EXISTS idx_geo_analysis_metrics_domain;
DROP TABLE IF EXISTS geo_analysis_metrics;
