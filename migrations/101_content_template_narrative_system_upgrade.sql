-- Migration 101: Narrative-system upgrade for Reddit and Official Website content templates
--
-- Context:
--   Prompt-debug logs showed that Reddit and Official Website generation
--   received the right data, but the template instructions were internally
--   conflicted. Reddit prompts asked for a community-first post while also
--   requiring SEO-style sections, tradeoff matrices, tables, FAQs, and public
--   "Brand Fit Summary" blocks. Official Website prompts over-forced brand fit,
--   value/dream/mini-benefits, feature tables, Helpful Resources, and CTA
--   patterns, creating formulaic marketing copy.
--
-- Purpose:
--   1. Move the narrative upgrade into template data instead of hardcoding.
--   2. Make Reddit output read like a real community workflow discussion.
--   3. Make Official Website output read like a useful owned-site article
--      without mandatory formula sections or unsupported hype.
--   4. Add deterministic Quality Gate checks for the specific failure modes.
--
-- Safe to re-run:
--   Yes. This migration overwrites the targeted template config keys with the
--   same values each time while preserving unrelated wizard_config keys such as
--   resource_link_policy, steps, and citation_analysis.

BEGIN;

UPDATE geo_report_templates AS t
SET
  default_prompt = $prompt$
Generate a publishable Reddit-style community post, not a blog article, SEO article, landing page, or brand ad.

The post must sound like a knowledgeable practitioner sharing a workflow, tradeoff, or decision point with peers. Use Reddit Discover to understand the community context and risk profile. Use Citation Analysis only as pattern learning for what questions, objections, workflows, and comparison angles matter; do not expose citation mechanics or source lists in the post.

