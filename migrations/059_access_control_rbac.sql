-- ============================================================
-- Migration 059: Access Control RBAC
-- ============================================================
-- Spec: docs/superpowers/specs/2026-05-18-access-control-rbac-design.md
--
-- Purpose:
--   - Add Google OAuth user registry.
--   - Add SaaS client-level access grants.
--   - Add Admin system-level access grants.
--   - Add explicit Super Admin SaaS all-clients override.
--
-- Execution:
--   - Run manually in Cloud SQL.
--   - This migration only creates schema objects. It does not seed users.
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------
-- 1. geo_users
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_users (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email          TEXT NOT NULL,
    google_sub     TEXT,
    name           TEXT,
    avatar_url     TEXT,
    quota_limit    INTEGER,
    is_active      BOOLEAN NOT NULL DEFAULT true,
    joined_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT geo_users_email_not_blank CHECK (btrim(email) <> ''),
    CONSTRAINT geo_users_quota_limit_non_negative CHECK (
        quota_limit IS NULL OR quota_limit >= 0
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_users_email_lower
    ON geo_users (LOWER(email));

CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_users_google_sub
    ON geo_users (google_sub)
    WHERE google_sub IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_geo_users_active
    ON geo_users (is_active);

COMMENT ON TABLE geo_users IS 'Google OAuth user registry for SaaS and Admin access control.';
COMMENT ON COLUMN geo_users.google_sub IS 'Stable Google OAuth subject identifier.';
COMMENT ON COLUMN geo_users.quota_limit IS 'User-level daily quota limit placeholder. Stored in this release; enforcement is implemented separately.';


-- ------------------------------------------------------------
-- 2. geo_client_user_access
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_client_user_access (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id   UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES geo_users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'member'
                CHECK (role IN ('member', 'viewer')),
    is_active   BOOLEAN NOT NULL DEFAULT true,
    granted_by  UUID REFERENCES geo_users(id) ON DELETE SET NULL,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (client_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_geo_client_user_access_user
    ON geo_client_user_access (user_id)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_geo_client_user_access_client
    ON geo_client_user_access (client_id)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_geo_client_user_access_role
    ON geo_client_user_access (role)
    WHERE is_active = true;

COMMENT ON TABLE geo_client_user_access IS 'SaaS client-level access grants. Any active role grants first-release SaaS access.';
COMMENT ON COLUMN geo_client_user_access.role IS 'Initial values: member, viewer. Fine-grained SaaS permissions can be layered later.';


-- ------------------------------------------------------------
-- 3. geo_admin_user_access
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_admin_user_access (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id              UUID NOT NULL REFERENCES geo_users(id) ON DELETE CASCADE,
    role                 TEXT NOT NULL
                         CHECK (role IN ('super_admin', 'viewer')),
    support_all_clients  BOOLEAN NOT NULL DEFAULT false,
    is_active            BOOLEAN NOT NULL DEFAULT true,
    granted_by           UUID REFERENCES geo_users(id) ON DELETE SET NULL,
    granted_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (user_id),
    CONSTRAINT geo_admin_user_access_support_all_clients_role CHECK (
        support_all_clients = false OR role = 'super_admin'
    )
);

CREATE INDEX IF NOT EXISTS idx_geo_admin_user_access_active_role
    ON geo_admin_user_access (role)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_geo_admin_user_access_support_all_clients
    ON geo_admin_user_access (support_all_clients)
    WHERE is_active = true AND support_all_clients = true;

COMMENT ON TABLE geo_admin_user_access IS 'Admin system-level access grants.';
COMMENT ON COLUMN geo_admin_user_access.role IS 'super_admin can mutate Admin resources; viewer is read-only.';
COMMENT ON COLUMN geo_admin_user_access.support_all_clients IS 'Explicit SaaS override. Only valid for super_admin; does not create client access rows.';


-- ------------------------------------------------------------
-- 4. updated_at helper
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_access_control_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_geo_users_updated_at ON geo_users;
CREATE TRIGGER trg_geo_users_updated_at
    BEFORE UPDATE ON geo_users
    FOR EACH ROW EXECUTE FUNCTION set_access_control_updated_at();

DROP TRIGGER IF EXISTS trg_geo_client_user_access_updated_at ON geo_client_user_access;
CREATE TRIGGER trg_geo_client_user_access_updated_at
    BEFORE UPDATE ON geo_client_user_access
    FOR EACH ROW EXECUTE FUNCTION set_access_control_updated_at();

DROP TRIGGER IF EXISTS trg_geo_admin_user_access_updated_at ON geo_admin_user_access;
CREATE TRIGGER trg_geo_admin_user_access_updated_at
    BEFORE UPDATE ON geo_admin_user_access
    FOR EACH ROW EXECUTE FUNCTION set_access_control_updated_at();

COMMIT;

-- ============================================================
-- Manual verification after execution
-- ============================================================
-- SELECT table_name
-- FROM information_schema.tables
-- WHERE table_name IN (
--   'geo_users',
--   'geo_client_user_access',
--   'geo_admin_user_access'
-- )
-- ORDER BY table_name;
--
-- SELECT indexname
-- FROM pg_indexes
-- WHERE tablename IN (
--   'geo_users',
--   'geo_client_user_access',
--   'geo_admin_user_access'
-- )
-- ORDER BY tablename, indexname;
