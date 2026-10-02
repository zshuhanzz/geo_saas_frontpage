import pytest

from services import citation_analysis


def test_resolve_citation_analysis_config_uses_template_enabled_and_input_overrides():
    config = citation_analysis.resolve_citation_analysis_config(
        inputs={
            "citation_analysis": {
                "citation_source_scope": "reddit_citations",
                "citation_max_sources": 7,
                "citation_fetch_full_pages": False,
                "citation_include_domains": "reddit.com, youtube.com",
            }
        },
        template_runtime_config={
            "citation_analysis": {"enabled": True},
            "citation_analysis_step": {
                "enabled": True,
                "citation_source_scope": "official_article_citations",
                "citation_max_sources": 12,
                "citation_fetch_full_pages": True,
                "citation_exclude_domains": "instagram.com",
            },
        },
    )

    assert config.enabled is True
    assert config.source_scope == "reddit_citations"
    assert config.max_sources == 7
    assert config.fetch_full_pages is False
    assert config.include_domains == ["reddit.com", "youtube.com"]
    assert config.exclude_domains == ["instagram.com"]


def test_resolve_citation_analysis_config_reads_template_brief_rules():
    config = citation_analysis.resolve_citation_analysis_config(
        inputs={},
        template_runtime_config={
            "citation_analysis": {
                "enabled": True,
                "brief_rules": [
                    "Configured rule one.",
                    "Configured rule two.",
                ],
            },
            "citation_analysis_step": {"enabled": True},
        },
    )

    assert config.brief_rules == ["Configured rule one.", "Configured rule two."]


def test_resolve_citation_analysis_config_stays_disabled_for_existing_templates():
    config = citation_analysis.resolve_citation_analysis_config(
        inputs={
            "citation_analysis": {
                "citation_source_scope": "auto_by_template",
                "citation_max_sources": 10,
            }
        },
        template_runtime_config={
            "citation_analysis": {"enabled": False},
            "citation_analysis_step": {"enabled": False},
        },
    )

    assert config.enabled is False


def test_build_citation_analysis_fingerprint_uses_only_citation_relevant_inputs():
    template_runtime_config = {
        "citation_analysis": {"enabled": True},
        "citation_analysis_step": {
            "enabled": True,
            "citation_source_scope": "reddit_citations",
            "citation_max_sources": 12,
            "citation_include_domains": "reddit.com",
        },
    }
    base_inputs = {
        "content_type": "reddit_article",
        "selected_metrics": ["answerability"],
        "topic_ids": ["topic-1"],
        "prompt_ids": ["prompt-1"],
        "citation_analysis": {
            "citation_source_scope": "reddit_citations",
            "citation_max_sources": 12,
            "citation_include_domains": "reddit.com",
        },
    }
    changed_non_citation = {
        **base_inputs,
        "user_strategy_edits": "Make the intro more concise",
        "count": 3,
    }
    changed_citation = {
        **base_inputs,
        "citation_analysis": {
            "citation_source_scope": "reddit_citations",
            "citation_max_sources": 8,
            "citation_include_domains": "reddit.com",
        },
    }

    first = citation_analysis.build_citation_analysis_fingerprint(
        inputs=base_inputs,
        template_runtime_config=template_runtime_config,
    )
    second = citation_analysis.build_citation_analysis_fingerprint(
        inputs=changed_non_citation,
        template_runtime_config=template_runtime_config,
    )
    third = citation_analysis.build_citation_analysis_fingerprint(
        inputs=changed_citation,
        template_runtime_config=template_runtime_config,
    )

    assert first == second
    assert first != third
    assert len(first) == 64


