\set ON_ERROR_STOP on

CREATE TEMP TABLE geo_clients (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    config_platforms text[] NOT NULL,
    config_countries text[] NOT NULL,
    config_languages text[] NOT NULL,
    updated_at timestamptz
);

CREATE TEMP TABLE geo_client_topics (
    id uuid PRIMARY KEY,
    client_id uuid NOT NULL REFERENCES geo_clients(id),
    topic_name text NOT NULL
);

CREATE TEMP TABLE geo_client_prompts (
    id uuid PRIMARY KEY,
    client_id uuid NOT NULL REFERENCES geo_clients(id),
    topic_id uuid NOT NULL REFERENCES geo_client_topics(id),
    text text NOT NULL,
    intent text,
    product text,
    platform text NOT NULL,
    country text NOT NULL,
    language text NOT NULL,
    is_active boolean NOT NULL DEFAULT TRUE,
    created_at timestamptz,
    updated_at timestamptz
);

INSERT INTO geo_clients (
    id,
    name,
    config_platforms,
    config_countries,
    config_languages,
    updated_at
)
VALUES
    (
        '804456ec-b9db-4d68-9b45-ee7064459542'::uuid,
        '杭州天铭科技',
        ARRAY['chatgpt','gemini','aimode']::text[],
        ARRAY['US','AU','FR','GB','ES','DE','IT','JP','KR','MY','PL','TH','VN','TW','SG','BR','RU','TR']::text[],
        ARRAY['en-US','de-DE','en-GB','es-ES','fr-FR','ja-JP','it-IT','ko-KR','ms-MY','pt-BR','ru-RU','th-TH','tr-TR','vi-VN','zh-CN']::text[],
        NOW()
    ),
    (
        '00000000-0000-0000-0000-000000000099'::uuid,
        'Out of Scope Client',
        ARRAY['chatgpt']::text[],
        ARRAY['US','GB']::text[],
        ARRAY['en-US']::text[],
        NOW()
    );

INSERT INTO geo_client_topics (id, client_id, topic_name)
VALUES
    (
        '00000000-0000-0000-0000-000000000001'::uuid,
        '804456ec-b9db-4d68-9b45-ee7064459542'::uuid,
        'Target Topic'
    ),
    (
        '00000000-0000-0000-0000-000000000099'::uuid,
        '00000000-0000-0000-0000-000000000099'::uuid,
        'Out of Scope Topic'
    );

WITH logical_prompts AS (
    SELECT
        n,
        format('Hangzhou Tianming Prompt %s', n) AS prompt_text
    FROM generate_series(1, 34) AS n
),
platforms(platform) AS (
    VALUES ('chatgpt'), ('gemini'), ('aimode')
),
countries(country) AS (
    VALUES
        ('US'),('AU'),('FR'),('GB'),('ES'),('DE'),('IT'),('JP'),('KR'),
        ('MY'),('PL'),('TH'),('VN'),('TW'),('SG'),('BR'),('RU'),('TR')
)
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
    '804456ec-b9db-4d68-9b45-ee7064459542'::uuid,
    '00000000-0000-0000-0000-000000000001'::uuid,
    lp.prompt_text,
    'Solution Discovery',
    'Test Product',
    p.platform,
    c.country,
    'en-US',
    TRUE,
    NOW(),
    NOW()
FROM logical_prompts lp
CROSS JOIN platforms p
CROSS JOIN countries c;

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
VALUES (
    gen_random_uuid(),
    '00000000-0000-0000-0000-000000000099'::uuid,
    '00000000-0000-0000-0000-000000000099'::uuid,
    'Out of scope prompt',
    'Solution Discovery',
    'Other Product',
    'chatgpt',
    'GB',
    'en-US',
    TRUE,
    NOW(),
    NOW()
);

\ir ../131_hangzhou_tianming_us_only_prompts.sql
\ir ../131_hangzhou_tianming_us_only_prompts.sql

DO $$
DECLARE
    v_client_id constant uuid := '804456ec-b9db-4d68-9b45-ee7064459542'::uuid;
    v_expected_platforms constant text[] := ARRAY['chatgpt','gemini','aimode']::text[];
    v_expected_languages constant text[] := ARRAY[
        'en-US','de-DE','en-GB','es-ES','fr-FR','ja-JP','it-IT','ko-KR',
        'ms-MY','pt-BR','ru-RU','th-TH','tr-TR','vi-VN','zh-CN'
    ]::text[];
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM geo_clients
         WHERE id = v_client_id
           AND name = '杭州天铭科技'
           AND config_countries = ARRAY['US']::text[]
           AND config_platforms = v_expected_platforms
           AND config_languages = v_expected_languages
    ) THEN
        RAISE EXCEPTION 'Test failed: Workspace configuration is not US-only or out-of-scope fields changed';
    END IF;

    IF (SELECT COUNT(*) FROM geo_client_prompts WHERE client_id = v_client_id) <> 1836 THEN
        RAISE EXCEPTION 'Test failed: migration inserted or deleted Prompt rows';
    END IF;

    IF (SELECT COUNT(*) FROM geo_client_prompts WHERE client_id = v_client_id AND is_active) <> 102 THEN
        RAISE EXCEPTION 'Test failed: expected 102 active physical US Prompt rows';
    END IF;

    IF (
        SELECT COUNT(DISTINCT (topic_id, text, COALESCE(product, ''), COALESCE(intent, ''), language))
          FROM geo_client_prompts
         WHERE client_id = v_client_id
           AND is_active
    ) <> 34 THEN
        RAISE EXCEPTION 'Test failed: expected 34 active logical Prompts';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM geo_client_prompts
         WHERE client_id = v_client_id
           AND is_active
           AND (country <> 'US' OR language <> 'en-US')
    ) THEN
        RAISE EXCEPTION 'Test failed: an active Prompt is not US/en-US';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM (
              SELECT
                  topic_id,
                  text,
                  COALESCE(product, '') AS product,
                  COALESCE(intent, '') AS intent,
                  language,
                  COUNT(*) AS variants,
                  COUNT(DISTINCT platform) AS platforms
              FROM geo_client_prompts
              WHERE client_id = v_client_id
                AND is_active
              GROUP BY topic_id, text, COALESCE(product, ''), COALESCE(intent, ''), language
          ) grouped
         WHERE variants <> 3 OR platforms <> 3
    ) THEN
        RAISE EXCEPTION 'Test failed: an active logical Prompt does not have all three US platform variants';
    END IF;

    IF (SELECT COUNT(*) FROM geo_client_prompts WHERE client_id = v_client_id AND NOT is_active) <> 1734 THEN
        RAISE EXCEPTION 'Test failed: expected 1,734 inactive non-US Prompt rows';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM geo_clients
         WHERE id = '00000000-0000-0000-0000-000000000099'::uuid
           AND config_countries = ARRAY['US','GB']::text[]
    ) OR NOT EXISTS (
        SELECT 1
          FROM geo_client_prompts
         WHERE client_id = '00000000-0000-0000-0000-000000000099'::uuid
           AND country = 'GB'
           AND is_active
    ) THEN
        RAISE EXCEPTION 'Test failed: migration changed out-of-scope tenant data';
    END IF;
END
$$;
