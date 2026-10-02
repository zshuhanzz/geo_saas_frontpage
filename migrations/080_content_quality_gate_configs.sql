-- =============================================================================
-- Migration 080: Configurable content Quality Gate rules
-- =============================================================================
--
-- Goal
-- ----
-- Add deterministic post-generation QA configs to the templates that currently
-- need stricter publishability control:
--   - Official Website Insight then Generate
--   - Reddit Article
--   - Reddit Insight then Generate
--
-- These configs are consumed from geo_report_templates.wizard_config.quality_gate.
-- They do not change schema and do not execute any generated content revision
-- by themselves; the application code reads these rules during Quality Review.
-- =============================================================================

BEGIN;

UPDATE geo_report_templates
SET wizard_config = jsonb_set(
  COALESCE(wizard_config, '{}'::jsonb),
  '{quality_gate}',
  '{
    "enabled": true,
    "blocker_score_cap": 6.0,
    "warning_score_cap": 8.0,
    "max_revise_attempts": 1,
    "rules": [
      {
        "id": "official_brand_fit_summary_required",
        "type": "required_heading",
        "severity": "blocker",
        "any_of": ["Brand Fit Summary", "Where Dreamina fits", "Where Dreamina Fits", "Where the Brand Fits"]
      },
      {
        "id": "official_feature_to_benefit_table_required",
        "type": "required_table",
        "severity": "blocker",
        "near_heading_any_of": ["Feature-to-Benefit Mapping", "Feature to Benefit Mapping", "Feature-Benefit Mapping"]
      },
      {
        "id": "official_internal_linking_required",
        "type": "required_heading",
        "severity": "blocker",
        "any_of": ["Internal Linking Suggestions", "Suggested Internal Links", "Internal Linking Plan"]
      },
      {
        "id": "official_faq_required",
        "type": "required_heading",
        "severity": "blocker",
        "any_of": ["Frequently Asked Questions", "FAQ", "FAQs"]
      },
      {
        "id": "official_high_risk_marketing_terms",
        "type": "forbidden_terms",
        "severity": "warning",
        "terms": [
          "ultimate",
          "definitive",
          "unparalleled",
          "dominates",
          "guaranteed",
          "viral-ready",
          "algorithm-ready",
          "zero editing",
          "eliminates",
          "best overall",
          "undisputed"
        ]
      },
      {
        "id": "official_unverified_numeric_or_result_claims",
        "type": "forbidden_patterns",
        "severity": "warning",
        "patterns": [
          "\\b\\d+\\s+(hours?|minutes?|seconds?|tokens?|credits?)\\b",
          "\\b\\d+\\s?%\\b",
          "increases engagement",
          "boosts retention",
          "guarantees? viral",
          "dominates the Instagram"
        ]
      }
    ]
  }'::jsonb,
  true
)
WHERE task_type = 'content_generation'
  AND name = 'Official Website Insight then Generate';

UPDATE geo_report_templates
SET wizard_config = jsonb_set(
  COALESCE(wizard_config, '{}'::jsonb),
  '{quality_gate}',
  '{
    "enabled": true,
    "blocker_score_cap": 6.0,
    "warning_score_cap": 8.0,
    "max_revise_attempts": 1,
    "rules": [
      {
        "id": "reddit_single_tldr",
        "type": "max_occurrences",
        "severity": "blocker",
        "pattern": "TL;DR",
        "max": 1
      },
      {
        "id": "reddit_brand_fit_required",
        "type": "required_heading",
        "severity": "blocker",
        "any_of": ["Brand Fit Summary", "Where Dreamina fits", "Where Dreamina Fits", "Where the brand fits"]
      },
      {
        "id": "reddit_fake_benchmark_claims",
        "type": "forbidden_patterns",
        "severity": "blocker",
        "patterns": [
          "I spent \\d+ days testing",
          "tested every major",
          "benchmark data",
          "master spreadsheet",
          "score out of 10",
          "RTX 4090"
        ]
      },
      {
        "id": "reddit_high_risk_platform_claims",
        "type": "forbidden_patterns",
        "severity": "warning",
        "patterns": [
          "algorithm actively (buries|penalizes|rewards)",
          "will shadowban",
          "shadowbanned",
          "guaranteed reach",
          "community consensus",
          "strictly enforced"
        ]
      },
      {
        "id": "reddit_duplicate_ending_terms",
        "type": "max_occurrences",
        "severity": "warning",
        "pattern": "## Conclusion",
        "max": 1
      }
    ]
  }'::jsonb,
  true
)
WHERE task_type = 'content_generation'
  AND name IN ('Reddit Article', 'Reddit Insight then Generate');

COMMIT;

-- Verification:
-- SELECT name,
--        wizard_config#>'{quality_gate}' AS quality_gate
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN (
--     'Official Website Insight then Generate',
--     'Reddit Article',
--     'Reddit Insight then Generate'
--   )
-- ORDER BY name;
