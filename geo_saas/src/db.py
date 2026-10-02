"""
``db`` — asyncpg-backed compatibility surface for geo_saas routers.

Phase 2.5b (2026-04-26): replaces the legacy ``databases`` lib + SQLAlchemy
table-object query path. Every router now interacts with the database through
either:

  * The ``geo_common.services.*Repository`` classes (preferred, for queries
    that already match a Repository surface), OR
  * The ``database`` adapter exported here, which executes **raw SQL strings**
    against the shared ``asyncpg.Pool``.

The adapter intentionally mimics the small subset of the ``databases.Database``
API that routers used (``fetch_all``, ``fetch_one``, ``fetch_val``,
``execute``, ``execute_many``, ``transaction``, ``connection``). This keeps
the migration mechanical: replace ``select(geo_clients).where(...)`` with a
raw SQL string carrying ``:name`` placeholders, and the call site stays
otherwise identical.

Named-parameter handling
------------------------

asyncpg accepts only positional ``$1, $2, ...`` placeholders. Routers
historically passed ``{"client_id": cid}`` style dicts. The adapter rewrites
``:name`` occurrences in SQL into the matching ``$N`` slots and orders the
positional argument list to match. This shim lives in
:func:`_named_to_positional` and is the only place where rewriting happens.

Pool lifecycle
--------------

The pool is created from ``DATABASE_URL`` once at module import time on first
``connect()``. ``main.lifespan`` calls ``await database.connect()`` /
``await database.disconnect()`` so the lifecycle exactly mirrors the previous
``databases`` lib usage.

The adapter also exposes a module-level ``pool()`` accessor so the legacy
``geo_common`` Repository wiring can keep using the same connection pool
without standing up a second one.
"""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Iterable, Mapping, Optional, Sequence

import asyncpg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DSN
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://answer-x-geo-db-user:answer-x-geo-db-user-123@localhost:5432/answer-x-geo-db",
)


def _asyncpg_dsn() -> str:
    """Strip the SQLAlchemy ``+asyncpg`` driver suffix that asyncpg won't accept."""
    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


# ---------------------------------------------------------------------------
# Named -> positional parameter rewrite
# ---------------------------------------------------------------------------

# Negative lookbehind ``(?<!:)`` skips the second colon in PostgreSQL
# ``::TYPE`` casts. Without it, ``WHERE created_at >= '2026-04-20'::date``
# would cause ``::date`` to look like a named parameter ``:date``, blowing
# up _named_to_positional with KeyError. Real named params always start
# with a single ``:`` (and the char before, if any, is whitespace, comma,
# or paren — never another ``:``).
_NAMED_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


def _named_to_positional(
    sql: str, params: Optional[Mapping[str, Any]] = None
) -> tuple[str, list[Any]]:
    """Translate ``:name`` placeholders into ``$N`` and return ordered args.

    Each unique name is assigned a positional slot the first time it appears;
    subsequent occurrences of the same name reuse that slot — matching
    asyncpg's "$1 referenced twice is the same value" semantics.

    If ``params`` is None or empty, returns the SQL untouched. SQL strings
    that already use ``$1, $2`` positional syntax are also returned untouched
    when no named placeholders are present.
    """
    if not params:
        # Nothing to substitute. Caller may still pass positional args via
        # *args to fetch_*/execute below.
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
            seen[name] = len(args)  # 1-based positional index
        return f"${seen[name]}"

    new_sql = _NAMED_PARAM_RE.sub(_sub, sql)
    return new_sql, args


# ---------------------------------------------------------------------------
# Connection wrapper exposed by ``database.connection() as conn``
# ---------------------------------------------------------------------------


class _ConnectionWrapper:
    """Thin wrapper exposing ``raw_connection`` for callers that want to drive
    asyncpg directly (e.g. NL2SQL execution where positional ``$N`` is the
    native style and no named-param rewrite is wanted).
    """

    __slots__ = ("raw_connection",)

    def __init__(self, conn: asyncpg.Connection) -> None:
        self.raw_connection = conn


# ---------------------------------------------------------------------------
# Database adapter
# ---------------------------------------------------------------------------


