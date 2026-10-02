"""
Prompts Router for SaaS Frontend.

Phase 4 (2026-04-25): migrated to :class:`PromptRepository`. The
``/{prompt_id}/tasks`` endpoint stays on the legacy ``databases`` lib
because it queries ``geo_tasks`` (not yet repository-ized).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from geo_common.services import (
    DEFAULT_PROMPT_CASCADE_BATCH_SIZE,
    MAX_PROMPT_CASCADE_BATCH_SIZE,
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
from pydantic import BaseModel, Field

from db import database
from pool import get_pool

router = APIRouter()

DEFAULT_PROMPT_DELETE_BATCH_SIZE = DEFAULT_PROMPT_CASCADE_BATCH_SIZE
MAX_PROMPT_DELETE_BATCH_SIZE = MAX_PROMPT_CASCADE_BATCH_SIZE


# ─── Output models ─────────────────────────────────────────────────────────


class PromptOut(BaseModel):
    """Mirror of ``geo_client_prompts`` row. UUIDs and datetimes are
    stringified by the route bodies before serialization."""

    id: str
    client_id: str
    topic_id: str
    text: str
    intent: Optional[str] = None
    product: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PromptFacetsOut(BaseModel):
    countries: List[str]


class PromptIntentFacetsOut(BaseModel):
    active: List[str]
    unconfigured: List[str]
    has_unconfigured_blank: bool


class PromptConceptRepresentativeOut(BaseModel):
    id: str
    client_id: str
    topic_id: str
    text: str
    intent: Optional[str] = None
    product: Optional[str] = None
    language: Optional[str] = None


class PromptConceptOut(BaseModel):
    representative: PromptConceptRepresentativeOut
    prompt_ids: List[str]


class PromptListVariantOut(BaseModel):
    id: str
    platform: Optional[str] = None
    country: Optional[str] = None


class PromptListConceptOut(BaseModel):
    id: str
    prompt_ids: List[str]
    client_id: str
    topic_id: str
    text: str
    intent: Optional[str] = None
    product: Optional[str] = None
    language: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    variants: List[PromptListVariantOut] = Field(default_factory=list)
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
class BatchPromptCreateOut(BaseModel):
    created: int
    ids: List[str]
    reactivated: int = 0
    reactivated_ids: List[str] = Field(default_factory=list)


class BatchDeleteOut(BaseModel):
    deleted: int


class BatchUpdateOut(BaseModel):
    updated: int


class StatusOkOut(BaseModel):
    status: str


class TaskRow(BaseModel):
    """``geo_tasks`` row — wide fields stringified upstream."""

    task_id: str
    client_prompt_id: str
    client_id: str
    topic_id: str
    topic: Optional[str] = None
    product: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    client_prompt_text: Optional[str] = None
    final_prompt: Optional[str] = None
    calls_per_prompt: Optional[int] = None
    dispatched_count: Optional[int] = None
    completed_count: Optional[int] = None
    status: Optional[str] = None
    batch_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PromptCreateInput(BaseModel):
    topic_id: UUID
    text: str
    intent: Optional[str] = None
    product: Optional[str] = None
    platform: str
    country: str
    language: str


class PromptUpdateInput(BaseModel):
    text: Optional[str] = None
    intent: Optional[str] = None
    product: Optional[str] = None
    platform: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    is_active: Optional[bool] = None


class BatchPromptUpdate(BaseModel):
    prompt_ids: List[UUID]
    updates: PromptUpdateInput


class BatchDeleteInput(BaseModel):
    """One serial, all-or-nothing physical-Prompt deletion batch."""

    model_config = {"extra": "forbid"}

    prompt_ids: List[UUID] = Field(default_factory=list, max_length=MAX_PROMPT_DELETE_BATCH_SIZE)
    batch_size: int = Field(
        default=DEFAULT_PROMPT_DELETE_BATCH_SIZE,
        ge=1,
        le=MAX_PROMPT_DELETE_BATCH_SIZE,
    )


def _stringify(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, UUID):
            out[k] = str(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out


def _prompt_quota_key(text: str, topic_id: UUID | str) -> tuple[str, str]:
    return canonical_prompt_logical_key(text, topic_id)


async def _enforce_unique_prompt_quota(
    repo: PromptRepository,
    client_id: str,
    quota: int,
    incoming_keys: set[tuple[str, str]],
    *,
    conn=None,
) -> None:
    """Enforce quota using unique prompt concepts, not expanded rows."""
    if not incoming_keys:
        return
    active_keys = (
        await repo.active_prompt_keys_on_connection(client_id, conn)
        if conn is not None
        else await repo.active_prompt_keys_for_client(client_id)
    )
    new_unique_count = len(incoming_keys - active_keys)
    if len(active_keys) + new_unique_count > quota:
        raise HTTPException(status_code=400, detail="Client Prompt quota exceeded")


async def _validate_prompt_update_config(
    client_id: UUID,
    update_data: dict[str, Any],
) -> None:
    """Validate updated prompt dimensions against client configuration."""
    if not any(k in update_data for k in ["platform", "country", "language"]):
        return

    client = await database.fetch_one(
        """
        SELECT id, config_platforms, config_countries
        FROM geo_clients
        WHERE id = :client_id
        """,
        {"client_id": client_id},
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if "platform" in update_data and update_data["platform"] not in (client["config_platforms"] or []):
        raise HTTPException(status_code=400, detail=f"Platform '{update_data['platform']}' not allowed")
    if "country" in update_data and update_data["country"] not in (client["config_countries"] or []):
        raise HTTPException(status_code=400, detail=f"Country '{update_data['country']}' not allowed")


async def _canonical_prompt_intent(
    service: PromptIntentService,
    value: str | None,
) -> str:
    try:
        return await service.require_active(value)
    except PromptIntentValidationError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if exc.value:
            detail["value"] = exc.value
        raise HTTPException(status_code=422, detail=detail) from exc


async def _canonical_prompt_intent_on_connection(
    service: PromptIntentService,
    conn,
    value: str | None,
) -> str:
    try:
        return await service.require_active_on_connection(conn, value)
    except PromptIntentValidationError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if exc.value:
            detail["value"] = exc.value
        raise HTTPException(status_code=422, detail=detail) from exc


def _normalized_prompt_text(value: str) -> str:
    return canonical_prompt_text(value)


def _physical_identity(row: dict[str, Any]) -> tuple[str, ...]:
    return canonical_prompt_physical_key(row)


def _physical_metadata(row: dict[str, Any]) -> tuple[str, str]:
    return canonical_prompt_metadata(row)


async def _expand_prompt_write_rows(
    conn,
    client_id: str,
    items: list["BatchPromptItemV2"],
    repo: PromptRepository,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    client_row = await conn.fetchrow(
        "SELECT id, client_prompt_quota, config_platforms, config_countries, config_languages "
        "FROM geo_clients WHERE id = $1::uuid",
        client_id,
    )
    if not client_row:
        raise HTTPException(status_code=404, detail="Client not found")
    client = dict(client_row)

    topic_ids = sorted({str(item.topic_id) for item in items})
    owned_topic_ids = await repo.owned_topic_ids_on_connection(client_id, conn, topic_ids)
    missing_topic_ids = sorted(set(topic_ids) - owned_topic_ids)
    if missing_topic_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "topic_not_owned",
                "message": "Every Topic must belong to the current Workspace",
                "topic_ids": missing_topic_ids,
            },
        )

    requested_products = {
        (str(item.topic_id), str(item.product).strip().lower())
        for item in items
        if item.product and str(item.product).strip()
    }
    if requested_products:
        product_rows = await conn.fetch(
            "SELECT topic_id, product_name FROM geo_client_topic_products "
            "WHERE client_id = $1::uuid AND topic_id = ANY($2::uuid[]) "
            "AND is_active = TRUE",
            client_id,
            [UUID(value) for value in topic_ids],
        )
        allowed_products = {
            (str(row["topic_id"]), str(row["product_name"]).strip().lower())
            for row in product_rows
        }
        if not requested_products <= allowed_products:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "product_not_owned",
                    "message": "Every Product must belong to its selected Topic",
                },
            )

    allowed_platforms = set(client.get("config_platforms") or [])
    allowed_countries = set(client.get("config_countries") or [])
    allowed_languages = set(client.get("config_languages") or [])
    intent_service = PromptIntentService(repo.pool)
    rows: list[dict[str, Any]] = []
    for item in items:
        canonical_intent = await _canonical_prompt_intent_on_connection(
            intent_service,
            conn,
            item.intent,
        )
        platforms = item.platforms if item.platforms else (
            [item.platform] if item.platform else ["chatgpt"]
        )
        countries = item.countries if item.countries else (
            [item.country] if item.country else ["US"]
        )
        for platform in platforms:
            if platform not in allowed_platforms:
                raise HTTPException(
                    status_code=400,
                    detail=f"Platform '{platform}' not allowed for this client",
                )
        for country in countries:
            if country not in allowed_countries:
                raise HTTPException(
                    status_code=400,
                    detail=f"Country '{country}' not allowed for this client",
                )
        if allowed_languages and item.language not in allowed_languages:
            raise HTTPException(
                status_code=400,
                detail=f"Language '{item.language}' not allowed for this client",
            )
        for platform in platforms:
            for country in countries:
                rows.append({
                    "topic_id": str(item.topic_id),
                    "text": item.text,
                    "intent": canonical_intent,
                    "product": item.product,
                    "platform": platform,
                    "country": country,
                    "language": item.language,
                    "is_active": True,
                })
    return client, rows


async def _classify_prompt_write_rows(
    conn,
    client_id: str,
    rows: list[dict[str, Any]],
    repo: PromptRepository,
) -> tuple[
    list[dict[str, Any]],
    dict[tuple[str, ...], dict[str, Any]],
    list[str],
]:
    candidates = await repo.physical_candidates_on_connection(
        client_id,
        conn,
        topic_ids=sorted({str(row["topic_id"]) for row in rows}),
        normalized_texts=sorted({_normalized_prompt_text(str(row["text"])) for row in rows}),
    )
    existing_by_identity: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for candidate in candidates:
        existing_by_identity.setdefault(_physical_identity(candidate), []).append(candidate)

    creates: list[dict[str, Any]] = []
    compatible_existing: dict[tuple[str, ...], dict[str, Any]] = {}
    reactivation_ids: list[str] = []
    declared: dict[tuple[str, ...], tuple[str, str]] = {}
    for row in rows:
        identity = _physical_identity(row)
        metadata = _physical_metadata(row)
        prior_metadata = declared.get(identity)
        if prior_metadata is not None:
            if prior_metadata != metadata:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "prompt_metadata_conflict", "message": "Duplicate physical Prompt has conflicting Product or Intent"},
                )
            continue
        declared[identity] = metadata

        matches = existing_by_identity.get(identity, [])
        if any(_physical_metadata(match) != metadata for match in matches):
            raise HTTPException(
                status_code=409,
                detail={"code": "prompt_metadata_conflict", "message": "Existing physical Prompt has conflicting Product or Intent"},
            )
        if matches:
            active_match = next(
                (match for match in matches if match.get("is_active") is not False),
                None,
            )
            selected = active_match or matches[0]
            compatible_existing[identity] = selected
            if active_match is None:
                reactivation_ids.append(str(selected["id"]))
        else:
            creates.append(row)
    return creates, compatible_existing, reactivation_ids


async def _prepare_prompt_updates_on_connection(
    conn,
    client_id: str,
    prompt_ids: list[str],
    updates: dict[str, Any],
    repo: PromptRepository,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current_rows = await repo.get_many_on_connection(
        client_id, conn, prompt_ids, for_update=True
    )
    if len(current_rows) != len(set(prompt_ids)):
        raise HTTPException(status_code=404, detail="Prompt not found")
    clean = dict(updates)
    if "intent" in clean:
        clean["intent"] = await _canonical_prompt_intent_on_connection(
            PromptIntentService(pool=repo.pool), conn, clean["intent"]
        )
    client_row = await conn.fetchrow(
        "SELECT id, client_prompt_quota, config_platforms, config_countries, config_languages "
        "FROM geo_clients WHERE id = $1::uuid",
        client_id,
    )
    if not client_row:
        raise HTTPException(status_code=404, detail="Client not found")
    client = dict(client_row)
    for field, config_field, label in (
        ("platform", "config_platforms", "Platform"),
        ("country", "config_countries", "Country"),
        ("language", "config_languages", "Language"),
    ):
        if field in clean and clean[field] not in (client.get(config_field) or []):
            raise HTTPException(status_code=400, detail=f"{label} not allowed")

    merged_rows = [{**row, **clean} for row in current_rows]
    active_keys = await repo.active_prompt_keys_on_connection(
        client_id, conn, exclude_prompt_ids=prompt_ids
    )
    for row in merged_rows:
        if row.get("is_active") is not False:
            active_keys.add(_prompt_quota_key(row["text"], row["topic_id"]))
    if len(active_keys) > int(client.get("client_prompt_quota") or 0):
        raise HTTPException(status_code=400, detail="Client Prompt quota exceeded")

    candidates = await repo.physical_candidates_on_connection(
        client_id,
        conn,
        topic_ids=sorted({str(row["topic_id"]) for row in merged_rows}),
        normalized_texts=sorted({canonical_prompt_text(row["text"]) for row in merged_rows}),
    )
    updated_ids = {str(row["id"]) for row in current_rows}
    candidate_keys = {
        canonical_prompt_physical_key(row)
        for row in candidates
        if str(row["id"]) not in updated_ids
    }
    merged_keys = [canonical_prompt_physical_key(row) for row in merged_rows]
    if len(set(merged_keys)) != len(merged_keys) or any(key in candidate_keys for key in merged_keys):
        raise HTTPException(
            status_code=409,
            detail={"code": "prompt_identity_conflict", "message": "Prompt update would create a duplicate physical variant"},
        )
    return current_rows, clean


@router.get("/facets", response_model=PromptFacetsOut)
async def get_prompt_facets(
    client_id: UUID,
) -> PromptFacetsOut:
    """Return lightweight prompt metadata for dashboard filters."""
    rows = await database.fetch_all(
        """
        SELECT DISTINCT country
        FROM geo_client_prompts
        WHERE client_id = :client_id
          AND is_active IS DISTINCT FROM FALSE
          AND NULLIF(TRIM(country), '') IS NOT NULL
        ORDER BY country
        """,
        {"client_id": client_id},
    )
    return PromptFacetsOut(countries=[str(row["country"]) for row in rows if row["country"]])


@router.get("/intent-facets", response_model=PromptIntentFacetsOut)
async def get_prompt_intent_facets(
    client_id: UUID,
    pool=Depends(get_pool),
) -> PromptIntentFacetsOut:
    """Return live writable Intents plus this tenant's read-only history."""
    facets = await PromptIntentService(pool).facets(str(client_id))
    return PromptIntentFacetsOut(
        active=facets.active,
        unconfigured=facets.unconfigured,
        has_unconfigured_blank=facets.has_unconfigured_blank,
    )


