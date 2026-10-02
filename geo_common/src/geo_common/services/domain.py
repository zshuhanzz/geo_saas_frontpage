"""
DomainRepository — DAL for ``geo_client_domains``.

Each row registers a host the client cares about. Schema (post-v1.2):

    id UUID PK,
    client_id UUID FK,
    domain TEXT,
    is_primary BOOLEAN default false,
    domain_scope TEXT default 'whole'      -- 'whole' | 'path-prefix'
    brand_id UUID NULL FK,                  -- mutually exclusive with peer_id
    peer_id  UUID NULL FK,                  -- (DB CHECK enforces it)
    created_at TIMESTAMP

Owner exclusivity (brand_id XOR peer_id) is enforced by the
``domain_owner_exclusive`` CHECK constraint at the DB level. The repository
DELIBERATELY does NOT enforce it — that's a router-layer concern, where the
router can return a friendly 422. This keeps this layer thin and lets bulk
flows (e.g. auto-discovery) bypass per-row validation.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from geo_common.db import tenant_scoped

from .base import BaseRepository

_DOMAIN_COLS = (
    "id, client_id, domain, is_primary, domain_scope, "
    "brand_id, peer_id, created_at"
)


class DomainRepository(BaseRepository):
    """``geo_client_domains`` DAL."""

    @tenant_scoped
    async def list_for_client(
        self,
        client_id: str,
        *,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Every domain for a client. ``scope`` optionally filters by
        ``domain_scope`` (e.g. ``'whole'`` for full-host matches only)."""
        clauses = ["client_id = $1"]
        params: list[Any] = [client_id]
        if scope is not None:
            clauses.append(f"domain_scope = ${len(params) + 1}")
            params.append(scope)
        sql = (
            f"SELECT {_DOMAIN_COLS} FROM geo_client_domains "
            f"WHERE {' AND '.join(clauses)} ORDER BY created_at"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def get_by_id(
        self, client_id: str, domain_id: UUID | str
    ) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_DOMAIN_COLS} FROM geo_client_domains "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                domain_id,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def get_by_domain(
        self, client_id: str, domain: str
    ) -> dict[str, Any] | None:
        """Fetch by exact domain string. Used by routers to detect
        duplicates before insert."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_DOMAIN_COLS} FROM geo_client_domains "
                "WHERE client_id = $1 AND domain = $2",
                client_id,
                domain,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add(
        self,
        client_id: str,
        *,
        domain: str,
        is_primary: bool = False,
        domain_scope: str = "whole",
        brand_id: UUID | str | None = None,
        peer_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """INSERT a domain row.

        Owner exclusivity is enforced by the DB CHECK constraint
        ``domain_owner_exclusive`` — the repository accepts both args and
        relies on the DB to reject ``brand_id != NULL AND peer_id != NULL``.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO geo_client_domains "
                "(id, client_id, domain, is_primary, domain_scope, brand_id, peer_id) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) "
                f"RETURNING {_DOMAIN_COLS}",
                uuid4(),
                client_id,
                domain,
                is_primary,
                domain_scope,
                brand_id,
                peer_id,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update(
        self,
        client_id: str,
        domain_id: UUID | str,
        *,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Apply a whitelisted partial update.

        Empty ``updates`` refetches the existing row (matches the router's
        no-op semantics)."""
        allowed = {"domain", "is_primary", "domain_scope", "brand_id", "peer_id"}
        # exclude_unset patches typically arrive without ``None`` filtering, so
        # use whitelist (which strips None) here too.
        clean = self._whitelist_updates(updates, allowed)

        async with self._pool.acquire() as conn:
            if not clean:
                row = await conn.fetchrow(
                    f"SELECT {_DOMAIN_COLS} FROM geo_client_domains "
                    "WHERE client_id = $1 AND id = $2",
                    client_id,
                    domain_id,
                )
            else:
                params: list[Any] = [client_id, domain_id]
                set_parts: list[str] = []
                for col, val in clean.items():
                    params.append(val)
                    set_parts.append(f"{col} = ${len(params)}")
                row = await conn.fetchrow(
                    "UPDATE geo_client_domains "
                    f"SET {', '.join(set_parts)} "
                    "WHERE client_id = $1 AND id = $2 "
                    f"RETURNING {_DOMAIN_COLS}",
                    *params,
                )
        return self._row_to_dict(row)

    @tenant_scoped
    async def delete(self, client_id: str, domain_id: UUID | str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM geo_client_domains "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                domain_id,
            )
        return result.rsplit(" ", 1)[-1] != "0"

    @tenant_scoped
    async def domain_owner_map(
        self,
        client_id: str,
        *,
        scope: str = "whole",
    ) -> dict[str, tuple[Any, Any]]:
        """Build a host → (brand_id, peer_id) map for fast URL-ownership
        inference.

        Returned host strings are lowercased and stripped of any leading
        ``www.`` so ``_normalize_host(url)`` lookups hit. Used by the bulk
        topic-import flow and the per-URL ``_infer_url_owner`` helper.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT domain, brand_id, peer_id FROM geo_client_domains "
                "WHERE client_id = $1 AND domain_scope = $2",
                client_id,
                scope,
            )
        out: dict[str, tuple[Any, Any]] = {}
        for r in rows:
            host = (r["domain"] or "").strip().lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                out[host] = (r["brand_id"], r["peer_id"])
        return out
