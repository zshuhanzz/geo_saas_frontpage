-- Migration 128: Refresh Cloro country support for AI Mode and AI Overview.
--
-- Source of truth:
--   Cloro GET /v1/countries?model=aimode
--   Cloro GET /v1/countries?model=aioverview
--
-- Source snapshot date: 2026-07-21
-- Expected counts:
--   - aimode: 212 ISO-3166 alpha-2 country/territory codes
--   - aioverview: 230 ISO-3166 alpha-2 country/territory codes
--
-- Scope:
--   Updates only geo_global_platforms.supported_countries for the two existing
--   platform rows. It does not modify any Workspace configuration, Prompt row,
--   historical result, or scheduler state.
--
-- Safety:
--   - Aborts if either platform row is missing or duplicated.
--   - Aborts if the embedded source lists contain duplicates or malformed codes.
--   - Verifies exact persisted arrays before commit.
--   - Safe to re-run; updated_at changes only when the country array changes.

BEGIN;

DO $$
DECLARE
    v_aimode_countries text[] := ARRAY[
        'AD','AE','AF','AG','AI','AL','AM','AO','AQ','AR','AS','AT','AU','AW','AX','AZ',
        'BA','BB','BD','BE','BF','BG','BH','BI','BJ','BM','BN','BO','BQ','BR','BS','BT',
        'BW','BZ','CA','CC','CD','CF','CG','CH','CI','CK','CL','CM','CO','CR','CV','CW',
        'CX','CY','CZ','DE','DJ','DK','DM','DO','DZ','EC','EE','EG','ES','FI','FJ','FK',
        'FM','FO','GA','GB','GD','GE','GG','GH','GI','GL','GM','GN','GQ','GR','GS','GT',
        'GY','HK','HM','HN','HR','HT','HU','ID','IE','IL','IM','IN','IO','IQ','IT','JE',
        'JM','JO','JP','KE','KG','KH','KI','KN','KR','KW','KY','LA','LB','LC','LI','LS',
        'LT','LU','LV','LY','MA','MD','ME','MG','MH','MK','ML','MM','MN','MP','MS','MT',
        'MU','MV','MW','MX','MY','MZ','NA','NE','NF','NG','NI','NL','NO','NP','NR','NU',
        'NZ','OM','PA','PE','PG','PH','PK','PL','PN','PR','PS','PT','PW','PY','QA','RO',
        'RS','RU','RW','SA','SB','SC','SD','SE','SG','SH','SI','SJ','SK','SL','SM','SN',
        'SO','SR','SS','ST','SV','SX','TC','TD','TG','TH','TJ','TK','TL','TM','TN','TO',
        'TR','TT','TV','TW','UA','UG','UM','US','UY','UZ','VC','VE','VG','VI','VN','VU',
        'WS','ZA','ZM','ZW'
    ]::text[];
    v_aioverview_countries text[] := ARRAY[
        'AD','AE','AF','AG','AI','AL','AM','AO','AQ','AR','AS','AT','AU','AW','AX','AZ',
        'BA','BB','BD','BE','BF','BG','BH','BI','BJ','BM','BN','BO','BQ','BR','BS','BT',
        'BW','BY','BZ','CA','CC','CD','CF','CG','CH','CI','CK','CL','CM','CO','CR','CV',
        'CW','CX','CY','CZ','DE','DJ','DK','DM','DO','DZ','EC','EE','EG','EH','ER','ES',
        'FI','FJ','FK','FM','FO','GA','GB','GD','GE','GG','GH','GI','GL','GM','GN','GQ',
        'GR','GS','GT','GU','GW','GY','HK','HM','HN','HR','HT','HU','ID','IE','IL','IM',
        'IN','IO','IQ','IT','JE','JM','JO','JP','KE','KG','KH','KI','KM','KN','KP','KR',
        'KW','KY','KZ','LA','LB','LC','LI','LR','LS','LT','LU','LV','LY','MA','MC','MD',
        'ME','MG','MH','MK','ML','MM','MN','MO','MP','MR','MS','MT','MU','MV','MW','MX',
        'MY','MZ','NA','NE','NF','NG','NI','NL','NO','NP','NR','NU','NZ','OM','PA','PE',
        'PG','PH','PK','PL','PN','PR','PS','PT','PW','PY','QA','RO','RS','RU','RW','SA',
        'SB','SC','SD','SE','SG','SH','SI','SJ','SK','SL','SM','SN','SO','SR','SS','ST',
        'SV','SX','SY','SZ','TC','TD','TG','TH','TJ','TK','TL','TM','TN','TO','TR','TT',
        'TV','TW','TZ','UA','UG','UM','US','UY','UZ','VA','VC','VE','VG','VI','VN','VU',
        'WS','XK','YE','ZA','ZM','ZW'
    ]::text[];
    v_aimode_row_count integer;
    v_aioverview_row_count integer;
    v_aimode_unique_count integer;
    v_aioverview_unique_count integer;
    v_updated_count integer;
