-- ============================================================
-- Migration 020: Agent Memories + Context Compression Settings
-- ============================================================
-- 1. Creates agent_memories table for cross-session memory persistence.
--    Memory is scoped per-user (user_identifier) within a workspace (client_id).
--    user_identifier uses provider prefix for future multi-auth support:
--      - Google OAuth: "google:<sub>"
--      - Email registration: "email:<user_id>"
--
-- 2. Inserts global settings for context compression configuration.
--    These are editable from Admin UI > Global Settings.
-- ============================================================

-- 1. Agent Memories
CREATE TABLE IF NOT EXISTS agent_memories (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    user_identifier   TEXT NOT NULL,           -- "google:<sub>" | "email:<id>" etc.
    memory_type       TEXT NOT NULL,           -- 'preference' | 'fact' | 'context' | 'brand'
    content           TEXT NOT NULL,
    metadata          JSONB DEFAULT '{}',      -- structured data (source_thread_id, extraction_model, etc.)
    shared            BOOLEAN DEFAULT FALSE,   -- if true, visible to all users under same client_id
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    expires_at        TIMESTAMPTZ              -- optional TTL for auto-cleanup
);

-- Primary query path: load memories for a specific user (+ shared ones)
CREATE INDEX IF NOT EXISTS idx_agent_memories_user
    ON agent_memories(client_id, user_identifier);

-- Admin query path: list all memories for a client workspace
CREATE INDEX IF NOT EXISTS idx_agent_memories_client
    ON agent_memories(client_id, created_at DESC);

-- Cleanup path: expire old memories
CREATE INDEX IF NOT EXISTS idx_agent_memories_expires
    ON agent_memories(expires_at)
    WHERE expires_at IS NOT NULL;

-- ============================================================
-- 2. Migrate existing user_id to prefixed format (google:<sub>)
-- ============================================================
-- All existing sessions use Google OAuth. Add "google:" prefix
-- to enable future multi-auth support without ID collisions.

UPDATE agent_sessions
SET user_id = 'google:' || user_id
WHERE user_id IS NOT NULL
  AND user_id != ''
  AND user_id NOT LIKE 'google:%';

-- ============================================================
-- 3. Context Compression Settings
-- ============================================================
-- Configurable from Admin UI > Global Settings page.
-- agent_compress_threshold: number of conversation turns before triggering compression.
-- agent_compress_retain: number of recent turns to keep uncompressed.

INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('agent_compress_threshold', '10', 'Number of conversation turns before triggering context compression')
ON CONFLICT (key) DO NOTHING;

INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('agent_compress_retain', '4', 'Number of recent turns to keep uncompressed after compression')
ON CONFLICT (key) DO NOTHING;
