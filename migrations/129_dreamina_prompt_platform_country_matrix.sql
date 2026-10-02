-- Migration 129: Normalize Dreamina enabled Prompt variants to 4 platforms x 8 countries.
--
-- Verified tenant identity (queried from Cloud SQL on 2026-07-21):
--   Dreamina / b0e10518-5f70-426f-b09e-dbe025984ba1
--
-- Target enabled matrix for each of the existing 120 logical Prompts:
--   Platforms: chatgpt, gemini, aimode, aioverview
--   Countries: US, BR, MX, SG, MY, ID, PH, TH
--   Language: en-US
--
-- Current-to-target transition:
--   - Preserve the 2,400 existing active variants in the 4-platform x
--     US/BR/MX/SG/MY overlap.
--   - Deactivate 4,800 old variants: all Perplexity variants plus all variants
--     for GB/CA/FR/DE/IT/ES/JP on the four retained platforms.
--   - Insert 1,440 missing variants for ID/PH/TH on the four retained platforms.
--   - Never delete or relabel an existing Prompt variant. Historical facts keep
--     their original client_prompt_id, platform, and country identity.
--
-- Logical Prompt scope:
--   AI Image (80), AI Video (30), AI Design (10). The inactive AI Creative
--   Tools topic is not selected as a seed and remains untouched.
--
-- Dependency:
--   Run Migration 128 first. This migration aborts unless all four target
--   Global Platform rows currently allow all eight target countries.
--
-- Concurrency and safety:
--   - Takes the same tenant lifecycle and Prompt-write advisory locks used by
--     application services, preventing concurrent collection/config writes.
--   - Accepts only the verified legacy 5 x 12 state or the completed 4 x 8
--     state. Any partial or unexpected state aborts before mutation.
--   - Uses the exact UI logical key dimensions: Topic, normalized Prompt text,
--     Product, Intent, and Language. Platform/country are expansion dimensions.
--   - Reactivates an exact inactive target variant when available; otherwise
--     inserts a new UUID. It never creates a duplicate physical identity.
--   - Verifies all final counts and matrix invariants before commit.
--   - Safe to re-run; the second run performs no inserts or status changes.

BEGIN;

SET LOCAL lock_timeout = '30s';
SET LOCAL statement_timeout = '5min';

