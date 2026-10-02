"""
TopicProductRepository — DAL for ``geo_client_topic_products``.

This table holds three product roles, distinguished by ``product_role``:

  - ``own``                    : Tenant's own products under a topic. Reviewed
                                 rows may carry an explicit ``owner_brand_id``.
  - ``shadow_brand_product``   : Products tied to a Shadow brand. ``owner_brand_id``
                                 must point at a ``geo_client_brands`` row with
                                 ``is_shadow=true``. ``shadow_sub_role`` is
                                 ``'native'`` or ``'resale'``.
  - ``peer``                   : Competitor products. ``owner_peer_id`` must
                                 point at a ``geo_client_peers`` row.

Schema CHECK constraints enforce the role × owner consistency at the DB layer.
This repository only enforces the ``product_role`` enumeration; structural
consistency rules (which owner field is required for which role) are left to
the DB CHECK constraints to keep the repository thin.
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID, uuid4

from geo_common.db import tenant_scoped

from .base import BaseRepository

_PRODUCT_ROLES = ("own", "shadow_brand_product", "peer")
_SHADOW_SUB_ROLES = ("native", "resale")

_PRODUCT_COLS = (
    "id, topic_id, client_id, product_name, match_variants, "
    "product_role, shadow_sub_role, owner_brand_id, owner_peer_id, "
    "is_active, created_at, updated_at"
)


class TopicProductRepository(BaseRepository):
    """``geo_client_topic_products`` DAL."""

    @tenant_scoped
    async def list_for_topic(
        self,
        client_id: str,
        topic_id: UUID | str,
        *,
        product_role: str | None = "own",
        only_active: bool = True,
    ) -> list[dict[str, Any]]:
        """Products under one topic.

        Args:
            product_role: filter to one role. Default ``'own'`` matches the
                Topics page UI which shows only own products under a topic.
                Pass ``None`` to include every role under this topic.
            only_active: filter out soft-deleted (is_active=false) rows.
        """
        if product_role is not None and product_role not in _PRODUCT_ROLES:
            raise ValueError(
                f"product_role must be one of {_PRODUCT_ROLES} or None, "
                f"got {product_role!r}"
            )

        clauses = ["client_id = $1", "topic_id = $2"]
        params: list[Any] = [client_id, topic_id]
        if product_role is not None:
            clauses.append(f"product_role = ${len(params) + 1}")
            params.append(product_role)
        if only_active:
            clauses.append("is_active = true")

        sql = (
            f"SELECT {_PRODUCT_COLS} "
            "FROM geo_client_topic_products "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def list_own_names(
        self,
        client_id: str,
        topic_id: UUID | str,
    ) -> list[str]:
        """Convenience: just the product_name strings for ``product_role='own'``
        and ``is_active=true``.

        Used by routers that surface a flat product-name list (the legacy
        TEXT[]-style API on /clients endpoints).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT product_name FROM geo_client_topic_products "
                "WHERE client_id = $1 AND topic_id = $2 "
                "AND product_role = 'own' AND is_active = true "
                "ORDER BY created_at",
                client_id,
                topic_id,
            )
        return [r["product_name"] for r in rows]

    @tenant_scoped
    async def get_by_id(
        self, client_id: str, product_id: UUID | str
    ) -> dict[str, Any] | None:
        """Fetch one row regardless of role; tenant-scoped."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_PRODUCT_COLS} FROM geo_client_topic_products "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                product_id,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add_own_product(
        self,
        client_id: str,
        *,
        topic_id: UUID | str,
        product_name: str,
        match_variants: list[str] | None = None,
        owner_brand_id: UUID | str | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """INSERT a ``product_role='own'`` row.

        ``owner_brand_id`` records human-confirmed attribution. It remains
        optional here for legacy and bulk-import compatibility; interactive
        creation validates and requires it at the router boundary.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO geo_client_topic_products "
                "(id, topic_id, client_id, product_name, match_variants, "
                " product_role, owner_brand_id, is_active) "
                "VALUES ($1, $2, $3, $4, $5, 'own', $6, $7) "
                f"RETURNING {_PRODUCT_COLS}",
                uuid4(),
                topic_id,
                client_id,
                product_name,
                match_variants or [],
                owner_brand_id,
                is_active,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add_shadow_brand_product(
        self,
        client_id: str,
        *,
        topic_id: UUID | str,
        product_name: str,
        owner_brand_id: UUID | str,
        match_variants: list[str] | None = None,
        shadow_sub_role: str | None = None,
        owner_peer_id: UUID | str | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """INSERT a ``product_role='shadow_brand_product'`` row.

        ``owner_peer_id`` is allowed when ``shadow_sub_role='resale'`` to
        record the original peer manufacturer; ``owner_brand_id`` always
        points at the Shadow brand under which the product is sold.
        """
        if shadow_sub_role is not None and shadow_sub_role not in _SHADOW_SUB_ROLES:
            raise ValueError(
                f"shadow_sub_role must be one of {_SHADOW_SUB_ROLES} or None, "
                f"got {shadow_sub_role!r}"
            )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO geo_client_topic_products "
                "(id, topic_id, client_id, product_name, match_variants, "
                " product_role, shadow_sub_role, owner_brand_id, owner_peer_id, is_active) "
                "VALUES ($1, $2, $3, $4, $5, 'shadow_brand_product', $6, $7, $8, $9) "
                f"RETURNING {_PRODUCT_COLS}",
                uuid4(),
                topic_id,
                client_id,
                product_name,
                match_variants or [],
                shadow_sub_role,
                owner_brand_id,
                owner_peer_id,
                is_active,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add_peer_product(
        self,
        client_id: str,
        *,
        topic_id: UUID | str,
        product_name: str,
        owner_peer_id: UUID | str,
        match_variants: list[str] | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """INSERT a ``product_role='peer'`` row."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO geo_client_topic_products "
                "(id, topic_id, client_id, product_name, match_variants, "
                " product_role, owner_peer_id, is_active) "
                "VALUES ($1, $2, $3, $4, $5, 'peer', $6, $7) "
                f"RETURNING {_PRODUCT_COLS}",
                uuid4(),
                topic_id,
                client_id,
                product_name,
                match_variants or [],
                owner_peer_id,
                is_active,
            )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update(
        self,
        client_id: str,
        product_id: UUID | str,
        *,
        updates: dict[str, Any],
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Apply a whitelisted partial update.

        Args:
            updates: column → new value pairs. Only known columns are applied.
            scope: extra equality filters (e.g. ``{'topic_id': ..., 'product_role': 'own'}``)
                so callers can scope the update to a particular role/topic and
                avoid bleeding into another role.

        Returns the updated row, or None if no row matched. An empty
        ``updates`` dict refetches the (possibly scoped) existing row.
        """
        allowed = {
            "product_name",
            "match_variants",
            "shadow_sub_role",
            "owner_peer_id",
            "owner_brand_id",
            "topic_id",
            "is_active",
            "product_role",
        }
        clean = self._whitelist_updates(updates, allowed)

        clauses = ["client_id = $1", "id = $2"]
        params: list[Any] = [client_id, product_id]
        for col, val in (scope or {}).items():
            clauses.append(f"{col} = ${len(params) + 1}")
            params.append(val)
        where_sql = " AND ".join(clauses)

        async with self._pool.acquire() as conn:
            if not clean:
                row = await conn.fetchrow(
                    f"SELECT {_PRODUCT_COLS} "
                    "FROM geo_client_topic_products "
                    f"WHERE {where_sql}",
                    *params,
                )
            else:
                set_parts: list[str] = []
                for col, val in clean.items():
                    params.append(val)
                    set_parts.append(f"{col} = ${len(params)}")
                set_parts.append("updated_at = NOW()")
                row = await conn.fetchrow(
                    "UPDATE geo_client_topic_products "
                    f"SET {', '.join(set_parts)} "
                    f"WHERE {where_sql} "
                    f"RETURNING {_PRODUCT_COLS}",
                    *params,
                )
        return self._row_to_dict(row)

    @tenant_scoped
    async def replace_own_products(
        self,
        client_id: str,
        topic_id: UUID | str,
        product_names: Iterable[str],
    ) -> list[dict[str, Any]]:
        """Wipe-and-rewrite Own products for a topic.

        Mirrors the legacy TEXT[]-style PUT semantics: take a fresh list of
        product names, drop the existing Own rows for the topic, and insert
        the new set in one transaction. Empty / whitespace-only names are
        skipped silently.

        Returns the freshly written rows (in insertion order).
        """
        cleaned = [(n or "").strip() for n in product_names]
        cleaned = [n for n in cleaned if n]

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM geo_client_topic_products "
                    "WHERE client_id = $1 AND topic_id = $2 AND product_role = 'own'",
                    client_id,
                    topic_id,
                )
                inserted: list[dict[str, Any]] = []
                for name in cleaned:
                    row = await conn.fetchrow(
                        "INSERT INTO geo_client_topic_products "
                        "(id, topic_id, client_id, product_name, match_variants, product_role) "
                        "VALUES ($1, $2, $3, $4, $5, 'own') "
                        f"RETURNING {_PRODUCT_COLS}",
                        uuid4(),
                        topic_id,
                        client_id,
                        name,
                        [],
                    )
                    inserted.append(self._row_to_dict(row))
        return inserted

    @tenant_scoped
    async def remove_own_product_by_name(
        self,
        client_id: str,
        topic_id: UUID | str,
        product_name: str,
    ) -> bool:
        """Delete a single Own product matched by name. Returns True iff a
        row was removed."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM geo_client_topic_products "
                "WHERE client_id = $1 AND topic_id = $2 "
                "AND product_role = 'own' AND product_name = $3",
                client_id,
                topic_id,
                product_name,
            )
        return result.rsplit(" ", 1)[-1] != "0"

    @tenant_scoped
    async def delete_for_topic(
        self,
        client_id: str,
        topic_id: UUID | str,
        *,
        product_role: str | None = None,
    ) -> int:
        """Delete every product (optionally filtered by role) under a topic.

        Returns the number of rows deleted.
        """
        clauses = ["client_id = $1", "topic_id = $2"]
        params: list[Any] = [client_id, topic_id]
        if product_role is not None:
            if product_role not in _PRODUCT_ROLES:
                raise ValueError(
                    f"product_role must be one of {_PRODUCT_ROLES} or None, "
                    f"got {product_role!r}"
                )
            clauses.append(f"product_role = ${len(params) + 1}")
            params.append(product_role)
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM geo_client_topic_products "
                f"WHERE {' AND '.join(clauses)}",
                *params,
            )
        try:
            return int(result.rsplit(" ", 1)[-1])
        except ValueError:
            return 0

    @tenant_scoped
    async def delete_by_id(
        self,
        client_id: str,
        product_id: UUID | str,
        *,
        scope: dict[str, Any] | None = None,
    ) -> bool:
        """Delete one row by id. ``scope`` adds extra equality filters
        (e.g. ``{'product_role': 'own', 'owner_brand_id': brand_id}``) so the
        router can guard against deleting a row from another role bucket."""
        clauses = ["client_id = $1", "id = $2"]
        params: list[Any] = [client_id, product_id]
        for col, val in (scope or {}).items():
            clauses.append(f"{col} = ${len(params) + 1}")
            params.append(val)
        where_sql = " AND ".join(clauses)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                product = await conn.fetchrow(
                    "SELECT id FROM geo_client_topic_products "
                    f"WHERE {where_sql} FOR UPDATE",
                    *params,
                )
                if product is None:
                    return False

                # Historical citation facts remain valid after a product
                # configuration is removed. Detach only the optional product
                # classification before deleting the configuration row.
                # This application-level guard works before and after the DB
                # FK is migrated to ON DELETE SET NULL.
                await conn.execute(
                    "UPDATE geo_citations SET matched_product_id = NULL "
                    "WHERE client_id = $1 AND matched_product_id = $2",
                    client_id,
                    product_id,
                )
                result = await conn.execute(
                    "DELETE FROM geo_client_topic_products "
                    f"WHERE {where_sql}",
                    *params,
                )
        return result.rsplit(" ", 1)[-1] != "0"

    @tenant_scoped
    async def list_by_owner_brand(
        self,
        client_id: str,
        brand_id: UUID | str,
        *,
        product_role: str | None = "shadow_brand_product",
    ) -> list[dict[str, Any]]:
        """All products under a given owner brand id (default Shadow brand)."""
        clauses = ["client_id = $1", "owner_brand_id = $2"]
        params: list[Any] = [client_id, brand_id]
        if product_role is not None:
            clauses.append(f"product_role = ${len(params) + 1}")
            params.append(product_role)
        sql = (
            f"SELECT {_PRODUCT_COLS} FROM geo_client_topic_products "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def list_by_owner_peer(
        self,
        client_id: str,
        peer_id: UUID | str,
        *,
        product_role: str | None = "peer",
    ) -> list[dict[str, Any]]:
        """All products under a given owner peer id (default Peer products)."""
        clauses = ["client_id = $1", "owner_peer_id = $2"]
        params: list[Any] = [client_id, peer_id]
        if product_role is not None:
            clauses.append(f"product_role = ${len(params) + 1}")
            params.append(product_role)
        sql = (
            f"SELECT {_PRODUCT_COLS} FROM geo_client_topic_products "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return self._rows_to_dicts(rows)
