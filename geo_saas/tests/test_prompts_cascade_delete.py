from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi import HTTPException
from geo_common.services import PromptWriteCoordinator as RealPromptWriteCoordinator
from pydantic import ValidationError

from routers import prompts


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class FakeDeleteResult:
    deleted_prompts: int


class FakeCascadeService:
    calls = []

    def __init__(self, pool):
        self.pool = pool

    async def delete_many(self, client_id, prompt_ids):
        self.calls.append(("many", str(client_id), [str(pid) for pid in prompt_ids]))
        return FakeDeleteResult(deleted_prompts=len(prompt_ids))

    async def delete_one(self, client_id, prompt_id):
        self.calls.append(("one", str(client_id), str(prompt_id)))
        return FakeDeleteResult(deleted_prompts=1)

    async def delete_many_on_connection(self, client_id, conn, prompt_ids):
        return await self.delete_many(client_id, prompt_ids)


class FakePromptDatabase:
    async def fetch_one(self, sql, params=None):
        return {
            "id": params["client_id"],
            "client_prompt_quota": 300,
            "config_platforms": ["chatgpt", "gemini"],
            "config_countries": ["US", "BR"],
        }


class FakePromptIntentService:
    def __init__(self, pool):
        self.pool = pool

    async def require_active(self, value):
        if not value or not value.strip():
            raise prompts.PromptIntentValidationError(
                "Intent is required",
                code="intent_required",
            )
        return value.strip()

    async def require_active_on_connection(self, conn, value):
        return await self.require_active(value)


class FakePromptRepository:
    count_unique = 0
    active_keys = set()
    added_rows = []
    updated_many = []
    physical_rows = []
    quota = 300

    def __init__(self, pool):
        self.pool = pool

    async def count_active_unique_for_client(self, client_id):
        return self.count_unique

    async def active_prompt_keys_for_client(self, client_id):
        return set(self.active_keys)

    async def active_prompt_keys_on_connection(self, client_id, conn, *, exclude_prompt_ids=None):
        return {
            prompts._prompt_quota_key(text, topic_id)
            for text, topic_id in await self.active_prompt_keys_for_client(client_id)
        }

    async def owned_topic_ids_on_connection(self, client_id, conn, topic_ids):
        return {str(value) for value in topic_ids}

    async def physical_candidates_on_connection(self, client_id, conn, **kwargs):
        return list(self.physical_rows)

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
        return [f"prompt-{i}" for i in range(len(rows))]

    async def add_many_on_connection(self, client_id, conn, rows):
        return await self.add_many(client_id, rows)

    async def reactivate_on_connection(self, client_id, conn, prompt_ids):
        rows = []
        for row in self.physical_rows:
            if str(row["id"]) in {str(value) for value in prompt_ids}:
                row["is_active"] = True
                rows.append(dict(row))
        return rows

    async def get_many_on_connection(self, client_id, conn, prompt_ids, **kwargs):
        return [
            {
                "id": str(prompt_id), "client_id": client_id,
                "topic_id": "11111111-1111-1111-1111-111111111111",
                "text": "Prompt", "intent": "Solution Discovery", "product": None,
                "platform": f"platform-{index}", "country": "US", "language": "en-US",
                "is_active": True, "created_at": None, "updated_at": None,
            }
            for index, prompt_id in enumerate(prompt_ids)
        ]

    async def update_many_on_connection(self, client_id, conn, prompt_ids, *, updates):
        return await self.update_many(client_id, prompt_ids, updates=updates)

    async def update_on_connection(self, client_id, conn, prompt_id, *, updates):
        row = (await self.get_many_on_connection(client_id, conn, [prompt_id]))[0]
        row.update(updates)
        return row

    async def update_many(self, client_id, prompt_ids, *, updates):
        self.updated_many.append((str(client_id), [str(pid) for pid in prompt_ids], dict(updates)))
        return len(prompt_ids)


