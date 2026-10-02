from src.services.unpackers.aioverview import AIOverviewUnpacker
from src.services.unpackers.chatgpt import ChatGPTUnpacker
from src.services.unpackers.factory import UnpackerFactory
from src.services.unpackers.perplexity import PerplexityUnpacker


def test_chatgpt_unpacker_normalizes_old_and_new_response_fields():
    payload = {
        "response": {
            "success": True,
            "result": {
                "text": "ChatGPT answer",
                "html": "<p>ChatGPT answer</p>",
                "markdown": "**ChatGPT answer**",
                "sources": [
                    {"position": 1, "url": "https://source.example/a", "label": "A"},
                ],
                "citationPills": [
                    {"url": "https://source.example/a", "label": "A"},
                    {"link": "https://pill.example/b", "label": "B"},
                ],
                "searchQueries": ["best backup software", {"query": "backup comparison"}],
            },
        }
    }

    result = ChatGPTUnpacker().unpack(payload)

    assert result["text"] == "ChatGPT answer"
    assert result["html"] == "<p>ChatGPT answer</p>"
    assert result["markdown"] == "**ChatGPT answer**"
    assert result["sources"][0]["url"] == "https://source.example/a"
    assert result["citation_pills"][1]["url"] == "https://pill.example/b"
    assert result["search_queries"] == [
        "best backup software",
        {"query": "backup comparison"},
    ]


def test_chatgpt_unpacker_accepts_direct_response_fields():
    payload = {
        "response": {
            "text": "Direct answer",
            "sources": [{"link": "https://source.example/direct", "title": "Direct"}],
            "citationPills": [],
            "searchQueries": [],
        }
    }

    result = ChatGPTUnpacker().unpack(payload)

    assert result["text"] == "Direct answer"
    assert result["sources"][0]["url"] == "https://source.example/direct"
    assert result["citation_pills"] == []
    assert result["search_queries"] == []


def test_chatgpt_unpacker_is_safe_for_missing_null_and_wrong_type_fields():
    payloads = [
        None,
        "not-an-object",
        {"response": None},
        {"response": "not-an-object"},
        {
            "response": {
                "result": {
                    "text": ["wrong"],
                    "html": 42,
                    "markdown": {},
                    "sources": "wrong",
                    "citationPills": None,
                    "searchQueries": {"query": "wrong"},
                }
            }
        },
    ]

    for payload in payloads:
        result = ChatGPTUnpacker().unpack(payload)
        assert result["text"] is None
        assert result["html"] is None
        assert result["markdown"] is None
        assert result["sources"] == []
        assert result["citation_pills"] == []
        assert result["search_queries"] == []


def test_chatgpt_unpacker_filters_invalid_source_and_pill_entries():
    payload = {
        "response": {
            "result": {
                "sources": [None, "wrong", {"url": "https://source.example/a"}],
                "citationPills": [42, {}, {"url": "https://pill.example/b"}],
                "searchQueries": [None, 42, "valid", {"query": "also valid"}],
            }
        }
    }

    result = ChatGPTUnpacker().unpack(payload)

    assert result["sources"] == [
        {
            "url": "https://source.example/a",
            "label": None,
            "description": None,
        }
    ]
    assert result["citation_pills"] == [
        {"url": None},
        {"url": "https://pill.example/b"},
    ]
    assert result["search_queries"] == ["valid", {"query": "also valid"}]


def test_perplexity_unpacker_maps_core_fields():
    payload = {
        "response": {
            "success": True,
            "result": {
                "text": "Perplexity answer",
                "markdown": "**Perplexity answer**",
                "sources": [{"position": 1, "url": "https://example.com", "label": "Example"}],
                "citations": [{"label": "Example +0", "sourceIndexes": [1]}],
                "shopping_cards": [{"products": [{"title": "A"}]}],
                "places": [{"name": "Place"}],
                "hotels": [{"name": "Hotel"}],
                "videos": [{"url": "https://video.example.com"}],
                "related_queries": ["best robot vacuum"],
            },
        }
    }

    result = PerplexityUnpacker().unpack(payload)

    assert result["text"] == "Perplexity answer"
    assert result["markdown"] == "**Perplexity answer**"
    assert result["sources"][0]["url"] == "https://example.com"
    assert result["citation_pills"][0]["label"] == "Example +0"
    assert result["citation_pills"][0]["url"] == "https://example.com"
    assert result["shopping_cards"][0]["products"][0]["title"] == "A"
    assert result["places"] == [{"name": "Place"}, {"name": "Hotel"}]
    assert result["entities"]["videos"][0]["url"] == "https://video.example.com"
    assert result["search_queries"] == ["best robot vacuum"]


def test_ai_overview_unpacker_maps_nested_aioverview_only():
    payload = {
        "response": {
            "success": True,
            "result": {
                "organicResults": [{"title": "Organic", "link": "https://organic.example.com"}],
                "relatedSearches": [{"query": "robot vacuum"}],
                "aiOverview": {
                    "text": "AI Overview answer",
                    "markdown": "AI Overview [source](https://example.com)",
                    "sources": [
                        {
                            "position": 1,
                            "title": "Source Title",
                            "link": "https://example.com",
                            "snippet": "Snippet",
                        }
                    ],
                    "citations": [{"label": "Source +0", "sourceIndexes": [1]}],
                    "videos": [{"url": "https://youtube.example.com"}],
                    "ads": [{"url": "https://ad.example.com"}],
                },
            },
        }
    }

    result = AIOverviewUnpacker().unpack(payload)

    assert result["text"] == "AI Overview answer"
    assert result["sources"] == [
        {
            "position": 1,
            "title": "Source Title",
            "link": "https://example.com",
            "snippet": "Snippet",
            "url": "https://example.com",
            "label": "Source Title",
            "description": "Snippet",
        }
    ]
    assert result["citation_pills"][0]["label"] == "Source +0"
    assert result["citation_pills"][0]["url"] == "https://example.com"
    assert result["entities"]["videos"][0]["url"] == "https://youtube.example.com"
    assert result["entities"]["organic_results"][0]["title"] == "Organic"


def test_ai_overview_unpacker_handles_null_aioverview():
    payload = {
        "response": {
            "success": True,
            "result": {
                "organicResults": [{"title": "Organic"}],
                "aioverview": None,
            },
        }
    }

    result = AIOverviewUnpacker().unpack(payload)

    assert result["text"] is None
    assert result["sources"] == []
    assert result["citation_pills"] == []
    assert result["entities"]["aioverview_present"] is False
    assert result["entities"]["organic_results"] == [{"title": "Organic"}]


def test_unpacker_factory_resolves_new_platform_aliases():
    assert isinstance(UnpackerFactory.get_unpacker("perplexity"), PerplexityUnpacker)
    assert isinstance(UnpackerFactory.get_unpacker("aioverview"), AIOverviewUnpacker)
    assert isinstance(UnpackerFactory.get_unpacker("ai-overview"), AIOverviewUnpacker)
    assert isinstance(UnpackerFactory.get_unpacker("ai_overview"), AIOverviewUnpacker)
    assert isinstance(UnpackerFactory.get_unpacker("google_ai_overview"), AIOverviewUnpacker)
