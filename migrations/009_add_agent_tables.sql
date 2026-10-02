-- ============================================================
-- Migration 009: Agent Layer Tables
-- ============================================================
-- For geo_agent module (Anthony Chat + Analyze/Action Agents).
--
-- NOTE: LangGraph's AsyncPostgresSaver.setup() will auto-create
-- its own checkpoint tables (checkpoint_blobs, checkpoint_writes,
-- checkpoints, checkpoint_migrations). You do NOT need to create
-- those manually — they are created on first startup.
--
-- This migration creates our APPLICATION-LEVEL session/message
-- tables (separate from LangGraph's internal state).
-- ============================================================

-- 1. Agent Sessions (chat history sidebar)
CREATE TABLE IF NOT EXISTS agent_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id   TEXT UNIQUE NOT NULL,
    client_id   UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    user_id     TEXT,               -- OAuth subject ID (Google sub, Apple sub, etc.)
    title       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_client_user
    ON agent_sessions(client_id, user_id);

-- 2. Agent Messages (for history replay, NOT for Agent execution)
-- Agent execution state lives in LangGraph checkpoints.
-- This table stores the rendered conversation for frontend display.
CREATE TABLE IF NOT EXISTS agent_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id       TEXT NOT NULL REFERENCES agent_sessions(thread_id) ON DELETE CASCADE,
    role            TEXT NOT NULL,           -- 'human' | 'ai' | 'tool'
    content         TEXT,
    tool_results    JSONB,                  -- Charts, query results (JSON)
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_thread
    ON agent_messages(thread_id);

-- 3. Brand Profiles (Tier 2 Context-Aware — brand tonality injection)
-- Used by Action Agent to generate brand-aligned content.
-- Editable from both Admin UI and SaaS UI.
CREATE TABLE IF NOT EXISTS geo_brand_profiles (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    brand_name        TEXT,
    tone_of_voice     TEXT,               -- e.g. "专业严谨" or "亲民实用"
    target_audience   TEXT,
    key_messages      JSONB,              -- ["智能清洁专家", "性价比之王"]
    brand_values      JSONB,              -- ["创新", "品质", "用户至上"]
    language          TEXT DEFAULT 'zh-CN',
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id)
);

-- ============================================================
-- 4. Seed global settings for Agent model IDs
-- ============================================================
-- Uses ON CONFLICT to avoid duplicates if re-run.
-- Update the 'value' column to change model versions.
INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('agent_pro_model_id',   'gemini-3.1-pro-preview',   'Gemini model for Analyze/Action agents (precision)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('agent_flash_model_id', 'gemini-3-flash-preview', 'Gemini model for Supervisor/Chat agents (fast)')
ON CONFLICT (key) DO NOTHING;

-- Agent timeout settings (seconds)
INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('agent_timeout_pro_seconds', '60', 'Timeout for Gemini Pro calls in Agent (Analyze/Action)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('agent_timeout_flash_seconds', '30', 'Timeout for Gemini Flash calls in Agent (Supervisor/Chat)')
ON CONFLICT (key) DO NOTHING;

-- Agent rate limiting settings
INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('agent_rate_limit_max_requests', '20', 'Max requests per client within the sliding window')
ON CONFLICT (key) DO NOTHING;

INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('agent_rate_limit_window_seconds', '300', 'Sliding window duration in seconds (default 5 min)')
ON CONFLICT (key) DO NOTHING;
