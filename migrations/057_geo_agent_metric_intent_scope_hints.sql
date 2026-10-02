-- 057_geo_agent_metric_intent_scope_hints.sql
--
-- Geo Agent analysis metrics must follow Global Config intent categories:
-- Visibility metrics only count prompts whose intent category includes Visibility;
-- Citation metrics only count prompts whose intent category includes Citation;
-- Sentiment metrics only count prompts whose intent category includes Sentiment.
--
-- This migration updates metric hints used by Geo Agent NL2SQL. It does not
-- touch analyzer raw data.

UPDATE geo_analysis_metrics
SET
  calculation_hint = CASE
    WHEN calculation_hint ILIKE '%MANDATORY GLOBAL CONFIG INTENT SCOPE%' THEN calculation_hint
    ELSE
      'MANDATORY GLOBAL CONFIG INTENT SCOPE:
- This metric is dynamically scoped by Global Config; analyzer raw rows keep all prompts.
- Before aggregating, restrict fact rows to prompts whose intent is enabled for the Citation metric.
- Join geo_client_prompts cp ON cp.id = <fact_alias>.client_prompt_id AND cp.client_id = <fact_alias>.client_id.
- If the table being aggregated does not have client_prompt_id, first join its parent fact table that does.
- Join geo_global_intents gi ON gi.intent_name = cp.intent.
- Add cp.client_id = $1, gi.is_active = true, and gi.categories @> ''["Citation"]''::jsonb.
- Apply this filter to every numerator, denominator, total CTE, and subquery in the reference SQL.
- Never fall back to all intents when no intent is configured for Citation.
'
      || E'\n'
      || COALESCE(calculation_hint, '')
  END,
  relevant_tables = COALESCE(relevant_tables, ARRAY[]::text[])
    || CASE
      WHEN 'geo_client_prompts' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_client_prompts']::text[]
    END
    || CASE
      WHEN 'geo_global_intents' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_global_intents']::text[]
    END
WHERE is_active = TRUE
  AND domain = 'citation';

UPDATE geo_analysis_metrics
SET
  calculation_hint = CASE
    WHEN calculation_hint ILIKE '%MANDATORY GLOBAL CONFIG INTENT SCOPE%' THEN calculation_hint
    ELSE
      'MANDATORY GLOBAL CONFIG INTENT SCOPE:
- This metric is dynamically scoped by Global Config; analyzer raw rows keep all prompts.
- Before aggregating, restrict fact rows to prompts whose intent is enabled for the Sentiment metric.
- Join geo_client_prompts cp ON cp.id = <fact_alias>.client_prompt_id AND cp.client_id = <fact_alias>.client_id.
- If aggregating geo_sentiment_themes, first join geo_sentiment_results sr ON sr.id = st.sentiment_result_id, then join cp from sr.client_prompt_id.
- Join geo_global_intents gi ON gi.intent_name = cp.intent.
- Add cp.client_id = $1, gi.is_active = true, and gi.categories @> ''["Sentiment"]''::jsonb.
- Apply this filter to every numerator, denominator, total CTE, and subquery in the reference SQL.
- Never fall back to all intents when no intent is configured for Sentiment.
'
      || E'\n'
      || COALESCE(calculation_hint, '')
  END,
  relevant_tables = COALESCE(relevant_tables, ARRAY[]::text[])
    || CASE
      WHEN 'geo_client_prompts' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_client_prompts']::text[]
    END
    || CASE
      WHEN 'geo_global_intents' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_global_intents']::text[]
    END
WHERE is_active = TRUE
  AND domain = 'sentiment';

UPDATE geo_analysis_metrics
SET
  calculation_hint = CASE
    WHEN calculation_hint ILIKE '%MANDATORY GLOBAL CONFIG INTENT SCOPE%' THEN calculation_hint
    ELSE
      'MANDATORY GLOBAL CONFIG INTENT SCOPE:
- This metric is dynamically scoped by Global Config; analyzer raw rows keep all prompts.
- Before aggregating, restrict fact rows to prompts whose intent is enabled for the Visibility metric.
- Join geo_client_prompts cp ON cp.id = <fact_alias>.client_prompt_id AND cp.client_id = <fact_alias>.client_id.
- If the table being aggregated does not have client_prompt_id, first join its parent fact table that does.
- Join geo_global_intents gi ON gi.intent_name = cp.intent.
- Add cp.client_id = $1, gi.is_active = true, and gi.categories @> ''["Visibility"]''::jsonb.
- Apply this filter to every numerator, denominator, total CTE, and subquery in the reference SQL.
- Never fall back to all intents when no intent is configured for Visibility.
'
      || E'\n'
      || COALESCE(calculation_hint, '')
  END,
  relevant_tables = COALESCE(relevant_tables, ARRAY[]::text[])
    || CASE
      WHEN 'geo_client_prompts' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_client_prompts']::text[]
    END
    || CASE
      WHEN 'geo_global_intents' = ANY(COALESCE(relevant_tables, ARRAY[]::text[]))
      THEN ARRAY[]::text[]
      ELSE ARRAY['geo_global_intents']::text[]
    END
WHERE is_active = TRUE
  AND domain = 'visibility';
