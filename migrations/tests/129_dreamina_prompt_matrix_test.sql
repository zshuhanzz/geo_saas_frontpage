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

CREATE TEMP TABLE geo_global_platforms (
    id uuid PRIMARY KEY,
    platform_id text NOT NULL UNIQUE,
    display_name text NOT NULL,
    supported_countries text[],
    is_active boolean,
    updated_at timestamptz
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
VALUES (
    'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid,
    'Dreamina',
    ARRAY['chatgpt','gemini','aimode','aioverview','perplexity']::text[],
    ARRAY['US','GB','CA','FR','DE','IT','ES','BR','MX','SG','MY','JP']::text[],
    ARRAY['en-US']::text[],
    NOW()
);

INSERT INTO geo_client_topics (id, client_id, topic_name)
VALUES
    ('00000000-0000-0000-0000-000000000001'::uuid, 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid, 'AI Image'),
    ('00000000-0000-0000-0000-000000000002'::uuid, 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid, 'AI Video'),
    ('00000000-0000-0000-0000-000000000003'::uuid, 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid, 'AI Design'),
    ('00000000-0000-0000-0000-000000000004'::uuid, 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid, 'AI Creative Tools');

INSERT INTO geo_global_platforms (
    id,
    platform_id,
    display_name,
    supported_countries,
    is_active,
    updated_at
)
SELECT
    gen_random_uuid(),
    platform_id,
    display_name,
    ARRAY['US','BR','MX','SG','MY','ID','PH','TH']::text[],
    TRUE,
    NOW()
FROM (
    VALUES
        ('chatgpt', 'ChatGPT'),
        ('gemini', 'Gemini'),
        ('aimode', 'Google AI Mode'),
        ('aioverview', 'AI Overview')
) AS platforms(platform_id, display_name);

WITH logical_prompts AS (
    SELECT
        n,
        CASE
            WHEN n <= 80 THEN '00000000-0000-0000-0000-000000000001'::uuid
            WHEN n <= 110 THEN '00000000-0000-0000-0000-000000000002'::uuid
            ELSE '00000000-0000-0000-0000-000000000003'::uuid
        END AS topic_id,
        format('Enabled Dreamina Prompt %s', n) AS prompt_text
    FROM generate_series(1, 120) AS n
),
platforms(platform) AS (
    VALUES ('chatgpt'), ('gemini'), ('aimode'), ('aioverview'), ('perplexity')
),
countries(country) AS (
    VALUES ('US'), ('GB'), ('CA'), ('FR'), ('DE'), ('IT'),
           ('ES'), ('BR'), ('MX'), ('SG'), ('MY'), ('JP')
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
    'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid,
    lp.topic_id,
    lp.prompt_text,
    'Solution Discovery',
    'Dreamina',
    p.platform,
    c.country,
    'en-US',
    TRUE,
    NOW(),
    NOW()
FROM logical_prompts lp
CROSS JOIN platforms p
CROSS JOIN countries c;

WITH logical_prompts AS (
    SELECT
        n,
        format('Inactive Creative Prompt %s', n) AS prompt_text
    FROM generate_series(1, 120) AS n
),
platforms(platform) AS (
    VALUES ('chatgpt'), ('gemini'), ('aimode'), ('aioverview'), ('perplexity')
),
countries(country) AS (
    VALUES ('US'), ('GB'), ('CA'), ('FR'), ('DE'), ('IT'),
           ('ES'), ('BR'), ('MX'), ('SG'), ('MY'), ('JP')
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
    'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid,
    '00000000-0000-0000-0000-000000000004'::uuid,
    lp.prompt_text,
    'Solution Discovery',
    'Dreamina',
    p.platform,
    c.country,
    'en-US',
    FALSE,
    NOW(),
    NOW()
FROM logical_prompts lp
CROSS JOIN platforms p
CROSS JOIN countries c;

\ir ../129_dreamina_prompt_platform_country_matrix.sql
\ir ../129_dreamina_prompt_platform_country_matrix.sql

DO $$
DECLARE
    v_client_id constant uuid := 'b0e10518-5f70-426f-b09e-dbe025984ba1'::uuid;
    v_active_physical integer;
    v_active_logical integer;
    v_total_physical integer;
    v_excluded_inactive integer;
    v_creative_inactive integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM geo_clients
         WHERE id = v_client_id
           AND config_platforms = ARRAY['chatgpt','gemini','aimode','aioverview']::text[]
           AND config_countries = ARRAY['US','BR','MX','SG','MY','ID','PH','TH']::text[]
           AND config_languages = ARRAY['en-US']::text[]
    ) THEN
        RAISE EXCEPTION 'Test failed: Dreamina client configuration is not canonical';
    END IF;

    SELECT COUNT(*), COUNT(DISTINCT (topic_id, text))
      INTO v_active_physical, v_active_logical
      FROM geo_client_prompts
     WHERE client_id = v_client_id
       AND is_active = TRUE;

    IF v_active_physical <> 3840 OR v_active_logical <> 120 THEN
        RAISE EXCEPTION
            'Test failed: expected 3840 active physical / 120 logical, found % / %',
            v_active_physical, v_active_logical;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM geo_client_prompts
         WHERE client_id = v_client_id
           AND is_active = TRUE
           AND (
               platform NOT IN ('aimode','aioverview','chatgpt','gemini')
               OR country NOT IN ('BR','ID','MX','MY','PH','SG','TH','US')
               OR language <> 'en-US'
           )
    ) THEN
        RAISE EXCEPTION 'Test failed: active Prompt contains an excluded dimension';
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
                  COUNT(DISTINCT platform) AS platforms,
                  COUNT(DISTINCT country) AS countries
              FROM geo_client_prompts
              WHERE client_id = v_client_id
                AND is_active = TRUE
              GROUP BY topic_id, text, COALESCE(product, ''), COALESCE(intent, ''), language
          ) grouped
         WHERE variants <> 32 OR platforms <> 4 OR countries <> 8
    ) THEN
        RAISE EXCEPTION 'Test failed: an active logical Prompt does not have the 4 x 8 matrix';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM (
              SELECT ct.topic_name,
                     COUNT(DISTINCT (cp.topic_id, cp.text)) AS logical_prompts
                FROM geo_client_prompts cp
                JOIN geo_client_topics ct
                  ON ct.id = cp.topic_id
                 AND ct.client_id = cp.client_id
               WHERE cp.client_id = v_client_id
                 AND cp.is_active = TRUE
               GROUP BY ct.topic_name
          ) topic_counts
         WHERE (topic_name = 'AI Image' AND logical_prompts <> 80)
            OR (topic_name = 'AI Video' AND logical_prompts <> 30)
            OR (topic_name = 'AI Design' AND logical_prompts <> 10)
            OR topic_name NOT IN ('AI Image','AI Video','AI Design')
    ) THEN
        RAISE EXCEPTION 'Test failed: active Topic distribution changed';
    END IF;

    SELECT COUNT(*)
      INTO v_excluded_inactive
      FROM geo_client_prompts
     WHERE client_id = v_client_id
       AND is_active = FALSE
       AND text LIKE 'Enabled Dreamina Prompt %'
       AND (
           platform = 'perplexity'
           OR country NOT IN ('BR','ID','MX','MY','PH','SG','TH','US')
       );

    IF v_excluded_inactive <> 4800 THEN
        RAISE EXCEPTION
            'Test failed: expected 4800 newly inactive old variants, found %',
            v_excluded_inactive;
    END IF;

    SELECT COUNT(*)
      INTO v_creative_inactive
      FROM geo_client_prompts cp
      JOIN geo_client_topics ct
        ON ct.id = cp.topic_id
       AND ct.client_id = cp.client_id
     WHERE cp.client_id = v_client_id
       AND ct.topic_name = 'AI Creative Tools'
       AND cp.is_active = FALSE;

    IF v_creative_inactive <> 7200 THEN
        RAISE EXCEPTION
            'Test failed: expected 7200 untouched AI Creative Tools variants, found %',
            v_creative_inactive;
    END IF;

    SELECT COUNT(*)
      INTO v_total_physical
      FROM geo_client_prompts
     WHERE client_id = v_client_id;

    IF v_total_physical <> 15840 THEN
        RAISE EXCEPTION
            'Test failed: idempotency or no-delete invariant failed; total rows=%',
            v_total_physical;
    END IF;
END
$$;
