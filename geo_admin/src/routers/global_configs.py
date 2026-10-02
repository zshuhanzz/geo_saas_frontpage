"""
Global Config Router - CRUD for geo_global_settings, geo_global_platforms, geo_global_intents, geo_domain_categories.

Provides endpoints for managing system-wide configurations.
Phase 2.5b (2026-04-26): SQL fully migrated off SQLAlchemy.
"""
import json
import math
import uuid as _uuid
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from db import database

router = APIRouter(prefix="/global-configs", tags=["Global Configs"])


# ============================================================================
# Pydantic Models
# ============================================================================

class SettingUpsert(BaseModel):
    key: str
    value: str
    description: Optional[str] = None

class PlatformCreate(BaseModel):
    platform_id: str
    display_name: str
    supported_countries: List[str] = []
    system_instructions: Optional[str] = None

class PlatformUpdate(BaseModel):
    display_name: Optional[str] = None
    supported_countries: Optional[List[str]] = None
    system_instructions: Optional[str] = None
    is_active: Optional[bool] = None

class IntentCreate(BaseModel):
    intent_name: str
    allocation_ratio: float
    description: Optional[str] = None
    categories: Optional[List[str]] = []

class IntentUpdate(BaseModel):
    intent_name: Optional[str] = None
    allocation_ratio: Optional[float] = None
    description: Optional[str] = None
    categories: Optional[List[str]] = None
    is_active: Optional[bool] = None

DOMAIN_CATEGORY_ENUM = ["Earned Media", "Agency", "Social Media", "Owned Media", "Other"]

class DomainCategoryCreate(BaseModel):
    domain: str
    category: str
    classified_by: Optional[str] = "manual"

class DomainCategoryUpdate(BaseModel):
    domain: Optional[str] = None
    category: Optional[str] = None


# ─── Output models ─────────────────────────────────────────────────────────


class SettingOut(BaseModel):
    key: str
    value: str
    description: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PlatformOut(BaseModel):
    id: Any
    platform_id: str
    display_name: str
    supported_countries: Optional[List[str]] = None
    system_instructions: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class IntentOut(BaseModel):
    id: Any
    intent_name: str
    allocation_ratio: float
    description: Optional[str] = None
    categories: Optional[Any] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DomainCategoryOut(BaseModel):
    id: Any
    domain: str
    category: str
    classified_by: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SettingPagination(BaseModel):
    page: int
    total: int
    pages: int


class DomainCategoryListOut(BaseModel):
    data: List[DomainCategoryOut]
    pagination: SettingPagination


class SentimentThemeOut(BaseModel):
    id: Any
    theme_name: str
    industry: Optional[str] = None
    created_by: Optional[str] = None
    description: Optional[str] = None
    usage_count: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SentimentThemeListOut(BaseModel):
    data: List[SentimentThemeOut]
    pagination: SettingPagination
    industries: List[str]


# ============================================================================
# Settings CRUD
# ============================================================================

@router.get("/settings", response_model=List[SettingOut])
async def list_settings() -> List[SettingOut]:
    """List all global settings (KV pairs)."""
    rows = await database.fetch_all("SELECT key, value, description, updated_at FROM geo_global_settings")
    return [SettingOut(**dict(r)) for r in rows]


@router.put("/settings", response_model=SettingOut)
async def upsert_setting(data: SettingUpsert) -> SettingOut:
    """Create or update a global setting."""
    existing = await database.fetch_one(
        "SELECT key FROM geo_global_settings WHERE key = :key",
        {"key": data.key},
    )
    if existing:
        await database.execute(
            """
            UPDATE geo_global_settings
            SET value = :value, description = :description
            WHERE key = :key
            """,
            {"key": data.key, "value": data.value, "description": data.description},
        )
    else:
        await database.execute(
            """
            INSERT INTO geo_global_settings (key, value, description)
            VALUES (:key, :value, :description)
            """,
            {"key": data.key, "value": data.value, "description": data.description},
        )
    return SettingOut(key=data.key, value=data.value, description=data.description)


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/settings/{key}", status_code=204)
async def delete_setting(key: str) -> None:
    """Delete a global setting."""
    await database.execute(
        "DELETE FROM geo_global_settings WHERE key = :key", {"key": key}
    )
    return None


# ============================================================================
# Platforms CRUD
# ============================================================================

_PLATFORM_COLUMNS = (
    "id, platform_id, display_name, supported_countries, "
    "system_instructions, is_active, created_at, updated_at"
)