@router.get("", response_model=List[PromptOut])
@router.get("/", response_model=List[PromptOut], include_in_schema=False)
async def list_prompts(
    client_id: UUID,
    topic_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    pool=Depends(get_pool),
) -> List[PromptOut]:
    """List all prompts for a client."""
    repo = PromptRepository(pool)
    rows = await repo.list_for_client(
        str(client_id),
        topic_id=str(topic_id) if topic_id else None,
        is_active=is_active,
    )
    return [PromptOut(**_stringify(r)) for r in rows]


@router.get("/concepts", response_model=List[PromptListConceptOut])
async def list_prompt_concepts(
    client_id: UUID,
    is_active: Optional[bool] = True,
    pool=Depends(get_pool),
) -> List[PromptListConceptOut]:
    """List compact logical Prompts instead of every platform/country row."""
    rows = await PromptRepository(pool).list_concepts_for_client(
        str(client_id),
        is_active=is_active,
    )
    concepts: List[PromptListConceptOut] = []
    for raw in rows:
        row = _stringify(raw)
        prompt_ids = [str(value) for value in row.get("prompt_ids") or []]
        if not prompt_ids:
            continue
        variant_platforms = list(row.get("variant_platforms") or [])
        variant_countries = list(row.get("variant_countries") or [])
        variants = [
            PromptListVariantOut(
                id=prompt_id,
                platform=str(variant_platforms[index]) if index < len(variant_platforms) and variant_platforms[index] else None,
                country=str(variant_countries[index]) if index < len(variant_countries) and variant_countries[index] else None,
            )
            for index, prompt_id in enumerate(prompt_ids)
        ]
        concepts.append(PromptListConceptOut(
            id=prompt_ids[0],
            prompt_ids=prompt_ids,
            client_id=str(row["client_id"]),
            topic_id=str(row["topic_id"]),
            text=str(row["text"]),
            intent=str(row["intent"]) or None,
            product=str(row["product"]) or None,
            language=str(row["language"]) or None,
            platforms=[str(value) for value in row.get("platforms") or []],
            countries=[str(value) for value in row.get("countries") or []],
            variants=variants,
            is_active=bool(row.get("active_final_prompt_count")),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        ))
    return concepts


