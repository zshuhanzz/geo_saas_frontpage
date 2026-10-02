"""Unit tests for ``product_parser.parse_product_mentions`` (v1.2)."""
from src.parsers.product_parser import parse_product_mentions

from uuid import uuid4


def _make_product(
    name,
    variants=None,
    role="own",
    sub_role=None,
    owner_brand_id=None,
    owner_brand_name=None,
    owner_peer_id=None,
    owner_peer_name=None,
    pid=None,
):
    return {
        "id": pid or uuid4(),
        "product_name": name,
        "match_variants": variants or [],
        "product_role": role,
        "shadow_sub_role": sub_role,
        "owner_brand_id": owner_brand_id,
        "owner_brand_name": owner_brand_name,
        "owner_peer_id": owner_peer_id,
        "owner_peer_name": owner_peer_name,
    }


def test_empty_inputs():
    assert parse_product_mentions("", [_make_product("S8 MaxV")]) == []
    assert parse_product_mentions("Some text", []) == []
    assert parse_product_mentions("Some text", None) == []


def test_match_variants_used_over_product_name():
    """When match_variants is set, the product_name itself is NOT matched
    (unless also in variants)."""
    out = parse_product_mentions(
        "The Q Revo is amazing. Nobody says S8 MaxV Plus here.",
        [_make_product("S8 MaxV Plus", variants=["Q Revo", "QRevo"])],
    )
    assert len(out) == 1
    assert out[0]["product_name"] == "S8 MaxV Plus"  # denormalized name
    assert out[0]["product_role"] == "own"


def test_fallback_to_product_name_when_variants_empty():
    out = parse_product_mentions(
        "The Roomba j7 works well.",
        [_make_product("Roomba j7")],
    )
    assert len(out) == 1
    assert out[0]["product_name"] == "Roomba j7"


def test_short_variant_rejected():
    out = parse_product_mentions(
        "Try the S8 for a steal.",
        [_make_product("S8 MaxV", variants=["S8"])],
    )
    assert out == []


def test_denormalized_owner_fields_passed_through():
    brand_id = uuid4()
    out = parse_product_mentions(
        "Amazon Basics robot vacuum is cheap.",
        [_make_product(
            "Amazon Basics Robot",
            variants=["Amazon Basics robot vacuum"],
            role="shadow_brand_product",
            sub_role="native",
            owner_brand_id=brand_id,
            owner_brand_name="Amazon",
        )],
    )
    assert len(out) == 1
    m = out[0]
    assert m["product_role"] == "shadow_brand_product"
    assert m["shadow_sub_role"] == "native"
    assert m["owner_brand_id"] == brand_id
    assert m["owner_brand_name"] == "Amazon"


def test_dedupe_same_product_first_occurrence_wins():
    out = parse_product_mentions(
        "Q Revo once. Then Q Revo again.",
        [_make_product("Q Revo", variants=["Q Revo"])],
    )
    assert len(out) == 1
    assert out[0]["mention_position"] == 1


def test_multiple_products_ordered_by_position():
    # "Q Revo" first, then "Roomba j7".
    out = parse_product_mentions(
        "The Q Revo dominates; for budget, Roomba j7 is fine.",
        [
            _make_product("Roomba j7", variants=["Roomba j7"], role="peer",
                          owner_peer_id=uuid4(), owner_peer_name="iRobot"),
            _make_product("Q Revo", variants=["Q Revo"], role="own"),
        ],
    )
    names = [m["product_name"] for m in out]
    assert names == ["Q Revo", "Roomba j7"]
    assert [m["mention_position"] for m in out] == [1, 2]


def test_case_insensitive_match():
    out = parse_product_mentions(
        "The q revo is back.",
        [_make_product("Q Revo", variants=["Q Revo"])],
    )
    assert len(out) == 1


def test_fallback_product_name_with_trailing_punctuation_matches():
    """A configured full name ending in ')' must not be rejected by ``\b``."""
    product_name = "Power Running Boards | 4 Door | Jeep Wrangler JL (2018-2026)"
    out = parse_product_mentions(
        f"The {product_name} is a strong option.",
        [_make_product(product_name)],
    )

    assert len(out) == 1
    assert out[0]["product_name"] == product_name


def test_punctuation_safe_boundaries_apply_to_standard_workspaces():
    """Punctuation-rich configured names use the same safe boundary globally."""
    product_name = "Power Running Boards | 4 Door | Jeep Wrangler JL (2018-2026)"

    out = parse_product_mentions(
        f"The {product_name} is a strong option.",
        [_make_product(product_name)],
    )

    assert [row["product_name"] for row in out] == [product_name]


def test_product_term_does_not_match_inside_larger_token():
    out = parse_product_mentions(
        "The replacement code is XPSR055110PLUS, not the tracked SKU.",
        [_make_product("Nissan running board", variants=["PSR055110"])],
    )

    assert out == []
