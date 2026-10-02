"""HTTP endpoints for the tenant-scoped Prompt CSV import workflow."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from geo_common.auth import AuthenticatedUser
from pydantic import BaseModel

from dependencies.auth import require_current_user
from pool import get_pool
from .prompt_import_service import (
    ALLOWED_VALUES_HEADERS,
    ImportLimits,
    ImportValidationError,
    PreviewStaleError,
    PromptImportService,
)


router = APIRouter()


class UndoInput(BaseModel):
    confirmation: bool


async def _read_bounded_upload(file: UploadFile, *, max_bytes: int) -> bytes:
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ImportValidationError(
            f"CSV has more than {max_bytes} bytes; allowed maximum is {max_bytes} bytes",
            code="file_too_large",
            actual=len(raw),
            allowed=max_bytes,
        )
    return raw


def _validation_http_error(exc: ImportValidationError) -> HTTPException:
    detail = {"code": exc.code, "message": str(exc)}
    if exc.actual is not None:
        detail["actual"] = exc.actual
    if exc.allowed is not None:
        detail["allowed"] = exc.allowed
    if exc.details:
        detail["details"] = exc.details
    if exc.code in {"workspace_not_found", "batch_not_found"}:
        status = 404
    elif exc.code == "safe_cleanup_required":
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail=detail)


@router.get("/import/template.csv")
async def download_template(client_id: UUID, pool=Depends(get_pool)) -> Response:
    try:
        content = await PromptImportService(pool).template_csv(str(client_id))
    except ImportValidationError as exc:
        raise _validation_http_error(exc) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="prompt-import-template.csv"', "Cache-Control": "no-store"},
    )


@router.get("/import/allowed-values")
async def get_allowed_values(
    client_id: UUID,
    response: Response,
    locale: Literal["zh-CN", "en-US"] = Query("zh-CN"),
    pool=Depends(get_pool),
) -> dict:
    try:
        result = await PromptImportService(pool).allowed_values(str(client_id), locale=locale)
    except ImportValidationError as exc:
        raise _validation_http_error(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/import/allowed-values.csv")
async def download_allowed_values(
    client_id: UUID,
    locale: Literal["zh-CN", "en-US"] = Query("zh-CN"),
    pool=Depends(get_pool),
) -> Response:
    try:
        allowed = await PromptImportService(pool).allowed_values(str(client_id), locale=locale)
    except ImportValidationError as exc:
        raise _validation_http_error(exc) from exc
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(ALLOWED_VALUES_HEADERS)
    for row in allowed["rows"]:
        writer.writerow([row["type"], row["value"], row["label"], row["parent_type"], row["parent_value"], row["notes"]])
    return Response(
        content=("\ufeff" + output.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="prompt-import-allowed-values.csv"', "Cache-Control": "no-store"},
    )


@router.post("/import/preview")
async def preview_import(
    client_id: UUID,
    file: UploadFile = File(...),
    pool=Depends(get_pool),
) -> dict:
    try:
        raw = await _read_bounded_upload(file, max_bytes=ImportLimits().max_bytes)
        return (await PromptImportService(pool).preview(str(client_id), raw)).as_dict()
    except ImportValidationError as exc:
        raise _validation_http_error(exc) from exc


@router.post("/import/commit")
async def commit_import(
    client_id: UUID,
    expected_manifest_sha256: str = Form(...),
    expected_preview_state_sha256: str = Form(...),
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> dict:
    if re.fullmatch(r"[0-9a-fA-F]{64}", expected_manifest_sha256) is None:
        raise HTTPException(status_code=422, detail={"code": "manifest_required", "message": "expected_manifest_sha256 is required"})
    if re.fullmatch(r"[0-9a-fA-F]{64}", expected_preview_state_sha256) is None:
        raise HTTPException(status_code=422, detail={"code": "preview_state_required", "message": "expected_preview_state_sha256 is required"})
    filename = Path(file.filename or "prompt-import.csv").name.strip() or "prompt-import.csv"
    try:
        raw = await _read_bounded_upload(file, max_bytes=ImportLimits().max_bytes)
        return await PromptImportService(pool).commit(
            str(client_id), user.id, filename, raw,
            expected_manifest_sha256, expected_preview_state_sha256,
        )
    except PreviewStaleError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "preview_stale", "message": str(exc), "preview": exc.preview.as_dict()},
        ) from exc
    except ImportValidationError as exc:
        raise _validation_http_error(exc) from exc


@router.post("/import/{batch_id}/undo")
async def undo_import(
    client_id: UUID,
    batch_id: UUID,
    body: UndoInput,
    user: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> dict:
    try:
        return await PromptImportService(pool).undo(
            str(client_id), user.id, str(batch_id), confirmation=body.confirmation,
        )
    except ImportValidationError as exc:
        raise _validation_http_error(exc) from exc


__all__ = ["PreviewStaleError", "router"]
