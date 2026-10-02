"""SaaS user audit event recording.

This router records only client-facing SaaS UI behavior: page views and
meaningful business actions. Admin UI permission changes are intentionally
excluded and live outside this service.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Request
from geo_common.auth import AuthenticatedUser
from pydantic import BaseModel, Field

from dependencies.auth import require_current_user
router = APIRouter()

AuditEventType = Literal["page_view", "api_action"]


class AuditEventCreate(BaseModel):
    client_id: str
    event_type: AuditEventType
    action_key: str = Field(min_length=1, max_length=120)
    action_label: Optional[str] = Field(default=None, max_length=240)
    route: Optional[str] = Field(default=None, max_length=500)
    method: Optional[str] = Field(default=None, max_length=16)
    status_code: Optional[int] = None
    target_type: Optional[str] = Field(default=None, max_length=120)
    target_id: Optional[str] = Field(default=None, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEventAcceptedOut(BaseModel):
    accepted: bool


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or None
    return request.client.host if request.client else None


@router.post("/events", response_model=AuditEventAcceptedOut, status_code=202)
async def create_audit_event(
    data: AuditEventCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_current_user),
) -> AuditEventAcceptedOut:
    writer = getattr(request.app.state, "audit_writer", None)
    accepted = bool(
        writer
        and writer.enqueue(
            {
                "user_id": user.id,
                "client_id": data.client_id,
                "event_type": data.event_type,
                "action_key": data.action_key,
                "action_label": data.action_label,
                "route": data.route,
                "method": data.method,
                "status_code": data.status_code,
                "target_type": data.target_type,
                "target_id": data.target_id,
                "metadata": data.metadata,
                "ip_address": _client_ip(request),
                "user_agent": request.headers.get("user-agent"),
            }
        )
    )
    return AuditEventAcceptedOut(accepted=accepted)
