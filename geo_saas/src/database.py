"""
Backward-compatibility shim — Phase 2.5b (2026-04-26).

The legacy ``databases`` lib + SQLAlchemy ``Table`` MetaData layer was
removed. All routers now talk to the database via ``db.database`` (asyncpg
adapter that accepts ``:name`` params in raw SQL strings).

This file used to re-export the SQLAlchemy ``Table`` objects for legacy
``from database import database, geo_clients`` callsites. None of the
production routers reference those imports anymore — every site has been
migrated to either:

  * ``from db import database`` + raw SQL strings, OR
  * ``from geo_common.services import XxxRepository`` + asyncpg pool.

We keep this module as a thin re-export of the new ``database`` adapter
plus a registry of canonical table-name string constants. The constants
mirror ``geo_collector/src/core/database.py``'s post-migration shape so
admin tooling and tests have a single place to look up the official table
catalog without importing SQLAlchemy.

The ``models/`` package next to this file follows the same shape — see
``models/__init__.py`` for the per-domain table-name groupings.
"""
from __future__ import annotations

from db import DATABASE_URL, database

# ---------------------------------------------------------------------------
# Canonical table-name constants. Used by raw-SQL call sites that prefer a
# typo-safe constant over inline string literals (e.g. when a single SQL
# string references the same table multiple times).
#
# This list is intentionally a flat string registry — no SQLAlchemy ``Table``
# objects, no ``MetaData``. The DDL source of truth lives in ``migrations/``.
# ---------------------------------------------------------------------------

# Global config
GEO_GLOBAL_SETTINGS = "geo_global_settings"
GEO_GLOBAL_PLATFORMS = "geo_global_platforms"
GEO_GLOBAL_INTENTS = "geo_global_intents"
GEO_GLOBAL_LANGUAGES = "geo_global_languages"

# Domain / sentiment dictionaries
GEO_DOMAIN_CATEGORIES = "geo_domain_categories"
GEO_SENTIMENT_THEME_DICTIONARY = "geo_sentiment_theme_dictionary"

# Client / tenancy
GEO_CLIENTS = "geo_clients"
GEO_CLIENT_BRANDS = "geo_client_brands"
GEO_CLIENT_PEERS = "geo_client_peers"
GEO_CLIENT_DOMAINS = "geo_client_domains"
GEO_CLIENT_TOPICS = "geo_client_topics"
GEO_CLIENT_TOPIC_PRODUCTS = "geo_client_topic_products"
GEO_CLIENT_PERSONAS = "geo_client_personas"
GEO_CLIENT_PROMPTS = "geo_client_prompts"

# Product relations + AI candidates
GEO_PRODUCT_SALES_CHANNELS = "geo_product_sales_channels"
GEO_PRODUCT_TRACKED_URLS = "geo_product_tracked_urls"
GEO_SETTINGS_CANDIDATES = "geo_settings_candidates"

# Execution
GEO_TASKS = "geo_tasks"
GEO_RESULTS = "geo_results"

# Analyzer mention tables (v1.2 dual-mode tracking)
GEO_BRAND_MENTIONS = "geo_brand_mentions"
GEO_PRODUCT_MENTIONS = "geo_product_mentions"
GEO_CITATIONS = "geo_citations"

# Analysis & insights
GEO_REPORT_TEMPLATES = "geo_report_templates"
GEO_WORKFLOW_CONFIG = "geo_workflow_config"
GEO_STATIC_REPORTS = "geo_static_reports"

# Brand / agent context
GEO_BRAND_PROFILES = "geo_brand_profiles"


__all__ = [
    "DATABASE_URL",
    "database",
    # Global config
    "GEO_GLOBAL_SETTINGS",
    "GEO_GLOBAL_PLATFORMS",
    "GEO_GLOBAL_INTENTS",
    "GEO_GLOBAL_LANGUAGES",
    "GEO_DOMAIN_CATEGORIES",
    "GEO_SENTIMENT_THEME_DICTIONARY",
    # Client / tenancy
    "GEO_CLIENTS",
    "GEO_CLIENT_BRANDS",
    "GEO_CLIENT_PEERS",
    "GEO_CLIENT_DOMAINS",
    "GEO_CLIENT_TOPICS",
    "GEO_CLIENT_TOPIC_PRODUCTS",
    "GEO_CLIENT_PERSONAS",
    "GEO_CLIENT_PROMPTS",
    # Product relations
    "GEO_PRODUCT_SALES_CHANNELS",
    "GEO_PRODUCT_TRACKED_URLS",
    "GEO_SETTINGS_CANDIDATES",
    # Execution
    "GEO_TASKS",
    "GEO_RESULTS",
    # Analyzer
    "GEO_BRAND_MENTIONS",
    "GEO_PRODUCT_MENTIONS",
    "GEO_CITATIONS",
    # Analysis
    "GEO_REPORT_TEMPLATES",
    "GEO_WORKFLOW_CONFIG",
    "GEO_STATIC_REPORTS",
    "GEO_BRAND_PROFILES",
]
