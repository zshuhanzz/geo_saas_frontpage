import json
import asyncio

from services.reddit_research import (
    RedditResearchConfig,
    RedditTargetingContext,
    WebGroundedRedditResearchProvider,
    build_reddit_research_config,
    build_reddit_research_fingerprint,
    extract_reddit_discovery_insights,
    extract_subreddit_name_from_url,
    load_reddit_research_config,
    normalize_subreddit_name,
    parse_reddit_about_json,
    parse_reddit_rules_json,
    parse_reddit_rules_text,
)


def test_web_grounded_config_can_run_without_reddit_api_credentials():
    cfg = build_reddit_research_config(
        {
            "reddit_research_provider": "web_grounded",
            "reddit_web_fetch_enabled": "true",
            "reddit_grounding_model_id": "gemini-3-flash-preview",
            "reddit_research_fetch_user_agent": "AnswerX-GEO/1.0",
        }
    )

    assert cfg.provider == "web_grounded"
    assert cfg.can_run is True


def test_new_global_reddit_grounding_config_overrides_legacy_template_values():
    class Row(dict):
        def __getitem__(self, key):
            return dict.__getitem__(self, key)

    class Pool:
        async def fetch(self, _sql, _keys):
            return [
                Row(key="reddit_research_grounding_model_id", value="gemini-3.5-flash"),
                Row(key="reddit_research_grounding_timeout_seconds", value="180"),
            ]

    template_runtime_config = {
        "reddit_research": {
            "provider": "web_grounded",
            "provider_config": {
                "web_grounded": {
                    "web_fetch_enabled": True,
                    "grounding_model_id": "gemini-3-flash-preview",
                    "request_timeout_seconds": 20,
                    "fetch_user_agent": "AnswerX-GEO/1.0",
                }
            },
        }
    }

    cfg = asyncio.run(load_reddit_research_config(Pool(), template_runtime_config))

    assert cfg.grounding_model_id == "gemini-3.5-flash"
    assert cfg.request_timeout_seconds == 180


