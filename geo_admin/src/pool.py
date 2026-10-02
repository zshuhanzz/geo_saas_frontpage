"""
asyncpg pool wiring for geo_admin — Phase 2.5b unified.

Mirror of ``geo_saas/src/pool.py``: a single asyncpg pool owned by
``db.database`` backs both raw-SQL routers and the
``geo_common.services.*Repository`` callsites that take a pool dep.
"""

from __future__ import annotations

import logging

import asyncpg
from fastapi import Request

from db import database

logger = logging.getLogger(__name__)


async def open_pool() -> asyncpg.Pool:
    """Initialize and return the shared asyncpg pool (idempotent)."""
    return await database.connect()


async def close_pool(pool: asyncpg.Pool | None) -> None:
    """Close the shared pool. ``pool`` arg accepted for lifespan back-compat."""
    await database.disconnect()


def get_pool(request: Request) -> asyncpg.Pool:
    """FastAPI dependency — returns the shared asyncpg pool."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        if not database.is_connected:
            raise RuntimeError(
                "asyncpg pool not initialized — "
                "FastAPI lifespan didn't run open_pool()"
            )
        return database.pool()
    return pool
