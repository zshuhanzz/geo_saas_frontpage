"""Database-backed, independently scoped browser Sessions.

Google credentials are verified only while creating a Session. SaaS, Agent,
and Admin requests subsequently resolve an opaque HttpOnly cookie whose raw
value is never stored in PostgreSQL.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from typing import Any, Literal

from .access_control import AuthenticatedUser

SessionScope = Literal["saas", "admin"]
SessionEndReason = Literal["expired", "logout", "revoked"]

SAAS_SESSION_COOKIE_NAME = "answerx_saas_session"
ADMIN_SESSION_COOKIE_NAME = "answerx_admin_session"
SAAS_SESSION_TTL_SECONDS = 24 * 60 * 60
ADMIN_SESSION_TTL_SECONDS = 12 * 60 * 60
SESSION_TOUCH_INTERVAL_SECONDS = 60 * 60
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreatedUserSession:
    session_id: str
    token: str
    session_scope: SessionScope
    user_id: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class SessionPrincipal:
    session_id: str
    session_scope: SessionScope
    expires_at: datetime | None
    user: AuthenticatedUser


@dataclass(frozen=True)
class SessionLifecycleTransition:
    session_id: str
    user_id: str
    session_scope: SessionScope
    expires_at: datetime
    ended_at: datetime
    end_reason: SessionEndReason


class SessionAuthError(Exception):
    """A stable Session failure surfaced by SaaS/Admin/Agent dependencies."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        lifecycle_transition: SessionLifecycleTransition | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.lifecycle_transition = lifecycle_transition


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now_utc(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _transition_from_row(row: Any) -> SessionLifecycleTransition:
    return SessionLifecycleTransition(
        session_id=str(row["session_id"]),
        user_id=str(row["user_id"]),
        session_scope=str(row["session_scope"]),
        expires_at=row["expires_at"],
        ended_at=row["ended_at"],
        end_reason=str(row["end_reason"]),
    )


async def create_user_session(
    db: Any,
    *,
    user_id: str,
    session_scope: SessionScope,
    ttl_seconds: int,
    ip_address: str | None,
    user_agent: str | None,
    now: datetime | None = None,
) -> CreatedUserSession:
    """Create one absolute-expiry Session and return its raw cookie token once."""
    created_at = _now_utc(now)
    expires_at = created_at + timedelta(seconds=ttl_seconds)
    token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(token)
    row = await db.fetchrow(
        """
        INSERT INTO geo_user_sessions (
            user_id, session_scope, token_hash, created_at, expires_at,
            last_seen_at, created_ip, user_agent
        )
        VALUES ($1::uuid, $2, $3, $4, $5, $4, $6, $7)
        RETURNING id, user_id, session_scope, created_at, expires_at
        """,
        user_id,
        session_scope,
        token_hash,
        created_at,
        expires_at,
        ip_address,
        (user_agent or "")[:1000] or None,
    )
    if row is None:
        raise RuntimeError("Failed to create user Session")
    return CreatedUserSession(
        session_id=str(row["id"]),
        token=token,
        session_scope=str(row["session_scope"]),
        user_id=str(row["user_id"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


async def resolve_user_session(
    db: Any,
    *,
    token: str,
    expected_scope: SessionScope,
    now: datetime | None = None,
) -> SessionPrincipal:
    """Resolve an active Session and enforce Scope, expiry, and user status."""
    checked_at = _now_utc(now)
    row = await db.fetchrow(
        """
        SELECT s.id::text AS session_id, s.session_scope,
               s.user_id::text AS user_id, s.expires_at, s.last_seen_at,
               s.ended_at, s.end_reason,
               u.email, u.google_sub, u.name, u.avatar_url, u.is_active
        FROM geo_user_sessions AS s
        JOIN geo_users AS u ON u.id = s.user_id
        WHERE s.token_hash = $1
          AND s.session_scope = $2
        """,
        hash_session_token(token),
        expected_scope,
    )
    if row is None:
        raise SessionAuthError("session_invalid", "Session is invalid")

    if row["ended_at"] is not None:
        code = (
            "session_expired"
            if row["end_reason"] == "expired"
            else "session_revoked"
        )
        raise SessionAuthError(code, "Session is no longer active")

    if row["expires_at"] <= checked_at:
        transitioned = await db.fetchrow(
            """
            UPDATE geo_user_sessions
            SET ended_at = $2, end_reason = 'expired'
            WHERE id = $1::uuid
              AND ended_at IS NULL
            RETURNING id::text AS session_id, user_id::text AS user_id,
                      session_scope, expires_at, ended_at, end_reason
            """,
            str(row["session_id"]),
            checked_at,
        )
        raise SessionAuthError(
            "session_expired",
            "Session has expired",
            lifecycle_transition=(
                _transition_from_row(transitioned) if transitioned else None
            ),
        )

    if not row["is_active"]:
        transitioned = await db.fetchrow(
            """
            UPDATE geo_user_sessions
            SET ended_at = $2, end_reason = 'revoked'
            WHERE id = $1::uuid
              AND ended_at IS NULL
            RETURNING id::text AS session_id, user_id::text AS user_id,
                      session_scope, expires_at, ended_at, end_reason
            """,
            str(row["session_id"]),
            checked_at,
        )
        raise SessionAuthError(
            "user_inactive",
            "User is inactive",
            lifecycle_transition=(
                _transition_from_row(transitioned) if transitioned else None
            ),
        )

    last_seen_at = row["last_seen_at"]
    if (
        last_seen_at is None
        or checked_at - last_seen_at
        >= timedelta(seconds=SESSION_TOUCH_INTERVAL_SECONDS)
    ):
        await db.execute(
            """
            UPDATE geo_user_sessions
            SET last_seen_at = $2
            WHERE id = $1::uuid
              AND ended_at IS NULL
            """,
            str(row["session_id"]),
            checked_at,
        )

    return SessionPrincipal(
        session_id=str(row["session_id"]),
        session_scope=str(row["session_scope"]),
        expires_at=row["expires_at"],
        user=AuthenticatedUser(
            id=str(row["user_id"]),
            email=str(row["email"]),
            google_sub=row["google_sub"],
            name=row["name"],
            avatar_url=row["avatar_url"],
            is_active=bool(row["is_active"]),
        ),
    )


async def end_user_session(
    db: Any,
    *,
    token: str,
    expected_scope: SessionScope,
    reason: SessionEndReason,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """End exactly one matching active Session; repeated calls are idempotent."""
    ended_at = _now_utc(now)
    row = await db.fetchrow(
        """
        UPDATE geo_user_sessions
        SET ended_at = $4,
            end_reason = CASE
                WHEN expires_at <= $4 THEN 'expired'
                ELSE $3
            END
        WHERE token_hash = $1
          AND session_scope = $2
          AND ended_at IS NULL
        RETURNING id::text AS session_id, user_id::text AS user_id,
                  session_scope, expires_at, ended_at, end_reason
        """,
        hash_session_token(token),
        expected_scope,
        reason,
        ended_at,
    )
    return dict(row) if row else None


async def expire_due_sessions(
    db: Any,
    *,
    limit: int = 500,
    now: datetime | None = None,
) -> list[SessionLifecycleTransition]:
    """Atomically close a bounded batch so expiry Audit is emitted once."""
    ended_at = _now_utc(now)
    rows = await db.fetch(
        """
        WITH due AS (
            SELECT id
            FROM geo_user_sessions
            WHERE ended_at IS NULL
              AND expires_at <= $1
            ORDER BY expires_at
            FOR UPDATE SKIP LOCKED
            LIMIT $2
        )
        UPDATE geo_user_sessions AS sessions
        SET ended_at = $1, end_reason = 'expired'
        FROM due
        WHERE sessions.id = due.id
        RETURNING sessions.id::text AS session_id,
                  sessions.user_id::text AS user_id,
                  sessions.session_scope, sessions.expires_at,
                  sessions.ended_at, sessions.end_reason
        """,
        ended_at,
        max(1, min(limit, 5000)),
    )
    return [_transition_from_row(row) for row in rows]


async def revoke_user_sessions(
    db: Any,
    *,
    user_id: str,
    session_scope: SessionScope | None = None,
    now: datetime | None = None,
) -> list[SessionLifecycleTransition]:
    """Revoke all active Sessions for one user, optionally within one scope."""
    ended_at = _now_utc(now)
    rows = await db.fetch(
        """
        UPDATE geo_user_sessions
        SET ended_at = $3, end_reason = 'revoked'
        WHERE user_id = $1::uuid
          AND ($2::text IS NULL OR session_scope = $2)
          AND ended_at IS NULL
        RETURNING id::text AS session_id, user_id::text AS user_id,
                  session_scope, expires_at, ended_at, end_reason
        """,
        user_id,
        session_scope,
        ended_at,
    )
    return [_transition_from_row(row) for row in rows]


def session_audit_event(
    *,
    user_id: str,
    session_id: str,
    session_scope: SessionScope,
    action_key: str,
    route: str | None,
    method: str | None,
    status_code: int | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    reason: str | None = None,
    expires_at: datetime | None = None,
) -> Mapping[str, Any]:
    """Build a privacy-safe auth lifecycle event for AsyncAuditWriter."""
    metadata: dict[str, Any] = {
        "source": "session_auth",
        "session_id": session_id,
        "session_scope": session_scope,
    }
    if reason:
        metadata["reason"] = reason
    if expires_at:
        metadata["expires_at"] = expires_at.isoformat()
    return {
        "user_id": user_id,
        "client_id": None,
        "event_type": "api_action",
        "action_key": action_key,
        "action_label": None,
        "route": route,
        "method": method,
        "status_code": status_code,
        "target_type": "user_session",
        "target_id": session_id,
        "metadata": metadata,
        "ip_address": ip_address,
        "user_agent": user_agent,
    }


class SessionExpiryAuditor:
    """Best-effort Session expiry sweeper that never blocks API requests."""

    def __init__(
        self,
        pool: Any,
        audit_writer: Any,
        *,
        interval_seconds: float = 15 * 60,
    ) -> None:
        self._pool = pool
        self._audit_writer = audit_writer
        self._interval_seconds = max(10.0, interval_seconds)
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="geo-user-session-expiry-auditor",
            )

    async def close(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                transitions = await expire_due_sessions(self._pool)
                for transition in transitions:
                    self._audit_writer.enqueue(
                        session_audit_event(
                            user_id=transition.user_id,
                            session_id=transition.session_id,
                            session_scope=transition.session_scope,
                            action_key="auth.session_expired",
                            route=None,
                            method=None,
                            status_code=None,
                            reason=transition.end_reason,
                            expires_at=transition.expires_at,
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Audit is explicitly best effort. A missing migration during
                # a rolling deploy or a transient DB failure must not prevent
                # the primary service from starting or serving requests.
                logger.warning(
                    "Best-effort Session expiry sweep failed",
                    exc_info=True,
                )
            await asyncio.sleep(self._interval_seconds)
