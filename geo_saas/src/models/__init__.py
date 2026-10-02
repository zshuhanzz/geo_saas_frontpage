"""
Table-name registry for ``geo_saas`` — Phase 2.5b stub.

Pre-Phase-2.5b, this package held SQLAlchemy ``Table`` objects + a shared
``MetaData`` registry consumed by the ``databases`` lib. With both
removed, the package becomes a thin re-export of the canonical table-name
string constants defined in ``geo_saas/src/database.py``.

Routers should import directly from ``database`` (or, preferably, hard-code
table names in raw SQL since the strings are stable and the constants don't
add typo safety beyond what the SQL parser already gives at execution time).
"""
from __future__ import annotations

from database import (
    DATABASE_URL,
    GEO_BRAND_MENTIONS,
    GEO_BRAND_PROFILES,
    GEO_CITATIONS,
    GEO_CLIENT_BRANDS,
    GEO_CLIENT_DOMAINS,
    GEO_CLIENT_PEERS,
    GEO_CLIENT_PERSONAS,
    GEO_CLIENT_PROMPTS,
    GEO_CLIENT_TOPIC_PRODUCTS,
    GEO_CLIENT_TOPICS,
    GEO_CLIENTS,
    GEO_DOMAIN_CATEGORIES,
    GEO_GLOBAL_INTENTS,
    GEO_GLOBAL_LANGUAGES,
    GEO_GLOBAL_PLATFORMS,
    GEO_GLOBAL_SETTINGS,
    GEO_PRODUCT_MENTIONS,
    GEO_PRODUCT_SALES_CHANNELS,
    GEO_PRODUCT_TRACKED_URLS,
    GEO_REPORT_TEMPLATES,
    GEO_RESULTS,
    GEO_SETTINGS_CANDIDATES,
    GEO_TASKS,
    GEO_WORKFLOW_CONFIG,
    database,
)

__all__ = [
    "DATABASE_URL",
    "database",
    "GEO_GLOBAL_SETTINGS",
    "GEO_GLOBAL_PLATFORMS",
    "GEO_GLOBAL_INTENTS",
    "GEO_GLOBAL_LANGUAGES",
    "GEO_DOMAIN_CATEGORIES",
    "GEO_CLIENTS",
    "GEO_CLIENT_BRANDS",
    "GEO_CLIENT_PEERS",
    "GEO_CLIENT_DOMAINS",
    "GEO_CLIENT_TOPICS",
    "GEO_CLIENT_TOPIC_PRODUCTS",
    "GEO_CLIENT_PERSONAS",
    "GEO_CLIENT_PROMPTS",
    "GEO_BRAND_PROFILES",
    "GEO_PRODUCT_SALES_CHANNELS",
    "GEO_PRODUCT_TRACKED_URLS",
    "GEO_SETTINGS_CANDIDATES",
    "GEO_TASKS",
    "GEO_RESULTS",
    "GEO_BRAND_MENTIONS",
    "GEO_PRODUCT_MENTIONS",
    "GEO_CITATIONS",
    "GEO_REPORT_TEMPLATES",
    "GEO_WORKFLOW_CONFIG",
]
