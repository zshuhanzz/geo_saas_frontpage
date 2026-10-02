"""HttpOnly Session and Workspace-access dependencies for the SaaS API."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import Depends, HTTPException, Request
from geo_common.auth import (
    SAAS_SESSION_COOKIE_NAME,
    AuthenticatedUser,
    SessionAuthError,
    get_workspace_access_or_legacy_full,
    has_client_access,
    resolve_user_session,
    session_audit_event,
    upsert_google_user,
)
from geo_common.permissions import resolve_backend_policies

from pool import get_pool

logger = logging.getLogger(__name__)


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
        token = request.cookies.get(SAAS_SESSION_COOKIE_NAME)
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
                expected_scope="saas",
            )
        except SessionAuthError as exc:
            transition = exc.lifecycle_transition
            app = request.scope.get("app")
            writer = getattr(getattr(app, "state", None), "audit_writer", None)
            if transition is not None and writer is not None:
                action_key = (
                    "auth.session_expired"
                    if transition.end_reason == "expired"
                    else "auth.session_revoked"
                )
                writer.enqueue(
                    session_audit_event(
                        user_id=transition.user_id,
                        session_id=transition.session_id,
                        session_scope="saas",
                        action_key=action_key,
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


async def _extract_client_id(request: Request) -> str | None:
    value = request.path_params.get("client_id") or request.query_params.get("client_id")
    if value:
        return str(value)
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return None
    try:
        body = await request.json()
    except Exception:
        return None
    if isinstance(body, dict) and body.get("client_id"):
        return str(body["client_id"])
    return None


async def require_client_access_if_present(
    request: Request,
    user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> AuthenticatedUser:
    client_id = await _extract_client_id(request)
    if not client_id:
        return user
    allowed = await has_client_access(pool, user.id, client_id)
    if not allowed:
        raise HTTPException(status_code=403, detail="No access to this client")
    request.state.authorized_client_id = client_id
    return user


async def require_feature_access_if_present(
    request: Request,
    user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> AuthenticatedUser:
    """Enforce Workspace entitlement first, then the user's role capability."""
    client_id = await _extract_client_id(request)
    if (
        not client_id
        and request.url.path.startswith("/api/static-reports/")
        and request.path_params.get("report_id")
    ):
        client_id = await pool.fetchval(
            """
            SELECT client_id::text
            FROM geo_static_reports
            WHERE id = $1::uuid
            """,
            str(request.path_params["report_id"]),
        )
        if not client_id:
            raise HTTPException(status_code=404, detail="Report not found")
    if not client_id:
        # Client discovery and other identity-scoped endpoints run before the
        # frontend has selected a Workspace.
        return user

    access = await get_workspace_access_or_legacy_full(pool, user.id, client_id)
    if access is None:
        raise HTTPException(status_code=403, detail="No access to this client")

    if request.url.path == "/api/audit/events":
        request.state.authorized_client_id = client_id
        request.state.workspace_access = access
        return user

    policies = resolve_backend_policies(
        "saas",
        request.method,
        request.url.path,
    )
    if not policies:
        logger.error(
            "Protected SaaS route is missing from feature registry: %s %s",
            request.method,
            request.url.path,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "feature_route_unregistered",
                "message": "This API route has no registered feature permission",
            },
        )

    # SaaS policies are expected to resolve to exactly one feature at the most
    # specific route level.
    feature, policy = policies[0]
    request.state.authorized_client_id = client_id
    request.state.workspace_access = access
    request.state.feature_key = feature.key
    request.state.feature_capability = policy.capability
    request.state.audit_policy = policy

    if not access.is_entitled(feature.key):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "workspace_feature_locked",
                "feature_key": feature.key,
                "message": "Workspace has not enabled this feature",
            },
        )
    if not access.allows(feature.key, policy.capability):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "role_capability_denied",
                "feature_key": feature.key,
                "required_capability": policy.capability,
                "message": "Your Workspace role does not allow this operation",
            },
        )
    return user
