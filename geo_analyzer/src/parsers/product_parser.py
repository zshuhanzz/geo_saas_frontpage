"""
Product Mention Parser (v1.2 dual-mode tracking — new in v1.2)

Extracts product-level mentions from AI response text. Products come from
``geo_client_topic_products`` (joined with ``geo_client_brands`` and
``geo_client_peers`` for denormalized owner names).

Matching rules (Spec §5.2):

1. For each product, scan all ``match_variants``. If ``match_variants``
   is empty, fall back to ``product_name``.
2. Matching is case-insensitive and uses punctuation-safe word-character
   lookarounds for every workspace. This supports configured names such as
   ``... (2018-2026)`` without matching inside larger alphanumeric tokens.
3. Variants of length <= 3 chars are **rejected** and warned (avoid
   false positives on noisy short strings like "X1").
4. Within a single response, each product appears **at most once**
   (the first-occurrence variant wins for position ordering).

Output schema (per mention dict):
    product_id         — UUID of the matched geo_client_topic_products row
    product_name       — the configured product_name
    product_role       — 'own' / 'shadow_brand_product' / 'peer'
    shadow_sub_role    — NULL / 'native' / 'resale' (Spec §2.4)
    owner_brand_id     — UUID or None
    owner_brand_name   — denormalized brand name (or None)
    owner_peer_id      — UUID or None
    owner_peer_name    — denormalized peer name (or None)
    mention_position   — 1-indexed ordinal in this response
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_MATCH_LEN = 4  # rejects "<=3" per brand parser alignment


def _collect_variants(
    product_name: str,
    match_variants: Optional[List[str]],
) -> List[str]:
    """Return the cleaned variants list. Falls back to ``product_name``
    if variants is empty/missing. Variants <= 3 chars are logged and
    dropped."""
    candidates: List[str] = []
    raw = list(match_variants) if match_variants else []
    if not raw and product_name:
        raw = [product_name]

    for v in raw:
        if not v:
            continue
        s = v.strip()
        if not s:
            continue
        if len(s) < MIN_MATCH_LEN:
            logger.warning(
                "[PRODUCT] dropping too-short variant %r for product %r",
                s,
                product_name,
            )
            continue
        candidates.append(s)
    return candidates


def _first_match_pos(
    text: str,
    term: str,
) -> Optional[int]:
    """Case-insensitive token-boundary first match position, else None.

    ``\b`` cannot close a term whose final character is punctuation (for
    example a configured product name ending in ``)``). Negative word-char
    lookarounds preserve protection against matching inside a larger token
    while supporting punctuation-rich configured names.
    """
    if not term:
        return None
    try:
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.start() if m else None
    except re.error as exc:
        logger.warning("[PRODUCT] regex compile failed for %r: %s", term, exc)
        return None


def parse_product_mentions(
    text: str,
    tracked_products: Optional[List[Dict]],
) -> List[Dict]:
    """Extract product mentions from ``text``.

    Args:
        text: AI response text.
        tracked_products: List of dicts. Each must include:
            id, product_name, match_variants, product_role, shadow_sub_role,
            owner_brand_id, owner_brand_name, owner_peer_id, owner_peer_name
            (the last four are passed through to the output, denormalized).
    Returns:
        List of mention dicts (see module docstring) ordered by
        mention_position. Each product appears at most once.
    """
    if not text or not tracked_products:
        return []

    per_product: List[Dict] = []
    for p in tracked_products:
        product_id = p.get("id")
        product_name = (p.get("product_name") or "").strip()
        if not product_name:
            continue

        variants = _collect_variants(product_name, p.get("match_variants"))
        if not variants:
            continue

        best_pos: Optional[int] = None
        for v in variants:
            pos = _first_match_pos(text, v)
            if pos is not None and (best_pos is None or pos < best_pos):
                best_pos = pos

        if best_pos is None:
            continue

        per_product.append({
            "product_id": product_id,
            "product_name": product_name,
            "product_role": p.get("product_role"),
            "shadow_sub_role": p.get("shadow_sub_role"),
            "owner_brand_id": p.get("owner_brand_id"),
            "owner_brand_name": p.get("owner_brand_name"),
            "owner_peer_id": p.get("owner_peer_id"),
            "owner_peer_name": p.get("owner_peer_name"),
            "_pos": best_pos,
        })

    # Dedup by product_id (if present) else by lower(product_name).
    seen: set = set()
    unique: List[Dict] = []
    for m in per_product:
        key = m["product_id"] if m["product_id"] is not None else m["product_name"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)

    unique.sort(key=lambda x: x["_pos"])
    out: List[Dict] = []
    for i, m in enumerate(unique, start=1):
        out.append({
            "product_id": m["product_id"],
            "product_name": m["product_name"],
            "product_role": m["product_role"],
            "shadow_sub_role": m["shadow_sub_role"],
            "owner_brand_id": m["owner_brand_id"],
            "owner_brand_name": m["owner_brand_name"],
            "owner_peer_id": m["owner_peer_id"],
            "owner_peer_name": m["owner_peer_name"],
            "mention_position": i,
        })
    return out
