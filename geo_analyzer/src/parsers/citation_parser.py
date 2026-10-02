"""
Citation Parser (v1.2 dual-mode tracking — scheme B)

Extracts per-citation attribution for each source URL using a
**two-stage in-memory match** (Spec §6):

    Stage 1 — Product-level match against ``geo_product_tracked_urls``.
              Both ``exact`` and ``path-prefix`` url_scope are checked,
              longest matching url wins.
    Stage 2 — Domain-level match against ``geo_client_domains``.
              Both ``whole`` and ``path-prefix`` domain_scope are checked,
              longest matching domain wins.
    Stage 3 — No hit. ``citation_role = None`` and the Analyzer main
              pipeline falls back to ``domain_classifier`` to populate
              ``'earned' | 'social' | 'agency' | 'other'``.

``citation_role`` derivation (Spec §6.2):

    Stage 1 hit:
        product_role = 'own'                                    → own_product
        product_role = 'shadow_brand_product', sub='native'     → shadow_product_native
        product_role = 'shadow_brand_product', sub='resale'     → shadow_product_resale
        product_role = 'shadow_brand_product', sub=NULL         → shadow_product
        product_role = 'peer'                                   → peer_product

    Stage 2 hit:
        brand_id set, is_shadow=false                           → own_domain
        brand_id set, is_shadow=true                            → shadow_other
        peer_id  set                                            → peer_channel

Output per citation dict:
    source_url / source_domain / source_position / source_label
    citation_role        — string enum OR None (None → fallback downstream)
    matched_brand_id     — UUID or None
    matched_product_id   — UUID or None
    matched_peer_id      — UUID or None
    is_citation_pill     — bool (URL also appeared in citationPills)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def extract_domain(url: str) -> str:
    """Return the host portion of a URL, lower-cased, www-stripped."""
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _normalize_for_match(url: str) -> Tuple[str, str]:
    """Return (host, full_normalized) where full_normalized is
    ``host + path`` with ``www.`` stripped, scheme removed, and
    **lowercased** — suitable for ``startswith`` path-prefix compares
    against lowercased rule strings."""
    if not url:
        return "", ""
    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
    except Exception:
        return "", ""
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").lower()
    full = host + path
    return host, full


def normalize_owned_entry(raw: str) -> Tuple[str, Optional[str]]:
    """Legacy helper (kept for ``domain_classifier`` compatibility).

    Parse an owned-domain list entry into a ``(host, path_prefix)`` pair.
    ``path_prefix is None`` means "whole domain", otherwise only URLs on
    ``host`` whose path starts with the prefix are considered owned.

    Raises ``ValueError`` if the host cannot be extracted (empty / malformed).
    """
    s = (raw or "").strip().lower()
    if not s:
        raise ValueError("Empty owned-domain entry")
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    parsed = urlparse(s)
    host = (parsed.netloc or "").strip()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        raise ValueError(f"Cannot extract host from {raw!r}")
    path = (parsed.path or "").rstrip("/")
    if not path:
        return (host, None)
    return (host, path)


def _normalize_rule_url(raw: str) -> Tuple[str, str]:
    """Normalize a rule-side url string (tracked URL or domain entry)
    into (host, full). Strips scheme/www, keeps path as-is.

    Handles common sloppy inputs:
        'brand.com'                   -> ('brand.com', 'brand.com')
        'https://www.brand.com'       -> ('brand.com', 'brand.com')
        'brand.com/'                  -> ('brand.com', 'brand.com')
        'amazon.com/stores/mybrand'   -> ('amazon.com', 'amazon.com/stores/mybrand')
    """
    s = (raw or "").strip().lower()
    if not s:
        return "", ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    try:
        parsed = urlparse(s)
    except Exception:
        return "", ""
    host = (parsed.netloc or "").strip()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/")
    full = host + path if path else host
    return host, full


# ---------------------------------------------------------------------------
# Role derivation (Spec §6.2)
# ---------------------------------------------------------------------------


def _derive_product_role(
    product_role: Optional[str],
    shadow_sub_role: Optional[str],
) -> Optional[str]:
    """Map a Stage-1 product hit to a citation_role."""
    if product_role == "own":
        return "own_product"
    if product_role == "peer":
        return "peer_product"
    if product_role == "shadow_brand_product":
        if shadow_sub_role == "native":
            return "shadow_product_native"
        if shadow_sub_role == "resale":
            return "shadow_product_resale"
        return "shadow_product"
    return None


def _derive_domain_role(
    brand_id: Any,
    peer_id: Any,
    is_shadow: bool,
) -> Optional[str]:
    """Map a Stage-2 domain hit to a citation_role."""
    if brand_id is not None:
        return "shadow_other" if is_shadow else "own_domain"
    if peer_id is not None:
        return "peer_channel"
    return None


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def parse_citations(
    sources: Optional[List[Dict]],
    citation_pills: Optional[List[Dict]],
    tracked_urls: Optional[List[Dict]] = None,
    domains: Optional[List[Dict]] = None,
    include_pill_only: bool = False,
) -> List[Dict]:
    """Classify each Cloro ``source`` against the client's tracked URLs
    and domains.

    Args:
        sources: Cloro ``sources`` list of ``{url, position, label, ...}``.
        citation_pills: Cloro ``citationPills`` list. URLs already present in
            ``sources`` mark the matching rows as citation pills.
        include_pill_only: When true, append unique pill URLs that are absent
            from ``sources`` after the original rows. Appended rows receive
            synthetic positions after the largest upstream source position.
        tracked_urls: List of dicts from ``geo_product_tracked_urls``
            joined with ``geo_client_topic_products``. Each must contain:
                url, url_scope ('exact'|'path-prefix'),
                brand_id, peer_id,
                product_id, product_role, shadow_sub_role.
        domains: List of dicts from ``geo_client_domains`` joined with
            ``geo_client_brands``. Each must contain:
                domain, domain_scope ('whole'|'path-prefix'),
                brand_id, peer_id, is_shadow (bool; None → treated as False).

    Returns:
        List of per-citation dicts (see module docstring).
    """
    pills_urls: set = set()
    normalized_pills: List[Dict] = []
    for pill in citation_pills or []:
        if not isinstance(pill, dict):
            continue
        url = pill.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        normalized = {**pill, "url": url.strip()}
        normalized_pills.append(normalized)
        pills_urls.add(normalized["url"])

    effective_sources: List[Dict] = [
        source
        for source in (sources if isinstance(sources, list) else [])
        if isinstance(source, dict)
    ]
    if include_pill_only and normalized_pills:
        source_urls = {
            source.get("url").strip()
            for source in effective_sources
            if isinstance(source, dict)
            and isinstance(source.get("url"), str)
            and source.get("url").strip()
        }
        positions = [
            source.get("position")
            for source in effective_sources
            if isinstance(source, dict)
            and isinstance(source.get("position"), int)
            and not isinstance(source.get("position"), bool)
        ]
        next_position = max(positions, default=0) + 1
        appended_urls: set[str] = set()
        for pill in normalized_pills:
            url = pill["url"]
            if url in source_urls or url in appended_urls:
                continue
            effective_sources.append({
                **pill,
                "position": next_position,
                "label": pill.get("label") or pill.get("title") or pill.get("domain"),
            })
            appended_urls.add(url)
            next_position += 1

    if not effective_sources:
        return []

    # ------- Pre-normalize rule tables once per batch -------
    # tracked_urls entries: (full_rule, url_scope, brand_id, peer_id,
    #                        product_id, product_role, shadow_sub_role)
    normalized_tracked: List[Tuple[str, str, Any, Any, Any, Optional[str], Optional[str]]] = []
    for t in tracked_urls or []:
        if not isinstance(t, dict):
            continue
        raw = t.get("url")
        if not raw:
            continue
        _, full = _normalize_rule_url(raw)
        if not full:
            continue
        normalized_tracked.append((
            full,
            (t.get("url_scope") or "exact"),
            t.get("brand_id"),
            t.get("peer_id"),
            t.get("product_id") or t.get("id"),  # JOIN shape may use either
            t.get("product_role"),
            t.get("shadow_sub_role"),
        ))

    # domains entries: (host_or_full, domain_scope, brand_id, peer_id, is_shadow)
    normalized_domains: List[Tuple[str, str, Any, Any, bool]] = []
    for d in domains or []:
        if not isinstance(d, dict):
            continue
        raw = d.get("domain")
        if not raw:
            continue
        host, full = _normalize_rule_url(raw)
        if not host:
            continue
        scope = (d.get("domain_scope") or "whole")
        # For 'whole' scope we match host equality; keep host only.
        # For 'path-prefix' scope we match host+path prefix.
        key = host if scope == "whole" else full
        normalized_domains.append((
            key,
            scope,
            d.get("brand_id"),
            d.get("peer_id"),
            bool(d.get("is_shadow")),
        ))

    out: List[Dict] = []
    for source in effective_sources:
        url = source.get("url", "")
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()

        host, full = _normalize_for_match(url)
        domain_out = extract_domain(url)

        citation_role: Optional[str] = None
        matched_brand_id: Any = None
        matched_product_id: Any = None
        matched_peer_id: Any = None

        # ----------- Stage 1: product tracked URL match -----------
        best_len = -1
        best_hit: Optional[Tuple] = None
        for (rule_full, scope, b_id, p_id, prod_id, p_role, sub_role) in normalized_tracked:
            hit = False
            if scope == "exact":
                if full == rule_full:
                    hit = True
            else:  # path-prefix
                if full.startswith(rule_full):
                    hit = True
            if hit and len(rule_full) > best_len:
                best_len = len(rule_full)
                best_hit = (rule_full, scope, b_id, p_id, prod_id, p_role, sub_role)

        if best_hit is not None:
            _, _, b_id, p_id, prod_id, p_role, sub_role = best_hit
            citation_role = _derive_product_role(p_role, sub_role)
            matched_brand_id = b_id
            matched_peer_id = p_id
            matched_product_id = prod_id

        # ----------- Stage 2: domain-level match (only if Stage 1 miss) -----
        if citation_role is None and normalized_domains:
            best_len = -1
            best_dhit: Optional[Tuple[str, str, Any, Any, bool]] = None
            for (key, scope, b_id, p_id, is_shadow) in normalized_domains:
                hit = False
                if scope == "whole":
                    if host == key:
                        hit = True
                else:  # path-prefix
                    if full.startswith(key):
                        hit = True
                if hit and len(key) > best_len:
                    best_len = len(key)
                    best_dhit = (key, scope, b_id, p_id, is_shadow)

            if best_dhit is not None:
                _, _, b_id, p_id, is_shadow = best_dhit
                citation_role = _derive_domain_role(b_id, p_id, is_shadow)
                # Only populate matched_* when we actually got a role.
                if citation_role is not None:
                    matched_brand_id = b_id
                    matched_peer_id = p_id

        out.append({
            "source_url": url,
            "source_domain": domain_out,
            "source_position": source.get("position"),
            "source_label": source.get("label"),
            "citation_role": citation_role,
            "matched_brand_id": matched_brand_id,
            "matched_product_id": matched_product_id,
            "matched_peer_id": matched_peer_id,
            "is_citation_pill": url in pills_urls,
        })

    return out
