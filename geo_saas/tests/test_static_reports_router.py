from fastapi import FastAPI
import asyncio
from contextlib import asynccontextmanager
from datetime import date
import pytest

from routers.static_reports.models import DYNAMIC_REPORT_VERSION, StaticReportStatus, compute_report_dates_for_date
from routers.static_reports.repository import MaterializationLeaseLost, StaticReportRepository
from routers.static_reports.router import (
    _load_authorized_report_metadata,
    _materialize_for_dates,
    _status_for_dates,
    export_static_report_html,
    router,
)


@pytest.fixture(autouse=True)
def _stub_global_report_capacity(monkeypatch):
    @asynccontextmanager
    async def available(_pool):
        yield

    monkeypatch.setattr(
        "routers.static_reports.router.static_report_global_capacity",
        available,
        raising=False,
    )


class _AuthorizationConnection:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self.row


class _AuthorizationAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _AuthorizationPool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _AuthorizationAcquire(self.connection)


def test_authorized_report_summary_filters_report_and_access_in_one_sql_query():
    connection = _AuthorizationConnection(row=None)
    repository = StaticReportRepository(_AuthorizationPool(connection))

    result = asyncio.run(repository.get_authorized_summary_by_id("report-1", "user-1"))

    assert result is None
    assert len(connection.calls) == 1
    sql, args = connection.calls[0]
    normalized = " ".join(sql.split())
    assert "FROM geo_static_reports sr" in normalized
    assert "sr.id = $1::uuid" in normalized
    assert "FROM geo_client_user_access" in normalized
    assert "FROM geo_admin_user_access" in normalized
    assert "cua.user_id = $2::uuid" in normalized
    assert "aua.user_id = $2::uuid" in normalized
    assert "cua.is_active = true" in normalized
    assert "aua.role = 'super_admin'" in normalized
    assert "aua.support_all_clients = true" in normalized
    assert "aua.is_active = true" in normalized
    assert "snapshot_json -> 'filters'" in normalized
    assert "AS filters" in normalized
    assert args == ("report-1", "user-1")


def test_report_row_decodes_dynamic_filter_json_text():
    from routers.static_reports.repository import row_to_dict

    decoded = row_to_dict({"filters": '{"topics":[{"id":"topic-1","name":"AI"}]}'})
    assert decoded["filters"] == {"topics": [{"id": "topic-1", "name": "AI"}]}


@pytest.mark.parametrize(
    ("method_name", "method_args"),
    [
        ("get_authorized_by_id", ()),
        ("get_authorized_snapshot_part_by_id", ("citations",)),
        ("get_authorized_snapshot_view_by_id", ("citations_share",)),
    ],
)
def test_authorized_full_part_and_view_queries_filter_access_before_returning_data(method_name, method_args):
    connection = _AuthorizationConnection(row=None)
    repository = StaticReportRepository(_AuthorizationPool(connection))

    result = asyncio.run(
        getattr(repository, method_name)("report-1", *method_args, "user-1")
    )

    assert result is None
    assert len(connection.calls) == 1
    sql, args = connection.calls[0]
    normalized = " ".join(sql.split())
    assert "FROM geo_static_reports sr" in normalized
    assert "sr.id = $1::uuid" in normalized
    assert "FROM geo_client_user_access" in normalized
    assert "FROM geo_admin_user_access" in normalized
    assert args == ("report-1", "user-1")


def test_unauthorized_and_missing_reports_share_404_without_preloading_report():
    calls = []

    class FakeRepository:
        async def get_authorized_summary_by_id(self, report_id, user_id):
            calls.append((report_id, user_id))
            return None

        async def get_summary_by_id(self, *_args):
            raise AssertionError("HTTP path must not load report before authorization")

    user = type("User", (), {"id": "user-1"})()
    for report_id in ("unauthorized-report", "missing-report"):
        try:
            asyncio.run(_load_authorized_report_metadata(FakeRepository(), report_id, user))
        except Exception as exc:
            assert exc.status_code == 404
            assert exc.detail == "Report not found"
        else:
            raise AssertionError("unauthorized and missing reports must return 404")

    assert calls == [
        ("unauthorized-report", "user-1"),
        ("missing-report", "user-1"),
    ]


