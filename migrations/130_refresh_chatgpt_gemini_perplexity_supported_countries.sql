-- Migration 130: Refresh Cloro country support for ChatGPT, Gemini, and Perplexity.
--
-- Authoritative source:
--   Cloro GET /v1/countries?model=chatgpt
--   Cloro GET /v1/countries?model=gemini
--   Cloro GET /v1/countries?model=perplexity
--
-- Source snapshot date: 2026-07-21
-- Expected exact snapshots:
--   - chatgpt:   243 codes, MD5 5fd02f6f1cc1e6ae9bb31822136f3363
--   - gemini:    247 codes, MD5 ac3159df1c2899b9b1ebabc29456fda0
--   - perplexity: 249 codes, MD5 ed2012e878e3d6ee852210c9d86433f7
--
-- The three live arrays share the same order and are strict subsets of the
-- Perplexity response. To avoid duplicating nearly 750 literals, this migration
-- embeds the exact Perplexity response once and derives the other two exact
-- snapshots using the live API differences observed above:
--   - ChatGPT excludes CZ, HK, IR, MO, RU, VE.
--   - Gemini excludes BY, RU.
--
-- Scope:
--   Updates only geo_global_platforms.supported_countries for the three existing
--   platform rows. It does not modify Workspace configuration, Prompt rows,
--   historical results, or scheduler state. AI Mode and AI Overview are left
--   unchanged because Migration 128 already matches today's Cloro responses.
--
-- Safety:
--   - Aborts if a target platform row is missing or duplicated.
--   - Aborts if the embedded/derived snapshots have unexpected counts, order,
--     hashes, duplicates, or malformed codes.
--   - Replaces each array exactly, so stale codes are removed as well as newly
--     supported codes being added.
--   - Verifies exact persisted arrays before commit.
--   - Safe to re-run; updated_at changes only when an array changes.

BEGIN;

DO $$
DECLARE
    v_perplexity_countries text[] := ARRAY[
        'AD','AE','AF','AG','AI','AL','AM','AO','AQ','AR','AS','AT','AU','AW','AX','AZ',
        'BA','BB','BD','BE','BF','BG','BH','BI','BJ','BL','BM','BN','BO','BQ','BR','BS',
        'BT','BV','BW','BY','BZ','CA','CC','CD','CF','CG','CH','CI','CK','CL','CM','CO',
        'CR','CU','CV','CW','CX','CY','CZ','DE','DJ','DK','DM','DO','DZ','EC','EE','EG',
        'EH','ER','ES','ET','FI','FJ','FK','FM','FO','FR','GA','GB','GD','GE','GF','GG',
        'GH','GI','GL','GM','GN','GP','GQ','GR','GS','GT','GU','GW','GY','HK','HM','HN',
        'HR','HT','HU','ID','IE','IL','IM','IN','IO','IQ','IR','IS','IT','JE','JM','JO',
        'JP','KE','KG','KH','KI','KM','KN','KP','KR','KW','KY','KZ','LA','LB','LC','LI',
        'LK','LR','LS','LT','LU','LV','LY','MA','MC','MD','ME','MF','MG','MH','MK','ML',
        'MM','MN','MO','MP','MQ','MR','MS','MT','MU','MV','MW','MX','MY','MZ','NA','NC',
        'NE','NF','NG','NI','NL','NO','NP','NR','NU','NZ','OM','PA','PE','PF','PG','PH',
        'PK','PL','PM','PN','PR','PS','PT','PW','PY','QA','RE','RO','RS','RU','RW','SA',
        'SB','SC','SD','SE','SG','SH','SI','SJ','SK','SL','SM','SN','SO','SR','SS','ST',
        'SV','SX','SY','SZ','TC','TD','TF','TG','TH','TJ','TK','TL','TM','TN','TO','TR',
        'TT','TV','TW','TZ','UA','UG','UM','US','UY','UZ','VA','VC','VE','VG','VI','VN',
        'VU','WF','WS','XK','YE','YT','ZA','ZM','ZW'
    ]::text[];
    v_chatgpt_countries text[];
    v_gemini_countries text[];
    v_chatgpt_row_count integer;
    v_gemini_row_count integer;
    v_perplexity_row_count integer;
    v_updated_count integer;
