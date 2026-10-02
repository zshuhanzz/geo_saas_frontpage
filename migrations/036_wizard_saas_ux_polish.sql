-- Migration 036 — SaaS wizard UX polish
-- ============================================================
-- Three fixes:
--
--   A. Mark `disable_user_edit` field as admin_only so it doesn't render
--      in the SaaS UI. The value still seeds from template defaults, it
--      just doesn't show a toggle to end users.
--
--   B. Add `execution_preview` field to both analysis and content
--      `confirm_execute` steps, so users see what pipeline stages will
--      run after they click "Run".
--
-- NOTE: `required_metrics` filtering is handled entirely in frontend
-- (PromptEditor reads template.wizard_config.required_metrics and filters
-- the variable catalog). No DB change needed.
-- ============================================================

BEGIN;

-- ============================================================
-- A. Analysis `prompt_edit` — mark disable_user_edit as admin_only
-- ============================================================
-- We rebuild the entire step value because jsonb_set on nested array
-- elements by key (not index) is fragile. The structure matches 031-C
-- exactly, with one addition: config.admin_only on disable_user_edit.
UPDATE geo_workflow_config
SET value = '{
  "num": 5,
  "label": "Prompt 编辑 (Prompt Edit)",
  "description": "终端用户微调 LLM 提示词；可锁定编辑权限 + 控制数据依据披露",
  "fields": [
    {
      "key": "disable_user_edit",
      "type": "boolean",
      "label": "禁止终端用户编辑 Prompt",
      "default": false,
      "description": "开启后 SaaS 端的 Prompt 编辑框只读，终端用户不能改动；适用于合规 / 内置模板 / 强约束场景",
      "config": { "admin_only": true }
    },
    {
      "key": "include_data_disclosure",
      "type": "boolean",
      "label": "插入「真实数据依据」章节",
      "default": true,
      "description": "运行时自动拼接品牌实际数据摘要，要求模型基于真实数据给出分析。强烈建议保持开启",
      "config": { "admin_only": true }
    },
    {
      "key": "custom_prompt",
      "type": "prompt_editor",
      "label": "自定义提示词 (可选)",
      "description": "留空则使用模板 default_prompt；支持变量捕获（如 [点击替换为可见度指标] 会被选中指标自动替换）",
      "depends_on": ["default_metrics"],
      "compute_default": "prompt_template_with_metrics",
      "config": {
        "variable_catalog_ref": {
          "endpoint": "/tasks/metrics/discover",
          "param_field": "default_domains"
        }
      }
    }
  ]
}'::jsonb,
    sort_order = 5
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'prompt_edit';


-- ============================================================
-- B. Analysis `confirm_execute` — add execution_preview field
-- ============================================================
UPDATE geo_workflow_config
SET value = '{
  "num": 6,
  "label": "确认执行 (Confirm)",
  "description": "复核向导配置后触发执行",
  "fields": [
    {
      "key": "execution_preview",
      "type": "execution_preview",
      "label": "执行流程",
      "config": {
        "steps": [
          { "name": "validate_inputs",    "label": "输入校验",   "description": "校验数据维度、时间范围等参数" },
          { "name": "hydrate_metrics",    "label": "指标水合",   "description": "查询数据库，计算分析指标" },
          { "name": "generate_charts",    "label": "图表生成",   "description": "根据图表配置生成可视化" },
          { "name": "synthesize_report",  "label": "报告合成",   "description": "基于指标数据 + Prompt 生成分析报告" },
          { "name": "quality_check",      "label": "质量检查",   "description": "检查数据准确性与幻觉风险" }
        ]
      }
    }
  ]
}'::jsonb,
    sort_order = 6
WHERE config_type = 'workflow_step' AND scope = 'analysis' AND key = 'confirm_execute';


-- ============================================================
-- C. Content `confirm_execute` — add execution_preview field
-- ============================================================
UPDATE geo_workflow_config
SET value = '{
  "num": 7,
  "label": "确认执行 (Confirm)",
  "description": "复核向导配置后触发执行",
  "fields": [
    {
      "key": "execution_preview",
      "type": "execution_preview",
      "label": "执行流程",
      "config": {
        "steps": [
          { "name": "strategy_generation", "label": "策略生成",   "description": "基于分析报告生成内容策略" },
          { "name": "content_generation",  "label": "内容生成",   "description": "按策略 + RATF 框架生成内容" },
          { "name": "quality_review",      "label": "质量评审",   "description": "评估内容质量并给出优化建议" }
        ]
      }
    }
  ]
}'::jsonb,
    sort_order = 7
WHERE config_type = 'workflow_step' AND scope = 'content_generation' AND key = 'confirm_execute';


COMMIT;

-- ============================================================
-- Verification queries
-- ============================================================
-- 1. Check admin_only flag on disable_user_edit
-- SELECT key, value->'fields' AS fields
-- FROM geo_workflow_config
-- WHERE config_type='workflow_step' AND scope='analysis' AND key='prompt_edit';
--
-- 2. Check execution_preview fields
-- SELECT key, scope, value->'fields' AS fields
-- FROM geo_workflow_config
-- WHERE config_type='workflow_step' AND key='confirm_execute';