def test_html_export_uses_authorized_full_report_query_without_preloading_snapshot(monkeypatch):
    calls = []

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def get_authorized_by_id(self, report_id, user_id):
            calls.append((report_id, user_id))
            return None

        async def get_by_id(self, *_args):
            raise AssertionError("HTTP export must not load snapshot before authorization")

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    user = type("User", (), {"id": "user-1"})()

    try:
        asyncio.run(export_static_report_html("report-1", user=user, pool=object()))
    except Exception as exc:
        assert exc.status_code == 404
        assert exc.detail == "Report not found"
    else:
        raise AssertionError("unauthorized report export must return 404")

    assert calls == [("report-1", "user-1")]


def test_static_reports_router_mounts():
    app = FastAPI()
    app.include_router(router)
    # FastAPI 0.124+ can retain an internal lazy router node; OpenAPI is the
    # stable public contract and resolves every included endpoint.
    paths = set(app.openapi()["paths"])
    assert "/api/static-reports" in paths
    assert "/api/static-reports/date-status" in paths
    assert "/api/static-reports/materialize-date" in paths
    assert "/api/static-reports/today" in paths
    assert "/api/static-reports/today/materialize" in paths
    assert "/api/static-reports/{report_id}" in paths
    assert "/api/static-reports/{report_id}/summary" in paths
    assert "/api/static-reports/{report_id}/filters" in paths
    assert "/api/static-reports/{report_id}/visibility" in paths
    assert "/api/static-reports/{report_id}/citations" in paths
    assert "/api/static-reports/{report_id}/sentiment" in paths
    assert "/api/static-reports/{report_id}/prompt-topic" in paths
    assert "/api/static-reports/{report_id}/lists/{list_type}" in paths
    assert "/api/static-reports/{report_id}/export.html" in paths


def test_missing_dynamic_report_is_create_ready_without_readiness_query(monkeypatch):
    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def get_for_date(self, *_args):
            return None

    async def forbidden_readiness(*_args):
        raise AssertionError("dynamic report status must not inspect data readiness")

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", forbidden_readiness)
    dates = compute_report_dates_for_date(date(2026, 7, 14), 7)

    result = asyncio.run(_status_for_dates(object(), "client-1", dates))

    assert result == {
        "status": StaticReportStatus.PENDING,
        "report_id": None,
        "report_date": dates.report_date,
        "window_days": 7,
        "ready": True,
        "reasons": [],
        "data_completeness": {"mode": "dynamic_live", "is_frozen": False},
    }


def test_dynamic_materialization_persists_live_descriptor_marker(monkeypatch):
    completed = {}

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            return {
                "report": {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value},
                "acquired_materialization": True,
                "materialization_token": "token-1",
            }

        async def complete_dynamic(self, _report_id, token, dates, completeness, warnings):
            assert token == "token-1"
            completed["dates"] = dates
            completed["completeness"] = completeness
            completed["warnings"] = warnings
            return {"id": "report-1"}

        async def fail(self, *_args):
            raise AssertionError("materialization should not fail")

    async def forbidden_readiness(*_args):
        raise AssertionError("dynamic report creation must not inspect data readiness")

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", forbidden_readiness)

    result = asyncio.run(_materialize_for_dates(
        object(),
        "client-1",
        "user-1",
        compute_report_dates_for_date(date(2026, 5, 27), 7),
    ))

    assert result["status"] == StaticReportStatus.COMPLETED
    assert completed["completeness"] == {"mode": "dynamic_live", "is_frozen": False}
    assert completed["dates"].window_days == 7
    assert completed["warnings"] == []


