"""
Products router — Product-level Tracked URLs + Sales Channels.

Phase 2.5b (2026-04-26): SQL fully migrated off SQLAlchemy. Tracked-URL and
Sales-Channel CRUD now uses raw SQL via the asyncpg-backed ``database``
adapter; product-existence checks remain backed by
:class:`TopicProductRepository`.

Endpoints (mounted under ``/api/settings``):
    - GET    /products/{product_id}/tracked_urls                       — list tracked URLs
    - POST   /products/{product_id}/tracked_urls                       — attach URL
    - PUT    /products/{product_id}/tracked_urls/{tracked_url_id}      — update URL
    - DELETE /products/{product_id}/tracked_urls/{tracked_url_id}      — detach URL
    - GET    /products/{product_id}/sales_channels                     — list sales channels
    - POST   /products/{product_id}/sales_channels                     — declare brand as channel
    - DELETE /products/{product_id}/sales_channels/{brand_id}          — remove channel decl
"""

from __future__ import annotations

from typing import Any, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from geo_common.services import (
    BrandRepository,
    DomainRepository,
    PeerRepository,
    TopicProductRepository,
)
from pydantic import BaseModel

from db import database
from pool import get_pool

from ._helpers import _normalize_host, _validate_owner_exclusive, serialize_row

router = APIRouter(tags=["Brand Settings - Products"])


# ───────── Output models ─────────


class TrackedUrlOut(BaseModel):
    id: str
    client_id: str
    product_id: str
    url: str
    url_scope: Optional[str] = None
    brand_id: Optional[str] = None
    peer_id: Optional[str] = None
    created_at: Optional[str] = None


class SalesChannelOut(BaseModel):
    product_id: str
    brand_id: str
    client_id: str
    notes: Optional[str] = None
    created_at: Optional[str] = None


# ───────── Tracked URL models ─────────

class TrackedUrlCreateInput(BaseModel):
    url: str
    url_scope: str = "exact"  # 'exact' | 'path-prefix'
    brand_id: Optional[UUID] = None
    peer_id: Optional[UUID] = None


class TrackedUrlUpdateInput(BaseModel):
    url: Optional[str] = None
    url_scope: Optional[str] = None
    brand_id: Optional[UUID] = None
    peer_id: Optional[UUID] = None


def _validate_url_scope(scope: Optional[str]) -> None:
    if scope is None:
        return
    if scope not in ("exact", "path-prefix"):
        raise HTTPException(status_code=422, detail="url_scope must be 'exact' or 'path-prefix'")


async def _infer_url_owner(client_id: UUID, url: str, pool):
    """Given a URL, look up its host in ``geo_client_domains`` and return the
    (brand_id, peer_id) owner pair, or (None, None) if the host isn't
    registered.
    """
    host = _normalize_host(url)
    if not host:
        return None, None
    repo = DomainRepository(pool)
    owner_map = await repo.domain_owner_map(str(client_id), scope="whole")
    return owner_map.get(host, (None, None))


async def _require_workspace_owner(
    pool,
    client_id: UUID,
    *,
    brand_id: Optional[UUID],
    peer_id: Optional[UUID],
) -> None:
    """Reject explicit attribution IDs that do not belong to this Workspace."""
    _validate_owner_exclusive(brand_id, peer_id)
    if brand_id is not None:
        row = await BrandRepository(pool).get_by_id(str(client_id), str(brand_id))
        if not row:
            raise HTTPException(
                status_code=422,
                detail="brand_id must belong to the current Workspace",
            )
    if peer_id is not None:
        row = await PeerRepository(pool).get_by_id(str(client_id), str(peer_id))
        if not row:
            raise HTTPException(
                status_code=422,
                detail="peer_id must belong to the current Workspace",
            )


# ───────── Sales channel models ─────────

class SalesChannelCreateInput(BaseModel):
    brand_id: UUID
    notes: Optional[str] = None


# ───────── Tracked URL endpoints ─────────

