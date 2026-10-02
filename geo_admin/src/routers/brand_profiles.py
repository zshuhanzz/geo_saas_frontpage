"""
Brand Profiles Router — Admin CRUD for geo_brand_profiles.

Allows admin to view and edit brand tonality settings for any client.
These settings are used by the Agent layer (Anthony Chat, Action Agent)
to inject brand context into LLM system prompts.
"""
import json
import uuid
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter
from services.workspace_lifecycle import long_workspace_lifecycle_session
from pydantic import BaseModel, ConfigDict

from db import database

router = APIRouter(prefix="/brand-profiles", tags=["Brand Profiles"])


class BrandProfileUpdate(BaseModel):
    brand_name: Optional[str] = None
    tone_of_voice: Optional[str] = None
    target_audience: Optional[str] = None
    key_messages: Optional[List[str]] = None
    brand_values: Optional[List[str]] = None
    language: Optional[str] = None


class BrandProfileOut(BaseModel):
    """Returned shape for GET — either the full row (when present) or a
    placeholder with ``client_id`` populated and the rest defaulted."""

    id: Optional[Any] = None
    client_id: Any
    brand_name: Optional[str] = None
    tone_of_voice: Optional[str] = None
    target_audience: Optional[str] = None
    key_messages: Optional[List[str]] = None
    brand_values: Optional[List[str]] = None
    language: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OkResult(BaseModel):
    ok: bool


@router.get("/{client_id}", response_model=BrandProfileOut)
async def get_brand_profile(client_id: UUID) -> BrandProfileOut:
    """Get brand profile for a client."""
    row = await database.fetch_one(
        "SELECT * FROM geo_brand_profiles WHERE client_id = :client_id",
        {"client_id": client_id},
    )
    if not row:
        return BrandProfileOut(
            client_id=str(client_id),
            brand_name=None,
            tone_of_voice=None,
            target_audience=None,
            key_messages=[],
            brand_values=[],
            language=None,
        )
    return BrandProfileOut(**dict(row))


@router.put("/{client_id}", response_model=OkResult)
async def upsert_brand_profile(client_id: UUID, data: BrandProfileUpdate) -> OkResult:
    """Create or update brand profile for a client."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_brand_profiles WHERE client_id = :client_id",
        {"client_id": client_id},
    )

    if existing:
        # Build a partial UPDATE — column whitelist guarded by the local
        # mapping so a malformed BrandProfileUpdate can't smuggle keys in.
        allowed = {
            "brand_name",
            "tone_of_voice",
            "target_audience",
            "key_messages",
            "brand_values",
            "language",
        }
        sets: list[str] = []
        params: dict = {"client_id": client_id}
        for col in allowed:
            val = getattr(data, col, None)
            if val is None:
                continue
            # JSONB columns need json.dumps when going through asyncpg.
            if col in {"key_messages", "brand_values"}:
                params[col] = json.dumps(val)
                sets.append(f"{col} = :{col}::jsonb")
            else:
                params[col] = val
                sets.append(f"{col} = :{col}")
        sets.append("updated_at = NOW()")
        async with long_workspace_lifecycle_session(database.pool(), str(client_id)):
            await database.execute(
                f"""
                UPDATE geo_brand_profiles
                SET {', '.join(sets)}
                WHERE client_id = :client_id
                """,
                params,
            )
    else:
        async with long_workspace_lifecycle_session(database.pool(), str(client_id)):
            await database.execute(
                """
                INSERT INTO geo_brand_profiles
                    (id, client_id, brand_name, tone_of_voice, target_audience,
                     key_messages, brand_values, language)
                VALUES
                    (:id, :client_id, :brand_name, :tone_of_voice, :target_audience,
                     :key_messages::jsonb, :brand_values::jsonb, :language)
                """,
                {
                    "id": uuid.uuid4(),
                    "client_id": client_id,
                    "brand_name": data.brand_name,
                    "tone_of_voice": data.tone_of_voice,
                    "target_audience": data.target_audience,
                    "key_messages": json.dumps(data.key_messages or []),
                    "brand_values": json.dumps(data.brand_values or []),
                    "language": data.language or "zh-CN",
                },
            )

    return OkResult(ok=True)
