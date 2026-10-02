"""Internal Admin API for feature metadata, packages, and Workspace grants."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from geo_common.auth import AuthenticatedUser
from geo_common.permissions import (
    FEATURE_REGISTRY,
    MODULES,
    ROLE_CAPABILITIES,
)
from pydantic import BaseModel, Field

from dependencies.auth import require_current_user, require_super_admin
from pool import get_pool
from services.feature_entitlements import (
    apply_workspace_entitlements,
    validate_feature_keys,
    validate_package_feature_keys,
)

router = APIRouter(prefix="/feature-access", tags=["Feature Access"])


class FeatureMetadataUpdate(BaseModel):
    display_name_zh: Optional[str] = None
    display_name_en: Optional[str] = None
    description_zh: Optional[str] = None
    description_en: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class PackageWrite(BaseModel):
    package_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    display_name_zh: str = Field(min_length=1, max_length=120)
    display_name_en: str = Field(min_length=1, max_length=120)
    description_zh: str = ""
    description_en: str = ""
    sort_order: int = 0
    is_active: bool = True
    feature_keys: list[str] = Field(min_length=1)


class WorkspaceEntitlementWrite(BaseModel):
    package_key: Optional[str] = None
    feature_keys: Optional[list[str]] = None


class WorkspaceOptionOut(BaseModel):
    id: str
    name: str


@router.get("/registry")
async def get_feature_registry(pool=Depends(get_pool)) -> dict:
    metadata_rows = await pool.fetch(
        """
        SELECT feature_key, module_key, display_name_zh, display_name_en,
               description_zh, description_en, sort_order, is_active
        FROM geo_feature_catalog
        """
    )
    metadata = {row["feature_key"]: dict(row) for row in metadata_rows}
    return {
        "modules": [
            {
                "key": module.key,
                "label_zh": module.label_zh,
                "label_en": module.label_en,
                "sort_order": module.sort_order,
            }
            for module in MODULES
        ],
        "features": [
            {
                "key": feature.key,
                "module_key": feature.module_key,
                "display_name_zh": metadata.get(feature.key, {}).get(
                    "display_name_zh",
                    feature.label_zh,
                ),
                "display_name_en": metadata.get(feature.key, {}).get(
                    "display_name_en",
                    feature.label_en,
                ),
                "description_zh": metadata.get(feature.key, {}).get(
                    "description_zh",
                    feature.description_zh,
                ),
                "description_en": metadata.get(feature.key, {}).get(
                    "description_en",
                    feature.description_en,
                ),
                "sort_order": metadata.get(feature.key, {}).get(
                    "sort_order",
                    feature.sort_order,
                ),
                "is_active": metadata.get(feature.key, {}).get("is_active", True),
            }
            for feature in FEATURE_REGISTRY
        ],
        "role_capabilities": ROLE_CAPABILITIES,
    }


@router.patch(
    "/registry/{feature_key}",
    dependencies=[Depends(require_super_admin)],
)
async def update_feature_metadata(
    feature_key: str,
    data: FeatureMetadataUpdate,
    pool=Depends(get_pool),
) -> dict:
    validate_feature_keys([feature_key])
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No changes supplied")
    columns = []
    params: list[object] = [feature_key]
    for column, value in updates.items():
        params.append(value)
        columns.append(f"{column} = ${len(params)}")
    row = await pool.fetchrow(
        f"""
        UPDATE geo_feature_catalog
        SET {", ".join(columns)}, updated_at = NOW()
        WHERE feature_key = $1
        RETURNING feature_key, module_key, display_name_zh, display_name_en,
                  description_zh, description_en, sort_order, is_active
        """,
        *params,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Feature metadata not found")
    return dict(row)


@router.get("/packages")
async def list_packages(pool=Depends(get_pool)) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT p.package_key, p.display_name_zh, p.display_name_en,
               p.description_zh, p.description_en, p.sort_order,
               p.is_system, p.is_active,
               COALESCE(
                   array_agg(i.feature_key ORDER BY i.feature_key)
                       FILTER (WHERE i.feature_key IS NOT NULL),
                   ARRAY[]::text[]
               ) AS feature_keys
        FROM geo_feature_packages p
        LEFT JOIN geo_feature_package_items i
          ON i.package_key = p.package_key
        GROUP BY p.package_key
        ORDER BY p.sort_order, p.package_key
        """
    )
    return [dict(row) for row in rows]


