"""
Topics router — Topic CRUD + Bulk import + Own products under topics.

Phase 4 (2026-04-25): topic CRUD migrated to :class:`TopicRepository`; own
product CRUD migrated to :class:`TopicProductRepository`. The bulk import
keeps its three-batch shape but pulls the domain-owner map from
:class:`DomainRepository` and emits the three INSERTs through the legacy
``databases`` lib so we get free ON CONFLICT support without re-implementing
batch-insert primitives in the repository.

Endpoints (mounted under ``/api/settings``):
    - GET    /topics                                  — list topics
    - POST   /topics                                  — add topic
    - POST   /topics/bulk                             — bulk import topics + products + tracked URLs
    - PUT    /topics/{topic_id}                       — update topic
    - DELETE /topics/{topic_id}                       — remove topic
    - GET    /topics/{topic_id}/products              — list own products under topic
    - POST   /topics/{topic_id}/products              — create own product
    - PUT    /topics/{topic_id}/products/{product_id} — update own product
    - DELETE /topics/{topic_id}/products/{product_id} — delete own product
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Union
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from geo_common.services import (
    BrandRepository,
    DomainRepository,
    TopicProductRepository,
    TopicRepository,
)
from pydantic import BaseModel

from db import database
from pool import get_pool

from ._helpers import _normalize_host

router = APIRouter(tags=["Brand Settings - Topics"])


# ───────── Output models ─────────


class TopicOut(BaseModel):
    id: str
    client_id: str
    topic_name: str
    topic_type: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OwnProductOut(BaseModel):
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


class BulkTopicCreatedItem(BaseModel):
    id: str
    topic_name: str
    topic_type: Optional[str] = None
    product_count: int


class BulkTopicCreateOut(BaseModel):
    created: int
    skipped: int
    items: List[BulkTopicCreatedItem]
    tracked_urls_created: int


class TopicUpdatedOut(BaseModel):
    message: str


# ───────── Topic models ─────────

class TopicCreateInput(BaseModel):
    topic_name: str
    topic_type: Optional[str] = "semantic_topic"


class TopicUpdateInput(BaseModel):
    topic_name: Optional[str] = None
    topic_type: Optional[str] = None


class BulkTopicProduct(BaseModel):
    """
    Richer product spec used by Auto-Discovery's "import selected topics" flow.

    ``urls`` carries the real product-detail URLs that Layer 0 scraped from the
    user-supplied seed listing page — these bypass the LLM entirely to avoid
    name-rewording breaking the name↔URL mapping. On import, each URL is
    inserted into ``geo_product_tracked_urls`` with ``url_scope='exact'``.
    """
    name: str
    urls: List[str] = []


class BulkTopicCreateItem(BaseModel):
    topic_name: str
    topic_type: Optional[str] = "semantic_topic"
    # Back-compat: accept plain strings OR {name, urls} objects.
    products: List[Union[str, BulkTopicProduct]] = []


class BulkTopicCreateInput(BaseModel):
    topics: List[BulkTopicCreateItem]


# ───────── Own product models ─────────

class OwnProductCreateInput(BaseModel):
    product_name: str
    match_variants: List[str] = []
    owner_brand_id: UUID
    is_active: bool = True


class OwnProductUpdateInput(BaseModel):
    product_name: Optional[str] = None
    match_variants: Optional[List[str]] = None
    owner_brand_id: Optional[UUID] = None
    is_active: Optional[bool] = None


def _stringify(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, UUID):
            out[k] = str(v)
    return out


async def _require_active_own_brand(pool, client_id: UUID, brand_id: UUID) -> None:
    """Reject cross-tenant, inactive, or Shadow-brand ownership assignments."""
    brand = await BrandRepository(pool).get_by_id(str(client_id), str(brand_id))
    if not brand or brand.get("is_shadow") or not brand.get("is_active", True):
        raise HTTPException(
            status_code=422,
            detail="owner_brand_id must reference an active Own Brand in this Workspace",
        )


# ───────── Topic endpoints ─────────

@router.get("/topics", response_model=List[TopicOut])
async def get_topics(client_id: UUID, pool=Depends(get_pool)) -> List[TopicOut]:
    repo = TopicRepository(pool)
    rows = await repo.list_for_client(str(client_id))
    return [TopicOut(**_stringify(r)) for r in rows]


@router.post("/topics", status_code=201, response_model=TopicOut)
async def add_topic(
    client_id: UUID, data: TopicCreateInput, pool=Depends(get_pool)
) -> TopicOut:
    topic_type = (data.topic_type or "semantic_topic").strip()
    if topic_type not in ("semantic_topic", "product_line"):
        raise HTTPException(
            status_code=422,
            detail="topic_type must be 'semantic_topic' or 'product_line'",
        )
    repo = TopicRepository(pool)
    row = await repo.add(
        str(client_id),
        topic_name=data.topic_name,
        topic_type=topic_type,
    )
    return TopicOut(**_stringify(row))


@router.post("/topics/bulk", status_code=201, response_model=BulkTopicCreateOut)
async def bulk_add_topics(
    client_id: UUID,
    data: BulkTopicCreateInput,
    pool=Depends(get_pool),
) -> BulkTopicCreateOut:
    """Bulk-insert topics + products + tracked URLs in **three round-trips**.

    Called by the Auto-Discovery modal after the user approves a discovered
    topic list. Each product may carry real Layer-0 URLs (name↔URL 1:1 when
    the user supplied seed listing pages) which get inserted as
    ``geo_product_tracked_urls`` rows with ``url_scope='exact'``.

    Performance shape: prior version was 2N+1 sequential queries per URL
    (lookup owner + insert product + insert URL). For a 52-URL import that's
    ~150 round-trips. This version pre-fetches the client's domain map once,
    then emits exactly three batch INSERTs (topics / products / tracked URLs),
    regardless of row count.

    Duplicate topic names (case-insensitive) are silently skipped. Duplicate
    tracked URLs (same client_id + url + product_id) are swallowed by
    ``ON CONFLICT DO NOTHING``.
    """
    if not data.topics:
        return BulkTopicCreateOut(
            created=0, skipped=0, items=[], tracked_urls_created=0
        )

    cid = str(client_id)
    topics_repo = TopicRepository(pool)
    domains_repo = DomainRepository(pool)

    # 1) Existing topic names (case-insensitive dedup).
    existing_lower = await topics_repo.existing_names_lower(cid)

    # 2) Domain → (brand_id, peer_id) map for URL-ownership inference.
    domain_map = await domains_repo.domain_owner_map(cid, scope="whole")

    # 3) Build all INSERT payloads in memory.
    topic_values: list = []
    product_values: list = []
    tracked_url_values: list = []
    seen_tracked_url_keys: set = set()
    created_items: list = []
    skipped = 0

    for t in data.topics:
        name = (t.topic_name or "").strip()
        if not name:
            continue
        if name.lower() in existing_lower:
            skipped += 1
            continue
        topic_type = (t.topic_type or "semantic_topic").strip()
        if topic_type not in ("semantic_topic", "product_line"):
            topic_type = "semantic_topic"
        existing_lower.add(name.lower())

        topic_id = uuid4()
        topic_values.append({
            "id": topic_id,
            "client_id": client_id,
            "topic_name": name,
            "topic_type": topic_type,
        })

        product_count = 0
        for prod_spec in t.products or []:
            if isinstance(prod_spec, str):
                pname_clean = prod_spec.strip()
                urls_for_product: List[str] = []
            else:
                pname_clean = (prod_spec.name or "").strip()
                urls_for_product = [u.strip() for u in (prod_spec.urls or []) if u and u.strip()]
            if not pname_clean:
                continue
            prod_id = uuid4()
            product_values.append({
                "id": prod_id,
                "topic_id": topic_id,
                "client_id": client_id,
                "product_name": pname_clean,
                "match_variants": [],
                "product_role": "own",
            })
            product_count += 1

            # Dedup URLs within each product up-front.
            seen_for_prod: set = set()
            for raw_url in urls_for_product:
                if raw_url in seen_for_prod:
                    continue
                seen_for_prod.add(raw_url)
                host = _normalize_host(raw_url) or ""
                brand_id, peer_id = domain_map.get(host, (None, None))
                key = (str(client_id), raw_url, str(prod_id))
                if key in seen_tracked_url_keys:
                    continue
                seen_tracked_url_keys.add(key)
                tracked_url_values.append({
                    "client_id": client_id,
                    "product_id": prod_id,
                    "url": raw_url,
                    "url_scope": "exact",
                    "brand_id": brand_id,
                    "peer_id": peer_id,
                })

        created_items.append({
            "id": str(topic_id),
            "topic_name": name,
            "topic_type": topic_type,
            "product_count": product_count,
        })

    # 4) Three batch INSERTs. asyncpg has no first-class ``execute_many``
    # over a heterogeneous shape — we loop in a single transaction so the
    # whole bulk import is atomic. ``ON CONFLICT DO NOTHING`` on the
    # tracked-URL composite-unique key swallows duplicates silently.
    if topic_values or product_values or tracked_url_values:
        async with database.transaction() as conn:
            for v in topic_values:
                await conn.execute(
                    """
                    INSERT INTO geo_client_topics
                        (id, client_id, topic_name, topic_type)
                    VALUES ($1, $2, $3, $4)
                    """,
                    v["id"], v["client_id"], v["topic_name"], v["topic_type"],
                )
            for v in product_values:
                await conn.execute(
                    """
                    INSERT INTO geo_client_topic_products
                        (id, topic_id, client_id, product_name,
                         match_variants, product_role)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    v["id"], v["topic_id"], v["client_id"],
                    v["product_name"], v["match_variants"], v["product_role"],
                )
            for v in tracked_url_values:
                await conn.execute(
                    """
                    INSERT INTO geo_product_tracked_urls
                        (client_id, product_id, url, url_scope, brand_id, peer_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (client_id, url, product_id) DO NOTHING
                    """,
                    v["client_id"], v["product_id"], v["url"],
                    v["url_scope"], v["brand_id"], v["peer_id"],
                )

    return BulkTopicCreateOut(
        created=len(created_items),
        skipped=skipped,
        items=[BulkTopicCreatedItem(**i) for i in created_items],
        tracked_urls_created=len(tracked_url_values),
    )


