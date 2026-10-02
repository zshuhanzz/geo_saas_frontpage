"""SaaS Session, Workspace access, and exact system-job dependencies."""

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

from database import get_pool

bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
TASK_CRON_RE = re.compile(
    r"^/api/agent/tasks/([0-9a-fA-F-]{36})/trigger_cron$"
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
) -> AuthenticatedUser:
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    claims = await _claims_from_dev_bypass(request)
    pool = await get_pool()
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
                writer.enqueue(
                    session_audit_event(
                        user_id=transition.user_id,
                        session_id=transition.session_id,
                        session_scope="saas",
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


def user_identifier(user: AuthenticatedUser) -> str:
    if user.google_sub:
        return f"google:{user.google_sub}"
    return f"email:{user.email}"


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
) -> AuthenticatedUser:
    client_id = await _extract_client_id(request)
    if not client_id:
        return user
    pool = await get_pool()
    allowed = await has_client_access(pool, user.id, client_id)
    if not allowed:
        raise HTTPException(status_code=403, detail="No access to this client")
    request.state.authorized_client_id = client_id
    return user


def _feature_key_for_task_type(task_type: str | None) -> str:
    normalized = (task_type or "").strip().lower()
    if normalized in {"content", "content_generation", "opportunity_discovery"}:
        return "actions.content"
    return "actions.analysis"


async def _task_route_feature_keys(
    request: Request,
    pool: Any,
) -> set[str] | None:
    """Resolve generic Agent task routes using task_type semantics."""
    path = request.url.path
    if not path.startswith("/api/agent/tasks"):
        return None

    # More-specific task sub-resources are owned directly by their registry
    # policy and must not be treated as a task UUID.
    static_segments = {
        "templates",
        "workflow-config",
        "framework",
        "metrics",
        "client-platforms",
        "reddit",
        "official-website",
        "prompts",
        "topics",
        "content",
        "generate-strategy",
    }
    suffix = path.removeprefix("/api/agent/tasks").strip("/")
    first_segment = suffix.split("/", 1)[0] if suffix else ""
    if first_segment in static_segments:
        explicit_type = (
            request.query_params.get("task_type")
            or request.query_params.get("type")
        )
        if explicit_type:
            return {_feature_key_for_task_type(explicit_type)}
        return None

    task_id = request.path_params.get("task_id")
    if task_id:
        task_type = await pool.fetchval(
            "SELECT task_type FROM geo_agent_tasks WHERE id = $1::uuid",
            str(task_id),
        )
        if not task_type:
            raise HTTPException(status_code=404, detail="Task not found")
        return {_feature_key_for_task_type(str(task_type))}

    query_types = {
        item.strip()
        for item in str(request.query_params.get("task_types", "")).split(",")
        if item.strip()
    }
    query_type = request.query_params.get("task_type")
    if query_type:
        query_types.add(query_type)
    if query_types:
        return {_feature_key_for_task_type(item) for item in query_types}

    if "application/json" in request.headers.get("content-type", ""):
        try:
            body = await request.json()
        except Exception:
            body = None
        if isinstance(body, dict) and body.get("task_type"):
            return {_feature_key_for_task_type(str(body["task_type"]))}

    # An unfiltered task list can contain both task families, so both grants
    # are required. This prevents leaking rows for an unpurchased feature.
    return {"actions.analysis", "actions.content"}


async def _enforce_agent_feature_access(
    request: Request,
    user: AuthenticatedUser,
) -> AuthenticatedUser:
    pool = await get_pool()
    client_id = await _extract_client_id(request)
    task_id = request.path_params.get("task_id")
    if not client_id and task_id:
        client_id = await pool.fetchval(
            "SELECT client_id::text FROM geo_agent_tasks WHERE id = $1::uuid",
            str(task_id),
        )
    if not client_id:
        return user

    access = await get_workspace_access_or_legacy_full(pool, user.id, str(client_id))
    if access is None:
        raise HTTPException(status_code=403, detail="No access to this client")

    policies = list(
        resolve_backend_policies("agent", request.method, request.url.path)
    )
    if not policies:
        logger.error(
            "Protected Agent route is missing from feature registry: %s %s",
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

    dynamic_keys = await _task_route_feature_keys(request, pool)
    if dynamic_keys is not None:
        policies = [
            (feature, policy)
            for feature, policy in policies
            if feature.key in dynamic_keys
        ]

    if not policies:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "feature_route_unregistered",
                "message": "Task type has no registered feature permission",
            },
        )

    request.state.authorized_client_id = str(client_id)
    request.state.workspace_access = access
    request.state.feature_keys = [feature.key for feature, _ in policies]
    request.state.audit_policy = next(
        (policy for _, policy in policies if policy.audit),
        None,
    )

    # Dynamic generic task routes are filtered to their requested task types
    # and require every requested family. Shared read-only resources such as
    # templates can serve Analysis, Content, or Training and therefore use OR.
    require_all = dynamic_keys is not None
    allowed_policies = [
        (feature, policy)
        for feature, policy in policies
        if access.allows(feature.key, policy.capability)
    ]
    authorized = (
        len(allowed_policies) == len(policies)
        if require_all
        else bool(allowed_policies)
    )
    if not authorized:
        entitled = [
            (feature, policy)
            for feature, policy in policies
            if access.is_entitled(feature.key)
        ]
        if not entitled:
            feature, policy = policies[0]
            request.state.feature_key = feature.key
            request.state.feature_capability = policy.capability
            request.state.audit_policy = policy if policy.audit else None
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "workspace_feature_locked",
                    "feature_key": feature.key,
                    "message": "Workspace has not enabled this feature",
                },
            )
        denied_entitled = [
            (feature, policy)
            for feature, policy in entitled
            if not access.allows(feature.key, policy.capability)
        ]
        feature, policy = denied_entitled[0] if denied_entitled else entitled[0]
        request.state.feature_key = feature.key
        request.state.feature_capability = policy.capability
        request.state.audit_policy = policy if policy.audit else None
        raise HTTPException(
            status_code=403,
            detail={
                "code": "role_capability_denied",
                "feature_key": feature.key,
                "required_capability": policy.capability,
                "message": "Your Workspace role does not allow this operation",
            },
        )
    chosen_feature, chosen_policy = allowed_policies[0]
    request.state.feature_key = chosen_feature.key
    request.state.feature_capability = chosen_policy.capability
    request.state.audit_policy = next(
        (policy for _, policy in allowed_policies if policy.audit),
        None,
    )
    return user


