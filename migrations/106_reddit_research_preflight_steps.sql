-- Migration 106: Reddit Research preflight wizard steps
--
-- Purpose:
--   Move Reddit-native targeting, deterministic Reddit discovery, and prompt
--   artifact preparation into explicit, template-enabled wizard steps.
--
-- Safe to re-run:
--   Yes. workflow_step rows are upserted, and template JSON is merged.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Workflow steps: Reddit Research group
-- ---------------------------------------------------------------------------
INSERT INTO geo_workflow_config (config_type, scope, key, value, sort_order, is_active)
VALUES
(
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

-- ---------------------------------------------------------------------------
-- 2) Hide Reddit Research steps for all content templates by default
-- ---------------------------------------------------------------------------
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
      '{steps,prompt_artifact_preparation}',
      COALESCE(wizard_config#>'{steps,prompt_artifact_preparation}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
      true
    ),
    '{steps,reddit_discovery}',
    COALESCE(wizard_config#>'{steps,reddit_discovery}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
    true
  )
WHERE task_type = 'content_generation';

-- ---------------------------------------------------------------------------
-- 3) Enable the new Reddit Research path only for Reddit-profile templates
-- ---------------------------------------------------------------------------
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
reddit_research_config AS (
  SELECT
    '{
      "enabled": true,
      "provider": "web_grounded",
      "provider_config": {
        "web_grounded": {
          "web_fetch_enabled": true,
          "grounding_model_id": "gemini-3-flash-preview",
          "request_timeout_seconds": 20,
          "fetch_user_agent": "AnswerX-GEO/1.0",
          "max_subreddit_candidates": 12,
          "max_posts_per_subreddit": 10
        }
      },
      "subreddit_targeting": {
        "modes": ["ai_recommend", "manual"],
        "default_mode": "ai_recommend",
        "candidate_policy": "Gemini Search Grounding may recommend subreddit candidates, but it must not create subreddit rules, vote counts, comments, or community evidence."
      },
      "reddit_discovery": {
        "source_policy": "Rules, sidebar metadata, and sampled posts must come from deterministic web fetch or approved Reddit API responses.",
        "rules_policy": "verified_rules_only",
        "unavailable_rules_behavior": "surface_unavailable_and_continue_without_inventing_rules"
      },
      "artifact_preparation": {
        "source": "wizard_confirmed",
        "reuse_confirmed_artifacts_in_final_generation": true,
        "allow_manual_edit": true,
        "do_not_depend_on_official_website_discovery": true
      }
    }'::jsonb AS reddit_research,
    '{
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
    }'::jsonb AS reddit_research_step
)
UPDATE geo_report_templates AS t
SET wizard_config =
  jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              COALESCE(t.wizard_config, '{}'::jsonb),
              '{reddit_research}',
              COALESCE(t.wizard_config->'reddit_research', '{}'::jsonb) || cfg.reddit_research,
              true
            ),
            '{steps,reddit_research}',
            COALESCE(t.wizard_config#>'{steps,reddit_research}', '{}'::jsonb) || cfg.reddit_research_step,
            true
          ),
          '{steps,reddit_discovery}',
          COALESCE(t.wizard_config#>'{steps,reddit_discovery}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
          true
        ),
        '{steps,prompt_artifact_preparation}',
        COALESCE(t.wizard_config#>'{steps,prompt_artifact_preparation}', '{}'::jsonb) || '{"enabled": false}'::jsonb,
        true
      ),
      '{derived_prompt_artifacts,instruction}',
      to_jsonb('Compress raw Strategy, Citation, Reddit Discover, selected prompts, and brand context into Reddit-native prompt artifacts. Do not copy raw internal framework language. Do not invent facts, first-hand testing, subreddit evidence, benchmarks, votes, screenshots, prices, or usage claims. Do not depend on Official Website Discovery for Reddit templates. The output should be concise enough to be safely injected into the final Reddit drafting prompt.'::text),
      true
    ),
    '{experience_style_notes,purpose}',
    to_jsonb('Convert Reddit Discover, Citation, target prompts, and strategy into writing-perspective material. These notes are not factual claims and must not depend on Official Website Discovery.'::text),
    true
  )
FROM reddit_research_config cfg
WHERE t.id IN (SELECT id FROM reddit_templates);

-- ---------------------------------------------------------------------------
-- 4) Execution preview: final generation reuses confirmed artifacts
-- ---------------------------------------------------------------------------
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
                "description": "基于模板配置、用户输入和已确认的研究结果生成或复用内容策略"
              },
              {
                "name": "artifact_preparation",
                "label": "Artifact Preparation",
                "description": "复用 Wizard 已确认的 Prompt artifacts；若模板要求确认且 artifacts 缺失或过期，最终生成会阻断并提示用户返回 Artifact Preparation"
              },
              {
                "name": "content_generation",
                "label": "内容生成",
                "description": "注入模板默认指令、平台规则、品牌画像、Citation Brief 与已确认 artifacts 生成内容"
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
  AND (parent_key IS NULL OR parent_key = '');

COMMIT;

-- Verification:
-- SELECT key, value->>'num' AS num, value->>'label' AS label, value->'fields' AS fields
-- FROM geo_workflow_config
-- WHERE scope = 'content_generation'
--   AND config_type = 'workflow_step'
--   AND key IN ('reddit_research', 'subreddit_targeting', 'reddit_discovery', 'prompt_artifact_preparation')
-- ORDER BY (value->>'num')::numeric;
--
-- SELECT name,
--        wizard_config#>>'{steps,reddit_research,enabled}' AS reddit_research_step,
--        wizard_config#>>'{steps,subreddit_targeting,enabled}' AS old_subreddit_targeting,
--        wizard_config#>>'{steps,reddit_discovery,enabled}' AS old_reddit_discovery,
--        wizard_config#>>'{steps,prompt_artifact_preparation,enabled}' AS old_artifact_preparation,
--        jsonb_pretty(wizard_config->'reddit_research') AS reddit_research
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     defaults->>'platform_profile' = 'reddit'
--     OR wizard_config->>'platform_profile' = 'reddit'
--     OR defaults->>'publish_platform' = 'reddit'
--     OR name ILIKE '%Reddit%'
--   )
-- ORDER BY name;
