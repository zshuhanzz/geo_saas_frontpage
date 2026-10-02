"""
TopicRepository — DAL for ``geo_client_topics``.

A Topic is a tenant-scoped tracking theme that prompts and products attach to.
Schema (post-v1.2):

    id UUID PK, client_id UUID FK, topic_name TEXT,
    topic_type TEXT default 'semantic_topic'  -- 'semantic_topic' | 'product_line'
    created_at TIMESTAMP

The historical ``products TEXT[]`` column was dropped in v1.2 — Own products
now live in ``geo_client_topic_products`` and are owned by ``TopicProductRepository``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from geo_common.db import tenant_scoped

from .base import BaseRepository

_TOPIC_TYPES = ("semantic_topic", "product_line")


class TopicRepository(BaseRepository):
    """``geo_client_topics`` DAL."""

    @tenant_scoped
    async def list_for_client(self, client_id: str) -> list[dict[str, Any]]:
        """Every topic belonging to a client, ordered by creation time."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, client_id, topic_name, topic_type, created_at "
                "FROM geo_client_topics "
                "WHERE client_id = $1 "
                "ORDER BY created_at",
                client_id,
            )
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def get_by_id(
        self, client_id: str, topic_id: UUID | str
    ) -> dict[str, Any] | None:
        """Fetch a single topic. Tenant-scoped — cross-tenant lookups return None."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, client_id, topic_name, topic_type, created_at "
                "FROM geo_client_topics "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                topic_id,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add(
        self,
        client_id: str,
        *,
        topic_name: str,
        topic_type: str = "semantic_topic",
    ) -> dict[str, Any]:
        """INSERT a new topic and return the persisted row.

        ``topic_type`` is validated against the v1.2 enumeration. The router
        layer should still surface a friendly 422; this is the defense-in-depth
        check at the DAL boundary.
        """
        if topic_type not in _TOPIC_TYPES:
            raise ValueError(
                f"topic_type must be one of {_TOPIC_TYPES}, got {topic_type!r}"
            )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO geo_client_topics "
                "(id, client_id, topic_name, topic_type) "
                "VALUES ($1, $2, $3, $4) "
                "RETURNING id, client_id, topic_name, topic_type, created_at",
                uuid4(),
                client_id,
                topic_name,
                topic_type,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update_name(
        self,
        client_id: str,
        topic_id: UUID | str,
        topic_name: str,
    ) -> dict[str, Any] | None:
        """Rename a topic. Returns the updated row, or None if not found."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE geo_client_topics "
                "SET topic_name = $3 "
                "WHERE client_id = $1 AND id = $2 "
                "RETURNING id, client_id, topic_name, topic_type, created_at",
                client_id,
                topic_id,
                topic_name,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update(
        self,
        client_id: str,
        topic_id: UUID | str,
        *,
        topic_name: str | None = None,
        topic_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Partial update of name and/or type.

        Returns the updated row, or None if the row didn't exist. If neither
        field is provided, behaves as a no-op fetch (the existing row, or None).
        """
        if topic_type is not None and topic_type not in _TOPIC_TYPES:
            raise ValueError(
                f"topic_type must be one of {_TOPIC_TYPES}, got {topic_type!r}"
            )

        sets: list[str] = []
        params: list[Any] = [client_id, topic_id]
        if topic_name is not None:
            sets.append(f"topic_name = ${len(params) + 1}")
            params.append(topic_name)
        if topic_type is not None:
            sets.append(f"topic_type = ${len(params) + 1}")
            params.append(topic_type)

        async with self._pool.acquire() as conn:
            if not sets:
                row = await conn.fetchrow(
                    "SELECT id, client_id, topic_name, topic_type, created_at "
                    "FROM geo_client_topics "
                    "WHERE client_id = $1 AND id = $2",
                    client_id,
                    topic_id,
                )
            else:
                row = await conn.fetchrow(
                    "UPDATE geo_client_topics "
                    f"SET {', '.join(sets)} "
                    "WHERE client_id = $1 AND id = $2 "
                    "RETURNING id, client_id, topic_name, topic_type, created_at",
                    *params,
                )
        return self._row_to_dict(row)

    @tenant_scoped
    async def delete(self, client_id: str, topic_id: UUID | str) -> bool:
        """Hard delete (CASCADE handles dependent products / prompts).

        Returns True iff a row was actually removed.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM geo_client_topics "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                topic_id,
            )
        return result.rsplit(" ", 1)[-1] != "0"

    @tenant_scoped
    async def existing_names_lower(
        self, client_id: str
    ) -> set[str]:
        """Return the lowercased names already taken by this client.

        Used by the bulk-import flow for case-insensitive dedup. Returning a
        set keeps the caller's loop O(1).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT topic_name FROM geo_client_topics WHERE client_id = $1",
                client_id,
            )
        return {(r["topic_name"] or "").strip().lower() for r in rows}
