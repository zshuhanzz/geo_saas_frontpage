-- Migration 039c: Fix 039 — required_metrics path in wizard_config
--
-- 039 wrote to '{steps,metric_config,required_metrics}' but the actual
-- path is '{required_metrics}' (top-level in wizard_config).
-- See _template_contracts_stub.py line 476: wc.get("required_metrics")

-- 1. Add brand_sentiment_breakdown to 综合分析 template
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{required_metrics}',
    (
        SELECT jsonb_agg(elem)
        FROM (
            SELECT elem
            FROM jsonb_array_elements(
                wizard_config->'required_metrics'
            ) AS elem
            UNION
            SELECT '"brand_sentiment_breakdown"'::jsonb
        ) sub
    )
),
updated_at = NOW()
WHERE id = '2ce092cd-8479-4cdc-b19a-208084c9e15b'
  AND wizard_config->'required_metrics' IS NOT NULL
  AND NOT (wizard_config->'required_metrics' @> '"brand_sentiment_breakdown"');

-- 2. Add to 情感分析 template
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
    wizard_config,
    '{required_metrics}',
    (
        SELECT jsonb_agg(elem)
        FROM (
            SELECT elem
            FROM jsonb_array_elements(
                wizard_config->'required_metrics'
            ) AS elem
            UNION
            SELECT '"brand_sentiment_breakdown"'::jsonb
        ) sub
    )
),
updated_at = NOW()
WHERE name = '情感分析'
  AND wizard_config->'required_metrics' IS NOT NULL
  AND NOT (wizard_config->'required_metrics' @> '"brand_sentiment_breakdown"');

-- 3. Clean up the wrong path 039 may have created
-- (If 039 created steps.metric_config.required_metrics, remove it to avoid confusion)
-- This is safe because the pipeline never reads from that path.
UPDATE geo_report_templates
SET wizard_config = wizard_config #- '{steps,metric_config}',
    updated_at = NOW()
WHERE wizard_config->'steps'->'metric_config' IS NOT NULL;
