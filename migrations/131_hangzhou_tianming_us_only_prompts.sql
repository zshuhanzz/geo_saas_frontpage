-- Migration 131: Restrict Hangzhou Tianming Technology Prompts to US only.
--
-- Verified tenant identity (queried from Cloud SQL on 2026-07-21):
--   杭州天铭科技 / 804456ec-b9db-4d68-9b45-ee7064459542
--
-- Verified source state:
--   - 34 logical Prompts.
--   - 3 platforms: chatgpt, gemini, aimode.
--   - 18 countries, including US.
--   - 1,836 active physical Prompt rows (34 x 3 x 18).
--   - Every physical Prompt row uses language en-US.
--
-- Target state:
--   - Workspace config_countries becomes exactly {US}.
--   - The existing 102 US rows remain active (34 x 3 x 1).
--   - The 1,734 non-US rows become inactive and remain stored for history and
--     rollback. No Prompt row is inserted, deleted, or relabelled.
--   - config_platforms and config_languages remain unchanged.
--   - Existing geo_tasks, geo_results, mentions, citations, sentiment, and
--     scheduler state are not modified.
--
-- Concurrency and safety:
--   - Takes the same Workspace lifecycle and Prompt-write advisory locks used
--     by application services.
--   - Accepts only the exact verified 18-country source state or the completed
--     US-only target state. A partial or unexpected matrix aborts before writes.
--   - Matches the client by both verified UUID and exact name.
--   - Verifies tenant isolation, row preservation, active logical Prompt count,
--     and the complete 3-platform US matrix before commit.
--   - Safe to re-run; the second run performs no updates.

BEGIN;

SET LOCAL lock_timeout = '30s';
SET LOCAL statement_timeout = '5min';

DO $$
DECLARE
    v_client_id constant uuid := '804456ec-b9db-4d68-9b45-ee7064459542'::uuid;
    v_client_name constant text := '杭州天铭科技';
    v_source_platforms constant text[] := ARRAY[
        'chatgpt','gemini','aimode'
    ]::text[];
    v_source_countries constant text[] := ARRAY[
        'US','AU','FR','GB','ES','DE','IT','JP','KR','MY','PL','TH','VN','TW',
        'SG','BR','RU','TR'
    ]::text[];
    v_target_countries constant text[] := ARRAY['US']::text[];
    v_client_count integer;
    v_client_platforms text[];
    v_client_countries text[];
    v_client_languages text[];
    v_active_physical_before integer;
    v_active_logical_before integer;
    v_total_physical_before integer;
    v_duplicate_identity_count integer;
    v_source_group_count integer;
    v_target_group_count integer;
    v_client_rows_updated integer;
    v_deactivated_count integer;
    v_active_physical_after integer;
    v_active_logical_after integer;
    v_total_physical_after integer;
