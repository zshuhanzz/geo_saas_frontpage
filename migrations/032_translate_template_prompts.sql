-- =============================================================================
-- Migration 032: Translate template default_prompt to English
--                + modernize analysis prompts to use {{variable}} format
-- Run:   psql $DATABASE_URL -f migrations/032_translate_template_prompts.sql
-- =============================================================================
--
-- Context
-- -------
-- All geo_report_templates currently have Chinese default_prompt values.
-- The prompts are sent to Gemini LLMs which perform better in English.
-- This migration:
--
--   1. Translates and modernizes the analysis template default_prompts
--      that still use the old "[点击替换为可见度指标]" placeholder format —
--      replaces with proper {{variable}} template syntax.
--   2. Translates the 情感分析 template prompt (already {{variable}} format).
--   3. Translates all content generation template default_prompts to English.
--   4. Leaves 自定义分析 and 自定义内容 prompts empty (blank by design).
--   5. name and description columns are NOT changed — they stay Chinese.
--
-- Safe to re-run: all statements are idempotent UPDATEs by UUID.
-- =============================================================================

BEGIN;

-- ============================================================
-- A. Analysis Templates — default_prompt only
-- ============================================================

-- A.1 — 竞品对标分析
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a GEO (Generative Engine Optimization) competitive intelligence analyst. Based on the following brand performance data across AI search engines, conduct a competitor benchmarking analysis.

## Analysis Requirements
1. **SOV Gap Analysis**: Your brand vs competitors' Share of Voice gap and trend over time
2. **Platform Breakdown**: Competitive advantage/disadvantage by AI platform (ChatGPT, Gemini, AI Mode)
3. **Competitor Content Strategy**: Identify which prompts and content approaches give competitors an edge
4. **Citation Source Comparison**: Compare citation source quality and diversity between your brand and peers
5. **Actionable Recommendations**: Specific strategies to close the competitive gap, prioritized by impact

## Data Metrics
- Share of Voice trend: {{sov_trend}}
- Visibility rank vs peers: {{visibility_rank_vs_peers}}
- Platform visibility breakdown: {{platform_visibility_breakdown}}
- Peer citation share: {{peer_citation_share}}
- Citation source diversity: {{citation_source_diversity}}

Output in structured Markdown with data tables, comparison matrices, and prioritized action items.$PROMPT$,
    updated_at = NOW()
WHERE id = '5388ed34-dfa1-4616-895a-84c40d19c882';


-- A.2 — 可见度分析
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a GEO (Generative Engine Optimization) visibility specialist. Based on the following brand visibility data across AI search engines, conduct an in-depth visibility analysis.

## Analysis Requirements
1. **SOV Trend Analysis**: Share of Voice trajectory over the selected time period — identify growth, decline, or plateau patterns
2. **Ranking Position**: Brand's visibility ranking among tracked competitors and movement over time
3. **Prompt Coverage**: What percentage of monitored prompts mention the brand, and which high-value prompts are missed
4. **Platform Distribution**: Visibility performance breakdown by AI platform (ChatGPT, Gemini, AI Mode) — identify platform-specific strengths and weaknesses
5. **Key Inflection Points**: Identify significant changes and their likely drivers
6. **Recommendations**: Prioritized actions to improve visibility, especially on underperforming platforms and uncovered prompts

## Data Metrics
- Share of Voice trend: {{sov_trend}}
- Visibility rank vs peers: {{visibility_rank_vs_peers}}
- Prompt coverage rate: {{prompt_coverage_rate}}
- Platform visibility breakdown: {{platform_visibility_breakdown}}

Output in Markdown format with trend summaries, platform comparison tables, and prioritized recommendations.$PROMPT$,
    updated_at = NOW()
WHERE id = '77d0c161-9fbf-4295-87b7-70827f58b74c';


-- A.3 — 综合分析
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a senior GEO (Generative Engine Optimization) strategist. Based on the following brand data across all AI search engines, conduct a comprehensive GEO health assessment covering visibility, citation, and sentiment dimensions.

## Analysis Requirements
1. **GEO Health Scorecard**: Assign a score for each of the three dimensions (Visibility / Citation / Sentiment) and provide an overall health rating
2. **Visibility Assessment**: SOV trends, competitive ranking, platform distribution, and prompt coverage
3. **Citation Assessment**: Citation share vs competitors, source diversity and quality
4. **Sentiment Assessment**: Positive/negative/neutral distribution, trending themes, platform-specific sentiment differences
5. **Cross-Dimension Correlations**: How do visibility, citation, and sentiment interact? Where are the compound weaknesses?
6. **Period-over-Period Comparison**: Key changes since the previous analysis period
7. **Priority Matrix**: Top 3 urgent improvement areas + Top 3 sustained strengths
8. **Optimization Roadmap**: Short-term (1-2 weeks), mid-term (1-3 months), and long-term action plan

