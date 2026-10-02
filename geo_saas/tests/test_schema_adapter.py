"""
Schema-adapter constant tests (Phase 2.5b).

Pre-Phase-2.5b these tests verified the SQLAlchemy ``Table.columns`` /
``Table.constraints`` shape of every v1.2 dual-mode-tracking table. With
SQLAlchemy gone, the equivalent layer is the table-name string registry
in ``database.py`` / ``models/*.py``. These tests assert the registry
exposes the v1.2 names every router relies on, and that the legacy
``geo_company_mentions`` import alias resolves to ``geo_brand_mentions``.

The actual column + check-constraint truth lives in ``migrations/`` and is
exercised by integration tests against a live Postgres. The unit tests
here remain cheap (no DB needed) so collection-time errors surface early.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# v1.2 dual-mode-tracking table-name registry
# ---------------------------------------------------------------------------


def test_geo_client_brands_constant():
    """Own + Shadow brands table name is exported."""
    from database import GEO_CLIENT_BRANDS
    assert GEO_CLIENT_BRANDS == "geo_client_brands"


def test_geo_client_topic_products_constant():
    """v1.2 structured product rows table name is exported."""
    from database import GEO_CLIENT_TOPIC_PRODUCTS
    assert GEO_CLIENT_TOPIC_PRODUCTS == "geo_client_topic_products"


def test_geo_product_mentions_constant():
    """v1.2 product-level mentions table name is exported."""
    from database import GEO_PRODUCT_MENTIONS
    assert GEO_PRODUCT_MENTIONS == "geo_product_mentions"


def test_geo_brand_mentions_rename():
    """v1.2 renamed ``geo_company_mentions`` → ``geo_brand_mentions``.

    The constant must point at the new name; any leftover ``geo_company_*``
    string would break analyzer + insights queries.
    """
    from database import GEO_BRAND_MENTIONS
    assert GEO_BRAND_MENTIONS == "geo_brand_mentions"


def test_geo_citations_constant():
    from database import GEO_CITATIONS
    assert GEO_CITATIONS == "geo_citations"


def test_geo_client_domains_constant():
    from database import GEO_CLIENT_DOMAINS
    assert GEO_CLIENT_DOMAINS == "geo_client_domains"


def test_geo_clients_constant():
    from database import GEO_CLIENTS
    assert GEO_CLIENTS == "geo_clients"


def test_geo_client_peers_constant():
    from database import GEO_CLIENT_PEERS
    assert GEO_CLIENT_PEERS == "geo_client_peers"


def test_geo_client_topics_constant():
    from database import GEO_CLIENT_TOPICS
    assert GEO_CLIENT_TOPICS == "geo_client_topics"


def test_v1_2_new_tables_exported():
    """v1.2 added three new tables for sales channels / tracked URLs / candidates."""
    from database import (
        GEO_PRODUCT_SALES_CHANNELS,
        GEO_PRODUCT_TRACKED_URLS,
        GEO_SETTINGS_CANDIDATES,
    )
    assert GEO_PRODUCT_SALES_CHANNELS == "geo_product_sales_channels"
    assert GEO_PRODUCT_TRACKED_URLS == "geo_product_tracked_urls"
    assert GEO_SETTINGS_CANDIDATES == "geo_settings_candidates"


def test_backcompat_alias_points_to_brand_mentions():
    """Legacy ``models.mentions.GEO_COMPANY_MENTIONS`` resolves to the
    renamed table so callers that haven't migrated still hit the right
    physical table.
    """
    from models.mentions import GEO_BRAND_MENTIONS, GEO_COMPANY_MENTIONS
    assert GEO_COMPANY_MENTIONS == GEO_BRAND_MENTIONS == "geo_brand_mentions"
