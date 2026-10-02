-- ============================================================
-- Migration 134: Internal Account Manager role and Analytics configuration
-- ============================================================
-- Purpose:
--   - Add account_manager as a Workspace-scoped internal role.
--   - Include read-only/editable Configuration access in the Analytics
--     package; role capabilities remain code-owned.
--   - Refresh only non-custom Workspaces whose recorded package is Analytics.
--
-- Security boundary:
--   - account_manager bypass behavior is enforced by application RBAC.
--   - This migration does not create grants or widen Workspace membership.
--
-- Execution:
--   - Run manually in Cloud SQL after migration 133.
-- ============================================================

BEGIN;

ALTER TABLE geo_client_user_access
    DROP CONSTRAINT IF EXISTS geo_client_user_access_role_check;

ALTER TABLE geo_client_user_access
    ADD CONSTRAINT geo_client_user_access_role_check
    CHECK (role IN ('admin', 'viewer', 'account_manager'));

COMMENT ON COLUMN geo_client_user_access.role IS
    'Workspace role: admin, viewer, or internal account_manager.';

INSERT INTO geo_feature_package_items (package_key, feature_key)
VALUES ('analytics', 'actions.configuration')
ON CONFLICT (package_key, feature_key) DO NOTHING;

INSERT INTO geo_workspace_feature_entitlements (
    client_id,
    feature_key,
    is_enabled,
    source,
    updated_by
)
SELECT
    profile.client_id,
    'actions.configuration',
    true,
    'package',
    profile.updated_by
FROM geo_workspace_entitlement_profiles AS profile
WHERE profile.applied_package_key = 'analytics'
  AND profile.is_custom = false
ON CONFLICT (client_id, feature_key) DO UPDATE SET
    is_enabled = true,
    source = 'package',
    updated_by = EXCLUDED.updated_by,
    updated_at = NOW();

COMMIT;

-- Manual verification:
-- SELECT role, COUNT(*) FROM geo_client_user_access GROUP BY role ORDER BY role;
-- SELECT package_key, feature_key
-- FROM geo_feature_package_items
-- WHERE package_key = 'analytics'
-- ORDER BY feature_key;
-- SELECT c.name, e.is_enabled, e.source
-- FROM geo_workspace_entitlement_profiles p
-- JOIN geo_clients c ON c.id = p.client_id
-- JOIN geo_workspace_feature_entitlements e
--   ON e.client_id = p.client_id
--  AND e.feature_key = 'actions.configuration'
-- WHERE p.applied_package_key = 'analytics'
--   AND p.is_custom = false
-- ORDER BY c.name;
