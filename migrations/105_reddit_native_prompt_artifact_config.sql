-- Migration 105: Reddit-native prompt artifact policy
--
-- Context:
--   Prompt-debug logs showed that Reddit templates now contain stronger
--   community-first instructions, but the final generation prompt can still be
--   pushed toward structured guide/blog output by raw Strategy, Citation,
--   Reddit Discover, and RATF subgoal text. In particular, global subgoal
--   descriptions can still mention lists/tables/summaries, while Strategy and
--   Citation artifacts can still look like internal planning documents.
--
-- Purpose:
--   1. Opt Reddit templates into prompt_input_policy.mode = reddit_native.
--   2. Hide raw internal framework artifacts from the final Reddit prompt and
--      replace them with concise Community Brief + Experience Style Notes.
--   3. Configure RATF subgoal rendering so Reddit templates do not inherit raw
--      table/matrix wording from global subgoal descriptions.
--   4. Add deterministic Reddit-native Quality Gate rules for the failure
--      modes surfaced in prompt logs.
--
-- Safe to re-run:
--   Yes. This migration overwrites only targeted Reddit template config keys
--   and de-duplicates the new Quality Gate rules by id before appending them.

BEGIN;

WITH reddit_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%reddit%'
      OR defaults->>'content_type' = 'reddit_article'
      OR defaults->>'publish_platform' = 'reddit'
      OR wizard_config->>'platform_profile' = 'reddit'
    )
),
new_rules AS (
  SELECT jsonb_build_array(
    jsonb_build_object(
      'id', 'reddit_opening_first_person_or_workflow_required',
      'type', 'first_paragraph_required_patterns',
      'severity', 'blocker',
      'patterns', jsonb_build_array(
        '\bI(?:''ve| have| am| still| usually| tend to| would)\b',
        '\bmy workflow\b',
        '\bwhat I(?:''d| would) test\b',
        '\bthe part that still feels\b',
        '\bthe workflow problem\b'
      ),
      'message', 'Reddit opening must start from a concrete first-person/workflow tension, not a broad industry-guide intro.'
    ),
    jsonb_build_object(
      'id', 'reddit_guide_structure_forbidden',
      'type', 'forbidden_patterns',
      'severity', 'blocker',
      'patterns', jsonb_build_array(
        '^\s{0,3}#{1,6}\s+Phase\s+\d+\b',
        '^\s{0,3}#{1,6}\s+Step[- ]by[- ]Step\b',
        '^\s{0,3}#{1,6}\s+Checklist\b',
        '^\s{0,3}#{1,6}\s+The Reality Check\b',
        '^\s{0,3}#{1,6}\s+Tradeoff Matrix\b',
        '^\s{0,3}#{1,6}\s+FAQ\b'
      ),
      'message', 'Reddit output must not use guide/blog framework headings or a default FAQ section.'
    ),
    jsonb_build_object(
      'id', 'reddit_strategy_artifact_language_forbidden',
      'type', 'forbidden_patterns',
      'severity', 'blocker',
      'patterns', jsonb_build_array(
        '\bBrand Fit Summary\b',
        '\bWhere\s+.+\s+Fits\b',
        '\bValue\s*/\s*Dream\s*/\s*Mini-benefits\b',
        '\bFeature-to-Benefit Mapping\b',
        '\bCitation Analysis\b',
        '\bQuality Gate\b',
        '\bRATF\b',
        '\bstrategy brief\b',
        '\bprompt input\b'
      ),
      'message', 'Remove internal strategy/framework artifacts from publishable Reddit content.'
    ),
    jsonb_build_object(
      'id', 'reddit_marketing_voice_forbidden_v2',
      'type', 'forbidden_patterns',
      'severity', 'blocker',
      'patterns', jsonb_build_array(
        '\bconsensus among creators\b',
        '\bbrand-safe visual control\b',
        '\bplatform-ready\b',
        '\bscroll-stopping\b',
        '\bhigh-volume creators\b',
        '\bindustry-leading\b',
        '\bhighly recommended\b',
        '\bunlock\b',
        '\bseamless\b',
        '\belevate your\b'
      ),
      'message', 'Reddit content must avoid polished marketing language and AI-product brochure phrasing.'
    ),
    jsonb_build_object(
      'id', 'reddit_discussion_question_required',
      'type', 'ending_required_patterns',
      'severity', 'blocker',
      'patterns', jsonb_build_array(
        '\?\s*$'
      ),
      'message', 'Reddit content must end with a real discussion question, not a CTA or summary slogan.'
    ),
    jsonb_build_object(
      'id', 'reddit_dynamic_brand_mentions_limited',
      'type', 'dynamic_brand_mention_count',
      'severity', 'blocker',
      'max', 4,
      'message', 'Brand mentions are too frequent for a Reddit-native post; keep the brand inside workflow or tool-stack context.'
    ),
    jsonb_build_object(
      'id', 'reddit_standalone_brand_heading_forbidden',
      'type', 'forbidden_standalone_brand_section',
      'severity', 'blocker',
      'message', 'Reddit content must not create a standalone brand section; mention the brand only inside natural workflow context.'
    )
  ) AS rules
),
prepared AS (
  SELECT
    rt.id,
    COALESCE(rt.wizard_config, '{}'::jsonb) AS wizard_config,
    COALESCE(rt.wizard_config->'quality_gate', '{}'::jsonb) AS existing_quality_gate,
    COALESCE(
      (
        SELECT jsonb_agg(rule)
        FROM jsonb_array_elements(COALESCE(rt.wizard_config#>'{quality_gate,rules}', '[]'::jsonb)) AS existing(rule)
        WHERE existing.rule->>'id' NOT IN (
          'reddit_opening_first_person_or_workflow_required',
          'reddit_guide_structure_forbidden',
          'reddit_strategy_artifact_language_forbidden',
          'reddit_marketing_voice_forbidden_v2',
          'reddit_discussion_question_required',
          'reddit_dynamic_brand_mentions_limited',
          'reddit_standalone_brand_heading_forbidden'
        )
      ),
      '[]'::jsonb
    ) AS retained_rules,
    new_rules.rules AS new_rules
  FROM reddit_templates rt
  CROSS JOIN new_rules
)
UPDATE geo_report_templates AS t
SET wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              jsonb_set(
                prepared.wizard_config,
                '{prompt_input_policy}',
                jsonb_build_object(
                  'mode', 'reddit_native',
                  'hide_internal_frameworks', true,
                  'hide_raw_strategy_dimensions', true,
                  'hide_raw_reddit_discover', true,
                  'hide_raw_official_discover', true,
                  'hide_raw_citation_analysis', true,
                  'data_disclosure_policy', 'internal_only',
                  'visible_artifacts', jsonb_build_array(
                    'subreddit_community_rules',
                    'experience_style_notes',
                    'community_brief',
                    'reddit_native_contract'
                  )
                ),
                true
              ),
              '{derived_prompt_artifacts}',
              jsonb_build_object(
                'enabled', true,
                'materialization', 'llm_json',
                'max_output_tokens', 4096,
                'instruction', 'Compress raw Strategy, Citation, Reddit Discover, Official Discover, selected prompts, and brand context into Reddit-native prompt artifacts. Do not copy raw internal framework language. Do not invent facts, first-hand testing, subreddit evidence, benchmarks, votes, screenshots, prices, or usage claims. The output should be concise enough to be safely injected into the final Reddit drafting prompt.',
                'output_artifacts', jsonb_build_array(
                  jsonb_build_object(
                    'key', 'subreddit_community_rules',
                    'label', 'Subreddit Community Rules',
                    'description', 'Posting risks, norms, objections, and language to avoid, derived from Reddit Discover and selected prompts.',
                    'fields', jsonb_build_array(
                      'community_norms',
                      'posting_risks',
                      'skeptical_objections',
                      'forbidden_moves'
                    ),
                    'rules', jsonb_build_array(
                      'Keep this as community context, not as a published section.',
                      'Do not invent subreddit names, votes, screenshots, comments, or rules that were not in the inputs.'
                    )
                  ),
                  jsonb_build_object(
                    'key', 'experience_style_notes',
                    'label', 'Experience Style Notes',
                    'description', 'Writing-perspective scaffolding. It can create texture and cautious phrasing, but it is not a source of factual product claims.',
                    'fields', jsonb_build_array(
                      'persona_frame',
                      'workflow_texture',
                      'skeptical_phrases',
                      'allowed_experience_claims',
                      'forbidden_experience_claims'
                    ),
                    'rules', jsonb_build_array(
                      'Use this only to guide voice and perspective.',
                      'Do not claim first-hand usage, tests, benchmarks, or results unless the raw input explicitly provides them.',
                      'Prefer conditional or exploratory phrasing when product facts are missing.'
                    ),
                    'skeptical_phrases', jsonb_build_array(
                      'what I would test first',
                      'where this could still fall apart',
                      'the part I would not trust yet',
                      'where the workflow gets awkward'
                    )
                  ),
                  jsonb_build_object(
                    'key', 'community_brief',
                    'label', 'Community Brief',
                    'description', 'The only compressed upstream brief that the final Reddit drafting prompt should use.',
                    'fields', jsonb_build_array(
                      'community_tension',
                      'reader_objections',
                      'workflow_angle',
                      'brand_safe_mention_angle',
                      'things_to_avoid',
                      'closing_discussion_question'
                    ),
                    'rules', jsonb_build_array(
                      'Short bullets only.',
                      'No tables, matrices, FAQ blocks, SEO outline, brand-fit sections, or resource lists.',
                      'Convert strategy and citation evidence into a peer discussion setup, not a guide outline.'
                    )
                  )
                )
              ),
              true
            ),
            '{experience_style_notes}',
            jsonb_build_object(
              'enabled', true,
              'scope', 'reddit_only',
              'purpose', 'Convert Reddit Discover, Official Discover, Citation, target prompts, and strategy into writing-perspective material. These notes are not factual claims.',
              'fact_policy', 'Never invent first-hand product experience, benchmarks, usage history, votes, screenshots, or subreddit evidence.',
              'preferred_voice_patterns', jsonb_build_array(
                'I would test this by...',
                'The part that still feels fragile is...',
                'What I would not trust yet is...',
                'This is where the workflow gets awkward...'
              )
            ),
            true
          ),
          '{community_brief}',
          jsonb_build_object(
            'enabled', true,
            'scope', 'reddit_only',
            'max_words', 500,
            'purpose', 'The final Reddit prompt should consume this concise community brief instead of raw internal strategy documents.',
            'required_fields', jsonb_build_array(
              'community_tension',
              'reader_objections',
              'workflow_angle',
              'brand_safe_mention_angle',
              'things_to_avoid',
              'closing_discussion_question'
            ),
            'rendering_policy', 'Short bullets only; no tables, matrices, FAQ blocks, SEO outline, or brand-fit sections.'
          ),
          true
        ),
        '{reddit_native_contract}',
        jsonb_build_object(
          'opening_contract', jsonb_build_object(
            'required_shape', 'first_person_or_workflow_tension',
            'avoid', jsonb_build_array(
              'broad industry overview',
              'definition-first intro',
              'SEO guide framing',
              'month/year trend intro unless user explicitly asked for it'
            )
          ),
          'structure_contract', jsonb_build_object(
            'allowed', jsonb_build_array(
              'natural paragraphs',
              'short practical bullets',
              'workflow notes',
              'caveat section',
              'closing discussion question'
            ),
            'forbidden_headings', jsonb_build_array(
              'Phase 1',
              'Step-by-Step',
              'Checklist',
              'Tradeoff Matrix',
              'FAQ',
              'Brand Fit Summary',
              'Where [Brand] Fits',
              'Value / Dream / Mini-benefits',
              'Feature-to-Benefit Mapping',
              'Helpful Resources'
            )
          ),
          'brand_contract', jsonb_build_object(
            'role', 'one option inside a workflow or tradeoff, not the whole point of the post',
            'claim_style', 'conservative and input-grounded',
            'no_hard_sell', true
          ),
          'closing_contract', jsonb_build_object(
            'required_shape', 'real_discussion_question',
            'purpose', 'Invite other users to compare workflows, caveats, or edge cases.'
          )
        ),
        true
      ),
      '{ratf_rendering}',
      jsonb_build_object(
        'mode', 'template_native',
        'include_subgoal_raw_descriptions', false,
        'subgoal_overrides', jsonb_build_object(
          'information_presentation', 'Use short paragraphs, compact bullets, and concrete examples. Do not use tables, matrices, or default FAQ blocks for Reddit.',
          'content_structure', 'Keep structure conversational and community-native; convert framework logic into natural sections.',
          'evidence_traceability', 'Keep claims conservative and traceable to provided input; if evidence is missing, write uncertainty instead of confidence.'
        )
      ),
      true
    ),
    '{quality_gate}',
    (prepared.existing_quality_gate - 'rules')
      || jsonb_build_object(
        'enabled', true,
        'revise_on_warning', true,
        'rules', prepared.retained_rules || prepared.new_rules
      ),
    true
  )
FROM prepared
WHERE t.id = prepared.id;

COMMIT;

-- Verification:
-- SELECT
--   name,
--   wizard_config#>>'{prompt_input_policy,mode}' AS prompt_input_mode,
--   wizard_config#>>'{ratf_rendering,include_subgoal_raw_descriptions}' AS include_raw_subgoals,
--   jsonb_pretty(wizard_config#>'{community_brief}') AS community_brief,
--   jsonb_pretty(wizard_config#>'{quality_gate,rules}') AS quality_gate_rules
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     name ILIKE '%reddit%'
--     OR defaults->>'content_type' = 'reddit_article'
--     OR defaults->>'publish_platform' = 'reddit'
--     OR wizard_config->>'platform_profile' = 'reddit'
--   )
-- ORDER BY sort_order, name;
