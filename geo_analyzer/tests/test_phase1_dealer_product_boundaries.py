from src.pipeline.phase0_load_config import ClientConfig
from src.pipeline.phase1_per_result_parse import parse_batch


PRODUCT_NAME = "Power Running Boards | 4 Door | Jeep Wrangler JL (2018-2026)"


def _config(*, dealer_mode: bool) -> ClientConfig:
    return ClientConfig(
        brands=[{
            "id": "brand-id",
            "brand_name": "Rough Country" if dealer_mode else "Standard Brand",
            "aliases": [],
            "is_shadow": dealer_mode,
        }],
        peers=[],
        tracked_products=[{
            "id": "product-id",
            "product_name": PRODUCT_NAME,
            "match_variants": [],
            "product_role": "own",
            "shadow_sub_role": None,
            "owner_brand_id": None,
            "owner_brand_name": None,
            "owner_peer_id": None,
            "owner_peer_name": None,
        }],
        domains=[],
        tracked_urls=[],
        owned_domain_strs=[],
    )


def _result():
    return {
        "result_id": 1,
        "text": f"The {PRODUCT_NAME} is a strong option.",
        "client_id": "client-id",
        "client_prompt_id": "prompt-id",
        "task_id": "task-id",
        "ingested_at": None,
        "platform": "gemini",
        "sources": [],
        "citation_pills": [],
    }


def test_phase1_enables_punctuation_safe_product_matching_for_dealer_clients():
    parsed = parse_batch([_result()], _config(dealer_mode=True))

    assert [m["product_name"] for m in parsed.per_result[0][2]] == [PRODUCT_NAME]


def test_phase1_uses_punctuation_safe_product_matching_for_standard_clients():
    parsed = parse_batch([_result()], _config(dealer_mode=False))

    assert [m["product_name"] for m in parsed.per_result[0][2]] == [PRODUCT_NAME]
