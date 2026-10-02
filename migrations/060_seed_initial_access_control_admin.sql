-- ============================================================
-- Migration 060: Seed Initial Access Control Admin
-- ============================================================
-- Purpose:
--   - Bootstrap the first Admin user after Migration 059.
--   - Grant Super Admin access in Admin.
--   - Enable explicit SaaS all-clients support access.
--
-- Execution:
--   - Run manually in Cloud SQL after 059_access_control_rbac.sql.
-- ============================================================

BEGIN;

WITH seed_user AS (
    INSERT INTO geo_users (
        email,
        name,
        quota_limit,
        is_active
    )
    VALUES (
        'gotyechen@gmail.com',
        'Lancelot Chen',
        NULL,
        true
    )
    ON CONFLICT (LOWER(email)) DO UPDATE SET
        name = EXCLUDED.name,
        is_active = true,
        updated_at = NOW()
    RETURNING id
)
INSERT INTO geo_admin_user_access (
    user_id,
    role,
    support_all_clients,
    is_active,
    granted_by
)
SELECT
    id,
    'super_admin',
    true,
    true,
    id
FROM seed_user
ON CONFLICT (user_id) DO UPDATE SET
    role = EXCLUDED.role,
    support_all_clients = EXCLUDED.support_all_clients,
    is_active = true,
    granted_by = EXCLUDED.granted_by,
    granted_at = NOW(),
    updated_at = NOW();

COMMIT;

-- ============================================================
-- Manual verification after execution
-- ============================================================
-- SELECT
--     u.email,
--     u.name,
--     u.is_active AS user_is_active,
--     a.role,
--     a.support_all_clients,
--     a.is_active AS admin_access_is_active
-- FROM geo_users u
-- JOIN geo_admin_user_access a ON a.user_id = u.id
-- WHERE LOWER(u.email) = LOWER('gotyechen@gmail.com');
