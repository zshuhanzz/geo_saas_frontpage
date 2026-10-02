-- Migration 098: Add Cloro Perplexity and Google AI Overview platforms
--
-- Purpose:
--   1. Seed Perplexity and AI Overview into geo_global_platforms.
--   2. Seed shared workflow platform display config when geo_workflow_config exists.
--   3. Leave existing customer config_platforms unchanged; Admins opt clients in.
--
-- Safe to re-run:
--   Yes. The migration updates existing rows and inserts missing rows by key.

BEGIN;

WITH platform_rows AS (
  SELECT *
  FROM (
    VALUES
      (
        'perplexity',
        'Perplexity',
        ARRAY[
          'US','GB','AU','CA','IN','DE','FR','JP','KR','BR','MX','ES','IT','NL',
          'SE','NO','DK','FI','PL','CZ','AT','CH','BE','IE','NZ','SG','HK','TW',
          'PH','MY','TH','ID','VN','ZA','NG','KE','EG','IL','AE','SA','TR','RU',
          'UA','AR','CL','CO','PE'
        ]::text[],
        ''
      ),
      (
        'aioverview',
        'AI Overview',
        ARRAY['US']::text[],
        ''
      )
  ) AS v(platform_id, display_name, supported_countries, system_instructions)
),
updated AS (
  UPDATE geo_global_platforms AS gp
     SET display_name = pr.display_name,
         supported_countries = pr.supported_countries,
         system_instructions = pr.system_instructions,
         is_active = TRUE,
         updated_at = NOW()
    FROM platform_rows AS pr
   WHERE gp.platform_id = pr.platform_id
  RETURNING gp.platform_id
)
INSERT INTO geo_global_platforms (
  id,
  platform_id,
  display_name,
  supported_countries,
  system_instructions,
  is_active
)
SELECT
  gen_random_uuid(),
  pr.platform_id,
  pr.display_name,
  pr.supported_countries,
  pr.system_instructions,
  TRUE
FROM platform_rows AS pr
WHERE NOT EXISTS (
  SELECT 1
  FROM geo_global_platforms AS gp
  WHERE gp.platform_id = pr.platform_id
);

DO $$
BEGIN
  IF to_regclass('public.geo_workflow_config') IS NOT NULL THEN
    UPDATE geo_workflow_config
       SET value = '{"label": "Perplexity", "icon": "🔎", "color": "text-teal-400 border-teal-500/30 bg-teal-500/5"}'::jsonb,
           sort_order = 4,
           is_active = TRUE
     WHERE config_type = 'platform'
       AND scope = 'shared'
       AND key = 'perplexity';

    IF NOT FOUND THEN
      INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
      VALUES (
        'platform',
        'shared',
        'perplexity',
        '{"label": "Perplexity", "icon": "🔎", "color": "text-teal-400 border-teal-500/30 bg-teal-500/5"}'::jsonb,
        4,
        TRUE
      );
    END IF;

    UPDATE geo_workflow_config
       SET value = '{"label": "AI Overview", "icon": "🌐", "color": "text-sky-400 border-sky-500/30 bg-sky-500/5"}'::jsonb,
           sort_order = 5,
           is_active = TRUE
     WHERE config_type = 'platform'
       AND scope = 'shared'
       AND key = 'aioverview';

    IF NOT FOUND THEN
      INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
      VALUES (
        'platform',
        'shared',
        'aioverview',
        '{"label": "AI Overview", "icon": "🌐", "color": "text-sky-400 border-sky-500/30 bg-sky-500/5"}'::jsonb,
        5,
        TRUE
      );
    END IF;
  END IF;
END $$;

COMMIT;
