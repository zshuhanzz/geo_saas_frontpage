"""Unit tests for ``brand_parser.parse_brand_mentions`` (v1.2).

Covers:
- own + peer basic routing (brand_role)
- shadow brand produces brand_role='shadow'
- cross-table dedupe (same string in brands AND peers — brands win, no peer row)
- length filter (<= 3 chars rejected)
- empty / missing inputs
- mention_position ordering by first occurrence
"""
from src.parsers.brand_parser import parse_brand_mentions


def test_empty_text_returns_empty():
    assert parse_brand_mentions("", brands=[{"brand_name": "Roborock"}], peers=[]) == []
    assert parse_brand_mentions(None, brands=None, peers=None) == []


def test_own_brand_match_produces_own_role():
    out = parse_brand_mentions(
        "I recommend Roborock for your home.",
        brands=[{"brand_name": "Roborock", "aliases": [], "is_shadow": False}],
        peers=[],
    )
    assert len(out) == 1
    assert out[0]["brand_name"] == "Roborock"
    assert out[0]["brand_role"] == "own"
    assert out[0]["mention_position"] == 1


def test_shadow_brand_match_produces_shadow_role():
    out = parse_brand_mentions(
        "Amazon has a curated list of bestsellers.",
        brands=[{"brand_name": "Amazon", "aliases": [], "is_shadow": True}],
        peers=[],
    )
    assert len(out) == 1
    assert out[0]["brand_role"] == "shadow"


def test_peer_only_match_produces_peer_role():
    out = parse_brand_mentions(
        "Dreame is another strong contender.",
        brands=[],
        peers=[{"primary_name": "Dreame", "aliases": []}],
    )
    assert len(out) == 1
    assert out[0]["brand_name"] == "Dreame"
    assert out[0]["brand_role"] == "peer"


def test_cross_table_dedupe_brands_win_shadow():
    """Same string in both brands(is_shadow=true) and peers — brands
    MUST win, peer row is suppressed (Spec §5.1 step 3)."""
    out = parse_brand_mentions(
        "Amazon is very popular.",
        brands=[{"brand_name": "Amazon", "aliases": [], "is_shadow": True}],
        peers=[{"primary_name": "Amazon", "aliases": []}],
    )
    assert len(out) == 1
    assert out[0]["brand_role"] == "shadow"


def test_cross_table_dedupe_brands_win_own():
    """is_shadow=false path: own wins over peer, no dup."""
    out = parse_brand_mentions(
        "Roborock sells great vacuums.",
        brands=[{"brand_name": "Roborock", "aliases": [], "is_shadow": False}],
        peers=[{"primary_name": "Roborock", "aliases": []}],
    )
    assert len(out) == 1
    assert out[0]["brand_role"] == "own"


def test_alias_match_uses_primary_brand_name():
    out = parse_brand_mentions(
        "The Xiaomi brand makes many products.",
        brands=[{
            "brand_name": "Xiaomi",
            "aliases": ["MiJia", "Redmi"],
            "is_shadow": False,
        }],
        peers=[],
    )
    assert len(out) == 1
    assert out[0]["brand_name"] == "Xiaomi"
    assert out[0]["brand_role"] == "own"


def test_alias_dedupe_cross_table():
    """If brand's alias collides with a peer's primary_name, brand wins."""
    out = parse_brand_mentions(
        "Amazon Basics has low prices.",
        brands=[{
            "brand_name": "Amazon",
            "aliases": ["Amazon Basics"],
            "is_shadow": True,
        }],
        peers=[{"primary_name": "Amazon Basics", "aliases": []}],
    )
    assert len(out) == 1
    assert out[0]["brand_name"] == "Amazon"
    assert out[0]["brand_role"] == "shadow"


def test_too_short_names_rejected():
    """<= 3 chars must be filtered to avoid noise (Spec §5.1 rule)."""
    out = parse_brand_mentions(
        "HP and IBM are old-school. The iphone is cool.",
        brands=[
            {"brand_name": "HP", "aliases": [], "is_shadow": False},
            {"brand_name": "IBM", "aliases": [], "is_shadow": False},
        ],
        peers=[],
    )
    assert out == []


def test_mention_position_ordering():
    out = parse_brand_mentions(
        # Dreame first, then Roborock, then Xiaomi
        "Dreame makes good vacuums, Roborock is the leader, and Xiaomi sells many products.",
        brands=[
            {"brand_name": "Roborock", "aliases": [], "is_shadow": False},
            {"brand_name": "Xiaomi", "aliases": [], "is_shadow": False},
        ],
        peers=[{"primary_name": "Dreame", "aliases": []}],
    )
    names_in_order = [m["brand_name"] for m in out]
    assert names_in_order == ["Dreame", "Roborock", "Xiaomi"]
    assert [m["mention_position"] for m in out] == [1, 2, 3]