@router.get("/platforms", response_model=List[PlatformOut])
async def list_platforms(active_only: bool = False) -> List[PlatformOut]:
    """List all global platforms."""
    where_sql = "WHERE is_active = TRUE" if active_only else ""
    rows = await database.fetch_all(
        f"""
        SELECT {_PLATFORM_COLUMNS} FROM geo_global_platforms
        {where_sql}
        ORDER BY display_name
        """
    )
    return [PlatformOut(**dict(r)) for r in rows]


@router.post("/platforms", status_code=201, response_model=PlatformOut)
async def create_platform(data: PlatformCreate) -> PlatformOut:
    """Create a new platform configuration."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_global_platforms WHERE platform_id = :platform_id",
        {"platform_id": data.platform_id},
    )
    if existing:
        raise HTTPException(status_code=400, detail="Platform with this ID already exists")

    new_id = _uuid.uuid4()
    await database.execute(
        """
        INSERT INTO geo_global_platforms
            (id, platform_id, display_name, supported_countries, system_instructions)
        VALUES (:id, :platform_id, :display_name, :supported_countries, :system_instructions)
        """,
        {
            "id": new_id,
            "platform_id": data.platform_id,
            "display_name": data.display_name,
            "supported_countries": data.supported_countries,
            "system_instructions": data.system_instructions,
        },
    )
    return PlatformOut(id=str(new_id), **data.model_dump())


@router.put("/platforms/{platform_uuid}", response_model=PlatformOut)
async def update_platform(platform_uuid: UUID, data: PlatformUpdate) -> PlatformOut:
    """Update a platform configuration."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_global_platforms WHERE id = :id",
        {"id": platform_uuid},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Platform not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        allowed = {
            "display_name", "supported_countries",
            "system_instructions", "is_active",
        }
        sets = [f"{col} = :{col}" for col in updates if col in allowed]
        if sets:
            await database.execute(
                f"UPDATE geo_global_platforms SET {', '.join(sets)} WHERE id = :id",
                {**updates, "id": platform_uuid},
            )

    row = await database.fetch_one(
        f"SELECT {_PLATFORM_COLUMNS} FROM geo_global_platforms WHERE id = :id",
        {"id": platform_uuid},
    )
    return PlatformOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/platforms/{platform_uuid}", status_code=204)
async def delete_platform(platform_uuid: UUID) -> None:
    """Delete a platform configuration."""
    await database.execute(
        "DELETE FROM geo_global_platforms WHERE id = :id",
        {"id": platform_uuid},
    )
    return None


# ============================================================================
# Intents CRUD
# ============================================================================

_INTENT_COLUMNS = (
    "id, intent_name, allocation_ratio, description, categories, "
    "is_active, created_at, updated_at"
)


@router.get("/intents", response_model=List[IntentOut])
async def list_intents(active_only: bool = False) -> List[IntentOut]:
    """List all global intents."""
    where_sql = "WHERE is_active = TRUE" if active_only else ""
    rows = await database.fetch_all(
        f"SELECT {_INTENT_COLUMNS} FROM geo_global_intents {where_sql} ORDER BY intent_name"
    )
    return [IntentOut(**dict(r)) for r in rows]


@router.post("/intents", status_code=201, response_model=IntentOut)
async def create_intent(data: IntentCreate) -> IntentOut:
    """Create a new intent."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_global_intents WHERE intent_name = :intent_name",
        {"intent_name": data.intent_name},
    )
    if existing:
        raise HTTPException(status_code=400, detail="Intent with this name already exists")

    new_id = _uuid.uuid4()
    await database.execute(
        """
        INSERT INTO geo_global_intents
            (id, intent_name, allocation_ratio, description, categories)
        VALUES (:id, :intent_name, :allocation_ratio, :description, :categories::jsonb)
        """,
        {
            "id": new_id,
            "intent_name": data.intent_name,
            "allocation_ratio": data.allocation_ratio,
            "description": data.description,
            "categories": json.dumps(data.categories or []),
        },
    )
    return IntentOut(id=str(new_id), **data.model_dump())


@router.put("/intents/{intent_uuid}", response_model=IntentOut)
async def update_intent(intent_uuid: UUID, data: IntentUpdate) -> IntentOut:
    """Update an intent."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_global_intents WHERE id = :id",
        {"id": intent_uuid},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Intent not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        allowed = {
            "intent_name", "allocation_ratio", "description",
            "categories", "is_active",
        }
        sets = []
        params: dict = {"id": intent_uuid}
        for col, val in updates.items():
            if col not in allowed:
                continue
            if col == "categories":
                params[col] = json.dumps(val)
                sets.append(f"{col} = :{col}::jsonb")
            else:
                params[col] = val
                sets.append(f"{col} = :{col}")
        if sets:
            await database.execute(
                f"UPDATE geo_global_intents SET {', '.join(sets)} WHERE id = :id",
                params,
            )

    row = await database.fetch_one(
        f"SELECT {_INTENT_COLUMNS} FROM geo_global_intents WHERE id = :id",
        {"id": intent_uuid},
    )
    return IntentOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/intents/{intent_uuid}", status_code=204)
