"""
AI-discovered configuration candidates (Phase 6 — Suggestions 系统).

Phase 2.5b (2026-04-26): SQL fully migrated off SQLAlchemy. All inserts and
status updates use raw SQL via the asyncpg-backed ``database`` adapter.

Three upstream producers (n_gram / llm_batch / auto_discovery) write into
``geo_settings_candidates``. The endpoints here power the per-tab
SuggestionsPanel — list pending, accept (INSERT into the target entity table
+ mark accepted), reject / ignore (status update only).

Accepting a candidate is opinionated about where the row lands::

    candidate_type    → target entity table(s) on accept
    ────────────────  → ──────────────────────────────────
    brand             → geo_client_brands (is_shadow=false)
    shadow_brand      → geo_client_brands (is_shadow=true)
    peer              → geo_client_peers
    own_product       → geo_client_topic_products (product_role='own')
                          — target_topic_id required
    shadow_product    → geo_client_topic_products (product_role='shadow_brand_product')
                          — target_brand_id + target_topic_id required
    peer_product      → geo_client_topic_products (product_role='peer')
                          — target_peer_id + target_topic_id required
    tracked_url       → geo_product_tracked_urls — target_product_id required
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from functools import wraps
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from services.workspace_lifecycle import long_workspace_lifecycle_session
from pydantic import BaseModel

from db import database

from ._helpers import serialize_row

router = APIRouter(tags=["Brand Settings - Candidates"])


# ───────── Output models ─────────


class CandidateOut(BaseModel):
    model_config = {"extra": "allow"}


class CandidateAcceptOut(BaseModel):
    candidate_id: str
    candidate_type: str
    status: str
    result: Dict[str, Any]


class CandidateStatusOut(BaseModel):
    candidate_id: str
    status: str


_VALID_STATUSES = {"pending", "accepted", "rejected", "ignored"}
_VALID_CANDIDATE_TYPES = {
    "brand", "shadow_brand", "peer",
    "own_product", "shadow_product", "peer_product",
    "tracked_url",
}


class CandidateAcceptInput(BaseModel):
    target_topic_id: Optional[UUID] = None
    target_brand_id: Optional[UUID] = None
    target_peer_id: Optional[UUID] = None
    target_product_id: Optional[UUID] = None
    override_string: Optional[str] = None
    url_scope: Optional[str] = None  # for tracked_url accept only


# ───────── List / counts ─────────

@router.get("/candidates", response_model=List[CandidateOut])
async def list_candidates(
    client_id: UUID,
    type: Optional[str] = None,
    status: Optional[str] = "pending",
) -> List[CandidateOut]:
    """List AI-discovered candidates for the client, filtered by type / status.

    Defaults to ``status='pending'`` so the UI only sees un-triaged rows by
    default. Pass ``status=any`` to return all rows regardless of status.
    """
    where_parts = ["client_id = :client_id"]
    params: dict = {"client_id": client_id}
    if type:
        if type not in _VALID_CANDIDATE_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid type: {type}")
        where_parts.append("candidate_type = :type")
        params["type"] = type
    if status and status != "any":
        if status not in _VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
        where_parts.append("status = :status")
        params["status"] = status

    rows = await database.fetch_all(
        f"""
        SELECT * FROM geo_settings_candidates
        WHERE {' AND '.join(where_parts)}
        ORDER BY frequency DESC, last_seen DESC
        """,
        params,
    )
    return [CandidateOut(**serialize_row(r)) for r in rows]


@router.get("/candidates/counts", response_model=Dict[str, int])
async def candidate_counts(client_id: UUID) -> Dict[str, int]:
    """Return a summary of pending candidate counts per ``candidate_type``."""
    rows = await database.fetch_all(
        """
        SELECT candidate_type, COUNT(*)::int AS n
        FROM geo_settings_candidates
        WHERE client_id = :cid AND status = 'pending'
        GROUP BY candidate_type
        """,
        {"cid": client_id},
    )
    return {r["candidate_type"]: r["n"] for r in rows}


# ───────── Internal helpers ─────────

async def _get_candidate_or_404(candidate_id: UUID, client_id: UUID):
    row = await database.fetch_one(
        """
        SELECT * FROM geo_settings_candidates
        WHERE id = :candidate_id AND client_id = :client_id
        """,
        {"candidate_id": candidate_id, "client_id": client_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return row


async def _mark_candidate_status(candidate_id: UUID, client_id: UUID, status: str):
    await database.execute(
        """
        UPDATE geo_settings_candidates
        SET status = :status
        WHERE id = :candidate_id AND client_id = :client_id
        """,
        {"status": status, "candidate_id": candidate_id, "client_id": client_id},
    )


async def _accept_brand_like(
    row, client_id: UUID, candidate_string: str, is_shadow: bool,
) -> dict:
    new_id = uuid4()
    try:
        inserted = await database.fetch_one(
            """
            INSERT INTO geo_client_brands
                (id, client_id, brand_name, aliases, is_shadow, is_active)
            VALUES (:id, :client_id, :brand_name, :aliases, :is_shadow, TRUE)
            RETURNING *
            """,
            {
                "id": new_id,
                "client_id": client_id,
                "brand_name": candidate_string,
                "aliases": [],
                "is_shadow": is_shadow,
            },
        )
    except Exception as exc:
        # UNIQUE (client_id, brand_name) — reuse existing instead of failing.
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            existing = await database.fetch_one(
                """
                SELECT * FROM geo_client_brands
                WHERE client_id = :client_id AND brand_name = :brand_name
                """,
                {"client_id": client_id, "brand_name": candidate_string},
            )
            return {"action": "reused_existing", "brand": serialize_row(existing)}
        raise
    return {"action": "created", "brand": serialize_row(inserted)}


async def _accept_peer(client_id: UUID, candidate_string: str) -> dict:
    new_id = uuid4()
    try:
        inserted = await database.fetch_one(
            """
            INSERT INTO geo_client_peers
                (id, client_id, primary_name, aliases)
            VALUES (:id, :client_id, :primary_name, :aliases)
            RETURNING *
            """,
            {
                "id": new_id,
                "client_id": client_id,
                "primary_name": candidate_string,
                "aliases": [],
            },
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            existing = await database.fetch_one(
                """
                SELECT * FROM geo_client_peers
                WHERE client_id = :client_id AND primary_name = :primary_name
                """,
                {"client_id": client_id, "primary_name": candidate_string},
            )
            return {"action": "reused_existing", "peer": serialize_row(existing)}
        raise
    return {"action": "created", "peer": serialize_row(inserted)}


async def _accept_product(
    client_id: UUID,
    candidate_string: str,
    target_topic_id: UUID,
    product_role: str,
    target_brand_id: Optional[UUID],
    target_peer_id: Optional[UUID],
) -> dict:
    topic = await database.fetch_one(
        """
        SELECT id
        FROM geo_client_topics
        WHERE id = :topic_id
          AND client_id = :client_id
        """,
        {"topic_id": target_topic_id, "client_id": client_id},
    )
    if not topic:
        raise HTTPException(
            status_code=422,
            detail="target_topic_id must reference a Topic in this Workspace",
        )

    if product_role in {"own", "shadow_brand_product"}:
        expected_shadow = product_role == "shadow_brand_product"
        if target_brand_id is None or target_peer_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Product owner does not match the requested product role",
            )
        brand = await database.fetch_one(
            """
            SELECT id, is_shadow, is_active
            FROM geo_client_brands
            WHERE id = :brand_id
              AND client_id = :client_id
              AND is_shadow = :is_shadow
              AND is_active = TRUE
            """,
            {
                "brand_id": target_brand_id,
                "client_id": client_id,
                "is_shadow": expected_shadow,
            },
        )
        if (
            not brand
            or bool(brand.get("is_shadow")) != expected_shadow
            or not brand.get("is_active", False)
        ):
            role_label = "Shadow Brand" if expected_shadow else "Own Brand"
            raise HTTPException(
                status_code=422,
                detail=f"target_brand_id must reference an active {role_label} in this Workspace",
            )
    elif product_role == "peer":
        if target_peer_id is None or target_brand_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Product owner does not match the requested product role",
            )
        peer = await database.fetch_one(
            """
            SELECT id
            FROM geo_client_peers
            WHERE id = :peer_id AND client_id = :client_id
            """,
            {"peer_id": target_peer_id, "client_id": client_id},
        )
        if not peer:
            raise HTTPException(
                status_code=422,
                detail="target_peer_id must reference a Peer in this Workspace",
            )
    else:
        raise HTTPException(status_code=422, detail="Unsupported product_role")

    new_id = uuid4()
    try:
        inserted = await database.fetch_one(
            """
            INSERT INTO geo_client_topic_products
                (id, client_id, topic_id, product_name, match_variants,
                 product_role, shadow_sub_role,
                 owner_brand_id, owner_peer_id, is_active)
            VALUES (:id, :client_id, :topic_id, :product_name, :match_variants,
                    :product_role, NULL,
                    :owner_brand_id, :owner_peer_id, TRUE)
            RETURNING *
            """,
            {
                "id": new_id,
                "client_id": client_id,
                "topic_id": target_topic_id,
                "product_name": candidate_string,
                "match_variants": [candidate_string],
                "product_role": product_role,
                "owner_brand_id": target_brand_id,
                "owner_peer_id": target_peer_id,
            },
        )
    except Exception as exc:
        # Surface DB CHECK constraint violation as actionable for the UI.
        raise HTTPException(
            status_code=422,
            detail=f"Failed to create product row: {exc}",
        )
    return {"action": "created", "product": serialize_row(inserted)}


async def _accept_tracked_url(
    client_id: UUID,
    candidate_string: str,
    target_product_id: UUID,
    url_scope: Optional[str],
) -> dict:
    product = await database.fetch_one(
        """
        SELECT id FROM geo_client_topic_products
        WHERE id = :product_id AND client_id = :client_id
        """,
        {"product_id": target_product_id, "client_id": client_id},
    )
    if not product:
        raise HTTPException(status_code=404, detail="target_product_id not found for this client")

    scope = url_scope or "exact"
    if scope not in {"exact", "path-prefix"}:
        raise HTTPException(status_code=422, detail="url_scope must be 'exact' or 'path-prefix'")

    new_id = uuid4()
    try:
        inserted = await database.fetch_one(
            """
            INSERT INTO geo_product_tracked_urls
                (id, client_id, product_id, url, url_scope)
            VALUES (:id, :client_id, :product_id, :url, :scope)
            RETURNING *
            """,
            {
                "id": new_id,
                "client_id": client_id,
                "product_id": target_product_id,
                "url": candidate_string,
                "scope": scope,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to attach tracked_url: {exc}")
    return {"action": "created", "tracked_url": serialize_row(inserted)}


# ───────── Accept / reject / ignore endpoints ─────────


def _workspace_guarded_candidate_mutation(endpoint):
    @wraps(endpoint)
    async def guarded(client_id: UUID, *args, **kwargs):
        async with long_workspace_lifecycle_session(database.pool(), str(client_id)):
            return await endpoint(client_id, *args, **kwargs)

    return guarded

@router.post("/candidates/{candidate_id}/accept", response_model=CandidateAcceptOut)
@_workspace_guarded_candidate_mutation
async def accept_candidate(
    client_id: UUID, candidate_id: UUID, data: CandidateAcceptInput,
) -> CandidateAcceptOut:
    """Accept a candidate: INSERT into the target entity table + mark accepted."""
    row = await _get_candidate_or_404(candidate_id, client_id)
    if row["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Candidate already in status '{row['status']}'",
        )

    candidate_string = (data.override_string or row["candidate_string"]).strip()
    if not candidate_string:
        raise HTTPException(status_code=422, detail="candidate_string empty after override")
    ctype = row["candidate_type"]

    if ctype == "brand":
        result = await _accept_brand_like(row, client_id, candidate_string, is_shadow=False)
    elif ctype == "shadow_brand":
        result = await _accept_brand_like(row, client_id, candidate_string, is_shadow=True)
    elif ctype == "peer":
        result = await _accept_peer(client_id, candidate_string)
    elif ctype == "own_product":
        if not (data.target_topic_id and data.target_brand_id):
            raise HTTPException(
                status_code=422,
                detail="target_topic_id + target_brand_id required for own_product accept",
            )
        result = await _accept_product(
            client_id, candidate_string, data.target_topic_id,
            "own", target_brand_id=data.target_brand_id, target_peer_id=None,
        )
    elif ctype == "shadow_product":
        if not (data.target_topic_id and data.target_brand_id):
            raise HTTPException(
                status_code=422,
                detail="target_topic_id + target_brand_id required for shadow_product accept",
            )
        result = await _accept_product(
            client_id, candidate_string, data.target_topic_id,
            "shadow_brand_product",
            target_brand_id=data.target_brand_id,
            target_peer_id=None,
        )
    elif ctype == "peer_product":
        if not (data.target_topic_id and data.target_peer_id):
            raise HTTPException(
                status_code=422,
                detail="target_topic_id + target_peer_id required for peer_product accept",
            )
        result = await _accept_product(
            client_id, candidate_string, data.target_topic_id,
            "peer",
            target_brand_id=None,
            target_peer_id=data.target_peer_id,
        )
    elif ctype == "tracked_url":
        if not data.target_product_id:
            raise HTTPException(status_code=422, detail="target_product_id required for tracked_url accept")
        result = await _accept_tracked_url(
            client_id, candidate_string, data.target_product_id, data.url_scope,
        )
    else:
        raise HTTPException(status_code=422, detail=f"Unsupported candidate_type: {ctype}")

    await _mark_candidate_status(candidate_id, client_id, "accepted")
    return CandidateAcceptOut(
        candidate_id=str(candidate_id),
        candidate_type=ctype,
        status="accepted",
        result=result,
    )


@router.post("/candidates/{candidate_id}/reject", response_model=CandidateStatusOut)
@_workspace_guarded_candidate_mutation
async def reject_candidate(
    client_id: UUID, candidate_id: UUID
) -> CandidateStatusOut:
    await _get_candidate_or_404(candidate_id, client_id)
    await _mark_candidate_status(candidate_id, client_id, "rejected")
    return CandidateStatusOut(candidate_id=str(candidate_id), status="rejected")


@router.post("/candidates/{candidate_id}/ignore", response_model=CandidateStatusOut)
@_workspace_guarded_candidate_mutation
async def ignore_candidate(
    client_id: UUID, candidate_id: UUID
) -> CandidateStatusOut:
    await _get_candidate_or_404(candidate_id, client_id)
    await _mark_candidate_status(candidate_id, client_id, "ignored")
    return CandidateStatusOut(candidate_id=str(candidate_id), status="ignored")
