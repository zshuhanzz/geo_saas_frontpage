"""
Languages Router - CRUD for global languages table.
Used by admin UI for language management.

Phase 2.5b (2026-04-26): SQL fully migrated off SQLAlchemy. Uses raw SQL
via the asyncpg-backed ``database`` adapter.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from db import database

router = APIRouter(prefix="/languages", tags=["Languages"])


# ─── Pydantic models ───────────────────────────────────────────────────────


class LanguageCreate(BaseModel):
    language_code: str = Field(..., min_length=1, max_length=16)
    language: str = Field(..., min_length=1, max_length=64)


class LanguageUpdate(BaseModel):
    language_code: Optional[str] = Field(None, min_length=1, max_length=16)
    language: Optional[str] = Field(None, min_length=1, max_length=64)
    is_active: Optional[bool] = None


class LanguageOut(BaseModel):
    id: str
    language_code: str
    language: str
    is_active: bool
    created_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class LanguageCreateOut(BaseModel):
    id: str
    language_code: str
    language: str


class LanguageUpdateOut(BaseModel):
    id: str
    language_code: Optional[str] = None
    language: Optional[str] = None
    is_active: Optional[bool] = None


class LanguageDeleteOut(BaseModel):
    deleted: bool
    id: str


# ─── Helpers ───────────────────────────────────────────────────────────────


def _row_to_out(row) -> LanguageOut:
    created_at = row["created_at"]
    return LanguageOut(
        id=str(row["id"]),
        language_code=row["language_code"],
        language=row["language"],
        is_active=row["is_active"],
        created_at=created_at.isoformat()
        if isinstance(created_at, datetime)
        else None,
    )


# ─── Endpoints ─────────────────────────────────────────────────────────────


_LANGUAGE_COLUMNS = "id, language_code, language, is_active, created_at"


@router.get("", response_model=list[LanguageOut])
async def list_languages() -> list[LanguageOut]:
    """List all global languages."""
    rows = await database.fetch_all(
        f"SELECT {_LANGUAGE_COLUMNS} FROM geo_global_languages ORDER BY language_code"
    )
    return [_row_to_out(r) for r in rows]


@router.post("", status_code=201, response_model=LanguageCreateOut)
async def create_language(data: LanguageCreate) -> LanguageCreateOut:
    """Create a new language."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_global_languages WHERE language_code = :code",
        {"code": data.language_code},
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Language code '{data.language_code}' already exists",
        )

    result = await database.fetch_one(
        """
        INSERT INTO geo_global_languages (language_code, language)
        VALUES (:code, :language)
        RETURNING id
        """,
        {"code": data.language_code, "language": data.language},
    )
    return LanguageCreateOut(
        id=str(result["id"]),
        language_code=data.language_code,
        language=data.language,
    )


@router.put("/{language_id}", response_model=LanguageUpdateOut)
async def update_language(
    language_id: UUID, data: LanguageUpdate
) -> LanguageUpdateOut:
    """Update a language."""
    lang = await database.fetch_one(
        "SELECT id FROM geo_global_languages WHERE id = :id",
        {"id": language_id},
    )
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    allowed = {"language_code", "language", "is_active"}
    sets = [f"{col} = :{col}" for col in updates if col in allowed]
    if not sets:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    await database.execute(
        f"""
        UPDATE geo_global_languages
        SET {', '.join(sets)}
        WHERE id = :id
        """,
        {**updates, "id": language_id},
    )
    return LanguageUpdateOut(id=str(language_id), **updates)


@router.delete("/{language_id}", response_model=LanguageDeleteOut)
async def delete_language(language_id: UUID) -> LanguageDeleteOut:
    """Delete a language."""
    lang = await database.fetch_one(
        "SELECT id FROM geo_global_languages WHERE id = :id",
        {"id": language_id},
    )
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found")

    await database.execute(
        "DELETE FROM geo_global_languages WHERE id = :id",
        {"id": language_id},
    )
    return LanguageDeleteOut(deleted=True, id=str(language_id))
