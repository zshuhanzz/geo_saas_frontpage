"""
Phase 2.5b stub — SQLAlchemy ``MetaData`` and the ``databases.Database``
instance previously lived here. Both are gone after the asyncpg-only
migration. This module remains as an empty namespace so the auto-generated
import graph (and any straggler that does ``from models._base import ...``)
fails loudly with a clear AttributeError instead of silently importing
nothing.

Use ``db.database`` for runtime queries. Use ``database.GEO_*`` constants
for canonical table names.
"""
from __future__ import annotations

from db import DATABASE_URL

__all__ = ["DATABASE_URL"]
