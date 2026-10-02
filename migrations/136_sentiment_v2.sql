-- Migration 136: Sentiment V2 four-state classification and verified product ownership
--
-- Deployment order:
--   1. Apply this migration.
--   2. Deploy geo_analyzer, geo_saas, and geo_agent.
--
-- Historical sentiment rows are intentionally left untouched. Their new
-- traceability columns remain NULL; only new Analyzer writes use V2.

BEGIN;

ALTER TABLE geo_sentiment_results
    DROP CONSTRAINT IF EXISTS geo_sentiment_results_sentiment_check;

ALTER TABLE geo_sentiment_results
    ADD CONSTRAINT geo_sentiment_results_sentiment_check
    CHECK (sentiment IN (
        'Positive',
        'Mixed/Neutral',
        'Negative',
        'Insufficient Evidence'
    )) NOT VALID;

ALTER TABLE geo_sentiment_results
    VALIDATE CONSTRAINT geo_sentiment_results_sentiment_check;

ALTER TABLE geo_sentiment_themes
    DROP CONSTRAINT IF EXISTS geo_sentiment_themes_sentiment_check;

ALTER TABLE geo_sentiment_themes
    ADD CONSTRAINT geo_sentiment_themes_sentiment_check
    CHECK (sentiment IN ('Positive', 'Mixed/Neutral', 'Negative')) NOT VALID;

ALTER TABLE geo_sentiment_themes
    VALIDATE CONSTRAINT geo_sentiment_themes_sentiment_check;

ALTER TABLE geo_sentiment_results
    ADD COLUMN IF NOT EXISTS classifier_version TEXT,
    ADD COLUMN IF NOT EXISTS model_id TEXT,
    ADD COLUMN IF NOT EXISTS reason_code TEXT,
    ADD COLUMN IF NOT EXISTS evidence JSONB;

ALTER TABLE geo_sentiment_results
    DROP CONSTRAINT IF EXISTS geo_sentiment_results_evidence_array_check;

ALTER TABLE geo_sentiment_results
    ADD CONSTRAINT geo_sentiment_results_evidence_array_check
    CHECK (evidence IS NULL OR jsonb_typeof(evidence) = 'array') NOT VALID;

ALTER TABLE geo_sentiment_results
    VALIDATE CONSTRAINT geo_sentiment_results_evidence_array_check;

-- Historical rows remain untouched. Only V2 writes are unique per Workspace
-- and source result, making retries idempotent without rewriting V1 history.
CREATE UNIQUE INDEX IF NOT EXISTS uq_geo_sentiment_results_v2_client_result
    ON geo_sentiment_results (client_id, result_id)
    WHERE classifier_version = 'sentiment-v2';

COMMENT ON COLUMN geo_sentiment_results.classifier_version IS
    'Classifier contract version. NULL denotes pre-versioned historical rows; new four-state rows are sentiment-v2.';
COMMENT ON COLUMN geo_sentiment_results.model_id IS
    'Resolved model identifier used for this classification.';
COMMENT ON COLUMN geo_sentiment_results.reason_code IS
    'Stable high-level explanation code emitted by the sentiment classifier.';
COMMENT ON COLUMN geo_sentiment_results.evidence IS
    'Validated verbatim evidence excerpts used to support the overall label.';

-- The original v1.2 constraint prohibited owner_brand_id for own products.
-- V2 allows an own product to be explicitly bound to an active non-shadow
-- client brand. Unbound legacy products remain valid but are excluded from
-- sentiment matching until an operator verifies their ownership.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM geo_client_topic_products product
        LEFT JOIN geo_client_topics topic ON topic.id = product.topic_id
        WHERE topic.id IS NULL OR topic.client_id <> product.client_id
    ) THEN
        RAISE EXCEPTION 'Migration 136 preflight failed: product Topic belongs to another Workspace';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM geo_client_topic_products product
        LEFT JOIN geo_client_brands brand ON brand.id = product.owner_brand_id
        WHERE product.owner_brand_id IS NOT NULL
          AND (
              brand.id IS NULL
              OR brand.client_id <> product.client_id
              OR (product.product_role = 'own' AND brand.is_shadow = TRUE)
              OR (product.product_role = 'shadow_brand_product' AND brand.is_shadow = FALSE)
              OR (product.is_active = TRUE AND brand.is_active = FALSE)
          )
    ) THEN
        RAISE EXCEPTION 'Migration 136 preflight failed: product Brand ownership is cross-Workspace, inactive, or role-mismatched';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM geo_client_topic_products product
        LEFT JOIN geo_client_peers peer ON peer.id = product.owner_peer_id
        WHERE product.owner_peer_id IS NOT NULL
          AND (peer.id IS NULL OR peer.client_id <> product.client_id)
    ) THEN
        RAISE EXCEPTION 'Migration 136 preflight failed: product Peer belongs to another Workspace';
    END IF;
