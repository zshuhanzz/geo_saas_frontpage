"""
Prompts Router (V2.5 SaaS) - CRUD for geo_client_prompts.

Phase 4 (2026-04-25): migrated to :class:`PromptRepository` and
:class:`ClientRepository`. Admin endpoints typically take ``prompt_id`` as
the path param without ``client_id`` (admin god-mode), so update/delete
fetch the prompt's owner first via a cross-tenant SELECT, then call the
tenant-scoped repository with the owning ``client_id``. The cross-tenant
SELECT is justified here because admin operates above the tenant scope.

Replaces the old campaigns.py.
Provides endpoints for Prompt Editor, where users manage the exact LLM prompts
they want to track under specific Topics.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from geo_common.services import (
    PromptCascadeDeletionService,
    PromptRepository,
    PromptWriteCoordinator,
    canonical_prompt_logical_key,
    canonical_prompt_metadata,
    canonical_prompt_physical_key,
    canonical_prompt_text,
)
from geo_common.services.prompt_intent import (
    PromptIntentService,
    PromptIntentValidationError,
)
from pydantic import BaseModel

from pool import get_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prompts", tags=["Prompts"])


# ============================================================================
# Pydantic Models
# ============================================================================

class PromptCreate(BaseModel):
    client_id: UUID
    topic_id: UUID
    text: str
    intent: Optional[str] = None
    platform: str
    country: str
    language: str
    is_active: bool = True


class PromptUpdate(BaseModel):
    text: Optional[str] = None
    intent: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    is_active: Optional[bool] = None


class PromptOut(BaseModel):
    id: str
    client_id: str
    topic_id: str
    topic_name: Optional[str] = None
    text: str
    intent: Optional[str] = None
    product: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PromptPagination(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class PromptListOut(BaseModel):
    data: List[PromptOut]
    pagination: PromptPagination


class PromptConceptOut(BaseModel):
    text: str
    topic_id: str
    topic_name: Optional[str] = None
    intent: Optional[str] = None
    product: Optional[str] = None
    language: Optional[str] = None
    prompt_ids: List[str]
    countries: List[str]
    platforms: List[str]
    final_prompt_count: int
    active_final_prompt_count: int
    inactive_final_prompt_count: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PromptConceptListOut(BaseModel):
    data: List[PromptConceptOut]
    pagination: PromptPagination


class PromptCreateOut(BaseModel):
    id: str
    client_id: UUID
    topic_id: UUID
    text: str
    intent: Optional[str] = None
    platform: str
    country: str
    language: str
    is_active: bool


class PromptStatusOut(BaseModel):
    status: str
    prompt_id: str


# ============================================================================
# Helpers
# ============================================================================

async def _fetch_prompt_owner(pool, prompt_id: UUID) -> dict[str, Any] | None:
    """Cross-tenant SELECT used by admin god-mode endpoints to learn which
    tenant owns ``prompt_id`` so the subsequent tenant-scoped repository call
    can be properly scoped.

    Justified: this router is mounted under ``geo_admin``, which operates
    above the tenant scope. The SaaS-side equivalent always carries
    ``client_id`` in the path / query.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, client_id FROM geo_client_prompts WHERE id = $1",
            prompt_id,
        )
    return dict(row) if row else None


def _stringify(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, UUID):
            out[k] = str(v)
    return out


async def _canonical_prompt_intent(pool, conn, value: str | None) -> str:
    try:
        return await PromptIntentService(pool).require_active_on_connection(conn, value)
    except PromptIntentValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


# ============================================================================
# Prompt CRUD (Prompt Editor)
# ============================================================================

