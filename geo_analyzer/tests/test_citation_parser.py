"""Unit tests for ``citation_parser.parse_citations`` (v1.2 scheme B)."""
from uuid import uuid4

from src.parsers.citation_parser import parse_citations


def _source(url, pos=1, label=None):
    return {"url": url, "position": pos, "label": label}


# --------------------------- Stage 3 (no hit) ---------------------------

def test_no_rules_yields_null_role_for_fallback():
    out = parse_citations(
        sources=[_source("https://random.example.com/a")],
        citation_pills=[],
        tracked_urls=[],
        domains=[],
    )
    assert len(out) == 1
    assert out[0]["citation_role"] is None
    assert out[0]["matched_brand_id"] is None
    assert out[0]["matched_product_id"] is None
    assert out[0]["matched_peer_id"] is None
    assert out[0]["source_domain"] == "random.example.com"


# --------------------------- Stage 2 (domain) ---------------------------

def test_own_domain_whole_scope():
    brand_id = uuid4()
    out = parse_citations(
        sources=[_source("https://www.roborock.com/s/some-page")],
        citation_pills=[],
        tracked_urls=[],
        domains=[{
            "domain": "roborock.com",
            "domain_scope": "whole",
            "brand_id": brand_id,
            "peer_id": None,
            "is_shadow": False,
        }],
    )
    assert out[0]["citation_role"] == "own_domain"
    assert out[0]["matched_brand_id"] == brand_id


def test_shadow_other_for_shadow_brand_domain_hit_without_product():
    brand_id = uuid4()
    out = parse_citations(
        sources=[_source("https://www.amazon.com/some-random-page")],
        citation_pills=[],
        tracked_urls=[],
        domains=[{
            "domain": "amazon.com",
            "domain_scope": "whole",
            "brand_id": brand_id,
            "peer_id": None,
            "is_shadow": True,
        }],
    )
    assert out[0]["citation_role"] == "shadow_other"
    assert out[0]["matched_brand_id"] == brand_id


def test_peer_channel_domain_hit():
    peer_id = uuid4()
    out = parse_citations(
        sources=[_source("https://dreame.com/support/faq")],
        citation_pills=[],
        tracked_urls=[],
        domains=[{
            "domain": "dreame.com",
            "domain_scope": "whole",
            "brand_id": None,
            "peer_id": peer_id,
            "is_shadow": False,
        }],
    )
    assert out[0]["citation_role"] == "peer_channel"
    assert out[0]["matched_peer_id"] == peer_id


# --------------------------- Stage 1 (product tracked_url) ---------------------------

def test_own_product_tracked_url_exact_hit():
    brand_id = uuid4()
    product_id = uuid4()
    out = parse_citations(
        sources=[_source("https://www.amazon.com/dp/B0CABCDEF")],
        citation_pills=[],
        tracked_urls=[{
            "url": "amazon.com/dp/B0CABCDEF",
            "url_scope": "exact",
            "brand_id": brand_id,
            "peer_id": None,
            "product_id": product_id,
            "product_role": "own",
            "shadow_sub_role": None,
        }],
        domains=[],
    )
    assert out[0]["citation_role"] == "own_product"
    assert out[0]["matched_product_id"] == product_id
    assert out[0]["matched_brand_id"] == brand_id


def test_shadow_product_native_from_product_role():
    brand_id = uuid4()
    product_id = uuid4()
    out = parse_citations(
        sources=[_source("https://amazon.com/stores/amazonbasics/product-1")],
        citation_pills=[],
        tracked_urls=[{
            "url": "amazon.com/stores/amazonbasics/product-1",
            "url_scope": "exact",
            "brand_id": brand_id,
            "peer_id": None,
            "product_id": product_id,
            "product_role": "shadow_brand_product",
            "shadow_sub_role": "native",
        }],
        domains=[],
    )
    assert out[0]["citation_role"] == "shadow_product_native"


