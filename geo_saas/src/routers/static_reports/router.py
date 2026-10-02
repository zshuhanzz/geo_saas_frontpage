from __future__ import annotations

import asyncio
import logging
import html
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from dependencies.auth import AuthenticatedUser, require_client_access_if_present
from pool import get_pool

from .models import (
    SNAPSHOT_VERSION,
    MaterializeTodayOut,
    MaterializeTodayRequest,
    MaterializeDateRequest,
    StaticReportDetail,
    StaticReportFiltersOut,
    StaticReportFrozenListOut,
    StaticReportListOut,
    StaticReportSectionOut,
    StaticReportStatus,
    StaticReportSummaryOut,
    TodayReportStatusOut,
    compute_report_dates,
    compute_report_dates_for_date,
    normalize_window_days,
)
from .readiness import check_report_readiness
from .repository import MaterializationLeaseLost, StaticReportRepository
from .snapshot_builder import (
    build_snapshot,
    build_static_report_list_blobs,
    static_report_global_capacity,
)
from .sorting import StaticReportListUnavailable

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/static-reports", tags=["Static Reports"])
_DYNAMIC_REPORT_DATA_COMPLETENESS = {
    "mode": "dynamic_live",
    "is_frozen": False,
}

# Future scheduled Reports extension (intentionally not implemented here):
# - Keep the current dynamic-report-v1 descriptor semantics unchanged.
# - Let Admin users configure cron/timezone/window from the SaaS Reports UI.
# - Have Cloud Scheduler call one exact OIDC-protected system endpoint.
# - The system principal bypasses end-user feature/role checks; the endpoint
#   resolves the schedule's Workspace and idempotently materializes the date
#   descriptor without invoking Collector, Analyzer, or Agent pipelines.
# - Do not add a schedule table until the corresponding UI is implemented.


def _authorized_client_id(request: Request, client_id: str) -> None:
    authorized = getattr(request.state, "authorized_client_id", None)
    if authorized and str(authorized) != str(client_id):
        raise HTTPException(status_code=403, detail="No access to this client")


async def _status_for_dates(pool, client_id: str, dates) -> dict:
    repo = StaticReportRepository(pool)
    existing = await repo.get_for_date(client_id, dates.report_date, dates.window_days)
    if existing and existing["status"] == StaticReportStatus.COMPLETED.value:
        return {
            "status": StaticReportStatus.COMPLETED,
            "report_id": existing["id"],
            "report_date": dates.report_date,
            "window_days": dates.window_days,
            "ready": True,
            "reasons": [],
            "data_completeness": existing.get("data_completeness") or {},
        }
    if existing and existing["status"] == StaticReportStatus.MATERIALIZING.value:
        return {
            "status": StaticReportStatus.MATERIALIZING,
            "report_id": existing["id"],
            "report_date": dates.report_date,
            "window_days": dates.window_days,
            "ready": False,
            "reasons": ["materialization_in_progress"],
            "data_completeness": existing.get("data_completeness") or {},
        }
    return {
        "status": StaticReportStatus.PENDING,
        "report_id": existing["id"] if existing else None,
        "report_date": dates.report_date,
        "window_days": dates.window_days,
        "ready": True,
        "reasons": [],
        "data_completeness": dict(_DYNAMIC_REPORT_DATA_COMPLETENESS),
    }