def test_dynamic_materialization_skips_snapshot_capacity_and_frozen_lists(monkeypatch):
    completed = {}

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            return {
                "report": {
                    "id": "report-dynamic",
                    "status": StaticReportStatus.MATERIALIZING.value,
                    "snapshot_version": DYNAMIC_REPORT_VERSION,
                },
                "acquired_materialization": True,
                "materialization_token": "token-dynamic",
            }

        async def complete_dynamic(
            self,
            report_id,
            token,
            dates,
            data_completeness,
            warnings,
        ):
            completed.update({
                "report_id": report_id,
                "token": token,
                "dates": dates,
                "data_completeness": data_completeness,
                "warnings": warnings,
            })
            return {"id": report_id, "status": StaticReportStatus.COMPLETED.value}

        async def complete(self, *_args):
            raise AssertionError("dynamic reports must not use frozen snapshot completion")

        async def fail(self, *_args):
            raise AssertionError("dynamic materialization should not fail")

    async def forbidden_readiness(*_args):
        raise AssertionError("dynamic materialization must not inspect data readiness")

    async def forbidden_async(*_args, **_kwargs):
        raise AssertionError("dynamic materialization must not enter static generation capacity or build_snapshot")

    def forbidden_sync(*_args, **_kwargs):
        raise AssertionError("dynamic materialization must not build frozen list blobs")

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", forbidden_readiness, raising=False)
    monkeypatch.setattr("routers.static_reports.router.build_snapshot", forbidden_async, raising=False)
    monkeypatch.setattr("routers.static_reports.router.build_static_report_list_blobs", forbidden_sync, raising=False)

    dates = compute_report_dates_for_date(date(2026, 7, 14), 7)
    result = asyncio.run(_materialize_for_dates(object(), "client-1", "user-1", dates))

    assert result == {
        "status": StaticReportStatus.COMPLETED,
        "report_id": "report-dynamic",
        "ready": True,
        "reasons": [],
    }
    assert completed == {
        "report_id": "report-dynamic",
        "token": "token-dynamic",
        "dates": dates,
        "data_completeness": {"mode": "dynamic_live", "is_frozen": False},
        "warnings": [],
    }


def test_concurrent_stale_lease_retries_have_one_recovery_owner_and_one_completion(monkeypatch):
    lock = asyncio.Lock()
    state = {"lease_stale": True, "completion_calls": 0}

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            async with lock:
                acquired = state["lease_stale"]
                state["lease_stale"] = False
                return {
                    "report": {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value},
                    "acquired_materialization": acquired,
                    "materialization_token": "token-owner" if acquired else None,
                }

        async def complete_dynamic(self, *_args):
            state["completion_calls"] += 1
            await asyncio.sleep(0)
            return {"id": "report-1"}

        async def fail(self, *_args):
            raise AssertionError("owner build should not fail")

    class Ready:
        ready = True
        data_completeness = {"raw_results": 1}

    async def fake_readiness(*_args):
        return Ready()

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", fake_readiness)
    dates = compute_report_dates_for_date(date(2026, 5, 27), 7)

    async def run_both():
        return await asyncio.gather(
            _materialize_for_dates(object(), "client-1", "user-1", dates),
            _materialize_for_dates(object(), "client-1", "user-2", dates),
        )

    results = asyncio.run(run_both())
    assert state["completion_calls"] == 1
    assert sorted(result["status"] for result in results) == [
        StaticReportStatus.COMPLETED,
        StaticReportStatus.MATERIALIZING,
    ]


def test_fresh_materializing_lease_returns_in_progress_without_build(monkeypatch):
    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            return {
                "report": {"id": "report-fresh", "status": StaticReportStatus.MATERIALIZING.value},
                "acquired_materialization": False,
            }

    async def forbidden(*_args):
        raise AssertionError("fresh non-owner must not run readiness or build")

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", forbidden)
    monkeypatch.setattr("routers.static_reports.router.build_snapshot", forbidden)
    result = asyncio.run(_materialize_for_dates(
        object(), "client-1", "user-1", compute_report_dates_for_date(date(2026, 5, 27), 7),
    ))
    assert result == {
        "status": StaticReportStatus.MATERIALIZING.value,
        "report_id": "report-fresh",
        "ready": False,
        "reasons": ["materialization_in_progress"],
    }


def test_cancellation_during_dynamic_completion_releases_the_owned_claim(monkeypatch):
    releases = []

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            return {
                "report": {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value},
                "acquired_materialization": True,
                "materialization_token": "token-1",
            }

        async def release_materialization(self, report_id, token):
            await asyncio.sleep(0)
            releases.append((report_id, token))
            return {"id": report_id, "status": StaticReportStatus.PENDING.value}

        async def complete_dynamic(self, *_args):
            raise asyncio.CancelledError

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_materialize_for_dates(
            object(), "client-1", "user-1", compute_report_dates_for_date(date(2026, 5, 27), 7),
        ))

    assert releases == [("report-1", "token-1")]


