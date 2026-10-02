-- ============================================================
-- Migration 049: Dual-Mode Tracking v1.2 - Per-client LLM Discovery cron
-- ============================================================
-- 背景:Phase 6(LLM Batch Discovery)原设计是单一 global Cloud Scheduler
-- (见 geo_analyzer/terraform/suggestions.tf google_cloud_scheduler_job.geo_suggestions_daily)。
-- 真实运营中每个客户的数据量、上线节奏、Flash token 预算都不同,需要按客户独立调度。
--
-- 本 migration 为 geo_clients 增加 cron_llm_discovery 字段,复用现有
-- services/gcp_scheduler.sync_scheduler_job 机制(和 cron_collector / cron_analyzer 同构)
-- 由 Admin API 按客户动态创建/更新 Cloud Scheduler Job,指向
-- POST /api/clients/{client_id}/jobs/llm_discovery/run
-- 该 endpoint 会以 CLIENT_ID env override 方式触发
-- Cloud Run Job `geo-analyzer-llm-batch-discovery`。
-- ============================================================

BEGIN;

ALTER TABLE geo_clients
    ADD COLUMN IF NOT EXISTS cron_llm_discovery TEXT;

COMMENT ON COLUMN geo_clients.cron_llm_discovery IS
    'Per-client Cloud Scheduler cron for LLM Batch Discovery (Phase 6). '
    'NULL = no schedule (manual trigger only). Managed by Admin UI; '
    'sync_scheduler_job() creates/updates geo-llm_discovery-<short_id> Cloud Scheduler job.';

COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- \d geo_clients
-- 期望看到 cron_llm_discovery | text | | |
