"""Phase 2.5b stub — see ``models/__init__.py``. Re-exports the constants."""
from database import (
    GEO_GLOBAL_INTENTS,
    GEO_GLOBAL_LANGUAGES,
    GEO_GLOBAL_PLATFORMS,
    GEO_GLOBAL_SETTINGS,
)

__all__ = [
    "GEO_GLOBAL_SETTINGS",
    "GEO_GLOBAL_PLATFORMS",
    "GEO_GLOBAL_INTENTS",
    "GEO_GLOBAL_LANGUAGES",
]