def test_web_grounded_reddit_targeting_retries_deadline_errors(monkeypatch):
    calls = {"count": 0}

    class ModelAPI:
        async def generate_content(self, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("504 DEADLINE_EXCEEDED")
            return type("Response", (), {"text": json.dumps({
                "candidates": [{
                    "name": "r/aivideo",
                    "url": "https://www.reddit.com/r/aivideo/",
                    "relevance_reason": "AI video creator discussion.",
                    "posting_risk": "Self-promotion rules vary.",
                    "confidence": 0.82,
                }]
            })})()

    class Client:
        aio = type("Aio", (), {"models": ModelAPI()})()

    async def fake_get_client(_model_id, role="flash", timeout_seconds=None):
        assert role == "flash"
        assert timeout_seconds == 180
        return Client()

    async def fake_sleep(_seconds):
        return None

    async def fake_resolve(_self, name):
        return {
            "name": f"r/{name}",
            "display_name": name,
            "title": name,
            "public_description": "",
            "subscribers": 0,
            "over18": False,
            "subreddit_type": "public",
            "url": f"https://www.reddit.com/r/{name}/",
            "source": "web_grounded",
            "metadata_status": "verified",
        }

    monkeypatch.setattr("services.reddit_research.get_genai_client", fake_get_client)
    monkeypatch.setattr("services.reddit_research.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(WebGroundedRedditResearchProvider, "resolve_subreddit", fake_resolve)

    provider = WebGroundedRedditResearchProvider(RedditResearchConfig(
        provider="web_grounded",
        web_fetch_enabled=True,
        grounding_model_id="gemini-3.5-flash",
        grounding_timeout_seconds=180,
        fetch_user_agent="AnswerX-GEO/1.0",
        request_timeout_seconds=180,
        max_subreddit_candidates=12,
        max_posts_per_subreddit=10,
        api_enabled=False,
        api_commercial_access_approved=False,
        client_id="",
        client_secret="",
        api_user_agent="",
    ))
    context = RedditTargetingContext(
        client_id="client",
        template_id="template",
        brand_context={},
        topics=["AI Video"],
        prompts=[],
        citation_analysis_result=None,
        content_type="reddit_article",
        keywords="AI Video",
    )

    result = asyncio.run(provider.recommend_subreddits(context, 1))

    assert calls["count"] == 2
    assert result[0]["display_name"] == "aivideo"


def test_web_grounded_reddit_discovery_retries_malformed_json(monkeypatch):
    calls = {"count": 0}

    async def fake_generate(_prompt, *, response_schema=None, max_output_tokens=8192):
        assert response_schema
        assert max_output_tokens >= 8192
        calls["count"] += 1
        if calls["count"] == 1:
            return type("Response", (), {"text": '{"metadata":{"display_name":"klingai" "title":"KlingAI"}}'})()
        return type("Response", (), {"text": json.dumps({
            "metadata": {
                "name": "r/klingai",
                "display_name": "klingai",
                "title": "KlingAI",
                "public_description": "Kling AI community context.",
            },
            "rules": {"rules_status": "unavailable", "rules_source_url": "", "rules": []},
            "sidebar_summary": "Kling AI community context.",
            "posts": {"search": [], "hot": [], "top": [], "new": []},
            "posting_capability": {},
            "risk_signals": {"rules": [], "sidebar": [], "posts": []},
            "source_urls": [],
        })})()

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr("services.reddit_research.asyncio.sleep", fake_sleep)

    provider = WebGroundedRedditResearchProvider(RedditResearchConfig(
        provider="web_grounded",
        web_fetch_enabled=True,
        grounding_model_id="gemini-3.5-flash",
        grounding_timeout_seconds=180,
        fetch_user_agent="AnswerX-GEO/1.0",
        request_timeout_seconds=180,
        max_subreddit_candidates=12,
        max_posts_per_subreddit=10,
        api_enabled=False,
        api_commercial_access_approved=False,
        client_id="",
        client_secret="",
        api_user_agent="",
    ))
    monkeypatch.setattr(provider, "_generate_grounded_candidates", fake_generate)

    result = asyncio.run(provider.discover_subreddit("klingai", query="AI video", limit=5))

    assert calls["count"] == 2
    assert result["metadata"]["display_name"] == "klingai"
    assert result["rules_status"] == "unavailable"


def test_reddit_api_config_requires_commercial_access():
    cfg = build_reddit_research_config(
        {
            "reddit_research_provider": "reddit_api",
            "reddit_api_enabled": "true",
            "reddit_api_commercial_access_approved": "false",
            "reddit_api_client_id": "cid",
            "reddit_api_client_secret": "secret",
            "reddit_api_user_agent": "AnswerX/1.0",
        }
    )

    assert cfg.can_run is False
    assert "commercial" in cfg.block_reason.lower()


def test_normalize_subreddit_name_accepts_common_forms():
    assert normalize_subreddit_name("r/robotvacuums") == "robotvacuums"
    assert normalize_subreddit_name("https://www.reddit.com/r/VideoEditing/") == "VideoEditing"
    assert normalize_subreddit_name("  artificial  ") == "artificial"


def test_extract_subreddit_name_from_url_rejects_non_subreddit_urls():
    assert extract_subreddit_name_from_url("https://www.reddit.com/r/VacuumCleaners/about/") == "VacuumCleaners"
    assert extract_subreddit_name_from_url("https://example.com/r/VacuumCleaners/") is None
    assert extract_subreddit_name_from_url("not a url") is None


def test_parse_reddit_rules_json_maps_rules_with_verified_source():
    raw = json.dumps(
        {
            "rules": [
                {
                    "short_name": "No self-promotion",
                    "description": "Avoid affiliate links and promotional posts.",
                    "kind": "link",
                    "priority": 0,
                },
                {
                    "short_name": "Be respectful",
                    "description": "",
                    "kind": "all",
                    "priority": 1,
                },
            ]
        }
    )

    parsed = parse_reddit_rules_json(
        raw,
        subreddit="RobotVacuums",
        source_url="https://www.reddit.com/r/RobotVacuums/about/rules.json",
    )

    assert parsed["rules_status"] == "verified"
    assert parsed["rules_source_url"].endswith("/about/rules.json")
    assert parsed["rules"][0]["short_name"] == "No self-promotion"
    assert parsed["rules"][0]["description"] == "Avoid affiliate links and promotional posts."


def test_parse_reddit_about_json_maps_metadata():
    raw = json.dumps(
        {
            "data": {
                "display_name": "RobotVacuums",
                "title": "Robot Vacuums",
                "public_description": "Reviews and help for robot vacuums.",
                "subscribers": 12345,
                "over18": False,
                "subreddit_type": "public",
            }
        }
    )

    parsed = parse_reddit_about_json(raw, source="web_grounded")

    assert parsed["name"] == "r/RobotVacuums"
    assert parsed["display_name"] == "RobotVacuums"
    assert parsed["subscribers"] == 12345
    assert parsed["source"] == "web_grounded"


def test_reddit_research_fingerprint_is_stable_for_key_order():
    first = build_reddit_research_fingerprint({
        "topics": ["Robot Vacuums"],
        "prompts": [{"id": "p1", "text": "Which vacuum works for pet hair?"}],
        "citation": {"fingerprint": "abc"},
    })
    second = build_reddit_research_fingerprint({
        "citation": {"fingerprint": "abc"},
        "prompts": [{"text": "Which vacuum works for pet hair?", "id": "p1"}],
        "topics": ["Robot Vacuums"],
    })

    assert first == second
    assert len(first) == 64


def test_parse_reddit_rules_text_extracts_deterministic_rules():
    parsed = parse_reddit_rules_text(
        "Rules\n1. No self-promotion\n2. Be respectful\n3. Keep posts on topic",
        subreddit="RobotVacuums",
        source_url="https://www.reddit.com/r/RobotVacuums/about/",
    )

    assert parsed["rules_status"] == "verified"
    assert parsed["rules_source_url"].endswith("/about/")
    assert [r["short_name"] for r in parsed["rules"]] == [
        "No self-promotion",
        "Be respectful",
        "Keep posts on topic",
    ]


def test_extract_reddit_discovery_insights_from_posts_and_sidebar():
    insights = extract_reddit_discovery_insights(
        sidebar="No affiliate links. Use honest comparisons.",
        posts=[
            {
                "title": "Which robot vacuum handles pet hair without getting stuck?",
                "score": 42,
                "num_comments": 18,
                "url": "https://www.reddit.com/r/RobotVacuums/comments/1",
            },
            {
                "title": "Avoid sponsored rankings for hardwood floor recommendations",
                "score": 11,
                "num_comments": 5,
                "url": "https://www.reddit.com/r/RobotVacuums/comments/2",
            },
        ],
    )

    assert insights["community_questions"] == [
        "Which robot vacuum handles pet hair without getting stuck?"
    ]
    assert any("sponsored" in item.lower() for item in insights["objections"])
    assert any("affiliate" in item.lower() for item in insights["risks"])
