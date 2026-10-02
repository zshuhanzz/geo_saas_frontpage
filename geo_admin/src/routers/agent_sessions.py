"""
Agent Sessions Router — read-only audit view of all agent chat sessions.

Admins can browse sessions across all clients, filter by client/user,
and view the full message history for any session.
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from db import database

router = APIRouter(prefix="/agent-sessions", tags=["Agent Sessions"])
logger = logging.getLogger("GeoAdmin.agent_sessions")


# ─── Pydantic models ───────────────────────────────────────────────────────


class AgentSessionRow(BaseModel):
    id: str
    thread_id: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    user_id: Optional[str] = None
    title: Optional[str] = None
    message_count: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentSessionListOut(BaseModel):
    data: list[AgentSessionRow]
    total: int
    limit: int
    offset: int


class AgentMessageOut(BaseModel):
    id: str
    thread_id: str
    role: Optional[str] = None
    content: Optional[Any] = None
    tool_results: Optional[Any] = None
    created_at: Optional[str] = None


@router.get("", response_model=AgentSessionListOut)
async def list_sessions(
    client_id: Optional[str] = None,
    user_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> AgentSessionListOut:
    """List agent sessions with optional filters, newest first."""
    where_parts: list[str] = []
    params: dict = {}
    if client_id:
        where_parts.append("s.client_id = :client_id")
        params["client_id"] = client_id
    if user_id:
        where_parts.append("s.user_id ILIKE :user_id")
        params["user_id"] = f"%{user_id}%"
    if search:
        where_parts.append("s.title ILIKE :search")
        params["search"] = f"%{search}%"
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM agent_sessions s
        LEFT JOIN geo_clients c ON s.client_id = c.id
        {where_sql}
        """,
        params,
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT
            s.id,
            s.thread_id,
            s.client_id,
            s.user_id,
            s.title,
            s.created_at,
            s.updated_at,
            c.name AS client_name,
            (
                SELECT COUNT(*)
                FROM agent_messages m
                WHERE m.thread_id = s.thread_id
            ) AS message_count
        FROM agent_sessions s
        LEFT JOIN geo_clients c ON s.client_id = c.id
        {where_sql}
        ORDER BY s.updated_at DESC
        LIMIT :limit OFFSET :offset
        """,
        {**params, "limit": limit, "offset": offset},
    )

    return AgentSessionListOut(
        data=[
            AgentSessionRow(
                id=str(r["id"]),
                thread_id=r["thread_id"],
                client_id=str(r["client_id"]) if r["client_id"] else None,
                client_name=r["client_name"],
                user_id=r["user_id"],
                title=r["title"],
                message_count=r["message_count"],
                created_at=str(r["created_at"]) if r["created_at"] else None,
                updated_at=str(r["updated_at"]) if r["updated_at"] else None,
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{thread_id}/messages", response_model=list[AgentMessageOut])
async def get_session_messages(thread_id: str) -> list[AgentMessageOut]:
    """Get all messages for a session, ordered chronologically."""
    rows = await database.fetch_all(
        """
        SELECT id, thread_id, role, content, tool_results, created_at
        FROM agent_messages
        WHERE thread_id = :thread_id
        ORDER BY created_at ASC
        """,
        {"thread_id": thread_id},
    )

    return [
        AgentMessageOut(
            id=str(r["id"]),
            thread_id=r["thread_id"],
            role=r["role"],
            content=r["content"],
            tool_results=r["tool_results"],
            created_at=str(r["created_at"]) if r["created_at"] else None,
        )
        for r in rows
    ]
