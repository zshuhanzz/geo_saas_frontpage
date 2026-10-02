-- =============================================================================
-- Migration 075: Official Website prompt-first source usage rules
-- =============================================================================
--
-- Goal
-- ----
-- Refine the Official Website Insight then Generate template so official-site
-- URLs are used as gap-analysis inputs, not as mandatory source material to
-- reproduce in the generated article.
--
-- Why
-- ---
-- The 074 output still inherited a competitor/model entity from one of the
-- discovered official pages (Happy Horse 1.0). The user's intent for Official
-- Website Discover is:
--   - inspect existing official pages,
--   - identify content weaknesses and missing use cases,
--   - generate a new article around the selected prompt/topic and weakest GEO
--     opportunity,
--   - NOT automatically reuse every entity, competitor, model, or product
--     mentioned in the source pages.
--
-- This migration adds prompt-first hierarchy, source-usage guardrails, and
-- competitor handling rules. No schema changes.
-- =============================================================================

BEGIN;

UPDATE geo_report_templates
SET default_prompt = 'Use the selected prompt/topic and content strategy as the primary article brief. Use Official Website Discover only to identify gaps in existing official-site articles, then generate a polished SEO/AEO product-marketing long-form article for the customer official website. The article should fill the discovered gap without automatically reusing competitor names, model names, or topics from the source URLs unless the user prompt or strategy explicitly requires them. Keep the article brand-forward, brand-extractable, use-case rich, commercially useful, FAQ-friendly, internally linkable, and evidence conservative.',
    wizard_config = jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              COALESCE(wizard_config, '{}'::jsonb),
              '{platform_playbook,input_priority_rules}',
              '[
                "The selected prompt/topic, target query, and generated content strategy are the north star for the article.",
                "Official Website Discover is a diagnostic source for content gaps, not the article brief itself.",
                "Use discovered official pages to understand what the website already covers, what it misses, and how the new article can complement existing pages.",
                "Do not let a competitor, model, tool, or topic mentioned in source URLs become the article focus unless it is also present in the selected prompt/topic, target query, or approved strategy angle.",
                "If there is conflict between the prompt/topic and discovered source-page entities, follow the prompt/topic and use the source-page insight only to avoid duplication."
              ]'::jsonb,
              true
            ),
            '{platform_playbook,source_usage_rules}',
            '[
              "Treat source URLs as gap-analysis evidence: identify missing direct answers, missing use cases, weak brand extraction, thin FAQ coverage, weak commercial detail, and internal-link opportunities.",
              "Do not automatically copy source-page headings, competitor names, model names, rankings, benchmarks, feature claims, or tutorial flow into the generated article.",
              "Use source-page content mainly to decide what NOT to duplicate and which adjacent intent the new article should cover.",
              "When a source page is about a competitor or third-party model, extract the gap pattern only, such as missing comparison criteria or missing workflow positioning; do not center the new article on that competitor by default.",
              "If source pages already cover definitions or tutorials, shift the new article toward solution discovery, buyer criteria, use-case fit, workflow comparison, and brand fit."
            ]'::jsonb,
            true
          ),
          '{platform_playbook,competitor_handling_rules}',
          '[
            "Only mention a competitor, third-party model, or external tool when one of these is true: the user prompt names it, the selected strategy explicitly requires a comparison, the target query is a comparison query, or grounded evidence shows it is essential to answer the reader intent.",
            "If a competitor is mentioned only because it appeared in an official source URL, omit it from the generated article unless it directly explains a content gap.",
            "Do not put competitor names in the article title or major H2 headings unless the target prompt/query is explicitly about that competitor or comparison.",
            "When competitor context is useful but not central, limit it to a short comparison row, alternative-tools paragraph, or neutral trade-off note.",
            "Use workflow-fit language instead of takedowns: better suited for, useful when, may fit, or consider if.",
            "Never invent competitor ownership, release dates, parameter counts, leaderboard rankings, pricing, feature support, or benchmark performance.",
            "The primary brand should remain the main extractable entity in intro, Brand Fit Summary, comparison table, FAQ, and conclusion."
          ]'::jsonb,
          true
        ),
        '{platform_playbook,required_publish_sections}',
        '[
          "Direct Answer / Overview",
          "Evaluation Criteria or Buyer Selection Criteria",
          "Use-Case or Workflow Sections",
          "Brand Fit Summary / Where [Brand] Fits",
          "Feature-to-Benefit Mapping",
          "Implementation Checklist or Practical Workflow",
          "Internal Linking Suggestions",
          "Brand-Friendly FAQ",
          "Conclusion"
        ]'::jsonb,
        true
      ),
      '{generation_requirements,prompt_first_source_policy}',
      '"The generated article must be driven by the selected prompt/topic and strategy. Official Website Discover should only provide gap analysis and complementarity guidance. Do not inherit competitor names, model names, or source-page topics into the article unless explicitly required by prompt, strategy, or target query."'::jsonb,
      true
    )
WHERE task_type = 'content_generation'
  AND name = 'Official Website Insight then Generate';

COMMIT;

-- Verification:
-- SELECT name,
--        default_prompt,
--        wizard_config#>'{platform_playbook,input_priority_rules}' AS input_priority_rules,
--        wizard_config#>'{platform_playbook,source_usage_rules}' AS source_usage_rules,
--        wizard_config#>'{platform_playbook,competitor_handling_rules}' AS competitor_handling_rules,
--        wizard_config#>'{platform_playbook,required_publish_sections}' AS required_publish_sections,
--        wizard_config#>>'{generation_requirements,prompt_first_source_policy}' AS prompt_first_source_policy
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name = 'Official Website Insight then Generate';