Mention the primary brand naturally only where it helps explain a workflow or choice. Do not create a standalone Brand Fit Summary, "Where the brand fits" ad block, comparison matrix, Markdown table, FAQ block, or conversion CTA. If upstream strategy asks for any of those, convert the idea into natural paragraphs or short bullets.
$prompt$,
  wizard_config = COALESCE(t.wizard_config, '{}'::jsonb) || jsonb_build_object(
    'platform_playbook',
    $json$
    {
      "version": "reddit_narrative_v1",
      "platform": "reddit",
      "positioning": "Community-first workflow discussion for peers, not SEO content or brand marketing.",
      "non_negotiables": [
        "No Markdown tables, comparison matrices, evidence tables, scoring tables, or table-like layouts.",
        "No standalone Brand Fit Summary, Where [Brand] Fits, product pitch, ad block, CTA block, or landing-page language.",
        "No FAQ section by default; only use a tiny Q&A paragraph if the user explicitly asked for it.",
        "No invented first-person experience, tests, benchmarks, Reddit comments, subreddit names, votes, screenshots, or usage claims.",
        "No SEO/blog title patterns such as Ultimate Guide, Complete Guide, Best Tool, Everything You Need to Know, or Top X.",
        "No internal workflow language such as Citation Analysis, Quality Gate, RAFT, strategy brief, prompt, or template."
      ],
      "title_rules": [
        "Use a title that feels like a real Reddit post: a practical question, tradeoff, workflow note, or decision problem.",
        "Prefer specific user tension over polished category claims.",
        "Do not force the brand name into the title unless it is naturally central to the discussion.",
        "Avoid current-month/year titles unless the date is genuinely part of the user context."
      ],
      "narrative_rules": [
        "Open with the practical situation or friction the community would recognize.",
        "Write in a grounded, conversational voice with concrete tradeoffs and limitations.",
        "If direct personal-use evidence is not provided, use cautious framing such as what I would test, the pattern I would look for, or where this might fit.",
        "Use short paragraphs and compact bullets only when they make the workflow easier to scan.",
        "End with a real discussion question that invites other users to compare workflows or caveats."
      ],
      "brand_rules": [
        "Mention the primary brand 2-4 times in helpful context when relevant.",
        "Treat the brand as one option or one step in a workflow, not as the whole point of the post.",
        "Use conservative language for ungrounded claims; avoid highly recommended, best overall, market-leading, superior, or leading-solution claims unless explicitly evidenced.",
        "If the post compares options, compare tradeoffs in prose or bullets instead of a table."
      ],
      "upstream_override_rules": [
        "If Strategy or Citation Analysis asks for Brand Fit Summary, Where [Brand] Fits, Value/Dream/Mini-benefits, Feature-to-Benefit Mapping, FAQ, or a tradeoff matrix, do not reproduce those sections.",
        "Convert useful ideas from upstream steps into natural Reddit paragraphs, caveats, workflow notes, or short bullets."
      ],
      "data_use_rules": [
        "Reddit Discover supplies community context, anxieties, tone, and posting risk.",
        "Citation Analysis supplies recurring questions and answer patterns only.",
        "Never present Citation sources as Helpful Resources in a Reddit post."
      ]
    }
    $json$::jsonb,
    'generation_requirements',
    $json$
    {
      "version": "reddit_narrative_v1",
      "output_shape": "Publishable Markdown post with one H1 title, natural paragraphs, optional short bullets, and a discussion question.",
      "tone": "Plainspoken, peer-to-peer, specific, slightly skeptical, useful.",
      "must_include": [
        "A concrete workflow, decision, or tradeoff the target community would recognize.",
        "At least one limitation, caveat, or situation where the primary brand is not the complete answer.",
        "A closing discussion question."
      ],
      "must_not_include": [
        "Markdown tables",
        "FAQ section",
        "Brand Fit Summary",
        "Where [Brand] Fits",
        "Value / Dream / Mini-benefits",
        "Feature-to-Benefit Mapping",
        "Helpful Resources",
        "SEO meta language",
        "Promotional CTA"
      ],
      "strategy_conflict_resolution": "Template rules win. If upstream strategy asks for a table, matrix, FAQ, brand block, or marketing CTA, translate the underlying idea into natural Reddit prose."
    }
    $json$::jsonb,
    'depth_profiles',
    $json$
    {
      "quick": {
        "label": "Short Reddit note",
        "word_count": "450-700 words",
        "structure": "Practical opening, 2-3 compact sections, one caveat, discussion question.",
        "table_policy": "Forbidden"
      },
      "standard": {
        "label": "Standard Reddit workflow post",
        "word_count": "700-1100 words",
        "structure": "Practical opening, workflow/tradeoff sections, short bullets where useful, one limitation section, discussion question.",
        "table_policy": "Forbidden"
      },
      "deep": {
        "label": "Detailed Reddit field notes",
        "word_count": "1100-1600 words",
        "structure": "Detailed workflow notes, decision criteria, caveats, edge cases, discussion question.",
        "table_policy": "Forbidden"
      },
      "authority": {
        "label": "Long Reddit discussion post",
        "word_count": "1400-1900 words",
        "structure": "Long-form but still conversational; no whitepaper tone, no table, no brand ad block.",
        "table_policy": "Forbidden"
      }
    }
    $json$::jsonb,
    'quality_gate',
    COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || $json$
    {
      "enabled": true,
      "min_overall_score": 8.0,
      "revise_below_score": true,
      "revise_on_warning": true,
      "max_revise_attempts": 2,
      "blocker_score_cap": 6.0,
      "warning_score_cap": 8.0,
      "rules": [
        {
          "id": "reddit_markdown_tables_forbidden",
          "type": "forbidden_patterns",
          "severity": "blocker",
          "patterns": ["^\\s*\\|[^\\n]*\\|\\s*$"],
          "message": "Reddit content must not use Markdown tables or matrix layouts."
        },
        {
          "id": "reddit_standalone_brand_blocks_forbidden",
          "type": "forbidden_patterns",
          "severity": "blocker",
          "patterns": [
            "^\\s{0,3}#{1,6}\\s+Brand Fit Summary\\b",
            "^\\s{0,3}#{1,6}\\s+Where\\s+.+\\s+Fits\\b",
            "^\\s{0,3}#{1,6}\\s+Value\\s*/\\s*Dream\\s*/\\s*Mini-benefits\\b",
            "^\\s{0,3}#{1,6}\\s+Feature-to-Benefit Mapping\\b",
            "^\\s{0,3}#{1,6}\\s+Helpful Resources\\b"
          ],
          "message": "Remove standalone brand-fit, feature-mapping, resources, or marketing framework sections from Reddit output."
        },
        {
          "id": "reddit_seo_title_patterns_forbidden",
          "type": "forbidden_patterns",
          "severity": "blocker",
          "patterns": [
            "^\\s{0,3}#\\s+.*\\bUltimate Guide\\b",
            "^\\s{0,3}#\\s+.*\\bComplete Guide\\b",
            "^\\s{0,3}#\\s+.*\\bEverything You Need to Know\\b",
            "^\\s{0,3}#\\s+.*\\bBest\\s+.+\\bTool\\b",
            "^\\s{0,3}#\\s+.*\\bTop\\s+\\d+\\b"
          ],
          "message": "Rewrite the title to sound like a real Reddit post, not SEO content."
        },
        {
          "id": "reddit_fake_experience_risk",
          "type": "forbidden_patterns",
          "severity": "warning",
          "patterns": [
            "\\bI\\s+tested\\b",
            "\\bI\\s+used\\b",
            "\\bI\\s+spent\\s+\\d+\\b",
            "\\bmy\\s+results\\b",
            "\\bin\\s+my\\s+workflow\\b",
            "\\bmy\\s+May\\s+\\d{4}\\s+workflow\\b"
          ],
          "message": "Avoid first-person usage claims unless the input explicitly provides that experience."
        },
        {
          "id": "reddit_marketing_cta_forbidden",
          "type": "forbidden_patterns",
          "severity": "blocker",
          "patterns": [
            "\\btry\\s+.+\\s+today\\b",
            "\\bget\\s+started\\s+with\\b",
            "\\bsign\\s+up\\b",
            "\\bstart\\s+creating\\s+with\\b",
            "\\bhighly\\s+recommended\\b",
            "\\bleading\\s+.+\\bsolution\\b",
            "\\bmarket-leading\\b"
          ],
          "message": "Remove promotional CTA or unsupported superiority language."
        },
        {
          "id": "llm_process_artifacts",
          "type": "forbidden_patterns",
          "severity": "blocker",
          "patterns": [
            "^\\s*RSThe search results confirm",
            "Let's double check the rules",
            "The prompt says:",
            "The primary brand to mention is",
            "The failure is `",
            "Re-evaluating the text",
            "Let's review the",
            "Let's refine",
            "Looks solid\\.\\s*#"
          ],
          "message": "Remove leaked model reasoning, self-check notes, or revision-process text; final output must contain publishable Markdown only."
        }
      ],
      "revision_guidance": {
        "general": [
          "Return final publishable Markdown only. Delete any reasoning transcript, self-check, search-result notes, prompt analysis, or Quality Gate debugging text.",
          "If a Reddit rule conflicts with upstream Strategy or Citation Analysis, the Reddit template rule wins.",
          "Remove Markdown tables, matrices, standalone brand-fit headings, FAQ blocks, Helpful Resources, and promotional CTA language.",
          "Rewrite SEO/blog titles into real Reddit-style questions, workflow notes, or tradeoff posts.",
          "Keep brand mentions natural and conservative; do not turn the post into a product ad."
        ]
      }
    }
    $json$::jsonb
  )
