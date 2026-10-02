-- ============================================================
-- Migration 133: Workspace feature entitlements
-- ============================================================
-- Purpose:
--   - Store business-facing feature metadata and reusable packages.
--   - Store the effective feature snapshot granted to each Workspace.
--   - Preserve all existing Workspace behavior by granting the Full Platform
--     package to every existing geo_clients row.
--
-- Boundary:
--   - Technical feature keys, URL mappings, and the initial Admin/Viewer
--     capability matrix remain code-owned in geo_common.permissions.
--   - Database rows cannot introduce a new technical feature key. Admin API
--     validates every key against the code registry before writing.
--   - Package application is a snapshot. Editing a package does not silently
--     change existing Workspace entitlements.
--
-- Execution:
--   - Run manually in Cloud SQL after migration 132.
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS geo_feature_catalog (
    feature_key      TEXT PRIMARY KEY,
    module_key       TEXT NOT NULL CHECK (module_key IN ('analytics', 'actions')),
    display_name_zh  TEXT NOT NULL,
    display_name_en  TEXT NOT NULL,
    description_zh   TEXT NOT NULL DEFAULT '',
    description_en   TEXT NOT NULL DEFAULT '',
    sort_order       INTEGER NOT NULL DEFAULT 0,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT geo_feature_catalog_key_not_blank
        CHECK (btrim(feature_key) <> '')
);

CREATE TABLE IF NOT EXISTS geo_feature_packages (
    package_key      TEXT PRIMARY KEY,
    display_name_zh  TEXT NOT NULL,
    display_name_en  TEXT NOT NULL,
    description_zh   TEXT NOT NULL DEFAULT '',
    description_en   TEXT NOT NULL DEFAULT '',
    sort_order       INTEGER NOT NULL DEFAULT 0,
    is_system        BOOLEAN NOT NULL DEFAULT false,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT geo_feature_packages_key_not_blank
        CHECK (btrim(package_key) <> '')
);

CREATE TABLE IF NOT EXISTS geo_feature_package_items (
    package_key  TEXT NOT NULL
                 REFERENCES geo_feature_packages(package_key) ON DELETE CASCADE,
    feature_key  TEXT NOT NULL
                 REFERENCES geo_feature_catalog(feature_key) ON DELETE RESTRICT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (package_key, feature_key)
);