@router.get("/products/{product_id}/tracked_urls", response_model=List[TrackedUrlOut])
async def list_tracked_urls(
    client_id: UUID, product_id: UUID
) -> List[TrackedUrlOut]:
    rows = await database.fetch_all(
        """
        SELECT * FROM geo_product_tracked_urls
        WHERE client_id = :client_id AND product_id = :product_id
        ORDER BY created_at
        """,
        {"client_id": client_id, "product_id": product_id},
    )
    return [TrackedUrlOut(**serialize_row(r)) for r in rows]


@router.post(
    "/products/{product_id}/tracked_urls",
    status_code=201,
    response_model=TrackedUrlOut,
)
async def create_tracked_url(
    client_id: UUID,
    product_id: UUID,
    data: TrackedUrlCreateInput,
    pool=Depends(get_pool),
) -> TrackedUrlOut:
    _validate_url_scope(data.url_scope)
    _validate_owner_exclusive(data.brand_id, data.peer_id)

    products_repo = TopicProductRepository(pool)
    if not await products_repo.get_by_id(str(client_id), str(product_id)):
        raise HTTPException(status_code=404, detail="Product not found")

    inferred_brand, inferred_peer = await _infer_url_owner(client_id, data.url, pool)
    resolved_brand = data.brand_id
    resolved_peer = data.peer_id

    if inferred_brand is not None or inferred_peer is not None:
        if data.brand_id is not None and data.brand_id != inferred_brand:
            raise HTTPException(
                status_code=400,
                detail="URL host already registered to a different Brand; verify the URL.",
            )
        if data.peer_id is not None and data.peer_id != inferred_peer:
            raise HTTPException(
                status_code=400,
                detail="URL host already registered to a different Peer; verify the URL.",
            )
        if resolved_brand is None and resolved_peer is None:
            resolved_brand = inferred_brand
            resolved_peer = inferred_peer

    await _require_workspace_owner(
        pool,
        client_id,
        brand_id=resolved_brand,
        peer_id=resolved_peer,
    )

    new_id = uuid4()
    row = await database.fetch_one(
        """
        INSERT INTO geo_product_tracked_urls
            (id, client_id, product_id, url, url_scope, brand_id, peer_id)
        VALUES (:id, :client_id, :product_id, :url, :url_scope, :brand_id, :peer_id)
        RETURNING *
        """,
        {
            "id": new_id,
            "client_id": client_id,
            "product_id": product_id,
            "url": data.url,
            "url_scope": data.url_scope,
            "brand_id": resolved_brand,
            "peer_id": resolved_peer,
        },
    )
    return TrackedUrlOut(**serialize_row(row))


