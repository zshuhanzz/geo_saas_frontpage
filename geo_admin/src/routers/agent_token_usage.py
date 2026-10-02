"""
Agent Token Usage Router — dashboard data for token consumption tracking.

Provides aggregated views of token usage by client, user, day, and model.
Phase 2.5b (2026-04-26): SQL migrated off SQLAlchemy ``text().bindparams()`` —
plain ``:name`` placeholders interpreted by the asyncpg-backed ``database``
adapter.
"""
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from db import database

router = APIRouter(prefix="/agent-token-usage", tags=["Agent Token Usage"])
logger = logging.getLogger("GeoAdmin.agent_token_usage")


# ─── Pydantic models ───────────────────────────────────────────────────────


class UsageSummaryRow(BaseModel):
    day: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    total_input: int
    total_output: int
    total_tokens: int
    request_count: int


class UsageByUserRow(BaseModel):
    user_identifier: Optional[str] = None
    total_input: int
    total_output: int
    total_tokens: int
    request_count: int
    last_active: Optional[str] = None


class UsageByModelRow(BaseModel):
    model_id: str
    total_input: int
    total_output: int
    total_tokens: int
    request_count: int


class UsageTodayOut(BaseModel):
    total_tokens: int
    total_input: int
    total_output: int
    request_count: int


@router.get("/summary", response_model=list[UsageSummaryRow])
async def usage_summary(
    client_id: Optional[str] = None,
    days: int = 7,
) -> list[UsageSummaryRow]:
    """Aggregate token usage by day for the last N days."""
    sql = """
        SELECT
            date_trunc('day', t.created_at AT TIME ZONE 'UTC')::date AS day,
            c.name AS client_name,
            t.client_id::text,
            SUM(t.tokens_input) AS total_input,
            SUM(t.tokens_output) AS total_output,
            SUM(t.tokens_input + t.tokens_output) AS total_tokens,
            COUNT(*) AS request_count
        FROM agent_token_usage t
        LEFT JOIN geo_clients c ON t.client_id = c.id
        WHERE t.created_at >= NOW() - make_interval(days => :days)
    """

    params: dict = {"days": days}
    if client_id:
        sql += " AND t.client_id = CAST(:client_id AS uuid)"
        params["client_id"] = client_id

    sql += """
        GROUP BY day, c.name, t.client_id
        ORDER BY day DESC, total_tokens DESC
    """

    rows = await database.fetch_all(sql, params)

    return [
        UsageSummaryRow(
            day=str(r["day"]),
            client_id=r["client_id"],
            client_name=r["client_name"],
            total_input=r["total_input"],
            total_output=r["total_output"],
            total_tokens=r["total_tokens"],
            request_count=r["request_count"],
        )
        for r in rows
    ]


@router.get("/by-user", response_model=list[UsageByUserRow])
async def usage_by_user(
    client_id: str,
    days: int = 7,
) -> list[UsageByUserRow]:
    """Token usage breakdown by user for a specific client."""
    rows = await database.fetch_all(
        """
        SELECT
            t.user_identifier,
            SUM(t.tokens_input) AS total_input,
            SUM(t.tokens_output) AS total_output,
            SUM(t.tokens_input + t.tokens_output) AS total_tokens,
            COUNT(*) AS request_count,
            MAX(t.created_at) AS last_active
        FROM agent_token_usage t
        WHERE t.client_id = CAST(:client_id AS uuid)
          AND t.created_at >= NOW() - make_interval(days => :days)
        GROUP BY t.user_identifier
        ORDER BY total_tokens DESC
        """,
        {"client_id": client_id, "days": days},
    )

    return [
        UsageByUserRow(
            user_identifier=r["user_identifier"],
            total_input=r["total_input"],
            total_output=r["total_output"],
            total_tokens=r["total_tokens"],
            request_count=r["request_count"],
            last_active=str(r["last_active"]) if r["last_active"] else None,
        )
        for r in rows
    ]


@router.get("/by-model", response_model=list[UsageByModelRow])
async def usage_by_model(
    client_id: Optional[str] = None,
    days: int = 7,
) -> list[UsageByModelRow]:
    """Token usage breakdown by model."""
    sql = """
        SELECT
            COALESCE(t.model_id, 'unknown') AS model_id,
            SUM(t.tokens_input) AS total_input,
            SUM(t.tokens_output) AS total_output,
            SUM(t.tokens_input + t.tokens_output) AS total_tokens,
            COUNT(*) AS request_count
        FROM agent_token_usage t
        WHERE t.created_at >= NOW() - make_interval(days => :days)
    """

    params: dict = {"days": days}
    if client_id:
        sql += " AND t.client_id = CAST(:client_id AS uuid)"
        params["client_id"] = client_id

    sql += """
        GROUP BY model_id
        ORDER BY total_tokens DESC
    """

    rows = await database.fetch_all(sql, params)

    return [
        UsageByModelRow(
            model_id=r["model_id"],
            total_input=r["total_input"],
            total_output=r["total_output"],
            total_tokens=r["total_tokens"],
            request_count=r["request_count"],
        )
        for r in rows
    ]


@router.get("/today", response_model=UsageTodayOut)
async def usage_today(client_id: str) -> UsageTodayOut:
    """Get today's token usage for a specific client (for quota display)."""
    row = await database.fetch_one(
        """
        SELECT
            COALESCE(SUM(t.tokens_input + t.tokens_output), 0) AS total_tokens,
            COALESCE(SUM(t.tokens_input), 0) AS total_input,
            COALESCE(SUM(t.tokens_output), 0) AS total_output,
            COUNT(*) AS request_count
        FROM agent_token_usage t
        WHERE t.client_id = CAST(:client_id AS uuid)
          AND t.created_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC')
        """,
        {"client_id": client_id},
    )

    return UsageTodayOut(
        total_tokens=row["total_tokens"] if row else 0,
        total_input=row["total_input"] if row else 0,
        total_output=row["total_output"] if row else 0,
        request_count=row["request_count"] if row else 0,
    )
