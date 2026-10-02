-- Migration 084: Strengthen Citation Alignment Quality Gate for AI-citable content templates
--
-- Context:
--   Migration 083 created the two citation-first templates. After 083 was first
--   executed, the application added stronger Citation Alignment review support:
--   configurable alignment markers and optional LLM/hybrid citation review.
--
-- Purpose:
--   Patch existing template rows so the new code path is active in production.
--
-- Safe to re-run:
--   Yes. This migration only merges JSONB quality_gate keys for the two named
--   built-in content_generation templates.

BEGIN;

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate}',
  COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || '{
    "enabled": true,
    "min_overall_score": 8,
    "revise_below_score": true,
    "citation_alignment_as_blocker": true,
    "citation_alignment_review_mode": "hybrid",
    "citation_alignment_markers": {
      "new_content_gap": ["brand fit", "use case", "workflow", "citation gap", "missing coverage"],
      "refresh_extractability": ["brand fit", "feature", "benefit", "faq", "internal link", "extractability"],
      "clarification_rebuttal": ["clarification", "correct", "misleading", "comparison", "troubleshooting"]
    },
    "max_revise_attempts": 1,
    "blocker_score_cap": 6,
    "warning_score_cap": 8,
    "llm_issue_blocker_patterns": ["重复结尾", "重复 FAQ", "残缺", "未完成句", "结构性错误", "duplicate ending", "duplicate FAQ", "unfinished sentence", "structural error"]
  }'::jsonb,
  true
)
WHERE t.task_type = 'content_generation'
  AND t.name IN (
    'Reddit AI Citable Post Generator',
    'Official Website AI Citable Article'
  );

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate}',
  COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || '{
    "revise_on_warning_rule_ids": ["multiple_faq_sections", "duplicate_h2_heading"],
    "rules": [
      {"id": "single_tldr", "type": "max_occurrences", "severity": "blocker", "pattern": "TL;DR", "max": 1},
      {"id": "fake_benchmark", "type": "forbidden_patterns", "severity": "blocker", "patterns": ["I spent \\\\d+ days testing", "master spreadsheet", "tested every major"]},
      {"id": "multiple_faq_sections", "type": "max_heading_occurrences", "severity": "warning", "heading_patterns": ["FAQ", "Frequently Asked Questions"], "max": 1},
      {"id": "duplicate_h2_heading", "type": "duplicate_heading", "level": 2, "severity": "warning"}
    ]
  }'::jsonb,
  true
)
WHERE t.task_type = 'content_generation'
  AND t.name = 'Reddit AI Citable Post Generator';

UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
  COALESCE(t.wizard_config, '{}'::jsonb),
  '{quality_gate}',
  COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || '{
    "revise_on_warning_rule_ids": ["multiple_faq_sections", "duplicate_h2_heading", "final_thoughts_and_conclusion", "duplicate_direct_answer"],
    "rules": [
      {"id": "brand_fit_summary", "type": "required_heading", "severity": "blocker", "any_of": ["Brand Fit Summary", "Where Dreamina Fits", "Where the Brand Fits"]},
      {"id": "feature_to_benefit_mapping", "type": "required_table", "severity": "blocker", "near_heading_any_of": ["Feature-to-Benefit Mapping", "Feature to Benefit Mapping"]},
      {"id": "internal_linking_suggestions", "type": "required_heading", "severity": "blocker", "any_of": ["Internal Linking Suggestions", "Suggested Internal Links"]},
      {"id": "value_dream_mini_benefits", "type": "required_heading", "severity": "blocker", "any_of": ["Value, Dream, Mini-benefits", "Value / Dream / Mini-benefits", "Value Dream Mini-benefits"]},
      {"id": "unsupported_hype_terms", "type": "forbidden_terms", "severity": "warning", "terms": ["definitive", "guarantee", "guarantees", "viral-ready", "ultimate", "unparalleled"]},
      {"id": "multiple_faq_sections", "type": "max_heading_occurrences", "severity": "warning", "heading_patterns": ["FAQ", "Frequently Asked Questions"], "max": 1},
      {"id": "duplicate_h2_heading", "type": "duplicate_heading", "level": 2, "severity": "warning"},
      {"id": "final_thoughts_and_conclusion", "type": "cooccurring_headings", "severity": "warning", "heading_patterns": ["Final thoughts", "Conclusion"]},
      {"id": "duplicate_direct_answer", "type": "max_heading_occurrences", "severity": "warning", "heading_patterns": ["Direct Answer"], "max": 1}
    ]
  }'::jsonb,
  true
)
WHERE t.task_type = 'content_generation'
  AND t.name = 'Official Website AI Citable Article';

COMMIT;

-- Verification:
-- SELECT name,
--        wizard_config#>>'{quality_gate,citation_alignment_review_mode}' AS citation_alignment_review_mode,
--        wizard_config#>'{quality_gate,citation_alignment_markers}' AS citation_alignment_markers,
--        jsonb_array_length(COALESCE(wizard_config#>'{quality_gate,rules}', '[]'::jsonb)) AS rule_count
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name IN ('Reddit AI Citable Post Generator', 'Official Website AI Citable Article')
-- ORDER BY name;