@router.put(
    "/products/{product_id}/tracked_urls/{tracked_url_id}",
    response_model=TrackedUrlOut,
)
async def update_tracked_url(
    client_id: UUID,
    product_id: UUID,
    tracked_url_id: UUID,
    data: TrackedUrlUpdateInput,
    pool=Depends(get_pool),
) -> TrackedUrlOut:
    """Update a tracked URL. Empty patch returns the existing row so the
    response shape stays consistent.
    """
    _validate_url_scope(data.url_scope)
    existing = await database.fetch_one(
        """
        SELECT * FROM geo_product_tracked_urls
        WHERE id = :tracked_url_id
          AND client_id = :client_id
          AND product_id = :product_id
        """,
        {
            "tracked_url_id": tracked_url_id,
            "client_id": client_id,
            "product_id": product_id,
        },
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Tracked URL not found")

    payload = data.model_dump(exclude_unset=True)
    effective_brand = payload.get("brand_id", existing["brand_id"])
    effective_peer = payload.get("peer_id", existing["peer_id"])
    _validate_owner_exclusive(effective_brand, effective_peer)

    if "url" in payload and payload["url"]:
        inferred_brand, inferred_peer = await _infer_url_owner(client_id, payload["url"], pool)
        if inferred_brand is not None or inferred_peer is not None:
            if effective_brand is not None and effective_brand != inferred_brand:
                raise HTTPException(
                    status_code=400,
                    detail="URL host already registered to a different Brand; verify the URL.",
                )
            if effective_peer is not None and effective_peer != inferred_peer:
                raise HTTPException(
                    status_code=400,
                    detail="URL host already registered to a different Peer; verify the URL.",
                )
            if effective_brand is None and effective_peer is None:
                effective_brand = inferred_brand
                effective_peer = inferred_peer
                payload["brand_id"] = inferred_brand
                payload["peer_id"] = inferred_peer

    await _require_workspace_owner(
        pool,
        client_id,
        brand_id=effective_brand,
        peer_id=effective_peer,
    )

    base_params = {
        "tracked_url_id": tracked_url_id,
        "client_id": client_id,
        "product_id": product_id,
    }
    if payload:
        # Whitelist updatable columns to avoid SQL injection via Pydantic extras.
        allowed = {"url", "url_scope", "brand_id", "peer_id"}
        sets = []
        upd_params: dict = {**base_params}
        for col, val in payload.items():
            if col not in allowed:
                continue
            sets.append(f"{col} = :{col}")
            upd_params[col] = val
        if sets:
            row = await database.fetch_one(
                f"""
                UPDATE geo_product_tracked_urls
                SET {', '.join(sets)}
                WHERE id = :tracked_url_id
                  AND client_id = :client_id
                  AND product_id = :product_id
                RETURNING *
                """,
                upd_params,
            )
        else:
            row = existing
    else:
        row = existing
    return TrackedUrlOut(**serialize_row(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/products/{product_id}/tracked_urls/{tracked_url_id}", status_code=204)
async def delete_tracked_url(
    client_id: UUID, product_id: UUID, tracked_url_id: UUID
) -> None:
    await database.execute(
        """
        DELETE FROM geo_product_tracked_urls
        WHERE id = :tracked_url_id
          AND client_id = :client_id
          AND product_id = :product_id
        """,
        {
            "tracked_url_id": tracked_url_id,
            "client_id": client_id,
            "product_id": product_id,
        },
    )
    return None


# ───────── Sales channel endpoints ─────────

@router.get("/products/{product_id}/sales_channels", response_model=List[SalesChannelOut])
async def list_sales_channels(
    client_id: UUID, product_id: UUID
) -> List[SalesChannelOut]:
    rows = await database.fetch_all(
        """
        SELECT * FROM geo_product_sales_channels
        WHERE client_id = :client_id AND product_id = :product_id
        ORDER BY created_at
        """,
        {"client_id": client_id, "product_id": product_id},
    )
    return [SalesChannelOut(**serialize_row(r)) for r in rows]


@router.post(
    "/products/{product_id}/sales_channels",
    status_code=201,
    response_model=SalesChannelOut,
)
async def create_sales_channel(
    client_id: UUID,
    product_id: UUID,
    data: SalesChannelCreateInput,
    pool=Depends(get_pool),
) -> SalesChannelOut:
    products_repo = TopicProductRepository(pool)
    brand_repo = BrandRepository(pool)

    if not await products_repo.get_by_id(str(client_id), str(product_id)):
        raise HTTPException(status_code=404, detail="Product not found")

    if not await brand_repo.get_by_id(str(client_id), str(data.brand_id)):
        raise HTTPException(status_code=404, detail="Brand not found")

    try:
        row = await database.fetch_one(
            """
            INSERT INTO geo_product_sales_channels
                (product_id, brand_id, client_id, notes)
            VALUES (:product_id, :brand_id, :client_id, :notes)
            RETURNING *
            """,
            {
                "product_id": product_id,
                "brand_id": data.brand_id,
                "client_id": client_id,
                "notes": data.notes,
            },
        )
    except Exception as exc:
        # Primary-key / unique-violation → already declared. Treat as idempotent.
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            existing = await database.fetch_one(
                """
                SELECT * FROM geo_product_sales_channels
                WHERE product_id = :product_id AND brand_id = :brand_id
                """,
                {"product_id": product_id, "brand_id": data.brand_id},
            )
            return SalesChannelOut(**serialize_row(existing))
        raise
    return SalesChannelOut(**serialize_row(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/products/{product_id}/sales_channels/{brand_id}", status_code=204)
async def delete_sales_channel(
    client_id: UUID, product_id: UUID, brand_id: UUID
) -> None:
    await database.execute(
        """
        DELETE FROM geo_product_sales_channels
        WHERE client_id = :client_id
          AND product_id = :product_id
          AND brand_id = :brand_id
        """,
        {
            "client_id": client_id,
            "product_id": product_id,
            "brand_id": brand_id,
        },
    )
    return None