async def delete_intent(intent_uuid: UUID) -> None:
    """Delete an intent."""
    await database.execute(
        "DELETE FROM geo_global_intents WHERE id = :id",
        {"id": intent_uuid},
    )
    return None


# ============================================================================
# Domain Categories CRUD
# ============================================================================

_DOMAIN_CATEGORY_COLUMNS = "id, domain, category, classified_by, created_at"


@router.get("/domain-categories", response_model=DomainCategoryListOut)
async def list_domain_categories(
    search: Optional[str] = None,
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> DomainCategoryListOut:
    """List domain categories with optional search, category filter, and pagination."""
    where_parts: list[str] = []
    params: dict = {}
    if search:
        where_parts.append("domain ILIKE :search")
        params["search"] = f"%{search}%"
    if category:
        where_parts.append("category = :category")
        params["category"] = category
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_domain_categories{where_sql}", params
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT {_DOMAIN_CATEGORY_COLUMNS} FROM geo_domain_categories
        {where_sql}
        ORDER BY domain
        OFFSET :offset LIMIT :limit
        """,
        {**params, "offset": (page - 1) * limit, "limit": limit},
    )

    return DomainCategoryListOut(
        data=[DomainCategoryOut(**dict(r)) for r in rows],
        pagination=SettingPagination(
            page=page,
            total=total,
            pages=math.ceil(total / limit) if total > 0 else 1,
        ),
    )


@router.get("/domain-categories/enums", response_model=List[str])
async def get_category_enums() -> List[str]:
    """Return available category enum values."""
    return DOMAIN_CATEGORY_ENUM


@router.post("/domain-categories", status_code=201, response_model=DomainCategoryOut)
async def create_domain_category(data: DomainCategoryCreate) -> DomainCategoryOut:
    """Create a new domain category mapping."""
    if data.category not in DOMAIN_CATEGORY_ENUM:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {DOMAIN_CATEGORY_ENUM}")
    existing = await database.fetch_one(
        "SELECT id FROM geo_domain_categories WHERE domain = :domain",
        {"domain": data.domain.lower()},
    )
    if existing:
        raise HTTPException(status_code=400, detail="Domain already exists")
    new_id = _uuid.uuid4()
    await database.execute(
        """
        INSERT INTO geo_domain_categories (id, domain, category, classified_by)
        VALUES (:id, :domain, :category, :classified_by)
        """,
        {
            "id": new_id,
            "domain": data.domain.lower(),
            "category": data.category,
            "classified_by": data.classified_by or "manual",
        },
    )
    return DomainCategoryOut(id=str(new_id), **data.model_dump())


@router.put("/domain-categories/{dc_uuid}", response_model=DomainCategoryOut)
async def update_domain_category(dc_uuid: UUID, data: DomainCategoryUpdate) -> DomainCategoryOut:
    """Update a domain category mapping."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_domain_categories WHERE id = :id",
        {"id": dc_uuid},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Domain category not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if "category" in updates and updates["category"] not in DOMAIN_CATEGORY_ENUM:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {DOMAIN_CATEGORY_ENUM}")
    if "domain" in updates:
        updates["domain"] = updates["domain"].lower()
    if updates:
        allowed = {"domain", "category"}
        sets = [f"{col} = :{col}" for col in updates if col in allowed]
        if sets:
            await database.execute(
                f"UPDATE geo_domain_categories SET {', '.join(sets)} WHERE id = :id",
                {**updates, "id": dc_uuid},
            )
    row = await database.fetch_one(
        f"SELECT {_DOMAIN_CATEGORY_COLUMNS} FROM geo_domain_categories WHERE id = :id",
        {"id": dc_uuid},
    )
    return DomainCategoryOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/domain-categories/{dc_uuid}", status_code=204)
async def delete_domain_category(dc_uuid: UUID) -> None:
    """Delete a domain category mapping."""
    await database.execute(
        "DELETE FROM geo_domain_categories WHERE id = :id",
        {"id": dc_uuid},
    )
    return None


# ============================================================================
# Sentiment Theme Dictionary CRUD
# ============================================================================

class SentimentThemeCreate(BaseModel):
    theme_name: str
    industry: Optional[str] = None
    created_by: Optional[str] = "manual"
    description: Optional[str] = None

class SentimentThemeUpdate(BaseModel):
    theme_name: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None


_SENT_THEME_COLUMNS = (
    "id, theme_name, industry, created_by, description, "
    "usage_count, created_at, updated_at"
)


@router.get("/sentiment-themes", response_model=SentimentThemeListOut)
async def list_sentiment_themes(
    search: Optional[str] = None,
    industry: Optional[str] = None,
    created_by: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
) -> SentimentThemeListOut:
    """List sentiment theme dictionary entries with optional search and pagination."""
    where_parts: list[str] = []
    params: dict = {}
    if search:
        where_parts.append("theme_name ILIKE :search")
        params["search"] = f"%{search}%"
    if industry:
        where_parts.append("industry = :industry")
        params["industry"] = industry
    if created_by:
        where_parts.append("created_by = :created_by")
        params["created_by"] = created_by
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_sentiment_theme_dictionary{where_sql}", params
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT {_SENT_THEME_COLUMNS} FROM geo_sentiment_theme_dictionary
        {where_sql}
        ORDER BY usage_count DESC, theme_name
        OFFSET :offset LIMIT :limit
        """,
        {**params, "offset": (page - 1) * limit, "limit": limit},
    )

    industry_rows = await database.fetch_all(
        """
        SELECT DISTINCT industry FROM geo_sentiment_theme_dictionary
        WHERE industry IS NOT NULL
        ORDER BY industry
        """
    )

    return SentimentThemeListOut(
        data=[SentimentThemeOut(**dict(r)) for r in rows],
        pagination=SettingPagination(
            page=page,
            total=total,
            pages=math.ceil(total / limit) if total else 1,
        ),
        industries=[r["industry"] for r in industry_rows],
    )


@router.post("/sentiment-themes", status_code=201, response_model=SentimentThemeOut)
async def create_sentiment_theme(data: SentimentThemeCreate) -> SentimentThemeOut:
    """Create a new sentiment theme in the dictionary."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_sentiment_theme_dictionary WHERE theme_name = :theme_name",
        {"theme_name": data.theme_name},
    )
    if existing:
        raise HTTPException(status_code=400, detail="Theme with this name already exists")

    new_id = str(_uuid.uuid4())
    result = await database.fetch_one(
        f"""
        INSERT INTO geo_sentiment_theme_dictionary
            (id, theme_name, industry, created_by, description)
        VALUES (:id, :theme_name, :industry, :created_by, :description)
        RETURNING {_SENT_THEME_COLUMNS}
        """,
        {
            "id": new_id,
            "theme_name": data.theme_name,
            "industry": data.industry,
            "created_by": data.created_by or "manual",
            "description": data.description,
        },
    )
    return SentimentThemeOut(**dict(result))


@router.put("/sentiment-themes/{theme_id}", response_model=SentimentThemeOut)
async def update_sentiment_theme(theme_id: UUID, data: SentimentThemeUpdate) -> SentimentThemeOut:
    """Update a sentiment theme entry."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_sentiment_theme_dictionary WHERE id = :id",
        {"id": theme_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Theme not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        allowed = {"theme_name", "industry", "description"}
        sets = [f"{col} = :{col}" for col in updates if col in allowed]
        sets.append("updated_at = NOW()")
        await database.execute(
            f"""
            UPDATE geo_sentiment_theme_dictionary
            SET {', '.join(sets)}
            WHERE id = :id
            """,
            {**updates, "id": theme_id},
        )
    row = await database.fetch_one(
        f"SELECT {_SENT_THEME_COLUMNS} FROM geo_sentiment_theme_dictionary WHERE id = :id",
        {"id": theme_id},
    )
    return SentimentThemeOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/sentiment-themes/{theme_id}", status_code=204)
async def delete_sentiment_theme(theme_id: UUID) -> None:
    """Delete a sentiment theme from the dictionary."""
    await database.execute(
        "DELETE FROM geo_sentiment_theme_dictionary WHERE id = :id",
        {"id": theme_id},
    )
    return None
