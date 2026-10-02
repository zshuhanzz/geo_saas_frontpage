-- 014_custom_template_and_scheduler.sql
-- 1. Insert custom (blank) content template into geo_report_templates
-- 2. Add scheduler columns to geo_agent_tasks (for admin cron management)
-- 3. Drop legacy geo_report_runs table (data now in geo_agent_tasks)

-- ─── Step 1: Custom content template ─────────────────────────────────────────
INSERT INTO geo_report_templates (
    id, name, description, icon, data_domains, default_prompt,
    is_builtin, is_active, sort_order, task_type
) VALUES (
    gen_random_uuid(),
    '自定义内容',
    '不预选任何选项，完全自定义所有配置',
    '✨',
    ARRAY[]::TEXT[],
    '',
    true, true, 0, 'content_generation'
);

-- ─── Step 2: Add scheduler columns to geo_agent_tasks ────────────────────────
ALTER TABLE geo_agent_tasks
    ADD COLUMN IF NOT EXISTS cron_expression TEXT,
    ADD COLUMN IF NOT EXISTS cron_timezone TEXT DEFAULT 'Asia/Shanghai',
    ADD COLUMN IF NOT EXISTS schedule_enabled BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS scheduler_job_name TEXT;

-- ─── Step 3: Drop legacy geo_report_runs table ──────────────────────────────
-- All report run data has been migrated to geo_agent_tasks.
-- Run this only after confirming no active reads/writes to geo_report_runs.
DROP TABLE IF EXISTS geo_report_runs;