@router.post("", response_model=PromptOut)
@router.post("/", response_model=PromptOut, include_in_schema=False)
async def create_prompt(
    client_id: UUID, prompt: PromptCreateInput, pool=Depends(get_pool)
) -> PromptOut:
    """Create a new prompt within the client's prompt pool."""
    tenant_id = str(client_id)

    async def operation(conn) -> PromptOut:
        repo = PromptRepository(pool)
        item = BatchPromptItemV2(
            topic_id=prompt.topic_id,
            text=prompt.text,
            intent=prompt.intent,
            product=prompt.product,
            platforms=[prompt.platform],
            countries=[prompt.country],
            language=prompt.language,
        )
        client, rows = await _expand_prompt_write_rows(
            conn, tenant_id, [item], repo
        )
        await _enforce_unique_prompt_quota(
            repo,
            tenant_id,
            int(client["client_prompt_quota"] or 0),
            {_prompt_quota_key(prompt.text, prompt.topic_id)},
            conn=conn,
        )
        create_rows, existing, reactivation_ids = await _classify_prompt_write_rows(
            conn, tenant_id, rows, repo
        )
        reactivated_rows = await repo.reactivate_on_connection(
            tenant_id, conn, reactivation_ids
        )
        for row in reactivated_rows:
            existing[_physical_identity(row)] = row
        if create_rows:
            row = await repo.add_on_connection(tenant_id, conn, **create_rows[0])
        else:
            row = next(iter(existing.values()), None)
        if not row:
            raise HTTPException(status_code=500, detail="Failed to create prompt")
        return PromptOut(**_stringify(row))

    return await PromptWriteCoordinator(pool).execute(tenant_id, operation)


