"""Current SaaS identity and lightweight bootstrap endpoints."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from geo_common.auth import AuthenticatedUser, WorkspaceRole, get_admin_access
from geo_common.permissions import FEATURE_REGISTRY, ROLE_CAPABILITIES
from pydantic import BaseModel, Field

from dependencies.auth import require_current_user
from pool import get_pool

router = APIRouter()


class CurrentUserOut(BaseModel):
    id: str
    email: str
    google_sub: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool


class WorkspaceSummaryOut(BaseModel):
    """Authorization-first Workspace bootstrap data.

    Configuration rows such as topics/products are intentionally excluded and
    loaded only after the user selects a Workspace.
    """

    id: str
    name: str
    role: WorkspaceRole
    enabled_features: list[str] = Field(default_factory=list)
    feature_capabilities: dict[str, list[str]] = Field(default_factory=dict)
    entitlement_override: bool = False


class FeatureCatalogItemOut(BaseModel):
    feature_key: str
    module_key: str
    display_name_zh: str
    display_name_en: str
    description_zh: str
    description_en: str
    sort_order: int


def _role_capabilities(role: str) -> dict[str, list[str]]:
    return {
        feature_key: list(capabilities)
        for feature_key, capabilities in ROLE_CAPABILITIES.get(role, {}).items()
    }


@router.get("/me", response_model=CurrentUserOut)
async def get_current_user(
    current_user: AuthenticatedUser = Depends(require_current_user),
) -> CurrentUserOut:
    """Return the database-backed user profile for the current SaaS Session."""
    return CurrentUserOut(
        id=current_user.id,
        email=current_user.email,
        google_sub=current_user.google_sub,
        name=current_user.name,
        avatar_url=current_user.avatar_url,
        is_active=current_user.is_active,
    )


@router.get("/me/workspaces", response_model=list[WorkspaceSummaryOut])
async def list_accessible_workspaces(
    current_user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> list[WorkspaceSummaryOut]:
    """List only Workspaces the current user is authorized to access.

    Super Admin broad scope is opt-in through ``support_all_clients``.
    Otherwise the query is anchored to the caller's active Workspace grants;
    no metadata for an ungranted Workspace is read or returned.
    """
    admin_access = await get_admin_access(pool, current_user.id)
    is_super_admin = bool(
        admin_access
        and admin_access.is_active
        and admin_access.role == "super_admin"
    )
    support_all_clients = bool(
        is_super_admin
        and admin_access
        and admin_access.support_all_clients
    )

    if support_all_clients:
        workspace_rows = await pool.fetch(
            """
            SELECT c.id, c.name, NULL::text AS grant_role
            FROM geo_clients AS c
            ORDER BY c.name
            """
        )
    else:
        workspace_rows = await pool.fetch(
            """
            SELECT c.id, c.name, a.role AS grant_role
            FROM geo_client_user_access AS a
            JOIN geo_clients AS c ON c.id = a.client_id
            WHERE a.user_id = $1::uuid
              AND a.is_active = true
            ORDER BY c.name
            """,
            current_user.id,
        )

    valid_rows: list[Any] = []
    standard_workspace_ids: list[Any] = []
    for row in workspace_rows:
        grant_role = row["grant_role"]
        if not support_all_clients and grant_role not in {
            "admin",
            "viewer",
            "account_manager",
        }:
            continue
        valid_rows.append(row)
        effective_role = (
            "super_admin"
            if is_super_admin
            else str(grant_role)
        )
        if effective_role not in {"super_admin", "account_manager"}:
            standard_workspace_ids.append(row["id"])

    entitlements: dict[str, set[str]] = {}
    if standard_workspace_ids:
        entitlement_rows = await pool.fetch(
            """
            SELECT client_id, feature_key
            FROM geo_workspace_feature_entitlements
            WHERE client_id = ANY($1::uuid[])
              AND is_enabled = true
            """,
            standard_workspace_ids,
        )
        for row in entitlement_rows:
            entitlements.setdefault(str(row["client_id"]), set()).add(
                str(row["feature_key"])
            )

    all_features = sorted(feature.key for feature in FEATURE_REGISTRY)
    result: list[WorkspaceSummaryOut] = []
    for row in valid_rows:
        grant_role = row["grant_role"]
        role = "super_admin" if is_super_admin else str(grant_role)
        entitlement_override = role in {"super_admin", "account_manager"}
        workspace_id = str(row["id"])
        result.append(
            WorkspaceSummaryOut(
                id=workspace_id,
                name=str(row["name"]),
                role=role,
                enabled_features=(
                    all_features
                    if entitlement_override
                    else sorted(entitlements.get(workspace_id, set()))
                ),
                feature_capabilities=_role_capabilities(role),
                entitlement_override=entitlement_override,
            )
        )
    return result


@router.get("/me/feature-catalog", response_model=list[FeatureCatalogItemOut])
async def get_feature_catalog(
    current_user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> list[FeatureCatalogItemOut]:
    """Return Admin-managed feature display metadata to authenticated users."""
    del current_user  # Authentication is the permission boundary for this catalog.
    rows = await pool.fetch(
        """
        SELECT feature_key, module_key, display_name_zh, display_name_en,
               description_zh, description_en, sort_order
        FROM geo_feature_catalog
        WHERE is_active = true
        ORDER BY module_key, sort_order, feature_key
        """
    )
    registered_keys = {feature.key for feature in FEATURE_REGISTRY}
    return [
        FeatureCatalogItemOut(**dict(row))
        for row in rows
        if str(row["feature_key"]) in registered_keys
    ]
