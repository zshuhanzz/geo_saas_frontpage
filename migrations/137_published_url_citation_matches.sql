-- 137_published_url_citation_matches.sql
-- Purpose: persist per-workspace user decisions for Published URL citation
-- variants without mutating or backfilling geo_citations.source_url.

BEGIN;

CREATE TABLE IF NOT EXISTS geo_published_url_citation_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL,
    published_url_id UUID NOT NULL,
    citation_url TEXT NOT NULL,
    citation_match_key TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT geo_published_url_citation_matches_required_text CHECK (
        btrim(citation_url) <> ''
        AND btrim(citation_match_key) <> ''
    ),
    CONSTRAINT geo_published_url_citation_matches_status_check CHECK (
        status IN ('confirmed', 'rejected')
    ),
    CONSTRAINT geo_published_url_citation_matches_published_url_fkey
        FOREIGN KEY (client_id, published_url_id)
        REFERENCES geo_published_urls(client_id, id)
        ON DELETE CASCADE,
    CONSTRAINT geo_published_url_citation_matches_page_key_unique
        UNIQUE (client_id, published_url_id, citation_match_key)
);

-- One semantic Citation URL can be explicitly confirmed for at most one
-- Published URL inside a workspace. Rejected candidates remain page-scoped.
CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_published_url_citation_matches_confirmed_key
    ON geo_published_url_citation_matches (client_id, citation_match_key)
    WHERE status = 'confirmed';

CREATE INDEX IF NOT EXISTS idx_geo_published_url_citation_matches_page_status
    ON geo_published_url_citation_matches (
        client_id,
        published_url_id,
        status,
        citation_match_key
    )
    INCLUDE (citation_url, updated_at);

COMMIT;

-- Rollback (manual, only after confirming no mapping data must be retained):
-- DROP TABLE geo_published_url_citation_matches;
