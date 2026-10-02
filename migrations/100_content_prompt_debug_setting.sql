-- Migration 100: Add content generation final prompt debug toggle
--
-- Purpose:
--   Allows Admin UI Global Config to temporarily enable full prompt logging
--   for content generation, quality review, and revise calls.
--
-- Safe to re-run:
--   Yes. Existing operator value is preserved.

INSERT INTO geo_global_settings (key, value, description)
VALUES (
    'content_generation_log_final_prompt',
    'false',
    'When true, geo_agent logs full Gemini prompts for content generation, strategy, quality review, and revise in chunked CONTENT_PROMPT_DEBUG log entries. Enable only for debugging, then turn off.'
)
ON CONFLICT (key) DO UPDATE
   SET description = EXCLUDED.description;
