"""Shared serialization boundary for tenant-scoped Prompt writes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from geo_common.db import tenant_scoped

from .base import BaseRepository
from .workspace_lifecycle import acquire_workspace_lifecycle_shared


ResultT = TypeVar("ResultT")


class PromptWriteCoordinator(BaseRepository):
    """Run a Prompt mutation under one tenant lock and one DB transaction.

    Every Prompt creation surface must use this coordinator so quota,
    ownership, allowlist, duplicate checks, and persistence observe one
    serialized tenant state without nested transactions.
    """

    @tenant_scoped
    async def execute(
        self,
        client_id: str,
        operation: Callable[[Any], Awaitable[ResultT]],
        *,
        transaction_setup: Callable[[Any], Awaitable[None]] | None = None,
    ) -> ResultT:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if transaction_setup is not None:
                    await transaction_setup(conn)
                # Lock order: Workspace lifecycle guard before narrower
                # Prompt serialization. Final Workspace deletion follows the
                # same order with the exclusive lifecycle fence.
                await acquire_workspace_lifecycle_shared(conn, client_id)
                await conn.fetchval(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    f"prompt-write:{client_id}",
                )
                return await operation(conn)
