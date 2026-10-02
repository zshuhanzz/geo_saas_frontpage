-- =============================================================================
-- Migration 082: Quality Gate v2 revise triggers
-- =============================================================================
--
-- Adds stricter, template-configured QA behavior for content_generation:
--   - overall_score < 8 triggers Revise
--   - LLM review issues mentioning duplicate endings, duplicate FAQ,
--     incomplete lines, or structural errors are upgraded to blockers
--   - deterministic heading checks emit warnings
--   - selected structural warnings trigger Revise
--
-- Requires application code that understands:
--   min_overall_score, revise_below_score, llm_issue_blocker_patterns,
--   revise_on_warning_rule_ids, duplicate_heading, max_heading_occurrences,
--   cooccurring_headings.
-- =============================================================================

BEGIN;

-- Official Website: strict publishability and GEO/AEO structure.
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
  COALESCE(wizard_config, '{}'::jsonb),
  '{quality_gate}',
  jsonb_set(
    COALESCE(wizard_config->'quality_gate', '{}'::jsonb) ||
    '{
      "min_overall_score": 8.0,
      "revise_below_score": true,
      "llm_issue_blocker_patterns": ["重复结尾", "重复 FAQ", "残缺", "未完成句", "结构性错误"],
      "revise_on_warning_rule_ids": [
        "official_duplicate_h2_heading",
        "official_multiple_faq_sections",
        "official_final_thoughts_and_conclusion",
        "official_final_source_and_conclusion",
        "official_duplicate_direct_answer"
      ]
    }'::jsonb,
    '{rules}',
    (
      SELECT COALESCE(jsonb_agg(existing_rule), '[]'::jsonb)
      FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,rules}', '[]'::jsonb)) AS existing(existing_rule)
      WHERE NOT (
        existing_rule->>'id' = ANY (ARRAY[
          'official_duplicate_h2_heading',
          'official_multiple_faq_sections',
          'official_final_thoughts_and_conclusion',
          'official_final_source_and_conclusion',
          'official_duplicate_direct_answer'
        ])
      )
    ) ||
    '[
      {
        "id": "official_duplicate_h2_heading",
        "type": "duplicate_heading",
        "severity": "warning",
        "level": 2
      },
      {
        "id": "official_multiple_faq_sections",
        "type": "max_heading_occurrences",
        "severity": "warning",
        "heading_patterns": ["FAQ", "Frequently Asked Questions"],
        "max": 1
      },
      {
        "id": "official_final_thoughts_and_conclusion",
        "type": "cooccurring_headings",
        "severity": "warning",
        "heading_patterns": ["Final thoughts", "Conclusion"]
      },
      {
        "id": "official_final_source_and_conclusion",
        "type": "cooccurring_headings",
        "severity": "warning",
        "heading_patterns": ["Final source", "Conclusion"]
      },
      {
        "id": "official_duplicate_direct_answer",
        "type": "max_heading_occurrences",
        "severity": "warning",
        "heading_patterns": ["Direct Answer"],
        "max": 1
      }
    ]'::jsonb,
    true
  ),
  true
)
WHERE task_type = 'content_generation'
  AND name = 'Official Website Insight then Generate';

-- Reddit templates: community-fit plus structural integrity.
UPDATE geo_report_templates
SET wizard_config = jsonb_set(
  COALESCE(wizard_config, '{}'::jsonb),
  '{quality_gate}',
  jsonb_set(
    COALESCE(wizard_config->'quality_gate', '{}'::jsonb) ||
    '{
      "min_overall_score": 8.0,
      "revise_below_score": true,
      "llm_issue_blocker_patterns": ["重复结尾", "重复 FAQ", "残缺", "未完成句", "结构性错误"],
      "revise_on_warning_rule_ids": [
        "reddit_duplicate_h2_heading",
        "reddit_multiple_faq_sections",
        "reddit_final_thoughts_and_conclusion",
        "reddit_final_source_and_conclusion"
      ]
    }'::jsonb,
    '{rules}',
    (
      SELECT COALESCE(jsonb_agg(existing_rule), '[]'::jsonb)
      FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,rules}', '[]'::jsonb)) AS existing(existing_rule)
      WHERE NOT (
        existing_rule->>'id' = ANY (ARRAY[
          'reddit_duplicate_h2_heading',
          'reddit_multiple_faq_sections',
          'reddit_final_thoughts_and_conclusion',
          'reddit_final_source_and_conclusion'
        ])
      )
    ) ||
    '[
      {
        "id": "reddit_duplicate_h2_heading",
        "type": "duplicate_heading",
        "severity": "warning",
        "level": 2
      },
      {
        "id": "reddit_multiple_faq_sections",
        "type": "max_heading_occurrences",
        "severity": "warning",
        "heading_patterns": ["FAQ", "Frequently Asked Questions"],
        "max": 1
      },
      {
        "id": "reddit_final_thoughts_and_conclusion",
        "type": "cooccurring_headings",
        "severity": "warning",
        "heading_patterns": ["Final thoughts", "Conclusion"]
      },
      {
        "id": "reddit_final_source_and_conclusion",
        "type": "cooccurring_headings",
        "severity": "warning",
        "heading_patterns": ["Final source", "Conclusion"]
      }
    ]'::jsonb,
    true
  ),
  true
)
WHERE task_type = 'content_generation'
  AND name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        wizard_config#>>'{quality_gate,min_overall_score}' AS min_score,
--        wizard_config#>>'{quality_gate,revise_below_score}' AS revise_below_score,
--        wizard_config#>'{quality_gate,revise_on_warning_rule_ids}' AS revise_warning_ids,
--        jsonb_path_query_array(wizard_config, '$.quality_gate.rules[*].id') AS rule_ids
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN (
--     'Official Website Insight then Generate',
--     'Reddit Article',
--     'Reddit Insight then Generate'
--   )
-- ORDER BY name;
