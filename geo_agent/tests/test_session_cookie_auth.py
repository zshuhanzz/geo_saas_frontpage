"""Agent user auth reads the SaaS Session cookie, not Google bearer tokens."""

from __future__ import annotations

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from geo_common.auth import AuthenticatedUser, SessionPrincipal
from starlette.requests import Request

from dependencies import auth


def _request(cookie: str = "") -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/agent/tasks",
            "raw_path": b"/api/agent/tasks",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("localhost", 9102),
            "scheme": "http",
        }
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_agent_resolves_saas_cookie(monkeypatch) -> None:
    user = AuthenticatedUser(
        id="8f422899-c4a0-494f-b868-b94fcd5f79d2",
        email="lancelot@example.com",
        google_sub="google-sub",
        name="lancelot",
        avatar_url=None,
        is_active=True,
    )

    async def fake_pool():
        return object()

    async def fake_resolve(pool, *, token, expected_scope):
        assert token == "saas-cookie"
        assert expected_scope == "saas"
        return SessionPrincipal(
            session_id="session-id",
            session_scope="saas",
            expires_at=None,
            user=user,
        )

    monkeypatch.setattr(auth, "get_pool", fake_pool)
    monkeypatch.setattr(auth, "resolve_user_session", fake_resolve)

    result = await auth.require_current_user(
        _request("answerx_saas_session=saas-cookie"),
    )

    assert result.email == "lancelot@example.com"


@pytest.mark.anyio
async def test_agent_cron_keeps_exact_service_identity_bypass(monkeypatch) -> None:
    task_id = "8f422899-c4a0-494f-b868-b94fcd5f79d2"
    request = _request()
    request.scope["method"] = "POST"
    request.scope["path"] = f"/api/agent/tasks/{task_id}/trigger_cron"
    request.scope["raw_path"] = request.scope["path"].encode()

    monkeypatch.setattr(
        auth,
        "_verify_system_job_oidc_token",
        lambda *args, **kwargs: {"email": "scheduler@example.iam.gserviceaccount.com"},
    )

    result = await auth.require_feature_or_system_task_job_access(
        request,
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="scheduler-oidc",
        ),
    )

    assert result["email"] == "scheduler@example.iam.gserviceaccount.com"
    assert request.state.system_job_auth is True
