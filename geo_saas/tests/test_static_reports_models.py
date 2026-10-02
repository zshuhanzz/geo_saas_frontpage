from datetime import date, datetime, timezone
from decimal import Decimal

from routers.static_reports.models import (
    MaterializeTodayOut,
    SHANGHAI_TZ,
    StaticReportDetail,
    StaticReportStatus,
    compute_report_dates,
    compute_report_dates_for_date,
    compute_previous_report_dates,
    serialize_record_value,
)


def test_compute_report_dates_uses_shanghai_day():
    now_utc = datetime(2026, 5, 26, 18, 30, tzinfo=timezone.utc)
    dates = compute_report_dates(now_utc)
    assert dates.report_date == date(2026, 5, 27)
    assert dates.window_start == date(2026, 5, 21)
    assert dates.window_end == date(2026, 5, 27)
    assert dates.window_days == 7
    assert dates.timezone == SHANGHAI_TZ


def test_compute_report_dates_for_explicit_date():
    dates = compute_report_dates_for_date(date(2026, 5, 27), window_days=14)
    assert dates.report_date == date(2026, 5, 27)
    assert dates.window_start == date(2026, 5, 14)
    assert dates.window_end == date(2026, 5, 27)
    assert dates.window_days == 14
    assert dates.timezone == SHANGHAI_TZ


def test_previous_window_is_equal_length_and_adjacent_for_supported_periods():
    for window_days in (1, 7, 30):
        current = compute_report_dates_for_date(date(2026, 5, 27), window_days=window_days)
        previous = compute_previous_report_dates(current)
        assert previous.window_end == current.window_start.fromordinal(current.window_start.toordinal() - 1)
        assert previous.window_days == window_days
        assert (previous.window_end - previous.window_start).days + 1 == window_days


def test_previous_window_crosses_month_boundary_without_gap():
    current = compute_report_dates_for_date(date(2026, 3, 3), window_days=7)
    previous = compute_previous_report_dates(current)
    assert current.window_start == date(2026, 2, 25)
    assert previous.window_start == date(2026, 2, 18)
    assert previous.window_end == date(2026, 2, 24)


def test_static_report_status_values_are_fixed():
    assert StaticReportStatus.COMPLETED == "COMPLETED"
    assert StaticReportStatus.NOT_READY == "NOT_READY"


def test_serialize_record_value_handles_dates_and_decimals():
    assert serialize_record_value(date(2026, 5, 27)) == "2026-05-27"
    assert serialize_record_value(Decimal("12.30")) == 12.3


def test_materialize_response_does_not_embed_report_payload():
    assert "report" not in MaterializeTodayOut.model_fields


def test_legacy_snapshot_deserializes_without_comparison_fields():
    report = StaticReportDetail.model_validate({
        "id": "report-1",
        "client_id": "client-1",
        "report_date": "2026-05-27",
        "status": "COMPLETED",
        "snapshot_version": "static-report-v2",
        "data_window_start": "2026-05-21",
        "data_window_end": "2026-05-27",
        "rendering_mode": "multi_day",
        "snapshot_json": {
            "version": "static-report-v2",
            "visibility": {"dashboard": {"summary": {"visibility_score": 50}}},
        },
    })
    assert report.snapshot_version == "static-report-v2"
    assert "visibility_score_change" not in report.snapshot_json["visibility"]["dashboard"]["summary"]
