"""
BrandRepository — DAL for ``geo_client_brands`` (Own + Shadow brand union).

This is the **reference implementation** for the Phase 4 repository pattern.
Read this file before adding new repositories to keep the conventions
consistent.

Conventions demonstrated here:
    - Every public method is ``async``.
    - Every method that scopes by tenant takes ``client_id`` as its first
      positional arg AND is decorated with ``@tenant_scoped``.
    - SQL is parameterized — never use f-strings or ``.format()`` to inject
      values. asyncpg uses ``$1, $2, ...`` placeholders.
    - Methods return plain ``dict`` rows; the router layer handles Pydantic
      serialization via ``response_model=``.
    - Mutation methods return the row that was written / updated, never just
      ``None`` — saves the caller a round-trip when echo-ing the result.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from geo_common.db import tenant_scoped

from .base import BaseRepository


def _normalize_aliases(aliases: list[str]) -> list[str]:
    """Return non-empty, case-insensitively unique aliases in input order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in aliases:
        alias = value.strip()
        canonical = alias.casefold()
        if not alias or canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(alias)
    return normalized


class BrandRepository(BaseRepository):
    """``geo_client_brands`` DAL — Own + Shadow brand reads/writes."""

    @tenant_scoped
    async def list_for_client(
        self,
        client_id: str,
        *,
        include_shadow: bool = True,
        only_active: bool = True,
    ) -> list[dict[str, Any]]:
        """All brands for a client.

        Args:
            include_shadow: when ``False`` returns only Own brands
                (``is_shadow=false``). Default ``True`` matches the SaaS
                Brand Settings UI which shows both.
            only_active: when ``True`` filters out soft-deleted (``is_active=false``)
                rows. Default ``True``.
        """
        clauses = ["client_id = $1"]
        params: list[Any] = [client_id]
        if not include_shadow:
            clauses.append("is_shadow = false")
        if only_active:
            clauses.append("is_active = true")
        sql = (
            "SELECT id, client_id, brand_name, aliases, is_shadow, is_active, "
            "created_at, updated_at "
            "FROM geo_client_brands "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY is_shadow ASC, brand_name ASC"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def get_by_id(
        self, client_id: str, brand_id: UUID | str
    ) -> dict[str, Any] | None:
        """Fetch a single brand. Tenant-scoped — cross-tenant lookups return None."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, client_id, brand_name, aliases, is_shadow, is_active, "
                "created_at, updated_at "
                "FROM geo_client_brands "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                brand_id,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add(
        self,
        client_id: str,
        *,
        brand_name: str,
        aliases: list[str] | None = None,
        is_shadow: bool = False,
    ) -> dict[str, Any]:
        """INSERT a new brand and return the persisted row.

        Caller is responsible for de-duplication if needed; the unique
        constraint ``uq_geo_client_brands_client_name`` will raise on collision.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO geo_client_brands "
                "(client_id, brand_name, aliases, is_shadow) "
                "VALUES ($1, $2, $3, $4) "
                "RETURNING id, client_id, brand_name, aliases, is_shadow, "
                "is_active, created_at, updated_at",
                client_id,
                brand_name,
                aliases or [],
                is_shadow,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update_aliases(
        self,
        client_id: str,
        brand_id: UUID | str,
        aliases: list[str],
    ) -> dict[str, Any] | None:
        """Replace the aliases array. Returns the updated row, or None if not found."""
        async with self._pool.acquire() as conn:
            return await self.update_aliases_on_connection(
                client_id,
                brand_id,
                aliases,
                conn=conn,
            )

    @tenant_scoped
    async def update_aliases_on_connection(
        self,
        client_id: str,
        brand_id: UUID | str,
        aliases: list[str],
        *,
        conn: Any,
    ) -> dict[str, Any] | None:
        """Replace aliases using a caller-owned transaction connection."""
        clean_aliases = _normalize_aliases(aliases)
        row = await conn.fetchrow(
            "UPDATE geo_client_brands "
            "SET aliases = $3, updated_at = NOW() "
            "WHERE client_id = $1 AND id = $2 "
            "RETURNING id, client_id, brand_name, aliases, is_shadow, "
            "is_active, created_at, updated_at",
            client_id,
            brand_id,
            clean_aliases,
        )
        return self._row_to_dict(row)

    @tenant_scoped
    async def soft_delete(
        self, client_id: str, brand_id: UUID | str
    ) -> bool:
        """Mark inactive (``is_active=false``). Returns True if a row was changed."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE geo_client_brands "
                "SET is_active = false, updated_at = NOW() "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                brand_id,
            )
        # asyncpg returns "UPDATE <n>" — n>0 means a row was matched.
        return result.rsplit(" ", 1)[-1] != "0"
