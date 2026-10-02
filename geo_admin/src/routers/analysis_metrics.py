"""
Analysis Metrics Router — CRUD for geo_analysis_metrics.

Phase 2.5b (2026-04-26): SQL fully migrated off SQLAlchemy. Uses raw SQL
via the asyncpg-backed ``database`` adapter.
"""
import json
import logging
import math
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from db import database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis/metrics", tags=["Analysis Metrics"])


# Keep the CHECK constraint values in sync with migration 026.
VALID_DOMAINS = {"visibility", "citation", "sentiment", "custom"}
VALID_NULL_BEHAVIORS = {"return_null", "return_zero", "raise"}


# ============================================================================
# Pydantic Models
# ============================================================================

class MetricCreate(BaseModel):
    metric_name: str = Field(..., min_length=1, max_length=120)
    display_name_zh: str = Field(..., min_length=1)
    display_name_en: Optional[str] = None
    domain: str
    description: str = Field(..., min_length=1)
    calculation_hint: str = Field(..., min_length=1)
    relevant_tables: List[str] = []
    sample_question: Optional[str] = None
    null_behavior: str = "return_null"
    unit: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0


class MetricUpdate(BaseModel):
    display_name_zh: Optional[str] = None
    display_name_en: Optional[str] = None
    domain: Optional[str] = None
    description: Optional[str] = None
    calculation_hint: Optional[str] = None
    relevant_tables: Optional[List[str]] = None
    sample_question: Optional[str] = None
    null_behavior: Optional[str] = None
    unit: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class MetricOut(BaseModel):
    id: str
    metric_name: str
    display_name_zh: str
    display_name_en: Optional[str] = None
    domain: str
    description: str
    calculation_hint: str
    relevant_tables: List[str] = []
    sample_question: Optional[str] = None
    null_behavior: str
    unit: Optional[str] = None
    is_active: bool
    sort_order: int
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None


class MetricPagination(BaseModel):
    page: int
    total: int
    pages: int


class MetricListOut(BaseModel):
    data: List[MetricOut]
    pagination: MetricPagination


class TemplateReferenceRow(BaseModel):
    id: str
    name: str
    is_builtin: Optional[bool] = None
    is_active: Optional[bool] = None


class MetricReferencesOut(BaseModel):
    metric_name: str
    references: List[TemplateReferenceRow]


_METRIC_COLUMNS = (
    "id, metric_name, display_name_zh, display_name_en, domain, description, "
    "calculation_hint, relevant_tables, sample_question, null_behavior, unit, "
    "is_active, sort_order, created_at, updated_at"
)


def _serialize(row) -> dict:
    """Convert an asyncpg.Record into a JSON-safe dict."""
    r = dict(row)
    if r.get("id") is not None:
        r["id"] = str(r["id"])
    return r


# ============================================================================
# Static helper endpoints — MUST be declared before /{metric_id}
# ============================================================================

@router.get("/schema-tables", response_model=List[str])
async def list_schema_tables() -> List[str]:
    """Return the live list of ``geo_*`` tables from information_schema."""
    rows = await database.fetch_all(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name LIKE 'geo_%'
        ORDER BY table_name
        """
    )
    return [r["table_name"] for r in rows]


# ============================================================================
# Core CRUD
# ============================================================================

@router.get("", response_model=MetricListOut)
async def list_metrics(
    domain: Optional[str] = None,
    is_active: Optional[bool] = None,
    relevant_table: Optional[str] = Query(
        None,
        description="Filter metrics whose relevant_tables array contains this table",
    ),
    q: Optional[str] = Query(None, description="Substring match on metric_name / display_name_zh"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
) -> MetricListOut:
    """List metrics with optional filters."""
    where_parts: list[str] = []
    params: dict = {}
    if domain:
        if domain not in VALID_DOMAINS:
            raise HTTPException(status_code=400, detail=f"domain must be one of {sorted(VALID_DOMAINS)}")
        where_parts.append("domain = :domain")
        params["domain"] = domain
    if is_active is not None:
        where_parts.append("is_active = :is_active")
        params["is_active"] = is_active
    if relevant_table:
        where_parts.append(":relevant_table = ANY(relevant_tables)")
        params["relevant_table"] = relevant_table
    if q:
        where_parts.append(
            "(metric_name ILIKE :needle OR display_name_zh ILIKE :needle "
            "OR COALESCE(display_name_en, '') ILIKE :needle)"
        )
        params["needle"] = f"%{q}%"

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_analysis_metrics{where_sql}", params
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT {_METRIC_COLUMNS} FROM geo_analysis_metrics
        {where_sql}
        ORDER BY domain, sort_order, metric_name
        OFFSET :offset LIMIT :limit
        """,
        {**params, "offset": (page - 1) * limit, "limit": limit},
    )

    return MetricListOut(
        data=[MetricOut(**_serialize(r)) for r in rows],
        pagination=MetricPagination(
            page=page,
            total=total,
            pages=math.ceil(total / limit) if total else 1,
        ),
    )


