"""Tests for shared Google OAuth access-control helpers."""

from __future__ import annotations

import pytest

from geo_common.auth.access_control import (
    AdminAccess,
    AuthenticatedUser,
    WorkspaceAccess,
    get_workspace_access,
    GOOGLE_ID_TOKEN_CLOCK_SKEW_SECONDS,
    get_admin_access,
    has_client_access,
    has_support_all_clients,
    normalize_email,
    upsert_google_user,
    verify_google_id_token,
)


class SequencedDb:
    """Tiny asyncpg-like test double returning fetchrow results in order."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append(("fetchrow", sql, args))
        if not self.rows:
            return None
        return self.rows.pop(0)


class WorkspaceAccessDb:
    def __init__(
        self,
        *,
        admin_access=None,
        client_role=None,
        entitlements=(),
    ):
        self.admin_access = admin_access
        self.client_role = client_role
        self.entitlements = list(entitlements)
        self.calls = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append(("fetchrow", sql, args))
        if "geo_admin_user_access" in sql:
            return self.admin_access
        raise AssertionError(f"Unexpected fetchrow query: {sql}")

    async def fetchval(self, sql: str, *args):
        self.calls.append(("fetchval", sql, args))
        if "geo_client_user_access" in sql:
            return self.client_role
        raise AssertionError(f"Unexpected fetchval query: {sql}")

    async def fetch(self, sql: str, *args):
        self.calls.append(("fetch", sql, args))
        if "geo_workspace_feature_entitlements" in sql:
            return [{"feature_key": key} for key in self.entitlements]
        raise AssertionError(f"Unexpected fetch query: {sql}")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_normalize_email_strips_and_lowercases() -> None:
    assert normalize_email("  lancelot.Example@GMAIL.com ") == "lancelot.example@gmail.com"


def test_verify_google_id_token_allows_small_clock_skew(monkeypatch) -> None:
    captured = {}

    def fake_verify_oauth2_token(token, request, audience=None, clock_skew_in_seconds=0):
        captured["token"] = token
        captured["audience"] = audience
        captured["clock_skew_in_seconds"] = clock_skew_in_seconds
        return {"email": "lancelot@example.com"}

    monkeypatch.setattr(
        "geo_common.auth.access_control.id_token.verify_oauth2_token",
        fake_verify_oauth2_token,
    )

    claims = verify_google_id_token("id-token", "google-client-id")

    assert claims == {"email": "lancelot@example.com"}
    assert captured == {
        "token": "id-token",
        "audience": "google-client-id",
        "clock_skew_in_seconds": GOOGLE_ID_TOKEN_CLOCK_SKEW_SECONDS,
    }


@pytest.mark.anyio
async def test_upsert_google_user_preserves_configured_name_and_caches_avatar() -> None:
    db = SequencedDb(
        [
            {
                "id": "8f422899-c4a0-494f-b868-b94fcd5f79d2",
                "email": "lancelot@example.com",
                "google_sub": "google-sub-1",
                "name": "lancelot",
                "avatar_url": "https://lh3.googleusercontent.com/avatar",
                "is_active": True,
            }
        ]
    )

    user = await upsert_google_user(
        db,
        {
            "email": " lancelot@Example.com ",
            "sub": "google-sub-1",
            "name": "lancelot",
            "picture": "https://lh3.googleusercontent.com/avatar",
        },
    )

    assert user == AuthenticatedUser(
        id="8f422899-c4a0-494f-b868-b94fcd5f79d2",
        email="lancelot@example.com",
        google_sub="google-sub-1",
        name="lancelot",
        avatar_url="https://lh3.googleusercontent.com/avatar",
        is_active=True,
    )
    sql = db.calls[0][1]
    assert "INSERT INTO geo_users" in sql
    assert "ON CONFLICT (LOWER(email))" in sql
    assert "name = COALESCE(geo_users.name, EXCLUDED.name)" in sql
    assert db.calls[0][2] == (
        "lancelot@example.com",
        "google-sub-1",
        "lancelot",
        "https://lh3.googleusercontent.com/avatar",
    )


@pytest.mark.anyio
async def test_get_admin_access_returns_role_and_support_override() -> None:
    db = SequencedDb(
        [{"role": "super_admin", "support_all_clients": True, "is_active": True}]
    )

    access = await get_admin_access(db, "8f422899-c4a0-494f-b868-b94fcd5f79d2")

    assert access == AdminAccess(
        role="super_admin",
        support_all_clients=True,
        is_active=True,
    )


@pytest.mark.anyio
async def test_has_support_all_clients_requires_active_super_admin_override() -> None:
    allowed_db = SequencedDb([{"exists": 1}])
    denied_db = SequencedDb([None])

    assert await has_support_all_clients(
        allowed_db, "8f422899-c4a0-494f-b868-b94fcd5f79d2"
    )
    assert not await has_support_all_clients(
        denied_db, "8f422899-c4a0-494f-b868-b94fcd5f79d2"
    )

    sql = allowed_db.calls[0][1]
    assert "role = 'super_admin'" in sql
    assert "support_all_clients = true" in sql
    assert "is_active = true" in sql


@pytest.mark.anyio
async def test_has_client_access_allows_support_override_before_client_grant() -> None:
    db = SequencedDb([{"exists": 1}])

    assert await has_client_access(
        db,
        "8f422899-c4a0-494f-b868-b94fcd5f79d2",
        "e6698f36-c07b-4b21-b160-1991d56af24c",
    )
    assert len(db.calls) == 1


@pytest.mark.anyio
async def test_has_client_access_checks_active_client_grant_without_support_override() -> None:
    db = SequencedDb([None, {"exists": 1}])

    assert await has_client_access(
        db,
        "8f422899-c4a0-494f-b868-b94fcd5f79d2",
        "e6698f36-c07b-4b21-b160-1991d56af24c",
    )

    client_sql = db.calls[1][1]
    assert "FROM geo_client_user_access" in client_sql
    assert "user_id = $1::uuid" in client_sql
    assert "client_id = $2::uuid" in client_sql
    assert "is_active = true" in client_sql


@pytest.mark.anyio
async def test_account_manager_bypasses_workspace_entitlements() -> None:
    db = WorkspaceAccessDb(client_role="account_manager")

    access = await get_workspace_access(
        db,
        "8f422899-c4a0-494f-b868-b94fcd5f79d2",
        "e6698f36-c07b-4b21-b160-1991d56af24c",
    )

    assert isinstance(access, WorkspaceAccess)
    assert access.role == "account_manager"
    assert access.entitlement_override is True
    assert access.allows("actions.content", "manage")
    assert not any(call[0] == "fetch" for call in db.calls)


@pytest.mark.anyio
async def test_super_admin_with_explicit_grant_bypasses_workspace_entitlements() -> None:
    db = WorkspaceAccessDb(
        admin_access={
            "role": "super_admin",
            "support_all_clients": False,
            "is_active": True,
        },
        client_role="viewer",
    )

    access = await get_workspace_access(
        db,
        "8f422899-c4a0-494f-b868-b94fcd5f79d2",
        "e6698f36-c07b-4b21-b160-1991d56af24c",
    )

    assert isinstance(access, WorkspaceAccess)
    assert access.role == "super_admin"
    assert access.entitlement_override is True
    assert access.allows("actions.training", "manage")
    assert not any(call[0] == "fetch" for call in db.calls)


@pytest.mark.anyio
async def test_super_admin_without_global_support_still_needs_workspace_grant() -> None:
    db = WorkspaceAccessDb(
        admin_access={
            "role": "super_admin",
            "support_all_clients": False,
            "is_active": True,
        },
        client_role=None,
    )

    access = await get_workspace_access(
        db,
        "8f422899-c4a0-494f-b868-b94fcd5f79d2",
        "e6698f36-c07b-4b21-b160-1991d56af24c",
    )

    assert access is None


@pytest.mark.anyio
async def test_super_admin_global_support_bypasses_grant_and_entitlements() -> None:
    db = WorkspaceAccessDb(
        admin_access={
            "role": "super_admin",
            "support_all_clients": True,
            "is_active": True,
        },
    )

    access = await get_workspace_access(
        db,
        "8f422899-c4a0-494f-b868-b94fcd5f79d2",
        "e6698f36-c07b-4b21-b160-1991d56af24c",
    )

    assert isinstance(access, WorkspaceAccess)
    assert access.role == "super_admin"
    assert access.support_override is True
    assert access.entitlement_override is True
    assert access.allows("actions.chat", "execute")
    assert not any(call[0] == "fetchval" for call in db.calls)
