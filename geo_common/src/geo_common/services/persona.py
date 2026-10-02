"""
PersonaRepository — DAL for ``geo_client_personas``.

Personas describe buyer/audience archetypes attached to a client. Schema:

    id UUID PK,
    client_id UUID FK,
    persona_name TEXT,
    persona_description TEXT NULL,
    created_at TIMESTAMP
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from geo_common.db import tenant_scoped

from .base import BaseRepository

_PERSONA_COLS = "id, client_id, persona_name, persona_description, created_at"


class PersonaRepository(BaseRepository):
    """``geo_client_personas`` DAL."""

    @tenant_scoped
    async def list_for_client(self, client_id: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_PERSONA_COLS} FROM geo_client_personas "
                "WHERE client_id = $1 ORDER BY created_at",
                client_id,
            )
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def get_by_id(
        self, client_id: str, persona_id: UUID | str
    ) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_PERSONA_COLS} FROM geo_client_personas "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                persona_id,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add(
        self,
        client_id: str,
        *,
        persona_name: str,
        persona_description: str | None = None,
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO geo_client_personas "
                "(id, client_id, persona_name, persona_description) "
                "VALUES ($1, $2, $3, $4) "
                f"RETURNING {_PERSONA_COLS}",
                uuid4(),
                client_id,
                persona_name,
                persona_description,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update(
        self,
        client_id: str,
        persona_id: UUID | str,
        *,
        persona_name: str | None = None,
        persona_description: str | None = None,
    ) -> dict[str, Any] | None:
        sets: list[str] = []
        params: list[Any] = [client_id, persona_id]
        if persona_name is not None:
            sets.append(f"persona_name = ${len(params) + 1}")
            params.append(persona_name)
        if persona_description is not None:
            sets.append(f"persona_description = ${len(params) + 1}")
            params.append(persona_description)
        async with self._pool.acquire() as conn:
            if not sets:
                row = await conn.fetchrow(
                    f"SELECT {_PERSONA_COLS} FROM geo_client_personas "
                    "WHERE client_id = $1 AND id = $2",
                    client_id,
                    persona_id,
                )
            else:
                row = await conn.fetchrow(
                    "UPDATE geo_client_personas "
                    f"SET {', '.join(sets)} "
                    "WHERE client_id = $1 AND id = $2 "
                    f"RETURNING {_PERSONA_COLS}",
                    *params,
                )
        return self._row_to_dict(row)

    @tenant_scoped
    async def delete(self, client_id: str, persona_id: UUID | str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM geo_client_personas "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                persona_id,
            )
        return result.rsplit(" ", 1)[-1] != "0"
