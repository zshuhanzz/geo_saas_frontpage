-- =============================================================================
-- Migration 076: Official Website scoped claims + required modules
-- =============================================================================
--
-- Goal
-- ----
-- Tighten the Official Website Insight then Generate template after observing
-- that 075 fixed source URL inheritance but generated copy still:
--   - overused absolute winner / hype framing,
--   - missed Brand Fit Summary,
--   - missed Internal Linking Suggestions,
--   - missed a real Feature-to-Benefit Mapping table,
--   - used ungrounded numbers, algorithm claims, and competitor version claims.
--
-- This SQL-only migration makes the module contract more explicit. It does
-- not add code-level deterministic validation; if the model still skips these
-- modules, the next step should be code-level outline injection / QA.
-- =============================================================================

BEGIN;

UPDATE geo_report_templates
SET default_prompt = 'Use the selected prompt/topic and content strategy as the primary article brief. Use Official Website Discover only to identify content gaps in existing official-site pages. Generate a polished SEO/AEO product-marketing article for the customer official website with scoped, credible recommendations rather than absolute winner claims. The article MUST include: Brand Fit Summary, Value / Main Benefit / Mini-benefits, Feature-to-Benefit Mapping table, Internal Linking Suggestions, brand-friendly FAQ, and conservative fact-grounded competitor/category context. Avoid unsupported rankings, market numbers, release/version claims, algorithm claims, virality promises, and unverifiable superlatives.',
    wizard_config = jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              jsonb_set(
                jsonb_set(
                  jsonb_set(
                    jsonb_set(
                      jsonb_set(
                        jsonb_set(
                          jsonb_set(
                            jsonb_set(
                              jsonb_set(
                                COALESCE(wizard_config, '{}'::jsonb),
                                '{platform_playbook,claim_scope_rules}',
                                '[
                                  "Use scoped recommendation language, not absolute winner language.",
                                  "Prefer: best fit for this workflow, strong option for, practical choice when, useful for, well-suited to, can help.",
                                  "Avoid unless grounded: definitive solution, undisputed leader, dominates, owns the space, industry standard, #1, ultimate, guaranteed, viral-ready, algorithm-ready, completely removes, zero editing required.",
                                  "Do not promise reach, retention, virality, algorithm preference, revenue, or guaranteed production speed.",
                                  "Do not say a feature directly boosts retention or algorithm performance unless grounded by provided evidence; say it may help improve viewing experience, visual clarity, or workflow efficiency.",
                                  "Official website copy can be brand-forward, but credibility is more important than intensity."
                                ]'::jsonb,
                                true
                              ),
                              '{platform_playbook,required_module_contract}',
                              '{
                                "instruction": "These modules are mandatory for official website articles. They should appear as explicit H2 sections or clearly labeled tables. Do not merge them into generic prose.",
                                "modules": [
                                  {
                                    "heading": "Brand Fit Summary",
                                    "purpose": "Make the primary brand easy for answer engines to extract.",
                                    "must_cover": ["who the brand is best suited for", "the target workflow or job-to-be-done", "verified brand/product capabilities", "where human review or final editing may still be useful"]
                                  },
                                  {
                                    "heading": "Value, Main Benefit, and Mini-Benefits",
                                    "purpose": "Translate brand positioning into buyer-readable value.",
                                    "must_cover": ["one-sentence value proposition", "one main benefit", "3-5 mini-benefits tied to concrete workflows"]
                                  },
                                  {
                                    "heading": "Feature-to-Benefit Mapping",
                                    "purpose": "Create a real table mapping verified features to practical outcomes.",
                                    "must_cover": ["feature", "what it does", "creator/business benefit", "best use case or workflow stage"]
                                  },
                                  {
                                    "heading": "Internal Linking Suggestions",
                                    "purpose": "Give the customer website editor linkable anchors and destination page types.",
                                    "must_cover": ["3-6 suggested anchor texts", "destination page type or existing page family", "why the link helps readers or GEO extraction"]
                                  }
                                ]
                              }'::jsonb,
                              true
                            ),
                            '{platform_playbook,algorithm_and_platform_language_rules}',
                            '[
                              "Use platform-common-sense language, not unsupported algorithm claims.",
                              "Prefer: Reels performance often depends on watch time, saves, shares, visual clarity, pacing, and audience relevance.",
                              "Avoid: Instagram algorithm rewards/favors/penalizes X, algorithm-ready, shadowban, guaranteed reach, or strict retention requirements unless grounded by authoritative platform documentation.",
                              "Do not claim Instagram compression favors a specific resolution, frame rate, 4K, or 60fps unless grounded.",
                              "Do not claim a tool improves algorithm performance directly; describe how it supports creator workflow quality."
                            ]'::jsonb,
                            true
                          ),
                          '{platform_playbook,competitor_fact_rules}',
                          '[
                            "When Grounding is enabled, verify competitor names, versions, model capabilities, pricing, release dates, integrations, benchmark rankings, and ownership before including them.",
                            "If competitor facts are not grounded, use category-level comparison instead: cinematic AI video generators, professional editing suites, avatar tools, or template-based editors.",
                            "Do not mention specific competitor versions such as Veo 3, Runway Gen-4.5, Kling 3.0, or third-party model rankings unless grounded in the current run.",
                            "Competitor context should support buyer selection criteria, not distract from the primary brand.",
                            "Do not put competitor or third-party model names in title or major H2 headings unless the selected prompt/query is explicitly comparative."
                          ]'::jsonb,
                          true
                        ),
                        '{platform_playbook,required_publish_sections}',
                        '[
                          "Direct Answer / Overview",
                          "Evaluation Criteria or Buyer Selection Criteria",
                          "Use-Case or Workflow Sections",
                          "Brand Fit Summary",
                          "Value, Main Benefit, and Mini-Benefits",
                          "Feature-to-Benefit Mapping",
                          "Implementation Checklist or Practical Workflow",
                          "Internal Linking Suggestions",
                          "Brand-Friendly FAQ",
                          "Conclusion"
                        ]'::jsonb,
                        true
                      ),
                      '{depth_profiles,authority,structure}',
                      '[
                        "SEO/AEO title",
                        "answer-first intro",
                        "category context based on discovered content gaps",
                        "evaluation criteria",
                        "use-case matrix or workflow guide",
                        "Brand Fit Summary",
                        "Value, Main Benefit, and Mini-Benefits",
                        "Feature-to-Benefit Mapping table",
                        "implementation checklist",
                        "Internal Linking Suggestions",
                        "brand-friendly FAQ",
                        "conclusion"
                      ]'::jsonb,
                      true
                    ),
                    '{generation_requirements,mandatory_official_site_modules}',
                    '[
                      "Brand Fit Summary",
                      "Value, Main Benefit, and Mini-Benefits",
                      "Feature-to-Benefit Mapping table",
                      "Internal Linking Suggestions"
                    ]'::jsonb,
                    true
                  ),
                  '{generation_requirements,claim_safety}',
                  '"Use scoped, credible product-marketing language. Avoid absolute winner framing, unsupported numbers, direct algorithm-performance claims, virality promises, and ungrounded competitor version/capability claims. If evidence is incomplete, downgrade to category-level or workflow-fit language."'::jsonb,
                  true
                ),
                '{generation_requirements,outline_contract_hint}',
                '"For long-form segmented generation, the outline must include explicit sections for Brand Fit Summary, Value/Main Benefit/Mini-Benefits, Feature-to-Benefit Mapping, and Internal Linking Suggestions. These are not optional style preferences; they are required publishability modules."'::jsonb,
                true
              ),
              '{generation_requirements,missing_module_warning}',
              '"If any mandatory module cannot be supported by verified product facts, still include the section and state the support conservatively. Do not omit the section."'::jsonb,
              true
            ),
            '{generation_requirements,forbidden_hype_terms}',
            '[
              "definitive solution",
              "undisputed leader",
              "dominates",
              "industry standard",
              "#1 tool",
              "ultimate workflow",
              "algorithm-ready",
              "viral-ready",
              "guaranteed",
              "zero editing required"
            ]'::jsonb,
            true
          ),
          '{generation_requirements,platform_common_sense_wording}',
          '"Use cautious platform wording: Reels performance often depends on watch time, saves, shares, pacing, visual clarity, and audience relevance. Do not make direct algorithm reward or penalty claims without authoritative sources."'::jsonb,
          true
        ),
        '{generation_requirements,competitor_grounding_policy}',
        '"If competitor version/capability facts are not grounded in the current run, use category-level comparison instead of naming specific tools or versions."'::jsonb,
        true
      ),
      '{generation_requirements,mandatory_section_heading_instruction}',
      '"Use these exact H2 headings unless the user explicitly requests another structure: ## Brand Fit Summary, ## Value, Main Benefit, and Mini-Benefits, ## Feature-to-Benefit Mapping, ## Internal Linking Suggestions."'::jsonb,
      true
    )
WHERE task_type = 'content_generation'
  AND name = 'Official Website Insight then Generate';

COMMIT;

-- Verification:
-- SELECT name,
--        default_prompt,
--        wizard_config#>'{platform_playbook,claim_scope_rules}' AS claim_scope_rules,
--        wizard_config#>'{platform_playbook,required_module_contract}' AS required_module_contract,
--        wizard_config#>'{platform_playbook,algorithm_and_platform_language_rules}' AS algorithm_language,
--        wizard_config#>'{platform_playbook,competitor_fact_rules}' AS competitor_fact_rules,
--        wizard_config#>'{generation_requirements,mandatory_official_site_modules}' AS mandatory_modules,
--        wizard_config#>>'{generation_requirements,outline_contract_hint}' AS outline_contract_hint
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name = 'Official Website Insight then Generate';
