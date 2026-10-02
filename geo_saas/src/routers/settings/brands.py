"""
Brands router — Own + Shadow brand CRUD + Shadow brand products.

Phase 4 (2026-04-25): migrated to the Repository pattern. Brand CRUD is now
backed by :class:`BrandRepository`; the shadow-brand product surface is
backed by :class:`TopicProductRepository`.

Endpoints (mounted under ``/api/settings``):
    - GET    /brands                                  — list Own + Shadow brands
    - POST   /brands                                  — create brand
    - PUT    /brands/{brand_id}                       — update brand
    - DELETE /brands/{brand_id}                       — delete brand
    - GET    /brands/{brand_id}/products              — list shadow brand products (path a + b)
    - POST   /brands/{brand_id}/products              — attach shadow product
    - PUT    /brands/{brand_id}/products/{product_id} — update shadow product
    - DELETE /brands/{brand_id}/products/{product_id} — detach shadow product
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from geo_common.services import (
    BrandRepository,
    PeerRepository,
    TopicProductRepository,
    TopicRepository,
)
from pydantic import BaseModel

from db import database
from pool import get_pool

router = APIRouter(tags=["Brand Settings - Brands"])


# ───────── Output models ─────────


class BrandOut(BaseModel):
    id: str
    client_id: str
    brand_name: str
    aliases: List[str] = []
    is_shadow: Optional[bool] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ShadowBrandProductOut(BaseModel):
    """Same shape as ``geo_client_topic_products`` but with the synthetic
    ``channel_source`` field appended by the list endpoint
    (``'owned'`` for path-a, ``'sales_channel'`` for path-b)."""

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
    channel_source: Optional[str] = None


# ───────── Brand models ─────────

class BrandCreateInput(BaseModel):
    brand_name: str
    aliases: List[str] = []
    is_shadow: bool = False
    is_active: bool = True


class BrandUpdateInput(BaseModel):
    brand_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    is_shadow: Optional[bool] = None
    is_active: Optional[bool] = None


# ───────── Shadow product models ─────────

class ShadowProductCreateInput(BaseModel):
    topic_id: UUID
    product_name: str
    match_variants: List[str] = []
    shadow_sub_role: Optional[str] = None  # 'native' | 'resale' | None
    owner_peer_id: Optional[UUID] = None   # populated when shadow_sub_role='resale'
    is_active: bool = True


class ShadowProductUpdateInput(BaseModel):
    product_name: Optional[str] = None
    match_variants: Optional[List[str]] = None
    shadow_sub_role: Optional[str] = None
    owner_peer_id: Optional[UUID] = None
    topic_id: Optional[UUID] = None
    is_active: Optional[bool] = None


def _validate_shadow_sub_role(sub_role: Optional[str]) -> None:
    if sub_role is None:
        return
    if sub_role not in ("native", "resale"):
        raise HTTPException(
            status_code=422,
            detail="shadow_sub_role must be 'native', 'resale', or null",
        )


def _stringify(row: dict[str, Any] | None) -> dict[str, Any]:
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


async def _require_workspace_peer(pool, client_id: UUID, peer_id: UUID) -> None:
    if not await PeerRepository(pool).get_by_id(str(client_id), str(peer_id)):
        raise HTTPException(
            status_code=422,
            detail="owner_peer_id must reference a Peer in this Workspace",
        )


# ───────── Brand endpoints ─────────

@router.get("/brands", response_model=List[BrandOut])
async def list_brands(
    client_id: UUID,
    is_shadow: Optional[bool] = None,
    pool=Depends(get_pool),
) -> List[BrandOut]:
    """List Own (``is_shadow=false``) and Shadow (``is_shadow=true``) brands."""
    repo = BrandRepository(pool)
    if is_shadow is None:
        rows = await repo.list_for_client(
            str(client_id), include_shadow=True, only_active=False
        )
    elif is_shadow:
        rows = await repo.list_for_client(
            str(client_id), include_shadow=True, only_active=False
        )
        rows = [r for r in rows if r["is_shadow"]]
    else:
        rows = await repo.list_for_client(
            str(client_id), include_shadow=False, only_active=False
        )
    return [BrandOut(**_stringify(r)) for r in rows]


@router.post("/brands", status_code=201, response_model=BrandOut)
async def create_brand(
    client_id: UUID, data: BrandCreateInput, pool=Depends(get_pool)
) -> BrandOut:
    repo = BrandRepository(pool)
    # Check duplicate by listing — small N, cleaner than a dedicated repo method.
    existing = [
        r for r in await repo.list_for_client(
            str(client_id), include_shadow=True, only_active=False
        )
        if r["brand_name"] == data.brand_name
    ]
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Brand name already exists for this workspace",
        )
    row = await repo.add(
        str(client_id),
        brand_name=data.brand_name,
        aliases=data.aliases,
        is_shadow=data.is_shadow,
    )
    # Honour is_active=false on create — Brand.add always inserts is_active
    # default true; if the caller opts out we soft-delete immediately so the
    # state machine stays linear.
    if not data.is_active:
        await repo.soft_delete(str(client_id), row["id"])
        row = await repo.get_by_id(str(client_id), row["id"])
    return BrandOut(**_stringify(row))


@router.put("/brands/{brand_id}", response_model=BrandOut)
async def update_brand(
    client_id: UUID,
    brand_id: UUID,
    data: BrandUpdateInput,
    pool=Depends(get_pool),
) -> BrandOut:
    """Update a brand. Empty patch returns the existing row so the
    response shape is consistent regardless of the patch contents.
    """
    repo = BrandRepository(pool)
    cid = str(client_id)
    bid = str(brand_id)

    payload = {k: v for k, v in data.model_dump().items() if v is not None}
    existing = await repo.get_by_id(cid, bid)
    if not existing:
        raise HTTPException(status_code=404, detail="Brand not found")

    # Own/Shadow is an ownership role, not editable presentation metadata.
    # Changing it in place would invalidate every active product bound to the
    # Brand, so callers must create the correct role and remap explicitly.
    if "is_shadow" in payload and payload["is_shadow"] != existing["is_shadow"]:
        raise HTTPException(
            status_code=409,
            detail="Brand role cannot be changed while updating a Brand",
        )

    row: Optional[dict[str, Any]]
    if not payload:
        row = existing
    else:
        async with pool.acquire() as conn:
            async with conn.transaction():
                aliases = payload.pop("aliases", None)
                if aliases is not None:
                    await repo.update_aliases_on_connection(
                        cid, bid, aliases, conn=conn
                    )

                # Reconcile active dependants before the DB's reverse-invariant
                # trigger allows the Brand to become inactive. Own products
                # remain available as unverified; Shadow products cannot exist
                # without their owning Shadow Brand, so they become inactive.
                if payload.get("is_active") is False:
                    locked_brand = await conn.fetchrow(
                        """
                        SELECT id
                        FROM geo_client_brands
                        WHERE client_id = $1 AND id = $2
                        FOR UPDATE
                        """,
                        cid,
                        bid,
                    )
                    if not locked_brand:
                        raise HTTPException(status_code=404, detail="Brand not found")
                    await conn.execute(
                        """
                        UPDATE geo_client_topic_products
                        SET owner_brand_id = NULL, updated_at = NOW()
                        WHERE client_id = $1 AND owner_brand_id = $2
                          AND product_role = 'own' AND is_active = TRUE
                        """,
                        cid,
                        bid,
                    )
                    await conn.execute(
                        """
                        UPDATE geo_client_topic_products
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE client_id = $1 AND owner_brand_id = $2
                          AND product_role = 'shadow_brand_product'
                          AND is_active = TRUE
                        """,
                        cid,
                        bid,
                    )

                allowed_cols = {"brand_name", "is_active"}
                sets: list[str] = []
                params: list[Any] = [cid, bid]
                for col, val in payload.items():
                    if col not in allowed_cols:
                        continue
                    params.append(val)
                    sets.append(f"{col} = ${len(params)}")
                if sets:
                    await conn.execute(
                        "UPDATE geo_client_brands "
                        f"SET {', '.join(sets)}, updated_at = NOW() "
                        "WHERE client_id = $1 AND id = $2",
                        *params,
                    )
        row = await repo.get_by_id(cid, bid)

    return BrandOut(**_stringify(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/brands/{brand_id}", status_code=204)
async def delete_brand(
    client_id: UUID, brand_id: UUID, pool=Depends(get_pool)
) -> None:
    # Shadow products require their owner Brand, so remove those products
    # before the Brand FK's ON DELETE SET NULL action runs. Own products are
    # intentionally retained as unverified and stop contributing to V2
    # customer sentiment until a new Own Brand is assigned.
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                DELETE FROM geo_client_topic_products
                WHERE client_id = $1
                  AND owner_brand_id = $2
                  AND product_role = 'shadow_brand_product'
                """,
                str(client_id),
                str(brand_id),
            )
            await conn.execute(
                "DELETE FROM geo_client_brands WHERE client_id = $1 AND id = $2",
                str(client_id),
                str(brand_id),
            )
    return None