END;
$$;

ALTER TABLE geo_client_topic_products
    DROP CONSTRAINT IF EXISTS product_role_owner_consistency;

ALTER TABLE geo_client_topic_products
    ADD CONSTRAINT product_role_owner_consistency CHECK (
        (product_role = 'own'
            AND owner_peer_id IS NULL
            AND shadow_sub_role IS NULL)
     OR (product_role = 'shadow_brand_product'
            AND owner_brand_id IS NOT NULL
            AND (shadow_sub_role = 'resale' OR owner_peer_id IS NULL))
     OR (product_role = 'peer'
            AND owner_peer_id IS NOT NULL
            AND owner_brand_id IS NULL
            AND shadow_sub_role IS NULL)
    ) NOT VALID;

ALTER TABLE geo_client_topic_products
    VALIDATE CONSTRAINT product_role_owner_consistency;

-- Cross-table ownership cannot be expressed by a CHECK constraint. Reject
-- cross-Workspace topic/owner IDs and Own-vs-Shadow role mismatches at the
-- database boundary as well as in the SaaS API and Analyzer read path.
CREATE OR REPLACE FUNCTION validate_geo_topic_product_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    topic geo_client_topics%ROWTYPE;
    brand geo_client_brands%ROWTYPE;
    peer geo_client_peers%ROWTYPE;
BEGIN
    SELECT * INTO topic
    FROM geo_client_topics
    WHERE id = NEW.topic_id
    FOR SHARE;

    IF NOT FOUND OR NOT (topic.client_id = NEW.client_id) THEN
        RAISE EXCEPTION 'topic_id must belong to the same Workspace as the product';
    END IF;
    IF NEW.product_role IN ('own', 'shadow_brand_product') THEN
        IF NEW.owner_brand_id IS NULL THEN
            IF NEW.product_role = 'shadow_brand_product' THEN
                RAISE EXCEPTION 'shadow_brand_product requires owner_brand_id';
            END IF;
        ELSE
            SELECT * INTO brand
            FROM geo_client_brands
            WHERE id = NEW.owner_brand_id
            FOR SHARE;

            IF NOT FOUND OR NOT (brand.client_id = NEW.client_id) THEN
                RAISE EXCEPTION 'owner_brand_id must belong to the same Workspace as the product';
            END IF;
            IF NEW.is_active AND NOT brand.is_active THEN
                RAISE EXCEPTION 'owner_brand_id must reference an active Brand';
            END IF;
            IF NEW.product_role = 'own' AND brand.is_shadow = TRUE THEN
                RAISE EXCEPTION 'Own product must reference an Own Brand';
            END IF;
            IF NEW.product_role = 'shadow_brand_product' AND brand.is_shadow = FALSE THEN
                RAISE EXCEPTION 'Shadow product must reference a Shadow Brand';
            END IF;
        END IF;
    END IF;

    IF NEW.owner_peer_id IS NOT NULL THEN
        SELECT * INTO peer
        FROM geo_client_peers
        WHERE id = NEW.owner_peer_id
        FOR SHARE;

        IF NOT FOUND OR NOT (peer.client_id = NEW.client_id) THEN
            RAISE EXCEPTION 'owner_peer_id must belong to the same Workspace as the product';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_geo_topic_product_scope
    ON geo_client_topic_products;
CREATE TRIGGER trg_geo_topic_product_scope
BEFORE INSERT OR UPDATE OF client_id, topic_id, product_role, owner_brand_id, owner_peer_id, is_active
ON geo_client_topic_products
FOR EACH ROW
EXECUTE FUNCTION validate_geo_topic_product_scope();

