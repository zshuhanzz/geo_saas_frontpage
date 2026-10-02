"""
PeerRepository — DAL for ``geo_client_peers``.

A Peer is a competitor brand the tenant is tracked against. Schema:

    id UUID PK,
    client_id UUID FK,
    primary_name TEXT,
    aliases TEXT[] default {},
    created_at TIMESTAMP

Peer products are stored in ``geo_client_topic_products`` with
``product_role='peer'`` — see ``TopicProductRepository`` for that surface.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from geo_common.db import tenant_scoped

from .base import BaseRepository

_PEER_COLS = "id, client_id, primary_name, aliases, created_at"


class PeerRepository(BaseRepository):
    """``geo_client_peers`` DAL."""

    @tenant_scoped
    async def list_for_client(self, client_id: str) -> list[dict[str, Any]]:
        """Every peer for a client, ordered by creation time."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_PEER_COLS} FROM geo_client_peers "
                "WHERE client_id = $1 ORDER BY created_at",
                client_id,
            )
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def get_by_id(
        self, client_id: str, peer_id: UUID | str
    ) -> dict[str, Any] | None:
        """Fetch a single peer; tenant-scoped."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_PEER_COLS} FROM geo_client_peers "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                peer_id,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def get_by_name(
        self, client_id: str, primary_name: str
    ) -> dict[str, Any] | None:
        """Fetch by exact ``primary_name``. Used by routers to detect duplicates
        before insert."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_PEER_COLS} FROM geo_client_peers "
                "WHERE client_id = $1 AND primary_name = $2",
                client_id,
                primary_name,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add(
        self,
        client_id: str,
        *,
        primary_name: str,
        aliases: list[str] | None = None,
    ) -> dict[str, Any]:
        """INSERT a peer and return the persisted row."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO geo_client_peers (id, client_id, primary_name, aliases) "
                "VALUES ($1, $2, $3, $4) "
                f"RETURNING {_PEER_COLS}",
                uuid4(),
                client_id,
                primary_name,
                aliases or [],
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update(
        self,
        client_id: str,
        peer_id: UUID | str,
        *,
        primary_name: str | None = None,
        aliases: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Partial update. An empty patch refetches the existing row, matching
        the router's no-op semantics."""
        sets: list[str] = []
        params: list[Any] = [client_id, peer_id]
        if primary_name is not None:
            sets.append(f"primary_name = ${len(params) + 1}")
            params.append(primary_name)
        if aliases is not None:
            sets.append(f"aliases = ${len(params) + 1}")
            params.append(aliases)

        async with self._pool.acquire() as conn:
            if not sets:
                row = await conn.fetchrow(
                    f"SELECT {_PEER_COLS} FROM geo_client_peers "
                    "WHERE client_id = $1 AND id = $2",
                    client_id,
                    peer_id,
                )
            else:
                row = await conn.fetchrow(
                    "UPDATE geo_client_peers "
                    f"SET {', '.join(sets)} "
                    "WHERE client_id = $1 AND id = $2 "
                    f"RETURNING {_PEER_COLS}",
                    *params,
                )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update_aliases(
        self,
        client_id: str,
        peer_id: UUID | str,
        aliases: list[str],
    ) -> dict[str, Any] | None:
        """Replace just the aliases array — mirrors BrandRepository.update_aliases."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE geo_client_peers SET aliases = $3 "
                "WHERE client_id = $1 AND id = $2 "
                f"RETURNING {_PEER_COLS}",
                client_id,
                peer_id,
                aliases,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def delete(self, client_id: str, peer_id: UUID | str) -> bool:
        """Hard delete (CASCADE removes dependent products / domains).
        Returns True iff a row was actually removed."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM geo_client_peers WHERE client_id = $1 AND id = $2",
                client_id,
                peer_id,
            )
        return result.rsplit(" ", 1)[-1] != "0"