@router.put(
    "/packages/{package_key}",
    dependencies=[Depends(require_super_admin)],
)
async def upsert_package(
    package_key: str,
    data: PackageWrite,
    pool=Depends(get_pool),
) -> dict:
    if package_key != data.package_key:
        raise HTTPException(status_code=400, detail="Package key cannot be renamed")
    feature_keys = validate_package_feature_keys(
        data.package_key,
        data.feature_keys,
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO geo_feature_packages (
                    package_key, display_name_zh, display_name_en,
                    description_zh, description_en, sort_order, is_active
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (package_key) DO UPDATE SET
                    display_name_zh = EXCLUDED.display_name_zh,
                    display_name_en = EXCLUDED.display_name_en,
                    description_zh = EXCLUDED.description_zh,
                    description_en = EXCLUDED.description_en,
                    sort_order = EXCLUDED.sort_order,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                """,
                data.package_key,
                data.display_name_zh,
                data.display_name_en,
                data.description_zh,
                data.description_en,
                data.sort_order,
                data.is_active,
            )
            await conn.execute(
                "DELETE FROM geo_feature_package_items WHERE package_key = $1",
                data.package_key,
            )
            await conn.executemany(
                """
                INSERT INTO geo_feature_package_items (package_key, feature_key)
                VALUES ($1, $2)
                """,
                [(data.package_key, feature_key) for feature_key in feature_keys],
            )
    return {"package_key": data.package_key, "feature_keys": feature_keys}


@router.get("/workspaces", response_model=list[WorkspaceOptionOut])
async def list_workspace_options(pool=Depends(get_pool)) -> list[dict]:
    """Return only the fields needed by the Feature Access Workspace selector."""
    rows = await pool.fetch(
        """
        SELECT id::text AS id, name
        FROM geo_clients
        ORDER BY name, id
        """
    )
    return [{"id": str(row["id"]), "name": row["name"]} for row in rows]


@router.get("/workspaces/{client_id}")
async def get_workspace_entitlements(
    client_id: str,
    pool=Depends(get_pool),
) -> dict:
    profile = await pool.fetchrow(
        """
        SELECT applied_package_key, is_custom, updated_at
        FROM geo_workspace_entitlement_profiles
        WHERE client_id = $1::uuid
        """,
        client_id,
    )
    exists = await pool.fetchval(
        "SELECT EXISTS(SELECT 1 FROM geo_clients WHERE id = $1::uuid)",
        client_id,
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Workspace not found")
    rows = await pool.fetch(
        """
        SELECT feature_key
        FROM geo_workspace_feature_entitlements
        WHERE client_id = $1::uuid
          AND is_enabled = true
        ORDER BY feature_key
        """,
        client_id,
    )
    return {
        "client_id": client_id,
        "applied_package_key": profile["applied_package_key"] if profile else None,
        "is_custom": profile["is_custom"] if profile else True,
        "feature_keys": [row["feature_key"] for row in rows],
        "updated_at": profile["updated_at"] if profile else None,
    }


@router.put(
    "/workspaces/{client_id}",
    dependencies=[Depends(require_super_admin)],
)
async def replace_workspace_entitlements(
    client_id: str,
    data: WorkspaceEntitlementWrite,
    actor: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            enabled = await apply_workspace_entitlements(
                conn,
                client_id=client_id,
                package_key=data.package_key,
                feature_keys=data.feature_keys,
                updated_by=actor.id,
            )
    return {
        "client_id": client_id,
        "applied_package_key": data.package_key,
        "is_custom": data.package_key is None,
        "feature_keys": enabled,
    }
