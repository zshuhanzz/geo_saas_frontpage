"""
Shared asyncpg connection pool creator.

Used by modules that speak asyncpg (`geo_agent`, `geo_saas`, `geo_admin`).
Modules on other DB drivers — `geo_collector` (uses `databases` lib) and
`geo_analyzer` (uses sync SQLAlchemy) — will migrate to this in Phase 2.5.
"""

import os
from typing import Any, Optional

import asyncpg


async def create_asyncpg_pool(
    settings: Any,
    min_size: int = 1,
    max_size: int = 10,
    **kwargs: Any,
) -> asyncpg.Pool:
    """
    Create a shared asyncpg connection pool from a BaseConfig-compatible settings object.

    Environment resolution (same policy as `BaseConfig.build_database_url`):

    - Cloud Run (`K_SERVICE` or `IS_CLOUD_RUN` env present) + `DB_INSTANCE_CONNECTION_NAME` set
      → Cloud SQL unix socket at `/cloudsql/<conn_name>`.
    - Otherwise → TCP to `DB_HOST:DB_PORT`.

    :param settings:  An instance of `geo_common.config.BaseConfig` (or subclass).
                      Must expose `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST`,
                      `DB_PORT`, and optionally `DB_INSTANCE_CONNECTION_NAME`.
    :param min_size:  Minimum pool size (default 1).
    :param max_size:  Maximum pool size (default 10).
    :param kwargs:    Forwarded to `asyncpg.create_pool` (e.g. `command_timeout`,
                      `server_settings`, `ssl`, etc.).
    :return:          An open `asyncpg.Pool`. Caller is responsible for `await pool.close()`.
    """
    is_cloud_run = bool(
        os.environ.get("K_SERVICE") or os.environ.get("IS_CLOUD_RUN")
    )

    conn_name = getattr(settings, "DB_INSTANCE_CONNECTION_NAME", None)
    if is_cloud_run and conn_name:
        host: str = f"/cloudsql/{conn_name}"
        port: Optional[int] = None
    else:
        host = settings.DB_HOST
        port = settings.DB_PORT

    return await asyncpg.create_pool(
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        host=host,
        port=port,
        min_size=min_size,
        max_size=max_size,
        **kwargs,
    )