class _WriteTx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.events.append("tx_enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.events.append("tx_rollback" if exc else "tx_commit")
        return False


class _WriteConn:
    def __init__(self):
        self.events: list[str] = []
        self.lock_keys: list[str] = []

    def transaction(self):
        return _WriteTx(self)

    async def fetchval(self, sql, *args):
        if "SELECT EXISTS(SELECT 1 FROM geo_clients" in sql:
            return True
        if "pg_try_advisory_xact_lock_shared" in sql:
            self.events.append("lock")
            self.lock_keys.append(args[0])
            return True
        if "pg_advisory_xact_lock" in sql:
            self.events.append("lock")
            self.lock_keys.append(args[0])
            return None
        return 0

    async def fetchrow(self, sql, *args):
        if "FROM geo_clients" in sql:
            return {
                "id": args[0],
                "client_prompt_quota": 20,
                "config_platforms": ["chatgpt"],
                "config_countries": ["US"],
                "config_languages": ["en-US"],
            }
        return None

    async def fetch(self, sql, *args):
        return []


class _WriteAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _WritePool:
    def __init__(self):
        self.conn = _WriteConn()

    def acquire(self):
        return _WriteAcquire(self.conn)


@pytest.mark.anyio
@pytest.mark.parametrize("route_kind", ["single", "batch"])
async def test_prompt_create_routes_enter_shared_write_lock_before_validation_and_insert(
    monkeypatch, route_kind
):
    pool = _WritePool()
    operation_events: list[str] = []

    class Repo:
        def __init__(self, _pool):
            self.pool = _pool

        async def owned_topic_ids_on_connection(self, client_id, conn, topic_ids):
            return {str(value) for value in topic_ids}

        async def active_prompt_keys_on_connection(self, client_id, conn, *, exclude_prompt_ids=None):
            operation_events.append("quota")
            return set()

        async def physical_candidates_on_connection(self, client_id, conn, **kwargs):
            return []

        async def reactivate_on_connection(self, client_id, conn, prompt_ids):
            return []

        async def add_on_connection(self, client_id, conn, **kwargs):
            operation_events.append("insert")
            return {
                "id": "33333333-3333-3333-3333-333333333333",
                "client_id": client_id,
                "created_at": None,
                "updated_at": None,
                **kwargs,
            }

        async def add_many_on_connection(self, client_id, conn, rows):
            operation_events.append("insert")
            return [f"prompt-{index}" for index, _ in enumerate(rows)]

    monkeypatch.setattr(prompts, "database", FakePromptDatabase())
    monkeypatch.setattr(prompts, "PromptRepository", Repo)
    monkeypatch.setattr(prompts, "PromptWriteCoordinator", RealPromptWriteCoordinator)
    payload = prompts.PromptCreateInput(
        topic_id=UUID("11111111-1111-1111-1111-111111111111"),
        text="Prompt",
        intent="Solution Discovery",
        platform="chatgpt",
        country="US",
        language="en-US",
    )

    if route_kind == "single":
        await prompts.create_prompt(client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), prompt=payload, pool=pool)
    else:
        await prompts.batch_create_prompts(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            data=prompts.BatchPromptCreate(prompts=[prompts.BatchPromptItemV2(**payload.model_dump())]),
            pool=pool,
        )

    assert pool.conn.events[:3] == ["tx_enter", "lock", "lock"]
    assert pool.conn.lock_keys == [
        "workspace-lifecycle:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "prompt-write:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    ]
    assert pool.conn.events[-1] == "tx_commit"
    assert operation_events == ["quota", "insert"]


