-- 063_prompt_cascade_delete_indexes.sql
-- Speeds up Prompt cascade deletion and stale async writer guards.
-- Run manually in Cloud SQL.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_geo_results_client_prompt
    ON geo_results(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_tasks_client_prompt
    ON geo_tasks(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_brand_mentions_client_prompt
    ON geo_brand_mentions(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_product_mentions_client_prompt
    ON geo_product_mentions(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_citations_client_prompt
    ON geo_citations(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_sentiment_results_client_prompt
    ON geo_sentiment_results(client_id, client_prompt_id);

CREATE INDEX IF NOT EXISTS idx_geo_sentiment_themes_client_prompt
    ON geo_sentiment_themes(client_id, client_prompt_id);

COMMIT;
