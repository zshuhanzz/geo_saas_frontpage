"""
Onboarding wizard router — first-login wizard status + completion.

Phase 3A.2 refactor (2026-04-25): extracted from ``routers/settings.py``.

Endpoints (mounted under ``/api/settings``):
    - GET  /onboarding_status   — wizard completion status + 4-branch defaults
    - POST /complete_onboarding — mark wizard complete; optionally seed Own brand
"""

from __future__ import annotations

from typing import Dict, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import database

router = APIRouter(tags=["Brand Settings - Onboarding"])


class _BranchDefault(BaseModel):
    own_brand: bool
    shadow_brand: bool


class OnboardingStatusOut(BaseModel):
    client_id: str
    client_name: Optional[str] = None
    onboarding_wizard_completed: bool
    branch_defaults: Dict[str, _BranchDefault]


class _Seeded(BaseModel):
    own_brand_id: Optional[str] = None


class CompleteOnboardingOut(BaseModel):
    client_id: str
    branch: str
    onboarding_wizard_completed: bool
    seeded: _Seeded


class CompleteOnboardingInput(BaseModel):
    branch: str  # 'own' | 'oem' | 'both' | 'skip'


# Default brand name suggestions per branch — used by the frontend Wizard as a
# starting point. The actual brand rows are seeded server-side when the user
# POSTs complete_onboarding, so the wizard UX can stay fully declarative.
_BRANCH_DEFAULTS = {
    "own": {"own_brand": True, "shadow_brand": False},
    "oem": {"own_brand": False, "shadow_brand": True},
    "both": {"own_brand": True, "shadow_brand": True},
    "skip": {"own_brand": False, "shadow_brand": False},
}


@router.get("/onboarding_status", response_model=OnboardingStatusOut)
async def get_onboarding_status(client_id: UUID) -> OnboardingStatusOut:
    """Return onboarding wizard completion status + the 4-branch suggestion map.

    The frontend uses this to decide whether to pop the wizard at first login
    and to pre-populate the defaults per branch selection.
    """
    row = await database.fetch_one(
        """
        SELECT id, name, onboarding_wizard_completed
        FROM geo_clients
        WHERE id = :client_id
        """,
        {"client_id": client_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
    return OnboardingStatusOut(
        client_id=str(row["id"]),
        client_name=row["name"],
        onboarding_wizard_completed=bool(row["onboarding_wizard_completed"]),
        branch_defaults={
            k: _BranchDefault(**v) for k, v in _BRANCH_DEFAULTS.items()
        },
    )


@router.post("/complete_onboarding", response_model=CompleteOnboardingOut)
async def complete_onboarding(
    client_id: UUID, data: CompleteOnboardingInput
) -> CompleteOnboardingOut:
    """Mark the onboarding wizard as completed and (optionally) seed defaults.

    Branch semantics (Spec §8.6):
    - ``own`` : seed one Own Brand using the client's name.
    - ``oem`` : no brand seeded — UI steers the user to create a Shadow Brand.
    - ``both``: seed one Own Brand (Shadow comes later via UI).
    - ``skip``: no brand seeded. Wizard simply marked complete.
    """
    branch = data.branch.strip().lower()
    if branch not in _BRANCH_DEFAULTS:
        raise HTTPException(
            status_code=422,
            detail="branch must be one of 'own', 'oem', 'both', 'skip'",
        )

    client_row = await database.fetch_one(
        "SELECT id, name, aliases FROM geo_clients WHERE id = :client_id",
        {"client_id": client_id},
    )
    if not client_row:
        raise HTTPException(status_code=404, detail="Client not found")

    seeded = {"own_brand_id": None}

    # Seed Own Brand for 'own' and 'both' if the client doesn't already have one.
    if _BRANCH_DEFAULTS[branch]["own_brand"]:
        existing_own = await database.fetch_one(
            """
            SELECT id FROM geo_client_brands
            WHERE client_id = :client_id AND is_shadow = FALSE
            """,
            {"client_id": client_id},
        )
        if not existing_own:
            new_id = uuid4()
            await database.execute(
                """
                INSERT INTO geo_client_brands
                    (id, client_id, brand_name, aliases, is_shadow, is_active)
                VALUES (:id, :client_id, :brand_name, :aliases, FALSE, TRUE)
                """,
                {
                    "id": new_id,
                    "client_id": client_id,
                    "brand_name": client_row["name"],
                    "aliases": list(client_row["aliases"] or []),
                },
            )
            seeded["own_brand_id"] = str(new_id)
        else:
            seeded["own_brand_id"] = str(existing_own["id"])

    await database.execute(
        """
        UPDATE geo_clients
        SET onboarding_wizard_completed = TRUE
        WHERE id = :client_id
        """,
        {"client_id": client_id},
    )

    return CompleteOnboardingOut(
        client_id=str(client_id),
        branch=branch,
        onboarding_wizard_completed=True,
        seeded=_Seeded(**seeded),
    )
