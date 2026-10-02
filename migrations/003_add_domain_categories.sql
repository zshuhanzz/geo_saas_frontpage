-- Migration: Add geo_domain_categories table and domain_category column to geo_citations
-- Run this against the geo_platform database before deploying the updated code.

-- Enable UUID extension if not already exists
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Add domain_category column to geo_citations
ALTER TABLE geo_citations
ADD COLUMN IF NOT EXISTS domain_category TEXT;

-- 2. Create geo_domain_categories mapping table
CREATE TABLE IF NOT EXISTS geo_domain_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    classified_by TEXT DEFAULT 'gemini',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create index on domain for fast lookups
CREATE INDEX IF NOT EXISTS idx_geo_domain_categories_domain ON geo_domain_categories (domain);

-- 4. Create index on domain_category in geo_citations for filtering
CREATE INDEX IF NOT EXISTS idx_geo_citations_domain_category ON geo_citations (domain_category);

-- 5. Seed some well-known domain categories (optional, can be managed via Admin UI)
INSERT INTO geo_domain_categories (domain, category, classified_by) VALUES
    ('youtube.com', 'Social Media', 'seed'),
    ('twitter.com', 'Social Media', 'seed'),
    ('x.com', 'Social Media', 'seed'),
    ('facebook.com', 'Social Media', 'seed'),
    ('instagram.com', 'Social Media', 'seed'),
    ('tiktok.com', 'Social Media', 'seed'),
    ('reddit.com', 'Social Media', 'seed'),
    ('quora.com', 'Social Media', 'seed'),
    ('linkedin.com', 'Social Media', 'seed'),
    ('pinterest.com', 'Social Media', 'seed')
ON CONFLICT (domain) DO NOTHING;

-- 6. Backfill: Update existing NULL domain_category using mapping table
UPDATE geo_citations c
SET domain_category = dc.category
FROM geo_domain_categories dc
WHERE LOWER(c.source_domain) = dc.domain
  AND c.domain_category IS NULL;

-- 7. Backfill: Mark owned domains
UPDATE geo_citations c
SET domain_category = 'Owned Media'
FROM geo_client_domains cd
WHERE LOWER(c.source_domain) = LOWER(cd.domain)
  AND c.client_id = cd.client_id
  AND c.domain_category IS NULL;

-- NOTE: For remaining NULL records, run the Python backfill script:
--   cd geo_analyzer && python -m scripts.backfill_domain_categories
-- This uses Gemini to classify unknown domains and updates all remaining NULLs.