class BatchPromptItemV2(BaseModel):
    """Supports multi-platform/country: each prompt expands to N rows."""
    topic_id: UUID
    text: str
    intent: Optional[str] = None
    product: Optional[str] = None
    platforms: List[str] = []  # multi-select → expand to N rows
    countries: List[str] = []  # multi-select → expand to N rows
    language: str = "en-US"
    # Legacy single-value fields (fallback)
    platform: Optional[str] = None
    country: Optional[str] = None


class BatchPromptCreate(BaseModel):
    prompts: List[BatchPromptItemV2]


@router.post("/batch", response_model=BatchPromptCreateOut)
async def batch_create_prompts(
    client_id: UUID, data: BatchPromptCreate, pool=Depends(get_pool)
) -> BatchPromptCreateOut:
    """Create multiple prompts at once. Used by brainstorm save flow.
    Supports multi-platform/country: each prompt is expanded to N rows.
    """
    tenant_id = str(client_id)

    async def operation(conn) -> BatchPromptCreateOut:
        repo = PromptRepository(pool)
        client, rows = await _expand_prompt_write_rows(
            conn, tenant_id, data.prompts, repo
        )
        incoming_keys = {
            _prompt_quota_key(prompt.text, prompt.topic_id)
            for prompt in data.prompts
        }
        await _enforce_unique_prompt_quota(
            repo,
            tenant_id,
            int(client["client_prompt_quota"] or 0),
            incoming_keys,
            conn=conn,
        )
        create_rows, _, reactivation_ids = await _classify_prompt_write_rows(
            conn, tenant_id, rows, repo
        )
        reactivated_rows = await repo.reactivate_on_connection(
            tenant_id, conn, reactivation_ids
        )
        ids = await repo.add_many_on_connection(
            tenant_id, conn, create_rows
        )
        return BatchPromptCreateOut(
            created=len(ids),
            ids=ids,
            reactivated=len(reactivated_rows),
            reactivated_ids=[str(row["id"]) for row in reactivated_rows],
        )

    return await PromptWriteCoordinator(pool).execute(tenant_id, operation)


