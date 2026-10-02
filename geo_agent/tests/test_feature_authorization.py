"""Agent task_type authorization contracts."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from geo_common.auth import AuthenticatedUser, WorkspaceAccess
from starlette.requests import Request

from dependencies import auth


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request(
    method: str,
    query: str,
    *,
    path: str = "/api/agent/tasks",
) -> Request:
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
            "path_params": {},
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
async def test_viewer_can_read_existing_content_tasks_but_cannot_create(
    monkeypatch,
) -> None:
    client_id = "b0e10518-5f70-426f-b09e-dbe025984ba1"
    access = WorkspaceAccess(
        client_id=client_id,
        role="viewer",
        enabled_features=frozenset({"actions.content"}),
    )

    async def fake_pool():
        return object()

    async def fake_access(*args):
        return access

    monkeypatch.setattr(auth, "get_pool", fake_pool)
    monkeypatch.setattr(auth, "get_workspace_access_or_legacy_full", fake_access)
    query = f"client_id={client_id}&task_type=content_generation"

    allowed = await auth._enforce_agent_feature_access(
        _request("GET", query),
        _user(),
    )
    assert allowed.email == "viewer@example.com"

    denied_request = _request("POST", query)
    with pytest.raises(HTTPException) as exc:
        await auth._enforce_agent_feature_access(
            denied_request,
            _user(),
        )
    assert exc.value.detail["code"] == "role_capability_denied"
    assert denied_request.state.feature_key == "actions.content"
    assert denied_request.state.feature_capability == "execute"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task_type", "expected_feature"),
    [
        ("analysis", "actions.analysis"),
        ("content_generation", "actions.content"),
    ],
)
async def test_shared_task_resources_resolve_explicit_type_to_one_feature(
    task_type: str,
    expected_feature: str,
) -> None:
    request = _request(
        "GET",
        f"client_id=b0e10518-5f70-426f-b09e-dbe025984ba1&type={task_type}",
        path="/api/agent/tasks/templates",
    )

    assert await auth._task_route_feature_keys(request, object()) == {
        expected_feature
    }
