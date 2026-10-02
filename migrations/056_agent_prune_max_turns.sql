-- ============================================================
-- Migration 056: Seed agent_prune_max_turns global setting
-- ============================================================
--
-- Background
-- ----------
-- `geo_agent/src/context/pruner.py` previously hardcoded
-- DEFAULT_MAX_TURNS = 10 as the only source of truth for how many user
-- turns to retain when truncating conversation history before each LLM
-- call. Ops had no way to tune this without a code change + redeploy.
--
-- This migration aligns pruner.py with the existing pattern used by
-- compressor.py: read the budget from `geo_global_settings`, with a 60s
-- in-process cache and a code-side fallback if the DB read fails.
--
-- The default value (10) preserves existing production behavior. Lower
-- it for cost-sensitive tenants; raise it when long-context recall
-- starts mattering.
--
-- This migration is idempotent — re-running it is safe.

BEGIN;

INSERT INTO geo_global_settings (key, value, description)
VALUES (
    'agent_prune_max_turns',
    '10',
    'Number of trailing user turns to retain when pruning conversation history before sending to the LLM (Layer 1 of context management)'
)
ON CONFLICT (key) DO UPDATE
    SET description = EXCLUDED.description;
-- Note: only the description is force-updated on conflict. The value is
-- preserved on re-run so an ops-tuned value is not silently reset to 10.

COMMIT;