def test_rule_based_brand_triage_classifies_unmentioned_and_positive_neutral():
    aliases = citation_analysis.extract_brand_aliases({
        "brand_name": "Dreamina",
        "own_brands": [{"brand_name": "Dreamina", "aliases": ["Dreamina AI"]}],
    })

    unmentioned = citation_analysis.triage_citation_source(
        citation_analysis.CitationSource(
            url="https://reddit.com/r/aivideo/comments/example",
            domain="reddit.com",
            citation_count=11,
            domain_category="Social Media",
            prompt_examples=["best ai video generator"],
            page_text="People compare tools for Instagram Reels and talk about workflows.",
        ),
        aliases,
    )
    mentioned = citation_analysis.triage_citation_source(
        citation_analysis.CitationSource(
            url="https://example.com/best-ai-video-tools",
            domain="example.com",
            citation_count=5,
            domain_category="Earned Media",
            prompt_examples=["best ai video generator"],
            page_text="Dreamina AI is mentioned as a useful option for short-form video creators.",
        ),
        aliases,
    )

    assert unmentioned.mention_state == "unmentioned"
    assert unmentioned.recommended_action == "new_content_gap"
    assert mentioned.mention_state == "positive_neutral"
    assert mentioned.recommended_action == "refresh_extractability"
    assert "Dreamina AI" in mentioned.evidence[0]


def test_aggregate_citation_analysis_prefers_clarification_for_negative_misleading():
    sources = [
        citation_analysis.CitationSource(
            url="https://example.com/review",
            domain="example.com",
            citation_count=8,
            domain_category="Earned Media",
            prompt_examples=[],
            triage=citation_analysis.BrandMentionTriage(
                mention_state="negative_misleading",
                brand_mentioned=True,
                evidence=["Claims Dreamina lacks vertical export, but product facts say otherwise."],
                content_risk="high",
                recommended_action="clarification_rebuttal",
            ),
        ),
        citation_analysis.CitationSource(
            url="https://reddit.com/r/aivideo/comments/x",
            domain="reddit.com",
            citation_count=6,
            domain_category="Social Media",
            prompt_examples=[],
            triage=citation_analysis.BrandMentionTriage(
                mention_state="unmentioned",
                brand_mentioned=False,
                evidence=[],
                content_risk="low",
                recommended_action="new_content_gap",
            ),
        ),
    ]

    result = citation_analysis.build_citation_analysis_result(
        config=citation_analysis.CitationAnalysisConfig(enabled=True),
        sources=sources,
        brand_aliases=["Dreamina"],
        platform_profile="official_website",
    )

    assert result["brand_mention_summary"]["negative_misleading"] == 1
    assert result["content_action_decision"]["primary_action"] == "clarification_rebuttal"
    assert "Do not imitate" in result["citation_grounded_brief"]


def test_citation_brief_uses_configured_rules_without_official_hardcoded_sections():
    result = citation_analysis.build_citation_analysis_result(
        config=citation_analysis.CitationAnalysisConfig(
            enabled=True,
            brief_rules=[
                "For official website articles, translate citation patterns into natural reader-facing sections.",
                "Do not require internal framework headings.",
            ],
        ),
        sources=[],
        brand_aliases=["AnswerX"],
        platform_profile="official_website",
    )

    brief = result["citation_grounded_brief"]
    assert "natural reader-facing sections" in brief
    assert "Brand Fit Summary" not in brief
    assert "Value/Dream" not in brief
    assert "Feature-to-Benefit Mapping" not in brief


def test_citation_brief_exposes_learnable_strengths_and_visibility_gaps():
    sources = [
        citation_analysis.CitationSource(
            url="https://www.reddit.com/r/aivideo/comments/example",
            domain="reddit.com",
            citation_count=14,
            page_title="I tested 8 AI video generators for Instagram Reels",
            page_text=(
                "Title: I tested 8 AI video generators for Instagram Reels. "
                "Here is my workflow, pros and cons, and the tools that still need editing."
            ),
            triage=citation_analysis.BrandMentionTriage(
                mention_state="unmentioned",
                brand_mentioned=False,
                recommended_action="new_content_gap",
            ),
        )
    ]

    result = citation_analysis.build_citation_analysis_result(
        config=citation_analysis.CitationAnalysisConfig(enabled=True),
        sources=sources,
        brand_aliases=["Dreamina"],
        platform_profile="reddit",
    )

    brief = result["citation_grounded_brief"]
    assert "Why AI likely cites these sources" in brief
    assert "Gaps to fill for customer GEO visibility" in brief
    assert "first-person" in brief.lower() or "field-tested" in brief.lower()
    assert "brand is missing" in brief.lower()
    assert result["citation_source_patterns"]["learnable_strengths"]
    assert result["citation_source_patterns"]["visibility_gaps"]