@router.post("/batch-update", response_model=BatchUpdateOut)
@router.post("/batch-update/", response_model=BatchUpdateOut, include_in_schema=False)
async def batch_update_prompts(
    client_id: UUID,
    data: BatchPromptUpdate,
    pool=Depends(get_pool),
) -> BatchUpdateOut:
    """Update multiple prompt rows in one request."""
    update_data = {k: v for k, v in data.updates.model_dump().items() if v is not None}
    if not data.prompt_ids:
        return BatchUpdateOut(updated=0)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    tenant_id = str(client_id)
    prompt_ids = [str(prompt_id) for prompt_id in data.prompt_ids]

    async def operation(conn) -> BatchUpdateOut:
        repo = PromptRepository(pool)
        _, clean = await _prepare_prompt_updates_on_connection(
            conn, tenant_id, prompt_ids, update_data, repo
        )
        updated = await repo.update_many_on_connection(
            tenant_id, conn, prompt_ids, updates=clean
        )
        return BatchUpdateOut(updated=updated)

    return await PromptWriteCoordinator(pool).execute(tenant_id, operation)


@router.get("/{prompt_id}/concept", response_model=PromptConceptOut)
async def get_prompt_concept(
    client_id: UUID,
    prompt_id: UUID,
    pool=Depends(get_pool),
) -> PromptConceptOut:
    """Resolve a physical prompt variant to its tenant-owned logical concept."""
    resolved = await PromptRepository(pool).resolve_concept_by_prompt_id(
        str(client_id),
        str(prompt_id),
    )
    if not resolved:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return PromptConceptOut(
        representative=PromptConceptRepresentativeOut(
            **_stringify(resolved["representative"])
        ),
        prompt_ids=[str(value) for value in resolved["prompt_ids"]],
    )


