-- ============================================================
-- Migration 048: Dual-Mode Tracking v1.2 - Phase 6 LLM Discovery model_id seed
-- ============================================================
-- 背景:Phase 6(LLM Batch Discovery)从 geo_global_settings 读 model_id,
-- key 为 'llm_batch_discovery_model_id'。此 key 在 v1.2 代码里有读取,
-- 但 migrations/046 没 seed。未 seed 时会 fallback 到硬编码 'gemini-2.0-flash',
-- 此模型在 GEO project 上无访问权(404)。
--
-- Layer 5b 本地验证时发现此问题(见 SESSION_HANDOFF_2026-04-20.md §5),
-- 本 migration 补 seed,保持和 sentiment_model_id / domain_classifier_model_id 一致。
-- ============================================================

BEGIN;

INSERT INTO geo_global_settings (key, value, description)
VALUES (
    'llm_batch_discovery_model_id',
    'gemini-3-flash-preview',
    'Phase 6 LLM Batch Discovery 使用的 Gemini model。保持和 sentiment/domain_classifier 同一模型,统一 model 升级/回滚。'
)
ON CONFLICT (key) DO UPDATE
  SET value = EXCLUDED.value,
      updated_at = NOW();

COMMIT;

-- ============================================================
-- 验证
-- ============================================================
-- SELECT key, value FROM geo_global_settings WHERE key = 'llm_batch_discovery_model_id';
-- 期望 value = 'gemini-3-flash-preview'
