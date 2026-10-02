-- ============================================================
-- Migration 135: AnswerX HttpOnly user Sessions
-- ============================================================
-- Purpose:
--   - Exchange short-lived Google login credentials for revocable AnswerX
--     browser Sessions.
--   - Keep SaaS/Agent (24h) and Admin (12h) Sessions strictly scoped.
--   - Store only a SHA-256 token hash; raw cookie values never reach Cloud SQL.
--
-- Data migration:
--   - None. Existing Google ID tokens live only in browser localStorage and
--     intentionally are not imported.
--   - Rows are created naturally after each successful post-cutover login.
--
-- Execution:
--   - Run manually in Cloud SQL after migration 134.
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS geo_user_sessions (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id        UUID NOT NULL
                   REFERENCES geo_users(id) ON DELETE CASCADE,
    session_scope  TEXT NOT NULL
                   CHECK (session_scope IN ('saas', 'admin')),
    token_hash     TEXT NOT NULL UNIQUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at     TIMESTAMPTZ NOT NULL,
    last_seen_at   TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    end_reason     TEXT
                   CHECK (end_reason IS NULL OR end_reason IN (
                       'expired', 'logout', 'revoked'
                   )),
    created_ip     TEXT,
    user_agent     TEXT,

    CONSTRAINT geo_user_sessions_token_hash_sha256
        CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT geo_user_sessions_expiry_after_creation
        CHECK (expires_at > created_at),
    CONSTRAINT geo_user_sessions_end_state_consistent
        CHECK (
            (ended_at IS NULL AND end_reason IS NULL)
            OR
            (ended_at IS NOT NULL AND end_reason IS NOT NULL)
        )
);

CREATE INDEX IF NOT EXISTS idx_geo_user_sessions_user_active
    ON geo_user_sessions (user_id, session_scope, expires_at DESC)
    WHERE ended_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_geo_user_sessions_expiry_active
    ON geo_user_sessions (expires_at)
    WHERE ended_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_geo_user_sessions_ended
    ON geo_user_sessions (ended_at)
    WHERE ended_at IS NOT NULL;

COMMENT ON TABLE geo_user_sessions IS
    'Revocable AnswerX browser Sessions. SaaS/Agent and Admin use independent scopes and cookies.';
COMMENT ON COLUMN geo_user_sessions.token_hash IS
    'SHA-256 of the opaque browser token. Never store or log the raw token.';
COMMENT ON COLUMN geo_user_sessions.session_scope IS
    'saas is accepted by SaaS and Agent; admin is accepted only by Admin.';
COMMENT ON COLUMN geo_user_sessions.end_reason IS
    'One terminal lifecycle transition: expired, explicit logout, or security/admin revoke.';

COMMIT;

-- Manual verification:
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'geo_user_sessions'
-- ORDER BY ordinal_position;
--
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename = 'geo_user_sessions'
-- ORDER BY indexname;
--
-- SELECT COUNT(*) AS initial_session_rows FROM geo_user_sessions;
