"""
Phase 0 — Load all per-client reference data from Postgres.

Returns a single ``ClientConfig`` dataclass holding everything the in-memory
parsers need so we don't pass 5 separate lists down the chain.

Phase 2.5b: every loader is now async and runs against an ``asyncpg.Connection``
acquired from the shared pool. asyncpg returns ``Record`` objects which
support both attribute and dict-style access; the original sync code used
``r.brand_name`` style and we keep that for minimal call-site churn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

logger = logging.getLogger("GeoAnalyzer.phase0")


@dataclass
class ClientConfig:
    brands: List[Dict[str, Any]]
    peers: List[Dict[str, Any]]
    tracked_products: List[Dict[str, Any]]
    domains: List[Dict[str, Any]]
    tracked_urls: List[Dict[str, Any]]
    # Convenience: whole-domain Own Brand hostnames consumed by domain_classifier
    # short-circuit. Path-prefix rows are intentionally excluded — they should
    # still flow through the global classifier and get their proper "Channel"
    # category.
    owned_domain_strs: List[str]


async def _load_brands(conn, client_id: str) -> List[Dict[str, Any]]:
    """Load all active brands (Own + Shadow) for the client."""
    rows = await conn.fetch(
        """
        SELECT id, brand_name, COALESCE(aliases, '{}'::text[]) AS aliases, is_shadow
          FROM geo_client_brands
         WHERE client_id = $1 AND is_active = true
        """,
        client_id,
    )
    return [
        {
            "id": r["id"],
            "brand_name": r["brand_name"],
            "aliases": list(r["aliases"] or []),
            "is_shadow": bool(r["is_shadow"]),
        }
        for r in rows
    ]


async def _load_peers(conn, client_id: str) -> List[Dict[str, Any]]:
    """Load all peers (independent competitors) for the client."""
    rows = await conn.fetch(
        """
        SELECT id, primary_name, COALESCE(aliases, '{}'::text[]) AS aliases
          FROM geo_client_peers
         WHERE client_id = $1
        """,
        client_id,
    )
    return [
        {
            "id": r["id"],
            "primary_name": r["primary_name"],
            "aliases": list(r["aliases"] or []),
        }
        for r in rows
    ]


async def _load_tracked_products(conn, client_id: str) -> List[Dict[str, Any]]:
    """Load tracked_products with denormalized owner names (brand or peer)."""
    rows = await conn.fetch(
        """
        SELECT tp.id,
               tp.product_name,
               COALESCE(tp.match_variants, '{}'::text[]) AS match_variants,
               tp.product_role,
               tp.shadow_sub_role,
               cb.id AS owner_brand_id,
               cb.brand_name AS owner_brand_name,
               cp.id AS owner_peer_id,
               cp.primary_name AS owner_peer_name
          FROM geo_client_topic_products tp
          LEFT JOIN geo_client_brands cb
            ON cb.id = tp.owner_brand_id
           AND cb.client_id = tp.client_id
           AND cb.is_active = true
           AND (
                (tp.product_role = 'own' AND cb.is_shadow = false)
             OR (tp.product_role = 'shadow_brand_product' AND cb.is_shadow = true)
           )
          LEFT JOIN geo_client_peers cp
            ON cp.id = tp.owner_peer_id
           AND cp.client_id = tp.client_id
           AND (tp.product_role = 'peer' OR tp.shadow_sub_role = 'resale')
         WHERE tp.client_id = $1 AND tp.is_active = true
        """,
        client_id,
    )
    return [
        {
            "id": r["id"],
            "product_name": r["product_name"],
            "match_variants": list(r["match_variants"] or []),
            "product_role": r["product_role"],
            "shadow_sub_role": r["shadow_sub_role"],
            "owner_brand_id": r["owner_brand_id"],
            "owner_brand_name": r["owner_brand_name"],
            "owner_peer_id": r["owner_peer_id"],
            "owner_peer_name": r["owner_peer_name"],
        }
        for r in rows
    ]


async def _load_tracked_urls(conn, client_id: str) -> List[Dict[str, Any]]:
    """Load tracked_urls joined with the parent product for Stage 1 matching."""
    rows = await conn.fetch(
        """
        SELECT ptu.id,
               ptu.url,
               ptu.url_scope,
               cb.id AS brand_id,
               cp.id AS peer_id,
               ptu.product_id,
               tp.product_role,
               tp.shadow_sub_role
          FROM geo_product_tracked_urls ptu
          JOIN geo_client_topic_products tp
            ON tp.id = ptu.product_id
           AND tp.client_id = ptu.client_id
           AND tp.is_active = true
          LEFT JOIN geo_client_brands cb
            ON cb.id = ptu.brand_id
           AND cb.client_id = ptu.client_id
          LEFT JOIN geo_client_peers cp
            ON cp.id = ptu.peer_id
           AND cp.client_id = ptu.client_id
         WHERE ptu.client_id = $1
        """,
        client_id,
    )
    return [
        {
            "id": r["id"],
            "url": r["url"],
            "url_scope": r["url_scope"],
            "brand_id": r["brand_id"],
            "peer_id": r["peer_id"],
            "product_id": r["product_id"],
            "product_role": r["product_role"],
            "shadow_sub_role": r["shadow_sub_role"],
        }
        for r in rows
    ]


async def _load_domains(conn, client_id: str) -> List[Dict[str, Any]]:
    """Load domains joined with their owning brand (to derive ``is_shadow``)."""
    rows = await conn.fetch(
        """
        SELECT d.id,
               d.domain,
               d.domain_scope,
               cb.id AS brand_id,
               cp.id AS peer_id,
               cb.is_shadow AS is_shadow
          FROM geo_client_domains d
          LEFT JOIN geo_client_brands cb
            ON cb.id = d.brand_id
           AND cb.client_id = d.client_id
          LEFT JOIN geo_client_peers cp
            ON cp.id = d.peer_id
           AND cp.client_id = d.client_id
         WHERE d.client_id = $1
        """,
        client_id,
    )
    return [
        {
            "id": r["id"],
            "domain": r["domain"],
            "domain_scope": r["domain_scope"],
            "brand_id": r["brand_id"],
            "peer_id": r["peer_id"],
            "is_shadow": bool(r["is_shadow"]) if r["is_shadow"] is not None else False,
        }
        for r in rows
    ]


async def load_client_config(conn, client_id: str) -> ClientConfig:
    """Run all Phase 0 loaders and return a single ``ClientConfig`` snapshot."""
    logger.info("[ANALYZER-S1] 加载 Brands...")
    brands = await _load_brands(conn, client_id)
    logger.info(
        "[ANALYZER-S1]   brands: %d (own=%d, shadow=%d)",
        len(brands),
        sum(1 for b in brands if not b["is_shadow"]),
        sum(1 for b in brands if b["is_shadow"]),
    )

    logger.info("[ANALYZER-S1] 加载 Peers...")
    peers = await _load_peers(conn, client_id)
    logger.info("[ANALYZER-S1]   peers: %d", len(peers))

    logger.info("[ANALYZER-S1] 加载 Tracked Products...")
    tracked_products = await _load_tracked_products(conn, client_id)
    logger.info("[ANALYZER-S1]   tracked_products: %d", len(tracked_products))

    logger.info("[ANALYZER-S1] 加载 Domains...")
    domains = await _load_domains(conn, client_id)
    logger.info("[ANALYZER-S1]   domains: %d", len(domains))

    logger.info("[ANALYZER-S1] 加载 Tracked URLs...")
    tracked_urls = await _load_tracked_urls(conn, client_id)
    logger.info("[ANALYZER-S1]   tracked_urls: %d", len(tracked_urls))

    # Whole-domain Own Brand hosts only — see ClientConfig docstring.
    owned_domain_strs = [
        d["domain"]
        for d in domains
        if d["brand_id"] is not None
        and not d["is_shadow"]
        and d.get("domain_scope") == "whole"
    ]

    return ClientConfig(
        brands=brands,
        peers=peers,
        tracked_products=tracked_products,
        domains=domains,
        tracked_urls=tracked_urls,
        owned_domain_strs=owned_domain_strs,
    )
