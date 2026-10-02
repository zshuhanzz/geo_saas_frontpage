"""SaaS Google-to-Session exchange contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request
from starlette.responses import Response

from routers import auth as auth_router


USER_ID = "8f422899-c4a0-494f-b868-b94fcd5f79d2"


class AccessPool:
    async def fetchval(self, sql: str, *args):
        assert "geo_client_user_access" in sql
        return True


def _request(origin: str = "http://localhost:6174") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/session",
            "raw_path": b"/api/auth/session",
            "query_string": b"",
            "headers": [
                (b"origin", origin.encode()),
                (b"user-agent", b"pytest"),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("localhost", 9101),
            "scheme": "http",
        }
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_saas_login_sets_24_hour_httponly_cookie(monkeypatch) -> None:
    user = auth_router.AuthenticatedUser(
        id=USER_ID,
        email="lancelot@example.com",
        google_sub="google-sub",
        name="lancelot",
        avatar_url=None,
        is_active=True,
    )
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    monkeypatch.setattr(
        auth_router,
        "verify_google_id_token",
        lambda credential, client_id: {"email": "lancelot@example.com"},
    )

    async def fake_upsert(pool, claims):
        return user

    async def fake_create(*args, **kwargs):
        return auth_router.CreatedUserSession(
            session_id="session-id",
            token="raw-cookie-token",
            session_scope="saas",
            user_id=USER_ID,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )

    monkeypatch.setattr(auth_router, "upsert_google_user", fake_upsert)
    monkeypatch.setattr(auth_router, "create_user_session", fake_create)
    monkeypatch.setattr(auth_router, "_google_client_id", lambda: "google-client")

    response = Response()
    result = await auth_router.create_session(
        data=auth_router.GoogleSessionCreate(credential="google-id-token"),
        request=_request(),
        response=response,
        pool=AccessPool(),
    )

    cookie = response.headers["set-cookie"].lower()
    assert "answerx_saas_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=86400" in cookie
    assert result.user.email == "lancelot@example.com"


@pytest.mark.anyio
async def test_saas_login_rejects_untrusted_origin() -> None:
    with pytest.raises(auth_router.HTTPException) as exc:
        await auth_router.create_session(
            data=auth_router.GoogleSessionCreate(credential="google-id-token"),
            request=_request("https://evil.example"),
            response=Response(),
            pool=AccessPool(),
        )
    assert exc.value.status_code == 403
