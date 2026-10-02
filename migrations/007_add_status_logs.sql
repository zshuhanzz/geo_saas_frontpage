-- ============================================================
-- 007_add_status_logs.sql
-- Fire-and-Forget 架构改造：为 geo_report_runs 添加 status_logs 字段
-- status_logs: JSONB 数组，记录后台任务每个阶段的进度日志
-- ============================================================

ALTER TABLE geo_report_runs
    ADD COLUMN IF NOT EXISTS status_logs JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN geo_report_runs.status_logs IS
    'Progress log entries for fire-and-forget pipeline. Each entry: {step, event, label, ts}';

-- ── 历史记录回填 ──────────────────────────────────────────────────
-- 对改造前已存在的 COMPLETED / FAILED 记录，写入一条标记性日志。
-- 理由：
--   1. status_logs 为空数组时，前端进度面板会是空白，体验不好。
--   2. 这些记录本身有完整的 report_output，前端仍可正常展示报告。
--   3. 这条 legacy 条目只是给进度面板一个占位说明，不影响任何业务逻辑。
UPDATE geo_report_runs
SET status_logs = jsonb_build_array(
    jsonb_build_object(
        'event',  'legacy',
        'label',  '（此报告生成于异步化改造前，进度日志不可用）',
        'ts',     COALESCE(completed_at, started_at, NOW())::text
    )
)
WHERE status IN ('COMPLETED', 'FAILED')
  AND (status_logs IS NULL OR status_logs = '[]'::jsonb);
