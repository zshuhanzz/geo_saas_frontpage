-- =============================================================================
-- Migration 074: Official Website template publishability refinements
-- =============================================================================
--
-- Goal
-- ----
-- Tighten the "Official Website Insight then Generate" template after reviewing
-- a generated official-site article against Dreamina's existing official pages.
--
-- This migration does NOT change schema and does NOT affect Reddit templates.
-- It only updates the official website content type copy and the template
-- playbook so generated articles are:
--   - suitable for customer official website publishing,
--   - more factual and evidence-conservative,
--   - stronger for GEO/AEO brand extraction,
--   - less likely to overclaim with unsupported competitor, market, ranking,
--     release, platform-policy, or algorithm statements.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Content type copy: clarify publishability + evidence expectations
-- ---------------------------------------------------------------------------
UPDATE geo_workflow_config
SET value = jsonb_set(
  value,
  '{description}',
  to_jsonb(
    '面向客户官网发布的 SEO/AEO 产品营销长文。强调品牌可抽取、Use Case 覆盖、商业转化信息、品牌友好 FAQ、内部链接建议和可验证事实；避免未核验榜单、市场数字、版本功能和过度营销断言。'::text
  ),
  true
)
WHERE scope = 'content_generation'
  AND config_type = 'content_type'
  AND key = 'official_website_article';

