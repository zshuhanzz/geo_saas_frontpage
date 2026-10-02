"""
asyncpg pool wiring for geo_saas — Phase 2.5b unified.

Single pool across the whole module: ``db.database`` owns the
``asyncpg.Pool`` and this file just exposes the FastAPI dependency
helpers (``open_pool`` / ``close_pool`` / ``get_pool``) that the
Repository-style routers expect.

Before Phase 2.5b two pools coexisted (legacy ``databases`` lib + asyncpg).
After Phase 2.5b the legacy ``databases`` lib is gone and the single pool
backs both raw-SQL routers (via ``db.database``) and the
``geo_common.services.*Repository`` callsites that take a pool dep.
"""

from __future__ import annotations

import logging

import asyncpg
from fastapi import Request

from db import database

logger = logging.getLogger(__name__)


async def open_pool() -> asyncpg.Pool:
    """Initialize the shared asyncpg pool (idempotent).

    Called once from ``main.lifespan``. The pool is owned by the ``database``
    singleton in ``db``; this helper just unwraps it so the lifespan can
    stash it on ``app.state.pg_pool`` for the FastAPI dependency.
    """
    return await database.connect()


async def close_pool(pool: asyncpg.Pool | None) -> None:
    """Close the shared pool. ``pool`` arg is accepted for backwards
    compatibility with ``main.lifespan``; the actual close happens through
    the ``database`` singleton so other modules holding references release
    cleanly.
    """
    await database.disconnect()


def get_pool(request: Request) -> asyncpg.Pool:
    """FastAPI dependency — returns the shared asyncpg pool.

    Falls back to the module-level ``database`` singleton if ``app.state``
    wasn't populated, which keeps test setups simple.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        if not database.is_connected:
            raise RuntimeError(
                "asyncpg pool not initialized — "
                "FastAPI lifespan didn't run open_pool()"
            )
        return database.pool()
    return pool