DO $$
DECLARE
    v_client_id constant uuid := 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid;
    v_client_name constant text := 'Dreamina';
    v_source_platforms constant text[] := ARRAY[
        'chatgpt','gemini','aimode','aioverview','perplexity'
    ]::text[];
    v_source_countries constant text[] := ARRAY[
        'US','GB','CA','FR','DE','IT','ES','BR','MX','SG','MY','JP'
    ]::text[];
    v_target_platforms constant text[] := ARRAY[
        'chatgpt','gemini','aimode','aioverview'
    ]::text[];
    v_target_countries constant text[] := ARRAY[
        'US','BR','MX','SG','MY','ID','PH','TH'
    ]::text[];
    v_client_count integer;
    v_client_platforms text[];
    v_client_countries text[];
    v_client_languages text[];
    v_global_platform_count integer;
    v_seed_count integer;
    v_image_count integer;
    v_video_count integer;
    v_design_count integer;
    v_other_topic_count integer;
    v_active_physical_before integer;
    v_total_physical_before integer;
    v_duplicate_target_identity_count integer;
    v_client_rows_updated integer;
    v_reactivated_count integer;
    v_inserted_count integer;
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
            'Abort: Dreamina client id/name dual match failed for %',
            v_client_id;
    END IF;

    SELECT config_platforms, config_countries, config_languages
      INTO v_client_platforms, v_client_countries, v_client_languages
      FROM geo_clients
     WHERE id = v_client_id
     FOR UPDATE;

    IF cardinality(v_client_languages) <> 1
       OR v_client_languages IS DISTINCT FROM ARRAY['en-US']::text[] THEN
        RAISE EXCEPTION
            'Abort: expected Dreamina config_languages={en-US}, found %',
            v_client_languages;
    END IF;

    IF NOT (
        (
            cardinality(v_client_platforms) = cardinality(v_source_platforms)
            AND v_client_platforms @> v_source_platforms
            AND v_source_platforms @> v_client_platforms
        )
        OR
        (
            cardinality(v_client_platforms) = cardinality(v_target_platforms)
            AND v_client_platforms @> v_target_platforms
            AND v_target_platforms @> v_client_platforms
        )
    ) THEN
        RAISE EXCEPTION
            'Abort: Dreamina config_platforms is neither the verified source nor target set: %',
            v_client_platforms;
    END IF;

    IF NOT (
        (
            cardinality(v_client_countries) = cardinality(v_source_countries)
            AND v_client_countries @> v_source_countries
            AND v_source_countries @> v_client_countries
        )
        OR
        (
            cardinality(v_client_countries) = cardinality(v_target_countries)
            AND v_client_countries @> v_target_countries
            AND v_target_countries @> v_client_countries
        )
    ) THEN
        RAISE EXCEPTION
            'Abort: Dreamina config_countries is neither the verified source nor target set: %',
            v_client_countries;
    END IF;

    SELECT COUNT(*)
      INTO v_global_platform_count
      FROM geo_global_platforms
     WHERE platform_id = ANY(v_target_platforms)
       AND is_active IS TRUE
       AND supported_countries @> v_target_countries;

    IF v_global_platform_count <> 4 THEN
        RAISE EXCEPTION
            'Abort: target Global Platforms do not all support the 8-country matrix; run Migration 128 first (valid rows=%)',
            v_global_platform_count;
    END IF;

    CREATE TEMP TABLE tmp_dreamina_prompt_seed (
        client_id uuid NOT NULL,
        topic_id uuid NOT NULL,
        text text NOT NULL,
        normalized_text text NOT NULL,
        intent text,
        normalized_intent text NOT NULL,
        product text,
        normalized_product text NOT NULL,
        language text NOT NULL,
        PRIMARY KEY (
            client_id,
            topic_id,
            normalized_text,
            normalized_product,
            normalized_intent,
            language
        )
    ) ON COMMIT DROP;

    INSERT INTO tmp_dreamina_prompt_seed (
        client_id,
        topic_id,
        text,
        normalized_text,
        intent,
        normalized_intent,
        product,
        normalized_product,
        language
    )
    SELECT DISTINCT ON (
        cp.client_id,
        cp.topic_id,
        LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')),
        LOWER(TRIM(COALESCE(cp.product, ''))),
        LOWER(TRIM(COALESCE(cp.intent, ''))),
        LOWER(TRIM(cp.language))
    )
        cp.client_id,
        cp.topic_id,
        REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g'),
        LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')),
        cp.intent,
        LOWER(TRIM(COALESCE(cp.intent, ''))),
        cp.product,
        LOWER(TRIM(COALESCE(cp.product, ''))),
        cp.language
      FROM geo_client_prompts cp
     WHERE cp.client_id = v_client_id
       AND cp.is_active = TRUE
     ORDER BY
        cp.client_id,
        cp.topic_id,
        LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')),
        LOWER(TRIM(COALESCE(cp.product, ''))),
        LOWER(TRIM(COALESCE(cp.intent, ''))),
        LOWER(TRIM(cp.language)),
        cp.created_at ASC NULLS LAST,
        cp.id ASC;

    SELECT COUNT(*)
      INTO v_seed_count
      FROM tmp_dreamina_prompt_seed;

    IF v_seed_count <> 120 THEN
        RAISE EXCEPTION
            'Abort: expected exactly 120 enabled logical Prompt seeds, found %',
            v_seed_count;
    END IF;

    SELECT
        COUNT(*) FILTER (WHERE ct.topic_name = 'AI Image'),
        COUNT(*) FILTER (WHERE ct.topic_name = 'AI Video'),
        COUNT(*) FILTER (WHERE ct.topic_name = 'AI Design'),
        COUNT(*) FILTER (
            WHERE ct.topic_name NOT IN ('AI Image','AI Video','AI Design')
        )
      INTO v_image_count, v_video_count, v_design_count, v_other_topic_count
      FROM tmp_dreamina_prompt_seed seed
      JOIN geo_client_topics ct
        ON ct.id = seed.topic_id
       AND ct.client_id = seed.client_id;

    IF v_image_count <> 80
       OR v_video_count <> 30
       OR v_design_count <> 10
       OR v_other_topic_count <> 0 THEN
        RAISE EXCEPTION
            'Abort: unexpected active Topic distribution; image=%, video=%, design=%, other=%',
            v_image_count, v_video_count, v_design_count, v_other_topic_count;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM tmp_dreamina_prompt_seed
         WHERE LOWER(TRIM(language)) <> 'en-us'
    ) THEN
        RAISE EXCEPTION 'Abort: an enabled logical Prompt does not use en-US';
    END IF;

    SELECT COUNT(*)
      INTO v_active_physical_before
      FROM geo_client_prompts
     WHERE client_id = v_client_id
       AND is_active = TRUE;

    SELECT COUNT(*)
      INTO v_total_physical_before
      FROM geo_client_prompts
     WHERE client_id = v_client_id;

    IF v_active_physical_before NOT IN (7200, 3840) THEN
        RAISE EXCEPTION
            'Abort: expected verified legacy 7200 or completed target 3840 active rows, found %',
            v_active_physical_before;
    END IF;

    IF v_total_physical_before NOT IN (14400, 15840) THEN
        RAISE EXCEPTION
            'Abort: expected verified 14400 or post-migration 15840 total rows, found %',
            v_total_physical_before;
    END IF;

    -- Verify that the pre-migration active state is a complete, duplicate-free
    -- source or target matrix before changing any row.
    IF v_active_physical_before = 7200 THEN
        IF EXISTS (
            SELECT 1
              FROM tmp_dreamina_prompt_seed seed
              CROSS JOIN unnest(v_source_platforms) AS target_platform(platform)
              CROSS JOIN unnest(v_source_countries) AS target_country(country)
              LEFT JOIN geo_client_prompts cp
                ON cp.client_id = seed.client_id
               AND cp.topic_id = seed.topic_id
               AND LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')) = seed.normalized_text
               AND LOWER(TRIM(COALESCE(cp.product, ''))) = seed.normalized_product
               AND LOWER(TRIM(COALESCE(cp.intent, ''))) = seed.normalized_intent
               AND LOWER(TRIM(cp.language)) = LOWER(TRIM(seed.language))
               AND cp.platform = target_platform.platform
               AND cp.country = target_country.country
               AND cp.is_active = TRUE
             GROUP BY
                seed.client_id,
                seed.topic_id,
                seed.normalized_text,
                seed.normalized_product,
                seed.normalized_intent,
                seed.language,
                target_platform.platform,
                target_country.country
            HAVING COUNT(cp.id) <> 1
        ) THEN
            RAISE EXCEPTION 'Abort: legacy active Prompt matrix is incomplete or duplicated';
        END IF;
    ELSE
        IF EXISTS (
            SELECT 1
              FROM tmp_dreamina_prompt_seed seed
              CROSS JOIN unnest(v_target_platforms) AS target_platform(platform)
              CROSS JOIN unnest(v_target_countries) AS target_country(country)
              LEFT JOIN geo_client_prompts cp
                ON cp.client_id = seed.client_id
               AND cp.topic_id = seed.topic_id
               AND LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')) = seed.normalized_text
               AND LOWER(TRIM(COALESCE(cp.product, ''))) = seed.normalized_product
               AND LOWER(TRIM(COALESCE(cp.intent, ''))) = seed.normalized_intent
               AND LOWER(TRIM(cp.language)) = LOWER(TRIM(seed.language))
               AND cp.platform = target_platform.platform
               AND cp.country = target_country.country
               AND cp.is_active = TRUE
             GROUP BY
                seed.client_id,
                seed.topic_id,
                seed.normalized_text,
                seed.normalized_product,
                seed.normalized_intent,
                seed.language,
                target_platform.platform,
                target_country.country
            HAVING COUNT(cp.id) <> 1
        ) THEN
            RAISE EXCEPTION 'Abort: completed target Prompt matrix is incomplete or duplicated';
        END IF;
    END IF;

    -- Across active and inactive states, there must be at most one exact row
    -- for every target physical identity. This keeps reactivation deterministic.
    SELECT COUNT(*)
      INTO v_duplicate_target_identity_count
      FROM (
          SELECT
              seed.topic_id,
              seed.normalized_text,
              seed.normalized_product,
              seed.normalized_intent,
              seed.language,
              cp.platform,
              cp.country
            FROM tmp_dreamina_prompt_seed seed
            JOIN geo_client_prompts cp
              ON cp.client_id = seed.client_id
             AND cp.topic_id = seed.topic_id
             AND LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')) = seed.normalized_text
             AND LOWER(TRIM(COALESCE(cp.product, ''))) = seed.normalized_product
             AND LOWER(TRIM(COALESCE(cp.intent, ''))) = seed.normalized_intent
             AND LOWER(TRIM(cp.language)) = LOWER(TRIM(seed.language))
           WHERE cp.platform = ANY(v_target_platforms)
             AND cp.country = ANY(v_target_countries)
           GROUP BY
              seed.topic_id,
              seed.normalized_text,
              seed.normalized_product,
              seed.normalized_intent,
              seed.language,
              cp.platform,
              cp.country
          HAVING COUNT(*) > 1
      ) duplicates;

    IF v_duplicate_target_identity_count <> 0 THEN
        RAISE EXCEPTION
            'Abort: found % duplicate target physical Prompt identities',
            v_duplicate_target_identity_count;
    END IF;

    UPDATE geo_clients
       SET config_platforms = v_target_platforms,
           config_countries = v_target_countries,
           updated_at = NOW()
     WHERE id = v_client_id
       AND (
           config_platforms IS DISTINCT FROM v_target_platforms
           OR config_countries IS DISTINCT FROM v_target_countries
       );

    GET DIAGNOSTICS v_client_rows_updated = ROW_COUNT;

    -- Reuse the exact UUID when a previous rollback left a target variant
    -- inactive. This is a status change only; no dimensions are relabelled.
    UPDATE geo_client_prompts cp
       SET is_active = TRUE,
           updated_at = NOW()
      FROM tmp_dreamina_prompt_seed seed
     WHERE cp.client_id = seed.client_id
       AND cp.topic_id = seed.topic_id
       AND LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')) = seed.normalized_text
       AND LOWER(TRIM(COALESCE(cp.product, ''))) = seed.normalized_product
       AND LOWER(TRIM(COALESCE(cp.intent, ''))) = seed.normalized_intent
       AND LOWER(TRIM(cp.language)) = LOWER(TRIM(seed.language))
       AND cp.platform = ANY(v_target_platforms)
       AND cp.country = ANY(v_target_countries)
       AND cp.is_active = FALSE;

    GET DIAGNOSTICS v_reactivated_count = ROW_COUNT;

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
        is_active,
        created_at,
        updated_at
    )
    SELECT
        gen_random_uuid(),
        seed.client_id,
        seed.topic_id,
        seed.text,
        seed.intent,
        seed.product,
        target_platform.platform,
        target_country.country,
        seed.language,
        TRUE,
        NOW(),
        NOW()
      FROM tmp_dreamina_prompt_seed seed
      CROSS JOIN unnest(v_target_platforms) AS target_platform(platform)
      CROSS JOIN unnest(v_target_countries) AS target_country(country)
     WHERE NOT EXISTS (
         SELECT 1
           FROM geo_client_prompts existing
          WHERE existing.client_id = seed.client_id
            AND existing.topic_id = seed.topic_id
            AND LOWER(REGEXP_REPLACE(TRIM(existing.text), '\s+', ' ', 'g')) = seed.normalized_text
            AND LOWER(TRIM(COALESCE(existing.product, ''))) = seed.normalized_product
            AND LOWER(TRIM(COALESCE(existing.intent, ''))) = seed.normalized_intent
            AND LOWER(TRIM(existing.language)) = LOWER(TRIM(seed.language))
            AND existing.platform = target_platform.platform
            AND existing.country = target_country.country
     );

    GET DIAGNOSTICS v_inserted_count = ROW_COUNT;

    UPDATE geo_client_prompts cp
       SET is_active = FALSE,
           updated_at = NOW()
      FROM tmp_dreamina_prompt_seed seed
     WHERE cp.client_id = seed.client_id
       AND cp.topic_id = seed.topic_id
       AND LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')) = seed.normalized_text
       AND LOWER(TRIM(COALESCE(cp.product, ''))) = seed.normalized_product
       AND LOWER(TRIM(COALESCE(cp.intent, ''))) = seed.normalized_intent
       AND LOWER(TRIM(cp.language)) = LOWER(TRIM(seed.language))
       AND cp.is_active = TRUE
       AND (
           cp.platform <> ALL(v_target_platforms)
           OR cp.country <> ALL(v_target_countries)
       );

    GET DIAGNOSTICS v_deactivated_count = ROW_COUNT;

    SELECT COUNT(*), COUNT(DISTINCT (topic_id, text))
      INTO v_active_physical_after, v_active_logical_after
      FROM geo_client_prompts
     WHERE client_id = v_client_id
       AND is_active = TRUE;

    SELECT COUNT(*)
      INTO v_total_physical_after
      FROM geo_client_prompts
     WHERE client_id = v_client_id;

    IF v_active_physical_after <> 3840 OR v_active_logical_after <> 120 THEN
        RAISE EXCEPTION
            'Abort: expected final 3840 active physical / 120 logical Prompts, found % / %',
            v_active_physical_after, v_active_logical_after;
    END IF;

    IF v_total_physical_after <> v_total_physical_before + v_inserted_count THEN
        RAISE EXCEPTION
            'Abort: no-delete invariant failed; before=%, inserted=%, after=%',
            v_total_physical_before, v_inserted_count, v_total_physical_after;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM geo_client_prompts cp
         WHERE cp.client_id = v_client_id
           AND cp.is_active = TRUE
           AND (
               cp.platform <> ALL(v_target_platforms)
               OR cp.country <> ALL(v_target_countries)
               OR LOWER(TRIM(cp.language)) <> 'en-us'
           )
    ) THEN
        RAISE EXCEPTION 'Abort: final active set contains an excluded dimension';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM tmp_dreamina_prompt_seed seed
          CROSS JOIN unnest(v_target_platforms) AS target_platform(platform)
          CROSS JOIN unnest(v_target_countries) AS target_country(country)
          LEFT JOIN geo_client_prompts cp
            ON cp.client_id = seed.client_id
           AND cp.topic_id = seed.topic_id
           AND LOWER(REGEXP_REPLACE(TRIM(cp.text), '\s+', ' ', 'g')) = seed.normalized_text
           AND LOWER(TRIM(COALESCE(cp.product, ''))) = seed.normalized_product
           AND LOWER(TRIM(COALESCE(cp.intent, ''))) = seed.normalized_intent
           AND LOWER(TRIM(cp.language)) = LOWER(TRIM(seed.language))
           AND cp.platform = target_platform.platform
           AND cp.country = target_country.country
           AND cp.is_active = TRUE
         GROUP BY
            seed.client_id,
            seed.topic_id,
            seed.normalized_text,
            seed.normalized_product,
            seed.normalized_intent,
            seed.language,
            target_platform.platform,
            target_country.country
        HAVING COUNT(cp.id) <> 1
    ) THEN
        RAISE EXCEPTION 'Abort: final 4-platform x 8-country matrix is incomplete or duplicated';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM geo_clients
         WHERE id = v_client_id
           AND (
               config_platforms IS DISTINCT FROM v_target_platforms
               OR config_countries IS DISTINCT FROM v_target_countries
               OR config_languages IS DISTINCT FROM ARRAY['en-US']::text[]
           )
    ) THEN
        RAISE EXCEPTION 'Abort: final Dreamina client configuration verification failed';
    END IF;

    RAISE NOTICE
        'Dreamina matrix verified: client_updated=%, reactivated=%, inserted=%, deactivated=%, active_physical=%, active_logical=%, total_physical=%',
        v_client_rows_updated,
        v_reactivated_count,
        v_inserted_count,
        v_deactivated_count,
        v_active_physical_after,
        v_active_logical_after,
        v_total_physical_after;