@router.put("/{prompt_id}", response_model=PromptOut)
async def update_prompt(
    client_id: UUID,
    prompt_id: UUID,
    prompt: PromptUpdateInput,
    pool=Depends(get_pool),
) -> PromptOut:
    """Update an existing prompt."""
    update_data = {k: v for k, v in prompt.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    tenant_id = str(client_id)

    async def operation(conn) -> PromptOut:
        repo = PromptRepository(pool)
        _, clean = await _prepare_prompt_updates_on_connection(
            conn, tenant_id, [str(prompt_id)], update_data, repo
        )
        row = await repo.update_on_connection(
            tenant_id, conn, str(prompt_id), updates=clean
        )
        if not row:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return PromptOut(**_stringify(row))

    return await PromptWriteCoordinator(pool).execute(tenant_id, operation)


@router.post("/batch-delete", response_model=BatchDeleteOut)
@router.post("/batch-delete/", response_model=BatchDeleteOut, include_in_schema=False)
async def batch_delete_prompts(
    client_id: UUID, body: BatchDeleteInput, pool=Depends(get_pool)
) -> BatchDeleteOut:
    """Delete multiple prompts by IDs in one go."""
    prompt_ids = list(body.prompt_ids)
    if not prompt_ids:
        return BatchDeleteOut(deleted=0)
    if len(prompt_ids) > MAX_PROMPT_DELETE_BATCH_SIZE:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "prompt_delete_batch_too_large",
                "message": (
                    "A Prompt delete batch may contain at most "
                    f"{MAX_PROMPT_DELETE_BATCH_SIZE} physical Prompt IDs"
                ),
                "max_batch_size": MAX_PROMPT_DELETE_BATCH_SIZE,
                "requested": len(prompt_ids),
            },
        )
    if len(prompt_ids) > body.batch_size:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "prompt_delete_batch_size_exceeded",
                "message": "The request contains more Prompt IDs than its batch_size",
                "batch_size": body.batch_size,
                "requested": len(prompt_ids),
            },
        )
    try:
        prompt_ids = [str(UUID(str(prompt_id))) for prompt_id in prompt_ids]
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_prompt_delete_id",
                "message": "Every prompt_id must be a valid UUID",
            },
        ) from exc
    tenant_id = str(client_id)

    async def operation(conn) -> BatchDeleteOut:
        result = await PromptCascadeDeletionService(pool).delete_many_on_connection(
            tenant_id, conn, prompt_ids
        )
        return BatchDeleteOut(deleted=result.deleted_prompts)

    return await PromptWriteCoordinator(pool).execute(tenant_id, operation)


