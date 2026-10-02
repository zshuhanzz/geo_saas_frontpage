"""Workspace entitlement and role checks at the SaaS API boundary."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from geo_common.auth import AuthenticatedUser, WorkspaceAccess
from starlette.requests import Request

from dependencies import auth


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request(method: str, path: str, query: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id="77246f8b-84b8-4e3b-a085-7a79b7a1e825",
        email="viewer@example.com",
        google_sub="viewer-sub",
        name="Viewer",
        avatar_url=None,
        is_active=True,
    )


@pytest.mark.anyio
async def test_viewer_can_read_prompt_report(monkeypatch) -> None:
    access = WorkspaceAccess(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        role="viewer",
        enabled_features=frozenset({"analytics.prompts"}),
    )

    async def fake_access(*args):
        return access

    monkeypatch.setattr(auth, "get_workspace_access_or_legacy_full", fake_access)
    request = _request(
        "GET",
        "/api/prompts",
        f"client_id={access.client_id}",
    )
    result = await auth.require_feature_access_if_present(
        request,
        user=_user(),
        pool=object(),
    )
    assert result.email == "viewer@example.com"
    assert request.state.feature_key == "analytics.prompts"


@pytest.mark.anyio
async def test_viewer_cannot_modify_prompt_configuration(monkeypatch) -> None:
    access = WorkspaceAccess(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        role="viewer",
        enabled_features=frozenset({"analytics.prompts"}),
    )

    async def fake_access(*args):
        return access

    monkeypatch.setattr(auth, "get_workspace_access_or_legacy_full", fake_access)
    request = _request(
        "POST",
        "/api/prompts",
        f"client_id={access.client_id}",
    )
    with pytest.raises(HTTPException) as exc:
        await auth.require_feature_access_if_present(
            request,
            user=_user(),
            pool=object(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "role_capability_denied"


@pytest.mark.anyio
async def test_workspace_entitlement_denial_precedes_role(monkeypatch) -> None:
    access = WorkspaceAccess(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        role="admin",
        enabled_features=frozenset(),
    )

    async def fake_access(*args):
        return access

    monkeypatch.setattr(auth, "get_workspace_access_or_legacy_full", fake_access)
    request = _request(
        "GET",
        "/api/insights/overview",
        f"client_id={access.client_id}",
    )
    with pytest.raises(HTTPException) as exc:
        await auth.require_feature_access_if_present(
            request,
            user=_user(),
            pool=object(),
        )
    assert exc.value.detail["code"] == "workspace_feature_locked"
