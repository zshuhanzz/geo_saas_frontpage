"""
Brand Mention Parser (v1.2 dual-mode tracking)

Extracts brand mentions from AI response text. Brands are loaded from
``geo_client_brands`` (Own + Shadow) and Peers from ``geo_client_peers``
(independent competitors).

Key rules (Spec §5.1):

1. Each brand / peer name (primary + aliases) is word-boundary matched
   case-insensitively against the response text.
2. Cross-table dedupe: if the same matched string is present in **both**
   ``brands`` (via name/alias) and ``peers`` (via primary_name/alias),
   **brands win**. The output gets ``brand_role`` derived from
   ``is_shadow`` (``'shadow'`` or ``'own'``); **no duplicate peer record
   is emitted**. This avoids Shadow brands being double-counted as Peers.
3. Within a single response, the same brand is only emitted once — at
   the position of its first occurrence.
4. Names/aliases with length <= 3 characters are rejected (too noisy).

Output schema (per mention dict):
    brand_name        — the configured primary name that matched
    brand_role        — 'own' / 'shadow' / 'peer'
    mention_position  — 1-indexed ordinal of first occurrence in the text
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_MATCH_LEN = 4  # rejects "<=3"


def _expand_terms(
    primary: str,
    aliases: Optional[List[str]],
) -> List[str]:
    """Return the cleaned primary + aliases list (length-filtered)."""
    terms: List[str] = []
    if primary and len(primary) >= MIN_MATCH_LEN:
        terms.append(primary)
    for a in aliases or []:
        if a and len(a) >= MIN_MATCH_LEN:
            terms.append(a)
    return terms


def _first_match_pos(text: str, term: str) -> Optional[int]:
    """Return the 0-based char index of the first case-insensitive,
    word-boundary match for ``term`` in ``text``, or None."""
    if not term:
        return None
    try:
        pattern = rf"\b{re.escape(term)}\b"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.start() if m else None
    except re.error as exc:
        logger.warning("[BRAND] regex compile failed for %r: %s", term, exc)
        return None


def parse_brand_mentions(
    text: str,
    brands: Optional[List[Dict]],
    peers: Optional[List[Dict]],
) -> List[Dict]:
    """Extract brand mentions from ``text``.

    Args:
        text: AI response text.
        brands: list of dicts ``{brand_name, aliases, is_shadow}`` — rows
            from ``geo_client_brands`` where ``is_active = true``.
        peers: list of dicts ``{primary_name, aliases}`` — rows from
            ``geo_client_peers``.

    Returns:
        List of mention dicts ``{brand_name, brand_role, mention_position}``,
        ordered by mention_position, each brand appearing at most once.
    """
    if not text:
        return []

    # -----------------------------------------------------------------
    # Step 1: scan all brand entries first — brands win dedupe ties.
    # A brand "claims" its term strings ONLY when that term actually
    # matched in the response text. A brand with zero matches does not
    # suppress a peer that happens to share the same alias string
    # (see ``test_unmatched_brand_does_not_suppress_peer``).
    # -----------------------------------------------------------------
    per_entity: List[Dict] = []  # each: {brand_name, brand_role, _pos}
    claimed_terms_lower: set = set()

    for b in brands or []:
        primary = (b.get("brand_name") or "").strip()
        if not primary:
            continue
        is_shadow = bool(b.get("is_shadow"))
        role = "shadow" if is_shadow else "own"
        terms = _expand_terms(primary, b.get("aliases"))
        if not terms:
            continue

        best_pos: Optional[int] = None
        matched_terms_lower: List[str] = []
        for t in terms:
            pos = _first_match_pos(text, t)
            if pos is not None:
                matched_terms_lower.append(t.lower())
                if best_pos is None or pos < best_pos:
                    best_pos = pos

        if best_pos is not None:
            # Claim only the terms that actually matched — an unmatched
            # brand must not suppress a peer with a colliding alias.
            for term_lower in matched_terms_lower:
                claimed_terms_lower.add(term_lower)
            # Also claim the full terms list so that a *later* occurrence
            # of a non-matching alias on a collision-sibling doesn't
            # accidentally leak through — the brand IS present, so its
            # entire identity wins future ties.
            for t in terms:
                claimed_terms_lower.add(t.lower())
            per_entity.append({
                "brand_name": primary,
                "brand_role": role,
                "_pos": best_pos,
            })

    # -----------------------------------------------------------------
    # Step 2: scan peers — skip any term that brands already claimed.
    # -----------------------------------------------------------------
    for p in peers or []:
        primary = (p.get("primary_name") or "").strip()
        if not primary:
            continue
        terms_raw = _expand_terms(primary, p.get("aliases"))
        # drop terms that brands have already claimed (case-insensitive)
        terms = [t for t in terms_raw if t.lower() not in claimed_terms_lower]
        if not terms:
            # Every term of this peer collides with a brand — the brand
            # pass already produced the (higher-priority) record.
            continue

        best_pos: Optional[int] = None
        for t in terms:
            pos = _first_match_pos(text, t)
            if pos is not None and (best_pos is None or pos < best_pos):
                best_pos = pos

        if best_pos is not None:
            per_entity.append({
                "brand_name": primary,
                "brand_role": "peer",
                "_pos": best_pos,
            })

    # -----------------------------------------------------------------
    # Step 3: dedupe by brand_name (case-insensitive). The brand pass
    # ran first, so on any primary-name collision it wins by appearing
    # earlier in per_entity.
    # -----------------------------------------------------------------
    seen: set = set()
    unique: List[Dict] = []
    for m in per_entity:
        key = m["brand_name"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)

    # Sort by position of first occurrence, then assign 1-indexed ordinal.
    unique.sort(key=lambda x: x["_pos"])
    out: List[Dict] = []
    for i, m in enumerate(unique, start=1):
        out.append({
            "brand_name": m["brand_name"],
            "brand_role": m["brand_role"],
            "mention_position": i,
        })
    return out
