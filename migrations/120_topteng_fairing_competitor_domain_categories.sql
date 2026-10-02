-- 120_topteng_fairing_competitor_domain_categories.sql
-- Correct high-confidence fairing competitor official domains for Topteng (拓腾).
--
-- Scope:
--   1. Keep the global geo_domain_categories mapping at "Owned Media" for the
--      reviewed competitor official domains.
--   2. Backfill existing Topteng citation snapshots from the two recent run
--      days, 2026-07-05 and 2026-07-06 Asia/Shanghai, for the same domains.
--
-- This migration does not change schema and does not touch unrelated clients.

BEGIN;

WITH target_client AS (
    SELECT id
      FROM geo_clients
     WHERE id = '89b03a38-b49f-469f-80c4-8740113372fe'::uuid
       AND name = '拓腾'
),
target_domains(domain) AS (
    VALUES
        ('kingsmotorcyclefairings.com'),
        ('absfairings.com'),
        ('nt-fairing.com'),
        ('mrfairing.com'),
        ('summitfairings.com')
),
upserted_domain_categories AS (
    INSERT INTO geo_domain_categories (id, domain, category, classified_by)
    SELECT gen_random_uuid(), domain, 'Owned Media', 'manual_migration_120'
      FROM target_domains
    ON CONFLICT (domain) DO UPDATE
       SET category = EXCLUDED.category,
           classified_by = EXCLUDED.classified_by
     WHERE geo_domain_categories.category IS DISTINCT FROM EXCLUDED.category
        OR geo_domain_categories.classified_by IS DISTINCT FROM EXCLUDED.classified_by
    RETURNING domain
),
updated_topteng_citations AS (
    UPDATE geo_citations c
       SET domain_category = 'Owned Media'
      FROM target_client tc
      JOIN target_domains td ON TRUE
     WHERE c.client_id = tc.id
       AND LOWER(c.source_domain) = td.domain
       AND c.executed_at >= TIMESTAMPTZ '2026-07-04 16:00:00+00' -- 2026-07-05 00:00 Asia/Shanghai
       AND c.executed_at <  TIMESTAMPTZ '2026-07-06 16:00:00+00' -- 2026-07-07 00:00 Asia/Shanghai
       AND c.domain_category IS DISTINCT FROM 'Owned Media'
    RETURNING c.source_domain
)
SELECT
    (SELECT COUNT(*) FROM upserted_domain_categories) AS domain_category_rows_upserted,
    (SELECT COUNT(*) FROM updated_topteng_citations) AS citation_rows_updated;

COMMIT;

-- Pre-run impact check used when creating this migration:
--
-- WITH target_domains(domain) AS (
--     VALUES
--         ('kingsmotorcyclefairings.com'),
--         ('absfairings.com'),
--         ('nt-fairing.com'),
--         ('mrfairing.com'),
--         ('summitfairings.com')
-- )
-- SELECT LOWER(c.source_domain) AS source_domain,
--        COALESCE(c.domain_category, '<NULL>') AS current_category,
--        COUNT(*) AS citation_rows
--   FROM geo_citations c
--   JOIN target_domains td ON LOWER(c.source_domain) = td.domain
--  WHERE c.client_id = '89b03a38-b49f-469f-80c4-8740113372fe'::uuid
--    AND c.executed_at >= TIMESTAMPTZ '2026-07-04 16:00:00+00'
--    AND c.executed_at <  TIMESTAMPTZ '2026-07-06 16:00:00+00'
--  GROUP BY LOWER(c.source_domain), COALESCE(c.domain_category, '<NULL>')
--  ORDER BY source_domain, current_category;
--
-- Expected rows to update at creation time:
--   absfairings.com                 Other -> Owned Media: 33
--   kingsmotorcyclefairings.com     Other -> Owned Media: 74
--   mrfairing.com                   Other -> Owned Media: 35
--   nt-fairing.com                  Other -> Owned Media: 30
--   summitfairings.com              Other -> Owned Media: 26
--   Total citation rows: 198
