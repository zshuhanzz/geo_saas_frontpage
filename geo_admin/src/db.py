"""
``db`` — asyncpg-backed compatibility surface for geo_admin routers.

Phase 2.5b (2026-04-26): mirror of ``geo_saas/src/db.py``. Exposes a
``database`` singleton that provides the same ``fetch_all`` / ``fetch_one`` /
``execute`` / ``transaction`` API the routers used to call on the legacy
``databases.Database`` instance, but executes against an ``asyncpg.Pool``
underneath. Named ``:param`` placeholders in SQL strings are translated to
positional ``$N`` so router call sites barely change.

See ``geo_saas/src/db.py`` docstring for the full design rationale.
"""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Mapping, Optional, Sequence

import asyncpg

logger = logging.getLogger(__name__)


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://answer-x-geo-db-user:answer-x-geo-db-user-123@localhost:5432/answer-x-geo-db",
)


def _asyncpg_dsn() -> str:
    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


# Negative lookbehind ``(?<!:)`` skips the second colon in PostgreSQL
# ``::TYPE`` casts. Without it, ``WHERE created_at >= '2026-04-20'::date``
# would cause ``::date`` to look like a named parameter ``:date``, blowing
# up _named_to_positional with KeyError. Real named params always start
# with a single ``:`` (and the char before, if any, is whitespace, comma,
# or paren — never another ``:``). Mirrors the saas-side fix in
# ``geo_saas/src/db.py``.
_NAMED_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


def _named_to_positional(
    sql: str, params: Optional[Mapping[str, Any]] = None
) -> tuple[str, list[Any]]:
    """Rewrite ``:name`` placeholders into ``$N`` and order args accordingly.

    Repeated occurrences of the same name reuse the first slot. Returns the
    SQL untouched when no params dict is supplied.
    """
    if not params:
        return sql, []

    seen: dict[str, int] = {}
    args: list[Any] = []

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in seen:
            if name not in params:
                raise KeyError(
                    f"SQL references :{name} but no value supplied in params dict"
                )
            args.append(params[name])
            seen[name] = len(args)
        return f"${seen[name]}"

    new_sql = _NAMED_PARAM_RE.sub(_sub, sql)
    return new_sql, args


class _ConnectionWrapper:
    __slots__ = ("raw_connection",)

    def __init__(self, conn: asyncpg.Connection) -> None:
        self.raw_connection = conn


class _Database:
    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
        if self._pool is None:
            dsn = _asyncpg_dsn()
            parsed = urllib.parse.urlparse(dsn)
            logger.info(
                "[db] opening asyncpg pool host=%s db=%s",
                parsed.hostname,
                (parsed.path or "/").lstrip("/"),
            )
            self._pool = await asyncpg.create_pool(
                dsn, min_size=min_size, max_size=max_size
            )
        return self._pool

    async def disconnect(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("[db] asyncpg pool closed")

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError(
                "asyncpg pool not initialized — call await database.connect() first."
            )
        return self._pool

    async def fetch_all(
        self,
        query: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> list[asyncpg.Record]:
        sql, args = _named_to_positional(query, values)
        async with self.pool().acquire() as conn:
            return await conn.fetch(sql, *args)

    async def fetch_one(
        self,
        query: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> Optional[asyncpg.Record]:
        sql, args = _named_to_positional(query, values)
        async with self.pool().acquire() as conn:
            return await conn.fetchrow(sql, *args)

    async def fetch_val(
        self,
        query: str,
        values: Optional[Mapping[str, Any]] = None,
        column: int = 0,
    ) -> Any:
        sql, args = _named_to_positional(query, values)
        async with self.pool().acquire() as conn:
            return await conn.fetchval(sql, *args, column=column)

    async def execute(
        self,
        query: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> str:
        sql, args = _named_to_positional(query, values)
        async with self.pool().acquire() as conn:
            return await conn.execute(sql, *args)

    async def execute_many(
        self,
        query: str,
        values: Sequence[Mapping[str, Any]],
    ) -> None:
        if not values:
            return
        async with self.pool().acquire() as conn:
            for row in values:
                sql, args = _named_to_positional(query, row)
                await conn.execute(sql, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        async with self.pool().acquire() as conn:
            async with conn.transaction():
                yield conn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_ConnectionWrapper]:
        async with self.pool().acquire() as conn:
            yield _ConnectionWrapper(conn)


database = _Database()


__all__ = ["DATABASE_URL", "database", "_named_to_positional"]
