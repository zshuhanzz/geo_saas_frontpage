"""
Content Optimization Framework Router — CRUD for metrics, subgoals, strategies, content assets.

Manages the 4-layer content optimization framework:
- Layer 1: geo_optimization_metrics
- Layer 2: geo_optimization_subgoals
- Layer 3: geo_strategies
- Feedback: geo_content_assets

Phase 2.5b (2026-04-26): SQL fully migrated off SQLAlchemy.
"""
import json as _json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from services.workspace_lifecycle import long_workspace_lifecycle_session
from pydantic import BaseModel, ConfigDict

from db import database

router = APIRouter(prefix="/content-framework", tags=["Content Framework"])


# ============================================================================
# Pydantic Models
# ============================================================================

class MetricCreate(BaseModel):
    id: str
    name_zh: str
    name_en: str
    description: str
    icon: Optional[str] = "📊"
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True

class MetricUpdate(BaseModel):
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

class SubgoalCreate(BaseModel):
    id: str
    metric_id: str
    name_zh: str
    name_en: str
    description: str
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True

class SubgoalUpdate(BaseModel):
    metric_id: Optional[str] = None
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    dimensions: Optional[dict] = {}
    source_metrics: Optional[List[str]] = []
    source_subgoals: Optional[List[str]] = []
    content_type: Optional[str] = None
    generation_method: Optional[str] = "llm_with_postprocess"
    is_seed: Optional[bool] = False
    is_active: Optional[bool] = True

class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    dimensions: Optional[dict] = None
    source_metrics: Optional[List[str]] = None
    source_subgoals: Optional[List[str]] = None
    content_type: Optional[str] = None
    generation_method: Optional[str] = None
    is_seed: Optional[bool] = None
    is_active: Optional[bool] = None

class ContentAssetCreate(BaseModel):
    client_id: str
    content_task_id: Optional[str] = None
    published_url: Optional[str] = None
    published_platform: Optional[str] = None
    published_at: Optional[str] = None
    tracking_status: Optional[str] = "pending"
    metadata: Optional[dict] = {}

class ContentAssetUpdate(BaseModel):
    published_url: Optional[str] = None
    published_platform: Optional[str] = None
    published_at: Optional[str] = None
    tracking_status: Optional[str] = None
    metadata: Optional[dict] = None


# Output models — mirror the table columns. ``id`` is the schema-defined PK
# (Text for metric/subgoal, UUID-as-string for strategy/asset).