BEGIN
    SELECT COUNT(*) FILTER (WHERE platform_id = 'aimode'),
           COUNT(*) FILTER (WHERE platform_id = 'aioverview')
      INTO v_aimode_row_count, v_aioverview_row_count
      FROM geo_global_platforms
     WHERE platform_id IN ('aimode', 'aioverview');

    IF v_aimode_row_count <> 1 OR v_aioverview_row_count <> 1 THEN
        RAISE EXCEPTION
            'Abort: expected exactly one row per platform; aimode=%, aioverview=%',
            v_aimode_row_count, v_aioverview_row_count;
    END IF;

    SELECT COUNT(DISTINCT code)
      INTO v_aimode_unique_count
      FROM unnest(v_aimode_countries) AS code;

    SELECT COUNT(DISTINCT code)
      INTO v_aioverview_unique_count
      FROM unnest(v_aioverview_countries) AS code;

    IF cardinality(v_aimode_countries) <> 212
       OR v_aimode_unique_count <> 212 THEN
        RAISE EXCEPTION
            'Abort: aimode source list must contain exactly 212 unique codes; rows=%, unique=%',
            cardinality(v_aimode_countries), v_aimode_unique_count;
    END IF;

    IF cardinality(v_aioverview_countries) <> 230
       OR v_aioverview_unique_count <> 230 THEN
        RAISE EXCEPTION
            'Abort: aioverview source list must contain exactly 230 unique codes; rows=%, unique=%',
            cardinality(v_aioverview_countries), v_aioverview_unique_count;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM unnest(v_aimode_countries || v_aioverview_countries) AS code
         WHERE code !~ '^[A-Z]{2}$'
    ) THEN
        RAISE EXCEPTION 'Abort: source lists contain a malformed country code';
    END IF;

    UPDATE geo_global_platforms
       SET supported_countries = CASE platform_id
               WHEN 'aimode' THEN v_aimode_countries
               WHEN 'aioverview' THEN v_aioverview_countries
           END,
           updated_at = NOW()
     WHERE platform_id IN ('aimode', 'aioverview')
       AND supported_countries IS DISTINCT FROM CASE platform_id
               WHEN 'aimode' THEN v_aimode_countries
               WHEN 'aioverview' THEN v_aioverview_countries
           END;

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;

    IF EXISTS (
        SELECT 1
          FROM geo_global_platforms
         WHERE (platform_id = 'aimode'
                AND supported_countries IS DISTINCT FROM v_aimode_countries)
            OR (platform_id = 'aioverview'
                AND supported_countries IS DISTINCT FROM v_aioverview_countries)
    ) THEN
        RAISE EXCEPTION 'Abort: persisted supported_countries failed final verification';
    END IF;

    RAISE NOTICE
        'Global Platform country support verified: updated_rows=%, aimode=%, aioverview=%',
        v_updated_count,
        cardinality(v_aimode_countries),
        cardinality(v_aioverview_countries);
END
$$;

COMMIT;

-- Post-run verification:
--
-- SELECT platform_id,
--        display_name,
--        is_active,
--        cardinality(supported_countries) AS supported_country_count,
--        supported_countries
--   FROM geo_global_platforms
--  WHERE platform_id IN ('aimode', 'aioverview')
--  ORDER BY platform_id;
