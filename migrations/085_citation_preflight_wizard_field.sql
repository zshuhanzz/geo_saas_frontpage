-- Migration 085: Make Citation Analysis visible and runnable inside the Content wizard.
--
-- User executes manually in Cloud SQL.

BEGIN;

UPDATE geo_workflow_config
SET value = jsonb_set(
      value,
      '{fields}',
      '[
        {
          "key": "citation_analysis_preflight",
          "type": "citation_analysis_preflight",
          "label": "Citation Analysis",
          "description": "Run Citation Analysis before final generation, review cited sources, brand mention triage, and the citation-grounded brief."
        }
      ]'::jsonb
    )
WHERE scope = 'content_generation'
  AND config_type = 'workflow_step'
  AND key = 'citation_analysis'
  AND parent_key IS NULL;

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
  AND parent_key IS NULL;

-- Require wizard preflight for the two AI-citable templates. The pipeline still
-- has a backend fallback when old drafts or API-created tasks do not provide a
-- preflight result.
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
      COALESCE(wizard_config, '{}'::jsonb),
      '{citation_analysis,require_preflight}',
      'true'::jsonb,
      true
    ),
    updated_at = NOW()
WHERE name IN (
  'Reddit AI Citable Post Generator',
  'Official Website AI Citable Article'
);

COMMIT;

-- Verification:
-- SELECT key, value->'fields'
-- FROM geo_workflow_config
-- WHERE scope = 'content_generation'
--   AND config_type = 'workflow_step'
--   AND key = 'citation_analysis';
--
-- SELECT name, wizard_config#>>'{citation_analysis,require_preflight}'
-- FROM geo_report_templates
-- WHERE name IN ('Reddit AI Citable Post Generator', 'Official Website AI Citable Article');