@router.get("/concepts", response_model=PromptConceptListOut)
async def list_prompt_concepts(
    client_id: UUID,
    topic_id: Optional[UUID] = None,
    is_active: Optional[bool] = True,
    search: Optional[str] = None,
    product: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    pool=Depends(get_pool),
) -> PromptConceptListOut:
    """List logical Client Prompts.

    This endpoint paginates the user-authored prompt concept, not the expanded
    country/platform rows in ``geo_client_prompts``. It keeps every prompt's
    variant ids together so the Admin UI can lazy-load complete fanouts.
    """
    offset = (page - 1) * limit
    repo = PromptRepository(pool)
    rows = await repo.list_concepts_for_client(
        str(client_id),
        topic_id=str(topic_id) if topic_id else None,
        is_active=is_active,
        search=search,
        product=product,
        platform=platform,
        country=country,
        language=language,
        limit=limit,
        offset=offset,
        with_topic_name=True,
    )
    total = await repo.count_concepts_for_client(
        str(client_id),
        topic_id=str(topic_id) if topic_id else None,
        is_active=is_active,
        search=search,
        product=product,
        platform=platform,
        country=country,
        language=language,
    )
    data = [
        PromptConceptOut(
            text=r["text"],
            topic_id=str(r["topic_id"]),
            topic_name=r.get("topic_name"),
            intent=r.get("intent") or None,
            product=r.get("product") or None,
            language=r.get("language") or None,
            prompt_ids=[str(pid) for pid in (r.get("prompt_ids") or [])],
            countries=sorted(str(c) for c in (r.get("countries") or []) if c),
            platforms=sorted(str(p) for p in (r.get("platforms") or []) if p),
            final_prompt_count=int(r.get("final_prompt_count") or 0),
            active_final_prompt_count=int(r.get("active_final_prompt_count") or 0),
            inactive_final_prompt_count=int(r.get("inactive_final_prompt_count") or 0),
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )
        for r in rows
    ]
    return PromptConceptListOut(
        data=data,
        pagination=PromptPagination(
            page=page,
            limit=limit,
            total=total,
            pages=(total + limit - 1) // limit if total > 0 else 1,
        ),
    )


