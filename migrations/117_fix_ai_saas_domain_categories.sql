-- 117_fix_ai_saas_domain_categories.sql
-- Correct high-confidence AI/SaaS/tool official domains that were previously
-- classified as Agency because the classifier prompt over-weighted
-- "advertising platforms" and under-specified product official websites.
--
-- This migration is intentionally limited to domain-category data corrections:
--   1. Upsert geo_domain_categories to Owned Media for reviewed domains.
--   2. Backfill existing geo_citations snapshots for the same domains.
--
-- It does not change schema and does not touch unrelated domains.

BEGIN;

WITH target_domains(domain) AS (
    VALUES
        ('getmaxim.ai'),
        ('reelmind.ai'),
        ('adstellar.ai'),
        ('aimlapi.com'),
        ('claid.ai'),
        ('getimg.ai'),
        ('photoroom.com'),
        ('lumalabs.ai'),
        ('vizard.ai'),
        ('quickads.ai'),
        ('pictory.ai'),
        ('lumen5.com'),
        ('piktochart.com'),
        ('venngage.com'),
        ('madgicx.com'),
        ('pebblely.com'),
        ('quso.ai'),
        ('fiddl.art'),
        ('photta.app'),
        ('wavespeed.ai'),
        ('siliconflow.com'),
        ('zsky.ai'),
        ('truefan.ai'),
        ('aiorastudio.com')
),
upserted AS (
    INSERT INTO geo_domain_categories (id, domain, category, classified_by)
    SELECT gen_random_uuid(), domain, 'Owned Media', 'manual_migration_117'
      FROM target_domains
    ON CONFLICT (domain) DO UPDATE
       SET category = EXCLUDED.category,
           classified_by = EXCLUDED.classified_by
     WHERE geo_domain_categories.category IS DISTINCT FROM EXCLUDED.category
        OR geo_domain_categories.classified_by IS DISTINCT FROM EXCLUDED.classified_by
    RETURNING domain
),
updated_citations AS (
    UPDATE geo_citations c
       SET domain_category = 'Owned Media'
      FROM target_domains td
     WHERE LOWER(c.source_domain) = td.domain
       AND c.domain_category IS DISTINCT FROM 'Owned Media'
    RETURNING c.source_domain
)
SELECT
    (SELECT COUNT(*) FROM upserted) AS domain_category_rows_upserted,
    (SELECT COUNT(*) FROM updated_citations) AS citation_rows_updated;

COMMIT;

-- Optional verification after commit:
--
-- WITH target_domains(domain) AS (
--     VALUES
--         ('getmaxim.ai'), ('reelmind.ai'), ('adstellar.ai'), ('aimlapi.com'),
--         ('claid.ai'), ('getimg.ai'), ('photoroom.com'), ('lumalabs.ai'),
--         ('vizard.ai'), ('quickads.ai'), ('pictory.ai'), ('lumen5.com'),
--         ('piktochart.com'), ('venngage.com'), ('madgicx.com'), ('pebblely.com'),
--         ('quso.ai'), ('fiddl.art'), ('photta.app'), ('wavespeed.ai'),
--         ('siliconflow.com'), ('zsky.ai'), ('truefan.ai'), ('aiorastudio.com')
-- )
-- SELECT td.domain,
--        dc.category AS dimension_category,
--        COUNT(c.*) FILTER (WHERE c.domain_category = 'Owned Media') AS owned_media_citations,
--        COUNT(c.*) AS total_citations
--   FROM target_domains td
--   LEFT JOIN geo_domain_categories dc
--          ON dc.domain = td.domain
--   LEFT JOIN geo_citations c
--          ON LOWER(c.source_domain) = td.domain
--  GROUP BY td.domain, dc.category
--  ORDER BY td.domain;