class MetricOut(BaseModel):
    id: str
    name_zh: str
    name_en: str
    description: str
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SubgoalOut(BaseModel):
    id: str
    metric_id: str
    name_zh: str
    name_en: str
    description: str
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class StrategyOut(BaseModel):
    id: Any
    name: str
    description: Optional[str] = None
    dimensions: Optional[Any] = None
    source_metrics: Optional[List[str]] = None
    source_subgoals: Optional[List[str]] = None
    content_type: Optional[str] = None
    generation_method: Optional[str] = None
    is_seed: Optional[bool] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ContentAssetOut(BaseModel):
    id: Any
    client_id: Any
    content_task_id: Optional[Any] = None
    published_url: Optional[str] = None
    published_platform: Optional[str] = None
    published_at: Optional[datetime] = None
    tracking_status: Optional[str] = None
    metadata: Optional[Any] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ContentAssetPagination(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class ContentAssetListOut(BaseModel):
    data: List[ContentAssetOut]
    pagination: ContentAssetPagination


_METRIC_COLUMNS = "id, name_zh, name_en, description, icon, sort_order, is_active, created_at"
_SUBGOAL_COLUMNS = "id, metric_id, name_zh, name_en, description, sort_order, is_active, created_at"
_STRATEGY_COLUMNS = (
    "id, name, description, dimensions, source_metrics, source_subgoals, "
    "content_type, generation_method, is_seed, is_active, created_at, updated_at"
)
_CONTENT_ASSET_COLUMNS = (
    "id, client_id, content_task_id, published_url, published_platform, "
    "published_at, tracking_status, metadata, created_at, updated_at"
)


# ============================================================================
# Metrics CRUD (Layer 1)
# ============================================================================

@router.get("/metrics", response_model=List[MetricOut])
async def list_metrics(active_only: bool = False) -> List[MetricOut]:
    """List all optimization metrics."""
    where_sql = "WHERE is_active = TRUE" if active_only else ""
    rows = await database.fetch_all(
        f"SELECT {_METRIC_COLUMNS} FROM geo_optimization_metrics {where_sql} ORDER BY sort_order"
    )
    return [MetricOut(**dict(r)) for r in rows]


@router.post("/metrics", status_code=201, response_model=MetricOut)
async def create_metric(data: MetricCreate) -> MetricOut:
    """Create a new optimization metric."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_optimization_metrics WHERE id = :id", {"id": data.id}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Metric with this ID already exists")
    await database.execute(
        """
        INSERT INTO geo_optimization_metrics
            (id, name_zh, name_en, description, icon, sort_order, is_active)
        VALUES
            (:id, :name_zh, :name_en, :description, :icon, :sort_order, :is_active)
        """,
        data.model_dump(),
    )
    return MetricOut(**data.model_dump())


@router.put("/metrics/{metric_id}", response_model=MetricOut)
async def update_metric(metric_id: str, data: MetricUpdate) -> MetricOut:
    """Update an optimization metric."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_optimization_metrics WHERE id = :id", {"id": metric_id}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Metric not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        allowed = {"name_zh", "name_en", "description", "icon", "sort_order", "is_active"}
        sets = [f"{c} = :{c}" for c in updates if c in allowed]
        if sets:
            await database.execute(
                f"UPDATE geo_optimization_metrics SET {', '.join(sets)} WHERE id = :id",
                {**updates, "id": metric_id},
            )
    row = await database.fetch_one(
        f"SELECT {_METRIC_COLUMNS} FROM geo_optimization_metrics WHERE id = :id",
        {"id": metric_id},
    )
    return MetricOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/metrics/{metric_id}", status_code=204)
async def delete_metric(metric_id: str) -> None:
    """Delete an optimization metric."""
    await database.execute(
        "DELETE FROM geo_optimization_metrics WHERE id = :id", {"id": metric_id}
    )
    return None


# ============================================================================
# Subgoals CRUD (Layer 2)
# ============================================================================

@router.get("/subgoals", response_model=List[SubgoalOut])
async def list_subgoals(
    metric_id: Optional[str] = None, active_only: bool = False
) -> List[SubgoalOut]:
    """List all optimization subgoals, optionally filtered by metric."""
    where_parts: list[str] = []
    params: dict = {}
    if metric_id:
        where_parts.append("metric_id = :metric_id")
        params["metric_id"] = metric_id
    if active_only:
        where_parts.append("is_active = TRUE")
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    rows = await database.fetch_all(
        f"""
        SELECT {_SUBGOAL_COLUMNS} FROM geo_optimization_subgoals
        {where_sql}
        ORDER BY metric_id, sort_order
        """,
        params,
    )
    return [SubgoalOut(**dict(r)) for r in rows]


@router.post("/subgoals", status_code=201, response_model=SubgoalOut)
async def create_subgoal(data: SubgoalCreate) -> SubgoalOut:
    """Create a new optimization subgoal."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_optimization_subgoals WHERE id = :id", {"id": data.id}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Subgoal with this ID already exists")
    metric = await database.fetch_one(
        "SELECT id FROM geo_optimization_metrics WHERE id = :id",
        {"id": data.metric_id},
    )
    if not metric:
        raise HTTPException(status_code=400, detail=f"Metric '{data.metric_id}' not found")
    await database.execute(
        """
        INSERT INTO geo_optimization_subgoals
            (id, metric_id, name_zh, name_en, description, sort_order, is_active)
        VALUES
            (:id, :metric_id, :name_zh, :name_en, :description, :sort_order, :is_active)
        """,
        data.model_dump(),
    )
    return SubgoalOut(**data.model_dump())


@router.put("/subgoals/{subgoal_id}", response_model=SubgoalOut)
async def update_subgoal(subgoal_id: str, data: SubgoalUpdate) -> SubgoalOut:
    """Update an optimization subgoal."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_optimization_subgoals WHERE id = :id",
        {"id": subgoal_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Subgoal not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        allowed = {"metric_id", "name_zh", "name_en", "description", "sort_order", "is_active"}
        sets = [f"{c} = :{c}" for c in updates if c in allowed]
        if sets:
            await database.execute(
                f"UPDATE geo_optimization_subgoals SET {', '.join(sets)} WHERE id = :id",
                {**updates, "id": subgoal_id},
            )
    row = await database.fetch_one(
        f"SELECT {_SUBGOAL_COLUMNS} FROM geo_optimization_subgoals WHERE id = :id",
        {"id": subgoal_id},
    )
    return SubgoalOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/subgoals/{subgoal_id}", status_code=204)
async def delete_subgoal(subgoal_id: str) -> None:
    """Delete an optimization subgoal."""
    await database.execute(
        "DELETE FROM geo_optimization_subgoals WHERE id = :id",
        {"id": subgoal_id},
    )
    return None


# ============================================================================
# Strategies CRUD (Layer 3)
# ============================================================================

@router.get("/strategies", response_model=List[StrategyOut])
async def list_strategies(
    content_type: Optional[str] = None,
    is_seed: Optional[bool] = None,
    active_only: bool = False,
) -> List[StrategyOut]:
    """List all content optimization strategies."""
    where_parts: list[str] = []
    params: dict = {}
    if content_type:
        where_parts.append("content_type = :content_type")
        params["content_type"] = content_type
    if is_seed is not None:
        where_parts.append("is_seed = :is_seed")
        params["is_seed"] = is_seed
    if active_only:
        where_parts.append("is_active = TRUE")
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    rows = await database.fetch_all(
        f"""
        SELECT {_STRATEGY_COLUMNS} FROM geo_strategies
        {where_sql}
        ORDER BY created_at DESC
        """,
        params,
    )
    return [StrategyOut(**dict(r)) for r in rows]


@router.post("/strategies", status_code=201, response_model=StrategyOut)
async def create_strategy(data: StrategyCreate) -> StrategyOut:
    """Create a new content optimization strategy."""
    result = await database.fetch_one(
        f"""
        INSERT INTO geo_strategies (
            name, description, dimensions, source_metrics, source_subgoals,
            content_type, generation_method, is_seed, is_active
        ) VALUES (
            :name, :description, :dimensions::jsonb, :source_metrics, :source_subgoals,
            :content_type, :generation_method, :is_seed, :is_active
        )
        RETURNING {_STRATEGY_COLUMNS}
        """,
        {
            "name": data.name,
            "description": data.description,
            "dimensions": _json.dumps(data.dimensions or {}),
            "source_metrics": data.source_metrics or [],
            "source_subgoals": data.source_subgoals or [],
            "content_type": data.content_type,
            "generation_method": data.generation_method,
            "is_seed": data.is_seed,
            "is_active": data.is_active,
        },
    )
    return StrategyOut(**dict(result))


@router.put("/strategies/{strategy_id}", response_model=StrategyOut)
async def update_strategy(strategy_id: UUID, data: StrategyUpdate) -> StrategyOut:
    """Update a content optimization strategy."""
    existing = await database.fetch_one(
        "SELECT id FROM geo_strategies WHERE id = :id", {"id": strategy_id}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Strategy not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        allowed = {
            "name", "description", "dimensions", "source_metrics",
            "source_subgoals", "content_type", "generation_method",
            "is_seed", "is_active",
        }
        sets = []
        params: dict = {"id": strategy_id}
        for col, val in updates.items():
            if col not in allowed:
                continue
            if col == "dimensions":
                params[col] = _json.dumps(val)
                sets.append(f"{col} = :{col}::jsonb")
            else:
                params[col] = val
                sets.append(f"{col} = :{col}")
        sets.append("updated_at = NOW()")
        await database.execute(
            f"UPDATE geo_strategies SET {', '.join(sets)} WHERE id = :id",
            params,
        )
    row = await database.fetch_one(
        f"SELECT {_STRATEGY_COLUMNS} FROM geo_strategies WHERE id = :id",
        {"id": strategy_id},
    )
    return StrategyOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/strategies/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: UUID) -> None:
    """Delete a content optimization strategy."""
    await database.execute(
        "DELETE FROM geo_strategies WHERE id = :id", {"id": strategy_id}
    )
    return None


# ============================================================================
# Content Assets CRUD (Feedback Loop)
# ============================================================================

@router.get("/assets", response_model=ContentAssetListOut)
async def list_content_assets(
    client_id: Optional[str] = None,
    tracking_status: Optional[str] = None,
    published_platform: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
) -> ContentAssetListOut:
    """List content assets with filters and pagination."""
    where_parts: list[str] = []
    params: dict = {}
    if client_id:
        where_parts.append("client_id = :client_id")
        params["client_id"] = client_id
    if tracking_status:
        where_parts.append("tracking_status = :tracking_status")
        params["tracking_status"] = tracking_status
    if published_platform:
        where_parts.append("published_platform = :published_platform")
        params["published_platform"] = published_platform
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_content_assets{where_sql}", params
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT {_CONTENT_ASSET_COLUMNS} FROM geo_content_assets
        {where_sql}
        ORDER BY created_at DESC
        OFFSET :offset LIMIT :limit
        """,
        {**params, "offset": (page - 1) * limit, "limit": limit},
    )

    return ContentAssetListOut(
        data=[ContentAssetOut(**dict(r)) for r in rows],
        pagination=ContentAssetPagination(
            page=page,
            limit=limit,
            total=total,
            pages=(total + limit - 1) // limit if total else 1,
        ),
    )


@router.post("/assets", status_code=201, response_model=ContentAssetOut)
async def create_content_asset(data: ContentAssetCreate) -> ContentAssetOut:
    """Create a new content asset record."""
    async with long_workspace_lifecycle_session(database.pool(), str(data.client_id)):
        result = await database.fetch_one(
            f"""
            INSERT INTO geo_content_assets (
                client_id, content_task_id, published_url, published_platform,
                published_at, tracking_status, metadata
            ) VALUES (
                :client_id, :content_task_id, :published_url, :published_platform,
                :published_at, :tracking_status, :metadata::jsonb
            )
            RETURNING {_CONTENT_ASSET_COLUMNS}
            """,
            {
                "client_id": data.client_id,
                "content_task_id": data.content_task_id,
                "published_url": data.published_url,
                "published_platform": data.published_platform,
                "published_at": data.published_at,
                "tracking_status": data.tracking_status,
                "metadata": _json.dumps(data.metadata or {}),
            },
        )
    return ContentAssetOut(**dict(result))


@router.put("/assets/{asset_id}", response_model=ContentAssetOut)
async def update_content_asset(asset_id: UUID, data: ContentAssetUpdate) -> ContentAssetOut:
    """Update a content asset."""
    existing = await database.fetch_one(
        "SELECT id, client_id::text AS client_id FROM geo_content_assets WHERE id = :id", {"id": asset_id}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Content asset not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        allowed = {
            "published_url", "published_platform", "published_at",
            "tracking_status", "metadata",
        }
        sets = []
        params: dict = {"id": asset_id}
        for col, val in updates.items():
            if col not in allowed:
                continue
            if col == "metadata":
                params[col] = _json.dumps(val)
                sets.append(f"{col} = :{col}::jsonb")
            else:
                params[col] = val
                sets.append(f"{col} = :{col}")
        sets.append("updated_at = NOW()")
        async with long_workspace_lifecycle_session(database.pool(), str(existing["client_id"])):
            await database.execute(
                f"UPDATE geo_content_assets SET {', '.join(sets)} WHERE id = :id",
                params,
            )
    row = await database.fetch_one(
        f"SELECT {_CONTENT_ASSET_COLUMNS} FROM geo_content_assets WHERE id = :id",
        {"id": asset_id},
    )
    return ContentAssetOut(**dict(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/assets/{asset_id}", status_code=204)
async def delete_content_asset(asset_id: UUID) -> None:
    """Delete a content asset."""
    existing = await database.fetch_one(
        "SELECT client_id::text AS client_id FROM geo_content_assets WHERE id = :id",
        {"id": asset_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Content asset not found")
    async with long_workspace_lifecycle_session(database.pool(), str(existing["client_id"])):
        await database.execute(
            "DELETE FROM geo_content_assets WHERE id = :id", {"id": asset_id}
        )
    return None
