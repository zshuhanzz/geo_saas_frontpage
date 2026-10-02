"""Admin adapter tests for canonical ``geo_client_brands.aliases``."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from geo_common.auth import AuthenticatedUser

from routers import clients


CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
BRAND_ID = UUID("22222222-2222-2222-2222-222222222222")
ACTOR = AuthenticatedUser(
    id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    email="admin@example.com",
    google_sub="google-sub",
    name="Admin",
    avatar_url=None,
    is_active=True,
)


class _Transaction:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        self.conn.events.append("tx_enter")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.conn.events.append("tx_commit" if exc_type is None else "tx_rollback")
        return False


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.fetch_rows: list[dict] = []
        self.fetchrow_row: dict | None = None
        self.events: list[str] = []
        self.fail_audit = False

    async def fetch(self, sql: str, *args: object) -> list[dict]:
        self.calls.append(("fetch", sql, args))
        return list(self.fetch_rows)

    async def fetchrow(self, sql: str, *args: object) -> dict | None:
        self.calls.append(("fetchrow", sql, args))
        return self.fetchrow_row

    async def fetchval(self, sql: str, *args: object):
        self.calls.append(("fetchval", sql, args))
        if "SELECT EXISTS" in sql:
            return True
        if "pg_try_advisory" in sql:
            return True
        return None

    async def execute(self, sql: str, *args: object) -> str:
        self.calls.append(("execute", sql, args))
        if self.fail_audit and "geo_user_audit_events" in sql:
            raise RuntimeError("audit insert failed")
        return "INSERT 0 1"

    def transaction(self):
        return _Transaction(self)


class _Acquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake_conn() -> FakeConn:
    return FakeConn()


@pytest.fixture
def fake_pool(fake_conn: FakeConn) -> FakePool:
    return FakePool(fake_conn)


def test_client_requests_expose_legacy_aliases_as_read_only() -> None:
    assert "aliases" in clients.ClientOut.model_fields
    assert "aliases" not in clients.ClientCreate.model_fields
    assert "aliases" not in clients.ClientUpdate.model_fields


@pytest.mark.parametrize("model", [clients.ClientCreate, clients.ClientUpdate])
def test_client_write_models_reject_legacy_aliases(model) -> None:
    payload = {"aliases": ["must-not-write"]}
    if model is clients.ClientCreate:
        payload["name"] = "Acme"

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_client_create_accepts_exact_admin_ui_payload_and_rejects_related_collections() -> None:
    payload = {
        "name": "Acme",
        "client_prompt_quota": 50,
        "config_platforms": [],
        "config_countries": [],
        "config_languages": [],
    }

    parsed = clients.ClientCreate.model_validate(payload)
    assert parsed.model_dump(include=set(payload)) == payload
    with pytest.raises(ValidationError):
        clients.ClientCreate.model_validate({**payload, "peers": []})


@pytest.mark.anyio
async def test_create_client_never_passes_legacy_aliases_to_repository(monkeypatch) -> None:
    calls: list[dict] = []
    entitlement_calls: list[dict] = []
    client_id = UUID("44444444-4444-4444-4444-444444444444")

    class AsyncContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def transaction(self):
            return self

    class FakePool:
        def acquire(self):
            return AsyncContext()

    class RecordingClientRepository:
        def __init__(self, pool) -> None:
            pass

        async def get_by_name(self, name: str):
            return None

        async def add(self, **kwargs):
            calls.append(kwargs)
            return {"id": client_id}

        async def get_by_id(self, value):
            return {
                "id": client_id,
                "name": "Acme",
                "client_prompt_quota": 50,
                "aliases": [],
                "config_platforms": [],
                "config_countries": [],
                "config_languages": [],
                "cron_collector": None,
                "cron_analyzer": None,
                "cron_llm_discovery": None,
                "agent_daily_token_quota": 500000,
                "agent_rpm_limit": 10,
                "reuse_latest_final_prompt": None,
                "country_localization_mode": None,
                "final_prompt_per_client_prompt": None,
                "default_calls_per_prompt": None,
            }

        async def fetch_related_collections(self, client_ids):
            return {
                "peers": {client_id: []},
                "domains": {client_id: []},
                "topics": {client_id: []},
                "personas": {client_id: []},
            }

    monkeypatch.setattr(clients, "ClientRepository", RecordingClientRepository)
    async def record_entitlements(conn, **kwargs):
        entitlement_calls.append(kwargs)
        return []

    monkeypatch.setattr(
        clients,
        "apply_workspace_entitlements",
        record_entitlements,
    )

    await clients.create_client(clients.ClientCreate(name="Acme"), pool=FakePool())

    assert len(calls) == 1
    assert "aliases" not in calls[0]
    assert calls[0]["conn"].__class__ is AsyncContext
    assert entitlement_calls == [
        {
            "client_id": str(client_id),
            "package_key": "full_platform",
            "feature_keys": None,
        }
    ]


def test_admin_openapi_brand_alias_contract_and_read_only_legacy_field() -> None:
    from main import app

    schema = app.openapi()
    components = schema["components"]["schemas"]
    assert "aliases" not in components["ClientCreate"]["properties"]
    assert "peers" not in components["ClientCreate"]["properties"]
    assert "aliases" not in components["ClientUpdate"]["properties"]
    assert set(components["ClientBrandOut"]["properties"]) == {
        "id",
        "brand_name",
        "aliases",
        "is_shadow",
    }
    assert set(components["BrandAliasesUpdate"]["properties"]) == {"aliases"}
    assert "/api/clients/{client_id}/brands" in schema["paths"]
    assert "/api/clients/{client_id}/brands/{brand_id}/aliases" in schema["paths"]


@pytest.mark.anyio
async def test_list_client_brands_returns_active_own_and_shadow_rows(fake_pool, fake_conn) -> None:
    fake_conn.fetch_rows = [
        {
            "id": BRAND_ID,
            "client_id": CLIENT_ID,
            "brand_name": "Acme",
            "aliases": ["ACME"],
            "is_shadow": False,
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": UUID("33333333-3333-3333-3333-333333333333"),
            "client_id": CLIENT_ID,
            "brand_name": "Retailer",
            "aliases": [],
            "is_shadow": True,
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        },
    ]

    rows = await clients.list_client_brands(CLIENT_ID, pool=fake_pool)

    assert [row.model_dump() for row in rows] == [
        {
            "id": str(BRAND_ID),
            "brand_name": "Acme",
            "aliases": ["ACME"],
            "is_shadow": False,
        },
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "brand_name": "Retailer",
            "aliases": [],
            "is_shadow": True,
        },
    ]
    _, sql, args = fake_conn.calls[-1]
    assert "client_id = $1" in sql
    assert "is_active = true" in sql
    assert args == (str(CLIENT_ID),)


@pytest.mark.anyio
async def test_update_client_brand_aliases_normalizes_and_returns_canonical_row(
    fake_pool,
    fake_conn,
) -> None:
    fake_conn.fetchrow_row = {
        "id": BRAND_ID,
        "client_id": CLIENT_ID,
        "brand_name": "Acme",
        "aliases": ["Alpha", "BETA"],
        "is_shadow": False,
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }

    row = await clients.update_client_brand_aliases(
        CLIENT_ID,
        BRAND_ID,
        clients.BrandAliasesUpdate(
            aliases=[" Alpha ", "alpha", "", " BETA ", "beta"]
        ),
        actor=ACTOR,
        pool=fake_pool,
    )

    assert row.aliases == ["Alpha", "BETA"]
    _, sql, args = next(
        call for call in fake_conn.calls if "UPDATE geo_client_brands" in call[1]
    )
    assert "UPDATE geo_client_brands" in sql
    assert "WHERE client_id = $1 AND id = $2" in sql
    assert args == (str(CLIENT_ID), str(BRAND_ID), ["Alpha", "BETA"])


@pytest.mark.anyio
async def test_update_client_brand_aliases_empty_array_clears_aliases(
    fake_pool,
    fake_conn,
) -> None:
    fake_conn.fetchrow_row = {
        "id": BRAND_ID,
        "client_id": CLIENT_ID,
        "brand_name": "Acme",
        "aliases": [],
        "is_shadow": False,
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }

    row = await clients.update_client_brand_aliases(
        CLIENT_ID,
        BRAND_ID,
        clients.BrandAliasesUpdate(aliases=[]),
        actor=ACTOR,
        pool=fake_pool,
    )

    assert row.aliases == []
    update_call = next(
        call for call in fake_conn.calls if "UPDATE geo_client_brands" in call[1]
    )
    assert update_call[2][2] == []


@pytest.mark.anyio
async def test_update_client_brand_aliases_hides_cross_tenant_brand(fake_pool, fake_conn) -> None:
    fake_conn.fetchrow_row = None

    with pytest.raises(HTTPException) as exc:
        await clients.update_client_brand_aliases(
            CLIENT_ID,
            BRAND_ID,
            clients.BrandAliasesUpdate(aliases=["Acme"]),
            actor=ACTOR,
            pool=fake_pool,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Brand not found"
    _, sql, args = next(
        call for call in fake_conn.calls if "UPDATE geo_client_brands" in call[1]
    )
    assert "WHERE client_id = $1 AND id = $2" in sql
    assert args[:2] == (str(CLIENT_ID), str(BRAND_ID))
    assert not any("geo_user_audit_events" in call[1] for call in fake_conn.calls)
    assert fake_conn.events == ["tx_enter", "tx_rollback"]


@pytest.mark.anyio
async def test_alias_update_has_no_inline_audit_dependency(
    fake_pool,
    fake_conn,
) -> None:
    fake_conn.fetchrow_row = {
        "id": BRAND_ID,
        "client_id": CLIENT_ID,
        "brand_name": "Acme",
        "aliases": ["Secret Alias", "Second"],
        "is_shadow": False,
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }

    await clients.update_client_brand_aliases(
        CLIENT_ID,
        BRAND_ID,
        clients.BrandAliasesUpdate(aliases=[" Secret Alias ", "Second"]),
        actor=ACTOR,
        pool=fake_pool,
    )

    assert fake_conn.events == ["tx_enter", "tx_commit"]
    lifecycle_index = next(
        index for index, call in enumerate(fake_conn.calls)
        if "advisory" in call[1]
    )
    update_index = next(
        index for index, call in enumerate(fake_conn.calls)
        if "UPDATE geo_client_brands" in call[1]
    )
    assert lifecycle_index < update_index
    assert not any(
        "INSERT INTO geo_user_audit_events" in call[1]
        for call in fake_conn.calls
    )


@pytest.mark.anyio
async def test_alias_update_is_independent_from_audit_storage(fake_pool, fake_conn) -> None:
    fake_conn.fetchrow_row = {
        "id": BRAND_ID,
        "client_id": CLIENT_ID,
        "brand_name": "Acme",
        "aliases": ["Alpha"],
        "is_shadow": False,
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }
    fake_conn.fail_audit = True

    await clients.update_client_brand_aliases(
        CLIENT_ID,
        BRAND_ID,
        clients.BrandAliasesUpdate(aliases=["Alpha"]),
        actor=ACTOR,
        pool=fake_pool,
    )

    assert fake_conn.events == ["tx_enter", "tx_commit"]