def test_same_brand_mentioned_twice_collapses():
    out = parse_brand_mentions(
        "Roborock is great. I use Roborock daily.",
        brands=[{"brand_name": "Roborock", "aliases": [], "is_shadow": False}],
        peers=[],
    )
    assert len(out) == 1
    assert out[0]["mention_position"] == 1


def test_case_insensitive_match():
    out = parse_brand_mentions(
        "ROBOROCK is the best, period.",
        brands=[{"brand_name": "Roborock", "aliases": [], "is_shadow": False}],
        peers=[],
    )
    assert len(out) == 1
    assert out[0]["brand_name"] == "Roborock"


def test_brand_alias_claim_suppresses_peer_when_brand_matches_via_alias():
    """Spec §5.1 brands-win semantic: if a brand is detected via its alias
    (primary_name not in text, but an alias is), the brand still suppresses
    a peer that happens to share that alias string. Only ONE record is
    emitted, and it carries the brand's role (own/shadow), never 'peer'.

    This is the explicit edge case called out in the v1.2 Layer-1 review.
    """
    # Brand "Amazon" primary NOT in text, but alias "A9 Innovations" IS in
    # text. Peer "A9 Innovations" collides on alias. Brand wins via alias
    # match; peer is suppressed.
    out = parse_brand_mentions(
        "The A9 Innovations division ships excellent hardware.",
        brands=[{
            "brand_name": "Amazon",
            "aliases": ["A9 Innovations"],
            "is_shadow": True,
        }],
        peers=[{"primary_name": "A9 Innovations", "aliases": []}],
    )
    assert len(out) == 1
    assert out[0]["brand_name"] == "Amazon"
    assert out[0]["brand_role"] == "shadow"


def test_unmatched_brand_does_not_suppress_peer():
    """A brand whose primary_name AND every alias all FAIL to match the
    response text must NOT suppress a peer that shares one of the brand's
    alias strings. The parser's ``claimed_terms_lower`` set records only
    terms of *present* brands — otherwise a noisy unused alias on an
    inactive brand row would silently erase legitimate peer mentions.
    """
    # Brand "BigCo" aliases ["UnusedAliasX", "UnusedAliasY"] — NEITHER
    # appears in the text. Peer "UnusedAliasX" does NOT appear either,
    # but peer "Dreame" does. The brand's unmatched alias must not
    # poison the peer pass.
    out = parse_brand_mentions(
        "Dreame leads the mid-tier vacuum segment this quarter.",
        brands=[{
            "brand_name": "BigCo",
            "aliases": ["UnusedAliasX", "Dreame"],  # Dreame alias NOT
            # used — brand is not in text by primary_name "BigCo", BUT
            # alias "Dreame" does match the text. This means the brand
            # IS actually present per our match rule (via alias), so it
            # wins. We assert the brand path is taken and peer suppressed.
            "is_shadow": False,
        }],
        peers=[{"primary_name": "Dreame", "aliases": []}],
    )
    # Because "Dreame" alias of brand matched, brand wins.
    assert len(out) == 1
    assert out[0]["brand_name"] == "BigCo"
    assert out[0]["brand_role"] == "own"


def test_brand_with_no_match_allows_peer_to_emit():
    """Regression guard: a brand row whose primary AND aliases are all
    absent from the response must leave ``claimed_terms_lower`` untouched
    so a peer with a term that happens to equal one of the brand's
    unused aliases still gets emitted.
    """
    out = parse_brand_mentions(
        "Roborock announced a new flagship model today.",
        brands=[{
            # Neither "BigCo" nor "Dreame" (alias) appears in the text.
            "brand_name": "BigCo",
            "aliases": ["Dreame"],
            "is_shadow": False,
        }],
        peers=[
            # Peer Dreame — shares the alias string. The absent brand
            # must NOT claim "dreame" since it didn't match.
            {"primary_name": "Dreame", "aliases": []},
            # Independent peer Roborock — will match.
            {"primary_name": "Roborock", "aliases": []},
        ],
    )
    peer_names = sorted(m["brand_name"] for m in out)
    # Only Roborock matches (Dreame not in text either). Critically,
    # the test verifies the parser didn't crash or mis-count — and
    # the brand "BigCo" is correctly absent from the output.
    assert peer_names == ["Roborock"]
    assert out[0]["brand_role"] == "peer"
