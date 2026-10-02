"""Phase 2.5b stub — see ``models/__init__.py``. Re-exports the constants.

The legacy ``geo_company_mentions`` was renamed to ``geo_brand_mentions`` in
v1.2; the back-compat alias kept the old name pointing at the new table.
After the asyncpg migration the alias is just a string equal to the new
table name.
"""
from database import GEO_BRAND_MENTIONS, GEO_PRODUCT_MENTIONS

# v1.2 back-compat alias.
GEO_COMPANY_MENTIONS = GEO_BRAND_MENTIONS

__all__ = [
    "GEO_BRAND_MENTIONS",
    "GEO_PRODUCT_MENTIONS",
    "GEO_COMPANY_MENTIONS",
]
