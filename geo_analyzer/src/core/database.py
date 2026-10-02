"""
GEO Analyzer — Database access (Phase 2.5b unified asyncpg pool).

Phase 2.5b migrated this module from sync SQLAlchemy + psycopg2 (with full
``Table`` MetaData definitions) onto the shared ``geo_common.db`` asyncpg pool
factory. All other GEO modules now use ``create_asyncpg_pool``; analyzer was
the last sync hold-out and now matches the collector's shape (see
``geo_collector/src/core/database.py``).

Public surface:

* ``get_pool()`` — return the lazily-initialized module-level ``asyncpg.Pool``.
* ``connect()`` — create the pool (call from job ``main()`` startup).
* ``disconnect()`` — close the pool (call from job ``main()`` shutdown).
* ``parse_affected(status_string)`` — turn an asyncpg command tag like
  ``"UPDATE 7"`` into the affected row count, mirroring the collector helper.
* Table-name constants (``GEO_RESULTS`` …) for raw-SQL clarity.

Why no SQLAlchemy ``Table`` definitions anymore:
asyncpg uses ``$1, $2, …`` placeholders and raw SQL. The previous SQLAlchemy
schema metadata existed only because the analyzer compiled SA constructs via
``sessionmaker`` — we now write SQL strings directly. The canonical schema
lives in ``migrations/`` (and, for cross-module reference,
``geo_admin/src/database.py``).

Schema alignment (v1.2 dual-mode tracking — Spec
``docs/superpowers/specs/2026-04-20-dual-mode-tracking-design-v1.2-finalized.md``
§4 + migrations 040–046):

Analyzer role:
* READS from ``geo_results`` (un-analyzed batches) plus the per-client
  config tables: ``geo_clients`` / ``geo_client_brands`` /
  ``geo_client_peers`` / ``geo_client_domains`` / ``geo_client_topics`` /
  ``geo_client_topic_products`` / ``geo_product_tracked_urls``.
* WRITES to ``geo_brand_mentions`` / ``geo_product_mentions`` /
  ``geo_citations`` / ``geo_sentiment_results`` / ``geo_sentiment_themes``
  / ``geo_sentiment_theme_dictionary`` / ``geo_domain_categories`` /
  ``geo_settings_candidates`` and stamps ``geo_results.analyzed_at``.
"""
from __future__ import annotations

import json
from typing import Optional

import asyncpg
from geo_common.db import create_asyncpg_pool

from src.core.config import get_settings


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Per-connection initializer registered with the asyncpg pool.

    Registers a JSON/JSONB codec so PG ``json``/``jsonb`` columns are
    automatically decoded into Python objects on read and serialized via
    ``json.dumps`` on write. Without this, asyncpg returns/sends raw text
    and every read site would need a manual ``json.loads`` (and every
    write a manual ``json.dumps``). Analyzer reads ``geo_results.sources``
    / ``citation_pills`` and writes ``geo_settings_candidates.metadata``
    (JSONB), so it benefits from both directions.
    """
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

# ---------------------------------------------------------------------------
# Module-level pool (lazy-init, lifecycle managed by the Cloud Run Job's
# main() — start with `await connect()` and end with `await disconnect()`).
# ---------------------------------------------------------------------------

_pool: Optional[asyncpg.Pool] = None


async def connect(min_size: int = 1, max_size: int = 5) -> asyncpg.Pool:
    """
    Initialize the module-level asyncpg pool.

    Idempotent: returns the existing pool if already connected.
    Defaults (1..5 connections) match the collector's choice — analyzer is a
    Cloud Run Job that processes one client at a time, so a small pool is
    enough and avoids burning Cloud SQL connection slots.
    """
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_asyncpg_pool(
            settings,
            min_size=min_size,
            max_size=max_size,
            init=_init_connection,
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

    Most call sites should depend on the job ``main()`` having run
    ``connect()`` first; this helper just unwraps the Optional so caller
    signatures stay clean.
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialized. Call `await connect()` first "
            "(typically from the Cloud Run Job main())."
        )
    return _pool


def parse_affected(status_string: str) -> int:
    """
    Parse asyncpg's command-status string (e.g. ``"UPDATE 7"``) into an
    affected-row count. Returns 0 on any unexpected shape so that callers
    treat the operation as a no-op (matches the collector helper).
    """
    if not status_string:
        return 0
    parts = status_string.strip().split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        return 0


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
GEO_PRODUCT_TRACKED_URLS = "geo_product_tracked_urls"
GEO_PRODUCT_SALES_CHANNELS = "geo_product_sales_channels"
GEO_SETTINGS_CANDIDATES = "geo_settings_candidates"

# Execution / Cloro
GEO_TASKS = "geo_tasks"
GEO_RESULTS = "geo_results"

# Analyzer outputs
GEO_BRAND_MENTIONS = "geo_brand_mentions"
GEO_PRODUCT_MENTIONS = "geo_product_mentions"
GEO_CITATIONS = "geo_citations"
GEO_DOMAIN_CATEGORIES = "geo_domain_categories"
GEO_SENTIMENT_RESULTS = "geo_sentiment_results"
GEO_SENTIMENT_THEMES = "geo_sentiment_themes"
GEO_SENTIMENT_THEME_DICTIONARY = "geo_sentiment_theme_dictionary"