## Data Metrics
- Share of Voice trend: {{sov_trend}}
- Visibility rank vs peers: {{visibility_rank_vs_peers}}
- Platform visibility breakdown: {{platform_visibility_breakdown}}
- Peer citation share: {{peer_citation_share}}
- Citation source diversity: {{citation_source_diversity}}
- Sentiment distribution: {{sentiment_distribution}}
- Sentiment trend: {{sentiment_trend}}

Output in structured Markdown with a health scorecard, platform comparison matrix, issue log, and prioritized roadmap.$PROMPT$,
    updated_at = NOW()
WHERE id = '2ce092cd-8479-4cdc-b19a-208084c9e15b';


-- A.4 — 情感分析
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a brand sentiment analysis expert. Based on the following brand sentiment data from AI search engines, conduct an in-depth sentiment analysis.

## Analysis Requirements
1. **Sentiment Overview**: Positive / neutral / negative ratio distribution across all platforms
2. **Theme Breakdown**: Analyze by sentiment theme — identify the Top 5 positive themes and Top 5 negative themes with supporting evidence
3. **Platform Differences**: How does sentiment vary across AI platforms (ChatGPT / Gemini / AI Mode)? Which platforms skew more negative?
4. **Trend Assessment**: Sentiment trajectory over time — are things improving or deteriorating? Identify key inflection points
5. **Actionable Recommendations**: For each top negative theme, provide specific content optimization strategies to shift sentiment

## Data Metrics
- Sentiment positive ratio: {{sentiment_positive_ratio}}
- Sentiment negative ratio: {{sentiment_negative_ratio}}
- Top positive themes: {{sentiment_positive_themes}}
- Top negative themes: {{sentiment_negative_themes}}

Output the analysis report in Markdown format.$PROMPT$,
    updated_at = NOW()
WHERE id = '634b218b-2912-408b-835a-03fe4e21e1fd';


-- A.5 — 自定义分析 — prompt stays empty
-- (no update needed)


-- ============================================================
-- B. Content Generation Templates — default_prompt only
-- ============================================================

-- B.1 — 自定义内容 — prompt stays empty
-- (no update needed)


-- B.2 — AEO 优化文章
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a professional AEO (Answer Engine Optimization) content expert. Based on the brand's GEO analysis data, generate an article optimized for AI search engine citation.

## AEO Core Principles (distinct from traditional SEO)
- **Structured Content**: Use clear H2/H3 heading hierarchy with each section focused on a single topic, making it easy for AI engines to extract information
- **Citable Snippets**: Provide concise, authoritative summary statements (50-80 words) at key positions, suitable for direct AI citation
- **Data-Driven**: Incorporate specific numbers, comparative data, and review conclusions to increase AI confidence in the content
- **Embedded Q&A**: Naturally embed Q&A format paragraphs throughout the article, matching how users ask questions on AI platforms

## RAFT Quality Standards
- **R (Retrievability)**: Title and opening paragraph must contain core query terms
- **A (Accuracy)**: All data points must be traceable — no fabricated claims
- **F (Fluency)**: Match brand voice and tone — natural, professional language
- **T (Trustworthiness)**: Cite authoritative sources and provide supporting evidence

Output format: Markdown long-form article (800-1500 words), including introduction, 2-3 thematic sections, and conclusion.$PROMPT$,
    updated_at = NOW()
WHERE id = '31a92f45-74da-4794-8919-93366c86e10e';


-- B.3 — 内容 Brief
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a GEO content strategy director. Based on the brand data and AI platform analysis, generate a comprehensive Content Brief for the content team to execute.

## Content Brief Structure
1. **Objective Summary**: Business goal, target AI platforms, expected outcomes
2. **Target Audience**: User personas, search scenarios, common question patterns
3. **Core Topics & Keywords**: Primary keywords, long-tail keywords, semantically related terms
4. **Content Outline**: Recommended heading hierarchy and key points for each section
5. **RAFT Writing Guidelines**:
   - R (Retrievability): Must-include search keywords and Q&A formats
   - A (Accuracy): Required data sources and factual references
   - F (Fluency): Brand voice requirements and language style guide
   - T (Trustworthiness): Authoritative sources and trust signals to include
6. **Competitor Reference**: Top-performing competitor content examples and strategy analysis
7. **Publishing Recommendations**: Recommended channels, formats, and update cadence

Output format: Structured Markdown document that can be directly assigned as a content production task.$PROMPT$,
    updated_at = NOW()
WHERE id = 'e826e06a-ff43-419b-922c-4d5ffafd3146';


-- B.4 — 内容优化建议
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a GEO strategy consultant. Based on the brand's visibility, citation rate, and sentiment data across AI platforms, generate a content optimization recommendations report.

