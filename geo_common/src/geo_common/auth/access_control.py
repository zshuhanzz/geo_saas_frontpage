"""Google OAuth user registry and RBAC helpers.

These helpers are intentionally framework-light: FastAPI dependencies in each
service own HTTP concerns, while this module owns token verification, user
upsert, and database-backed access decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from geo_common.permissions import FEATURE_REGISTRY, capability_allowed
from geo_common.permissions.registry import Capability

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

AdminRole = Literal["super_admin", "viewer"]
ClientRole = Literal["admin", "viewer", "account_manager"]
WorkspaceRole = Literal["admin", "viewer", "account_manager", "super_admin"]
GOOGLE_ID_TOKEN_CLOCK_SKEW_SECONDS = 120


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    google_sub: str | None
    name: str | None
    avatar_url: str | None
    is_active: bool


@dataclass(frozen=True)
class AdminAccess:
    role: AdminRole
    support_all_clients: bool
    is_active: bool


@dataclass(frozen=True)
class WorkspaceAccess:
    """Effective access context for one user and one Workspace."""

    client_id: str
    role: WorkspaceRole
    enabled_features: frozenset[str]
    support_override: bool = False
    entitlement_override: bool = False

    def is_entitled(self, feature_key: str) -> bool:
        return self.entitlement_override or feature_key in self.enabled_features

    def allows(self, feature_key: str, capability: Capability) -> bool:
        return self.is_entitled(feature_key) and capability_allowed(
            self.role,
            feature_key,
            capability,
        )


def normalize_email(email: str) -> str:
    """Normalize email addresses for unique lookup and display matching."""
    return email.strip().lower()


def verify_google_id_token(token: str, google_client_id: str) -> dict[str, Any]:
    """Verify a Google OAuth ID token and return its claims."""
    claims = id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        google_client_id,
        clock_skew_in_seconds=GOOGLE_ID_TOKEN_CLOCK_SKEW_SECONDS,
    )
    if not claims.get("email"):
        raise ValueError("Google token does not contain email")
    return claims


def _authenticated_user_from_row(row: Any) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(row["id"]),
        email=row["email"],
        google_sub=row["google_sub"],
        name=row["name"],
        avatar_url=row["avatar_url"],
        is_active=row["is_active"],
    )


async def upsert_google_user(db: Any, claims: dict[str, Any]) -> AuthenticatedUser:
    """Create or refresh a user from Google OAuth claims.

    This is not authorization. It only keeps a user registry in sync with a
    verified Google identity; SaaS/Admin permissions still require explicit
    access rows.
    """
    email = normalize_email(str(claims["email"]))
    row = await db.fetchrow(
        """
        INSERT INTO geo_users (email, google_sub, name, avatar_url, last_login_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (LOWER(email)) DO UPDATE SET
            google_sub = COALESCE(EXCLUDED.google_sub, geo_users.google_sub),
            name = COALESCE(geo_users.name, EXCLUDED.name),
            avatar_url = COALESCE(EXCLUDED.avatar_url, geo_users.avatar_url),
            last_login_at = NOW(),
            updated_at = NOW()
        RETURNING id, email, google_sub, name, avatar_url, is_active
        """,
        email,
        claims.get("sub"),
        claims.get("name"),
        claims.get("picture"),
    )
    if row is None:
        raise RuntimeError("Failed to upsert Google user")
    return _authenticated_user_from_row(row)


async def get_admin_access(db: Any, user_id: str) -> AdminAccess | None:
    """Return Admin system access for a user, if configured."""
    row = await db.fetchrow(
        """
        SELECT role, support_all_clients, is_active
        FROM geo_admin_user_access
        WHERE user_id = $1::uuid
        """,
        user_id,
    )
    if not row:
        return None
    return AdminAccess(
        role=row["role"],
        support_all_clients=row["support_all_clients"],
        is_active=row["is_active"],
    )


async def has_support_all_clients(db: Any, user_id: str) -> bool:
    """Return True when a Super Admin has explicit SaaS all-client support."""
    row = await db.fetchrow(
        """
        SELECT 1 AS exists
        FROM geo_admin_user_access
        WHERE user_id = $1::uuid
          AND role = 'super_admin'
          AND support_all_clients = true
          AND is_active = true
        """,
        user_id,
    )
    return row is not None


async def has_client_access(db: Any, user_id: str, client_id: str) -> bool:
    """Return True when user can access a SaaS client."""
    if await has_support_all_clients(db, user_id):
        return True
    row = await db.fetchrow(
        """
        SELECT 1 AS exists
        FROM geo_client_user_access
        WHERE user_id = $1::uuid
          AND client_id = $2::uuid
          AND is_active = true
        """,
        user_id,
        client_id,
    )
    return row is not None


async def get_workspace_access(
    db: Any,
    user_id: str,
    client_id: str,
) -> WorkspaceAccess | None:
    """Load role + entitlement state used by SaaS and Agent authorization."""
    admin_access = await get_admin_access(db, user_id)
    is_super_admin = bool(
        admin_access
        and admin_access.is_active
        and admin_access.role == "super_admin"
    )
    support_override = bool(
        is_super_admin
        and admin_access
        and admin_access.support_all_clients
    )

    grant_role: ClientRole | None = None
    if not support_override:
        role_value = await db.fetchval(
            """
            SELECT role
            FROM geo_client_user_access
            WHERE user_id = $1::uuid
              AND client_id = $2::uuid
              AND is_active = true
            """,
            user_id,
            client_id,
        )
        if role_value not in {"admin", "viewer", "account_manager"}:
            return None
        grant_role = role_value

    if is_super_admin:
        role: WorkspaceRole = "super_admin"
    elif grant_role is not None:
        # support_override is only possible for an active Super Admin, so a
        # non-Super-Admin path always has an explicit Workspace grant.
        role = grant_role
    else:
        # Defensive guard for future role/source changes.
        return None

    entitlement_override = role in {"account_manager", "super_admin"}
    if entitlement_override:
        enabled_features = frozenset(feature.key for feature in FEATURE_REGISTRY)
    else:
        rows = await db.fetch(
            """
            SELECT feature_key
            FROM geo_workspace_feature_entitlements
            WHERE client_id = $1::uuid
              AND is_enabled = true
            """,
            client_id,
        )
        enabled_features = frozenset(str(row["feature_key"]) for row in rows)

    return WorkspaceAccess(
        client_id=client_id,
        role=role,
        enabled_features=enabled_features,
        support_override=support_override,
        entitlement_override=entitlement_override,
    )


async def get_workspace_access_or_legacy_full(
    db: Any,
    user_id: str,
    client_id: str,
) -> WorkspaceAccess | None:
    """Migration-safe loader for rolling deployments.

    The migration must be applied before production rollout. This fallback
    exists only so local environments and staggered Cloud Run revisions do
    not temporarily lock every Workspace while migration 133 is pending.
    """
    try:
        return await get_workspace_access(db, user_id, client_id)
    except Exception as exc:
        # asyncpg is intentionally an optional implementation detail here.
        if exc.__class__.__name__ != "UndefinedTableError":
            raise
        if not await has_client_access(db, user_id, client_id):
            return None
        role_value = await db.fetchval(
            """
            SELECT role
            FROM geo_client_user_access
            WHERE user_id = $1::uuid
              AND client_id = $2::uuid
              AND is_active = true
            """,
            user_id,
            client_id,
        )
        admin_access = await get_admin_access(db, user_id)
        is_super_admin = bool(
            admin_access
            and admin_access.is_active
            and admin_access.role == "super_admin"
        )
        role: WorkspaceRole
        if is_super_admin:
            role = "super_admin"
        elif role_value in {"admin", "viewer", "account_manager"}:
            role = role_value
        else:
            role = "admin"
        return WorkspaceAccess(
            client_id=client_id,
            role=role,
            enabled_features=frozenset(feature.key for feature in FEATURE_REGISTRY),
            support_override=bool(
                is_super_admin
                and admin_access
                and admin_access.support_all_clients
            ),
            entitlement_override=role in {"account_manager", "super_admin"},
        )
