-- ============================================================
-- Migration 011: Add user_id to agent_sessions
-- ============================================================
-- Enables per-user session isolation within a workspace (client).
-- user_id stores the OAuth provider's subject identifier (e.g. Google sub).
-- Future: when a users table exists, migrate to UUID FK.
-- ============================================================

ALTER TABLE agent_sessions
    ADD COLUMN IF NOT EXISTS user_id TEXT;

-- Composite index: most queries filter by (client_id, user_id)
CREATE INDEX IF NOT EXISTS idx_agent_sessions_client_user
    ON agent_sessions(client_id, user_id);