# ───────── Shadow brand product endpoints ─────────

@router.get("/brands/{brand_id}/products", response_model=List[ShadowBrandProductOut])
async def list_shadow_brand_products(
    client_id: UUID, brand_id: UUID, pool=Depends(get_pool)
) -> List[ShadowBrandProductOut]:
    """List every product associated with a Shadow/channel brand, covering
    BOTH paths:

      (a) Shadow-owned products — product_role='shadow_brand_product' AND
          owner_brand_id = brand_id. These are the canonical "products sold
          ONLY under this channel brand".

      (b) Own or shadow products that declare this brand as a sales channel
          via the geo_product_sales_channels table (written by the
          "产品销售渠道" selector on the Topics page). This covers the OEM
          case where Tmax's own HT-series product is sold through the
          Rough Country channel — it's an Own product but the channel page
          should show it.

    Bug fix 2026-04-21: prior version only returned (a), so selecting a
    sales channel on the Topics page had no visible effect on the brand page.

    Each returned row carries a synthetic `channel_source` field:
      'owned'          → path (a) — brand is the canonical owner
      'sales_channel'  → path (b) — brand is a declared resale channel
    UI can use this to style the row and decide whether
    "remove from channel" means DELETE product vs DELETE sales_channel.
    """
    products_repo = TopicProductRepository(pool)
    owned_rows = await products_repo.list_by_owner_brand(
        str(client_id),
        str(brand_id),
        product_role="shadow_brand_product",
    )
    owned_ids = {row["id"] for row in owned_rows}

    # Sales-channel-attached products — JOIN the channel link table.
    channel_rows = await database.fetch_all(
        """
        SELECT p.*
        FROM geo_client_topic_products p
        JOIN geo_product_sales_channels sc
          ON sc.product_id = p.id
         AND sc.client_id = p.client_id
        WHERE sc.client_id = :client_id
          AND sc.brand_id = :brand_id
        ORDER BY sc.created_at
        """,
        {"client_id": client_id, "brand_id": brand_id},
    )

    out: List[ShadowBrandProductOut] = []
    for r in owned_rows:
        d = _stringify(r)
        d["channel_source"] = "owned"
        out.append(ShadowBrandProductOut(**d))
    for r in channel_rows:
        if r["id"] in owned_ids:
            continue
        d = _stringify(dict(r))
        d["channel_source"] = "sales_channel"
        out.append(ShadowBrandProductOut(**d))
    return out