def test_build_citation_source_query_is_tenant_and_prompt_scoped():
    config = citation_analysis.CitationAnalysisConfig(
        enabled=True,
        source_scope="reddit_citations",
        include_domains=["reddit.com"],
        exclude_domains=["youtube.com"],
        max_sources=12,
        query_override="instagram reels",
    )

    sql, params = citation_analysis.build_citation_source_query(
        client_id="00000000-0000-0000-0000-000000000000",
        inputs={
            "target_prompt_ids": ["11111111-1111-1111-1111-111111111111"],
            "topic_ids": ["22222222-2222-2222-2222-222222222222"],
        },
        config=config,
    )

    assert "c.client_id = $1::uuid" in sql
    assert "cp.client_id = c.client_id" in sql
    assert "c.client_prompt_id = ANY" in sql
    assert "cp.topic_id = ANY" in sql
    assert "LOWER(c.source_domain) LIKE" in sql
    assert params[0] == "00000000-0000-0000-0000-000000000000"
    assert params[-1] == 12


def test_auto_by_template_routes_citation_scope_from_publish_platform():
    reddit_sql, _ = citation_analysis.build_citation_source_query(
        client_id="00000000-0000-0000-0000-000000000000",
        inputs={"publish_platform": "reddit"},
        config=citation_analysis.CitationAnalysisConfig(
            enabled=True,
            source_scope="auto_by_template",
        ),
    )
    official_sql, _ = citation_analysis.build_citation_source_query(
        client_id="00000000-0000-0000-0000-000000000000",
        inputs={"publish_platform": "official_site"},
        config=citation_analysis.CitationAnalysisConfig(
            enabled=True,
            source_scope="auto_by_template",
        ),
    )

    assert "LIKE '%reddit.com'" in reddit_sql
    assert "NOT LIKE '%reddit.com'" in official_sql
    assert "NOT LIKE '%youtube.com'" in official_sql


def test_brand_mention_policy_prioritizes_matching_triage_states():
    sources = [
        citation_analysis.CitationSource(
            url="https://example.com/negative",
            domain="example.com",
            citation_count=10,
            triage=citation_analysis.BrandMentionTriage(
                mention_state="negative_misleading",
                brand_mentioned=True,
            ),
        ),
        citation_analysis.CitationSource(
            url="https://reddit.com/unmentioned",
            domain="reddit.com",
            citation_count=8,
            triage=citation_analysis.BrandMentionTriage(
                mention_state="unmentioned",
                brand_mentioned=False,
            ),
        ),
        citation_analysis.CitationSource(
            url="https://example.com/positive",
            domain="example.com",
            citation_count=12,
            triage=citation_analysis.BrandMentionTriage(
                mention_state="positive_neutral",
                brand_mentioned=True,
            ),
        ),
    ]

    prioritized = citation_analysis.apply_brand_mention_policy(
        sources,
        citation_analysis.CitationAnalysisConfig(
            enabled=True,
            brand_mention_policy="prioritize_unmentioned",
        ),
    )
    clarified = citation_analysis.apply_brand_mention_policy(
        sources,
        citation_analysis.CitationAnalysisConfig(
            enabled=True,
            brand_mention_policy="clarify_negative_misleading",
        ),
    )

    assert prioritized[0].triage.mention_state == "unmentioned"
    assert clarified[0].triage.mention_state == "negative_misleading"