async def _materialize_for_dates(pool, client_id: str, user_id: str, dates) -> dict:
    repo = StaticReportRepository(pool)
    claim = await repo.claim_materialization(client_id, dates, user_id)
    row = claim["report"]
    if not claim["acquired_materialization"] and row["status"] == StaticReportStatus.COMPLETED.value:
        return {
            "status": StaticReportStatus.COMPLETED,
            "report_id": row["id"],
            "ready": True,
            "reasons": [],
        }
    if not claim["acquired_materialization"]:
        return {
            "status": row["status"],
            "report_id": row["id"],
            "ready": False,
            "reasons": ["materialization_in_progress"] if row["status"] == StaticReportStatus.MATERIALIZING.value else [],
        }
    materialization_token = claim["materialization_token"]

    async def lease_lost_response() -> dict:
        current = await repo.get_summary_by_id(row["id"])
        current_status = (current or {}).get("status", StaticReportStatus.MATERIALIZING.value)
        return {
            "status": current_status,
            "report_id": row["id"],
            "ready": current_status == StaticReportStatus.COMPLETED.value,
            "reasons": [] if current_status == StaticReportStatus.COMPLETED.value else ["materialization_in_progress"],
        }

    ownership_finished = False

    async def release_owned_claim() -> None:
        nonlocal ownership_finished
        if ownership_finished:
            return
        release_task = asyncio.create_task(
            repo.release_materialization(row["id"], materialization_token),
        )
        try:
            await asyncio.shield(release_task)
            ownership_finished = True
        except asyncio.CancelledError:
            try:
                await release_task
                ownership_finished = True
            except MaterializationLeaseLost:
                ownership_finished = True
            except Exception:
                logger.exception("[STATIC_REPORT] failed to release materialization lease after cancellation")
        except MaterializationLeaseLost:
            ownership_finished = True
        except Exception:
            logger.exception("[STATIC_REPORT] failed to release materialization lease")

    async def run_owned_materialization() -> dict:
        nonlocal ownership_finished
        try:
            report = await repo.complete_dynamic(
                row["id"],
                materialization_token,
                dates,
                dict(_DYNAMIC_REPORT_DATA_COMPLETENESS),
                [],
            )
            ownership_finished = True
            return {
                "status": StaticReportStatus.COMPLETED,
                "report_id": report["id"],
                "ready": True,
                "reasons": [],
            }
        except MaterializationLeaseLost:
            ownership_finished = True
            return await lease_lost_response()
        except Exception:
            logger.exception("[STATIC_REPORT] materialization failed")
            try:
                report = await repo.fail(
                    row["id"], materialization_token, "snapshot_materialization_failed",
                )
            except MaterializationLeaseLost:
                ownership_finished = True
                return await lease_lost_response()
            ownership_finished = True
            return {
                "status": StaticReportStatus.FAILED,
                "report_id": report["id"],
                "ready": False,
                "reasons": ["snapshot_materialization_failed"],
            }

    try:
        return await run_owned_materialization()
    except asyncio.CancelledError:
        await release_owned_claim()
        raise
    except BaseException:
        await release_owned_claim()
        raise