@pytest.mark.anyio
@pytest.mark.parametrize("route_kind", ["update", "batch_update", "delete", "batch_delete"])
async def test_remaining_saas_prompt_mutations_use_tenant_prompt_write_coordinator(
    monkeypatch, route_kind
):
    calls: list[str] = []

    class RecordingCoordinator:
        def __init__(self, pool):
            self.pool = pool

        async def execute(self, client_id, operation):
            calls.append(str(client_id))
            return await operation(_LegacyWriteConn())

    monkeypatch.setattr(prompts, "PromptWriteCoordinator", RecordingCoordinator)
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)
    monkeypatch.setattr(prompts, "PromptCascadeDeletionService", FakeCascadeService)
    client_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    prompt_id = UUID("11111111-1111-1111-1111-111111111111")

    if route_kind == "update":
        await prompts.update_prompt(
            client_id, prompt_id, prompts.PromptUpdateInput(text="Updated"), pool=object()
        )
    elif route_kind == "batch_update":
        await prompts.batch_update_prompts(
            client_id,
            prompts.BatchPromptUpdate(
                prompt_ids=[prompt_id],
                updates=prompts.PromptUpdateInput(is_active=False),
            ),
            pool=object(),
        )
    elif route_kind == "delete":
        await prompts.delete_prompt(client_id, prompt_id, pool=object())
    else:
        await prompts.batch_delete_prompts(
            client_id,
            prompts.BatchDeleteInput(prompt_ids=[prompt_id]),
            pool=object(),
        )

    assert calls == [str(client_id)]


class _LegacyWriteConn:
    async def fetchrow(self, sql, *args):
        if "FROM geo_clients" in sql:
            return {
                "id": args[0],
                "client_prompt_quota": FakePromptRepository.quota,
                "config_platforms": ["chatgpt", "gemini"],
                "config_countries": ["US", "BR"],
                "config_languages": ["en-US"],
            }
        return None

    async def fetch(self, sql, *args):
        return []


class _LegacyWriteCoordinator:
    def __init__(self, pool):
        self.pool = pool

    async def execute(self, client_id, operation):
        return await operation(_LegacyWriteConn())


@pytest.fixture(autouse=True)
def mock_prompt_write_dependencies(monkeypatch):
    FakePromptRepository.physical_rows = []
    FakePromptRepository.quota = 300
    monkeypatch.setattr(prompts, "PromptIntentService", FakePromptIntentService)
    monkeypatch.setattr(prompts, "PromptWriteCoordinator", _LegacyWriteCoordinator)


