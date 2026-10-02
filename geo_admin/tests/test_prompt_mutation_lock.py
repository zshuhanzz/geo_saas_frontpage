from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException

from routers import prompts


CLIENT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TOPIC_ID = "11111111-1111-1111-1111-111111111111"
PROMPT_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeConn:
    quota = 20

    async def fetchrow(self, sql, *args):
        if "FROM geo_clients" in sql:
            return {
                "id": CLIENT_ID,
                "client_prompt_quota": self.quota,
                "config_platforms": ["chatgpt"],
                "config_countries": ["US"],
                "config_languages": ["en-US"],
            }
        return None


class RecordingCoordinator:
    calls: list[str] = []

    def __init__(self, pool):
        self.pool = pool

    async def execute(self, client_id, operation):
        self.calls.append(str(client_id))
        return await operation(FakeConn())


class FakePromptRepository:
    physical_rows: list[dict] = []
    add_calls = 0
    active_keys: set[tuple[str, str]] = set()

    def __init__(self, pool):
        self.pool = pool

    async def owned_topic_ids_on_connection(self, client_id, conn, topic_ids):
        return {str(value) for value in topic_ids}

    async def active_prompt_keys_on_connection(
        self, client_id, conn, *, exclude_prompt_ids=None
    ):
        return set(self.active_keys)

    async def physical_candidates_on_connection(self, client_id, conn, **kwargs):
        return list(self.physical_rows)

    async def add_on_connection(self, client_id, conn, **kwargs):
        self.__class__.add_calls += 1
        return {
            "id": PROMPT_ID,
            "client_id": client_id,
            "is_active": True,
            **kwargs,
        }

    async def reactivate_on_connection(self, client_id, conn, prompt_ids):
        return []

    async def get_by_id_on_connection(self, client_id, conn, prompt_id, **kwargs):
        return {
            "id": str(prompt_id),
            "client_id": client_id,
            "topic_id": TOPIC_ID,
            "text": "Prompt",
            "intent": "Solution Discovery",
            "product": None,
            "platform": "chatgpt",
            "country": "US",
            "language": "en-US",
            "is_active": True,
        }

    async def update_on_connection(self, client_id, conn, prompt_id, *, updates):
        return {"id": str(prompt_id), **updates}

    async def delete_on_connection(self, client_id, conn, prompt_id):
        return True


class FakePromptIntentService:
    def __init__(self, pool):
        self.pool = pool

    async def require_active_on_connection(self, conn, value):
        if not value or not value.strip():
            raise prompts.PromptIntentValidationError(
                "Intent is required", code="intent_required"
            )
        return value.strip()


class FakePromptCascadeDeletionService:
    def __init__(self, pool):
        self.pool = pool

    async def delete_many_on_connection(self, client_id, conn, prompt_ids):
        return None


@pytest.fixture(autouse=True)
def prompt_dependencies(monkeypatch):
    RecordingCoordinator.calls = []
    FakePromptRepository.physical_rows = []
    FakePromptRepository.add_calls = 0
    FakePromptRepository.active_keys = set()
    FakeConn.quota = 20
    monkeypatch.setattr(prompts, "PromptWriteCoordinator", RecordingCoordinator)
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)
    monkeypatch.setattr(prompts, "PromptIntentService", FakePromptIntentService)
    monkeypatch.setattr(
        prompts, "PromptCascadeDeletionService", FakePromptCascadeDeletionService
    )


@pytest.mark.anyio
@pytest.mark.parametrize("route_kind", ["create", "update", "delete"])
async def test_admin_prompt_mutations_use_tenant_prompt_write_coordinator(
    monkeypatch, route_kind
):
    async def owner(pool, prompt_id):
        return {"id": str(prompt_id), "client_id": CLIENT_ID}

    monkeypatch.setattr(prompts, "_fetch_prompt_owner", owner)

    if route_kind == "create":
        await prompts.create_prompt(
            prompts.PromptCreate(
                client_id=UUID(CLIENT_ID),
                topic_id=UUID(TOPIC_ID),
                text="Prompt",
                intent="Solution Discovery",
                platform="chatgpt",
                country="US",
                language="en-US",
            ),
            pool=object(),
        )
    elif route_kind == "update":
        await prompts.update_prompt(
            UUID(PROMPT_ID), prompts.PromptUpdate(text="Updated Prompt"), pool=object()
        )
    else:
        await prompts.delete_prompt(UUID(PROMPT_ID), pool=object())

    assert RecordingCoordinator.calls == [CLIENT_ID]


@pytest.mark.anyio
async def test_admin_update_rejects_duplicate_physical_variant(monkeypatch):
    async def owner(pool, prompt_id):
        return {"id": str(prompt_id), "client_id": CLIENT_ID}

    monkeypatch.setattr(prompts, "_fetch_prompt_owner", owner)
    FakePromptRepository.physical_rows = [{
        "id": "44444444-4444-4444-4444-444444444444",
        "client_id": CLIENT_ID,
        "topic_id": TOPIC_ID,
        "text": "Duplicate Prompt",
        "intent": "Solution Discovery",
        "product": None,
        "platform": "chatgpt",
        "country": "US",
        "language": "en-US",
        "is_active": True,
    }]

    with pytest.raises(HTTPException) as exc:
        await prompts.update_prompt(
            UUID(PROMPT_ID),
            prompts.PromptUpdate(text=" duplicate   prompt "),
            pool=object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Prompt identity conflict"


@pytest.mark.anyio
async def test_admin_inactive_create_is_idempotent_for_compatible_inactive_variant():
    FakePromptRepository.physical_rows = [{
        "id": PROMPT_ID,
        "client_id": CLIENT_ID,
        "topic_id": TOPIC_ID,
        "text": "Prompt",
        "intent": "Solution Discovery",
        "product": None,
        "platform": "chatgpt",
        "country": "US",
        "language": "en-US",
        "is_active": False,
    }]

    result = await prompts.create_prompt(
        prompts.PromptCreate(
            client_id=UUID(CLIENT_ID),
            topic_id=UUID(TOPIC_ID),
            text=" prompt ",
            intent="Solution Discovery",
            platform="chatgpt",
            country="US",
            language="en-US",
            is_active=False,
        ),
        pool=object(),
    )

    assert result.id == PROMPT_ID
    assert result.is_active is False
    assert FakePromptRepository.add_calls == 0


@pytest.mark.anyio
async def test_admin_update_quota_keeps_old_key_when_active_sibling_remains(monkeypatch):
    async def owner(pool, prompt_id):
        return {"id": str(prompt_id), "client_id": CLIENT_ID}

    monkeypatch.setattr(prompts, "_fetch_prompt_owner", owner)
    FakeConn.quota = 1
    FakePromptRepository.active_keys = {
        prompts.canonical_prompt_logical_key("Prompt", TOPIC_ID)
    }

    with pytest.raises(HTTPException) as exc:
        await prompts.update_prompt(
            UUID(PROMPT_ID), prompts.PromptUpdate(text="New Prompt"), pool=object()
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Client Prompt quota exceeded"
