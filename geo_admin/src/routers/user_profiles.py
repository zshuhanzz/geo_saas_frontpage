"""
User Profiles Router — Admin CRUD for agent_user_profiles.

Admins can view and edit free-form Markdown user profiles.
"""
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from services.workspace_lifecycle import long_workspace_lifecycle_session
from pydantic import BaseModel

from db import database

router = APIRouter(prefix="/user-profiles", tags=["User Profiles"])
logger = logging.getLogger("GeoAdmin.user_profiles")


class ProfileUpdate(BaseModel):
    profile_md: Optional[str] = None
    onboarded: Optional[bool] = None


class ProfileOut(BaseModel):
    id: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    user_identifier: Optional[str] = None
    profile_md: Optional[str] = None
    onboarded: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProfileListOut(BaseModel):
    data: List[ProfileOut]
    total: int
    limit: int
    offset: int


@router.get("", response_model=ProfileListOut)
async def list_profiles(
    client_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> ProfileListOut:
    """List all user profiles with optional filters."""
    where_parts: list[str] = []
    params: dict = {}
    if client_id:
        where_parts.append("p.client_id = :client_id")
        params["client_id"] = client_id
    if search:
        where_parts.append(
            "(p.user_identifier ILIKE :search OR p.profile_md ILIKE :search)"
        )
        params["search"] = f"%{search}%"
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM agent_user_profiles p
        LEFT JOIN geo_clients c ON p.client_id = c.id
        {where_sql}
        """,
        params,
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT
            p.id, p.client_id, p.user_identifier, p.profile_md,
            p.onboarded, p.created_at, p.updated_at,
            c.name AS client_name
        FROM agent_user_profiles p
        LEFT JOIN geo_clients c ON p.client_id = c.id
        {where_sql}
        ORDER BY p.updated_at DESC
        LIMIT :limit OFFSET :offset
        """,
        {**params, "limit": limit, "offset": offset},
    )

    return ProfileListOut(
        data=[
            ProfileOut(
                id=str(r["id"]),
                client_id=str(r["client_id"]) if r["client_id"] else None,
                client_name=r["client_name"],
                user_identifier=r["user_identifier"],
                profile_md=r["profile_md"],
                onboarded=r["onboarded"],
                created_at=str(r["created_at"]) if r["created_at"] else None,
                updated_at=str(r["updated_at"]) if r["updated_at"] else None,
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{profile_id}", response_model=ProfileOut)
async def get_profile(profile_id: UUID) -> ProfileOut:
    """Get a single user profile."""
    row = await database.fetch_one(
        """
        SELECT
            p.id, p.client_id, p.user_identifier, p.profile_md,
            p.onboarded, p.created_at, p.updated_at,
            c.name AS client_name
        FROM agent_user_profiles p
        LEFT JOIN geo_clients c ON p.client_id = c.id
        WHERE p.id = :id
        """,
        {"id": profile_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")

    return ProfileOut(
        id=str(row["id"]),
        client_id=str(row["client_id"]) if row["client_id"] else None,
        client_name=row["client_name"],
        user_identifier=row["user_identifier"],
        profile_md=row["profile_md"],
        onboarded=row["onboarded"],
        created_at=str(row["created_at"]) if row["created_at"] else None,
        updated_at=str(row["updated_at"]) if row["updated_at"] else None,
    )


@router.put("/{profile_id}", response_model=ProfileOut)
async def update_profile(profile_id: UUID, data: ProfileUpdate) -> ProfileOut:
    """Update a user profile's content or onboarded status."""
    existing = await database.fetch_one(
        "SELECT id, client_id::text AS client_id FROM agent_user_profiles WHERE id = :id",
        {"id": profile_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Profile not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    allowed = {"profile_md", "onboarded"}
    sets = [f"{col} = :{col}" for col in updates if col in allowed]
    if not sets:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    async with long_workspace_lifecycle_session(database.pool(), str(existing["client_id"])):
        await database.execute(
            f"UPDATE agent_user_profiles SET {', '.join(sets)} WHERE id = :id",
            {**updates, "id": profile_id},
        )

    logger.info(f"[PROFILE] Admin updated profile {profile_id} | fields={list(updates.keys())}")
    return await get_profile(profile_id)
