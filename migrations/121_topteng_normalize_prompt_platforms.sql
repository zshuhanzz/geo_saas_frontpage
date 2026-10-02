-- 121_topteng_normalize_prompt_platforms.sql
-- Normalize Topteng (拓腾) prompt platform configuration to:
--   aimode, chatgpt, gemini
--
-- Context:
--   geo_client_prompts stores one physical row per logical prompt/platform.
--   Per product-owner decision, non-target platform rows are deleted rather
--   than deactivated, so the prompt pool has no inactive cleanup rows.
--
-- Important:
--   geo_tasks.client_prompt_id has ON DELETE CASCADE. Deleting non-target
--   physical prompt rows will cascade-delete tasks for those prompt rows.
--   geo_results / analysis fact rows are not deleted by this migration, but
--   historical task rows for removed platforms will no longer be present.
--
-- Expected impact at creation time:
--   - logical active prompts remain 100
--   - active physical geo_client_prompts go from 498 to 300
--   - insert 3 missing target-platform rows
--   - delete 201 active rows: 98 aioverview + 103 perplexity
--   - update geo_clients.config_platforms to {aimode,chatgpt,gemini}

BEGIN;

WITH target_client AS (
    SELECT id
      FROM geo_clients
     WHERE id = '89b03a38-b49f-469f-80c4-8740113372fe'::uuid
       AND name = '拓腾'
),
updated_client AS (
    UPDATE geo_clients gc
       SET config_platforms = ARRAY['aimode', 'chatgpt', 'gemini']::text[],
           updated_at = NOW()
      FROM target_client tc
     WHERE gc.id = tc.id
       AND gc.config_platforms IS DISTINCT FROM ARRAY['aimode', 'chatgpt', 'gemini']::text[]
    RETURNING gc.id
)
SELECT COUNT(*) AS client_rows_updated
  FROM updated_client;

WITH target_client AS (
    SELECT id
      FROM geo_clients
     WHERE id = '89b03a38-b49f-469f-80c4-8740113372fe'::uuid
       AND name = '拓腾'
),
target_platforms(platform) AS (
    VALUES ('aimode'), ('chatgpt'), ('gemini')
),
active_logical_prompts AS (
    SELECT DISTINCT ON (
           p.topic_id,
           p.text,
           COALESCE(p.intent, ''),
           COALESCE(p.product, ''),
           p.country,
           p.language
       )
           p.client_id,
           p.topic_id,
           p.text,
           p.intent,
           p.product,
           p.country,
           p.language
      FROM geo_client_prompts p
      JOIN target_client tc ON tc.id = p.client_id
     WHERE p.is_active = TRUE
     ORDER BY
           p.topic_id,
           p.text,
           COALESCE(p.intent, ''),
           COALESCE(p.product, ''),
           p.country,
           p.language,
           p.created_at DESC,
           p.id
),
inserted_missing_target_platforms AS (
    INSERT INTO geo_client_prompts (
        id,
        client_id,
        topic_id,
        text,
        intent,
        product,
        platform,
        country,
        language,
        is_active
    )
    SELECT
        gen_random_uuid(),
        alp.client_id,
        alp.topic_id,
        alp.text,
        alp.intent,
        alp.product,
        tp.platform,
        alp.country,
        alp.language,
        TRUE
      FROM active_logical_prompts alp
      CROSS JOIN target_platforms tp
     WHERE NOT EXISTS (
           SELECT 1
             FROM geo_client_prompts existing
            WHERE existing.client_id = alp.client_id
              AND existing.topic_id = alp.topic_id
              AND existing.text = alp.text
              AND COALESCE(existing.intent, '') = COALESCE(alp.intent, '')
              AND COALESCE(existing.product, '') = COALESCE(alp.product, '')
              AND existing.country = alp.country
              AND existing.language = alp.language
              AND existing.platform = tp.platform
              AND existing.is_active = TRUE
       )
    RETURNING id
)
SELECT COUNT(*) AS target_platform_rows_inserted
  FROM inserted_missing_target_platforms;

WITH target_client AS (
    SELECT id
      FROM geo_clients
     WHERE id = '89b03a38-b49f-469f-80c4-8740113372fe'::uuid
       AND name = '拓腾'
),
ranked_prompts AS (
    SELECT
        p.id,
        p.platform,
        ROW_NUMBER() OVER (
            PARTITION BY
                p.topic_id,
                p.text,
                COALESCE(p.intent, ''),
                COALESCE(p.product, ''),
                p.country,
                p.language,
                p.platform
            ORDER BY p.created_at DESC, p.id
        ) AS rn
      FROM geo_client_prompts p
      JOIN target_client tc ON tc.id = p.client_id
),
deleted_prompt_rows AS (
    DELETE FROM geo_client_prompts p
      USING ranked_prompts rp
     WHERE p.id = rp.id
       AND (
            rp.platform NOT IN ('aimode', 'chatgpt', 'gemini')
            OR rp.rn > 1
       )
    RETURNING rp.platform
)
SELECT
    platform,
    COUNT(*) AS rows_deleted
  FROM deleted_prompt_rows
 GROUP BY platform
 ORDER BY platform;

COMMIT;

-- Suggested post-run verification:
--
-- SELECT config_platforms
--   FROM geo_clients
--  WHERE id = '89b03a38-b49f-469f-80c4-8740113372fe'::uuid;
--
-- SELECT COUNT(*) AS active_physical_client_prompts,
--        COUNT(*) FILTER (WHERE is_active = FALSE) AS inactive_physical_client_prompts,
--        COUNT(DISTINCT text) AS distinct_prompt_texts,
--        COUNT(DISTINCT (topic_id::text || '|' || COALESCE(text, ''))) AS distinct_topic_prompt_texts
--   FROM geo_client_prompts
--  WHERE client_id = '89b03a38-b49f-469f-80c4-8740113372fe'::uuid;
--
-- WITH logical AS (
--     SELECT topic_id,
--            text,
--            ARRAY_AGG(platform ORDER BY platform) AS platforms,
--            COUNT(*) AS row_count
--       FROM geo_client_prompts
--      WHERE client_id = '89b03a38-b49f-469f-80c4-8740113372fe'::uuid
--        AND is_active = TRUE
--      GROUP BY topic_id, text
-- )
-- SELECT platforms::text AS platform_set,
--        COUNT(*) AS logical_prompt_count,
--        SUM(row_count) AS physical_rows
--   FROM logical
--  GROUP BY platforms
--  ORDER BY logical_prompt_count DESC, platform_set;