def test_shadow_product_resale_from_product_role():
    out = parse_citations(
        sources=[_source("https://roughcountry.com/product/ht-series-X")],
        citation_pills=[],
        tracked_urls=[{
            "url": "roughcountry.com/product/ht-series-X",
            "url_scope": "exact",
            "brand_id": uuid4(),
            "peer_id": None,
            "product_id": uuid4(),
            "product_role": "shadow_brand_product",
            "shadow_sub_role": "resale",
        }],
        domains=[],
    )
    assert out[0]["citation_role"] == "shadow_product_resale"


def test_shadow_product_null_sub_role():
    out = parse_citations(
        sources=[_source("https://channel.com/p/sku123")],
        citation_pills=[],
        tracked_urls=[{
            "url": "channel.com/p/sku123",
            "url_scope": "exact",
            "brand_id": uuid4(),
            "peer_id": None,
            "product_id": uuid4(),
            "product_role": "shadow_brand_product",
            "shadow_sub_role": None,
        }],
        domains=[],
    )
    assert out[0]["citation_role"] == "shadow_product"


def test_peer_product_from_product_role():
    peer_id = uuid4()
    product_id = uuid4()
    out = parse_citations(
        sources=[_source("https://irobot.com/products/roomba-j7")],
        citation_pills=[],
        tracked_urls=[{
            "url": "irobot.com/products/roomba-j7",
            "url_scope": "exact",
            "brand_id": None,
            "peer_id": peer_id,
            "product_id": product_id,
            "product_role": "peer",
            "shadow_sub_role": None,
        }],
        domains=[],
    )
    assert out[0]["citation_role"] == "peer_product"
    assert out[0]["matched_peer_id"] == peer_id
    assert out[0]["matched_product_id"] == product_id


def test_path_prefix_scope_matches_subpath():
    out = parse_citations(
        sources=[_source("https://amazon.com/stores/mybrand/product/123")],
        citation_pills=[],
        tracked_urls=[{
            "url": "amazon.com/stores/mybrand",
            "url_scope": "path-prefix",
            "brand_id": uuid4(),
            "peer_id": None,
            "product_id": uuid4(),
            "product_role": "shadow_brand_product",
            "shadow_sub_role": "native",
        }],
        domains=[],
    )
    assert out[0]["citation_role"] == "shadow_product_native"


def test_stage_1_wins_over_stage_2_when_both_would_match():
    """Stage 1 (product tracked_url) MUST win over Stage 2 (domain)."""
    brand_id = uuid4()
    product_id = uuid4()
    out = parse_citations(
        sources=[_source("https://amazon.com/stores/mybrand")],
        citation_pills=[],
        tracked_urls=[{
            "url": "amazon.com/stores/mybrand",
            "url_scope": "exact",
            "brand_id": brand_id,
            "peer_id": None,
            "product_id": product_id,
            "product_role": "own",
            "shadow_sub_role": None,
        }],
        domains=[{
            "domain": "amazon.com",
            "domain_scope": "whole",
            "brand_id": uuid4(),  # Different brand — Shadow
            "peer_id": None,
            "is_shadow": True,
        }],
    )
    assert out[0]["citation_role"] == "own_product"
    assert out[0]["matched_product_id"] == product_id


def test_longest_match_wins_within_stage1():
    """When two tracked_urls both match, the one with the longer rule string wins."""
    short_pid = uuid4()
    long_pid = uuid4()
    out = parse_citations(
        sources=[_source("https://amazon.com/stores/mybrand/product-x")],
        citation_pills=[],
        tracked_urls=[
            {
                "url": "amazon.com/stores",
                "url_scope": "path-prefix",
                "brand_id": uuid4(),
                "peer_id": None,
                "product_id": short_pid,
                "product_role": "own",
                "shadow_sub_role": None,
            },
            {
                "url": "amazon.com/stores/mybrand",
                "url_scope": "path-prefix",
                "brand_id": uuid4(),
                "peer_id": None,
                "product_id": long_pid,
                "product_role": "peer",
                "shadow_sub_role": None,
            },
        ],
        domains=[],
    )
    assert out[0]["matched_product_id"] == long_pid
    assert out[0]["citation_role"] == "peer_product"