@router.post(
    "/brands/{brand_id}/products",
    status_code=201,
    response_model=ShadowBrandProductOut,
)
async def create_shadow_brand_product(
    client_id: UUID,
    brand_id: UUID,
    data: ShadowProductCreateInput,
    pool=Depends(get_pool),
) -> ShadowBrandProductOut:
    _validate_shadow_sub_role(data.shadow_sub_role)

    brand_repo = BrandRepository(pool)
    products_repo = TopicProductRepository(pool)

    brand_row = await brand_repo.get_by_id(str(client_id), str(brand_id))
    if not brand_row:
        raise HTTPException(status_code=404, detail="Brand not found")
    if not brand_row["is_shadow"] or not brand_row.get("is_active", True):
        raise HTTPException(
            status_code=400,
            detail="Can only attach shadow_brand_product to an active Shadow brand. Use /topics/{topic_id}/products for Own products.",
        )

    await _require_workspace_topic(pool, client_id, data.topic_id)
    if data.owner_peer_id is not None:
        if data.shadow_sub_role != "resale":
            raise HTTPException(
                status_code=422,
                detail="owner_peer_id is only valid for a resale Shadow product",
            )
        await _require_workspace_peer(pool, client_id, data.owner_peer_id)

    row = await products_repo.add_shadow_brand_product(
        str(client_id),
        topic_id=str(data.topic_id),
        product_name=data.product_name,
        owner_brand_id=str(brand_id),
        match_variants=data.match_variants,
        shadow_sub_role=data.shadow_sub_role,
        owner_peer_id=str(data.owner_peer_id) if data.owner_peer_id else None,
        is_active=data.is_active,
    )
    return ShadowBrandProductOut(**_stringify(row))


@router.put(
    "/brands/{brand_id}/products/{product_id}",
    response_model=ShadowBrandProductOut,
)
async def update_shadow_brand_product(
    client_id: UUID,
    brand_id: UUID,
    product_id: UUID,
    data: ShadowProductUpdateInput,
    pool=Depends(get_pool),
) -> ShadowBrandProductOut:
    """Update a shadow brand product. Empty patch is a no-op that returns the
    existing row so the response shape stays consistent.
    """
    _validate_shadow_sub_role(data.shadow_sub_role)
    products_repo = TopicProductRepository(pool)
    updates = {
        key: value
        for key, value in data.model_dump(exclude_unset=True).items()
        if value is not None or key == "owner_peer_id"
    }
    if updates.get("topic_id") is not None:
        await _require_workspace_topic(pool, client_id, updates["topic_id"])
        updates["topic_id"] = str(updates["topic_id"])
    if updates.get("owner_peer_id") is not None:
        await _require_workspace_peer(pool, client_id, updates["owner_peer_id"])
        updates["owner_peer_id"] = str(updates["owner_peer_id"])
    row = await products_repo.update(
        str(client_id),
        str(product_id),
        updates=updates,
        scope={"owner_brand_id": str(brand_id)},
    )
    if not row:
        raise HTTPException(
            status_code=404, detail="Shadow brand product not found"
        )
    return ShadowBrandProductOut(**_stringify(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/brands/{brand_id}/products/{product_id}", status_code=204)
async def delete_shadow_brand_product(
    client_id: UUID,
    brand_id: UUID,
    product_id: UUID,
    pool=Depends(get_pool),
) -> None:
    products_repo = TopicProductRepository(pool)
    await products_repo.delete_by_id(
        str(client_id),
        str(product_id),
        scope={"owner_brand_id": str(brand_id)},
    )
    return None
