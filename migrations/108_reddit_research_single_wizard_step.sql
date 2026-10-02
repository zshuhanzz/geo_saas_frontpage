-- Migration 108: Collapse Reddit Research substages into one Wizard step
--
-- Purpose:
--   106 originally modeled Subreddit Targeting, Reddit Discovery, and
--   Artifact Preparation as three separate Wizard steps with a shared group.
--   The SaaS Wizard renders groups as labels, not containers, so Reddit users
--   saw separate steps. This migration creates one visible Reddit Research
--   step with the three substages as ordered fields.
--
-- Safe to re-run:
--   Yes. Upserts the canonical step, disables the old standalone rows, and
--   rewrites only template step visibility/defaults for Reddit Research.

BEGIN;

INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES (
  'workflow_step',
  'content_generation',
  'reddit_research',
  '{
    "num": 2.45,
    "label": "Reddit Research",
    "default_enabled": false,
    "description": "确定目标社区、抓取社区规则与语境，并准备 Reddit-native Prompt artifacts。三个子环节在同一个 Wizard 页面内顺序执行。",
    "fields": [
      {
        "key": "subreddit_targeting_preflight",
        "type": "subreddit_targeting_preflight",
        "label": "Subreddit Targeting",
        "description": "选择 AI 推荐或手动输入 Subreddit。确认结果会作为 Reddit Discovery 的唯一输入。"
      },
      {
        "key": "reddit_discovery_preflight",
        "type": "reddit_discovery_preflight",
        "label": "Reddit Discovery",
        "description": "基于已确认的 Subreddit targets 抓取社区规则、sidebar 与公开帖子语境。规则只来自确定性抓取或 Reddit API。"
      },
      {
        "key": "prompt_artifact_preparation",
        "type": "prompt_artifact_preparation_preflight",
        "label": "Artifact Preparation",
        "description": "生成、查看、编辑并确认最终 Prompt 会引用的 Reddit-native artifacts。确认后最终生成不会重复调用模型准备这些 artifacts。"
      }
    ]
  }'::jsonb,
  245,
  true
)
ON CONFLICT (scope, config_type, key) WHERE parent_key IS NULL DO UPDATE
  SET value = EXCLUDED.value,
      sort_order = EXCLUDED.sort_order,
      is_active = true;

UPDATE geo_workflow_config
SET is_active = false
WHERE scope = 'content_generation'
  AND config_type = 'workflow_step'
  AND key IN ('subreddit_targeting', 'reddit_discovery', 'prompt_artifact_preparation')
  AND (parent_key IS NULL OR parent_key = '');

UPDATE geo_report_templates
SET wizard_config =
  jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          COALESCE(wizard_config, '{}'::jsonb),
          '{steps,reddit_research}',
          COALESCE(wizard_config#>'{steps,reddit_research}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
          true
        ),
        '{steps,subreddit_targeting}',
        COALESCE(wizard_config#>'{steps,subreddit_targeting}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
        true
      ),
      '{steps,reddit_discovery}',
      COALESCE(wizard_config#>'{steps,reddit_discovery}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
      true
    ),
    '{steps,prompt_artifact_preparation}',
    COALESCE(wizard_config#>'{steps,prompt_artifact_preparation}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
    true
  )
WHERE task_type = 'content_generation';

WITH reddit_templates AS (
  SELECT id
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      defaults->>'platform_profile' = 'reddit'
      OR wizard_config->>'platform_profile' = 'reddit'
      OR defaults->>'publish_platform' = 'reddit'
      OR wizard_config#>>'{steps,generation_config,default_publish_platform}' = 'reddit'
      OR name IN (
        'Reddit Article',
        'Reddit Insight then Generate',
        'Reddit AI Citable Post Generator'
      )
    )
),
reddit_research_step AS (
  SELECT '{
    "enabled": true,
    "__sort_override": 2.45,
    "__label_override": "Reddit Research",
    "__description_override": "Subreddit Targeting、Reddit Discovery 和 Artifact Preparation 在同一个页面内顺序执行。",
    "subreddit_targeting_preflight": {
      "mode": "ai_recommend",
      "status": "idle",
      "error": null
    },
    "reddit_discovery_preflight": {
      "status": "idle",
      "error": null
    },
    "prompt_artifact_preparation": {
      "status": "idle",
      "error": null
    }
  }'::jsonb AS value
)
UPDATE geo_report_templates AS t
SET wizard_config =
  jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          COALESCE(t.wizard_config, '{}'::jsonb),
          '{steps,reddit_research}',
          COALESCE(t.wizard_config#>'{steps,reddit_research}', '{}'::jsonb) || s.value,
          true
        ),
        '{steps,subreddit_targeting}',
        COALESCE(t.wizard_config#>'{steps,subreddit_targeting}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
        true
      ),
      '{steps,reddit_discovery}',
      COALESCE(t.wizard_config#>'{steps,reddit_discovery}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
      true
    ),
    '{steps,prompt_artifact_preparation}',
    COALESCE(t.wizard_config#>'{steps,prompt_artifact_preparation}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
    true
  )
FROM reddit_research_step s
WHERE t.id IN (SELECT id FROM reddit_templates);

COMMIT;

-- Verification:
-- SELECT key, value->>'num' AS num, value->>'label' AS label, is_active
-- FROM geo_workflow_config
-- WHERE scope='content_generation'
--   AND config_type='workflow_step'
--   AND key IN ('reddit_research','subreddit_targeting','reddit_discovery','prompt_artifact_preparation')
-- ORDER BY sort_order;
