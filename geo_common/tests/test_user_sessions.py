"""Server-side user Session lifecycle contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from geo_common.auth.sessions import (
    ADMIN_SESSION_TTL_SECONDS,
    SAAS_SESSION_TTL_SECONDS,
    SessionAuthError,
    create_user_session,
    end_user_session,
    hash_session_token,
    resolve_user_session,
    revoke_user_sessions,
)


USER_ID = "8f422899-c4a0-494f-b868-b94fcd5f79d2"
SESSION_ID = "d5fdd7c7-2dc8-42ed-ad92-3bb497b2f760"
NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


class SessionDb:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.rows.pop(0) if self.rows else None

    async def execute(self, sql: str, *args):
        self.calls.append(("execute", sql, args))
        return "UPDATE 1"

    async def fetch(self, sql: str, *args):
        self.calls.append(("fetch", sql, args))
        rows = self.rows
        self.rows = []
        return rows


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _active_row(*, scope: str = "saas", expires_at=None, ended_at=None):
    return {
        "session_id": SESSION_ID,
        "session_scope": scope,
        "user_id": USER_ID,
        "expires_at": expires_at or NOW + timedelta(hours=1),
        "last_seen_at": NOW,
        "ended_at": ended_at,
        "end_reason": None,
        "email": "lancelot@example.com",
        "google_sub": "google-sub",
        "name": "lancelot",
        "avatar_url": None,
        "is_active": True,
    }


def test_session_ttls_are_independent() -> None:
    assert SAAS_SESSION_TTL_SECONDS == 24 * 60 * 60
    assert ADMIN_SESSION_TTL_SECONDS == 12 * 60 * 60


def test_session_hash_is_deterministic_and_does_not_store_raw_token() -> None:
    token_hash = hash_session_token("raw-secret-token")
    assert token_hash == hash_session_token("raw-secret-token")
    assert token_hash != "raw-secret-token"
    assert len(token_hash) == 64


@pytest.mark.anyio
async def test_create_session_inserts_only_hash_with_absolute_expiry() -> None:
    db = SessionDb(
        [
            {
                "id": SESSION_ID,
                "user_id": USER_ID,
                "session_scope": "saas",
                "created_at": NOW,
                "expires_at": NOW + timedelta(hours=24),
            }
        ]
    )

    created = await create_user_session(
        db,
        user_id=USER_ID,
        session_scope="saas",
        ttl_seconds=SAAS_SESSION_TTL_SECONDS,
        now=NOW,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    call = db.calls[0]
    assert "INSERT INTO geo_user_sessions" in call[1]
    assert created.token not in call[2]
    assert hash_session_token(created.token) in call[2]
    assert created.expires_at == NOW + timedelta(hours=24)


@pytest.mark.anyio
async def test_resolve_session_returns_user_only_for_expected_scope() -> None:
    db = SessionDb([_active_row()])

    principal = await resolve_user_session(
        db,
        token="browser-token",
        expected_scope="saas",
        now=NOW,
    )

    assert principal.session_id == SESSION_ID
    assert principal.session_scope == "saas"
    assert principal.user.email == "lancelot@example.com"
    assert db.calls[0][2] == (hash_session_token("browser-token"), "saas")


@pytest.mark.anyio
async def test_cross_scope_cookie_is_rejected() -> None:
    db = SessionDb([])

    with pytest.raises(SessionAuthError) as exc:
        await resolve_user_session(
            db,
            token="admin-cookie",
            expected_scope="saas",
            now=NOW,
        )

    assert exc.value.code == "session_invalid"
    assert db.calls[0][2] == (hash_session_token("admin-cookie"), "saas")


@pytest.mark.anyio
async def test_expired_session_transitions_once_for_audit() -> None:
    expired = _active_row(expires_at=NOW - timedelta(seconds=1))
    transitioned = {
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "session_scope": "saas",
        "expires_at": expired["expires_at"],
        "ended_at": NOW,
        "end_reason": "expired",
    }
    db = SessionDb([expired, transitioned])

    with pytest.raises(SessionAuthError) as exc:
        await resolve_user_session(
            db,
            token="expired-token",
            expected_scope="saas",
            now=NOW,
        )

    assert exc.value.code == "session_expired"
    assert exc.value.lifecycle_transition is not None
    assert exc.value.lifecycle_transition.end_reason == "expired"
    assert "ended_at IS NULL" in db.calls[1][1]


@pytest.mark.anyio
async def test_logout_ends_only_the_matching_active_session() -> None:
    ended = {
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "session_scope": "admin",
        "expires_at": NOW + timedelta(hours=1),
        "ended_at": NOW,
        "end_reason": "logout",
    }
    db = SessionDb([ended])

    result = await end_user_session(
        db,
        token="admin-token",
        expected_scope="admin",
        reason="logout",
        now=NOW,
    )

    assert result == ended
    assert "ended_at IS NULL" in db.calls[0][1]
    assert db.calls[0][2][:3] == (
        hash_session_token("admin-token"),
        "admin",
        "logout",
    )


@pytest.mark.anyio
async def test_revoke_user_sessions_can_be_limited_to_admin_scope() -> None:
    revoked = {
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "session_scope": "admin",
        "expires_at": NOW + timedelta(hours=1),
        "ended_at": NOW,
        "end_reason": "revoked",
    }
    db = SessionDb([revoked])

    transitions = await revoke_user_sessions(
        db,
        user_id=USER_ID,
        session_scope="admin",
        now=NOW,
    )

    assert transitions[0].end_reason == "revoked"
    assert db.calls[0][2] == (USER_ID, "admin", NOW)
    assert "ended_at IS NULL" in db.calls[0][1]
