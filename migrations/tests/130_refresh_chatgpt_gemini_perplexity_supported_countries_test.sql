\set ON_ERROR_STOP on

CREATE TEMP TABLE geo_global_platforms (
    id uuid PRIMARY KEY,
    platform_id text NOT NULL UNIQUE,
    display_name text NOT NULL,
    supported_countries text[],
    is_active boolean,
    updated_at timestamptz
);

INSERT INTO geo_global_platforms (
    id,
    platform_id,
    display_name,
    supported_countries,
    is_active,
    updated_at
)
VALUES
    (gen_random_uuid(), 'chatgpt', 'ChatGPT', ARRAY['US','CA']::text[], TRUE, NOW()),
    (gen_random_uuid(), 'gemini', 'Gemini', ARRAY['US','CA']::text[], TRUE, NOW()),
    (gen_random_uuid(), 'perplexity', 'Perplexity', ARRAY['US','CA']::text[], TRUE, NOW()),
    (gen_random_uuid(), 'aimode', 'Google AI Mode', ARRAY['US','BR']::text[], TRUE, NOW()),
    (gen_random_uuid(), 'aioverview', 'AI Overview', ARRAY['US','MX']::text[], TRUE, NOW()),
    (gen_random_uuid(), 'test-platform', 'Unrelated Platform', ARRAY['US']::text[], TRUE, NOW());

\ir ../130_refresh_chatgpt_gemini_perplexity_supported_countries.sql
\ir ../130_refresh_chatgpt_gemini_perplexity_supported_countries.sql

DO $$
DECLARE
    v_aimode_before constant text[] := ARRAY['US','BR']::text[];
    v_aioverview_before constant text[] := ARRAY['US','MX']::text[];
    v_unrelated_before constant text[] := ARRAY['US']::text[];
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM geo_global_platforms
         WHERE platform_id = 'chatgpt'
           AND cardinality(supported_countries) = 243
           AND md5(array_to_string(supported_countries, ',')) =
               '5fd02f6f1cc1e6ae9bb31822136f3363'
    ) THEN
        RAISE EXCEPTION 'Test failed: ChatGPT country snapshot is not exact';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM geo_global_platforms
         WHERE platform_id = 'gemini'
           AND cardinality(supported_countries) = 247
           AND md5(array_to_string(supported_countries, ',')) =
               'ac3159df1c2899b9b1ebabc29456fda0'
    ) THEN
        RAISE EXCEPTION 'Test failed: Gemini country snapshot is not exact';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM geo_global_platforms
         WHERE platform_id = 'perplexity'
           AND cardinality(supported_countries) = 249
           AND md5(array_to_string(supported_countries, ',')) =
               'ed2012e878e3d6ee852210c9d86433f7'
    ) THEN
        RAISE EXCEPTION 'Test failed: Perplexity country snapshot is not exact';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM geo_global_platforms
         WHERE platform_id IN ('chatgpt','gemini','perplexity')
           AND (
               cardinality(supported_countries) <>
                   (SELECT COUNT(DISTINCT code)
                      FROM unnest(supported_countries) AS code)
               OR EXISTS (
                   SELECT 1
                     FROM unnest(supported_countries) AS code
                    WHERE code !~ '^[A-Z]{2}$'
               )
           )
    ) THEN
        RAISE EXCEPTION 'Test failed: refreshed country arrays contain duplicates or malformed codes';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM geo_global_platforms
         WHERE platform_id = 'aimode'
           AND supported_countries = v_aimode_before
    ) OR NOT EXISTS (
        SELECT 1 FROM geo_global_platforms
         WHERE platform_id = 'aioverview'
           AND supported_countries = v_aioverview_before
    ) OR NOT EXISTS (
        SELECT 1 FROM geo_global_platforms
         WHERE platform_id = 'test-platform'
           AND supported_countries = v_unrelated_before
    ) THEN
        RAISE EXCEPTION 'Test failed: migration changed an out-of-scope platform';
    END IF;
END
$$;
