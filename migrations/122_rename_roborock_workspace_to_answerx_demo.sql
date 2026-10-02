-- 122_rename_roborock_workspace_to_answerx_demo.sql
-- Rename only the Roborock workspace display name to "AnswerX (Demo)".
--
-- Scope:
--   - Updates geo_clients.name for the Roborock client only.
--   - Does not update geo_client_brands.brand_name or aliases.
--   - Does not update peer, product, prompt, result, or analysis data.
--
-- UI impact note:
--   geo_clients.name is the workspace/customer display label used by the
--   workspace switcher. Other consumers of that same workspace metadata,
--   including static report titles, may also display the new name. Brand
--   matching and Settings brand configuration continue to use
--   geo_client_brands and are unchanged by this migration.

BEGIN;

DO $$
DECLARE
    v_roborock_count integer;
    v_demo_count integer;
    v_rows_updated integer;
BEGIN
    SELECT COUNT(*) FILTER (WHERE name = 'Roborock'),
           COUNT(*) FILTER (WHERE name = 'AnswerX (Demo)')
      INTO v_roborock_count, v_demo_count
      FROM geo_clients
     WHERE name IN ('Roborock', 'AnswerX (Demo)');

    IF v_roborock_count = 0 AND v_demo_count = 1 THEN
        RAISE NOTICE 'workspace_rows_updated=0 (already applied)';
        RETURN;
    END IF;

    IF v_roborock_count <> 1 OR v_demo_count <> 0 THEN
        RAISE EXCEPTION
            'Migration 122 aborted: expected exactly one "Roborock" workspace and no "AnswerX (Demo)" workspace, found Roborock=% and AnswerX (Demo)=%',
            v_roborock_count,
            v_demo_count;
    END IF;

    UPDATE geo_clients
       SET name = 'AnswerX (Demo)',
           updated_at = NOW()
     WHERE name = 'Roborock';

    GET DIAGNOSTICS v_rows_updated = ROW_COUNT;
    RAISE NOTICE 'workspace_rows_updated=%', v_rows_updated;
END
$$;

COMMIT;

-- Suggested pre-run verification (read-only):
--
-- SELECT c.id,
--        c.name AS workspace_name,
--        b.id AS brand_id,
--        b.brand_name,
--        b.aliases,
--        b.is_shadow,
--        b.is_active
--   FROM geo_clients c
--   LEFT JOIN geo_client_brands b ON b.client_id = c.id
--  WHERE c.name IN ('Roborock', 'AnswerX (Demo)')
--  ORDER BY b.is_shadow, b.brand_name;
--
-- Suggested post-run verification (read-only):
-- Run the same query above. Only workspace_name should change to
-- "AnswerX (Demo)"; brand_name and aliases should remain unchanged.
