-- =============================================================
-- Migration 005: Add Sentiment Analysis Tables
-- Run: psql $DATABASE_URL -f migrations/005_add_sentiment.sql
-- =============================================================

-- 1. geo_sentiment_results: Overall sentiment label per geo_result (one Cloro call)
CREATE TABLE IF NOT EXISTS geo_sentiment_results (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_prompt_id UUID NOT NULL,
    task_id          UUID,
    result_id        INTEGER NOT NULL,
    client_id        UUID NOT NULL,
    sentiment        TEXT NOT NULL CHECK (sentiment IN ('Positive', 'Negative')),
    confidence       FLOAT,
    executed_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_sentiment_results_client
    ON geo_sentiment_results (client_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_geo_sentiment_results_result
    ON geo_sentiment_results (result_id);

-- 2. geo_sentiment_themes: Extracted themes per geo_result (multiple per result)
CREATE TABLE IF NOT EXISTS geo_sentiment_themes (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_prompt_id UUID NOT NULL,
    task_id          UUID,
    result_id        INTEGER NOT NULL,
    client_id        UUID NOT NULL,
    theme_name       TEXT NOT NULL,   -- Normalized via theme dictionary
    sentiment        TEXT NOT NULL CHECK (sentiment IN ('Positive', 'Negative')),
    excerpt          TEXT,            -- Relevant sentence from raw AI text
    executed_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_sentiment_themes_client
    ON geo_sentiment_themes (client_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_geo_sentiment_themes_theme
    ON geo_sentiment_themes (theme_name);
CREATE INDEX IF NOT EXISTS idx_geo_sentiment_themes_result
    ON geo_sentiment_themes (result_id);

-- 3. geo_sentiment_theme_dictionary: Persistent, cross-client theme vocabulary
--    Themes extracted by Gemini (Phase A) are normalized here in Phase B.
--    Industry field scopes the vocabulary so irrelevant themes aren't loaded.
CREATE TABLE IF NOT EXISTS geo_sentiment_theme_dictionary (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    theme_name   TEXT NOT NULL UNIQUE,
    industry     TEXT,                -- e.g. 'Consumer Electronics', 'Retail', 'SaaS'
    created_by   TEXT DEFAULT 'gemini' CHECK (created_by IN ('gemini', 'manual')),
    description  TEXT,               -- Optional context about the theme
    usage_count  INTEGER DEFAULT 0,  -- How many times this theme has been extracted
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geo_sentiment_theme_dict_industry
    ON geo_sentiment_theme_dictionary (industry);

-- 4. Add sentiment_model_id to global settings (batch size is hardcoded in analyzer at 15)
INSERT INTO geo_global_settings (key, value, description)
VALUES
    ('sentiment_model_id', 'gemini-3-flash-preview',
     'Vertex AI model used by the Analyzer Sentiment Parser')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