@router.delete("/{prompt_id}", response_model=StatusOkOut)
async def delete_prompt(
    client_id: UUID, prompt_id: UUID, pool=Depends(get_pool)
) -> StatusOkOut:
    """Delete a prompt entirely."""
    tenant_id = str(client_id)

    async def operation(conn) -> StatusOkOut:
        await PromptCascadeDeletionService(pool).delete_many_on_connection(
            tenant_id, conn, [str(prompt_id)]
        )
        return StatusOkOut(status="ok")

    return await PromptWriteCoordinator(pool).execute(tenant_id, operation)


@router.get("/{prompt_id}/tasks", response_model=List[TaskRow])
async def list_prompt_tasks(client_id: UUID, prompt_id: UUID) -> List[TaskRow]:
    """Get tasks (final prompts / fanouts) for a client prompt — latest batch only."""
    # Find the latest batch_id for this client_prompt
    latest_batch_id = await database.fetch_val(
        """
        SELECT MAX(batch_id)
        FROM geo_tasks
        WHERE client_prompt_id = :prompt_id AND client_id = :client_id
        """,
        {"prompt_id": prompt_id, "client_id": client_id},
    )

    if not latest_batch_id:
        return []

    rows = await database.fetch_all(
        """
        SELECT *
        FROM geo_tasks
        WHERE client_prompt_id = :prompt_id
          AND client_id = :client_id
          AND batch_id = :batch_id
        ORDER BY created_at DESC
        """,
        {
            "prompt_id": prompt_id,
            "client_id": client_id,
            "batch_id": latest_batch_id,
        },
    )
    results = []
    for row in rows:
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, UUID):
                d[k] = str(v)
            elif hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        results.append(d)
    return [TaskRow(**r) for r in results]
