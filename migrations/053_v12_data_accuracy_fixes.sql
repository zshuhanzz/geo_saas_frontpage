-- 053_v12_data_accuracy_fixes.sql
-- v1.2 data accuracy pass (v2 late-session, 2026-04-20):
--
--   Bug #3: `citation_by_citation_role` metric silently dropped the NULL
--   `citation_role` rows (via `AND citation_role IS NOT NULL`). For OEM
--   customers (Tmax) this hid 5611 citations as "待分类 / unclassified"
--   — making it look like they only had 6 own-domain citations when in
--   reality there were 5617 total. The unclassified bucket is a signal,
--   not noise: it tells the customer "these domains aren't in your
--   Settings yet — consider adding them".
--
--   Fix: COALESCE NULL → 'unclassified' in both SELECT and GROUP BY, and
--   drop the `IS NOT NULL` filter.
--
-- Other bugs (code-only, no SQL):
--   Bug #1: /api/insights/peer-sov-via-list returned orphan mentions
--     whose client_prompt_id pointed at deleted prompts — inconsistent
--     with /visibility. Fixed in geo_saas/api/routers/insights/peer_sov.py
--     by adding an EXISTS join on geo_client_prompts.is_active.
--   Bug #2: NL2SQL LLM emitted 'positive'/'negative'/'owned' enum
--     literals (lower / wrong). Fixed in geo_agent/api/pipelines/
--     analysis_pipeline.py via (a) stronger METRIC_SQL_HEADER enum
--     guardrails and (b) normalize_enum_literals() post-processor.
--
-- Rollback:
--   UPDATE geo_analysis_metrics SET calculation_hint =
--     'SELECT citation_role, COUNT(*) AS citations FROM geo_citations
--      WHERE client_id = $1 AND executed_at BETWEEN $2 AND $3
--      AND citation_role IS NOT NULL GROUP BY citation_role
--      ORDER BY citations DESC'
--   WHERE metric_name='citation_by_citation_role';

BEGIN;

UPDATE geo_analysis_metrics
   SET calculation_hint = 'SELECT COALESCE(citation_role, ''unclassified'') AS citation_role, COUNT(*) AS citations FROM geo_citations WHERE client_id = $1 AND executed_at BETWEEN $2 AND $3 GROUP BY COALESCE(citation_role, ''unclassified'') ORDER BY citations DESC',
       updated_at = now()
 WHERE metric_name = 'citation_by_citation_role';

-- Verification: should return the updated calculation_hint with COALESCE.
--   SELECT metric_name, calculation_hint FROM geo_analysis_metrics
--     WHERE metric_name='citation_by_citation_role';

COMMIT;
