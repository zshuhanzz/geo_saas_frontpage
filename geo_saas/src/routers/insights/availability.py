"""
Availability endpoint — returns the 9 data-driven visibility flags the frontend
uses to decide which sections / tabs / View-By options are shown.

Spec §8.5:
    has_own_brands              = EXISTS(brands WHERE is_shadow=false)
    has_shadow_brands           = EXISTS(brands WHERE is_shadow=true)
    has_peers                   = EXISTS(peers)
    has_topics                  = EXISTS(topics)
    has_own_products            = EXISTS(topic_products WHERE product_role='own')
    has_shadow_products         = EXISTS(topic_products WHERE product_role='shadow_brand_product')
    has_peer_products           = EXISTS(topic_products WHERE product_role='peer')
    has_shadow_sub_role_distinction = EXISTS(topic_products WHERE shadow_sub_role IS NOT NULL)
    has_mentions_data           = EXISTS(brand_mentions in last 30d)
    has_product_mentions_data   = EXISTS(product_mentions in last 30d)
    has_citations_data          = EXISTS(citations in last 30d)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from db import database

router = APIRouter()


class AvailabilityOut(BaseModel):
    client_id: str
    has_own_brands: bool
    has_shadow_brands: bool
    has_peers: bool
    has_topics: bool
    has_own_products: bool
    has_shadow_products: bool
    has_peer_products: bool
    has_shadow_sub_role_distinction: bool
    has_mentions_data: bool
    has_product_mentions_data: bool
    has_citations_data: bool


async def _exists(sql: str, params: dict) -> bool:
    """``True`` iff the SELECT (with an implicit LIMIT 1) returns any row."""
    row = await database.fetch_one(sql + " LIMIT 1", params)
    return row is not None


@router.get("/availability", response_model=AvailabilityOut)
async def get_availability(client_id: UUID) -> AvailabilityOut:
    """Return availability flags driving UI visibility for a client.

    Callers must pass ``client_id``; every sub-query is scoped to it. The 30-
    day window for mentions / citations keeps the flag honest: a tenant with
    stale data from 6 months ago should still see the empty-state card.
    """
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    # --- Configuration flags ---
    has_own_brands = await _exists(
        "SELECT id FROM geo_client_brands "
        "WHERE client_id = :client_id AND is_shadow = FALSE AND is_active = TRUE",
        {"client_id": client_id},
    )
    has_shadow_brands = await _exists(
        "SELECT id FROM geo_client_brands "
        "WHERE client_id = :client_id AND is_shadow = TRUE AND is_active = TRUE",
        {"client_id": client_id},
    )
    has_peers = await _exists(
        "SELECT id FROM geo_client_peers WHERE client_id = :client_id",
        {"client_id": client_id},
    )
    has_topics = await _exists(
        "SELECT id FROM geo_client_topics WHERE client_id = :client_id",
        {"client_id": client_id},
    )

    has_own_products = await _exists(
        "SELECT id FROM geo_client_topic_products "
        "WHERE client_id = :client_id AND product_role = 'own' AND is_active = TRUE",
        {"client_id": client_id},
    )
    has_shadow_products = await _exists(
        "SELECT id FROM geo_client_topic_products "
        "WHERE client_id = :client_id "
        "  AND product_role = 'shadow_brand_product' AND is_active = TRUE",
        {"client_id": client_id},
    )
    has_peer_products = await _exists(
        "SELECT id FROM geo_client_topic_products "
        "WHERE client_id = :client_id AND product_role = 'peer' AND is_active = TRUE",
        {"client_id": client_id},
    )
    has_shadow_sub_role_distinction = await _exists(
        "SELECT id FROM geo_client_topic_products "
        "WHERE client_id = :client_id AND shadow_sub_role IS NOT NULL AND is_active = TRUE",
        {"client_id": client_id},
    )

    # --- Data-presence flags (last 30 days) ---
    has_mentions_data = await _exists(
        "SELECT id FROM geo_brand_mentions "
        "WHERE client_id = :client_id AND executed_at >= :since",
        {"client_id": client_id, "since": thirty_days_ago},
    )
    has_product_mentions_data = await _exists(
        "SELECT id FROM geo_product_mentions "
        "WHERE client_id = :client_id AND executed_at >= :since",
        {"client_id": client_id, "since": thirty_days_ago},
    )
    has_citations_data = await _exists(
        "SELECT id FROM geo_citations "
        "WHERE client_id = :client_id AND executed_at >= :since",
        {"client_id": client_id, "since": thirty_days_ago},
    )

    return AvailabilityOut(
        client_id=str(client_id),
        has_own_brands=has_own_brands,
        has_shadow_brands=has_shadow_brands,
        has_peers=has_peers,
        has_topics=has_topics,
        has_own_products=has_own_products,
        has_shadow_products=has_shadow_products,
        has_peer_products=has_peer_products,
        has_shadow_sub_role_distinction=has_shadow_sub_role_distinction,
        has_mentions_data=has_mentions_data,
        has_product_mentions_data=has_product_mentions_data,
        has_citations_data=has_citations_data,
    )