-- Enforce the same ownership invariant in the reverse direction. Without
-- this guard, a direct Brand update could leave an active product pointing at
-- an inactive Brand even though product writes themselves are validated.
CREATE OR REPLACE FUNCTION validate_geo_brand_deactivation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.client_id IS DISTINCT FROM OLD.client_id THEN
        RAISE EXCEPTION 'A Brand cannot be moved between Workspaces';
    END IF;

    IF (NEW.is_active = FALSE OR NEW.is_shadow IS DISTINCT FROM OLD.is_shadow)
       AND EXISTS (
           SELECT 1
           FROM geo_client_topic_products p
           WHERE p.owner_brand_id = NEW.id
             AND p.client_id = NEW.client_id
             AND p.is_active = TRUE
       ) THEN
        RAISE EXCEPTION 'Deactivate or remap active products before changing the Brand state or role';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_geo_brand_deactivation
    ON geo_client_brands;
CREATE TRIGGER trg_geo_brand_deactivation
BEFORE UPDATE OF client_id, is_shadow, is_active
ON geo_client_brands
FOR EACH ROW
EXECUTE FUNCTION validate_geo_brand_deactivation();

COMMENT ON COLUMN geo_client_topic_products.owner_brand_id IS
    'Verified owning brand. Required by sentiment matching for own and shadow-brand products.';

-- Keep Anthony's database-backed NL2SQL catalog aligned with the application
-- metric semantics. Percentages for the three rated states exclude
-- Insufficient Evidence; the excluded count remains visible as coverage data.
UPDATE geo_analysis_metrics
SET description = '客户目标实体（Own Brand、Shadow Brand 及已验证产品）的 Positive / Mixed/Neutral / Negative 分布，并单独报告 Insufficient Evidence',
    calculation_hint = $metric$REFERENCE SQL:
WITH counts AS (
  SELECT sr.sentiment, COUNT(*) AS cnt
  FROM geo_sentiment_results sr
  JOIN geo_results gr ON gr.result_id = sr.result_id AND gr.client_id = sr.client_id
  JOIN geo_client_prompts cp ON cp.id = sr.client_prompt_id AND cp.client_id = sr.client_id
  JOIN geo_global_intents gi ON gi.intent_name = cp.intent
  WHERE sr.client_id = $1 AND gr.client_id = $1 AND cp.client_id = $1
    AND cp.is_active = TRUE AND gi.is_active = TRUE
    AND gi.categories @> '["Sentiment"]'::jsonb
    AND sr.executed_at BETWEEN $2 AND $3
    AND gr.platform IN ({platforms})
  GROUP BY sr.sentiment
), totals AS (
  SELECT COALESCE(SUM(cnt) FILTER (WHERE sentiment <> 'Insufficient Evidence'), 0) AS rated,
         COALESCE(SUM(cnt), 0) AS total FROM counts
)
SELECT sentiment, cnt AS count,
  CASE WHEN sentiment = 'Insufficient Evidence'
       THEN ROUND(cnt::numeric / NULLIF(total, 0) * 100, 2)
       ELSE ROUND(cnt::numeric / NULLIF(rated, 0) * 100, 2) END AS percentage,
  rated AS rated_count, total - rated AS insufficient_evidence_count
FROM counts CROSS JOIN totals ORDER BY count DESC;
CRITICAL: Positive / Mixed/Neutral / Negative 的分母只能是 rated；Insufficient Evidence 单独展示，不能并入 Mixed/Neutral。返回 Markdown 表格。$metric$,
    relevant_tables = ARRAY['geo_sentiment_results','geo_results','geo_client_prompts','geo_global_intents'],
    updated_at = NOW()
WHERE metric_name = 'sentiment_distribution';

UPDATE geo_analysis_metrics
SET description = '客户目标实体的三类有效情感占比随时间变化，并单独报告证据不足数量',
    calculation_hint = $metric$REFERENCE SQL:
SELECT DATE(sr.executed_at) AS date,
  ROUND(COUNT(*) FILTER (WHERE sr.sentiment = 'Positive')::numeric / NULLIF(COUNT(*) FILTER (WHERE sr.sentiment <> 'Insufficient Evidence'), 0) * 100, 2) AS positive_pct,
  ROUND(COUNT(*) FILTER (WHERE sr.sentiment = 'Mixed/Neutral')::numeric / NULLIF(COUNT(*) FILTER (WHERE sr.sentiment <> 'Insufficient Evidence'), 0) * 100, 2) AS mixed_neutral_pct,
  ROUND(COUNT(*) FILTER (WHERE sr.sentiment = 'Negative')::numeric / NULLIF(COUNT(*) FILTER (WHERE sr.sentiment <> 'Insufficient Evidence'), 0) * 100, 2) AS negative_pct,
  COUNT(*) FILTER (WHERE sr.sentiment = 'Insufficient Evidence') AS insufficient_evidence_count