BEGIN
    SELECT array_agg(code ORDER BY ord)
      INTO v_chatgpt_countries
      FROM unnest(v_perplexity_countries) WITH ORDINALITY AS source(code, ord)
     WHERE code <> ALL (ARRAY['CZ','HK','IR','MO','RU','VE']::text[]);

    SELECT array_agg(code ORDER BY ord)
      INTO v_gemini_countries
      FROM unnest(v_perplexity_countries) WITH ORDINALITY AS source(code, ord)
     WHERE code <> ALL (ARRAY['BY','RU']::text[]);

    SELECT COUNT(*) FILTER (WHERE platform_id = 'chatgpt'),
           COUNT(*) FILTER (WHERE platform_id = 'gemini'),
           COUNT(*) FILTER (WHERE platform_id = 'perplexity')
      INTO v_chatgpt_row_count, v_gemini_row_count, v_perplexity_row_count
      FROM geo_global_platforms
     WHERE platform_id IN ('chatgpt', 'gemini', 'perplexity');

    IF v_chatgpt_row_count <> 1
       OR v_gemini_row_count <> 1
       OR v_perplexity_row_count <> 1 THEN
        RAISE EXCEPTION
            'Abort: expected exactly one row per platform; chatgpt=%, gemini=%, perplexity=%',
            v_chatgpt_row_count,
            v_gemini_row_count,
            v_perplexity_row_count;
    END IF;

    IF cardinality(v_chatgpt_countries) <> 243
       OR (SELECT COUNT(DISTINCT code) FROM unnest(v_chatgpt_countries) AS code) <> 243
       OR md5(array_to_string(v_chatgpt_countries, ',')) <>
          '5fd02f6f1cc1e6ae9bb31822136f3363' THEN
        RAISE EXCEPTION
            'Abort: ChatGPT source snapshot failed exact verification; rows=%, unique=%, md5=%',
            cardinality(v_chatgpt_countries),
            (SELECT COUNT(DISTINCT code) FROM unnest(v_chatgpt_countries) AS code),
            md5(array_to_string(v_chatgpt_countries, ','));
    END IF;

    IF cardinality(v_gemini_countries) <> 247
       OR (SELECT COUNT(DISTINCT code) FROM unnest(v_gemini_countries) AS code) <> 247
       OR md5(array_to_string(v_gemini_countries, ',')) <>
          'ac3159df1c2899b9b1ebabc29456fda0' THEN
        RAISE EXCEPTION
            'Abort: Gemini source snapshot failed exact verification; rows=%, unique=%, md5=%',
            cardinality(v_gemini_countries),
            (SELECT COUNT(DISTINCT code) FROM unnest(v_gemini_countries) AS code),
            md5(array_to_string(v_gemini_countries, ','));
    END IF;

    IF cardinality(v_perplexity_countries) <> 249
       OR (SELECT COUNT(DISTINCT code) FROM unnest(v_perplexity_countries) AS code) <> 249
       OR md5(array_to_string(v_perplexity_countries, ',')) <>
          'ed2012e878e3d6ee852210c9d86433f7' THEN
        RAISE EXCEPTION
            'Abort: Perplexity source snapshot failed exact verification; rows=%, unique=%, md5=%',
            cardinality(v_perplexity_countries),
            (SELECT COUNT(DISTINCT code) FROM unnest(v_perplexity_countries) AS code),
            md5(array_to_string(v_perplexity_countries, ','));
    END IF;

    IF EXISTS (
        SELECT 1
          FROM unnest(
              v_chatgpt_countries || v_gemini_countries || v_perplexity_countries
          ) AS code
         WHERE code !~ '^[A-Z]{2}$'
    ) THEN
        RAISE EXCEPTION 'Abort: source snapshots contain a malformed country code';
    END IF;

    UPDATE geo_global_platforms
       SET supported_countries = CASE platform_id
               WHEN 'chatgpt' THEN v_chatgpt_countries
               WHEN 'gemini' THEN v_gemini_countries
               WHEN 'perplexity' THEN v_perplexity_countries
           END,
           updated_at = NOW()
     WHERE platform_id IN ('chatgpt', 'gemini', 'perplexity')
       AND supported_countries IS DISTINCT FROM CASE platform_id
               WHEN 'chatgpt' THEN v_chatgpt_countries
               WHEN 'gemini' THEN v_gemini_countries
               WHEN 'perplexity' THEN v_perplexity_countries
           END;

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;

    IF EXISTS (
        SELECT 1
          FROM geo_global_platforms
         WHERE (platform_id = 'chatgpt'
                AND supported_countries IS DISTINCT FROM v_chatgpt_countries)
            OR (platform_id = 'gemini'
                AND supported_countries IS DISTINCT FROM v_gemini_countries)
            OR (platform_id = 'perplexity'
                AND supported_countries IS DISTINCT FROM v_perplexity_countries)
    ) THEN
        RAISE EXCEPTION 'Abort: persisted supported_countries failed final verification';
    END IF;

    RAISE NOTICE
        'Global Platform country support verified: updated_rows=%, chatgpt=%, gemini=%, perplexity=%',
        v_updated_count,
        cardinality(v_chatgpt_countries),
        cardinality(v_gemini_countries),
        cardinality(v_perplexity_countries);
END
$$;

COMMIT;

-- Post-run verification:
--
-- SELECT platform_id,
--        display_name,
--        is_active,
--        cardinality(supported_countries) AS supported_country_count,
--        md5(array_to_string(supported_countries, ',')) AS country_snapshot_md5
--   FROM geo_global_platforms
--  WHERE platform_id IN ('chatgpt','gemini','perplexity','aimode','aioverview')
--  ORDER BY platform_id;
