"""
GEO Collector — Database access (Phase 2.5a unified asyncpg pool).

Phase 2.5a migrated this module away from the third-party ``databases`` lib +
SQLAlchemy ``Table`` MetaData into the shared ``geo_common.db`` asyncpg pool
factory. Every other GEO module now uses ``create_asyncpg_pool``; this module
removes the last remaining异类 caller.

Public surface:

* ``get_pool()`` — return the lazily-initialized module-level ``asyncpg.Pool``.
* ``connect()`` — create the pool (call from app startup).
* ``disconnect()`` — close the pool (call from app shutdown).
* Table-name constants (``GEO_TASKS``, ``GEO_RESULTS`` …) for raw-SQL clarity.

Why no SQLAlchemy ``Table`` definitions anymore:
asyncpg uses ``$1, $2, …`` placeholders and raw SQL. The previous SQLAlchemy
schema metadata existed only because the ``databases`` lib compiled SA
constructs. We now write SQL strings directly. The canonical schema lives in
``migrations/`` (and, for cross-module reference, ``geo_admin/src/database.py``).

Schema alignment (v1.2 dual-mode tracking — Spec
``docs/superpowers/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md``
§4 + migrations 040–046):

Collector role:
* WRITES to ``geo_tasks`` / ``geo_results`` / ``geo_client_prompts``
  (no longer to ``geo_citations`` directly — analyzer owns that).
* READS from ``geo_clients`` / ``geo_client_brands`` / ``geo_client_peers``
  / ``geo_client_domains`` / ``geo_client_topics`` /
  ``geo_client_topic_products`` / ``geo_client_personas`` /
  ``geo_client_prompts`` / ``geo_global_*`` for prompt assembly.
"""
from __future__ import annotations

from typing import Optional

import asyncpg
from geo_common.db import create_asyncpg_pool

from src.core.config import get_settings

# ---------------------------------------------------------------------------
# Module-level pool (lazy-init, lifecycle managed by FastAPI startup/shutdown
# hooks or the Cloud Run Job's main()).
# ---------------------------------------------------------------------------

_pool: Optional[asyncpg.Pool] = None


async def connect(min_size: int = 1, max_size: int = 5) -> asyncpg.Pool:
    """
    Initialize the module-level asyncpg pool.

    Idempotent: returns the existing pool if already connected.
    Defaults preserve the original ``databases`` settings (1..5 connections),
    appropriate for Cloud Run instances that scale horizontally.
    """
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_asyncpg_pool(
            settings,
            min_size=min_size,
            max_size=max_size,
        )
    return _pool


async def disconnect() -> None:
    """Close the module-level asyncpg pool. Safe to call when not connected."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """
    Return the live pool. Raises if ``connect()`` has not been called.

    Most call sites should depend on the FastAPI startup hook having run; this
    helper just unwraps the Optional so caller signatures stay clean.
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialized. Call `await connect()` first "
            "(typically from the FastAPI startup hook or job main())."
        )
    return _pool


# ---------------------------------------------------------------------------
# Table-name constants — used in raw SQL strings to keep typos catchable in
# one place. NOT a schema; consult ``migrations/`` for the source of truth.
# ---------------------------------------------------------------------------

# Global config
GEO_GLOBAL_SETTINGS = "geo_global_settings"
GEO_GLOBAL_PLATFORMS = "geo_global_platforms"
GEO_GLOBAL_INTENTS = "geo_global_intents"

# Client / tenancy
GEO_CLIENTS = "geo_clients"
GEO_CLIENT_BRANDS = "geo_client_brands"
GEO_CLIENT_PEERS = "geo_client_peers"
GEO_CLIENT_DOMAINS = "geo_client_domains"
GEO_CLIENT_TOPICS = "geo_client_topics"
GEO_CLIENT_TOPIC_PRODUCTS = "geo_client_topic_products"
GEO_CLIENT_PERSONAS = "geo_client_personas"
GEO_CLIENT_PROMPTS = "geo_client_prompts"

# Execution
GEO_TASKS = "geo_tasks"
GEO_RESULTS = "geo_results"
