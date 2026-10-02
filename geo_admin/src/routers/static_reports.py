from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from services.workspace_lifecycle import long_workspace_lifecycle_session
from pydantic import BaseModel, Field

from db import database

router = APIRouter(prefix="/static-reports", tags=["Static Reports"])


def _json_field(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _normalize_report_row(row: dict[str, Any]) -> dict[str, Any]:
    data = {key: _serialize_value(value) for key, value in dict(row).items()}
    data["data_completeness"] = _json_field(data.get("data_completeness"), {})
    data["warnings"] = _json_field(data.get("warnings"), [])
    if "snapshot_json" in data:
        data["snapshot_json"] = _json_field(data.get("snapshot_json"), None)
    return data


class StaticReportListRow(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    report_date: str
    timezone: str
    status: str
    snapshot_version: str
    data_window_start: str
    data_window_end: str
    window_days: int = 7
    rendering_mode: str
    data_completeness: dict[str, Any] = Field(default_factory=dict)
    warnings: list[Any] = Field(default_factory=list)
    error_message: Optional[str] = None
    materialized_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class StaticReportDetail(StaticReportListRow):
    snapshot_json: Optional[dict[str, Any]] = None


class StaticReportPagination(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class StaticReportListOut(BaseModel):
    data: list[StaticReportListRow]
    pagination: StaticReportPagination


class StaticReportAdminActionOut(BaseModel):
    ok: bool
    report_id: str
    client_id: str
    report_date: str
    action: str
    message: str


def _build_filters(
    client_id: Optional[UUID],
    status: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
) -> tuple[str, dict[str, Any]]:
    where_parts: list[str] = []
    params: dict[str, Any] = {}
    if client_id:
        where_parts.append("r.client_id = :client_id")
        params["client_id"] = client_id
    if status:
        where_parts.append("UPPER(r.status) = :status")
        params["status"] = status.upper()
    if date_from:
        where_parts.append("r.report_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where_parts.append("r.report_date <= :date_to")
        params["date_to"] = date_to
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    return where_sql, params


@router.get("", response_model=StaticReportListOut)
async def list_static_reports(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    client_id: Optional[UUID] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> StaticReportListOut:
    offset = (page - 1) * limit
    where_sql, params = _build_filters(client_id, status, date_from, date_to)

    total = await database.fetch_val(
        f"""
        SELECT COUNT(*)
        FROM geo_static_reports r
        LEFT JOIN geo_clients c ON c.id = r.client_id
        {where_sql}
        """,
        params,
    ) or 0

    rows = await database.fetch_all(
        f"""
        SELECT r.id, r.client_id, c.name AS client_name,
               r.report_date, r.timezone, r.status, r.snapshot_version,
               r.data_window_start, r.data_window_end, r.window_days, r.rendering_mode,
               r.data_completeness, r.warnings, r.error_message,
               r.materialized_at, r.created_at, r.updated_at
        FROM geo_static_reports r
        LEFT JOIN geo_clients c ON c.id = r.client_id
        {where_sql}
        ORDER BY r.report_date DESC, r.created_at DESC
        OFFSET :offset LIMIT :limit
        """,
        {**params, "offset": offset, "limit": limit},
    )

    return StaticReportListOut(
        data=[StaticReportListRow(**_normalize_report_row(dict(row))) for row in rows],
        pagination=StaticReportPagination(
            page=page,
            limit=limit,
            total=int(total),
            pages=(int(total) + limit - 1) // limit if int(total) > 0 else 1,
        ),
    )


@router.get("/{report_id}", response_model=StaticReportDetail)
async def get_static_report(report_id: UUID) -> StaticReportDetail:
    row = await database.fetch_one(
        """
        SELECT r.id, r.client_id, c.name AS client_name,
               r.report_date, r.timezone, r.status, r.snapshot_version,
               r.snapshot_json, r.data_window_start, r.data_window_end,
               r.window_days, r.rendering_mode, r.data_completeness, r.warnings,
               r.error_message, r.materialized_at, r.created_at, r.updated_at
        FROM geo_static_reports r
        LEFT JOIN geo_clients c ON c.id = r.client_id
        WHERE r.id = :report_id
        """,
        {"report_id": report_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return StaticReportDetail(**_normalize_report_row(dict(row)))


async def _delete_report(report_id: UUID, action: str) -> StaticReportAdminActionOut:
    existing = await database.fetch_one(
        "SELECT client_id::text AS client_id FROM geo_static_reports WHERE id = :report_id",
        {"report_id": report_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Report not found")
    async with long_workspace_lifecycle_session(database.pool(), str(existing["client_id"])):
        row = await database.fetch_one(
            """
            DELETE FROM geo_static_reports
            WHERE id = :report_id
            RETURNING id, client_id, report_date
            """,
            {"report_id": report_id},
        )
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    normalized = _normalize_report_row(dict(row))
    message = (
        "Report reset for regeneration. Generate it again from the SaaS report entry."
        if action == "regenerate"
        else "Report deleted."
    )
    return StaticReportAdminActionOut(
        ok=True,
        report_id=normalized["id"],
        client_id=normalized["client_id"],
        report_date=normalized["report_date"],
        action=action,
        message=message,
    )


@router.delete("/{report_id}", response_model=StaticReportAdminActionOut)
async def delete_static_report(report_id: UUID) -> StaticReportAdminActionOut:
    return await _delete_report(report_id, "delete")


@router.post("/{report_id}/regenerate", response_model=StaticReportAdminActionOut)
async def reset_static_report_for_regeneration(report_id: UUID) -> StaticReportAdminActionOut:
    return await _delete_report(report_id, "regenerate")