FROM geo_sentiment_results sr
JOIN geo_results gr ON gr.result_id = sr.result_id AND gr.client_id = sr.client_id
JOIN geo_client_prompts cp ON cp.id = sr.client_prompt_id AND cp.client_id = sr.client_id
JOIN geo_global_intents gi ON gi.intent_name = cp.intent
WHERE sr.client_id = $1 AND gr.client_id = $1 AND cp.client_id = $1
  AND cp.is_active = TRUE AND gi.is_active = TRUE
  AND gi.categories @> '["Sentiment"]'::jsonb
  AND sr.executed_at BETWEEN $2 AND $3
  AND gr.platform IN ({platforms})
GROUP BY DATE(sr.executed_at) ORDER BY 1;
CRITICAL: 三类有效情感使用 rated 分母；Insufficient Evidence 不进入三类百分比。返回 Markdown 表格。$metric$,
    relevant_tables = ARRAY['geo_sentiment_results','geo_results','geo_client_prompts','geo_global_intents'],
    updated_at = NOW()
WHERE metric_name = 'sentiment_trend';

UPDATE geo_analysis_metrics
SET description = '已验证客户产品的四分类情感分布，按 Own 与 Shadow Product 区分并单独报告证据不足',
    calculation_hint = $metric$REFERENCE SQL:
SELECT pm.product_name, pm.product_role, sr.sentiment, COUNT(DISTINCT sr.id) AS count
FROM geo_sentiment_results sr
JOIN geo_product_mentions pm ON pm.result_id = sr.result_id AND pm.client_id = sr.client_id
JOIN geo_client_brands cb ON cb.id = pm.owner_brand_id
  AND cb.client_id = pm.client_id
  AND cb.is_active = TRUE
  AND (
       (pm.product_role = 'own' AND cb.is_shadow = FALSE)
    OR (pm.product_role = 'shadow_brand_product' AND cb.is_shadow = TRUE)
  )
JOIN geo_client_prompts cp ON cp.id = sr.client_prompt_id AND cp.client_id = sr.client_id
JOIN geo_global_intents gi ON gi.intent_name = cp.intent
WHERE sr.client_id = $1 AND pm.client_id = $1 AND cp.client_id = $1
  AND pm.product_role IN ('own', 'shadow_brand_product')
  AND pm.owner_brand_id IS NOT NULL
  AND cp.is_active = TRUE AND gi.is_active = TRUE
  AND gi.categories @> '["Sentiment"]'::jsonb
  AND sr.executed_at BETWEEN $2 AND $3
GROUP BY pm.product_name, pm.product_role, sr.sentiment
ORDER BY pm.product_role, pm.product_name, count DESC;
CRITICAL: 不得把 peer 产品的优缺点归因为客户情感。Own 和 Shadow Product 必须存在已验证 owner_brand_id；比例计算必须排除 Insufficient Evidence 并单独报告其数量。$metric$,
    relevant_tables = ARRAY['geo_sentiment_results','geo_product_mentions','geo_client_brands','geo_client_prompts','geo_global_intents'],
    updated_at = NOW()
WHERE metric_name = 'product_sentiment_by_role';

UPDATE geo_analysis_metrics
SET description = '客户自有及 Shadow Brand 的四分类情感分布；三类有效情感使用 rated 分母，证据不足单独报告',
    calculation_hint = $metric$REFERENCE SQL:
WITH brand_sentiment AS (
  SELECT bm.brand_name, bm.brand_role, sr.sentiment, COUNT(DISTINCT sr.id) AS cnt
  FROM geo_sentiment_results sr
  JOIN geo_results gr ON gr.result_id = sr.result_id AND gr.client_id = sr.client_id
  JOIN geo_brand_mentions bm ON bm.result_id = gr.result_id AND bm.client_id = gr.client_id
  JOIN geo_client_prompts cp ON cp.id = sr.client_prompt_id AND cp.client_id = sr.client_id
  JOIN geo_global_intents gi ON gi.intent_name = cp.intent
  WHERE sr.client_id = $1 AND gr.client_id = $1 AND bm.client_id = $1 AND cp.client_id = $1
    AND bm.brand_role IN ('own', 'shadow')
    AND cp.is_active = TRUE AND gi.is_active = TRUE
    AND gi.categories @> '["Sentiment"]'::jsonb
    AND sr.executed_at BETWEEN $2 AND $3
    AND gr.platform IN ({platforms})
  GROUP BY bm.brand_name, bm.brand_role, sr.sentiment
), rolled AS (
  SELECT brand_name, brand_role,
    SUM(cnt) FILTER (WHERE sentiment = 'Positive') AS positive_count,
    SUM(cnt) FILTER (WHERE sentiment = 'Mixed/Neutral') AS mixed_neutral_count,
    SUM(cnt) FILTER (WHERE sentiment = 'Negative') AS negative_count,
    SUM(cnt) FILTER (WHERE sentiment = 'Insufficient Evidence') AS insufficient_evidence_count,
    SUM(cnt) FILTER (WHERE sentiment <> 'Insufficient Evidence') AS rated_count
  FROM brand_sentiment GROUP BY brand_name, brand_role
)
SELECT brand_name, brand_role,
  COALESCE(positive_count, 0) AS positive_count,
  COALESCE(mixed_neutral_count, 0) AS mixed_neutral_count,
  COALESCE(negative_count, 0) AS negative_count,
  COALESCE(insufficient_evidence_count, 0) AS insufficient_evidence_count,
  COALESCE(rated_count, 0) AS rated_count,
  ROUND(COALESCE(positive_count, 0)::numeric / NULLIF(rated_count, 0) * 100, 2) AS positive_pct,
  ROUND(COALESCE(mixed_neutral_count, 0)::numeric / NULLIF(rated_count, 0) * 100, 2) AS mixed_neutral_pct,
  ROUND(COALESCE(negative_count, 0)::numeric / NULLIF(rated_count, 0) * 100, 2) AS negative_pct
FROM rolled ORDER BY brand_role, rated_count DESC;
CRITICAL: 只允许把客户目标实体的结果归因给 own/shadow brand；Positive / Mixed/Neutral / Negative 使用 rated 分母，Insufficient Evidence 单独展示。$metric$,
    relevant_tables = ARRAY['geo_sentiment_results','geo_results','geo_brand_mentions','geo_client_prompts','geo_global_intents'],
    updated_at = NOW()
WHERE metric_name = 'brand_sentiment_breakdown';

UPDATE geo_analysis_metrics
SET calculation_hint = replace(
    calculation_hint,
    'If aggregating geo_sentiment_themes, first join geo_sentiment_results sr ON sr.id = st.sentiment_result_id, then join cp from sr.client_prompt_id.',
    'If aggregating geo_sentiment_themes, join geo_client_prompts cp directly ON cp.id = st.client_prompt_id AND cp.client_id = st.client_id.'
),
    updated_at = NOW()
WHERE domain = 'sentiment'
  AND is_active = TRUE;

-- Apply the V2 contract to every active sentiment metric, including theme
-- metrics and future catalog additions that do not require a bespoke query.
UPDATE geo_analysis_metrics
SET calculation_hint = COALESCE(calculation_hint, '') || E'\nSENTIMENT V2 CONTRACT: Overall sentiment values are Positive, Mixed/Neutral, Negative, and Insufficient Evidence. Theme sentiment values are Positive, Mixed/Neutral, and Negative only. Any percentage across rated sentiment must exclude Insufficient Evidence from its denominator and report the excluded count separately. Sentiment is scoped only to verified customer target entities; never attribute peer-only evidence to the customer. Every sentiment metric must filter cp.is_active = TRUE, gi.is_active = TRUE, and gi.categories @> ''["Sentiment"]''::jsonb. For geo_sentiment_themes, join geo_client_prompts directly with cp.id = st.client_prompt_id AND cp.client_id = st.client_id. Apply the active-prompt and active-intent scope to every numerator, denominator, total CTE, and subquery.',
    relevant_tables = COALESCE(relevant_tables, ARRAY[]::text[])
        || CASE
            WHEN 'geo_client_prompts' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
            THEN ARRAY[]::text[] ELSE ARRAY['geo_client_prompts']::text[]
           END
        || CASE
            WHEN 'geo_global_intents' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
            THEN ARRAY[]::text[] ELSE ARRAY['geo_global_intents']::text[]
           END,
    updated_at = NOW()
WHERE domain = 'sentiment'
  AND is_active = TRUE
  AND (calculation_hint IS NULL OR calculation_hint NOT LIKE '%SENTIMENT V2 CONTRACT:%');

COMMIT;
