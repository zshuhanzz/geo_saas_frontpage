-- =============================================================================
-- Migration 021: Agent Quota, Token Usage, User Profiles, Compression Config
-- Run: psql $DATABASE_URL -f migrations/021_add_agent_quota_tracking.sql
-- =============================================================================
--
-- 1. Per-client quota config on geo_clients (daily token budget + RPM)
-- 2. Per-request token usage tracking table
-- 3. User profile table (one Markdown doc per user per client)
-- 4. Global settings: percentage-based compression trigger
-- =============================================================================


-- ── 1. Client-level quota configuration ──────────────────────────────────────

-- Clean up old columns if they exist (from earlier draft)
ALTER TABLE geo_clients DROP COLUMN IF EXISTS agent_token_quota_hourly;
ALTER TABLE geo_clients DROP COLUMN IF EXISTS agent_request_quota_per_window;
ALTER TABLE geo_clients DROP COLUMN IF EXISTS agent_request_window_seconds;

-- New quota columns
ALTER TABLE geo_clients
  ADD COLUMN IF NOT EXISTS agent_daily_token_quota INTEGER NOT NULL DEFAULT 500000,
  ADD COLUMN IF NOT EXISTS agent_rpm_limit         INTEGER NOT NULL DEFAULT 10;

COMMENT ON COLUMN geo_clients.agent_daily_token_quota
  IS 'Max tokens (input+output) per user per day. Default 500K. Resets daily at UTC 00:00.';
COMMENT ON COLUMN geo_clients.agent_rpm_limit
  IS 'Max chat requests per user per minute. Default 10. Enforced in-memory.';


-- ── 2. Per-request token usage tracking ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_token_usage (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id        UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    user_identifier  TEXT NOT NULL,
    tokens_input     INTEGER NOT NULL DEFAULT 0,
    tokens_output    INTEGER NOT NULL DEFAULT 0,
    model_id         TEXT,
    entry_point      TEXT,           -- 'chat' | 'analyze' | 'content' | 'memory_eval' | 'compress'
    thread_id        TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_token_usage_daily
    ON agent_token_usage (client_id, user_identifier, created_at DESC);


-- ── 3. User profiles (one Markdown doc per user per client) ──────────────────

CREATE TABLE IF NOT EXISTS agent_user_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    user_identifier TEXT NOT NULL,
    profile_md      TEXT NOT NULL DEFAULT '',   -- Free-form Markdown document
    onboarded       BOOLEAN DEFAULT FALSE,      -- True after cold-start interview completes
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id, user_identifier)
);

CREATE INDEX IF NOT EXISTS idx_agent_user_profiles_client
    ON agent_user_profiles (client_id);


-- ── 4. Compression: switch from turn-count to percentage trigger ─────────────

-- Remove old turn-count threshold (if present)
DELETE FROM geo_global_settings WHERE key = 'agent_compress_threshold';

-- Add percentage trigger (compress when context >= 80%)
INSERT INTO geo_global_settings (key, value, description)
VALUES ('agent_compress_percentage', '80', 'Auto-compress when context usage >= this percentage')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;

-- Keep agent_compress_retain (how many recent turns to keep after compression)
-- Default 4, already seeded in prior migration. No change needed.