WHERE t.task_type = 'content_generation'
  AND (
    t.name = 'Reddit AI Citable Post Generator'
    OR t.defaults->>'content_type' = 'reddit_article'
    OR t.defaults->>'publish_platform' = 'reddit'
    OR t.wizard_config->>'platform_profile' = 'reddit'
  );

UPDATE geo_report_templates AS t
SET
  default_prompt = $prompt$
Generate a publishable official website article that helps readers make a practical decision. The article should be clear, specific, brand-safe, and useful, but not formulaic or over-promotional.

Use Official Website Discovery to understand the brand's owned-site context and verified publishable URLs. Use Citation Analysis to learn what questions, objections, comparison criteria, and answer patterns matter in the category. Do not automatically copy Citation source URLs into the article, and do not invent Helpful Resources.

The article may include brand positioning, buyer criteria, workflow examples, use cases, limitations, FAQs, and soft next steps when they genuinely help the reader. Do not force Brand Fit Summary, Value / Dream / Mini-benefits, Feature-to-Benefit Mapping tables, or any other internal framework as public section headings. If upstream strategy asks for those formula sections, translate the useful content into natural reader-facing sections.
$prompt$,
  wizard_config = COALESCE(t.wizard_config, '{}'::jsonb) || jsonb_build_object(
    'platform_playbook',
    $json$
    {
      "version": "official_site_narrative_v1",
      "platform": "official_site",
      "positioning": "Owned-site educational article with credible brand context, not a mechanical SEO template.",
      "non_negotiables": [
        "Do not use unsupported hype such as best overall, highly recommended, market-leading, superior, guaranteed, or leading-solution claims unless explicitly evidenced.",
        "Do not expose internal framework names as public headings: Brand Fit Summary, Value / Dream / Mini-benefits, Feature-to-Benefit Mapping, Citation Analysis, Quality Gate, RAFT, or strategy brief.",
        "Do not require Markdown tables. Use tables only when they materially improve reader comprehension and the underlying facts are grounded.",
        "Do not invent Helpful Resources or same-domain URLs; only use exact verified URLs from Official Website Discovery when available.",
        "Do not write a hard-sell CTA. Use soft next steps tied to the reader's decision."
      ],
      "article_rules": [
        "Open with the user's decision problem or practical category question.",
        "Answer the core question early, then develop criteria, workflows, limitations, and use cases.",
        "Bring the primary brand in as a relevant solution or example where grounded, not as the only answer to every question.",
        "Explain tradeoffs and limitations honestly; credibility is more important than aggressive conversion.",
        "Use reader-facing headings that would make sense on the customer's website."
      ],
      "brand_rules": [
        "Mention the primary brand naturally and sufficiently for extractability.",
        "Use conservative, evidence-aware language when details are not present in inputs.",
        "If the brand is positioned against alternatives, compare decision criteria rather than making unsupported superiority claims."
      ],
      "upstream_override_rules": [
        "If Strategy or Citation Analysis asks for public Brand Fit Summary, Value/Dream/Mini-benefits, Feature-to-Benefit Mapping, or mandatory comparison tables, do not reproduce those labels.",
        "Convert useful internal strategy ideas into natural official-site sections such as What to look for, How to evaluate, Workflow example, Common mistakes, or When this approach fits."
      ],
      "resource_rules": [
        "Helpful Resources are optional.",
        "Helpful Resources may only use exact URLs verified by Official Website Discovery.",
        "If no verified URLs exist, omit Helpful Resources entirely."
      ]
    }
    $json$::jsonb,
    'generation_requirements',
    $json$
    {
      "version": "official_site_narrative_v1",
      "output_shape": "Publishable Markdown article with one H1, useful reader-facing sections, optional FAQ, and soft next steps.",
      "tone": "Helpful, credible, specific, brand-safe, and lightly commercial without sounding like a landing page.",
      "must_include": [
        "A clear answer to the reader's practical question.",
        "Decision criteria, workflow guidance, or use-case guidance grounded in available inputs.",
        "Natural primary-brand context where relevant.",
        "At least one limitation, caveat, or implementation consideration."
      ],
      "optional_sections": [
        "FAQ when the topic has real recurring questions.",
        "A concise checklist when it helps actionability.",
        "Helpful Resources only when verified URLs are available from Official Website Discovery."
      ],
      "must_not_include": [
        "Internal framework headings",
        "Unsupported hype",
        "Invented Helpful Resources",
        "Mandatory comparison table",
        "Hard-sell CTA"
      ],
      "strategy_conflict_resolution": "Template rules win. Translate internal framework outputs into natural owned-site prose and reader-facing sections."
    }
    $json$::jsonb,
    'depth_profiles',
    $json$
    {
      "quick": {
        "label": "Short official article",
        "word_count": "700-1000 words",
        "structure": "Direct answer, key criteria, brand context, caveat, soft next step."
      },
      "standard": {
        "label": "Standard official article",
        "word_count": "1100-1600 words",
        "structure": "Decision-oriented intro, criteria/workflow sections, brand context, limitations, optional FAQ."
      },
      "deep": {
        "label": "In-depth official article",
        "word_count": "1700-2400 words",
        "structure": "Detailed buyer/use-case guide with grounded examples, honest tradeoffs, optional FAQ and verified resources."
      },
      "authority": {
        "label": "Authority official article",
        "word_count": "2200-3000 words",
        "structure": "Comprehensive but reader-friendly owned-site guide; credibility and specificity over formulaic SEO."
      }
    }
    $json$::jsonb,
    'quality_gate',
    COALESCE(t.wizard_config->'quality_gate', '{}'::jsonb) || $json$
    {
      "enabled": true,
      "min_overall_score": 8.0,
      "revise_below_score": true,
      "revise_on_warning": true,
      "max_revise_attempts": 2,
      "blocker_score_cap": 6.0,
      "warning_score_cap": 8.0,
      "rules": [
        {
          "id": "official_internal_framework_headings_forbidden",
          "type": "forbidden_patterns",
          "severity": "blocker",
          "patterns": [
            "^\\s{0,3}#{1,6}\\s+Brand Fit Summary\\b",
            "^\\s{0,3}#{1,6}\\s+Value\\s*/\\s*Dream\\s*/\\s*Mini-benefits\\b",
            "^\\s{0,3}#{1,6}\\s+Feature-to-Benefit Mapping\\b",
            "^\\s{0,3}#{1,6}\\s+Citation Analysis\\b",
            "^\\s{0,3}#{1,6}\\s+Quality Gate\\b",
            "^\\s{0,3}#{1,6}\\s+RAFT\\b"
          ],
          "message": "Replace internal framework headings with natural reader-facing official-site headings."
        },
        {
          "id": "official_unsupported_hype_forbidden",
          "type": "forbidden_patterns",
          "severity": "warning",
          "patterns": [
            "\\bhighly\\s+recommended\\b",
            "\\bleading\\s+(?:AI|platform|solution|tool|brand|provider|choice|option|generator|software|product|company)\\b",
            "\\bmarket-leading\\b",
            "\\bbest\\s+overall\\b",
            "\\bsuperior\\b",
            "\\bguaranteed\\b",
            "\\bunmatched\\b",
            "\\brevolutionary\\b"
          ],
          "message": "Remove unsupported hype or replace it with grounded, specific wording."
        },
        {
          "id": "official_hard_sell_cta_forbidden",
          "type": "forbidden_patterns",
          "severity": "warning",
          "patterns": [
            "\\btry\\s+.+\\s+today\\b",
            "\\bsign\\s+up\\s+now\\b",
            "\\bget\\s+started\\s+today\\b",
            "\\bdon't\\s+wait\\b",
            "\\bunlock\\s+.+\\s+now\\b"
          ],
          "message": "Use soft, decision-relevant next steps instead of hard-sell CTA language."
        },
        {
          "id": "llm_process_artifacts",
          "type": "forbidden_patterns",
          "severity": "blocker",
          "patterns": [
            "^\\s*RSThe search results confirm",
            "Let's double check the rules",
            "The prompt says:",
            "The primary brand to mention is",
            "The failure is `",
            "Re-evaluating the text",
            "Let's review the",
            "Let's refine",
            "Looks solid\\.\\s*#"
          ],
          "message": "Remove leaked model reasoning, self-check notes, or revision-process text; final output must contain publishable Markdown only."
        }
      ],
      "revision_guidance": {
        "general": [
          "Return final publishable Markdown only. Delete any reasoning transcript, self-check, search-result notes, prompt analysis, or Quality Gate debugging text.",
          "If the article uses internal framework headings, rewrite them into natural reader-facing headings.",
          "Remove unsupported hype and hard-sell CTA language; replace it with specific, grounded, decision-useful language.",
          "Helpful Resources must use exact URLs verified by Official Website Discovery; if no verified URL replacement exists, delete the resources section.",
          "If Strategy or Citation Analysis asks for formula sections or mandatory tables, convert the useful ideas into natural official-site prose."
        ]
      }
    }
    $json$::jsonb
  )
WHERE t.task_type = 'content_generation'
  AND (
    t.name = 'Official Website AI Citable Article'
    OR t.defaults->>'content_type' = 'official_website_article'
    OR t.defaults->>'publish_platform' IN ('official_site', 'official_website')
    OR t.wizard_config->>'platform_profile' IN ('official_site', 'official_website')
  );

COMMIT;

-- Verification:
-- SELECT
--   name,
--   default_prompt,
--   wizard_config->'platform_playbook' AS platform_playbook,
--   wizard_config->'generation_requirements' AS generation_requirements,
--   wizard_config->'quality_gate'->'rules' AS quality_gate_rules,
--   wizard_config->'resource_link_policy' AS resource_link_policy
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND (
--     name IN ('Reddit AI Citable Post Generator', 'Official Website AI Citable Article')
--     OR defaults->>'content_type' IN ('reddit_article', 'official_website_article')
--     OR defaults->>'publish_platform' IN ('reddit', 'official_site', 'official_website')
--     OR wizard_config->>'platform_profile' IN ('reddit', 'official_site', 'official_website')
--   )
-- ORDER BY name;
