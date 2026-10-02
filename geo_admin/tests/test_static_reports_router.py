from fastapi import FastAPI

from routers.static_reports import StaticReportListRow, _normalize_report_row, router


def test_static_reports_router_mounts():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    paths = {route.path for route in app.routes}

    assert "/api/static-reports" in paths
    assert "/api/static-reports/{report_id}" in paths
    assert "/api/static-reports/{report_id}/regenerate" in paths


def test_static_report_row_normalizes_json_fields_and_dates():
    row = _normalize_report_row(
        {
            "id": "report-1",
            "client_id": "client-1",
            "client_name": "Roborock",
            "report_date": "2026-05-27",
            "timezone": "Asia/Shanghai",
            "status": "COMPLETED",
            "snapshot_version": "static-report-v1",
            "data_window_start": "2026-05-21",
            "data_window_end": "2026-05-27",
            "rendering_mode": "single_day",
            "data_completeness": '{"raw_results": 8}',
            "warnings": '["single_day_report"]',
            "error_message": None,
            "materialized_at": None,
            "created_at": None,
            "updated_at": None,
        }
    )

    parsed = StaticReportListRow(**row)
    assert parsed.client_name == "Roborock"
    assert parsed.data_completeness["raw_results"] == 8
    assert parsed.warnings == ["single_day_report"]


def test_static_report_admin_action_response_shape():
    from routers.static_reports import StaticReportAdminActionOut

    response = StaticReportAdminActionOut(
        ok=True,
        report_id="report-1",
        client_id="client-1",
        report_date="2026-05-27",
        action="delete",
        message="Report deleted.",
    )

    assert response.ok is True
    assert response.action == "delete"
