"""Admin mutations are audited after the business response, never inline."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.responses import Response
from geo_common.auth import AuthenticatedUser
from starlette.requests import Request

import main as admin_main


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Writer:
    def __init__(self) -> None:
        self.events = []

    def enqueue(self, event):
        self.events.append(event)
        return True


def _request(method: str = "PUT") -> tuple[Request, Writer]:
    writer = Writer()
    app = SimpleNamespace(state=SimpleNamespace(audit_writer=writer))
    path = "/api/clients/client-id/brands/brand-id/aliases"
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
            "app": app,
            "path_params": {
                "client_id": "b0e10518-5f70-426f-b09e-dbe025984ba1",
                "brand_id": "6f758eb6-8d0a-49dc-88da-267fb1ead848",
            },
            "route": SimpleNamespace(
                path="/api/clients/{client_id}/brands/{brand_id}/aliases"
            ),
        }
    )
    request.state.current_user = AuthenticatedUser(
        id="77246f8b-84b8-4e3b-a085-7a79b7a1e825",
        email="admin@example.com",
        google_sub="admin-sub",
        name="Admin",
        avatar_url=None,
        is_active=True,
    )
    return request, writer


@pytest.mark.anyio
async def test_admin_mutation_enqueues_after_primary_response(monkeypatch) -> None:
    request, writer = _request()
    monkeypatch.setattr(admin_main.app.state, "audit_writer", writer, raising=False)

    async def call_next(_request):
        assert writer.events == []
        return Response(status_code=200)

    response = await admin_main.enqueue_admin_user_audit(request, call_next)
    assert response.status_code == 200
    assert len(writer.events) == 1
    assert writer.events[0]["route"] == (
        "/api/clients/{client_id}/brands/{brand_id}/aliases"
    )


@pytest.mark.anyio
async def test_scheduler_identity_is_not_recorded_as_user_behavior(monkeypatch) -> None:
    request, writer = _request("POST")
    monkeypatch.setattr(admin_main.app.state, "audit_writer", writer, raising=False)
    request.state.system_job_auth = True

    async def call_next(_request):
        return Response(status_code=200)

    await admin_main.enqueue_admin_user_audit(request, call_next)
    assert writer.events == []
