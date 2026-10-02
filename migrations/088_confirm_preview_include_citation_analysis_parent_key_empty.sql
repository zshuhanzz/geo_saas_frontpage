-- Migration 088: Retry Confirm execution preview update for empty parent_key rows
--
-- Context:
--   Migration 087 targeted parent_key IS NULL. In the local E2E database,
--   the content_generation confirm_execute workflow row has parent_key = ''
--   (empty string), so 087 completed successfully but matched zero rows.
--
-- Scope:
--   Same payload as 087, but matches both NULL and empty parent_key.

BEGIN;

UPDATE geo_workflow_config
SET value = jsonb_set(
      COALESCE(value, '{}'::jsonb),
      '{fields}',
      '[
        {
          "key": "execution_preview",
          "type": "execution_preview",
          "label": "执行流程",
          "config": {
            "steps": [
              {
                "name": "citation_analysis",
                "label": "Citation Analysis",
                "description": "复用 Wizard 预运行 Citation Brief；缺失或过期时才在后台重新分析"
              },
              {
                "name": "strategy_generation",
                "label": "策略生成",
                "description": "基于 Citation Brief、模板配置和用户输入生成或复用内容策略"
              },
              {
                "name": "content_generation",
                "label": "内容生成",
                "description": "注入模板默认指令、平台规则、品牌画像与 Citation Brief 生成内容"
              },
              {
                "name": "quality_review",
                "label": "Quality Gate",
                "description": "执行 LLM 评审与模板配置化 deterministic QA，标记阻断项和警告"
              },
              {
                "name": "revise",
                "label": "内容修正 / Revise",
                "description": "仅当 Quality Gate 触发修正时定向改写；通过则自动跳过"
              }
            ]
          }
        }
      ]'::jsonb,
      true
    )
WHERE scope = 'content_generation'
  AND config_type = 'workflow_step'
  AND key = 'confirm_execute'
  AND COALESCE(parent_key, '') = '';

COMMIT;

-- Verification:
-- SELECT key, parent_key, value->'fields'
-- FROM geo_workflow_config
-- WHERE scope = 'content_generation'
--   AND config_type = 'workflow_step'
--   AND key = 'confirm_execute'
--   AND COALESCE(parent_key, '') = '';