async def require_feature_access_if_present(
    request: Request,
) -> AuthenticatedUser:
    user = await require_current_user(request)
    return await _enforce_agent_feature_access(request, user)


def _system_invoker_email() -> str:
    return (
        os.environ.get("INVOKER_SERVICE_ACCOUNT")
        or os.environ.get("SERVICE_ACCOUNT_EMAIL")
        or ""
    ).strip().lower()


def _system_job_allowed_audiences(request: Request, service_url_env: str) -> list[str]:
    audiences = {
        str(request.url).rstrip("/"),
        f"{request.url.scheme}://{request.url.netloc}{request.url.path}".rstrip("/"),
    }
    service_url = os.environ.get(service_url_env, "").strip().rstrip("/")
    if service_url:
        audiences.add(service_url)
        audiences.add(f"{service_url}{request.url.path}".rstrip("/"))
        if request.url.query:
            audiences.add(f"{service_url}{request.url.path}?{request.url.query}".rstrip("/"))
    return [audience for audience in audiences if audience]


def _verify_system_job_oidc_token(
    token: str,
    request: Request,
    *,
    service_url_env: str,
) -> dict[str, Any]:
    expected_email = _system_invoker_email()
    if not expected_email:
        raise HTTPException(
            status_code=500,
            detail="System job invoker service account is not configured on the API server",
        )

    last_error: Exception | None = None
    for audience in _system_job_allowed_audiences(request, service_url_env):
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
            raise HTTPException(status_code=403, detail="Invalid system job identity")
        return claims

    logger.warning(
        "System job OIDC verification failed for %s: %s",
        request.url.path,
        last_error,
    )
    raise HTTPException(status_code=401, detail="Invalid system job token")


async def _require_task_client_access(
    request: Request,
    task_id: str,
    user: AuthenticatedUser,
) -> AuthenticatedUser:
    pool = await get_pool()
    client_id = await pool.fetchval(
        "SELECT client_id::text FROM geo_agent_tasks WHERE id = $1::uuid",
        task_id,
    )
    if not client_id:
        raise HTTPException(status_code=404, detail="Task not found")
    allowed = await has_client_access(pool, user.id, client_id)
    if not allowed:
        raise HTTPException(status_code=403, detail="No access to this client")
    request.state.authorized_client_id = client_id
    return user


async def require_client_or_system_task_job_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser | dict[str, Any]:
    """Allow Cloud Scheduler service-account calls to Agent task cron endpoints."""
    cron_match = TASK_CRON_RE.match(request.url.path)
    if request.method == "POST" and cron_match:
        if credentials is not None and credentials.credentials:
            try:
                claims = _verify_system_job_oidc_token(
                    credentials.credentials,
                    request,
                    service_url_env="AGENT_API_URL",
                )
                request.state.system_job_auth = True
                return claims
            except HTTPException as exc:
                if exc.status_code == 403:
                    raise
                logger.debug(
                    "Request to %s was not a system-job OIDC token; trying user auth",
                    request.url.path,
                )

        user = await require_current_user(request)
        return await _require_task_client_access(request, cron_match.group(1), user)

    user = await require_current_user(request)
    return await require_client_access_if_present(request, user)


async def require_feature_or_system_task_job_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser | dict[str, Any]:
    """Feature-aware Agent auth with an exact service-identity cron bypass."""
    cron_match = TASK_CRON_RE.match(request.url.path)
    if request.method == "POST" and cron_match:
        if credentials is not None and credentials.credentials:
            try:
                claims = _verify_system_job_oidc_token(
                    credentials.credentials,
                    request,
                    service_url_env="AGENT_API_URL",
                )
                request.state.system_job_auth = True
                request.state.audit_policy = None
                return claims
            except HTTPException as exc:
                if exc.status_code == 403:
                    raise
                logger.debug(
                    "Request to %s was not a system-job OIDC token; trying user auth",
                    request.url.path,
                )

    user = await require_current_user(request)
    return await _enforce_agent_feature_access(request, user)
