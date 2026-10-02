"""Admin Google-to-Session exchange contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request
from starlette.responses import Response

from dependencies import auth as auth_dependencies
from routers import auth as auth_router


USER_ID = "8f422899-c4a0-494f-b868-b94fcd5f79d2"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/session",
            "raw_path": b"/api/auth/session",
            "query_string": b"",
            "headers": [
                (b"origin", b"http://localhost:6173"),
                (b"user-agent", b"pytest"),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("localhost", 9100),
            "scheme": "http",
        }
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_admin_login_sets_independent_12_hour_cookie(monkeypatch) -> None:
    user = auth_router.AuthenticatedUser(
        id=USER_ID,
        email="lancelot@example.com",
        google_sub="google-sub",
        name="lancelot",
        avatar_url=None,
        is_active=True,
    )
    access = auth_router.AdminAccess(
        role="super_admin",
        support_all_clients=True,
        is_active=True,
    )
    expires_at = datetime.now(timezone.utc) + timedelta(hours=12)

    monkeypatch.setattr(
        auth_router,
        "verify_google_id_token",
        lambda credential, client_id: {"email": "lancelot@example.com"},
    )

    async def fake_upsert(pool, claims):
        return user

    async def fake_access(pool, user_id):
        return access

    async def fake_create(*args, **kwargs):
        return auth_router.CreatedUserSession(
            session_id="session-id",
            token="raw-cookie-token",
            session_scope="admin",
            user_id=USER_ID,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )

    monkeypatch.setattr(auth_router, "upsert_google_user", fake_upsert)
    monkeypatch.setattr(auth_router, "get_admin_access", fake_access)
    monkeypatch.setattr(auth_router, "create_user_session", fake_create)
    monkeypatch.setattr(auth_router, "_google_client_id", lambda: "google-client")

    response = Response()
    result = await auth_router.create_session(
        data=auth_router.GoogleSessionCreate(credential="google-id-token"),
        request=_request(),
        response=response,
        pool=object(),
    )

    cookie = response.headers["set-cookie"].lower()
    assert "answerx_admin_session=" in cookie
    assert "answerx_saas_session" not in cookie
    assert "httponly" in cookie
    assert "max-age=43200" in cookie
    assert result.user.email == "lancelot@example.com"


@pytest.mark.anyio
async def test_manual_job_run_falls_back_to_admin_session_without_bearer(
    monkeypatch,
) -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": (
                "/api/clients/8f422899-c4a0-494f-b868-b94fcd5f79d2/"
                "jobs/collector/run"
            ),
            "raw_path": b"",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("localhost", 9100),
            "scheme": "http",
        }
    )
    user = auth_dependencies.AuthenticatedUser(
        id=USER_ID,
        email="lancelot@example.com",
        google_sub="google-sub",
        name="lancelot",
        avatar_url=None,
        is_active=True,
    )
    access = auth_dependencies.AdminAccess(
        role="super_admin",
        support_all_clients=True,
        is_active=True,
    )

    async def fake_user(*args):
        return user

    async def fake_access(*args):
        return access

    monkeypatch.setattr(auth_dependencies, "require_current_user", fake_user)
    monkeypatch.setattr(auth_dependencies, "require_admin_access", fake_access)

    result = await auth_dependencies.require_admin_or_scheduler_job_access(
        request,
        credentials=None,
        pool=object(),
    )

    assert result == access
