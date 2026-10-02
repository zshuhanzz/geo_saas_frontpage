"""No-DDL concurrency fence for Workspace-owned writes and final deletion.

Lock order is global Workspace-delete single-flight (Admin only), then the
tenant lifecycle advisory lock, then narrower subsystem locks such as
``prompt-write:{client_id}``. Short writers take the shared lifecycle lock
for their transaction. Final deletion takes the exclusive form before its
authoritative readiness pass. Long Agent/Analyzer workflows hold the shared
session form so library-owned or multi-transaction writes (LangGraph
checkpoints included) remain inside the same deletion fence.

The existence check deliberately runs *after* lock acquisition. A writer
that arrives while final deletion owns the exclusive lock fails fast, releases
its pool connection, and cannot form a connection-pool convoy behind deletion.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from geo_common.db import tenant_scoped

from .base import BaseRepository


ResultT = TypeVar("ResultT")


class WorkspaceLifecycleMissing(RuntimeError):
    """Raised when a guarded writer targets a deleted Workspace."""


class WorkspaceLifecycleBusy(RuntimeError):
    """Raised when final deletion currently owns the Workspace lifecycle fence."""


class WorkspaceLifecycleSessionLimiter:
    """Bound long lifecycle sessions before they acquire a pool connection."""

    def __init__(
        self,
        env_name: str,
        *,
        default: int,
        pool_capacity: int,
    ) -> None:
        safe_max = max(1, pool_capacity // 2)
        try:
            configured = int(os.environ.get(env_name, str(default)))
        except ValueError:
            configured = default
        self.limit = max(1, min(configured, safe_max))
        self._slots = asyncio.BoundedSemaphore(self.limit)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Reserve bounded capacity before acquiring a database connection."""
        await self._slots.acquire()
        try:
            yield
        finally:
            self._slots.release()

    @asynccontextmanager
    async def session(self, pool, client_id: str) -> AsyncIterator[Any]:
        async with self.slot():
            async with workspace_lifecycle_session(pool, client_id) as conn:
                yield conn


def workspace_lifecycle_lock_key(client_id: str) -> str:
    return f"workspace-lifecycle:{client_id}"


async def _require_workspace_exists(conn, client_id: str) -> None:
    exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM geo_clients WHERE id = $1::uuid)",
        str(client_id),
    )
    if not exists:
        raise WorkspaceLifecycleMissing(f"Workspace {client_id} does not exist")


async def acquire_workspace_lifecycle_shared(conn, client_id: str) -> None:
    """Take the shared lifecycle guard without waiting behind final deletion."""
    acquired = await conn.fetchval(
        "SELECT pg_try_advisory_xact_lock_shared(hashtextextended($1, 0))",
        workspace_lifecycle_lock_key(str(client_id)),
    )
    if not acquired:
        raise WorkspaceLifecycleBusy(
            f"Workspace {client_id} final deletion is in progress"
        )
    await _require_workspace_exists(conn, str(client_id))


async def acquire_workspace_lifecycle_exclusive(conn, client_id: str) -> None:
    """Take the transaction-scoped exclusive final-deletion fence."""
    await conn.fetchval(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        workspace_lifecycle_lock_key(str(client_id)),
    )
    await _require_workspace_exists(conn, str(client_id))


async def try_acquire_workspace_lifecycle_exclusive(conn, client_id: str) -> bool:
    """Try to fence a Workspace for a consistent readiness snapshot.

    The lock, when acquired, is transaction scoped and releases on commit or
    rollback. ``False`` means an active guarded writer/workflow owns a shared
    lifecycle lock.
    """
    acquired = await conn.fetchval(
        "SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))",
        workspace_lifecycle_lock_key(str(client_id)),
    )
    return bool(acquired)


class WorkspaceWriteCoordinator(BaseRepository):
    """Run a short Workspace mutation under one guarded transaction."""

    @tenant_scoped
    async def execute(
        self,
        client_id: str,
        operation: Callable[[Any], Awaitable[ResultT]],
    ) -> ResultT:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await acquire_workspace_lifecycle_shared(conn, client_id)
                return await operation(conn)


@asynccontextmanager
async def workspace_lifecycle_session(pool, client_id: str) -> AsyncIterator[Any]:
    """Hold a shared session lock across a long multi-transaction workflow."""
    async with pool.acquire() as conn:
        acquired = False
        try:
            await acquire_workspace_lifecycle_session_shared(conn, str(client_id))
            acquired = True
            yield conn
        finally:
            if acquired:
                await release_workspace_lifecycle_session_shared(conn, str(client_id))


async def acquire_workspace_lifecycle_session_shared(conn, client_id: str) -> None:
    """Try a shared session fence and verify the Workspace under it."""
    key = workspace_lifecycle_lock_key(str(client_id))
    try:
        # Include the lock round trip in the cancellation cleanup region. The
        # server may have acquired the session lock just before the client sees
        # cancellation; an unconditional unlock attempt safely covers both
        # that case and cancellation while waiting behind an exclusive lock.
        acquired = await conn.fetchval(
            "SELECT pg_try_advisory_lock_shared(hashtextextended($1, 0))",
            key,
        )
    except BaseException:
        await release_workspace_lifecycle_session_shared(
            conn,
            str(client_id),
            require_owned=False,
        )
        raise
    if not acquired:
        raise WorkspaceLifecycleBusy(
            f"Workspace {client_id} final deletion is in progress"
        )
    try:
        await _require_workspace_exists(conn, str(client_id))
    except BaseException:
        await release_workspace_lifecycle_session_shared(
            conn,
            str(client_id),
            require_owned=False,
        )
        raise


async def release_workspace_lifecycle_session_shared(
    conn,
    client_id: str,
    *,
    require_owned: bool = True,
) -> None:
    """Release a shared session fence, even when its workflow is cancelled.

    A leaked session advisory lock can survive transaction rollback and poison
    a pooled connection. Shield the unlock so request cancellation cannot
    return that connection to the pool while it still owns the lifecycle lock.
    """
    unlock_task = asyncio.create_task(
        conn.fetchval(
            "SELECT pg_advisory_unlock_shared(hashtextextended($1, 0))",
            workspace_lifecycle_lock_key(str(client_id)),
        )
    )
    try:
        unlocked = await asyncio.shield(unlock_task)
    except asyncio.CancelledError:
        # ``shield`` keeps the unlock running but raises immediately to its
        # caller. Wait for the database round trip before the surrounding pool
        # context can return this connection for reuse, then preserve the
        # original cancellation.
        unlocked = await unlock_task
        raise
    if require_owned and unlocked is False:
        raise RuntimeError(
            f"Connection did not own Workspace lifecycle lock for {client_id}"
        )