@router.put("/topics/{topic_id}", response_model=TopicUpdatedOut)
async def update_topic(
    client_id: UUID,
    topic_id: UUID,
    data: TopicUpdateInput,
    pool=Depends(get_pool),
) -> TopicUpdatedOut:
    if data.topic_type is not None and data.topic_type not in ("semantic_topic", "product_line"):
        raise HTTPException(
            status_code=422,
            detail="topic_type must be 'semantic_topic' or 'product_line'",
        )
    repo = TopicRepository(pool)
    await repo.update(
        str(client_id),
        str(topic_id),
        topic_name=data.topic_name,
        topic_type=data.topic_type,
    )
    return TopicUpdatedOut(message="Topic updated")


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/topics/{topic_id}", status_code=204)
async def remove_topic(
    client_id: UUID, topic_id: UUID, pool=Depends(get_pool)
) -> None:
    repo = TopicRepository(pool)
    await repo.delete(str(client_id), str(topic_id))
    return None


# ───────── Own product endpoints (under topic) ─────────

@router.get("/topics/{topic_id}/products", response_model=List[OwnProductOut])
async def list_own_products(
    client_id: UUID, topic_id: UUID, pool=Depends(get_pool)
) -> List[OwnProductOut]:
    repo = TopicProductRepository(pool)
    # Mirror legacy semantics: include rows regardless of is_active.
    rows = await repo.list_for_topic(
        str(client_id),
        str(topic_id),
        product_role="own",
        only_active=False,
    )
    return [OwnProductOut(**_stringify(r)) for r in rows]


