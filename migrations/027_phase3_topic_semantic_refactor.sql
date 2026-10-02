-- =============================================================
-- Migration 027: Phase 3 — Topic Semantic Refactor
-- Run: psql $DATABASE_URL -f migrations/027_phase3_topic_semantic_refactor.sql
-- =============================================================
-- This migration redefines Topic from "product line" to "semantic theme / topic cluster".
-- See: docs/roadmap_20260411.md § 4.2
--
-- Summary of changes:
--   1. Add topic_type enum column to geo_client_topics with CHECK constraint
--   2. Backfill existing rows as 'semantic_topic' (Roborock topic rows remain valid
--      under the new definition because they already describe categories like
--      "robot vacuum", "wet & dry", etc., which are semantic themes).
--   3. Add helpful comment so schema introspection tools see the new definition.
-- =============================================================

BEGIN;

-- =============================================================
-- STEP 1: Add topic_type column (idempotent)
-- =============================================================

ALTER TABLE geo_client_topics
    ADD COLUMN IF NOT EXISTS topic_type TEXT DEFAULT 'semantic_topic';

-- Drop old constraint if it exists (idempotent re-run)
ALTER TABLE geo_client_topics
    DROP CONSTRAINT IF EXISTS geo_client_topics_topic_type_check;

-- Add fresh CHECK constraint
ALTER TABLE geo_client_topics
    ADD CONSTRAINT geo_client_topics_topic_type_check
    CHECK (topic_type IN ('product_line', 'semantic_topic'));

-- =============================================================
-- STEP 2: Backfill existing rows
-- =============================================================
-- Any rows created before this migration had no topic_type; default them to
-- 'semantic_topic' so the new definition is the forward-going baseline.

UPDATE geo_client_topics
SET topic_type = 'semantic_topic'
WHERE topic_type IS NULL;

-- Make the column NOT NULL once backfill is complete
ALTER TABLE geo_client_topics
    ALTER COLUMN topic_type SET NOT NULL;

-- =============================================================
-- STEP 3: Schema comment (for introspection tools + DBAs)
-- =============================================================

COMMENT ON COLUMN geo_client_topics.topic_type IS
    'Topic classification: semantic_topic (theme/topic cluster used for AI-search monitoring, default) or product_line (legacy product line grouping). The platform treats topics as semantic themes by default.';

COMMENT ON TABLE geo_client_topics IS
    'Client topics — semantic themes (not product lines) that a client tracks across AI search engines. Each topic groups related products, queries, and analyses under one monitoring umbrella.';

COMMIT;

-- =============================================================
-- Verification (run manually after COMMIT)
-- =============================================================
-- SELECT topic_type, COUNT(*) FROM geo_client_topics GROUP BY topic_type;
-- \d+ geo_client_topics
