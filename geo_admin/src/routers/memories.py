"""
Memories Router — Admin CRUD for agent_memories.

Allows admins to view, create, edit, delete memories per client workspace.
Supports toggling the 'shared' flag (visible to all users under same client).
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from services.workspace_lifecycle import long_workspace_lifecycle_session
from pydantic import BaseModel

from db import database

router = APIRouter(prefix="/memories", tags=["Memories"])

logger = logging.getLogger("GeoAdmin.memories")


# ============================================================================
# Pydantic Models
# ============================================================================

class MemoryCreate(BaseModel):
    client_id: str
    user_identifier: str
    memory_type: str            # 'preference' | 'fact' | 'context' | 'brand'
    content: str
    shared: bool = False


class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    memory_type: Optional[str] = None
    shared: Optional[bool] = None


class MemoryOut(BaseModel):
    id: str
    client_id: str
    user_identifier: Optional[str] = None
    memory_type: Optional[str] = None
    content: Optional[str] = None
    metadata: Any = {}
    shared: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None


class MemoryListOut(BaseModel):
    data: List[MemoryOut]
    total: int
    limit: int
    offset: int


class MemoryUserRow(BaseModel):
    user_identifier: Optional[str] = None
    memory_count: int


class MemoryToggleSharedOut(BaseModel):
    id: str
    shared: bool


_MEMORY_COLUMNS = (
    "id, client_id, user_identifier, memory_type, content, metadata, shared, "
    "created_at, updated_at, expires_at"
)


def _row_to_memory_out(r) -> MemoryOut:
    return MemoryOut(
        id=str(r["id"]),
        client_id=str(r["client_id"]),
        user_identifier=r["user_identifier"],
        memory_type=r["memory_type"],
        content=r["content"],
        metadata=r["metadata"] or {},
        shared=r["shared"],
        created_at=str(r["created_at"]) if r["created_at"] else None,
        updated_at=str(r["updated_at"]) if r["updated_at"] else None,
        expires_at=str(r["expires_at"]) if r["expires_at"] else None,
    )


# ============================================================================
# Endpoints
# ============================================================================

@router.get("", response_model=MemoryListOut)
async def list_memories(
    client_id: str,
    user_identifier: Optional[str] = None,
    memory_type: Optional[str] = None,
    shared_only: bool = False,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> MemoryListOut:
    """List all memories for a client workspace, with optional filters."""
    where_parts = ["client_id = :client_id"]
    params: dict = {"client_id": client_id}

    if user_identifier:
        where_parts.append("user_identifier = :user_identifier")
        params["user_identifier"] = user_identifier
    if memory_type:
        where_parts.append("memory_type = :memory_type")
        params["memory_type"] = memory_type
    if shared_only:
        where_parts.append("shared = TRUE")
    if search:
        where_parts.append("content ILIKE :search")
        params["search"] = f"%{search}%"

    where_sql = " AND ".join(where_parts)

    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM agent_memories WHERE {where_sql}", params
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT {_MEMORY_COLUMNS}
        FROM agent_memories
        WHERE {where_sql}
        ORDER BY updated_at DESC
        LIMIT :limit OFFSET :offset
        """,
        {**params, "limit": limit, "offset": offset},
    )

    return MemoryListOut(
        data=[_row_to_memory_out(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users", response_model=List[MemoryUserRow])
async def list_memory_users(client_id: str) -> List[MemoryUserRow]:
    """List distinct user_identifiers that have memories for a client."""
    rows = await database.fetch_all(
        """
        SELECT user_identifier, COUNT(*) AS memory_count
        FROM agent_memories
        WHERE client_id = :client_id
        GROUP BY user_identifier
        ORDER BY COUNT(*) DESC
        """,
        {"client_id": client_id},
    )
    return [
        MemoryUserRow(
            user_identifier=r["user_identifier"],
            memory_count=r["memory_count"],
        )
        for r in rows
    ]


@router.get("/{memory_id}", response_model=MemoryOut)
async def get_memory(memory_id: UUID) -> MemoryOut:
    """Get a single memory by ID."""
    row = await database.fetch_one(
        f"SELECT {_MEMORY_COLUMNS} FROM agent_memories WHERE id = :id",
        {"id": memory_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")
    return _row_to_memory_out(row)


@router.post("", status_code=201, response_model=MemoryOut)
async def create_memory(data: MemoryCreate) -> MemoryOut:
    """Create a new memory entry (admin-created)."""
    valid_types = {"preference", "fact", "context", "brand"}
    if data.memory_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid memory_type. Must be one of: {', '.join(valid_types)}"
        )

    async with long_workspace_lifecycle_session(database.pool(), data.client_id):
        result = await database.fetch_one(
            """
            INSERT INTO agent_memories
                (client_id, user_identifier, memory_type, content, shared, metadata)
            VALUES
                (:client_id, :user_identifier, :memory_type, :content, :shared, :metadata::jsonb)
            RETURNING id
            """,
            {
                "client_id": data.client_id,
                "user_identifier": data.user_identifier,
                "memory_type": data.memory_type,
                "content": data.content,
                "shared": data.shared,
                "metadata": json.dumps({"source": "admin"}),
            },
        )

    logger.info(f"[MEMORY] Admin created memory | client={data.client_id} | user={data.user_identifier} | type={data.memory_type}")
    return await get_memory(result["id"])


@router.put("/{memory_id}", response_model=MemoryOut)
async def update_memory(memory_id: UUID, data: MemoryUpdate) -> MemoryOut:
    """Update a memory's content, type, or shared status."""
    existing = await database.fetch_one(
        "SELECT id, client_id::text AS client_id FROM agent_memories WHERE id = :id",
        {"id": memory_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "memory_type" in updates:
        valid_types = {"preference", "fact", "context", "brand"}
        if updates["memory_type"] not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid memory_type. Must be one of: {', '.join(valid_types)}"
            )

    allowed = {"content", "memory_type", "shared"}
    sets = [f"{col} = :{col}" for col in updates if col in allowed]
    if not sets:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    async with long_workspace_lifecycle_session(database.pool(), str(existing["client_id"])):
        await database.execute(
            f"UPDATE agent_memories SET {', '.join(sets)} WHERE id = :id",
            {**updates, "id": memory_id},
        )

    logger.info(f"[MEMORY] Admin updated memory {memory_id} | fields={list(updates.keys())}")
    return await get_memory(memory_id)


@router.put("/{memory_id}/toggle-shared", response_model=MemoryToggleSharedOut)
async def toggle_shared(memory_id: UUID) -> MemoryToggleSharedOut:
    """Toggle the shared flag on a memory."""
    existing = await database.fetch_one(
        "SELECT shared, client_id::text AS client_id FROM agent_memories WHERE id = :id",
        {"id": memory_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")

    new_shared = not existing["shared"]
    async with long_workspace_lifecycle_session(database.pool(), str(existing["client_id"])):
        await database.execute(
            "UPDATE agent_memories SET shared = :shared WHERE id = :id",
            {"shared": new_shared, "id": memory_id},
        )

    logger.info(f"[MEMORY] Toggled shared={new_shared} for memory {memory_id}")
    return MemoryToggleSharedOut(id=str(memory_id), shared=new_shared)


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: UUID) -> None:
    """Delete a memory."""
    existing = await database.fetch_one(
        "SELECT id, client_id::text AS client_id FROM agent_memories WHERE id = :id",
        {"id": memory_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")

    async with long_workspace_lifecycle_session(database.pool(), str(existing["client_id"])):
        await database.execute(
            "DELETE FROM agent_memories WHERE id = :id",
            {"id": memory_id},
        )
    logger.info(f"[MEMORY] Admin deleted memory {memory_id}")
    return None


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("", status_code=204)
async def bulk_delete_expired(client_id: str) -> None:
    """Delete all expired memories for a client."""
    async with long_workspace_lifecycle_session(database.pool(), client_id):
        result = await database.execute(
            """
            DELETE FROM agent_memories
            WHERE client_id = :client_id
              AND expires_at IS NOT NULL
              AND expires_at < :now
            """,
            {"client_id": client_id, "now": datetime.now(timezone.utc)},
        )
    logger.info(f"[MEMORY] Bulk deleted expired memories for client {client_id} | affected={result}")
    return None
