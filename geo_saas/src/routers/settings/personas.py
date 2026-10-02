"""
Personas router — buyer/audience persona CRUD.

Phase 4 (2026-04-25): migrated to :class:`PersonaRepository`.

Endpoints (mounted under ``/api/settings``):
    - GET    /personas               — list personas
    - POST   /personas               — add persona
    - DELETE /personas/{persona_id}  — remove persona
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from geo_common.services import PersonaRepository
from pydantic import BaseModel

from pool import get_pool

router = APIRouter(tags=["Brand Settings - Personas"])


class PersonaCreateInput(BaseModel):
    persona_name: str
    persona_description: Optional[str] = None


class PersonaOut(BaseModel):
    id: str
    client_id: str
    persona_name: str
    persona_description: Optional[str] = None
    created_at: Optional[datetime] = None


def _stringify(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, UUID):
            out[k] = str(v)
    return out


@router.get("/personas", response_model=List[PersonaOut])
async def get_personas(
    client_id: UUID, pool=Depends(get_pool)
) -> List[PersonaOut]:
    repo = PersonaRepository(pool)
    rows = await repo.list_for_client(str(client_id))
    return [PersonaOut(**_stringify(r)) for r in rows]


@router.post("/personas", status_code=201, response_model=PersonaOut)
async def add_persona(
    client_id: UUID, data: PersonaCreateInput, pool=Depends(get_pool)
) -> PersonaOut:
    repo = PersonaRepository(pool)
    row = await repo.add(
        str(client_id),
        persona_name=data.persona_name,
        persona_description=data.persona_description,
    )
    return PersonaOut(**_stringify(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/personas/{persona_id}", status_code=204)
async def remove_persona(
    client_id: UUID, persona_id: UUID, pool=Depends(get_pool)
) -> None:
    repo = PersonaRepository(pool)
    await repo.delete(str(client_id), str(persona_id))
    return None
