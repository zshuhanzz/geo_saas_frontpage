"""Admin Access Control API.

Manages Google user registry rows, SaaS client grants, and Admin system roles.
Read access is available to Admin Viewer/Super Admin; mutations are restricted
by the application-level Admin request dependency in ``main.py``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from geo_common.auth import (
    AuthenticatedUser,
    SessionScope,
    normalize_email,
    revoke_user_sessions,
    session_audit_event,
)
from pydantic import BaseModel, Field, field_validator

from dependencies.auth import require_current_user, require_super_admin
from pool import get_pool

router = APIRouter(prefix="/access-control", tags=["Access Control"])

ClientRole = Literal["admin", "viewer", "account_manager"]
AdminRole = Literal["super_admin", "viewer"]


class UserOut(BaseModel):
    id: str
    email: str
    google_sub: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    quota_limit: Optional[int] = None
    is_active: bool
    joined_at: Optional[str] = None
    last_login_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class UserUpsert(BaseModel):
    email: str
    name: Optional[str] = None
    quota_limit: Optional[int] = Field(default=None, ge=0)
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Valid email is required")
        return normalized


class ClientAccessOut(BaseModel):
    id: str
    user_id: str
    email: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    client_id: str
    client_name: str
    role: ClientRole
    is_active: bool
    granted_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ClientAccessUpsert(BaseModel):
    user_id: UUID
    client_id: UUID
    role: ClientRole = "admin"
    is_active: bool = True


class ClientAccessUpdate(BaseModel):
    role: Optional[ClientRole] = None
    is_active: Optional[bool] = None


class AdminAccessOut(BaseModel):
    id: str
    user_id: str
    email: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: AdminRole
    support_all_clients: bool
    is_active: bool
    granted_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminAccessUpsert(BaseModel):
    user_id: UUID
    role: AdminRole
    support_all_clients: bool = False
    is_active: bool = True


class AdminAccessUpdate(BaseModel):
    role: Optional[AdminRole] = None
    support_all_clients: Optional[bool] = None
    is_active: Optional[bool] = None


class MeOut(BaseModel):
    user: UserOut
    admin_access: AdminAccessOut


class UserAuditEventOut(BaseModel):
    id: str
    user_id: str
    email: str
    name: Optional[str] = None
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    event_type: str
    action_key: str
    action_label: Optional[str] = None
    route: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class UserAuditPageOut(BaseModel):
    items: list[UserAuditEventOut]
    total: int
    page: int
    page_size: int


def _serialize_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key, value in list(data.items()):
        if isinstance(value, UUID):
            data[key] = str(value)
        elif isinstance(value, datetime):
            data[key] = value.isoformat()
        elif hasattr(value, "isoformat"):
            data[key] = value.isoformat()
        elif key == "metadata" and isinstance(value, str):
            data[key] = json.loads(value)
    return data


def _build_user_audit_filters(
    client_search: Optional[str],
    user_search: Optional[str],
    page: int,
    page_size: int,
) -> tuple[str, list[Any], int, int]:
    params: list[Any] = []
    where: list[str] = []
    if client_search and client_search.strip():
        params.append(f"%{client_search.strip()}%")
        where.append(f"c.name ILIKE ${len(params)}")
    if user_search and user_search.strip():
        params.append(f"%{user_search.strip()}%")
        where.append(
            f"(u.email ILIKE ${len(params)} OR u.name ILIKE ${len(params)})"
        )
    limit = min(max(page_size, 1), 100)
    safe_page = max(page, 1)
    offset = (safe_page - 1) * limit
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return where_sql, params, limit, offset


def _validate_admin_role_support(role: AdminRole, support_all_clients: bool) -> None:
    if support_all_clients and role != "super_admin":
        raise HTTPException(
            status_code=400,
            detail="support_all_clients can only be enabled for Super Admin",
        )


async def _ensure_not_last_active_super_admin(db: Any, user_id: str) -> None:
    current = await db.fetchrow(
        """
        SELECT role, is_active
        FROM geo_admin_user_access
        WHERE user_id = $1::uuid
        """,
        user_id,
    )
    if not current or current["role"] != "super_admin" or not current["is_active"]:
        return
    count_row = await db.fetchrow(
        """
        SELECT COUNT(*) AS count
        FROM geo_admin_user_access
        WHERE role = 'super_admin'
          AND is_active = true
        """
    )
    count = int(count_row["count"]) if count_row else 0
    if count <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove or deactivate the last active Super Admin",
        )


async def _revoke_and_audit_sessions(
    request: Request,
    db: Any,
    *,
    user_id: str,
    session_scope: SessionScope | None,
) -> None:
    transitions = await revoke_user_sessions(
        db,
        user_id=user_id,
        session_scope=session_scope,
    )
    writer = getattr(request.app.state, "audit_writer", None)
    if writer is None:
        return
    for transition in transitions:
        writer.enqueue(
            session_audit_event(
                user_id=transition.user_id,
                session_id=transition.session_id,
                session_scope=transition.session_scope,
                action_key="auth.session_revoked",
                route=request.url.path,
                method=request.method,
                status_code=200,
                reason=transition.end_reason,
                expires_at=transition.expires_at,
                ip_address=request.headers.get("x-forwarded-for", "").split(",", 1)[0]
                or (request.client.host if request.client else None),
                user_agent=request.headers.get("user-agent"),
            )
        )


@router.get("/me", response_model=MeOut)
async def get_me(
    current_user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> MeOut:
    user_row = await pool.fetchrow(
        """
        SELECT id, email, google_sub, name, avatar_url, quota_limit, is_active,
               joined_at, last_login_at, created_at, updated_at
        FROM geo_users
        WHERE id = $1::uuid
        """,
        current_user.id,
    )
    access_row = await pool.fetchrow(
        """
        SELECT a.id, a.user_id, u.email, u.name, u.avatar_url, a.role,
               a.support_all_clients, a.is_active, a.granted_at,
               a.created_at, a.updated_at
        FROM geo_admin_user_access a
        JOIN geo_users u ON u.id = a.user_id
        WHERE a.user_id = $1::uuid
        """,
        current_user.id,
    )
    if not user_row or not access_row:
        raise HTTPException(status_code=403, detail="Admin access required")
    return MeOut(
        user=UserOut(**_serialize_row(user_row)),
        admin_access=AdminAccessOut(**_serialize_row(access_row)),
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    search: Optional[str] = None,
    active_only: bool = False,
    pool=Depends(get_pool),
) -> list[UserOut]:
    params: list[Any] = []
    where: list[str] = []
    if search:
        params.append(f"%{search.strip()}%")
        where.append(f"(email ILIKE ${len(params)} OR name ILIKE ${len(params)})")
    if active_only:
        where.append("is_active = true")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = await pool.fetch(
        f"""
        SELECT id, email, google_sub, name, avatar_url, quota_limit, is_active,
               joined_at, last_login_at, created_at, updated_at
        FROM geo_users
        {where_sql}
        ORDER BY joined_at DESC, email ASC
        LIMIT 200
        """,
        *params,
    )
    return [UserOut(**_serialize_row(row)) for row in rows]


@router.post("/users", response_model=UserOut, dependencies=[Depends(require_super_admin)])
async def upsert_user(
    data: UserUpsert,
    request: Request,
    pool=Depends(get_pool),
) -> UserOut:
    existing = await pool.fetchrow(
        "SELECT id FROM geo_users WHERE LOWER(email) = LOWER($1)",
        normalize_email(str(data.email)),
    )
    if existing and not data.is_active:
        await _ensure_not_last_active_super_admin(pool, str(existing["id"]))
    row = await pool.fetchrow(
        """
        INSERT INTO geo_users (email, name, quota_limit, is_active)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (LOWER(email)) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, geo_users.name),
            quota_limit = EXCLUDED.quota_limit,
            is_active = EXCLUDED.is_active,
            updated_at = NOW()
        RETURNING id, email, google_sub, name, avatar_url, quota_limit, is_active,
                  joined_at, last_login_at, created_at, updated_at
        """,
        normalize_email(str(data.email)),
        data.name,
        data.quota_limit,
        data.is_active,
    )
    if existing and not data.is_active:
        await _revoke_and_audit_sessions(
            request,
            pool,
            user_id=str(row["id"]),
            session_scope=None,
        )
    return UserOut(**_serialize_row(row))


@router.put("/users/{user_id}", response_model=UserOut, dependencies=[Depends(require_super_admin)])
async def update_user(
    user_id: UUID,
    data: UserUpsert,
    request: Request,
    pool=Depends(get_pool),
) -> UserOut:
    if not data.is_active:
        await _ensure_not_last_active_super_admin(pool, str(user_id))
    row = await pool.fetchrow(
        """
        UPDATE geo_users
        SET email = $2,
            name = $3,
            quota_limit = $4,
            is_active = $5,
            updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING id, email, google_sub, name, avatar_url, quota_limit, is_active,
                  joined_at, last_login_at, created_at, updated_at
        """,
        str(user_id),
        normalize_email(str(data.email)),
        data.name,
        data.quota_limit,
        data.is_active,
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if not data.is_active:
        await _revoke_and_audit_sessions(
            request,
            pool,
            user_id=str(user_id),
            session_scope=None,
        )
    return UserOut(**_serialize_row(row))


@router.get("/user-audit", response_model=UserAuditPageOut)
async def list_user_audit(
    client_search: Optional[str] = None,
    user_search: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
    pool=Depends(get_pool),
) -> UserAuditPageOut:
    where_sql, params, limit, offset = _build_user_audit_filters(
        client_search=client_search,
        user_search=user_search,
        page=page,
        page_size=page_size,
    )
    total = await pool.fetchval(
        f"""
        SELECT COUNT(*)
        FROM geo_user_audit_events e
        JOIN geo_users u ON u.id = e.user_id
        LEFT JOIN geo_clients c ON c.id = e.client_id
        {where_sql}
        """,
        *params,
    )
    rows = await pool.fetch(
        f"""
        SELECT e.id, e.user_id, u.email, u.name,
               e.client_id, c.name AS client_name,
               e.event_type, e.action_key, e.action_label, e.route,
               e.method, e.status_code, e.target_type, e.target_id,
               e.metadata, e.created_at
        FROM geo_user_audit_events e
        JOIN geo_users u ON u.id = e.user_id
        LEFT JOIN geo_clients c ON c.id = e.client_id
        {where_sql}
        ORDER BY e.created_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params,
        limit,
        offset,
    )
    return UserAuditPageOut(
        items=[UserAuditEventOut(**_serialize_row(row)) for row in rows],
        total=int(total or 0),
        page=max(page, 1),
        page_size=limit,
    )


