-- ============================================================
-- Migration 061: Rename Client Access role member -> admin
-- ============================================================
-- Purpose:
--   - Align client-level SaaS access roles with product semantics:
--     Admin and Viewer.
--   - Preserve existing access grants by migrating member rows to admin.
--
-- Execution:
--   - Run manually in Cloud SQL after migration 059.
-- ============================================================

BEGIN;

ALTER TABLE geo_client_user_access
    DROP CONSTRAINT IF EXISTS geo_client_user_access_role_check;

DO $$
DECLARE
    check_name TEXT;
BEGIN
    FOR check_name IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'geo_client_user_access'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%member%'
    LOOP
        EXECUTE format(
            'ALTER TABLE geo_client_user_access DROP CONSTRAINT %I',
            check_name
        );
    END LOOP;
END $$;

UPDATE geo_client_user_access
SET role = 'admin',
    updated_at = NOW()
WHERE role = 'member';

ALTER TABLE geo_client_user_access
    ALTER COLUMN role SET DEFAULT 'admin';

ALTER TABLE geo_client_user_access
    ADD CONSTRAINT geo_client_user_access_role_check
    CHECK (role IN ('admin', 'viewer'));

COMMENT ON COLUMN geo_client_user_access.role IS
    'Client-level SaaS role. Initial values: admin, viewer. Viewer read-only enforcement will be layered later.';

COMMIT;
