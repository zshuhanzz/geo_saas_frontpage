"""
Clients router (SaaS).

Phase 4 (2026-04-25): migrated to the Repository pattern. The legacy
``geo_client_topics.products TEXT[]`` was dropped in v1.2 in favour of the
structured ``geo_client_topic_products`` table, so this router composes
:class:`TopicRepository` and :class:`TopicProductRepository`. Listing /
creating clients themselves still uses the legacy ``databases`` lib because
listing is not in the Repository's tenant-scoped surface (operating ABOVE
the tenant scope).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from geo_common.auth import AuthenticatedUser
from geo_common.services import TopicProductRepository, TopicRepository
from pydantic import BaseModel

from db import database
from dependencies.auth import require_current_user
from pool import get_pool
from routers.me import list_accessible_workspaces

router = APIRouter()


# ─── Output models ─────────────────────────────────────────────────────────


class TopicWithProductsOut(BaseModel):
    """``geo_client_topics`` row + materialized ``products`` list."""

    id: Any
    client_id: Any
    topic_name: Optional[str] = None
    products: List[str] = []
    # Other table columns (defaults / created_at) are surfaced as-is so the
    # frontend doesn't lose anything when the schema gains fields. We use
    # ``Any`` for unknowns so this stays forward-compatible.
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AccessibleClientOut(BaseModel):
    id: str
    name: str
    client_prompt_quota: Optional[int] = None
    config_platforms: List[str] = []
    config_countries: List[str] = []
    config_languages: List[str] = []
    topics: List[TopicWithProductsOut] = []
    role: str
    enabled_features: List[str] = []
    feature_capabilities: dict[str, List[str]] = {}


class TopicCreateOut(BaseModel):
    id: str
    topic_name: str
    products: List[str] = []


class TopicDeleteOut(BaseModel):
    deleted: bool


class ProductsListOut(BaseModel):
    products: List[str]


@router.get("", response_model=List[AccessibleClientOut])
async def list_accessible_clients(
    user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> List[AccessibleClientOut]:
    """Compatibility endpoint with set-based, authorization-first loading.

    New frontend bootstrap uses ``/api/me/workspaces`` followed by one selected
    Workspace context. This endpoint keeps its historical all-details response
    without the previous Workspace × Topic N+1 query pattern.
    """
    summaries = await list_accessible_workspaces(
        current_user=user,
        pool=pool,
    )
    if not summaries:
        return []
    authorized_ids = [UUID(summary.id) for summary in summaries]

    clients = await pool.fetch(
        """
        SELECT id, name, client_prompt_quota,
               config_platforms, config_countries, config_languages
        FROM geo_clients
        WHERE id = ANY($1::uuid[])
        """,
        authorized_ids,
    )
    topics = await pool.fetch(
        """
        SELECT id, client_id, topic_name, topic_type, created_at
        FROM geo_client_topics
        WHERE client_id = ANY($1::uuid[])
        ORDER BY created_at
        """,
        authorized_ids,
    )
    products = await pool.fetch(
        """
        SELECT topic_id, product_name
        FROM geo_client_topic_products
        WHERE client_id = ANY($1::uuid[])
          AND product_role = 'own'
          AND is_active = true
        ORDER BY created_at
        """,
        authorized_ids,
    )

    client_by_id = {str(row["id"]): row for row in clients}
    products_by_topic: dict[str, list[str]] = {}
    for row in products:
        products_by_topic.setdefault(str(row["topic_id"]), []).append(
            str(row["product_name"])
        )
    topics_by_client: dict[str, list[TopicWithProductsOut]] = {}
    for row in topics:
        topic = dict(row)
        topic["products"] = products_by_topic.get(str(row["id"]), [])
        topics_by_client.setdefault(str(row["client_id"]), []).append(
            TopicWithProductsOut(**topic)
        )

    result: list[AccessibleClientOut] = []
    for summary in summaries:
        client = client_by_id.get(summary.id)
        if client is None:
            # The Workspace may have been deleted after the grant list query.
            continue
        result.append(
            AccessibleClientOut(
                id=summary.id,
                name=str(client["name"]),
                client_prompt_quota=client["client_prompt_quota"],
                config_platforms=list(client["config_platforms"] or []),
                config_countries=list(client["config_countries"] or []),
                config_languages=list(client["config_languages"] or []),
                topics=topics_by_client.get(summary.id, []),
                role=summary.role,
                enabled_features=summary.enabled_features,
                feature_capabilities=summary.feature_capabilities,
            )
        )
    return result


# ── Topic / Product Management ──────────────────────────────────────────────


class TopicCreate(BaseModel):
    topic_name: str
    # Optional seed list — onboarding wizard sends ``products: []`` and may
    # later send a non-empty list to create topic + Own products in one shot.
    # Empty list / None is a no-op (no rows in geo_client_topic_products).
    products: Optional[List[str]] = None


class TopicUpdate(BaseModel):
    topic_name: Optional[str] = None
    products: Optional[List[str]] = None


class ProductAdd(BaseModel):
    product_name: str


@router.post("/{client_id}/topics", response_model=TopicCreateOut)
async def create_topic(
    client_id: UUID, body: TopicCreate, pool=Depends(get_pool)
) -> TopicCreateOut:
    """Add a new topic for a client. Optional ``products`` seeds Own product
    rows in ``geo_client_topic_products`` in the same call — kept consistent
    with the legacy frontend wizard which always posts a (possibly empty)
    products list."""
    topic_repo = TopicRepository(pool)
    row = await topic_repo.add(str(client_id), topic_name=body.topic_name)
    seeded: List[str] = []
    if body.products:
        product_repo = TopicProductRepository(pool)
        for pname in body.products:
            pname_clean = (pname or "").strip()
            if not pname_clean:
                continue
            await product_repo.add_own_product(
                str(client_id),
                topic_id=row["id"],
                product_name=pname_clean,
            )
            seeded.append(pname_clean)
    return TopicCreateOut(
        id=str(row["id"]), topic_name=row["topic_name"], products=seeded
    )


@router.put(
    "/{client_id}/topics/{topic_id}", response_model=TopicWithProductsOut
)
async def update_topic(
    client_id: UUID,
    topic_id: UUID,
    body: TopicUpdate,
    pool=Depends(get_pool),
) -> TopicWithProductsOut:
    """Update a topic's name and/or products list.

    ``products`` is mapped into the structured ``geo_client_topic_products``
    table: we delete existing Own products for the topic and re-insert the
    new list. This keeps the public PUT semantics identical to the legacy
    TEXT[]-backed behaviour — callers can still send a full replacement list.
    """
    cid = str(client_id)
    tid = str(topic_id)
    topics_repo = TopicRepository(pool)
    products_repo = TopicProductRepository(pool)

    if body.topic_name is not None:
        await topics_repo.update_name(cid, tid, body.topic_name)

    if body.products is not None:
        # Wipe-and-rewrite Own products for this topic. A fresh client does
        # not yet carry enough structured product metadata (match_variants,
        # tracked_urls, etc.) for merge-by-name to be meaningful, so full
        # replacement matches the legacy TEXT[] semantics cleanly.
        await products_repo.replace_own_products(cid, tid, body.products)

    row = await topics_repo.get_by_id(cid, tid)
    if not row:
        # Normalized to 404 instead of returning {} so the response shape
        # stays consistent with the success branch.
        raise HTTPException(status_code=404, detail="Topic not found")
    names = await products_repo.list_own_names(cid, tid)
    out = dict(row)
    out["products"] = names
    return TopicWithProductsOut(**out)


@router.delete("/{client_id}/topics/{topic_id}", response_model=TopicDeleteOut)
async def delete_topic(
    client_id: UUID, topic_id: UUID, pool=Depends(get_pool)
) -> TopicDeleteOut:
    """Delete a topic from a client."""
    repo = TopicRepository(pool)
    await repo.delete(str(client_id), str(topic_id))
    return TopicDeleteOut(deleted=True)


@router.post("/{client_id}/topics/{topic_id}/products", response_model=ProductsListOut)
async def add_product(
    client_id: UUID,
    topic_id: UUID,
    body: ProductAdd,
    pool=Depends(get_pool),
) -> ProductsListOut:
    """Append an Own product under a topic. Duplicates are rejected."""
    cid = str(client_id)
    tid = str(topic_id)
    topics_repo = TopicRepository(pool)
    products_repo = TopicProductRepository(pool)

    if not await topics_repo.get_by_id(cid, tid):
        raise HTTPException(404, "Topic not found")

    current = await products_repo.list_own_names(cid, tid)
    if body.product_name in current:
        raise HTTPException(400, "Product already exists")

    await products_repo.add_own_product(
        cid, topic_id=tid, product_name=body.product_name
    )
    current.append(body.product_name)
    return ProductsListOut(products=current)


@router.delete(
    "/{client_id}/topics/{topic_id}/products/{product_name}",
    response_model=ProductsListOut,
)
async def remove_product(
    client_id: UUID,
    topic_id: UUID,
    product_name: str,
    pool=Depends(get_pool),
) -> ProductsListOut:
    """Remove an Own product from a topic by product_name."""
    cid = str(client_id)
    tid = str(topic_id)
    topics_repo = TopicRepository(pool)
    products_repo = TopicProductRepository(pool)

    if not await topics_repo.get_by_id(cid, tid):
        raise HTTPException(404, "Topic not found")

    await products_repo.remove_own_product_by_name(cid, tid, product_name)
    remaining = await products_repo.list_own_names(cid, tid)
    return ProductsListOut(products=remaining)