@router.get("/client-access", response_model=list[ClientAccessOut])
async def list_client_access(
    search: Optional[str] = None,
    client_id: Optional[UUID] = None,
    active_only: bool = False,
    pool=Depends(get_pool),
) -> list[ClientAccessOut]:
    params: list[Any] = []
    where: list[str] = []
    if search:
        params.append(f"%{search.strip()}%")
        where.append(
            f"(u.email ILIKE ${len(params)} OR u.name ILIKE ${len(params)} OR c.name ILIKE ${len(params)})"
        )
    if client_id:
        params.append(str(client_id))
        where.append(f"a.client_id = ${len(params)}::uuid")
    if active_only:
        where.append("a.is_active = true")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = await pool.fetch(
        f"""
        SELECT a.id, a.user_id, u.email, u.name, u.avatar_url,
               a.client_id, c.name AS client_name, a.role, a.is_active,
               a.granted_at, a.created_at, a.updated_at
        FROM geo_client_user_access a
        JOIN geo_users u ON u.id = a.user_id
        JOIN geo_clients c ON c.id = a.client_id
        {where_sql}
        ORDER BY a.granted_at DESC
        LIMIT 300
        """,
        *params,
    )
    return [ClientAccessOut(**_serialize_row(row)) for row in rows]


@router.post(
    "/client-access",
    response_model=ClientAccessOut,
    dependencies=[Depends(require_super_admin)],
)
async def upsert_client_access(
    data: ClientAccessUpsert,
    current_user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> ClientAccessOut:
    row = await pool.fetchrow(
        """
        INSERT INTO geo_client_user_access
            (user_id, client_id, role, is_active, granted_by)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5::uuid)
        ON CONFLICT (client_id, user_id) DO UPDATE SET
            role = EXCLUDED.role,
            is_active = EXCLUDED.is_active,
            granted_by = EXCLUDED.granted_by,
            granted_at = NOW(),
            updated_at = NOW()
        RETURNING id
        """,
        str(data.user_id),
        str(data.client_id),
        data.role,
        data.is_active,
        current_user.id,
    )
    return await _get_client_access_by_id(pool, str(row["id"]))


@router.put(
    "/client-access/{access_id}",
    response_model=ClientAccessOut,
    dependencies=[Depends(require_super_admin)],
)
async def update_client_access(
    access_id: UUID,
    data: ClientAccessUpdate,
    pool=Depends(get_pool),
) -> ClientAccessOut:
    current = await pool.fetchrow(
        "SELECT role, is_active FROM geo_client_user_access WHERE id = $1::uuid",
        str(access_id),
    )
    if not current:
        raise HTTPException(status_code=404, detail="Client access not found")
    row = await pool.fetchrow(
        """
        UPDATE geo_client_user_access
        SET role = COALESCE($2, role),
            is_active = COALESCE($3, is_active),
            updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING id
        """,
        str(access_id),
        data.role,
        data.is_active,
    )
    return await _get_client_access_by_id(pool, str(row["id"]))


@router.delete(
    "/client-access/{access_id}",
    response_model=ClientAccessOut,
    dependencies=[Depends(require_super_admin)],
)
async def remove_client_access(
    access_id: UUID,
    pool=Depends(get_pool),
) -> ClientAccessOut:
    row = await pool.fetchrow(
        """
        WITH deleted AS (
            DELETE FROM geo_client_user_access
            WHERE id = $1::uuid
            RETURNING *
        )
        SELECT d.id, d.user_id, u.email, u.name, u.avatar_url,
               d.client_id, c.name AS client_name, d.role, d.is_active,
               d.granted_at, d.created_at, d.updated_at
        FROM deleted d
        JOIN geo_users u ON u.id = d.user_id
        JOIN geo_clients c ON c.id = d.client_id
        """,
        str(access_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Client access not found")
    return ClientAccessOut(**_serialize_row(row))


@router.get("/admin-access", response_model=list[AdminAccessOut])
async def list_admin_access(
    search: Optional[str] = None,
    active_only: bool = False,
    pool=Depends(get_pool),
) -> list[AdminAccessOut]:
    params: list[Any] = []
    where: list[str] = []
    if search:
        params.append(f"%{search.strip()}%")
        where.append(f"(u.email ILIKE ${len(params)} OR u.name ILIKE ${len(params)})")
    if active_only:
        where.append("a.is_active = true")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = await pool.fetch(
        f"""
        SELECT a.id, a.user_id, u.email, u.name, u.avatar_url, a.role,
               a.support_all_clients, a.is_active, a.granted_at,
               a.created_at, a.updated_at
        FROM geo_admin_user_access a
        JOIN geo_users u ON u.id = a.user_id
        {where_sql}
        ORDER BY a.granted_at DESC
        LIMIT 200
        """,
        *params,
    )
    return [AdminAccessOut(**_serialize_row(row)) for row in rows]


@router.post(
    "/admin-access",
    response_model=AdminAccessOut,
    dependencies=[Depends(require_super_admin)],
)
async def upsert_admin_access(
    data: AdminAccessUpsert,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> AdminAccessOut:
    _validate_admin_role_support(data.role, data.support_all_clients)
    current = await pool.fetchrow(
        """
        SELECT role, is_active
        FROM geo_admin_user_access
        WHERE user_id = $1::uuid
        """,
        str(data.user_id),
    )
    if current and current["role"] == "super_admin" and current["is_active"]:
        if data.role != "super_admin" or not data.is_active:
            await _ensure_not_last_active_super_admin(pool, str(data.user_id))
    row = await pool.fetchrow(
        """
        INSERT INTO geo_admin_user_access
            (user_id, role, support_all_clients, is_active, granted_by)
        VALUES ($1::uuid, $2, $3, $4, $5::uuid)
        ON CONFLICT (user_id) DO UPDATE SET
            role = EXCLUDED.role,
            support_all_clients = EXCLUDED.support_all_clients,
            is_active = EXCLUDED.is_active,
            granted_by = EXCLUDED.granted_by,
            granted_at = NOW(),
            updated_at = NOW()
        RETURNING id
        """,
        str(data.user_id),
        data.role,
        data.support_all_clients,
        data.is_active,
        current_user.id,
    )
    if not data.is_active:
        await _revoke_and_audit_sessions(
            request,
            pool,
            user_id=str(data.user_id),
            session_scope="admin",
        )
    return await _get_admin_access_by_id(pool, str(row["id"]))


@router.put(
    "/admin-access/{access_id}",
    response_model=AdminAccessOut,
    dependencies=[Depends(require_super_admin)],
)
async def update_admin_access(
    access_id: UUID,
    data: AdminAccessUpdate,
    request: Request,
    pool=Depends(get_pool),
) -> AdminAccessOut:
    current = await pool.fetchrow(
        """
        SELECT user_id, role, support_all_clients, is_active
        FROM geo_admin_user_access
        WHERE id = $1::uuid
        """,
        str(access_id),
    )
    if not current:
        raise HTTPException(status_code=404, detail="Admin access not found")

    next_role = data.role or current["role"]
    next_support = (
        data.support_all_clients
        if data.support_all_clients is not None
        else current["support_all_clients"]
    )
    next_active = data.is_active if data.is_active is not None else current["is_active"]
    _validate_admin_role_support(next_role, next_support)
    if current["role"] == "super_admin" and current["is_active"]:
        if next_role != "super_admin" or not next_active:
            await _ensure_not_last_active_super_admin(pool, str(current["user_id"]))

    row = await pool.fetchrow(
        """
        UPDATE geo_admin_user_access
        SET role = $2,
            support_all_clients = $3,
            is_active = $4,
            updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING id
        """,
        str(access_id),
        next_role,
        next_support,
        next_active,
    )
    if not next_active:
        await _revoke_and_audit_sessions(
            request,
            pool,
            user_id=str(current["user_id"]),
            session_scope="admin",
        )
    return await _get_admin_access_by_id(pool, str(row["id"]))


@router.delete(
    "/admin-access/{access_id}",
    response_model=AdminAccessOut,
    dependencies=[Depends(require_super_admin)],
)
async def remove_admin_access(
    access_id: UUID,
    request: Request,
    pool=Depends(get_pool),
) -> AdminAccessOut:
    current = await pool.fetchrow(
        "SELECT user_id FROM geo_admin_user_access WHERE id = $1::uuid",
        str(access_id),
    )
    if not current:
        raise HTTPException(status_code=404, detail="Admin access not found")
    await _ensure_not_last_active_super_admin(pool, str(current["user_id"]))
    row = await pool.fetchrow(
        """
        WITH deleted AS (
            DELETE FROM geo_admin_user_access
            WHERE id = $1::uuid
            RETURNING *
        )
        SELECT d.id, d.user_id, u.email, u.name, u.avatar_url, d.role,
               d.support_all_clients, d.is_active, d.granted_at,
               d.created_at, d.updated_at
        FROM deleted d
        JOIN geo_users u ON u.id = d.user_id
        """,
        str(access_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Admin access not found")
    await _revoke_and_audit_sessions(
        request,
        pool,
        user_id=str(current["user_id"]),
        session_scope="admin",
    )
    return AdminAccessOut(**_serialize_row(row))


async def _get_client_access_by_id(db: Any, access_id: str) -> ClientAccessOut:
    row = await db.fetchrow(
        """
        SELECT a.id, a.user_id, u.email, u.name, u.avatar_url,
               a.client_id, c.name AS client_name, a.role, a.is_active,
               a.granted_at, a.created_at, a.updated_at
        FROM geo_client_user_access a
        JOIN geo_users u ON u.id = a.user_id
        JOIN geo_clients c ON c.id = a.client_id
        WHERE a.id = $1::uuid
        """,
        access_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Client access not found")
    return ClientAccessOut(**_serialize_row(row))


async def _get_admin_access_by_id(db: Any, access_id: str) -> AdminAccessOut:
    row = await db.fetchrow(
        """
        SELECT a.id, a.user_id, u.email, u.name, u.avatar_url, a.role,
               a.support_all_clients, a.is_active, a.granted_at,
               a.created_at, a.updated_at
        FROM geo_admin_user_access a
        JOIN geo_users u ON u.id = a.user_id
        WHERE a.id = $1::uuid
        """,
        access_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Admin access not found")
    return AdminAccessOut(**_serialize_row(row))
