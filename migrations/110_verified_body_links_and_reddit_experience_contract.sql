-- Migration 110: Verified body links and Reddit experience contract
--
-- Context:
--   Recent production runs showed two remaining prompt-contract gaps:
--   1. Official Website articles could still place inline Markdown links to
--      the root owned domain even though Helpful Resources were restricted to
--      Official Website Discovery verified URLs.
--   2. Reddit templates needed a clearer contract that preserves community
--      first-hand texture while blocking fabricated hard benchmarks, exact
--      testing claims, votes, screenshots, or unverifiable results.
--
-- Purpose:
--   1. Configure official-site templates so every Markdown link in the body,
--      not only Helpful Resources, must be an exact URL from the verified
--      Official Website Discovery URL pool.
--   2. Update official-site prompt and revise guidance so invalid body links
--      are removed or replaced with verified exact URLs.
--   3. Update Reddit template instructions and Quality Gate rules to allow
--      experience-informed community writing while forbidding fabricated
--      specific personal tests or benchmarks.
--
-- Safe to re-run:
--   Yes. This migration overwrites targeted config keys and de-duplicates the
--   replaced rule ids before appending the new versions.

BEGIN;

WITH official_templates AS (
  SELECT id, wizard_config
  FROM geo_report_templates
  WHERE task_type = 'content_generation'
    AND (
      name ILIKE '%official website%'
      OR defaults->>'content_type' = 'official_website_article'
      OR defaults->>'publish_platform' IN ('official_site', 'official_website')
      OR wizard_config->>'platform_profile' IN ('official_site', 'official_website')
    )
),
official_guidance AS (
  SELECT
    id,
    COALESCE(
      (
        SELECT jsonb_agg(value)
        FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,revision_guidance,general}', '[]'::jsonb)) AS guidance(value)
        WHERE value NOT IN (
          '"Helpful Resources must use exact URLs verified by Official Website Discovery; if no verified URL replacement exists, delete the resources section."'::jsonb,
          '"Helpful Resources must use exact URLs verified by Official Website Discovery; same-domain guessed paths are not allowed."'::jsonb,
          '"If there is no verified URL replacement, delete the Helpful Resources section instead of inventing a new link."'::jsonb,
          '"All Markdown links in official-site articles must use exact URLs verified by Official Website Discovery; replace unverified links with verified URLs or plain text."'::jsonb,
          '"Do not use owned-domain root URLs as fallback links unless the exact root URL appears in the verified URL pool."'::jsonb
        )
      ),
      '[]'::jsonb
    ) AS retained_guidance
  FROM official_templates
),
official_rules AS (
  SELECT
    id,
    COALESCE(
      (
        SELECT jsonb_agg(rule)
        FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,rules}', '[]'::jsonb)) AS existing(rule)
        WHERE existing.rule->>'id' <> 'official_body_links_unverified'
      ),
      '[]'::jsonb
    ) AS retained_rules
  FROM official_templates
)
UPDATE geo_report_templates AS t
SET
  default_prompt = $prompt$
Generate a publishable official website article that helps readers make a practical decision. The article should be clear, specific, brand-safe, useful, and credible without sounding formulaic or over-promotional.

Use Official Website Discovery to understand the brand's owned-site context and the exact verified URLs that may be linked in the article. Every Markdown link in the final article must use an exact URL from that verified URL pool. Do not use root-domain fallbacks, guessed same-domain paths, Citation Analysis source URLs, or invented Helpful Resources.

Use Citation Analysis to learn what questions, objections, comparison criteria, and answer patterns matter in the category. Do not automatically copy Citation source URLs into the article. The article may include brand positioning, buyer criteria, workflow examples, use cases, limitations, FAQs, and soft next steps when they genuinely help the reader.