CREATE TABLE IF NOT EXISTS geo_workspace_entitlement_profiles (
    client_id            UUID PRIMARY KEY
                         REFERENCES geo_clients(id) ON DELETE CASCADE,
    applied_package_key  TEXT
                         REFERENCES geo_feature_packages(package_key)
                         ON DELETE SET NULL,
    is_custom            BOOLEAN NOT NULL DEFAULT false,
    updated_by           UUID REFERENCES geo_users(id) ON DELETE SET NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS geo_workspace_feature_entitlements (
    client_id    UUID NOT NULL REFERENCES geo_clients(id) ON DELETE CASCADE,
    feature_key  TEXT NOT NULL
                 REFERENCES geo_feature_catalog(feature_key) ON DELETE RESTRICT,
    is_enabled   BOOLEAN NOT NULL DEFAULT true,
    source       TEXT NOT NULL DEFAULT 'custom'
                 CHECK (source IN ('migration', 'package', 'custom')),
    updated_by   UUID REFERENCES geo_users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (client_id, feature_key)
);

CREATE INDEX IF NOT EXISTS idx_geo_workspace_feature_entitlements_enabled
    ON geo_workspace_feature_entitlements (client_id, feature_key)
    WHERE is_enabled = true;

INSERT INTO geo_feature_catalog (
    feature_key, module_key, display_name_zh, display_name_en,
    description_zh, description_en, sort_order
)
VALUES
    ('analytics.overview', 'analytics', '可见度总览', 'Overview',
     '汇总查看品牌的核心 GEO 指标与趋势。',
     'View a summary of core GEO metrics and trends.', 10),
    ('analytics.visibility', 'analytics', '可见度', 'Visibility',
     '查看品牌、产品和渠道的可见度表现。',
     'Explore brand, product, and channel visibility.', 20),
    ('analytics.citations', 'analytics', '引用', 'Citations',
     '查看引用来源、域名和页面表现。',
     'Inspect cited sources, domains, and pages.', 30),
    ('analytics.sentiment', 'analytics', '引用情感', 'Sentiment',
     '查看品牌和引用内容的情感分布。',
     'Review sentiment across brands and citations.', 40),
    ('analytics.prompts', 'analytics', 'Prompt 报告', 'Prompt Reports',
     '查看 Prompt、主题、扇出和单次回答明细。',
     'Review prompts, topics, fan-outs, and individual responses.', 50),
    ('analytics.reports', 'analytics', 'Reports', 'Reports',
     '生成并查看动态日期范围报告入口。',
     'Materialize and view dynamic date-range report entries.', 60),
    ('actions.configuration', 'actions', '配置', 'Configuration',
     '查看或维护 Workspace 品牌、竞品、主题和 Prompt 配置。',
     'View or maintain workspace brands, peers, topics, and prompts.', 10),
    ('actions.analysis', 'actions', '分析内容', 'Analyze',
     '查看分析任务结果；管理员可创建、运行、编辑和删除任务。',
     'View analysis results; Admins can create, run, edit, and delete tasks.', 20),
    ('actions.content', 'actions', '内容生成', 'Content Generation',
     '查看已生成文章；管理员可创建和执行内容任务。',
     'View generated articles; Admins can create and execute content tasks.', 30),
    ('actions.chat', 'actions', '对话 Anthony', 'Chat with Anthony',
     '通过 Anthony 对话执行跨模块分析与协作。',
     'Use Anthony for conversational analysis and collaboration.', 40),
    ('actions.training', 'actions', '训练 Anthony', 'Train Anthony',
     '配置 Anthony 的模板、框架和训练资源。',
     'Configure Anthony templates, frameworks, and training resources.', 50)
ON CONFLICT (feature_key) DO UPDATE SET
    module_key = EXCLUDED.module_key,
    display_name_zh = EXCLUDED.display_name_zh,
    display_name_en = EXCLUDED.display_name_en,
    description_zh = EXCLUDED.description_zh,
    description_en = EXCLUDED.description_en,
    sort_order = EXCLUDED.sort_order,
    updated_at = NOW();

INSERT INTO geo_feature_packages (
    package_key, display_name_zh, display_name_en,
    description_zh, description_en, sort_order, is_system
)
VALUES
    ('analytics', '数据分析包', 'Analytics',
     '包含全部数据分析与洞察功能。',
     'Includes all Data Analysis & Monitoring features.', 10, true),
    ('full_platform', '全功能包', 'Full Platform',
     '包含数据分析与全部 Actions 功能。',
     'Includes analytics and all Actions features.', 20, true)
ON CONFLICT (package_key) DO UPDATE SET
    display_name_zh = EXCLUDED.display_name_zh,
    display_name_en = EXCLUDED.display_name_en,
    description_zh = EXCLUDED.description_zh,
    description_en = EXCLUDED.description_en,
    sort_order = EXCLUDED.sort_order,
    is_system = EXCLUDED.is_system,
    updated_at = NOW();

INSERT INTO geo_feature_package_items (package_key, feature_key)
SELECT 'analytics', feature_key
FROM geo_feature_catalog
WHERE module_key = 'analytics'
ON CONFLICT DO NOTHING;

INSERT INTO geo_feature_package_items (package_key, feature_key)
SELECT 'full_platform', feature_key
FROM geo_feature_catalog
ON CONFLICT DO NOTHING;

INSERT INTO geo_workspace_entitlement_profiles (
    client_id, applied_package_key, is_custom
)
SELECT id, 'full_platform', false
FROM geo_clients
ON CONFLICT (client_id) DO NOTHING;

INSERT INTO geo_workspace_feature_entitlements (
    client_id, feature_key, is_enabled, source
)
SELECT clients.id, features.feature_key, true, 'migration'
FROM geo_clients AS clients
CROSS JOIN geo_feature_catalog AS features
ON CONFLICT (client_id, feature_key) DO NOTHING;

CREATE OR REPLACE FUNCTION set_feature_entitlement_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_geo_feature_catalog_updated_at
    ON geo_feature_catalog;
CREATE TRIGGER trg_geo_feature_catalog_updated_at
    BEFORE UPDATE ON geo_feature_catalog
    FOR EACH ROW EXECUTE FUNCTION set_feature_entitlement_updated_at();

DROP TRIGGER IF EXISTS trg_geo_feature_packages_updated_at
    ON geo_feature_packages;
CREATE TRIGGER trg_geo_feature_packages_updated_at
    BEFORE UPDATE ON geo_feature_packages
    FOR EACH ROW EXECUTE FUNCTION set_feature_entitlement_updated_at();

DROP TRIGGER IF EXISTS trg_geo_workspace_entitlement_profiles_updated_at
    ON geo_workspace_entitlement_profiles;
CREATE TRIGGER trg_geo_workspace_entitlement_profiles_updated_at
    BEFORE UPDATE ON geo_workspace_entitlement_profiles
    FOR EACH ROW EXECUTE FUNCTION set_feature_entitlement_updated_at();

DROP TRIGGER IF EXISTS trg_geo_workspace_feature_entitlements_updated_at
    ON geo_workspace_feature_entitlements;
CREATE TRIGGER trg_geo_workspace_feature_entitlements_updated_at
    BEFORE UPDATE ON geo_workspace_feature_entitlements
    FOR EACH ROW EXECUTE FUNCTION set_feature_entitlement_updated_at();

COMMENT ON TABLE geo_feature_catalog IS
    'Business-facing metadata for code-declared feature keys.';
COMMENT ON TABLE geo_feature_packages IS
    'Reusable entitlement presets. Applying a package copies a snapshot.';
COMMENT ON TABLE geo_workspace_feature_entitlements IS
    'Effective Workspace feature grants; absence or is_enabled=false means unentitled.';
COMMENT ON COLUMN geo_workspace_entitlement_profiles.applied_package_key IS
    'Provenance only. Later package edits do not mutate this Workspace snapshot.';

COMMIT;

-- Manual verification:
-- SELECT c.name, p.applied_package_key, COUNT(*) FILTER (WHERE e.is_enabled)
-- FROM geo_clients c
-- JOIN geo_workspace_entitlement_profiles p ON p.client_id = c.id
-- JOIN geo_workspace_feature_entitlements e ON e.client_id = c.id
-- GROUP BY c.name, p.applied_package_key
-- ORDER BY c.name;
