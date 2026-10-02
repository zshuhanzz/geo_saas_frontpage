-- Migration 099: Add model-specific Vertex AI region overrides
--
-- Purpose:
--   Keep existing *_model_id settings as plain model-id strings while allowing
--   specific GA models (for example gemini-3.5-flash) to route to the global
--   Vertex endpoint.
--
-- Safe to re-run:
--   Yes. Existing valid JSON overrides are preserved and win over defaults.

BEGIN;

DO $$
DECLARE
  default_overrides jsonb := '{
    "gemini-3.5-flash": "global",
    "gemini-3.1-pro-preview": "global",
    "gemini-3-flash-preview": "global"
  }'::jsonb;
  existing_value text;
  existing_overrides jsonb := '{}'::jsonb;
BEGIN
  SELECT value
    INTO existing_value
    FROM geo_global_settings
   WHERE key = 'model_region_overrides'
   FOR UPDATE;

  IF existing_value IS NOT NULL THEN
    BEGIN
      existing_overrides := existing_value::jsonb;
      IF jsonb_typeof(existing_overrides) <> 'object' THEN
        existing_overrides := '{}'::jsonb;
      END IF;
    EXCEPTION WHEN others THEN
      existing_overrides := '{}'::jsonb;
    END;
  END IF;

  INSERT INTO geo_global_settings (key, value, description)
  VALUES (
    'model_region_overrides',
    (default_overrides || existing_overrides)::text,
    'JSON object mapping Gemini model IDs to Vertex AI locations, e.g. {"gemini-3.5-flash":"global"}'
  )
  ON CONFLICT (key) DO UPDATE
     SET value = (default_overrides || existing_overrides)::text,
         description = EXCLUDED.description;
END $$;

COMMIT;
