-- =============================================================
-- Migration 019: Add content_type to content generation template defaults
-- Run: psql $DATABASE_URL -f migrations/019_content_template_defaults.sql
-- =============================================================
-- The pipeline dispatches to different generators based on inputs.content_type.
-- Previously this was inferred by frontend from the template name (fragile).
-- Now each template carries its canonical content_type in the defaults JSONB.
--
-- The "自定义内容" (blank/custom) template is intentionally left without
-- a content_type default — users choose the type themselves in the wizard.
-- =============================================================


-- 1. FAQ 内容生成
UPDATE geo_report_templates
SET defaults = jsonb_set(COALESCE(defaults, '{}'), '{content_type}', '"faq"'),
    updated_at = NOW()
WHERE name = 'FAQ 内容生成' AND is_builtin = true AND task_type = 'content_generation';

-- 2. AEO 优化文章
UPDATE geo_report_templates
SET defaults = jsonb_set(COALESCE(defaults, '{}'), '{content_type}', '"aeo_article"'),
    updated_at = NOW()
WHERE name = 'AEO 优化文章' AND is_builtin = true AND task_type = 'content_generation';

-- 3. SEO 优化文章
UPDATE geo_report_templates
SET defaults = jsonb_set(COALESCE(defaults, '{}'), '{content_type}', '"article"'),
    updated_at = NOW()
WHERE name = 'SEO 优化文章' AND is_builtin = true AND task_type = 'content_generation';

-- 4. 内容优化建议
UPDATE geo_report_templates
SET defaults = jsonb_set(COALESCE(defaults, '{}'), '{content_type}', '"recommendations"'),
    updated_at = NOW()
WHERE name = '内容优化建议' AND is_builtin = true AND task_type = 'content_generation';

-- 5. Content Brief
UPDATE geo_report_templates
SET defaults = jsonb_set(COALESCE(defaults, '{}'), '{content_type}', '"brief"'),
    updated_at = NOW()
WHERE name = 'Content Brief' AND is_builtin = true AND task_type = 'content_generation';
