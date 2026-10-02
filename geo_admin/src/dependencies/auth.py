"""Admin Session, role, and exact Cloud Scheduler identity dependencies."""

from __future__ import annotations

import os
import logging
import re
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from geo_common.auth import (
    ADMIN_SESSION_COOKIE_NAME,
    AdminAccess,
    AuthenticatedUser,
    SessionAuthError,
    get_admin_access,
    resolve_user_session,
    session_audit_event,
    upsert_google_user,
)

from pool import get_pool

bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
SCHEDULER_JOB_RUN_RE = re.compile(
    r"^/api/clients/[0-9a-fA-F-]{36}/jobs/(collector|analyzer|llm_discovery)/run$"
)


async def _claims_from_dev_bypass(request: Request) -> dict[str, Any] | None:
    dev_email = os.environ.get("DEV_AUTH_USER_EMAIL")
    if not dev_email:
        return None
    header_email = request.headers.get("x-dev-user-email")
    if header_email and header_email.strip().lower() != dev_email.strip().lower():
        raise HTTPException(status_code=403, detail="Invalid dev auth user")
    return {
        "email": dev_email,
        "sub": os.environ.get("DEV_AUTH_USER_SUB", "dev-sub"),
        "name": os.environ.get("DEV_AUTH_USER_NAME", "Dev User"),
        "picture": os.environ.get("DEV_AUTH_USER_PICTURE"),
    }


async def require_current_user(
    request: Request,
    pool=Depends(get_pool),
) -> AuthenticatedUser:
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    claims = await _claims_from_dev_bypass(request)
    if claims is not None:
        user = await upsert_google_user(pool, claims)
        if not user.is_active:
            raise HTTPException(status_code=403, detail="User is inactive")
    else:
        token = request.cookies.get(ADMIN_SESSION_COOKIE_NAME)
        if not token:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "authentication_required",
                    "message": "Authentication required",
                },
            )
        try:
            principal = await resolve_user_session(
                pool,
                token=token,
                expected_scope="admin",
            )
        except SessionAuthError as exc:
            transition = exc.lifecycle_transition
            app = request.scope.get("app")
            writer = getattr(getattr(app, "state", None), "audit_writer", None)
            if transition is not None and writer is not None:
                writer.enqueue(
                    session_audit_event(
                        user_id=transition.user_id,
                        session_id=transition.session_id,
                        session_scope="admin",
                        action_key=(
                            "auth.session_expired"
                            if transition.end_reason == "expired"
                            else "auth.session_revoked"
                        ),
                        route=request.url.path,
                        method=request.method,
                        status_code=401 if exc.code != "user_inactive" else 403,
                        reason=transition.end_reason,
                        expires_at=transition.expires_at,
                        ip_address=request.headers.get("x-forwarded-for", "").split(",", 1)[0]
                        or (request.client.host if request.client else None),
                        user_agent=request.headers.get("user-agent"),
                    )
                )
            raise HTTPException(
                status_code=403 if exc.code == "user_inactive" else 401,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        user = principal.user
        request.state.session_id = principal.session_id
        request.state.session_scope = principal.session_scope
    request.state.current_user = user
    return user


async def require_admin_access(
    request: Request,
    user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> AdminAccess:
    cached = getattr(request.state, "admin_access", None)
    if cached is not None:
        return cached
    access = await get_admin_access(pool, user.id)
    if access is None or not access.is_active:
        raise HTTPException(status_code=403, detail="Admin access required")
    request.state.admin_access = access
    return access


async def require_super_admin(
    access: AdminAccess = Depends(require_admin_access),
) -> AdminAccess:
    if access.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return access


async def require_admin_request_access(
    request: Request,
    access: AdminAccess = Depends(require_admin_access),
) -> AdminAccess:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return access
    if access.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return access


def _scheduler_allowed_audiences(request: Request) -> list[str]:
    audiences = {str(request.url).rstrip("/")}
    admin_api_url = os.environ.get("ADMIN_API_URL", "").strip().rstrip("/")
    if admin_api_url:
        audiences.add(admin_api_url)
        audiences.add(f"{admin_api_url}{request.url.path}".rstrip("/"))
    return [audience for audience in audiences if audience]


def _verify_scheduler_oidc_token(token: str, request: Request) -> dict[str, Any]:
    expected_email = os.environ.get("INVOKER_SERVICE_ACCOUNT", "").strip().lower()
    if not expected_email:
        raise HTTPException(
            status_code=500,
            detail="INVOKER_SERVICE_ACCOUNT is not configured on the API server",
        )

    last_error: Exception | None = None
    for audience in _scheduler_allowed_audiences(request):
        try:
            claims = google_id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                audience,
                clock_skew_in_seconds=120,
            )
        except Exception as exc:
            last_error = exc
            continue

        token_email = str(claims.get("email", "")).strip().lower()
        if token_email != expected_email:
            raise HTTPException(status_code=403, detail="Invalid scheduler identity")
        return claims

    logger.warning(
        "Cloud Scheduler OIDC verification failed for %s: %s",
        request.url.path,
        last_error,
    )
    raise HTTPException(status_code=401, detail="Invalid scheduler token")


async def require_admin_or_scheduler_job_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    pool=Depends(get_pool),
) -> AdminAccess | dict[str, Any]:
    """Allow Super Admin users or Cloud Scheduler service-account calls.

    The scheduler exception is intentionally limited to the job-run endpoints.
    All other Admin API writes still require a Super Admin user.
    """
    if request.method == "POST" and SCHEDULER_JOB_RUN_RE.match(request.url.path):
        if credentials is not None and credentials.credentials:
            try:
                claims = _verify_scheduler_oidc_token(credentials.credentials, request)
                request.state.system_job_auth = True
                return claims
            except HTTPException as exc:
                if exc.status_code == 403:
                    raise
                # The Admin UI uses the same run endpoints for manual one-off
                # jobs. User requests now authenticate with the independent
                # Admin Session cookie, so a non-scheduler Bearer falls through.
                logger.debug(
                    "Request to %s was not a Scheduler OIDC token; trying Admin auth",
                    request.url.path,
                )

    user = await require_current_user(request, pool)
    access = await require_admin_access(request, user, pool)
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return access
    if access.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return access
