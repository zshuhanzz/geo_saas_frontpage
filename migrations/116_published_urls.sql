-- 116_published_urls.sql
-- Published Pages / Published URL Tracking.
--
-- This migration is intentionally additive. It creates customer-scoped
-- Published URL assets and their explicit workspace topic associations.
-- Run manually in Cloud SQL after review.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS geo_published_urls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    published_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    published_at DATE NOT NULL,
    channel TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'approved',
    publish_status TEXT NOT NULL DEFAULT 'published',
    draft_doc_url TEXT,
    owner_name TEXT,
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID,
    updated_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT geo_published_urls_required_text CHECK (
        btrim(title) <> ''
        AND btrim(published_url) <> ''
        AND btrim(normalized_url) <> ''
        AND btrim(channel) <> ''
    ),
    CONSTRAINT geo_published_urls_review_status_check CHECK (
        review_status IN ('not_submitted', 'in_review', 'approved', 'changes_requested', 'rejected')
    ),
    CONSTRAINT geo_published_urls_publish_status_check CHECK (
        publish_status IN ('draft', 'scheduled', 'published', 'offline')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_published_urls_client_normalized_url
    ON geo_published_urls (client_id, normalized_url);

CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_published_urls_client_id_id
    ON geo_published_urls (client_id, id);

CREATE INDEX IF NOT EXISTS idx_geo_published_urls_client_published_at
    ON geo_published_urls (client_id, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_geo_published_urls_client_publish_status
    ON geo_published_urls (client_id, publish_status);

CREATE INDEX IF NOT EXISTS idx_geo_published_urls_client_active_publish_status_published_at
    ON geo_published_urls (client_id, is_active, publish_status, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_geo_published_urls_client_channel
    ON geo_published_urls (client_id, channel);

CREATE INDEX IF NOT EXISTS idx_geo_published_urls_client_active
    ON geo_published_urls (client_id, is_active);

CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_client_topics_client_id_id
    ON geo_client_topics (client_id, id);

CREATE TABLE IF NOT EXISTS geo_published_url_topics (
    client_id UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    published_url_id UUID NOT NULL,
    topic_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (client_id, published_url_id, topic_id),
    CONSTRAINT fk_geo_published_url_topics_url_client
        FOREIGN KEY (client_id, published_url_id)
        REFERENCES geo_published_urls(client_id, id)
        ON DELETE CASCADE,
    CONSTRAINT fk_geo_published_url_topics_topic_client
        FOREIGN KEY (client_id, topic_id)
        REFERENCES geo_client_topics(client_id, id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_geo_published_url_topics_client_topic
    ON geo_published_url_topics (client_id, topic_id);

CREATE INDEX IF NOT EXISTS idx_geo_published_url_topics_client_url
    ON geo_published_url_topics (client_id, published_url_id);