async def _load_authorized_report_metadata(
    repo: StaticReportRepository,
    report_id: str,
    user: AuthenticatedUser,
) -> dict:
    report = await repo.get_authorized_summary_by_id(report_id, user.id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


async def _load_authorized_snapshot_part(
    repo: StaticReportRepository,
    report_id: str,
    part: str,
    user: AuthenticatedUser,
) -> dict:
    row = await repo.get_authorized_snapshot_part_by_id(report_id, part, user.id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return row


async def _load_authorized_snapshot_view(
    repo: StaticReportRepository,
    report_id: str,
    view: str,
    user: AuthenticatedUser,
) -> dict:
    row = await repo.get_authorized_snapshot_view_by_id(report_id, view, user.id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return row


@router.get("", response_model=StaticReportListOut)
async def list_static_reports(
    client_id: str,
    request: Request,
    _user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    _authorized_client_id(request, client_id)
    repo = StaticReportRepository(pool)
    return {"data": await repo.list_for_client(client_id)}


@router.get("/today", response_model=TodayReportStatusOut)
async def today_static_report_status(
    client_id: str,
    request: Request,
    window_days: int = Query(7),
    _user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    _authorized_client_id(request, client_id)
    return await _status_for_dates(pool, client_id, compute_report_dates(window_days=normalize_window_days(window_days)))


@router.get("/date-status", response_model=TodayReportStatusOut)
async def date_static_report_status(
    client_id: str,
    report_date: date,
    request: Request,
    window_days: int = Query(7),
    _user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    _authorized_client_id(request, client_id)
    return await _status_for_dates(pool, client_id, compute_report_dates_for_date(report_date, window_days=normalize_window_days(window_days)))


@router.post("/today/materialize", response_model=MaterializeTodayOut)
async def materialize_today_static_report(
    payload: MaterializeTodayRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    _authorized_client_id(request, payload.client_id)
    return await _materialize_for_dates(
        pool,
        payload.client_id,
        user.id,
        compute_report_dates(window_days=normalize_window_days(payload.window_days)),
    )


@router.post("/materialize-date", response_model=MaterializeTodayOut)
async def materialize_date_static_report(
    payload: MaterializeDateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    _authorized_client_id(request, payload.client_id)
    return await _materialize_for_dates(
        pool,
        payload.client_id,
        user.id,
        compute_report_dates_for_date(payload.report_date, window_days=normalize_window_days(payload.window_days)),
    )


@router.get("/{report_id}", response_model=StaticReportDetail)
async def get_static_report(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    report = await _load_authorized_report_metadata(repo, report_id, user)
    report["snapshot_json"] = None
    return report


@router.get("/{report_id}/summary", response_model=StaticReportSummaryOut)
async def get_static_report_summary(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    return await _load_authorized_report_metadata(repo, report_id, user)


@router.get("/{report_id}/filters", response_model=StaticReportFiltersOut)
async def get_static_report_filters(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_part(repo, report_id, "filters", user)
    return {"filters": row.get("data") or {}}


@router.get("/{report_id}/visibility", response_model=StaticReportSectionOut)
async def get_static_report_visibility(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_part(repo, report_id, "visibility", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/visibility/score", response_model=StaticReportSectionOut)
async def get_static_report_visibility_score(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_view(repo, report_id, "visibility_score", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/visibility/brand-ranking", response_model=StaticReportSectionOut)
async def get_static_report_visibility_brand_ranking(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_view(repo, report_id, "visibility_brand_ranking", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/visibility/sov", response_model=StaticReportSectionOut)
async def get_static_report_visibility_sov(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_view(repo, report_id, "visibility_sov", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/visibility/position", response_model=StaticReportSectionOut)
async def get_static_report_visibility_position(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_view(repo, report_id, "visibility_position", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/citations", response_model=StaticReportSectionOut)
async def get_static_report_citations(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_part(repo, report_id, "citations", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/citations/share", response_model=StaticReportSectionOut)
async def get_static_report_citations_share(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_view(repo, report_id, "citations_share", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/citations/ranking", response_model=StaticReportSectionOut)
async def get_static_report_citations_ranking(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_view(repo, report_id, "citations_ranking", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/citations/categories", response_model=StaticReportSectionOut)
async def get_static_report_citations_categories(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_view(repo, report_id, "citations_categories", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/sentiment", response_model=StaticReportSectionOut)
async def get_static_report_sentiment(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_part(repo, report_id, "sentiment", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/prompt-topic", response_model=StaticReportSectionOut)
async def get_static_report_prompt_topic(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    row = await _load_authorized_snapshot_view(repo, report_id, "prompt_topic", user)
    return {"data": row.get("data") or {}}


@router.get("/{report_id}/lists/{list_type}", response_model=StaticReportFrozenListOut)
async def get_static_report_frozen_list(
    report_id: str,
    list_type: str,
    sort_by: str | None = Query(default=None),
    sort_order: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    parent_key: str | None = Query(default=None, max_length=200),
    prompt_key: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=200),
    sentiment: str | None = Query(default=None, max_length=100),
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
):
    repo = StaticReportRepository(pool)
    report = await _load_authorized_report_metadata(repo, report_id, user)
    if report.get("snapshot_version") != SNAPSHOT_VERSION:
        raise HTTPException(
            status_code=409,
            detail="Frozen list storage is unavailable for this report version",
        )
    try:
        return await repo.list_frozen_rows(
            report_id,
            str(report["client_id"]),
            list_type,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            parent_key=parent_key,
            prompt_key=prompt_key,
            search=search,
            sentiment=sentiment,
        )
    except StaticReportListUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{report_id}/export.html")
async def export_static_report_html(
    report_id: str,
    user: AuthenticatedUser = Depends(require_client_access_if_present),
    pool=Depends(get_pool),
) -> Response:
    repo = StaticReportRepository(pool)
    report = await repo.get_authorized_by_id(report_id, user.id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    snapshot = report.get("snapshot_json") or {}
    title = snapshot.get("client", {}).get("name") or "GEO Report"
    payload = html.escape(json.dumps(snapshot, ensure_ascii=False, default=str))
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)} GEO Report</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #080a0c; color: #f8fafc; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 32px 24px 56px; }}
    .muted {{ color: #94a3b8; }}
    .card {{ border: 1px solid rgba(148, 163, 184, .22); border-radius: 8px; padding: 18px; background: rgba(15, 23, 42, .58); margin-top: 16px; }}
    h1 {{ font-size: 32px; margin: 0 0 8px; }}
    h2 {{ font-size: 18px; margin: 0 0 12px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.55; }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(title)} GEO Report</h1>
    <div class="muted">Report date: {html.escape(str(report.get("report_date") or ""))} · Window: {html.escape(str(report.get("data_window_start") or ""))} - {html.escape(str(report.get("data_window_end") or ""))}</div>
    <section class="card">
      <h2>Embedded Snapshot</h2>
      <p class="muted">This HTML file contains the static report snapshot. Open the web report for the full interactive rendering.</p>
      <pre id="snapshot">{payload}</pre>
    </section>
  </main>
</body>
</html>"""
    filename = f"geo-report-{report_id}.html"
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