class _Database:
    """Process-wide singleton mimicking ``databases.Database`` over asyncpg.

    Only the methods routers actually used are reproduced. Each query runs
    through :func:`_named_to_positional` so that callers can keep passing
    ``{"name": value}`` dicts while the underlying driver receives positional
    ``$1, $2, ...`` parameters.
    """

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None
        self._query_timeout_seconds = float(
            os.environ.get("DB_QUERY_TIMEOUT_SECONDS", "60")
        )
        self._statement_timeout_ms = int(
            float(
                os.environ.get(
                    "DB_STATEMENT_TIMEOUT_SECONDS",
                    str(self._query_timeout_seconds),
                )
            )
            * 1000
        )
        self._pool_acquire_timeout_seconds = float(
            os.environ.get("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", "10")
        )

    # -- lifecycle -------------------------------------------------------

    async def connect(self, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
        if self._pool is None:
            min_size = int(os.environ.get("DB_POOL_MIN_SIZE", str(min_size)))
            max_size = int(os.environ.get("DB_POOL_MAX_SIZE", str(max_size)))
            dsn = _asyncpg_dsn()
            parsed = urllib.parse.urlparse(dsn)
            logger.info(
                "[db] opening asyncpg pool host=%s db=%s pool=%s-%s query_timeout=%.1fs acquire_timeout=%.1fs statement_timeout=%sms",
                parsed.hostname,
                (parsed.path or "/").lstrip("/"),
                min_size,
                max_size,
                self._query_timeout_seconds,
                self._pool_acquire_timeout_seconds,
                self._statement_timeout_ms,
            )
            self._pool = await asyncpg.create_pool(
                dsn,
                min_size=min_size,
                max_size=max_size,
                command_timeout=self._query_timeout_seconds,
                server_settings={"statement_timeout": str(self._statement_timeout_ms)},
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

    # -- query helpers ---------------------------------------------------

    async def fetch_all(
        self,
        query: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> list[asyncpg.Record]:
        sql, args = _named_to_positional(query, values)
        async with self.pool().acquire(timeout=self._pool_acquire_timeout_seconds) as conn:
            return await conn.fetch(sql, *args, timeout=self._query_timeout_seconds)

    async def fetch_one(
        self,
        query: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> Optional[asyncpg.Record]:
        sql, args = _named_to_positional(query, values)
        async with self.pool().acquire(timeout=self._pool_acquire_timeout_seconds) as conn:
            return await conn.fetchrow(sql, *args, timeout=self._query_timeout_seconds)

    async def fetch_val(
        self,
        query: str,
        values: Optional[Mapping[str, Any]] = None,
        column: int = 0,
    ) -> Any:
        sql, args = _named_to_positional(query, values)
        async with self.pool().acquire(timeout=self._pool_acquire_timeout_seconds) as conn:
            return await conn.fetchval(
                sql, *args, column=column, timeout=self._query_timeout_seconds
            )

    async def execute(
        self,
        query: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> str:
        sql, args = _named_to_positional(query, values)
        async with self.pool().acquire(timeout=self._pool_acquire_timeout_seconds) as conn:
            return await conn.execute(sql, *args, timeout=self._query_timeout_seconds)

    async def execute_many(
        self,
        query: str,
        values: Sequence[Mapping[str, Any]],
    ) -> None:
        """Execute the same statement repeatedly. asyncpg has ``executemany``
        but it requires positional args, so we translate per-row dicts the
        same way as :meth:`execute`. Suitable for bulk inserts the SaaS
        codebase did with ``database.execute_many``.
        """
        if not values:
            return
        async with self.pool().acquire(timeout=self._pool_acquire_timeout_seconds) as conn:
            for row in values:
                sql, args = _named_to_positional(query, row)
                await conn.execute(sql, *args, timeout=self._query_timeout_seconds)

    # -- context managers ------------------------------------------------

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """Yield a connection inside a transaction. Routers that previously
        wrote ``async with database.transaction(): ...`` get an asyncpg
        ``Connection`` that they can drive with positional args, OR they
        keep calling ``database.fetch_all`` from inside the block (which
        will check out a *different* connection — same as before).
        """
        async with self.pool().acquire(timeout=self._pool_acquire_timeout_seconds) as conn:
            async with conn.transaction():
                yield conn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_ConnectionWrapper]:
        """Yield a wrapped connection. ``conn.raw_connection`` is the asyncpg
        ``Connection`` — used by NL2SQL for positional-only execution.
        """
        async with self.pool().acquire(timeout=self._pool_acquire_timeout_seconds) as conn:
            yield _ConnectionWrapper(conn)


# Module-level singleton — mirrors the old ``databases.Database`` global.
database = _Database()


__all__ = ["DATABASE_URL", "database", "_named_to_positional"]