@pytest.mark.anyio
async def test_create_prompt_rejects_new_unique_prompt_when_unique_quota_full(monkeypatch):
    FakePromptRepository.count_unique = 300
    FakePromptRepository.active_keys = {
        (f"Existing prompt {i}", "11111111-1111-1111-1111-111111111111")
        for i in range(300)
    }
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "database", FakePromptDatabase())
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    with pytest.raises(HTTPException) as exc:
        await prompts.create_prompt(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            prompt=prompts.PromptCreateInput(
                topic_id=UUID("11111111-1111-1111-1111-111111111111"),
                text="New prompt",
                intent="Solution Discovery",
                platform="chatgpt",
                country="US",
                language="en-US",
            ),
            pool=object(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Client Prompt quota exceeded"
    assert FakePromptRepository.added_rows == []


@pytest.mark.anyio
async def test_create_prompt_allows_existing_unique_prompt_variant_when_quota_full(monkeypatch):
    topic_id = "11111111-1111-1111-1111-111111111111"
    FakePromptRepository.count_unique = 300
    FakePromptRepository.active_keys = {("Existing prompt", topic_id)}
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "database", FakePromptDatabase())
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    result = await prompts.create_prompt(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        prompt=prompts.PromptCreateInput(
            topic_id=UUID(topic_id),
            text="Existing prompt",
            intent="Solution Discovery",
            platform="chatgpt",
            country="BR",
            language="en-US",
        ),
        pool=object(),
    )

    assert result.text == "Existing prompt"
    assert len(FakePromptRepository.added_rows) == 1


@pytest.mark.anyio
async def test_single_create_is_idempotent_after_import_created_compatible_variant(monkeypatch):
    topic_id = "11111111-1111-1111-1111-111111111111"
    existing = {
        "id": "33333333-3333-3333-3333-333333333333",
        "client_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "topic_id": topic_id,
        "text": "Imported prompt",
        "intent": "Solution Discovery",
        "product": None,
        "platform": "chatgpt",
        "country": "US",
        "language": "en-US",
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }
    FakePromptRepository.active_keys = {("Imported prompt", topic_id)}
    FakePromptRepository.physical_rows = [existing]
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    result = await prompts.create_prompt(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        prompt=prompts.PromptCreateInput(
            topic_id=UUID(topic_id),
            text="Imported prompt",
            intent="Solution Discovery",
            platform="chatgpt",
            country="US",
            language="en-US",
        ),
        pool=object(),
    )

    assert result.id == existing["id"]
    assert FakePromptRepository.added_rows == []


@pytest.mark.anyio
async def test_json_batch_skips_imported_variant_and_inserts_only_missing_physical_variant(monkeypatch):
    topic_id = "11111111-1111-1111-1111-111111111111"
    FakePromptRepository.active_keys = {("Imported prompt", topic_id)}
    FakePromptRepository.physical_rows = [{
        "id": "33333333-3333-3333-3333-333333333333",
        "client_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "topic_id": topic_id,
        "text": "Imported prompt",
        "intent": "Solution Discovery",
        "product": None,
        "platform": "chatgpt",
        "country": "US",
        "language": "en-US",
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }]
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    result = await prompts.batch_create_prompts(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        data=prompts.BatchPromptCreate(prompts=[prompts.BatchPromptItemV2(
            topic_id=UUID(topic_id),
            text="Imported prompt",
            intent="Solution Discovery",
            platforms=["chatgpt", "gemini"],
            countries=["US"],
            language="en-US",
        )]),
        pool=object(),
    )

    assert result.created == 1
    assert len(FakePromptRepository.added_rows) == 1
    assert FakePromptRepository.added_rows[0]["platform"] == "gemini"


@pytest.mark.anyio
async def test_full_quota_treats_casing_and_spacing_variant_as_same_logical_prompt(monkeypatch):
    topic_id = "11111111-1111-1111-1111-111111111111"
    existing_keys = {
        (f"Existing {index}", topic_id) for index in range(299)
    }
    existing_keys.add(("Best Robot?", topic_id))
    FakePromptRepository.active_keys = existing_keys
    FakePromptRepository.quota = 300
    FakePromptRepository.physical_rows = [{
        "id": "33333333-3333-3333-3333-333333333333",
        "client_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "topic_id": topic_id, "text": "Best Robot?", "intent": "Solution Discovery",
        "product": None, "platform": "chatgpt", "country": "US",
        "language": "en-US", "is_active": True,
        "created_at": None, "updated_at": None,
    }]
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    result = await prompts.create_prompt(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        prompt=prompts.PromptCreateInput(
            topic_id=UUID(topic_id), text=" best   robot? ",
            intent="Solution Discovery", platform="chatgpt", country="US", language="en-US",
        ), pool=object(),
    )

    assert result.id == "33333333-3333-3333-3333-333333333333"
    assert FakePromptRepository.added_rows == []


@pytest.mark.anyio
async def test_batch_deduplicates_canonical_prompt_variants_before_quota_and_insert(monkeypatch):
    topic_id = UUID("11111111-1111-1111-1111-111111111111")
    FakePromptRepository.active_keys = set()
    FakePromptRepository.quota = 1
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    result = await prompts.batch_create_prompts(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        data=prompts.BatchPromptCreate(prompts=[
            prompts.BatchPromptItemV2(topic_id=topic_id, text="Prompt", intent="Solution Discovery", platforms=["chatgpt"], countries=["US"]),
            prompts.BatchPromptItemV2(topic_id=topic_id, text=" prompt ", intent="Solution Discovery", platforms=["chatgpt"], countries=["US"]),
        ]), pool=object(),
    )

    assert result.created == 1
    assert len(FakePromptRepository.added_rows) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("route_kind", ["single", "batch"])
async def test_compatible_inactive_variant_is_reactivated_without_duplicate_insert(monkeypatch, route_kind):
    topic_id = UUID("11111111-1111-1111-1111-111111111111")
    FakePromptRepository.active_keys = set()
    FakePromptRepository.physical_rows = [{
        "id": "33333333-3333-3333-3333-333333333333",
        "client_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "topic_id": str(topic_id), "text": "Prompt", "intent": "Solution Discovery",
        "product": None, "platform": "chatgpt", "country": "US",
        "language": "en-US", "is_active": False,
        "created_at": None, "updated_at": None,
    }]
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    if route_kind == "single":
        result = await prompts.create_prompt(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            prompt=prompts.PromptCreateInput(topic_id=topic_id, text="Prompt", intent="Solution Discovery", platform="chatgpt", country="US", language="en-US"),
            pool=object(),
        )
        assert result.is_active is True
    else:
        result = await prompts.batch_create_prompts(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            data=prompts.BatchPromptCreate(prompts=[prompts.BatchPromptItemV2(topic_id=topic_id, text="Prompt", intent="Solution Discovery", platforms=["chatgpt"], countries=["US"])]),
            pool=object(),
        )
        assert result.created == 0
        assert result.reactivated == 1
        assert result.reactivated_ids == ["33333333-3333-3333-3333-333333333333"]
    assert FakePromptRepository.added_rows == []


@pytest.mark.anyio
@pytest.mark.parametrize("route_kind", ["single", "batch"])
async def test_incompatible_inactive_variant_remains_a_metadata_conflict(monkeypatch, route_kind):
    topic_id = UUID("11111111-1111-1111-1111-111111111111")
    FakePromptRepository.active_keys = set()
    FakePromptRepository.physical_rows = [{
        "id": "33333333-3333-3333-3333-333333333333",
        "client_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "topic_id": str(topic_id), "text": "Prompt", "intent": "Competitive Evaluation",
        "product": None, "platform": "chatgpt", "country": "US",
        "language": "en-US", "is_active": False,
        "created_at": None, "updated_at": None,
    }]
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    with pytest.raises(HTTPException) as exc:
        if route_kind == "single":
            await prompts.create_prompt(
                client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                prompt=prompts.PromptCreateInput(topic_id=topic_id, text="Prompt", intent="Solution Discovery", platform="chatgpt", country="US", language="en-US"),
                pool=object(),
            )
        else:
            await prompts.batch_create_prompts(
                client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                data=prompts.BatchPromptCreate(prompts=[prompts.BatchPromptItemV2(topic_id=topic_id, text="Prompt", intent="Solution Discovery", platforms=["chatgpt"], countries=["US"])]),
                pool=object(),
            )

    assert exc.value.status_code == 409
    assert FakePromptRepository.added_rows == []


@pytest.mark.anyio
async def test_batch_create_counts_new_unique_prompt_keys_for_quota(monkeypatch):
    topic_id = "11111111-1111-1111-1111-111111111111"
    FakePromptRepository.count_unique = 299
    FakePromptRepository.active_keys = {
        ("Existing prompt", topic_id),
        *{
            (f"Existing prompt {i}", topic_id)
            for i in range(298)
        },
    }
    FakePromptRepository.added_rows = []
    monkeypatch.setattr(prompts, "database", FakePromptDatabase())
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    with pytest.raises(HTTPException) as exc:
        await prompts.batch_create_prompts(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            data=prompts.BatchPromptCreate(prompts=[
                    prompts.BatchPromptItemV2(
                        topic_id=UUID(topic_id),
                        text="Existing prompt",
                        intent="Solution Discovery",
                        platforms=["chatgpt", "gemini"],
                    countries=["US", "BR"],
                ),
                prompts.BatchPromptItemV2(
                        topic_id=UUID(topic_id),
                        text="New prompt A",
                        intent="Solution Discovery",
                    platforms=["chatgpt"],
                    countries=["US"],
                ),
                prompts.BatchPromptItemV2(
                        topic_id=UUID(topic_id),
                        text="New prompt B",
                        intent="Solution Discovery",
                    platforms=["chatgpt"],
                    countries=["US"],
                ),
            ]),
            pool=object(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Client Prompt quota exceeded"
    assert FakePromptRepository.added_rows == []


@pytest.mark.anyio
async def test_batch_update_prompts_updates_all_ids_once(monkeypatch):
    FakePromptRepository.updated_many = []
    monkeypatch.setattr(prompts, "database", FakePromptDatabase())
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    result = await prompts.batch_update_prompts(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        data=prompts.BatchPromptUpdate(
            prompt_ids=[
                UUID("11111111-1111-1111-1111-111111111111"),
                UUID("22222222-2222-2222-2222-222222222222"),
            ],
            updates=prompts.PromptUpdateInput(is_active=False),
        ),
        pool=object(),
    )

    assert result.updated == 2
    assert FakePromptRepository.updated_many == [
        (
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ],
            {"is_active": False},
        )
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("route_kind", ["single", "batch"])
async def test_update_quota_keeps_old_logical_key_when_active_sibling_remains(
    monkeypatch, route_kind
):
    topic_id = UUID("11111111-1111-1111-1111-111111111111")

    class SiblingAwareRepository(FakePromptRepository):
        async def active_prompt_keys_on_connection(
            self, client_id, conn, *, exclude_prompt_ids=None
        ):
            if exclude_prompt_ids:
                return {prompts._prompt_quota_key("Prompt", topic_id)}
            return {prompts._prompt_quota_key("Prompt", topic_id)}

    FakePromptRepository.quota = 1
    monkeypatch.setattr(prompts, "PromptRepository", SiblingAwareRepository)
    update = prompts.PromptUpdateInput(text="New Prompt")

    with pytest.raises(HTTPException) as exc:
        if route_kind == "single":
            await prompts.update_prompt(
                UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                UUID("33333333-3333-3333-3333-333333333333"),
                update,
                pool=object(),
            )
        else:
            await prompts.batch_update_prompts(
                UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                prompts.BatchPromptUpdate(
                    prompt_ids=[UUID("33333333-3333-3333-3333-333333333333")],
                    updates=update,
                ),
                pool=object(),
            )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Client Prompt quota exceeded"


@pytest.mark.anyio
async def test_batch_update_prompts_rejects_empty_patch(monkeypatch):
    FakePromptRepository.updated_many = []
    monkeypatch.setattr(prompts, "database", FakePromptDatabase())
    monkeypatch.setattr(prompts, "PromptRepository", FakePromptRepository)

    with pytest.raises(HTTPException) as exc:
        await prompts.batch_update_prompts(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            data=prompts.BatchPromptUpdate(
                prompt_ids=[UUID("11111111-1111-1111-1111-111111111111")],
                updates=prompts.PromptUpdateInput(),
            ),
            pool=object(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "No fields to update"
    assert FakePromptRepository.updated_many == []


@pytest.mark.anyio
async def test_batch_delete_prompts_uses_cascade_service(monkeypatch):
    FakeCascadeService.calls = []
    monkeypatch.setattr(prompts, "PromptCascadeDeletionService", FakeCascadeService)

    result = await prompts.batch_delete_prompts(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        body=prompts.BatchDeleteInput(
            prompt_ids=[
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ],
        ),
        pool=object(),
    )

    assert result.deleted == 2
    assert FakeCascadeService.calls == [
        (
            "many",
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ],
        )
    ]


@pytest.mark.anyio
async def test_batch_delete_prompts_rejects_more_than_hard_limit_without_truncating(monkeypatch):
    FakeCascadeService.calls = []
    monkeypatch.setattr(prompts, "PromptCascadeDeletionService", FakeCascadeService)
    prompt_ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(101)]

    with pytest.raises(HTTPException) as exc:
        await prompts.batch_delete_prompts(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            body=prompts.BatchDeleteInput.model_construct(
                prompt_ids=prompt_ids,
                batch_size=100,
            ),
            pool=object(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == {
        "code": "prompt_delete_batch_too_large",
        "message": "A Prompt delete batch may contain at most 100 physical Prompt IDs",
        "max_batch_size": 100,
        "requested": 101,
    }
    assert FakeCascadeService.calls == []


def test_workspace_cleanup_delete_batch_contract_is_25_default_100_hard_limit():
    assert prompts.DEFAULT_PROMPT_DELETE_BATCH_SIZE == 25
    assert prompts.MAX_PROMPT_DELETE_BATCH_SIZE == 100
    body = prompts.BatchDeleteInput(prompt_ids=[])
    assert body.batch_size == 25
    field = prompts.BatchDeleteInput.model_fields["batch_size"]
    assert field.default == 25


@pytest.mark.anyio
async def test_batch_delete_prompts_accepts_exact_hard_limit_without_truncation(monkeypatch):
    FakeCascadeService.calls = []
    monkeypatch.setattr(prompts, "PromptCascadeDeletionService", FakeCascadeService)
    prompt_ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(100)]

    result = await prompts.batch_delete_prompts(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        body=prompts.BatchDeleteInput(prompt_ids=prompt_ids, batch_size=100),
        pool=object(),
    )

    assert result.deleted == 100
    assert FakeCascadeService.calls[0][2] == prompt_ids


@pytest.mark.anyio
async def test_batch_delete_prompts_rejects_invalid_uuid_before_transaction(monkeypatch):
    FakeCascadeService.calls = []
    monkeypatch.setattr(prompts, "PromptCascadeDeletionService", FakeCascadeService)

    with pytest.raises(HTTPException) as exc:
        await prompts.batch_delete_prompts(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            body=prompts.BatchDeleteInput.model_construct(
                prompt_ids=["not-a-uuid"],
                batch_size=25,
            ),
            pool=object(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "invalid_prompt_delete_id"
    assert FakeCascadeService.calls == []


@pytest.mark.anyio
async def test_batch_delete_prompts_rejects_non_list_even_when_empty():
    with pytest.raises(ValidationError):
        prompts.BatchDeleteInput.model_validate({"prompt_ids": ""})


@pytest.mark.anyio
async def test_batch_delete_omitted_size_uses_25_and_rejects_26_without_truncation(monkeypatch):
    FakeCascadeService.calls = []
    monkeypatch.setattr(prompts, "PromptCascadeDeletionService", FakeCascadeService)
    prompt_ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(26)]

    with pytest.raises(HTTPException) as exc:
        await prompts.batch_delete_prompts(
            client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            body=prompts.BatchDeleteInput(prompt_ids=prompt_ids),
            pool=object(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == {
        "code": "prompt_delete_batch_size_exceeded",
        "message": "The request contains more Prompt IDs than its batch_size",
        "batch_size": 25,
        "requested": 26,
    }
    assert FakeCascadeService.calls == []


def test_batch_delete_input_validates_batch_size_range_and_hard_id_limit():
    with pytest.raises(ValidationError):
        prompts.BatchDeleteInput(prompt_ids=[], batch_size=0)
    with pytest.raises(ValidationError):
        prompts.BatchDeleteInput(prompt_ids=[], batch_size=101)
    with pytest.raises(ValidationError):
        prompts.BatchDeleteInput(
            prompt_ids=[UUID(int=index) for index in range(101)],
            batch_size=100,
        )


@pytest.mark.anyio
async def test_delete_prompt_uses_cascade_service(monkeypatch):
    FakeCascadeService.calls = []
    monkeypatch.setattr(prompts, "PromptCascadeDeletionService", FakeCascadeService)

    result = await prompts.delete_prompt(
        client_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        prompt_id=UUID("11111111-1111-1111-1111-111111111111"),
        pool=object(),
    )

    assert result.status == "ok"
    assert FakeCascadeService.calls == [(
        "many",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ["11111111-1111-1111-1111-111111111111"],
    )]
