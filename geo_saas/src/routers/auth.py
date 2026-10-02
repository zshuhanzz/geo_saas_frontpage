"""SaaS Google credential exchange and server-side Session lifecycle."""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from geo_common.auth import (
    SAAS_SESSION_COOKIE_NAME,
    SAAS_SESSION_TTL_SECONDS,
    AuthenticatedUser,
    CreatedUserSession,
    create_user_session,
    end_user_session,
    session_audit_event,
    upsert_google_user,
    verify_google_id_token,
)
from pydantic import BaseModel, Field

from pool import get_pool

router = APIRouter(prefix="/auth")


class GoogleSessionCreate(BaseModel):
    credential: str = Field(min_length=1)


class SessionUserOut(BaseModel):
    id: str
    email: str
    google_sub: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    is_active: bool


class SessionLoginOut(BaseModel):
    user: SessionUserOut
    expires_at: datetime


class SessionLogoutOut(BaseModel):
    ok: bool = True


def _google_client_id() -> str:
    value = (
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        or os.environ.get("GOOGLE_CLIENT_ID")
        or os.environ.get("VITE_GOOGLE_CLIENT_ID")
    )
    if not value:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth client ID is not configured on the API server",
        )
    return value


def _allowed_origins() -> set[str]:
    raw_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
    configured = {
        value.strip().rstrip("/")
        for value in raw_origins.split(",")
        if value.strip()
    }
    if configured:
        return configured
    # Development fallback supports checked-in Vite and Codex E2E ports.
    return {
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in (5173, 5174, 6173, 6174)
    }


def _require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").strip().rstrip("/")
    if not origin or origin not in _allowed_origins():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "untrusted_origin",
                "message": "Session request origin is not allowed",
            },
        )


def _request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None)


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",", 1)[0].strip().lower() == "https" or (
        request.url.scheme == "https"
    )


def _enqueue_auth_audit(
    request: Request,
    *,
    user_id: str,
    session_id: str,
    action_key: str,
    status_code: int,
    expires_at: datetime | None = None,
    reason: str | None = None,
) -> None:
    app = request.scope.get("app")
    writer = getattr(getattr(app, "state", None), "audit_writer", None)
    if writer is None:
        return
    writer.enqueue(
        session_audit_event(
            user_id=user_id,
            session_id=session_id,
            session_scope="saas",
            action_key=action_key,
            route=request.url.path,
            method=request.method,
            status_code=status_code,
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
            reason=reason,
            expires_at=expires_at,
        )
    )


@router.post("/session", response_model=SessionLoginOut)
async def create_session(
    data: GoogleSessionCreate,
    request: Request,
    response: Response,
    pool=Depends(get_pool),
) -> SessionLoginOut:
    """Verify Google once, authorize SaaS access, then issue a 24h cookie."""
    _require_trusted_origin(request)
    try:
        claims = verify_google_id_token(data.credential, _google_client_id())
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "google_token_invalid", "message": "Google login failed"},
        ) from exc

    user = await upsert_google_user(pool, claims)
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail={"code": "user_inactive", "message": "User is inactive"},
        )

    has_access = await pool.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM geo_client_user_access
            WHERE user_id = $1::uuid
              AND is_active = true
            UNION ALL
            SELECT 1
            FROM geo_admin_user_access
            WHERE user_id = $1::uuid
              AND role = 'super_admin'
              AND support_all_clients = true
              AND is_active = true
        )
        """,
        user.id,
    )
    if not has_access:
        raise HTTPException(
            status_code=403,
            detail={"code": "saas_access_required", "message": "SaaS access required"},
        )

    created = await create_user_session(
        pool,
        user_id=user.id,
        session_scope="saas",
        ttl_seconds=SAAS_SESSION_TTL_SECONDS,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        key=SAAS_SESSION_COOKIE_NAME,
        value=created.token,
        max_age=SAAS_SESSION_TTL_SECONDS,
        expires=SAAS_SESSION_TTL_SECONDS,
        path="/",
        secure=_is_secure_request(request),
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    _enqueue_auth_audit(
        request,
        user_id=user.id,
        session_id=created.session_id,
        action_key="auth.login_succeeded",
        status_code=200,
        expires_at=created.expires_at,
    )
    return SessionLoginOut(
        user=SessionUserOut(**user.__dict__),
        expires_at=created.expires_at,
    )


@router.post("/logout", response_model=SessionLogoutOut)
async def logout_session(
    request: Request,
    response: Response,
    pool=Depends(get_pool),
) -> SessionLogoutOut:
    """End only the current SaaS Session; repeated logout is harmless."""
    _require_trusted_origin(request)
    token = request.cookies.get(SAAS_SESSION_COOKIE_NAME)
    ended = None
    if token:
        ended = await end_user_session(
            pool,
            token=token,
            expected_scope="saas",
            reason="logout",
        )
    response.delete_cookie(
        key=SAAS_SESSION_COOKIE_NAME,
        path="/",
        secure=_is_secure_request(request),
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    if ended:
        end_reason = str(ended["end_reason"])
        _enqueue_auth_audit(
            request,
            user_id=str(ended["user_id"]),
            session_id=str(ended["session_id"]),
            action_key=(
                "auth.session_expired"
                if end_reason == "expired"
                else "auth.logout"
            ),
            status_code=200,
            expires_at=ended["expires_at"],
            reason=end_reason,
        )
    return SessionLogoutOut()
