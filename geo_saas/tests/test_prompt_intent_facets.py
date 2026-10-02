"""Prompt Intent facet route and canonical write integration."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from geo_common.auth import AuthenticatedUser

from dependencies import auth as auth_dependencies
from routers import prompts

CLIENT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TOPIC_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True)
class FakeFacets:
    active: list[str]
    unconfigured: list[str]
    has_unconfigured_blank: bool


class FakeIntentService:
    require_calls: list[str | None] = []
    facet_calls: list[str] = []

    def __init__(self, pool) -> None:
        self.pool = pool

    async def facets(self, client_id: str) -> FakeFacets:
        self.facet_calls.append(client_id)
        return FakeFacets(
            active=["Solution Discovery"],
            unconfigured=["general"],
            has_unconfigured_blank=True,
        )

    async def require_active(self, value: str | None) -> str:
        self.require_calls.append(value)
        if value is None or not value.strip():
            raise prompts.PromptIntentValidationError(
                "Intent is required", code="intent_required"
            )
        if value.strip().casefold() != "solution discovery".casefold():
            raise prompts.PromptIntentValidationError(
                "Intent is not active", code="intent_not_active"
            )
        return "Solution Discovery"

    async def require_active_on_connection(self, conn, value: str | None) -> str:
        return await self.require_active(value)


class FakeDatabase:
    async def fetch_one(self, sql, params=None):
        return {
            "id": params["client_id"],
            "client_prompt_quota": 300,
            "config_platforms": ["chatgpt", "gemini"],
            "config_countries": ["US", "BR"],
        }


class FakeRepo:
    added_rows: list[dict] = []
    updated_rows: list[tuple[str, str | list[str], dict]] = []

    def __init__(self, pool) -> None:
        self.pool = pool

    async def active_prompt_keys_for_client(self, client_id):
        return set()

    async def active_prompt_keys_on_connection(
        self, client_id, conn, *, exclude_prompt_ids=None
    ):
        return set()

    async def owned_topic_ids_on_connection(self, client_id, conn, topic_ids):
        return {str(value) for value in topic_ids}

    async def physical_candidates_on_connection(self, client_id, conn, **kwargs):
        return []

    async def add(self, client_id, **kwargs):
        row = {
            "id": "33333333-3333-3333-3333-333333333333",
            "client_id": client_id,
            "created_at": None,
            "updated_at": None,
            **kwargs,
        }
        self.added_rows.append(row)
        return row

    async def add_on_connection(self, client_id, conn, **kwargs):
        return await self.add(client_id, **kwargs)

    async def add_many(self, client_id, rows):
        self.added_rows.extend(rows)
        return [f"prompt-{index}" for index, _ in enumerate(rows)]

    async def add_many_on_connection(self, client_id, conn, rows):
        return await self.add_many(client_id, rows)

    async def reactivate_on_connection(self, client_id, conn, prompt_ids):
        return []

    async def get_many_on_connection(self, client_id, conn, prompt_ids, **kwargs):
        return [
            {
                "id": str(prompt_id), "client_id": client_id,
                "topic_id": str(TOPIC_ID), "text": "Prompt",
                "intent": "Solution Discovery", "product": None,
                "platform": f"platform-{index}", "country": "US", "language": "en-US",
                "is_active": True, "created_at": None, "updated_at": None,
            }
            for index, prompt_id in enumerate(prompt_ids)
        ]

    async def update_on_connection(self, client_id, conn, prompt_id, *, updates):
        return await self.update(client_id, prompt_id, updates=updates)

    async def update_many_on_connection(self, client_id, conn, prompt_ids, *, updates):
        return await self.update_many(client_id, prompt_ids, updates=updates)

    async def update(self, client_id, prompt_id, *, updates):
        self.updated_rows.append((client_id, prompt_id, dict(updates)))
        return {
            "id": prompt_id,
            "client_id": client_id,
            "topic_id": str(TOPIC_ID),
            "text": "Prompt",
            "intent": updates.get("intent", "Solution Discovery"),
            "product": None,
            "platform": "chatgpt",
            "country": "US",
            "language": "en-US",
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        }

    async def update_many(self, client_id, prompt_ids, *, updates):
        self.updated_rows.append((client_id, list(prompt_ids), dict(updates)))
        return len(prompt_ids)


class _WriteConn:
    async def fetchrow(self, sql, *args):
        if "FROM geo_clients" in sql:
            return {
                "id": args[0],
                "client_prompt_quota": 300,
                "config_platforms": ["chatgpt", "gemini"],
                "config_countries": ["US", "BR"],
                "config_languages": ["en-US"],
            }
        return None

    async def fetch(self, sql, *args):
        return []


class _WriteCoordinator:
    def __init__(self, pool):
        self.pool = pool

    async def execute(self, client_id, operation):
        return await operation(_WriteConn())


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeIntentService.require_calls = []
    FakeIntentService.facet_calls = []
    FakeRepo.added_rows = []
    FakeRepo.updated_rows = []
    monkeypatch.setattr(prompts, "PromptIntentService", FakeIntentService)
    monkeypatch.setattr(prompts, "PromptRepository", FakeRepo)
    monkeypatch.setattr(prompts, "PromptWriteCoordinator", _WriteCoordinator)
    monkeypatch.setattr(prompts, "database", FakeDatabase())


@pytest.mark.anyio
async def test_intent_facets_route_uses_requested_authorized_tenant_context() -> None:
    result = await prompts.get_prompt_intent_facets(client_id=CLIENT_ID, pool=object())

    assert result.active == ["Solution Discovery"]
    assert result.unconfigured == ["general"]
    assert result.has_unconfigured_blank is True
    assert FakeIntentService.facet_calls == [str(CLIENT_ID)]


@pytest.mark.anyio
async def test_single_create_canonicalizes_active_intent_before_write() -> None:
    result = await prompts.create_prompt(
        client_id=CLIENT_ID,
        prompt=prompts.PromptCreateInput(
            topic_id=TOPIC_ID,
            text="Prompt",
            intent=" solution discovery ",
            platform="chatgpt",
            country="US",
            language="en-US",
        ),
        pool=object(),
    )

    assert result.intent == "Solution Discovery"
    assert FakeIntentService.require_calls == [" solution discovery "]
    assert FakeRepo.added_rows[0]["intent"] == "Solution Discovery"


@pytest.mark.anyio
async def test_batch_create_canonicalizes_once_per_logical_input_not_per_variant() -> None:
    result = await prompts.batch_create_prompts(
        client_id=CLIENT_ID,
        data=prompts.BatchPromptCreate(
            prompts=[
                prompts.BatchPromptItemV2(
                    topic_id=TOPIC_ID,
                    text="Prompt",
                    intent="solution discovery",
                    platforms=["chatgpt", "gemini"],
                    countries=["US", "BR"],
                )
            ]
        ),
        pool=object(),
    )

    assert result.created == 4
    assert FakeIntentService.require_calls == ["solution discovery"]
    assert {row["intent"] for row in FakeRepo.added_rows} == {"Solution Discovery"}


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, "", "general"])
async def test_single_create_maps_invalid_or_historical_intent_to_422(
    value: str | None,
) -> None:
    with pytest.raises(HTTPException) as exc:
        await prompts.create_prompt(
            client_id=CLIENT_ID,
            prompt=prompts.PromptCreateInput(
                topic_id=TOPIC_ID,
                text="Prompt",
                intent=value,
                platform="chatgpt",
                country="US",
                language="en-US",
            ),
            pool=object(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] in {"intent_required", "intent_not_active"}
    assert FakeRepo.added_rows == []


@pytest.mark.anyio
async def test_batch_create_rejects_historical_intent_without_writing() -> None:
    with pytest.raises(HTTPException) as exc:
        await prompts.batch_create_prompts(
            client_id=CLIENT_ID,
            data=prompts.BatchPromptCreate(
                prompts=[
                    prompts.BatchPromptItemV2(
                        topic_id=TOPIC_ID,
                        text="Prompt",
                        intent="general",
                        platforms=["chatgpt"],
                        countries=["US"],
                    )
                ]
            ),
            pool=object(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "intent_not_active"
    assert FakeRepo.added_rows == []


@pytest.mark.anyio
async def test_single_update_canonicalizes_active_intent_before_write() -> None:
    prompt_id = UUID("33333333-3333-3333-3333-333333333333")

    result = await prompts.update_prompt(
        client_id=CLIENT_ID,
        prompt_id=prompt_id,
        prompt=prompts.PromptUpdateInput(intent=" solution discovery "),
        pool=object(),
    )

    assert result.intent == "Solution Discovery"
    assert FakeIntentService.require_calls == [" solution discovery "]
    assert FakeRepo.updated_rows == [
        (
            str(CLIENT_ID),
            str(prompt_id),
            {"intent": "Solution Discovery"},
        )
    ]


@pytest.mark.anyio
async def test_batch_update_canonicalizes_active_intent_before_write() -> None:
    prompt_ids = [
        UUID("33333333-3333-3333-3333-333333333333"),
        UUID("44444444-4444-4444-4444-444444444444"),
    ]

    result = await prompts.batch_update_prompts(
        client_id=CLIENT_ID,
        data=prompts.BatchPromptUpdate(
            prompt_ids=prompt_ids,
            updates=prompts.PromptUpdateInput(intent="SOLUTION DISCOVERY"),
        ),
        pool=object(),
    )

    assert result.updated == 2
    assert FakeIntentService.require_calls == ["SOLUTION DISCOVERY"]
    assert FakeRepo.updated_rows == [
        (
            str(CLIENT_ID),
            [str(prompt_id) for prompt_id in prompt_ids],
            {"intent": "Solution Discovery"},
        )
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("route_kind", ["single", "batch"])
@pytest.mark.parametrize("value", ["", "general"])
async def test_update_rejects_blank_or_historical_intent_without_repo_write(
    route_kind: str,
    value: str,
) -> None:
    with pytest.raises(HTTPException) as exc:
        if route_kind == "single":
            await prompts.update_prompt(
                client_id=CLIENT_ID,
                prompt_id=UUID("33333333-3333-3333-3333-333333333333"),
                prompt=prompts.PromptUpdateInput(intent=value),
                pool=object(),
            )
        else:
            await prompts.batch_update_prompts(
                client_id=CLIENT_ID,
                data=prompts.BatchPromptUpdate(
                    prompt_ids=[UUID("33333333-3333-3333-3333-333333333333")],
                    updates=prompts.PromptUpdateInput(intent=value),
                ),
                pool=object(),
            )

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] in {"intent_required", "intent_not_active"}
    assert FakeRepo.updated_rows == []


@pytest.mark.anyio
async def test_intent_facets_dependency_rejects_cross_tenant_before_route(
    monkeypatch,
) -> None:
    async def current_user_override() -> AuthenticatedUser:
        return AuthenticatedUser(
            id="99999999-9999-9999-9999-999999999999",
            email="tester@example.com",
            google_sub="google-sub",
            name="Tester",
            avatar_url=None,
            is_active=True,
        )

    async def deny_client_access(pool, user_id: str, client_id: str) -> bool:
        assert user_id == "99999999-9999-9999-9999-999999999999"
        assert client_id == str(CLIENT_ID)
        return False

    monkeypatch.setattr(auth_dependencies, "has_client_access", deny_client_access)
    app = FastAPI()
    app.include_router(
        prompts.router,
        prefix="/api/prompts",
        dependencies=[Depends(auth_dependencies.require_client_access_if_present)],
    )
    app.dependency_overrides[auth_dependencies.require_current_user] = (
        current_user_override
    )
    app.dependency_overrides[prompts.get_pool] = lambda: object()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/prompts/intent-facets",
            params={"client_id": str(CLIENT_ID)},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "No access to this client"
    assert FakeIntentService.facet_calls == []
