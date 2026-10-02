"""Unit tests for SaaS user audit event recording."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from geo_common.auth import AuthenticatedUser

from routers.audit import AuditEventCreate, create_audit_event


class FakeRequest:
    def __init__(self) -> None:
        self.client = SimpleNamespace(host="127.0.0.1")
        self.headers = {"user-agent": "pytest-browser"}
        self.app = SimpleNamespace(
            state=SimpleNamespace(audit_writer=FakeWriter())
        )


class FakeWriter:
    def __init__(self) -> None:
        self.events = []

    def enqueue(self, event):
        self.events.append(event)
        return True


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_create_audit_event_records_saas_user_action() -> None:
    request = FakeRequest()
    user = AuthenticatedUser(
        id="77246f8b-84b8-4e3b-a085-7a79b7a1e825",
        email="gotyechen@gmail.com",
        google_sub="google-sub",
        name="Lancelot Chen",
        avatar_url=None,
        is_active=True,
    )
    data = AuditEventCreate(
        client_id="b0e10518-5f70-426f-b09e-dbe025984ba1",
        event_type="api_action",
        action_key="agents.chat.submit",
        action_label="Start Agent Chat",
        route="/agents/chat",
        method="POST",
        status_code=200,
        metadata={"entry_point": "chat"},
    )

    result = await create_audit_event(
        data=data,
        request=request,
        user=user,
    )

    assert result.accepted is True
    event = request.app.state.audit_writer.events[0]
    assert event["action_key"] == "agents.chat.submit"
    assert event["metadata"] == {"entry_point": "chat"}
    assert event["user_id"] == user.id
    assert event["client_id"] == data.client_id
