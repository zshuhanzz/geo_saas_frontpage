-- =============================================================================
-- Migration 022: Add optimized index for daily quota SUM query
-- Run: psql $DATABASE_URL -f migrations/022_add_token_usage_index.sql
-- =============================================================================
--
-- The daily quota query does:
--   SELECT SUM(tokens_input + tokens_output)
--   FROM agent_token_usage
--   WHERE client_id = $1 AND user_identifier = $2 AND created_at >= <today>
--
-- A covering index on (client_id, user_identifier, created_at DESC)
-- already exists (idx_agent_token_usage_daily), but adding tokens as
-- INCLUDE columns lets Postgres do an index-only scan without heap access.
-- =============================================================================

-- Drop old index and recreate with INCLUDE for index-only scan
DROP INDEX IF EXISTS idx_agent_token_usage_daily;

CREATE INDEX idx_agent_token_usage_daily
    ON agent_token_usage (client_id, user_identifier, created_at DESC)
    INCLUDE (tokens_input, tokens_output);

-- Fix historical records with 'unknown' model_id
UPDATE agent_token_usage SET model_id = 'auto' WHERE model_id = 'unknown';