END
$$;

COMMIT;

-- Expected first-run NOTICE against the verified 2026-07-21 state:
--   client_updated=1, reactivated=0, inserted=1440, deactivated=4800,
--   active_physical=3840, active_logical=120, total_physical=15840
--
-- Expected second-run NOTICE:
--   client_updated=0, reactivated=0, inserted=0, deactivated=0,
--   active_physical=3840, active_logical=120, total_physical=15840
--
-- Post-run verification:
--
-- SELECT config_platforms, config_countries, config_languages
--   FROM geo_clients
--  WHERE id = 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid;
--
-- SELECT ct.topic_name,
--        cp.is_active,
--        COUNT(*) AS physical_rows,
--        COUNT(DISTINCT (cp.topic_id, cp.text)) AS logical_prompts,
--        ARRAY_AGG(DISTINCT cp.platform ORDER BY cp.platform) AS platforms,
--        ARRAY_AGG(DISTINCT cp.country ORDER BY cp.country) AS countries
--   FROM geo_client_prompts cp
--   JOIN geo_client_topics ct
--     ON ct.id = cp.topic_id
--    AND ct.client_id = cp.client_id
--  WHERE cp.client_id = 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid
--  GROUP BY ct.topic_name, cp.is_active
--  ORDER BY cp.is_active DESC, ct.topic_name;
--
-- Full rollback semantics (do not run after new logical Prompts are added):
--   1. Take the same lifecycle and prompt-write advisory locks in one transaction.
--   2. Verify the active logical Prompt count/topic distribution is still 120/80/30/10.
--   3. Restore config_platforms to chatgpt/gemini/aimode/aioverview/perplexity.
--   4. Restore config_countries to US/GB/CA/FR/DE/IT/ES/BR/MX/SG/MY/JP.
--   5. Reactivate the original 5 x 12 variants for AI Image/Video/Design.
--   6. Deactivate the added ID/PH/TH variants; do not delete them.
