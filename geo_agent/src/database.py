"""
Database module for geo_agent.

Uses raw asyncpg pool (not SQLAlchemy) for direct SQL execution.
Shares Cloud SQL with geo_saas — same database, separate connection pool.
"""
import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from geo_common.services import workspace_lifecycle_session

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


def _lifecycle_concurrency_limit() -> int:
    """Leave capacity for writes performed by guarded Agent workflows."""
    raw = os.environ.get("AGENT_WORKSPACE_LIFECYCLE_MAX_CONCURRENCY", "4")
    try:
        configured = int(raw)
    except ValueError:
        configured = 4
    # The Agent pool has ten connections. Capping lifecycle sessions at five
    # guarantees at least half remain available to graph tools and persistence.
    return max(1, min(configured, 5))


_workspace_lifecycle_slots = asyncio.BoundedSemaphore(_lifecycle_concurrency_limit())


def _build_dsn() -> str:
    """Build PostgreSQL DSN from environment variables.

    For Cloud Run: uses CLOUD_SQL_INSTANCE → Unix socket.
    For local dev: falls back to hardcoded default (same as geo_saas/geo_admin).
    """
    # Cloud SQL Unix socket support (production)
    instance = os.environ.get("CLOUD_SQL_INSTANCE")
    if instance:
        socket_dir = os.environ.get("DB_SOCKET_DIR", "/cloudsql")
        user = os.environ.get("DB_USER", "answer-x-geo-db-user")
        password = os.environ.get("DB_PASSWORD", "")
        dbname = os.environ.get("DB_NAME", "answer-x-geo-db")
        host = f"{socket_dir}/{instance}"
        return f"postgresql://{user}:{password}@/{dbname}?host={host}"

    # Local dev default (matches geo_saas & geo_admin)
    return "postgresql://answer-x-geo-db-user:answer-x-geo-db-user-123@localhost:5432/answer-x-geo-db"


async def get_pool() -> asyncpg.Pool:
    """Get or create the asyncpg connection pool (singleton)."""
    global _pool
    if _pool is None:
        dsn = os.environ.get("DATABASE_URL") or _build_dsn()
        # Strip SQLAlchemy driver prefix if present
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        logger.info("[DB] Creating asyncpg pool...")
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        logger.info("[DB] Pool created.")
    return _pool


async def reserve_workspace_lifecycle_slot() -> None:
    """Reserve one of the bounded long-workflow lifecycle connections."""
    await _workspace_lifecycle_slots.acquire()


def release_workspace_lifecycle_slot() -> None:
    """Release a lifecycle connection reservation."""
    _workspace_lifecycle_slots.release()


@asynccontextmanager
async def agent_workspace_lifecycle_session(client_id: str) -> AsyncIterator[asyncpg.Connection]:
    """Fence a long Agent workflow without exhausting its connection pool."""
    await reserve_workspace_lifecycle_slot()
    try:
        pool = await get_pool()
        async with workspace_lifecycle_session(pool, client_id) as conn:
            yield conn
    finally:
        release_workspace_lifecycle_slot()


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("[DB] Pool closed.")
