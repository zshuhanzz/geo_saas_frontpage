-- =============================================================================
-- Migration 081: Show the real 4-step content execution flow in Wizard Confirm
-- =============================================================================
--
-- Root cause
-- ----------
-- The Confirm step's "执行流程" preview is not rendered from the live
-- CONTENT_V2_STEPS pipeline definition. It is a static execution_preview field
-- stored in geo_workflow_config.value.fields[].config.steps, originally seeded
-- by migration 036 with the old 3-step flow.
--
-- This migration updates only the content_generation confirm_execute preview so
-- the UI matches the current backend:
--   1. strategy_generation
--   2. content_generation
--   3. quality_review / Quality Gate
--   4. revise (conditional)
-- =============================================================================

BEGIN;

UPDATE geo_workflow_config
SET value = jsonb_set(
  value,
  '{fields}',
  '[
    {
      "key": "execution_preview",
      "type": "execution_preview",
      "label": "执行流程",
      "config": {
        "steps": [
          {
            "name": "strategy_generation",
            "label": "策略生成",
            "description": "复用 Wizard 已确认策略；缺失时才基于模板和分析上下文生成策略"
          },
          {
            "name": "content_generation",
            "label": "内容生成",
            "description": "注入模板默认指令、平台规则、品牌画像与前序节点输入生成内容"
          },
          {
            "name": "quality_review",
            "label": "质量评审 / Quality Gate",
            "description": "执行 LLM 评审与模板配置化 deterministic QA，标记缺失结构和高风险表达"
          },
          {
            "name": "revise",
            "label": "内容修正 / Revise",
            "description": "仅当 Quality Gate 未通过时触发定向修正；通过则自动跳过"
          }
        ]
      }
    }
  ]'::jsonb,
  true
)
WHERE config_type = 'workflow_step'
  AND scope = 'content_generation'
  AND key = 'confirm_execute';

COMMIT;

-- Verification:
-- SELECT value#>'{fields,0,config,steps}' AS execution_preview_steps
-- FROM geo_workflow_config
-- WHERE config_type = 'workflow_step'
--   AND scope = 'content_generation'
--   AND key = 'confirm_execute';