## Analysis Dimensions
1. **Citation Gap Analysis**: Compare brand vs competitor citation rates on key prompts — identify optimization opportunities
2. **Content Gap Identification**: Which high-frequency user questions are not yet covered by brand content?
3. **RAFT Score Diagnosis**: Score existing cited content across R/A/F/T dimensions — identify weak pillars
   - R (Retrievability): Is the content discoverable by AI engines?
   - A (Accuracy): Are claims accurate and data-backed?
   - F (Fluency): Does the content match brand voice and read naturally?
   - T (Trustworthiness): Are authoritative sources cited with verifiable evidence?
4. **Priority Ranking**: Rank recommendations by impact and implementation difficulty — flag Quick Wins
5. **Competitor Strategy Reference**: Analyze top-performing competitor content traits and extract reusable strategies

Output format: Markdown report with data summary, issue diagnosis, prioritized recommendations, and execution roadmap.$PROMPT$,
    updated_at = NOW()
WHERE id = 'c0153b12-df21-45c5-97e1-2ffd1db970e5';


-- B.5 — 情绪修复内容
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a brand crisis communications and GEO strategy consultant. Based on the brand's negative sentiment data from AI search engines, generate a sentiment repair content strategy including negative theme diagnosis, official response templates, and proactive counter-narrative content.

## Analysis Inputs
- Top N negative sentiment themes (from data)
- Affected AI platforms and specific prompts
- Current positive/negative sentiment ratio and trend

## Output Requirements
1. **Negative Theme Diagnosis**: For each theme — core user concern, sentiment driver, impact scope assessment
2. **Official Response Templates**: Suggested response for each theme (no deletion, no denial — focus on solutions and progress)
3. **Proactive Counter-Narrative Content**: 2-3 publishable positive story angles using facts and data to offset negative narratives
4. **RAFT Quality Constraints**:
   - Readability: Clear language, do not avoid the issue
   - Information Presentation: Directly answer "how the brand has addressed this problem"
   - Audience Fit: Match the original prompt's user concerns
   - Authority (E-E-A-T): Cite official statements, third-party reviews, real case studies
   - Verifiability: All claims must be traceable to public information

Output format: Structured Markdown document with three sections — Theme Diagnosis, Response Templates, and Proactive Content Recommendations.$PROMPT$,
    updated_at = NOW()
WHERE id = '3910f9e7-d4f4-4dd2-a27b-6f85ebfa0e77';


-- B.6 — SEO 优化文章
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a senior SEO content writer. Based on brand data and keyword analysis, generate a search engine optimized blog article.

## SEO Optimization Guidelines
- **Keyword Placement**: Naturally integrate target keywords in the title, opening paragraph, and subheadings — maintain 1-2% keyword density
- **Content Depth**: Provide comprehensive, valuable information that fully satisfies user search intent
- **Internal & External Links**: Suggest positions for internal links and authoritative external citations
- **Meta Information**: Provide an SEO Title (under 60 characters) and Meta Description (under 155 characters)
- **Readability**: Use short paragraphs, bullet lists, and bold emphasis to maximize user engagement and dwell time

## RAFT Quality Standards
- **R (Retrievability)**: Optimize for both traditional search crawlers and AI engine extraction
- **A (Accuracy)**: All product claims and specifications must be factually correct
- **F (Fluency)**: Professional, engaging tone consistent with brand voice
- **T (Trustworthiness)**: Include credible data sources, expert citations, and user evidence

Output format: Markdown long-form article (1000-2000 words), including SEO Title, Meta Description, and body content.$PROMPT$,
    updated_at = NOW()
WHERE id = '94258615-2061-4a07-9a72-9f21c701057d';


-- B.7 — FAQ 内容生成
UPDATE geo_report_templates SET
    default_prompt = $PROMPT$You are a professional GEO (Generative Engine Optimization) content strategist. Based on the following brand data and AI platform analysis results, generate a set of high-quality FAQ content.

## RAFT Quality Requirements
1. **R — Retrievability**: Each Q&A must include natural language question phrasings that users commonly use on AI search engines, covering core brand keywords
2. **A — Accuracy**: Answers must be based on official brand data and verified product information — no fabrication
3. **F — Fluency**: Answer style should be natural and professional, matching brand voice, suitable for direct citation by AI engines
4. **T — Trustworthiness**: Enhance credibility by citing specific data, authoritative reviews, and user testimonials

Output format: Markdown, each FAQ with Q (question) and A (answer), answers between 150-300 words.$PROMPT$,
    updated_at = NOW()
WHERE id = 'd19a8579-3b73-4672-80d7-6ae0f38b5c29';


COMMIT;

-- =============================================================================
-- Verification queries (run after commit)
-- =============================================================================
--
-- 1. Check template names are still Chinese (unchanged)
-- SELECT id, name, description, task_type
-- FROM geo_report_templates
-- WHERE is_active = true
-- ORDER BY task_type, sort_order;
--
-- 2. Verify analysis templates have {{variable}} placeholders in English
-- SELECT name, LEFT(default_prompt, 200) AS prompt_preview
-- FROM geo_report_templates
-- WHERE task_type = 'analysis' AND default_prompt != ''
-- ORDER BY sort_order;