Do not force Brand Fit Summary, Value / Dream / Mini-benefits, Feature-to-Benefit Mapping tables, or any other internal framework as public section headings. If upstream strategy asks for those formula sections, translate the useful content into natural reader-facing sections.
$prompt$,
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            COALESCE(t.wizard_config, '{}'::jsonb),
            '{resource_link_policy}',
            COALESCE(t.wizard_config->'resource_link_policy', '{}'::jsonb) || jsonb_build_object(
              'enabled', true,
              'apply_to_content_types', jsonb_build_array('official_website_article'),
              'apply_to_publish_platforms', jsonb_build_array('official_site', 'official_website'),
              'apply_to_platform_profiles', jsonb_build_array('official_site', 'official_website'),
              'verified_url_source', 'official_website_discovery',
              'verified_url_match', 'exact',
              'link_scope', 'all_markdown_links',
              'sanitize_generated_content', true,
              'sanitize_inline_markdown_links', true,
              'remove_section_when_no_verified_links', true,
              'include_wizard_input_urls_without_discovery', false,
              'include_citation_source_urls_by_default', false,
              'section_headings', jsonb_build_array(
                'Helpful Resources',
                'Further Reading',
                'Related Resources',
                'Learn More'
              ),
              'output_heading', 'Helpful Resources',
              'prompt_title', 'Verified Link Policy',
              'no_verified_urls_instruction', 'No exact URL has been verified by Official Website Discovery; do not generate Markdown links, Helpful Resources, Further Reading, Related Resources, or Learn More sections.',
              'generation_rules', jsonb_build_array(
                'Every Markdown link in the article body must use an exact URL from the verified URL pool below.',
                'Do not use owned-domain root URLs as fallback links unless the exact root URL appears in the verified URL pool.',
                'Do not invent same-domain paths, redirect guesses, or short vanity links.',
                'Citation Analysis URLs are learning examples for structure and content gaps; do not turn them into article links unless the exact URL is also verified by Official Website Discovery.',
                'If a useful sentence has no verified URL, keep the sentence as plain text rather than linking it.',
                'Helpful Resources / Further Reading / Related Resources / Learn More are optional and must use only verified exact URLs.'
              ),
              'revision_instruction', 'If any Markdown link is outside the Official Website Discovery verified exact URL pool, replace it with a verified exact URL only when the destination meaning remains accurate; otherwise unwrap the link and keep the anchor text as plain text.'
              ,
              'quality_gate_rule', jsonb_build_object(
                'id', 'official_body_links_unverified',
                'type', 'official_resource_link_policy',
                'severity', 'blocker',
                'message', 'Official-site article contains Markdown links outside the verified Official Website Discovery URL pool.'
              )
            ),
            true
          ),
          '{platform_playbook,resource_rules}',
          jsonb_build_array(
            'All Markdown links in the article body must use exact URLs verified by Official Website Discovery.',
            'Helpful Resources are optional and may only use verified exact URLs.',
            'Do not use root-domain fallbacks or guessed same-domain paths unless the exact URL appears in the verified pool.',
            'If no verified URL exists for a claim or resource, keep the sentence as plain text or omit the resource section.'
          ),
          true
        ),
        '{generation_requirements,must_not_include}',
        (
          SELECT COALESCE(jsonb_agg(DISTINCT value), '[]'::jsonb)
          FROM jsonb_array_elements(
            COALESCE(t.wizard_config#>'{generation_requirements,must_not_include}', '[]'::jsonb)
            || '[
              "Unverified Markdown links",
              "Root-domain fallback links",
              "Guessed same-domain URLs",
              "Invented Helpful Resources"
            ]'::jsonb
          ) AS items(value)
        ),
        true
      ),
      '{quality_gate,revision_guidance,general}',
      official_guidance.retained_guidance || '[
        "All Markdown links in official-site articles must use exact URLs verified by Official Website Discovery; replace unverified links with verified URLs or plain text.",
        "Do not use owned-domain root URLs as fallback links unless the exact root URL appears in the verified URL pool.",
        "Helpful Resources must use exact URLs verified by Official Website Discovery; if no verified URL replacement exists, delete the resources section."
      ]'::jsonb,
      true
    ),
    '{quality_gate,rules}',
    official_rules.retained_rules || jsonb_build_array(
      jsonb_build_object(
        'id', 'official_body_links_unverified',
        'type', 'resource_link_policy',
        'severity', 'blocker',
        'message', 'Official-site article contains Markdown links outside the verified Official Website Discovery URL pool.'
      )
    ),
    true
  )