def test_llm_triage_is_required_for_unmentioned_comparison_shortlists():
    source = citation_analysis.CitationSource(
        url="https://example.com/best-ai-video-tools",
        domain="example.com",
        citation_count=5,
        page_text="A ranked comparison of the best AI video generators, alternatives, pricing, pros and cons.",
        triage=citation_analysis.BrandMentionTriage(
            mention_state="unmentioned",
            brand_mentioned=False,
        ),
    )

    assert citation_analysis.needs_llm_triage(source, source.triage) is True


def test_extract_page_content_prefers_article_and_metadata():
    html = """
    <html>
      <head>
        <title>Best AI Video Tools</title>
        <meta name="description" content="A practical comparison for AI video creators.">
        <link rel="canonical" href="https://example.com/canonical">
        <script>window.noise = true;</script>
      </head>
      <body>
        <nav>Navigation should not dominate extraction.</nav>
        <article>
          <h1>Best AI Video Tools</h1>
          <p>Dreamina is compared with other tools for Instagram Reels.</p>
        </article>
      </body>
    </html>
    """

    extracted = citation_analysis.extract_page_content(
        html,
        content_type="text/html",
        source_url="https://example.com/original",
    )

    assert extracted["title"] == "Best AI Video Tools"
    assert extracted["meta_description"] == "A practical comparison for AI video creators."
    assert extracted["canonical_url"] == "https://example.com/canonical"
    assert "Dreamina is compared" in extracted["text"]
    assert "window.noise" not in extracted["text"]


def test_parse_llm_triage_response_validates_schema_and_values():
    parsed = citation_analysis.parse_llm_triage_response({
        "items": [
            {
                "index": 0,
                "brand_mentioned": True,
                "mention_state": "positive_neutral",
                "evidence": ["Dreamina is listed as a practical option."],
                "content_risk": "low",
                "recommended_action": "refresh_extractability",
            },
            {
                "index": 1,
                "brand_mentioned": True,
                "mention_state": "unsupported_state",
                "evidence": "not a list",
                "content_risk": "low",
                "recommended_action": "refresh_extractability",
            },
        ]
    })

    assert len(parsed.items) == 1
    assert parsed.items[0].mention_state == "positive_neutral"


def test_reddit_verification_page_detection_and_json_extraction():
    blocked_text = "Reddit - Dive into anything Please wait for verification. Your request has been blocked."
    assert citation_analysis.looks_like_reddit_verification_page(blocked_text) is True

    payload = [
        {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Testing AI video tools for Reels",
                            "selftext": "I compared Dreamina, Kling, and Runway for short-form video workflows.",
                            "subreddit": "aivideo",
                            "score": 42,
                            "num_comments": 9,
                            "permalink": "/r/aivideo/comments/abc/testing_ai_video_tools/",
                        }
                    }
                ]
            }
        },
        {
            "data": {
                "children": [
                    {"data": {"body": "The useful posts show tradeoffs instead of marketing claims.", "score": 8}},
                    {"data": {"body": "[deleted]", "score": 1}},
                ]
            }
        },
    ]

    extracted = citation_analysis.extract_reddit_json_content(
        citation_analysis.json.dumps(payload),
        source_url="https://www.reddit.com/r/aivideo/comments/abc/testing_ai_video_tools/",
    )

    assert "Testing AI video tools for Reels" in extracted["text"]
    assert "Dreamina, Kling, and Runway" in extracted["text"]
    assert "tradeoffs instead of marketing claims" in extracted["text"]
    assert extracted["title"] == "Testing AI video tools for Reels"


def test_reddit_fetch_candidates_include_json_and_old_reddit():
    candidates = citation_analysis.build_reddit_fetch_candidates(
        "https://www.reddit.com/r/aivideo/comments/abc/testing_ai_video_tools/?utm_source=chatgpt.com"
    )

    assert candidates[0].endswith("/testing_ai_video_tools.json?raw_json=1")
    assert "https://api.reddit.com/r/aivideo/comments/abc/testing_ai_video_tools/?raw_json=1" in candidates
    assert "https://old.reddit.com/r/aivideo/comments/abc/testing_ai_video_tools/" in candidates
