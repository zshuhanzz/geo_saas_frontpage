-- 123_rename_easeus_workspace_deprecated.sql
-- Rename only the existing EaseUS workspace/customer display name to
-- "EaseUS (Deprecated)" so the name "EaseUS" can be reused by a new client.
--
-- Scope:
--   - Updates geo_clients.name only.
--   - Does not update geo_client_brands.brand_name or aliases.
--   - Does not update peer, product, prompt, result, or analysis data.
--
-- UI impact note:
--   Any UI or export that displays geo_clients.name may show the deprecated
--   label. Brand matching and Settings brand configuration continue to use
--   geo_client_brands and are unchanged by this migration.

BEGIN;

DO $$
DECLARE
    v_easeus_count integer;
    v_deprecated_count integer;
    v_rows_updated integer;
BEGIN
    SELECT COUNT(*) FILTER (WHERE name = 'EaseUS'),
           COUNT(*) FILTER (WHERE name = 'EaseUS (Deprecated)')
      INTO v_easeus_count, v_deprecated_count
      FROM geo_clients
     WHERE name IN ('EaseUS', 'EaseUS (Deprecated)');

    IF v_easeus_count = 0 AND v_deprecated_count = 1 THEN
        RAISE NOTICE 'workspace_rows_updated=0 (already applied)';
        RETURN;
    END IF;

    IF v_easeus_count <> 1 OR v_deprecated_count <> 0 THEN
        RAISE EXCEPTION
            'Migration 123 aborted: expected exactly one "EaseUS" workspace and no "EaseUS (Deprecated)" workspace, found EaseUS=% and EaseUS (Deprecated)=%',
            v_easeus_count,
            v_deprecated_count;
    END IF;

    UPDATE geo_clients
       SET name = 'EaseUS (Deprecated)',
           updated_at = NOW()
     WHERE name = 'EaseUS';

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
--  WHERE c.name IN ('EaseUS', 'EaseUS (Deprecated)')
--  ORDER BY c.name, b.is_shadow, b.brand_name;
--
-- Suggested post-run verification (read-only):
-- Run the same query above. Only workspace_name should change to
-- "EaseUS (Deprecated)"; brand_name and aliases should remain unchanged.
