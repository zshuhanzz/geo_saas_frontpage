"""
Backward-compatibility shim — Phase 2.5b (2026-04-26).

The legacy ``databases`` lib + SQLAlchemy ``Table`` MetaData layer was
removed. All admin routers now talk to the database via ``db.database``
(asyncpg adapter that accepts ``:name`` params in raw SQL strings).

This file used to define every ``geo_*`` Table object as the single source
of truth for the admin module. The DDL truth has always lived in
``migrations/`` — the Tables here only existed to keep the ``databases``
lib happy. With ``databases`` gone, only the table-name string constants
remain, mirroring ``geo_collector/src/core/database.py``'s post-migration
shape.
"""
from __future__ import annotations

from db import DATABASE_URL, database

# ---------------------------------------------------------------------------
# Canonical table-name constants. Kept in lockstep with ``migrations/``.
# ---------------------------------------------------------------------------

# Global config
GEO_GLOBAL_SETTINGS = "geo_global_settings"
GEO_GLOBAL_PLATFORMS = "geo_global_platforms"
GEO_GLOBAL_INTENTS = "geo_global_intents"
GEO_GLOBAL_LANGUAGES = "geo_global_languages"
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
GEO_BRAND_PROFILES = "geo_brand_profiles"

# Product relations + AI candidates
GEO_PRODUCT_SALES_CHANNELS = "geo_product_sales_channels"
GEO_PRODUCT_TRACKED_URLS = "geo_product_tracked_urls"
GEO_SETTINGS_CANDIDATES = "geo_settings_candidates"

# Execution
GEO_TASKS = "geo_tasks"
GEO_RESULTS = "geo_results"

# Analyzer
GEO_BRAND_MENTIONS = "geo_brand_mentions"
GEO_PRODUCT_MENTIONS = "geo_product_mentions"
GEO_CITATIONS = "geo_citations"

# Analysis & insights
GEO_ANALYSIS_METRICS = "geo_analysis_metrics"
GEO_REPORT_TEMPLATES = "geo_report_templates"
GEO_WORKFLOW_CONFIG = "geo_workflow_config"
GEO_AGENT_TASKS = "geo_agent_tasks"

# Agent runtime
AGENT_MEMORIES = "agent_memories"
AGENT_SESSIONS = "agent_sessions"
AGENT_MESSAGES = "agent_messages"
AGENT_TOKEN_USAGE = "agent_token_usage"
AGENT_USER_PROFILES = "agent_user_profiles"

# Content optimization framework
GEO_OPTIMIZATION_METRICS = "geo_optimization_metrics"
GEO_OPTIMIZATION_SUBGOALS = "geo_optimization_subgoals"
GEO_STRATEGIES = "geo_strategies"
GEO_CONTENT_ASSETS = "geo_content_assets"


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
    "GEO_BRAND_PROFILES",
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
    "GEO_ANALYSIS_METRICS",
    "GEO_REPORT_TEMPLATES",
    "GEO_WORKFLOW_CONFIG",
    "GEO_AGENT_TASKS",
    # Agent runtime
    "AGENT_MEMORIES",
    "AGENT_SESSIONS",
    "AGENT_MESSAGES",
    "AGENT_TOKEN_USAGE",
    "AGENT_USER_PROFILES",
    # Content framework
    "GEO_OPTIMIZATION_METRICS",
    "GEO_OPTIMIZATION_SUBGOALS",
    "GEO_STRATEGIES",
    "GEO_CONTENT_ASSETS",
]
