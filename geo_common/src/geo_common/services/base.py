"""
BaseRepository — shared scaffolding for every domain repository.

Design choices:
    - Repositories take an ``asyncpg.Pool`` at construction. They do NOT
      reach for a global ``database`` object — keeps the layer testable
      and module-agnostic.
    - Every method that scopes by tenant takes ``client_id`` as the first
      positional arg and is decorated with ``@tenant_scoped`` (re-exported
      via ``geo_common.db``). Skipping the decorator is a P0 violation.
    - Methods return plain ``dict`` rows (``asyncpg.Record._asdict()``-style)
      rather than ORM objects. Pydantic ``response_model=`` at the router
      boundary handles serialization. This avoids forcing modules to import
      a shared ORM layer.

Usage::

    from geo_common.services import BrandRepository

    brands = BrandRepository(pool)
    rows = await brands.list_for_client(client_id, include_shadow=True)
"""

from __future__ import annotations

from typing import Any, Mapping

import asyncpg


class BaseRepository:
    """Common pool-injection + cursor helpers."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @property
    def pool(self) -> asyncpg.Pool:
        return self._pool

    @staticmethod
    def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
        """Convert an ``asyncpg.Record`` to ``dict`` (or ``None``).

        ``asyncpg.Record`` is dict-like but isn't a real dict — JSON
        serialization, deep equality checks, and Pydantic validation
        all want a real dict. Centralize the conversion here.
        """
        if row is None:
            return None
        return dict(row)

    @staticmethod
    def _rows_to_dicts(rows: list[asyncpg.Record]) -> list[dict[str, Any]]:
        return [dict(r) for r in rows]

    @staticmethod
    def _whitelist_updates(
        data: Mapping[str, Any], allowed: set[str]
    ) -> dict[str, Any]:
        """Filter a partial-update dict to allowed columns only.

        Defense-in-depth against a malformed Pydantic model leaking unknown
        keys into a dynamic ``UPDATE`` statement. Repositories should always
        funnel partial updates through this helper.
        """
        return {
            k: v for k, v in data.items() if k in allowed and v is not None
        }
