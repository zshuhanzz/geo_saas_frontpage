"""
Global Dictionary Tables Router (SaaS) — Read-only access.

Consolidates endpoints for:
- Intents (for prompt editor intent selection)
- Platforms (for brainstorming platform selection)
- Languages (for brainstorming language selection)
"""
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from db import database

router = APIRouter()


# ─── Output models ─────────────────────────────────────────────────────────


class IntentOut(BaseModel):
    id: str
    intent_name: str
    description: Optional[str] = None


class PlatformOut(BaseModel):
    id: str
    platform_id: str
    display_name: str
    supported_countries: List[str] = []
    system_instructions: Optional[str] = None


class LanguageOut(BaseModel):
    id: str
    language_code: str
    language: str


# ============================================================================
# Intents
# ============================================================================
@router.get("/intents", response_model=List[IntentOut])
async def list_intents() -> List[IntentOut]:
    """List all active global intents."""
    rows = await database.fetch_all(
        """
        SELECT id, intent_name, description
        FROM geo_global_intents
        WHERE is_active = TRUE
        ORDER BY intent_name
        """
    )
    return [
        IntentOut(
            id=str(r["id"]),
            intent_name=r["intent_name"],
            description=r["description"],
        )
        for r in rows
    ]


# ============================================================================
# Platforms
# ============================================================================
@router.get("/platforms", response_model=List[PlatformOut])
async def list_platforms() -> List[PlatformOut]:
    """Return all active global platforms with their supported countries."""
    rows = await database.fetch_all(
        """
        SELECT id, platform_id, display_name, supported_countries, system_instructions
        FROM geo_global_platforms
        WHERE is_active = TRUE
        ORDER BY display_name
        """
    )
    return [
        PlatformOut(
            id=str(row["id"]),
            platform_id=row["platform_id"],
            display_name=row["display_name"],
            supported_countries=row["supported_countries"] or [],
            system_instructions=row["system_instructions"],
        )
        for row in rows
    ]


# ============================================================================
# Languages
# ============================================================================
@router.get("/languages", response_model=List[LanguageOut])
async def list_languages() -> List[LanguageOut]:
    """List all active global languages."""
    rows = await database.fetch_all(
        """
        SELECT id, language_code, language
        FROM geo_global_languages
        WHERE is_active = TRUE
        ORDER BY language_code
        """
    )
    return [
        LanguageOut(
            id=str(r["id"]),
            language_code=r["language_code"],
            language=r["language"],
        )
        for r in rows
    ]