def test_dynamic_completion_does_not_consult_failing_readiness(monkeypatch):
    completions = []

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            return {
                "report": {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value},
                "acquired_materialization": True,
                "materialization_token": "token-1",
            }

        async def complete_dynamic(self, report_id, token, *_args):
            completions.append((report_id, token))
            return {"id": report_id, "status": StaticReportStatus.COMPLETED.value}

    async def failing_readiness(*_args):
        raise RuntimeError("readiness unavailable")

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", failing_readiness, raising=False)

    result = asyncio.run(_materialize_for_dates(
        object(), "client-1", "user-1", compute_report_dates_for_date(date(2026, 5, 27), 7),
    ))

    assert result["status"] == StaticReportStatus.COMPLETED
    assert completions == [("report-1", "token-1")]


def test_dynamic_completion_bypasses_static_capacity_build_and_blob_construction(monkeypatch):
    events = []

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            return {
                "report": {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value},
                "acquired_materialization": True,
                "materialization_token": "token-1",
            }

        async def complete_dynamic(self, *_args):
            events.append("complete_dynamic")
            return {"id": "report-1", "status": StaticReportStatus.COMPLETED.value}

    class Ready:
        ready = True
        data_completeness = {}

    async def fake_readiness(*_args):
        return Ready()

    async def fake_build(*_args):
        raise AssertionError("dynamic materialization must not build a static snapshot")

    def fake_blobs(_snapshot):
        raise AssertionError("dynamic materialization must not build frozen list blobs")

    @asynccontextmanager
    async def tracked_capacity(_pool):
        raise AssertionError("dynamic materialization must not acquire static capacity")
        yield

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", fake_readiness)
    monkeypatch.setattr("routers.static_reports.router.build_snapshot", fake_build)
    monkeypatch.setattr("routers.static_reports.router.build_static_report_list_blobs", fake_blobs)
    monkeypatch.setattr("routers.static_reports.router.static_report_global_capacity", tracked_capacity)

    result = asyncio.run(_materialize_for_dates(
        object(), "client-1", "user-1", compute_report_dates_for_date(date(2026, 5, 27), 7),
    ))

    assert result["status"] == StaticReportStatus.COMPLETED
    assert events == ["complete_dynamic"]


def test_materialization_persists_only_a_stable_public_failure_message(monkeypatch):
    persisted_messages = []

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            return {
                "report": {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value},
                "acquired_materialization": True,
                "materialization_token": "token-1",
            }

        async def fail(self, _report_id, _token, message):
            persisted_messages.append(message)
            return {"id": "report-1", "status": StaticReportStatus.FAILED.value}

    class Ready:
        ready = True
        data_completeness = {}

    async def fake_readiness(*_args):
        return Ready()

    async def failing_completion(*_args):
        raise RuntimeError("relation secret_customer_table does not exist")

    FakeRepository.complete_dynamic = failing_completion

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", fake_readiness)

    result = asyncio.run(_materialize_for_dates(
        object(), "client-1", "user-1", compute_report_dates_for_date(date(2026, 5, 27), 7),
    ))

    assert result["status"] == StaticReportStatus.FAILED
    assert persisted_messages == ["snapshot_materialization_failed"]


def test_router_old_owner_cannot_fail_after_completion_fence_is_lost(monkeypatch):
    calls = []

    class FakeRepository:
        def __init__(self, _pool):
            pass

        async def claim_materialization(self, *_args):
            return {
                "report": {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value},
                "acquired_materialization": True,
                "materialization_token": "old-token",
            }

        async def complete_dynamic(self, _report_id, token, *_args):
            calls.append(("complete", token))
            raise MaterializationLeaseLost("taken over")

        async def fail(self, *_args):
            calls.append(("fail",))
            raise AssertionError("lease loss must not be converted into an old-owner failure")

        async def get_summary_by_id(self, _report_id):
            return {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value}

    class Ready:
        ready = True
        data_completeness = {"raw_results": 1}

    async def fake_readiness(*_args):
        return Ready()

    monkeypatch.setattr("routers.static_reports.router.StaticReportRepository", FakeRepository)
    monkeypatch.setattr("routers.static_reports.router.check_report_readiness", fake_readiness)
    result = asyncio.run(_materialize_for_dates(
        object(), "client-1", "user-1", compute_report_dates_for_date(date(2026, 5, 27), 7),
    ))

    assert calls == [("complete", "old-token")]
    assert result == {
        "status": StaticReportStatus.MATERIALIZING.value,
        "report_id": "report-1",
        "ready": False,
        "reasons": ["materialization_in_progress"],
    }
