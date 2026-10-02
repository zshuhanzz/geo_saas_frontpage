"""
Peers router — Peer (competitor) brand CRUD + Peer products.

Phase 4 (2026-04-25): migrated to the Repository pattern. Peer rows live
behind ``PeerRepository``; peer products live behind
``TopicProductRepository`` (with ``product_role='peer'``).

Endpoints (mounted under ``/api/settings``):
    - GET    /peers                                 — list peers
    - POST   /peers                                 — add peer
    - PUT    /peers/{peer_id}                       — update peer
    - DELETE /peers/{peer_id}                       — remove peer
    - GET    /peers/{peer_id}/products              — list peer products
    - POST   /peers/{peer_id}/products              — attach peer product
    - PUT    /peers/{peer_id}/products/{product_id} — update peer product
    - DELETE /peers/{peer_id}/products/{product_id} — detach peer product
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from geo_common.services import PeerRepository, TopicProductRepository, TopicRepository
from pydantic import BaseModel

from pool import get_pool

router = APIRouter(tags=["Brand Settings - Peers"])


# ───────── Output models ─────────


class PeerOut(BaseModel):
    id: str
    client_id: str
    primary_name: str
    aliases: List[str] = []
    created_at: Optional[datetime] = None


class PeerProductOut(BaseModel):
    id: str
    topic_id: str
    client_id: str
    product_name: str
    match_variants: List[str] = []
    product_role: Optional[str] = None
    shadow_sub_role: Optional[str] = None
    owner_brand_id: Optional[str] = None
    owner_peer_id: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ───────── Peer models ─────────

class PeerCreateInput(BaseModel):
    primary_name: str
    aliases: List[str] = []


class PeerUpdateInput(BaseModel):
    primary_name: Optional[str] = None
    aliases: Optional[List[str]] = None


# ───────── Peer product models ─────────

class PeerProductCreateInput(BaseModel):
    topic_id: UUID
    product_name: str
    match_variants: List[str] = []
    is_active: bool = True


class PeerProductUpdateInput(BaseModel):
    product_name: Optional[str] = None
    match_variants: Optional[List[str]] = None
    topic_id: Optional[UUID] = None
    is_active: Optional[bool] = None


def _stringify(row: dict[str, Any] | None) -> dict[str, Any]:
    """UUID → str so Pydantic serialization stays JSON-friendly."""
    if not row:
        return {}
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, UUID):
            out[k] = str(v)
    return out


async def _require_workspace_topic(pool, client_id: UUID, topic_id: UUID) -> None:
    topic = await TopicRepository(pool).get_by_id(str(client_id), str(topic_id))
    if not topic:
        raise HTTPException(
            status_code=422,
            detail="topic_id must reference a Topic in this Workspace",
        )


# ───────── Peer endpoints ─────────

@router.get("/peers", response_model=List[PeerOut])
async def get_peers(client_id: UUID, pool=Depends(get_pool)) -> List[PeerOut]:
    repo = PeerRepository(pool)
    rows = await repo.list_for_client(str(client_id))
    return [PeerOut(**_stringify(r)) for r in rows]


@router.post("/peers", status_code=201, response_model=PeerOut)
async def add_peer(
    client_id: UUID, data: PeerCreateInput, pool=Depends(get_pool)
) -> PeerOut:
    repo = PeerRepository(pool)
    if await repo.get_by_name(str(client_id), data.primary_name):
        raise HTTPException(
            status_code=400,
            detail="Peer Name already exists for this workspace",
        )
    row = await repo.add(
        str(client_id),
        primary_name=data.primary_name,
        aliases=data.aliases,
    )
    return PeerOut(**_stringify(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/peers/{peer_id}", status_code=204)
async def remove_peer(
    client_id: UUID, peer_id: UUID, pool=Depends(get_pool)
) -> None:
    repo = PeerRepository(pool)
    await repo.delete(str(client_id), str(peer_id))
    return None


@router.put("/peers/{peer_id}", response_model=PeerOut)
async def update_peer(
    client_id: UUID,
    peer_id: UUID,
    data: PeerUpdateInput,
    pool=Depends(get_pool),
) -> PeerOut:
    """Update a peer. Empty patch is a no-op that returns the existing row,
    so the response shape stays consistent.
    """
    repo = PeerRepository(pool)
    row = await repo.update(
        str(client_id),
        str(peer_id),
        primary_name=data.primary_name,
        aliases=data.aliases,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Peer not found")
    return PeerOut(**_stringify(row))


# ───────── Peer product endpoints ─────────

@router.get("/peers/{peer_id}/products", response_model=List[PeerProductOut])
async def list_peer_products(
    client_id: UUID, peer_id: UUID, pool=Depends(get_pool)
) -> List[PeerProductOut]:
    repo = TopicProductRepository(pool)
    rows = await repo.list_by_owner_peer(
        str(client_id), str(peer_id), product_role="peer"
    )
    return [PeerProductOut(**_stringify(r)) for r in rows]


@router.post(
    "/peers/{peer_id}/products", status_code=201, response_model=PeerProductOut
)
async def create_peer_product(
    client_id: UUID,
    peer_id: UUID,
    data: PeerProductCreateInput,
    pool=Depends(get_pool),
) -> PeerProductOut:
    peers_repo = PeerRepository(pool)
    products_repo = TopicProductRepository(pool)

    if not await peers_repo.get_by_id(str(client_id), str(peer_id)):
        raise HTTPException(status_code=404, detail="Peer not found")

    await _require_workspace_topic(pool, client_id, data.topic_id)

    row = await products_repo.add_peer_product(
        str(client_id),
        topic_id=str(data.topic_id),
        product_name=data.product_name,
        owner_peer_id=str(peer_id),
        match_variants=data.match_variants,
        is_active=data.is_active,
    )
    return PeerProductOut(**_stringify(row))


@router.put(
    "/peers/{peer_id}/products/{product_id}", response_model=PeerProductOut
)
async def update_peer_product(
    client_id: UUID,
    peer_id: UUID,
    product_id: UUID,
    data: PeerProductUpdateInput,
    pool=Depends(get_pool),
) -> PeerProductOut:
    """Update a peer product. Empty patch is a no-op that returns the
    existing row so the response shape stays consistent.
    """
    products_repo = TopicProductRepository(pool)
    updates = {
        key: value
        for key, value in data.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if updates.get("topic_id") is not None:
        await _require_workspace_topic(pool, client_id, updates["topic_id"])
        updates["topic_id"] = str(updates["topic_id"])
    row = await products_repo.update(
        str(client_id),
        str(product_id),
        updates=updates,
        scope={"owner_peer_id": str(peer_id)},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Peer product not found")
    return PeerProductOut(**_stringify(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/peers/{peer_id}/products/{product_id}", status_code=204)
async def delete_peer_product(
    client_id: UUID,
    peer_id: UUID,
    product_id: UUID,
    pool=Depends(get_pool),
) -> None:
    products_repo = TopicProductRepository(pool)
    await products_repo.delete_by_id(
        str(client_id),
        str(product_id),
        scope={"owner_peer_id": str(peer_id)},
    )
    return None