BEGIN
    -- Match the application's lock order: Workspace lifecycle, then Prompt write.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('workspace-lifecycle:' || v_client_id::text, 0)
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended('prompt-write:' || v_client_id::text, 0)
    );

    SELECT COUNT(*)
      INTO v_client_count
      FROM geo_clients
     WHERE id = v_client_id
       AND name = v_client_name;

    IF v_client_count <> 1 THEN
        RAISE EXCEPTION
            'Abort: Hangzhou Tianming client id/name dual match failed for %',
            v_client_id;
    END IF;

    SELECT config_platforms, config_countries, config_languages
      INTO v_client_platforms, v_client_countries, v_client_languages
      FROM geo_clients
     WHERE id = v_client_id
     FOR UPDATE;

    IF cardinality(v_client_platforms) <> cardinality(v_source_platforms)
       OR NOT (v_client_platforms @> v_source_platforms)
       OR NOT (v_source_platforms @> v_client_platforms) THEN
        RAISE EXCEPTION
            'Abort: expected platforms %, found %',
            v_source_platforms,
            v_client_platforms;
    END IF;

    IF NOT (
        (
            cardinality(v_client_countries) = cardinality(v_source_countries)
            AND v_client_countries @> v_source_countries
            AND v_source_countries @> v_client_countries
        )
        OR
        v_client_countries IS NOT DISTINCT FROM v_target_countries
    ) THEN
        RAISE EXCEPTION
            'Abort: config_countries is neither the verified source nor target set: %',
            v_client_countries;
    END IF;

    IF v_client_languages IS NULL OR cardinality(v_client_languages) = 0 THEN
        RAISE EXCEPTION 'Abort: config_languages must remain populated';
    END IF;

    SELECT
        COUNT(*) FILTER (WHERE is_active),
        COUNT(DISTINCT (
            topic_id,
            LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')),
            LOWER(TRIM(COALESCE(product, ''))),
            LOWER(TRIM(COALESCE(intent, ''))),
            LOWER(TRIM(language))
        )) FILTER (WHERE is_active),
        COUNT(*)
      INTO
        v_active_physical_before,
        v_active_logical_before,
        v_total_physical_before
      FROM geo_client_prompts
     WHERE client_id = v_client_id;

    IF v_total_physical_before <> 1836
       OR v_active_logical_before <> 34
       OR v_active_physical_before NOT IN (1836, 102) THEN
        RAISE EXCEPTION
            'Abort: unexpected Prompt counts; total=%, active_physical=%, active_logical=%',
            v_total_physical_before,
            v_active_physical_before,
            v_active_logical_before;
    END IF;

    SELECT COUNT(*)
      INTO v_duplicate_identity_count
      FROM (
          SELECT
              topic_id,
              LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')) AS normalized_text,
              LOWER(TRIM(COALESCE(product, ''))) AS normalized_product,
              LOWER(TRIM(COALESCE(intent, ''))) AS normalized_intent,
              LOWER(TRIM(language)) AS normalized_language,
              platform,
              country,
              COUNT(*) AS rows_per_identity
            FROM geo_client_prompts
           WHERE client_id = v_client_id
           GROUP BY
              topic_id,
              LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')),
              LOWER(TRIM(COALESCE(product, ''))),
              LOWER(TRIM(COALESCE(intent, ''))),
              LOWER(TRIM(language)),
              platform,
              country
          HAVING COUNT(*) <> 1
      ) duplicate_groups;

    IF v_duplicate_identity_count <> 0 THEN
        RAISE EXCEPTION
            'Abort: found % duplicate Prompt physical identities',
            v_duplicate_identity_count;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM geo_client_prompts
         WHERE client_id = v_client_id
           AND (
               language <> 'en-US'
               OR platform <> ALL (v_source_platforms)
               OR country <> ALL (v_source_countries)
           )
    ) THEN
        RAISE EXCEPTION 'Abort: a physical Prompt contains an unexpected platform, country, or language';
    END IF;

    SELECT COUNT(*)
      INTO v_source_group_count
      FROM (
          SELECT
              topic_id,
              LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')) AS normalized_text,
              LOWER(TRIM(COALESCE(product, ''))) AS normalized_product,
              LOWER(TRIM(COALESCE(intent, ''))) AS normalized_intent,
              LOWER(TRIM(language)) AS normalized_language,
              COUNT(*) AS variants,
              COUNT(DISTINCT platform) AS platforms,
              COUNT(DISTINCT country) AS countries
            FROM geo_client_prompts
           WHERE client_id = v_client_id
             AND is_active
           GROUP BY
              topic_id,
              LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')),
              LOWER(TRIM(COALESCE(product, ''))),
              LOWER(TRIM(COALESCE(intent, ''))),
              LOWER(TRIM(language))
      ) grouped
     WHERE variants = 54
       AND platforms = 3
       AND countries = 18;

    SELECT COUNT(*)
      INTO v_target_group_count
      FROM (
          SELECT
              topic_id,
              LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')) AS normalized_text,
              LOWER(TRIM(COALESCE(product, ''))) AS normalized_product,
              LOWER(TRIM(COALESCE(intent, ''))) AS normalized_intent,
              LOWER(TRIM(language)) AS normalized_language,
              COUNT(*) AS variants,
              COUNT(DISTINCT platform) AS platforms,
              COUNT(DISTINCT country) AS countries,
              MIN(country) AS only_country
            FROM geo_client_prompts
           WHERE client_id = v_client_id
             AND is_active
           GROUP BY
              topic_id,
              LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')),
              LOWER(TRIM(COALESCE(product, ''))),
              LOWER(TRIM(COALESCE(intent, ''))),
              LOWER(TRIM(language))
      ) grouped
     WHERE variants = 3
       AND platforms = 3
       AND countries = 1
       AND only_country = 'US';

    IF NOT (
        (v_active_physical_before = 1836 AND v_source_group_count = 34)
        OR
        (v_active_physical_before = 102 AND v_target_group_count = 34)
    ) THEN
        RAISE EXCEPTION
            'Abort: active Prompt matrix is neither verified 3x18 source nor 3x1 target; source_groups=%, target_groups=%',
            v_source_group_count,
            v_target_group_count;
    END IF;

    UPDATE geo_clients
       SET config_countries = v_target_countries,
           updated_at = NOW()
     WHERE id = v_client_id
       AND config_countries IS DISTINCT FROM v_target_countries;

    GET DIAGNOSTICS v_client_rows_updated = ROW_COUNT;

    UPDATE geo_client_prompts
       SET is_active = FALSE,
           updated_at = NOW()
     WHERE client_id = v_client_id
       AND country <> 'US'
       AND is_active = TRUE;

    GET DIAGNOSTICS v_deactivated_count = ROW_COUNT;

    SELECT
        COUNT(*) FILTER (WHERE is_active),
        COUNT(DISTINCT (
            topic_id,
            LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')),
            LOWER(TRIM(COALESCE(product, ''))),
            LOWER(TRIM(COALESCE(intent, ''))),
            LOWER(TRIM(language))
        )) FILTER (WHERE is_active),
        COUNT(*)
      INTO
        v_active_physical_after,
        v_active_logical_after,
        v_total_physical_after
      FROM geo_client_prompts
     WHERE client_id = v_client_id;

    IF v_client_rows_updated NOT IN (0, 1)
       OR v_deactivated_count NOT IN (0, 1734)
       OR v_active_physical_after <> 102
       OR v_active_logical_after <> 34
       OR v_total_physical_after <> v_total_physical_before THEN
        RAISE EXCEPTION
            'Abort: final count verification failed; client_updates=%, deactivated=%, active_physical=%, active_logical=%, total_before=%, total_after=%',
            v_client_rows_updated,
            v_deactivated_count,
            v_active_physical_after,
            v_active_logical_after,
            v_total_physical_before,
            v_total_physical_after;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM geo_client_prompts
         WHERE client_id = v_client_id
           AND is_active
           AND (
               country <> 'US'
               OR language <> 'en-US'
               OR platform <> ALL (v_source_platforms)
           )
    ) THEN
        RAISE EXCEPTION 'Abort: final active Prompt set contains an unexpected dimension';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM (
              SELECT
                  topic_id,
                  LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')) AS normalized_text,
                  LOWER(TRIM(COALESCE(product, ''))) AS normalized_product,
                  LOWER(TRIM(COALESCE(intent, ''))) AS normalized_intent,
                  LOWER(TRIM(language)) AS normalized_language,
                  COUNT(*) AS variants,
                  COUNT(DISTINCT platform) AS platforms,
                  COUNT(DISTINCT country) AS countries,
                  MIN(country) AS only_country
                FROM geo_client_prompts
               WHERE client_id = v_client_id
                 AND is_active
               GROUP BY
                  topic_id,
                  LOWER(REGEXP_REPLACE(TRIM(text), '\s+', ' ', 'g')),
                  LOWER(TRIM(COALESCE(product, ''))),
                  LOWER(TRIM(COALESCE(intent, ''))),
                  LOWER(TRIM(language))
          ) grouped
         WHERE variants <> 3
            OR platforms <> 3
            OR countries <> 1
            OR only_country <> 'US'
    ) THEN
        RAISE EXCEPTION 'Abort: final logical Prompt matrix is not exactly 3 platforms x US';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM geo_clients
         WHERE id = v_client_id
           AND name = v_client_name
           AND config_countries = v_target_countries
           AND config_platforms = v_client_platforms
           AND config_languages = v_client_languages
    ) THEN
        RAISE EXCEPTION 'Abort: final Workspace configuration verification failed';
    END IF;

    RAISE NOTICE
        'Hangzhou Tianming US-only Prompt migration verified: client_updates=%, deactivated=%, active_physical=%, active_logical=%, total_preserved=%',
        v_client_rows_updated,
        v_deactivated_count,
        v_active_physical_after,
        v_active_logical_after,
        v_total_physical_after;
END
$$;

COMMIT;

-- Post-run verification:
--
-- SELECT id, name, config_platforms, config_countries, config_languages
--   FROM geo_clients
--  WHERE id = '804456ec-b9db-4d68-9b45-ee7064459542';
--
-- SELECT country,
--        platform,
--        is_active,
--        COUNT(*) AS physical_rows,
--        COUNT(DISTINCT (topic_id, text, COALESCE(product, ''), COALESCE(intent, ''), language)) AS logical_prompts
--   FROM geo_client_prompts
--  WHERE client_id = '804456ec-b9db-4d68-9b45-ee7064459542'
--  GROUP BY country, platform, is_active
--  ORDER BY is_active DESC, country, platform;
