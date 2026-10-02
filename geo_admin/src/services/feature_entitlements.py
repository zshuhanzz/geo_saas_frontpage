"""Admin-side feature package and Workspace entitlement writes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from geo_common.permissions import FEATURE_REGISTRY

VALID_FEATURE_KEYS = frozenset(feature.key for feature in FEATURE_REGISTRY)
CONFIGURATION_FEATURE_KEY = "actions.configuration"
STANDARD_PACKAGES_WITH_CONFIGURATION = frozenset({"analytics", "full_platform"})


def validate_feature_keys(feature_keys: Iterable[str]) -> list[str]:
    normalized = sorted({str(key).strip() for key in feature_keys if str(key).strip()})
    unknown = [key for key in normalized if key not in VALID_FEATURE_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown code-declared feature keys: {', '.join(unknown)}",
        )
    return normalized


def validate_package_feature_keys(
    package_key: str,
    feature_keys: Iterable[str],
) -> list[str]:
    """Validate package composition and locked standard-package invariants."""
    normalized = validate_feature_keys(feature_keys)
    if (
        package_key in STANDARD_PACKAGES_WITH_CONFIGURATION
        and CONFIGURATION_FEATURE_KEY not in normalized
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{package_key} must include "
                f"{CONFIGURATION_FEATURE_KEY}"
            ),
        )
    return normalized


async def resolve_package_features(conn: Any, package_key: str) -> list[str]:
    package = await conn.fetchrow(
        """
        SELECT package_key
        FROM geo_feature_packages
        WHERE package_key = $1
          AND is_active = true
        """,
        package_key,
    )
    if not package:
        raise HTTPException(status_code=400, detail="Unknown or inactive feature package")
    rows = await conn.fetch(
        """
        SELECT feature_key
        FROM geo_feature_package_items
        WHERE package_key = $1
        ORDER BY feature_key
        """,
        package_key,
    )
    return validate_package_feature_keys(
        package_key,
        (row["feature_key"] for row in rows),
    )


async def apply_workspace_entitlements(
    conn: Any,
    *,
    client_id: str,
    package_key: str | None = None,
    feature_keys: Iterable[str] | None = None,
    updated_by: str | None = None,
) -> list[str]:
    """Atomically replace a Workspace's effective entitlement snapshot."""
    if package_key and feature_keys is not None:
        raise HTTPException(
            status_code=400,
            detail="Choose either a package or explicit feature keys, not both",
        )
    if package_key:
        enabled = await resolve_package_features(conn, package_key)
        is_custom = False
        source = "package"
    elif feature_keys is not None:
        enabled = validate_feature_keys(feature_keys)
        is_custom = True
        source = "custom"
    else:
        raise HTTPException(
            status_code=400,
            detail="A feature package or explicit feature keys is required",
        )

    exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM geo_clients WHERE id = $1::uuid)",
        client_id,
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Workspace not found")

    await conn.execute(
        "DELETE FROM geo_workspace_feature_entitlements WHERE client_id = $1::uuid",
        client_id,
    )
    if enabled:
        await conn.executemany(
            """
            INSERT INTO geo_workspace_feature_entitlements (
                client_id, feature_key, is_enabled, source, updated_by
            )
            VALUES ($1::uuid, $2, true, $3, $4::uuid)
            """,
            [
                (client_id, feature_key, source, updated_by)
                for feature_key in enabled
            ],
        )
    await conn.execute(
        """
        INSERT INTO geo_workspace_entitlement_profiles (
            client_id, applied_package_key, is_custom, updated_by
        )
        VALUES ($1::uuid, $2, $3, $4::uuid)
        ON CONFLICT (client_id) DO UPDATE SET
            applied_package_key = EXCLUDED.applied_package_key,
            is_custom = EXCLUDED.is_custom,
            updated_by = EXCLUDED.updated_by,
            updated_at = NOW()
        """,
        client_id,
        package_key,
        is_custom,
        updated_by,
    )
    return enabled