@router.get("/{metric_id}", response_model=MetricOut)
async def get_metric(metric_id: UUID) -> MetricOut:
    """Fetch one metric by UUID."""
    row = await database.fetch_one(
        f"SELECT {_METRIC_COLUMNS} FROM geo_analysis_metrics WHERE id = :id",
        {"id": metric_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Metric not found")
    return MetricOut(**_serialize(row))


@router.post("", status_code=201, response_model=MetricOut)
async def create_metric(data: MetricCreate) -> MetricOut:
    """Create a new metric row.

    ``metric_name`` must be unique — enforced both here (friendly 409) and
    by the DB's unique constraint (defensive).
    """
    if data.domain not in VALID_DOMAINS:
        raise HTTPException(status_code=400, detail=f"domain must be one of {sorted(VALID_DOMAINS)}")
    if data.null_behavior not in VALID_NULL_BEHAVIORS:
        raise HTTPException(
            status_code=400,
            detail=f"null_behavior must be one of {sorted(VALID_NULL_BEHAVIORS)}",
        )

    existing = await database.fetch_one(
        "SELECT id FROM geo_analysis_metrics WHERE metric_name = :metric_name",
        {"metric_name": data.metric_name},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Metric with metric_name='{data.metric_name}' already exists",
        )

    row = await database.fetch_one(
        f"""
        INSERT INTO geo_analysis_metrics (
            metric_name, display_name_zh, display_name_en, domain,
            description, calculation_hint, relevant_tables, sample_question,
            null_behavior, unit, is_active, sort_order
        ) VALUES (
            :metric_name, :display_name_zh, :display_name_en, :domain,
            :description, :calculation_hint, :relevant_tables, :sample_question,
            :null_behavior, :unit, :is_active, :sort_order
        )
        RETURNING {_METRIC_COLUMNS}
        """,
        data.model_dump(),
    )
    return MetricOut(**_serialize(row))


@router.put("/{metric_id}", response_model=MetricOut)
async def update_metric(metric_id: UUID, data: MetricUpdate) -> MetricOut:
    """Partial update.

    ``metric_name`` is intentionally NOT editable: it is the stable
    identifier referenced by ``wizard_config.required_metrics`` across
    templates, and renaming would silently break contracts.
    """
    existing = await database.fetch_one(
        "SELECT id FROM geo_analysis_metrics WHERE id = :id",
        {"id": metric_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Metric not found")

    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if "domain" in updates and updates["domain"] not in VALID_DOMAINS:
        raise HTTPException(status_code=400, detail=f"domain must be one of {sorted(VALID_DOMAINS)}")
    if "null_behavior" in updates and updates["null_behavior"] not in VALID_NULL_BEHAVIORS:
        raise HTTPException(
            status_code=400,
            detail=f"null_behavior must be one of {sorted(VALID_NULL_BEHAVIORS)}",
        )

    if updates:
        allowed = {
            "display_name_zh", "display_name_en", "domain", "description",
            "calculation_hint", "relevant_tables", "sample_question",
            "null_behavior", "unit", "is_active", "sort_order",
        }
        sets = [f"{col} = :{col}" for col in updates if col in allowed]
        sets.append("updated_at = NOW()")
        await database.execute(
            f"UPDATE geo_analysis_metrics SET {', '.join(sets)} WHERE id = :id",
            {**updates, "id": metric_id},
        )

    row = await database.fetch_one(
        f"SELECT {_METRIC_COLUMNS} FROM geo_analysis_metrics WHERE id = :id",
        {"id": metric_id},
    )
    return MetricOut(**_serialize(row))


# 204 No Content — response_model= incompatible with empty-body responses.
@router.delete("/{metric_id}", status_code=204)
async def delete_metric(metric_id: UUID) -> None:
    """Delete a metric. Refuses if any template still references it."""
    existing = await database.fetch_one(
        "SELECT metric_name FROM geo_analysis_metrics WHERE id = :id",
        {"id": metric_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Metric not found")

    metric_name = existing["metric_name"]
    refs = await _find_template_references(metric_name)
    if refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"Metric '{metric_name}' is still referenced by "
                    f"{len(refs)} template(s). Remove the references before deleting."
                ),
                "references": refs,
            },
        )

    await database.execute(
        "DELETE FROM geo_analysis_metrics WHERE id = :id", {"id": metric_id}
    )
    return None


@router.get("/{metric_id}/references", response_model=MetricReferencesOut)
async def get_metric_references(metric_id: UUID) -> MetricReferencesOut:
    """Return templates whose ``wizard_config.required_metrics`` references
    this metric. Used by the admin UI's delete confirmation dialog."""
    existing = await database.fetch_one(
        "SELECT metric_name FROM geo_analysis_metrics WHERE id = :id",
        {"id": metric_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Metric not found")

    metric_name = existing["metric_name"]
    refs = await _find_template_references(metric_name)
    return MetricReferencesOut(
        metric_name=metric_name,
        references=[TemplateReferenceRow(**r) for r in refs],
    )


# ============================================================================
# Helpers
# ============================================================================

async def _find_template_references(metric_name: str) -> list[dict]:
    """Return templates whose wizard_config.required_metrics contains the name.

    Uses Postgres JSONB containment for index-friendly matching.
    """
    needle = json.dumps([metric_name])
    rows = await database.fetch_all(
        """
        SELECT id, name, is_builtin, is_active
        FROM geo_report_templates
        WHERE wizard_config IS NOT NULL
          AND wizard_config ? 'required_metrics'
          AND wizard_config->'required_metrics' @> CAST(:needle AS jsonb)
        ORDER BY name
        """,
        {"needle": needle},
    )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "is_builtin": r["is_builtin"],
            "is_active": r["is_active"],
        }
        for r in rows
    ]