@router.post(
    "/topics/{topic_id}/products", status_code=201, response_model=OwnProductOut
)
async def create_own_product(
    client_id: UUID,
    topic_id: UUID,
    data: OwnProductCreateInput,
    pool=Depends(get_pool),
) -> OwnProductOut:
    topics_repo = TopicRepository(pool)
    products_repo = TopicProductRepository(pool)

    if not await topics_repo.get_by_id(str(client_id), str(topic_id)):
        raise HTTPException(status_code=404, detail="Topic not found")

    await _require_active_own_brand(pool, client_id, data.owner_brand_id)

    row = await products_repo.add_own_product(
        str(client_id),
        topic_id=str(topic_id),
        product_name=data.product_name,
        match_variants=data.match_variants,
        owner_brand_id=str(data.owner_brand_id),
        is_active=data.is_active,
    )
    return OwnProductOut(**_stringify(row))


@router.put(
    "/topics/{topic_id}/products/{product_id}", response_model=OwnProductOut
)
async def update_own_product(
    client_id: UUID,
    topic_id: UUID,
    product_id: UUID,
    data: OwnProductUpdateInput,
    pool=Depends(get_pool),
) -> OwnProductOut:
    """Update an own product. Empty patch returns the existing row so the
    response shape stays consistent.
    """
    products_repo = TopicProductRepository(pool)
    updates = data.model_dump(exclude_unset=True)
    if "owner_brand_id" in updates:
        if updates["owner_brand_id"] is not None:
            await _require_active_own_brand(pool, client_id, updates["owner_brand_id"])
            updates["owner_brand_id"] = str(updates["owner_brand_id"])
    row = await products_repo.update(
        str(client_id),
        str(product_id),
        updates=updates,
        scope={"topic_id": str(topic_id), "product_role": "own"},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Own product not found")
    return OwnProductOut(**_stringify(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/topics/{topic_id}/products/{product_id}", status_code=204)
async def delete_own_product(
    client_id: UUID,
    topic_id: UUID,
    product_id: UUID,
    pool=Depends(get_pool),
) -> None:
    products_repo = TopicProductRepository(pool)
    await products_repo.delete_by_id(
        str(client_id),
        str(product_id),
        scope={"topic_id": str(topic_id), "product_role": "own"},
    )
    return None
