"""
Domains router — Client-owned domain CRUD with brand/peer ownership.

Phase 4 (2026-04-25): migrated to :class:`DomainRepository`. Owner exclusivity
(``brand_id`` XOR ``peer_id``) is enforced at the router layer via
``_validate_owner_exclusive`` so the user gets a friendly 422 instead of the
DB CHECK error.

Endpoints (mounted under ``/api/settings``):
    - GET    /domains              — list client's domains
    - POST   /domains              — register new domain
    - PUT    /domains/{domain_id}  — update domain
    - DELETE /domains/{domain_id}  — remove domain
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from geo_common.services import DomainRepository
from pydantic import BaseModel

from pool import get_pool

from ._helpers import _validate_owner_exclusive

router = APIRouter(tags=["Brand Settings - Domains"])


class DomainOut(BaseModel):
    id: str
    client_id: str
    domain: str
    is_primary: Optional[bool] = None
    domain_scope: Optional[str] = None
    brand_id: Optional[str] = None
    peer_id: Optional[str] = None
    created_at: Optional[datetime] = None


class DomainCreateInput(BaseModel):
    domain: str
    is_primary: bool = False
    domain_scope: str = "whole"  # 'whole' | 'path-prefix'
    brand_id: Optional[UUID] = None
    peer_id: Optional[UUID] = None


class DomainUpdateInput(BaseModel):
    domain: Optional[str] = None
    is_primary: Optional[bool] = None
    domain_scope: Optional[str] = None
    brand_id: Optional[UUID] = None
    peer_id: Optional[UUID] = None


def _validate_domain_scope(scope: Optional[str]) -> None:
    if scope is None:
        return
    if scope not in ("whole", "path-prefix"):
        raise HTTPException(status_code=422, detail="domain_scope must be 'whole' or 'path-prefix'")


def _stringify(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, UUID):
            out[k] = str(v)
    return out


@router.get("/domains", response_model=List[DomainOut])
async def get_domains(
    client_id: UUID, pool=Depends(get_pool)
) -> List[DomainOut]:
    repo = DomainRepository(pool)
    rows = await repo.list_for_client(str(client_id))
    return [DomainOut(**_stringify(r)) for r in rows]


@router.post("/domains", status_code=201, response_model=DomainOut)
async def add_domain(
    client_id: UUID, data: DomainCreateInput, pool=Depends(get_pool)
) -> DomainOut:
    _validate_domain_scope(data.domain_scope)
    _validate_owner_exclusive(data.brand_id, data.peer_id)

    repo = DomainRepository(pool)
    if await repo.get_by_domain(str(client_id), data.domain):
        raise HTTPException(
            status_code=400, detail="Domain already exists for this workspace"
        )
    row = await repo.add(
        str(client_id),
        domain=data.domain,
        is_primary=data.is_primary,
        domain_scope=data.domain_scope,
        brand_id=data.brand_id,
        peer_id=data.peer_id,
    )
    return DomainOut(**_stringify(row))


@router.put("/domains/{domain_id}", response_model=DomainOut)
async def update_domain(
    client_id: UUID,
    domain_id: UUID,
    data: DomainUpdateInput,
    pool=Depends(get_pool),
) -> DomainOut:
    """Update a domain. Empty patch returns the existing row so the response
    shape stays consistent.
    """
    _validate_domain_scope(data.domain_scope)
    payload = data.model_dump(exclude_unset=True)
    # Only enforce owner_exclusive when both are explicitly set in the patch.
    if "brand_id" in payload and "peer_id" in payload:
        _validate_owner_exclusive(payload.get("brand_id"), payload.get("peer_id"))

    repo = DomainRepository(pool)
    # Convert UUIDs to strings (asyncpg accepts both, but be explicit so
    # JSON-encoded ID round-trips cleanly).
    for k in ("brand_id", "peer_id"):
        if k in payload and payload[k] is not None:
            payload[k] = str(payload[k])

    row = await repo.update(str(client_id), str(domain_id), updates=payload)
    if not row:
        raise HTTPException(status_code=404, detail="Domain not found")
    return DomainOut(**_stringify(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/domains/{domain_id}", status_code=204)
async def remove_domain(
    client_id: UUID, domain_id: UUID, pool=Depends(get_pool)
) -> None:
    repo = DomainRepository(pool)
    await repo.delete(str(client_id), str(domain_id))
    return None
