-- ============================================================
-- Migration 062: SaaS User Audit Events
-- ============================================================
-- Purpose:
--   - Record user behavior inside the SaaS UI only.
--   - Capture PageView and meaningful API Action events.
--   - Exclude Admin UI authorization/audit actions and ordinary GET list reads.
--
-- Execution:
--   - Run manually in Cloud SQL after migration 061.
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS geo_user_audit_events (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       UUID NOT NULL REFERENCES geo_users(id) ON DELETE CASCADE,
    client_id     UUID REFERENCES geo_clients(id) ON DELETE SET NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN ('page_view', 'api_action')),
    action_key    TEXT NOT NULL,
    action_label  TEXT,
    route         TEXT,
    method        TEXT,
    status_code   INTEGER,
    target_type   TEXT,
    target_id     TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address    TEXT,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT geo_user_audit_events_action_key_not_blank
        CHECK (btrim(action_key) <> ''),
    CONSTRAINT geo_user_audit_events_method_not_blank
        CHECK (method IS NULL OR btrim(method) <> '')
);

CREATE INDEX IF NOT EXISTS idx_geo_user_audit_events_created_at
    ON geo_user_audit_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_geo_user_audit_events_client_created
    ON geo_user_audit_events (client_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_geo_user_audit_events_user_created
    ON geo_user_audit_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_geo_user_audit_events_event_type
    ON geo_user_audit_events (event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_geo_user_audit_events_action_key
    ON geo_user_audit_events (action_key, created_at DESC);

COMMENT ON TABLE geo_user_audit_events IS
    'Append-only audit events for SaaS UI page views and meaningful user actions.';
COMMENT ON COLUMN geo_user_audit_events.metadata IS
    'Small, non-sensitive JSON metadata. Do not store prompt text, chat content, tokens, or secrets.';

COMMIT;