-- ---------------------------------------------------------------------------
-- Template playbook: official-site quality gates for GEO-ready publishing
-- ---------------------------------------------------------------------------
WITH refined AS (
  SELECT
    '{
      "platform": "official_website",
      "positioning": "SEO/AEO product-marketing long-form for the customer official website",
      "methodology": "Model the useful parts of Profound-style product marketing content: dense use-case coverage, answer-ready sections, clear brand fit, comparison tables, FAQs, and conversion-oriented detail. Do not copy Profound wording or mention Profound.",
      "publishability_principle": "The article should feel ready for a customer official website after light human fact-checking: brand-forward, useful, commercially specific, and credible. Do not sacrifice trust for aggressive SEO claims.",
      "title_rules": [
        "Use SEO/AEO-friendly article titles that clearly name the topic, buyer problem, or product category.",
        "Official website titles may use guide, comparison, how-to, use-case, or best-fit language when useful.",
        "Avoid unverifiable superlatives such as definitive best, undisputed leader, number one, ultimate, guaranteed, viral-ready, algorithm-ready, or official unless the claim is supported by grounded evidence.",
        "Prefer scoped titles such as best fit for Instagram creators, tools for Reels workflows, or how to choose an AI video generator for social content."
      ],
      "voice_rules": [
        "Use polished product-marketing language suitable for a customer official website.",
        "Be helpful, concrete, commercially useful, and brand-forward without making unsupported claims.",
        "Write like an official educational product article, not a Reddit post, not a hype thread, and not a thin affiliate listicle.",
        "Structure the article so AI answer engines can extract brand, use cases, feature benefits, limitations, workflows, FAQs, and buyer fit."
      ],
      "brand_prominence_rules": [
        "Use the Brand Profile section as the source of truth for the brand name; do not confuse client name with brand name.",
        "The article must make the primary brand highly extractable through direct answer intro, Brand Fit Summary, use-case sections, comparison rows, feature-to-benefit mapping, and FAQ answers.",
        "Mention the brand more prominently than Reddit content, but every brand mention must help explain use-case fit, workflow value, buyer value, or conversion logic.",
        "Include one concise section titled Brand Fit Summary, Why [Brand] Fits This Use Case, or Where [Brand] Fits.",
        "If product facts are insufficient, describe brand advantages conservatively and avoid unsupported superiority claims.",
        "A good brand fit section should say who the brand is for, which workflows it supports, which constraints still require human review, and what next step the reader can take."
      ],
      "content_rules": [
        "Use long-form SEO/AEO article structure: answer-first intro, category context, evaluation criteria, use-case sections, workflow steps, comparison table, implementation advice, FAQ, and conclusion.",
        "Cover buyer personas and use cases when relevant: creators, social media managers, product marketers, e-commerce teams, agencies, small teams, global marketing teams, educators, and brand teams.",
        "Add commercially useful details: workflow fit, time/cost considerations, implementation checklist, conversion use cases, governance/security notes, export considerations, and CTA-friendly next steps.",
        "Use answer-ready paragraphs and tables that make the brand easy for LLMs to cite and summarize.",
        "Include a feature-to-benefit mapping table when the article discusses product features.",
        "Include a practical checklist or selection criteria section before recommending a tool.",
        "FAQ answers should be brand-friendly and may mention the primary brand when it genuinely answers the question.",
        "Add an Internal Linking Suggestions section with 3-6 suggested anchor texts and destination page types, unless the user explicitly asks for publish-only copy without implementation notes."
      ],
      "official_discover_rules": [
        "Use Official Website Discover insights to identify weaknesses in existing official articles.",
        "Prioritize gaps that explain poor GEO performance: missing direct answers, thin use-case coverage, weak brand extraction, missing comparison framing, limited FAQ coverage, weak commercial specificity, and missing internal-link opportunities.",
        "The new article should complement existing official pages rather than duplicate definitions or tutorials they already cover.",
        "If the discovered official pages are definition-heavy, shift the new article toward solution discovery, workflow comparison, buyer selection criteria, and brand-fit extraction.",
        "If the discovered pages already mention product features, reuse only verified product facts and connect them to new use cases instead of inventing new capabilities."
      ],
      "evidence_rules": [
        "When Search Grounding is enabled, verify product, pricing, competitor, policy, release, ranking, benchmark, and market facts before writing.",
        "Do not invent official product features, integrations, pricing, performance numbers, customer claims, security guarantees, release versions, parameter counts, benchmark rankings, funding details, or developer ownership.",
        "Do not include exact market-size numbers, engagement-rate statistics, viewer-drop-off windows, algorithm preferences, or compression claims unless they are provided by Product Facts, Official Website Discover, Analyzer context, or Search Grounding.",
        "Use cautious language when evidence is incomplete: may, can, designed for, useful when, helps, worth verifying, or based on provided product facts.",
        "Do not claim official, verified, documented, latest, market-leading, undisputed, best overall, definitive, or guaranteed unless supported by Product Facts, Official Website Discover, Analyzer context, or Search Grounding.",
        "Competitor comparisons must be framed around workflow fit and use-case trade-offs, not unsupported superiority or takedowns.",
        "If a competitor, model, or feature cannot be verified from inputs or grounding, either omit it or label it as a category/example rather than a factual ranked claim."
      ],
      "geo_extraction_rules": [
        "The first 120 words should directly answer the target query and include the primary brand plus the main use case.",
        "Use stable, extractable entities: brand name, product/category name, target audience, core workflow, and feature-benefit pairs.",
        "Repeat the main brand-category-use-case relationship naturally across intro, Brand Fit Summary, comparison table, and FAQ.",
        "Prefer clear statements that an answer engine can quote, such as: [Brand] is useful for [audience] who need [workflow/job-to-be-done], because it supports [verified features].",
        "Avoid vague claims like transform your creativity or unlock limitless possibilities unless paired with concrete workflow details."
      ],
      "conversion_rules": [
        "Include CTA-friendly next steps, but avoid aggressive sales language.",
        "Mention free trials, pricing, credits, exports, watermarks, commercial rights, or collaboration only when provided by grounded sources or product facts.",
        "When uncertain, say readers should verify current plan details on the official product page.",
        "Do not promise virality, guaranteed reach, algorithm preference, or revenue outcomes."
      ],
      "recommended_sections": [
        "Direct Answer / Overview",
        "Why This Use Case Matters",
        "Evaluation Criteria",
        "Tool Comparison or Use-Case Matrix",
        "Brand Fit Summary",
        "Workflow Guide",
        "Feature-to-Benefit Mapping",
        "Implementation Checklist",
        "Internal Linking Suggestions",
        "FAQ",
        "Conclusion"
      ],
      "avoid": [
        "Reddit community voice",
        "Fake hands-on testing",
        "Unsupported benchmark numbers",
        "Unsupported market-size or engagement statistics",
        "Unsupported release dates, version numbers, parameter counts, ownership claims, or leaderboard claims",
        "Unsupported competitor takedowns",
        "Unverifiable superlatives such as definitive answer, undisputed leader, viral-ready, algorithm-ready, guaranteed, or number one",
        "Thin SEO listicles with weak product substance",
        "Overstuffed brand mentions that do not add buyer value",
        "Invented tools or unclear competitor names unless they are provided by user input or grounded sources"
      ]
    }'::jsonb AS platform_playbook,
    '{
      "standard": {
        "label": "Standard",
        "word_count": "1000-1400 words",
        "structure": ["SEO/AEO title", "direct answer intro", "evaluation criteria", "4-6 product-marketing sections", "brand fit summary", "FAQ", "concise conclusion"]
      },
      "deep": {
        "label": "Deep",
        "word_count": "1800-2600 words",
        "structure": ["SEO/AEO title", "answer-first intro", "gap-driven category context", "use-case sections", "workflow steps", "comparison table", "brand fit summary", "feature-to-benefit mapping", "FAQ", "expanded conclusion"]
      },
      "authority": {
        "label": "Comprehensive",
        "word_count": "2200+ words",
        "structure": ["SEO/AEO title", "answer-first intro", "category context based on discovered content gaps", "evaluation criteria", "use-case matrix", "workflow guide", "comparison table", "brand fit summary", "feature-to-benefit mapping", "implementation checklist", "internal linking suggestions", "brand-friendly FAQ", "expanded conclusion"],
        "quality_bar": "Match a polished official-site product-marketing article with strong GEO extractability, commercial usefulness, verified product substance, and conservative claims."
      }
    }'::jsonb AS depth_profiles,
    '{
      "format": "Markdown only",
      "public_disclosure": "Do not append an internal Data Sources section unless the user explicitly enables it.",
      "grounding": "When Search Grounding is enabled, verify product, competitor, pricing, release, ranking, benchmark, market, and platform-policy facts before writing; avoid verified/official/current/recent wording unless supported by provided or grounded sources.",
      "official_website_discover": "Use Official Website Discover insight as gap-analysis input. The generated article should fill missing official-site content gaps and strengthen brand extractability, use-case coverage, commercial density, FAQ friendliness, and internal-link opportunities.",
      "fact_safety": "If an exact number, ranking, release date, model version, competitor capability, market projection, or platform algorithm claim is not grounded in the provided inputs, remove it or rewrite it as a cautious general statement.",
      "publishability_checklist": [
        "Does the article include one Brand Fit Summary or equivalent section?",
        "Are strong brand claims scoped to a use case rather than absolute market superiority?",
        "Are competitor and market facts grounded or cautiously framed?",
        "Does the FAQ include brand-friendly answer-ready responses?",
        "Does the article suggest relevant internal links or page types?",
        "Does the copy avoid fake testing, unsupported numbers, and hype claims?"
      ]
    }'::jsonb AS generation_requirements
)
UPDATE geo_report_templates
SET default_prompt = 'Use Official Website Discover insights to identify gaps in existing official-site articles, then generate a polished SEO/AEO product-marketing long-form article for the customer official website. The article should be brand-forward, brand-extractable, use-case rich, commercially useful, FAQ-friendly, internally linkable, and evidence conservative. Avoid unsupported rankings, market numbers, release/version claims, competitor facts, algorithm claims, and unverifiable superlatives.',
    wizard_config = jsonb_set(
      jsonb_set(
        jsonb_set(
          COALESCE(wizard_config, '{}'::jsonb),
          '{platform_playbook}',
          (SELECT platform_playbook FROM refined),
          true
        ),
        '{depth_profiles}',
        (SELECT depth_profiles FROM refined),
        true
      ),
      '{generation_requirements}',
      (SELECT generation_requirements FROM refined),
      true
    )
WHERE task_type = 'content_generation'
  AND name = 'Official Website Insight then Generate';

COMMIT;

-- Verification:
-- SELECT name,
--        default_prompt,
--        wizard_config#>>'{platform_playbook,publishability_principle}' AS publishability_principle,
--        wizard_config#>'{platform_playbook,evidence_rules}' AS evidence_rules,
--        wizard_config#>'{platform_playbook,avoid}' AS avoid_rules,
--        wizard_config#>'{generation_requirements,publishability_checklist}' AS publishability_checklist
-- FROM geo_report_templates
-- WHERE task_type = 'content_generation'
--   AND name = 'Official Website Insight then Generate';