# --------------------------- citation_pills flag ---------------------------

def test_citation_pill_flag_set():
    out = parse_citations(
        sources=[_source("https://foo.example.com/a")],
        citation_pills=[{"url": "https://foo.example.com/a"}],
        tracked_urls=[],
        domains=[],
    )
    assert out[0]["is_citation_pill"] is True


def test_citation_pill_flag_unset_when_missing():
    out = parse_citations(
        sources=[_source("https://foo.example.com/a")],
        citation_pills=[{"url": "https://other.example.com/b"}],
        tracked_urls=[],
        domains=[],
    )
    assert out[0]["is_citation_pill"] is False


def test_chatgpt_pill_only_urls_append_after_sources_in_first_seen_order():
    sources = [
        _source("https://source.example.com/first", pos=2, label="First"),
        _source("https://source.example.com/second", pos=7, label="Second"),
    ]
    citation_pills = [
        {"url": "https://source.example.com/first", "label": "Existing"},
        {"url": "https://pill.example.com/b", "label": "Pill B"},
        {"url": "https://pill.example.com/b", "label": "Duplicate Pill B"},
        {"url": "https://pill.example.com/a", "label": "Pill A"},
    ]

    out = parse_citations(
        sources=sources,
        citation_pills=citation_pills,
        tracked_urls=[],
        domains=[],
        include_pill_only=True,
    )

    assert [row["source_url"] for row in out] == [
        "https://source.example.com/first",
        "https://source.example.com/second",
        "https://pill.example.com/b",
        "https://pill.example.com/a",
    ]
    assert [row["source_position"] for row in out] == [2, 7, 8, 9]
    assert [row["source_label"] for row in out] == ["First", "Second", "Pill B", "Pill A"]
    assert [row["is_citation_pill"] for row in out] == [True, False, True, True]


def test_chatgpt_pill_only_urls_start_at_position_one_without_sources():
    out = parse_citations(
        sources=[],
        citation_pills=[
            {"url": "https://pill.example.com/one", "label": "One"},
            {"url": "https://pill.example.com/two", "label": "Two"},
        ],
        tracked_urls=[],
        domains=[],
        include_pill_only=True,
    )

    assert [row["source_url"] for row in out] == [
        "https://pill.example.com/one",
        "https://pill.example.com/two",
    ]
    assert [row["source_position"] for row in out] == [1, 2]


def test_chatgpt_preserves_duplicate_source_rows_and_marks_each_overlap():
    duplicate_url = "https://source.example.com/duplicate"
    out = parse_citations(
        sources=[
            _source(duplicate_url, pos=1, label="First occurrence"),
            _source(duplicate_url, pos=2, label="Second occurrence"),
        ],
        citation_pills=[{"url": duplicate_url}],
        tracked_urls=[],
        domains=[],
        include_pill_only=True,
    )

    assert [row["source_url"] for row in out] == [duplicate_url, duplicate_url]
    assert [row["source_position"] for row in out] == [1, 2]
    assert [row["source_label"] for row in out] == [
        "First occurrence",
        "Second occurrence",
    ]
    assert [row["is_citation_pill"] for row in out] == [True, True]


def test_pill_only_urls_are_not_appended_by_default_for_other_platforms():
    out = parse_citations(
        sources=[_source("https://source.example.com/one", pos=1)],
        citation_pills=[{"url": "https://pill.example.com/only"}],
        tracked_urls=[],
        domains=[],
    )

    assert [row["source_url"] for row in out] == ["https://source.example.com/one"]


def test_malformed_source_and_rule_entries_are_ignored_safely():
    out = parse_citations(
        sources=[None, "wrong", {"url": 42}, _source("https://valid.example/one")],
        citation_pills={"url": "not-a-list"},
        tracked_urls=[None, "wrong"],
        domains=[None, "wrong"],
        include_pill_only=True,
    )

    assert [row["source_url"] for row in out] == ["https://valid.example/one"]