FROM official_guidance
JOIN official_rules ON official_rules.id = official_guidance.id
WHERE t.id = official_guidance.id;

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
reddit_rules AS (
  SELECT
    id,
    COALESCE(
      (
        SELECT jsonb_agg(rule)
        FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,rules}', '[]'::jsonb)) AS existing(rule)
        WHERE existing.rule->>'id' NOT IN (
          'reddit_opening_first_person_or_workflow_required',
          'reddit_fake_experience_risk',
          'reddit_unverifiable_specific_experience_forbidden'
        )
      ),
      '[]'::jsonb
    ) AS retained_rules
  FROM reddit_templates
),
reddit_guidance AS (
  SELECT
    id,
    COALESCE(
      (
        SELECT jsonb_agg(value)
        FROM jsonb_array_elements(COALESCE(wizard_config#>'{quality_gate,revision_guidance,general}', '[]'::jsonb)) AS guidance(value)
        WHERE value NOT IN (
          '"Rewrite SEO/blog titles into real Reddit-style questions, workflow notes, or tradeoff posts."'::jsonb,
          '"Use experience-informed Reddit voice from provided research artifacts, but do not fabricate exact personal tests, days/weeks used, vote counts, screenshots, benchmarks, or results."'::jsonb,
          '"Keep first-person texture when it reflects workflow perspective; soften unverifiable specific claims into cautious phrases such as I would test, the pattern I am seeing, or where this could still fail."'::jsonb
        )
      ),
      '[]'::jsonb
    ) AS retained_guidance
  FROM reddit_templates
)
UPDATE geo_report_templates AS t
SET
  default_prompt = $prompt$
Generate a publishable Reddit-style community post, not a blog article, SEO article, landing page, or brand ad.

The post must sound like a real knowledgeable practitioner inside the community: experience-informed, specific, slightly skeptical, and useful. Use Reddit Research artifacts as the source of community norms, objections, risk signals, and writing texture. You may write with first-person or close peer-to-peer perspective when it helps the post feel native, but do not fabricate exact personal tests, usage history, votes, screenshots, benchmarks, prices, or results that are not present in the inputs.

Use Citation Analysis only as pattern learning for what questions, objections, workflows, and comparison angles matter; do not expose citation mechanics or source lists in the post. Mention the primary brand naturally only where it helps explain a workflow or choice. Do not create a standalone Brand Fit Summary, "Where the brand fits" ad block, comparison matrix, Markdown table, FAQ block, Helpful Resources, or conversion CTA. If upstream strategy asks for any of those, convert the idea into natural Reddit paragraphs, caveats, workflow notes, or short bullets.
$prompt$,
  wizard_config = jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              COALESCE(t.wizard_config, '{}'::jsonb),
              '{platform_playbook,narrative_rules}',
              jsonb_build_array(
                'Open with a concrete workflow tension, practical frustration, decision point, or experience-informed observation that the community would recognize.',
                'Write with first-person or close peer-to-peer texture when useful, but keep factual claims grounded in provided research artifacts.',
                'When direct personal-use evidence is not provided, use cautious framing such as what I would test, the pattern I am seeing, where this might fit, or where this could still fail.',
                'Use short paragraphs and compact bullets only when they make the workflow easier to scan.',
                'End with a real discussion question that invites other users to compare workflows, caveats, or edge cases.'
              ),
              true
            ),
            '{platform_playbook,non_negotiables}',
            jsonb_build_array(
              'No Markdown tables, comparison matrices, evidence tables, scoring tables, or table-like layouts.',
              'No standalone Brand Fit Summary, Where [Brand] Fits, product pitch, ad block, CTA block, Helpful Resources, or landing-page language.',
              'No FAQ section by default; only use a tiny Q&A paragraph if the user explicitly asked for it.',
              'No fabricated exact first-person tests, usage history, days/weeks used, vote counts, screenshots, benchmarks, prices, or result claims.',
              'No SEO/blog title patterns such as Ultimate Guide, Complete Guide, Best Tool, Everything You Need to Know, or Top X.',
              'No internal workflow language such as Citation Analysis, Quality Gate, RAFT, strategy brief, prompt, or template.'
            ),
            true
          ),
          '{experience_style_notes,fact_policy}',
          '"Use first-person or peer-to-peer writing texture only as a style scaffold. Do not fabricate exact personal testing, usage history, quantified results, screenshots, votes, or benchmarks; convert unsupported specifics into cautious workflow observations."'::jsonb,
          true
        ),
        '{reddit_native_contract,opening_contract}',
        jsonb_build_object(
          'required_shape', 'experience_informed_or_workflow_tension',
          'allow', jsonb_build_array(
            'first-person workflow tension',
            'close peer-to-peer observation',
            'specific practical frustration',
            'decision problem the subreddit would recognize'
          ),
          'avoid', jsonb_build_array(
            'broad industry overview',
            'definition-first intro',
            'SEO guide framing',
            'month/year trend intro unless user explicitly asked for it',
            'fabricated exact personal testing or benchmark claims'
          )
        ),
        true
      ),
      '{quality_gate,revision_guidance,general}',
      reddit_guidance.retained_guidance || '[
        "Rewrite SEO/blog titles into real Reddit-style questions, workflow notes, or tradeoff posts.",
        "Use experience-informed Reddit voice from provided research artifacts, but do not fabricate exact personal tests, days/weeks used, vote counts, screenshots, benchmarks, or results.",
        "Keep first-person texture when it reflects workflow perspective; soften unverifiable specific claims into cautious phrases such as I would test, the pattern I am seeing, or where this could still fail."
      ]'::jsonb,
      true
    ),
    '{quality_gate,rules}',
    reddit_rules.retained_rules || jsonb_build_array(
      jsonb_build_object(
        'id', 'reddit_opening_first_person_or_workflow_required',
        'type', 'first_paragraph_required_patterns',
        'severity', 'blocker',
        'patterns', jsonb_build_array(
          '\bI(?:''ve| have| am| still| usually| tend to| would)\b',
          '\bif you(?:''re| are)\s+(?:trying|building|choosing|scaling|posting|testing)\b',
          '\bmy workflow\b',
          '\bwhat I(?:''d| would) test\b',
          '\bthe pattern I(?:''m| am) seeing\b',
          '\bthe part that still feels\b',
          '\bthe workflow problem\b'
        ),
        'message', 'Reddit opening must start from experience-informed community voice or a concrete workflow tension, not a broad industry-guide intro.'
      ),
      jsonb_build_object(
        'id', 'reddit_unverifiable_specific_experience_forbidden',
        'type', 'forbidden_patterns',
        'severity', 'blocker',
        'patterns', jsonb_build_array(
          '\bI\s+(?:tested|benchmarked)\s+\d+\b',
          '\bI\s+spent\s+\d+\s+(?:days|weeks|months)\b',
          '\bI\s+used\s+.+\s+for\s+\d+\s+(?:days|weeks|months)\b',
          '\bmy\s+results\b',
          '\bmy\s+benchmark(?:s)?\b',
          '\bmy\s+spreadsheet\b',
          '\bscreenshot(?:s)?\s+prove\b',
          '\b\d+\s+upvotes\b',
          '\b\d+\s+comments\b'
        ),
        'message', 'Keep Reddit first-person texture, but remove fabricated exact personal tests, benchmarks, usage durations, screenshots, vote counts, or result claims.'
      )
    ),
    true
  )
FROM reddit_guidance
JOIN reddit_rules ON reddit_rules.id = reddit_guidance.id
WHERE t.id = reddit_guidance.id;

COMMIT;

-- Verification:
-- SELECT
--   name,
--   wizard_config#>>'{resource_link_policy,link_scope}' AS link_scope,
--   wizard_config#>>'{resource_link_policy,sanitize_inline_markdown_links}' AS sanitize_inline,
--   wizard_config#>'{platform_playbook,narrative_rules}' AS narrative_rules,
--   wizard_config#>'{quality_gate,rules}' AS quality_gate_rules
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     defaults->>'content_type' IN ('reddit_article', 'official_website_article')
--     OR defaults->>'publish_platform' IN ('reddit', 'official_site', 'official_website')
--     OR wizard_config->>'platform_profile' IN ('reddit', 'official_site', 'official_website')
--   )
-- ORDER BY name;