@router.get("", response_model=PromptListOut)
async def list_prompts(
    client_id: UUID,
    topic_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    pool=Depends(get_pool),
) -> PromptListOut:
    """List prompts for a specific client (filtered by topic/status)."""
    offset = (page - 1) * limit
    repo = PromptRepository(pool)

    rows = await repo.list_for_client(
        str(client_id),
        topic_id=str(topic_id) if topic_id else None,
        is_active=is_active,
        limit=limit,
        offset=offset,
        with_topic_name=True,
    )
    total = await repo.count_for_client(
        str(client_id),
        topic_id=str(topic_id) if topic_id else None,
        is_active=is_active,
    )

    data = [
        PromptOut(
            id=str(r["id"]),
            client_id=str(r["client_id"]),
            topic_id=str(r["topic_id"]),
            topic_name=r.get("topic_name"),
            text=r["text"],
            intent=r["intent"],
            product=r["product"],
            platform=r["platform"],
            country=r["country"],
            language=r["language"],
            is_active=r["is_active"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]
    return PromptListOut(
        data=data,
        pagination=PromptPagination(
            page=page,
            limit=limit,
            total=total,
            pages=(total + limit - 1) // limit if total > 0 else 1,
        ),
    )


@router.post("", status_code=201, response_model=PromptCreateOut)
async def create_prompt(
    data: PromptCreate, pool=Depends(get_pool)
) -> PromptCreateOut:
    """Create a new Client Prompt in the Prompt Pool."""
    tenant_id = str(data.client_id)

    async def operation(conn) -> PromptCreateOut:
        prompt_repo = PromptRepository(pool)
        canonical_intent = await _canonical_prompt_intent(pool, conn, data.intent)
        client_row = await conn.fetchrow(
            "SELECT id, client_prompt_quota, config_platforms, config_countries, config_languages "
            "FROM geo_clients WHERE id = $1::uuid",
            tenant_id,
        )
        if not client_row:
            raise HTTPException(status_code=404, detail="Client not found")
        client = dict(client_row)
        owned = await prompt_repo.owned_topic_ids_on_connection(
            tenant_id, conn, [data.topic_id]
        )
        if str(data.topic_id) not in owned:
            raise HTTPException(status_code=400, detail="Topic not allowed for client")
        if data.platform not in (client.get("config_platforms") or []):
            raise HTTPException(status_code=400, detail=f"Platform {data.platform} not allowed for client")
        if data.country not in (client.get("config_countries") or []):
            raise HTTPException(status_code=400, detail=f"Country {data.country} not allowed for client")
        if client.get("config_languages") and data.language not in client["config_languages"]:
            raise HTTPException(status_code=400, detail=f"Language {data.language} not allowed for client")

        active_keys = await prompt_repo.active_prompt_keys_on_connection(tenant_id, conn)
        incoming_key = canonical_prompt_logical_key(data.text, data.topic_id)
        if data.is_active and len(active_keys | {incoming_key}) > int(client.get("client_prompt_quota") or 0):
            raise HTTPException(status_code=400, detail="Client Prompt quota exceeded")
        candidate = {
            "topic_id": str(data.topic_id), "text": data.text, "intent": canonical_intent,
            "product": None, "platform": data.platform, "country": data.country,
            "language": data.language,
        }
        matches = await prompt_repo.physical_candidates_on_connection(
            tenant_id, conn, topic_ids=[data.topic_id],
            normalized_texts=[canonical_prompt_text(data.text)],
        )
        matches = [row for row in matches if canonical_prompt_physical_key(row) == canonical_prompt_physical_key(candidate)]
        if any(canonical_prompt_metadata(row) != canonical_prompt_metadata(candidate) for row in matches):
            raise HTTPException(status_code=409, detail="Prompt metadata conflict")
        active_match = next((row for row in matches if row.get("is_active") is not False), None)
        if active_match:
            row = active_match
        elif matches:
            if data.is_active:
                reactivated = await prompt_repo.reactivate_on_connection(
                    tenant_id, conn, [matches[0]["id"]]
                )
                row = reactivated[0]
            else:
                row = matches[0]
        else:
            row = await prompt_repo.add_on_connection(
                tenant_id, conn, topic_id=str(data.topic_id), text=data.text,
                platform=data.platform, country=data.country, language=data.language,
                intent=canonical_intent, is_active=data.is_active,
            )
        return PromptCreateOut(
            id=str(row["id"]), client_id=data.client_id, topic_id=data.topic_id,
            text=row["text"], intent=row.get("intent"), platform=row["platform"],
            country=row["country"], language=row["language"], is_active=bool(row["is_active"]),
        )

    return await PromptWriteCoordinator(pool).execute(tenant_id, operation)


@router.put("/{prompt_id}", response_model=PromptStatusOut)
async def update_prompt(
    prompt_id: UUID,
    data: PromptUpdate,
    pool=Depends(get_pool),
) -> PromptStatusOut:
    """Update a specific prompt's text, config, or active status."""
    owner = await _fetch_prompt_owner(pool, prompt_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Prompt not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}

    if updates:
        tenant_id = str(owner["client_id"])

        async def operation(conn):
            prompt_repo = PromptRepository(pool)
            current = await prompt_repo.get_by_id_on_connection(
                tenant_id, conn, prompt_id, for_update=True
            )
            if not current:
                raise HTTPException(status_code=404, detail="Prompt not found")
            client_row = await conn.fetchrow(
                "SELECT client_prompt_quota, config_platforms, config_countries, config_languages "
                "FROM geo_clients WHERE id = $1::uuid", tenant_id,
            )
            client = dict(client_row or {})
            for field, config, label in (
                ("platform", "config_platforms", "Platform"),
                ("country", "config_countries", "Country"),
                ("language", "config_languages", "Language"),
            ):
                if field in updates and updates[field] not in (client.get(config) or []):
                    raise HTTPException(status_code=400, detail=f"{label} not allowed")
            merged = {**current, **updates}
            if "intent" in updates:
                updates["intent"] = await _canonical_prompt_intent(
                    pool, conn, updates["intent"]
                )
                merged["intent"] = updates["intent"]
            active_keys = await prompt_repo.active_prompt_keys_on_connection(
                tenant_id, conn, exclude_prompt_ids=[prompt_id]
            )
            if merged.get("is_active") is not False:
                active_keys.add(canonical_prompt_logical_key(merged["text"], merged["topic_id"]))
            if len(active_keys) > int(client.get("client_prompt_quota") or 0):
                raise HTTPException(status_code=400, detail="Client Prompt quota exceeded")
            candidates = await prompt_repo.physical_candidates_on_connection(
                tenant_id,
                conn,
                topic_ids=[merged["topic_id"]],
                normalized_texts=[canonical_prompt_text(merged["text"])],
            )
            merged_key = canonical_prompt_physical_key(merged)
            if any(
                str(row["id"]) != str(prompt_id)
                and canonical_prompt_physical_key(row) == merged_key
                for row in candidates
            ):
                raise HTTPException(status_code=409, detail="Prompt identity conflict")
            await prompt_repo.update_on_connection(
                tenant_id, conn, str(prompt_id), updates=updates
            )

        await PromptWriteCoordinator(pool).execute(tenant_id, operation)

    return PromptStatusOut(status="updated", prompt_id=str(prompt_id))


@router.delete("/{prompt_id}", response_model=PromptStatusOut)
async def delete_prompt(
    prompt_id: UUID, pool=Depends(get_pool)
) -> PromptStatusOut:
    """Hard delete a prompt."""
    owner = await _fetch_prompt_owner(pool, prompt_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Prompt not found")
    tenant_id = str(owner["client_id"])

    async def operation(conn):
        await PromptCascadeDeletionService(pool).delete_many_on_connection(
            tenant_id, conn, [str(prompt_id)]
        )

    await PromptWriteCoordinator(pool).execute(tenant_id, operation)
    return PromptStatusOut(status="deleted", prompt_id=str(prompt_id))
