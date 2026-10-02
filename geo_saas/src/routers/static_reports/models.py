from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

SHANGHAI_TZ = "Asia/Shanghai"
SNAPSHOT_VERSION = "static-report-v5"
DYNAMIC_REPORT_VERSION = "dynamic-report-v1"
ALLOWED_WINDOW_DAYS = (1, 7, 14, 30)
MAX_STATIC_REPORT_BLOB_ROWS = 25_000
MAX_STATIC_REPORT_LOGICAL_LIST_ROWS = 300_000
# Backward-compatible name used by snapshot construction for one logical list.
MAX_STATIC_REPORT_LIST_ROWS = MAX_STATIC_REPORT_LOGICAL_LIST_ROWS
MAX_STATIC_REPORT_TOTAL_ROWS = 300_000
MAX_STATIC_REPORT_BLOB_BYTES = 16 * 1024 * 1024
# Backward-compatible persisted-row byte ceiling.
MAX_STATIC_REPORT_LIST_BYTES = MAX_STATIC_REPORT_BLOB_BYTES
MAX_STATIC_REPORT_TOTAL_BYTES = 128 * 1024 * 1024
MAX_STATIC_REPORT_SNAPSHOT_BYTES = 32 * 1024 * 1024


class StaticReportPayloadTooLarge(RuntimeError):
    pass


class StaticReportStatus(str, Enum):
    PENDING = "PENDING"
    MATERIALIZING = "MATERIALIZING"
    COMPLETED = "COMPLETED"
    NOT_READY = "NOT_READY"
    FAILED = "FAILED"


class RenderingMode(str, Enum):
    SINGLE_DAY = "single_day"
    MULTI_DAY = "multi_day"


@dataclass(frozen=True)
class ReportDates:
    report_date: date
    window_start: date
    window_end: date
    window_days: int = 7
    timezone: str = SHANGHAI_TZ


def normalize_window_days(window_days: int | None = 7) -> int:
    value = int(window_days or 7)
    if value not in ALLOWED_WINDOW_DAYS:
        raise ValueError(f"window_days must be one of {ALLOWED_WINDOW_DAYS}")
    return value


def compute_report_dates(now: datetime | None = None, window_days: int = 7) -> ReportDates:
    window_days = normalize_window_days(window_days)
    current = now or datetime.now(tz=ZoneInfo(SHANGHAI_TZ))
    shanghai_now = current.astimezone(ZoneInfo(SHANGHAI_TZ))
    return compute_report_dates_for_date(shanghai_now.date(), window_days=window_days)


def compute_report_dates_for_date(report_date: date, window_days: int = 7) -> ReportDates:
    window_days = normalize_window_days(window_days)
    return ReportDates(
        report_date=report_date,
        window_start=date.fromordinal(report_date.toordinal() - window_days + 1),
        window_end=report_date,
        window_days=window_days,
    )


def compute_previous_report_dates(dates: ReportDates) -> ReportDates:
    """Return the adjacent, equal-length window used by dashboard comparisons."""
    previous_end = date.fromordinal(dates.window_start.toordinal() - 1)
    previous_start = date.fromordinal(previous_end.toordinal() - dates.window_days + 1)
    return ReportDates(
        report_date=previous_end,
        window_start=previous_start,
        window_end=previous_end,
        window_days=dates.window_days,
        timezone=dates.timezone,
    )


def serialize_record_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        return str(value)
    return value


def serialize_rows(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        out.append({key: serialize_record_value(value) for key, value in item.items()})
    return out


class StaticReportMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    client_id: str
    report_date: date
    timezone: str = SHANGHAI_TZ
    status: StaticReportStatus
    snapshot_version: str
    data_window_start: date
    data_window_end: date
    window_days: int = 7
    rendering_mode: RenderingMode
    data_completeness: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any] | str] = Field(default_factory=list)
    error_message: str | None = None
    materialized_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StaticReportDetail(StaticReportMeta):
    snapshot_json: dict[str, Any] | None = None


class StaticReportSummaryOut(StaticReportMeta):
    client: dict[str, Any] = Field(default_factory=dict)
    report: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    frozen_lists: dict[str, Any] = Field(default_factory=dict)


class StaticReportFiltersOut(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)


class StaticReportSectionOut(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class StaticReportFrozenListOut(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    sort_by: str
    sort_order: str


class StaticReportListOut(BaseModel):
    data: list[StaticReportMeta] = Field(default_factory=list)


class TodayReportStatusOut(BaseModel):
    status: StaticReportStatus
    report_id: str | None = None
    report_date: date
    window_days: int = 7
    ready: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_completeness: dict[str, Any] = Field(default_factory=dict)


class MaterializeTodayRequest(BaseModel):
    client_id: str
    window_days: int = 7


class MaterializeDateRequest(BaseModel):
    client_id: str
    report_date: date
    window_days: int = 7


class MaterializeTodayOut(BaseModel):
    status: StaticReportStatus
    report_id: str | None = None
    ready: bool = False
    reasons: list[str] = Field(default_factory=list)
