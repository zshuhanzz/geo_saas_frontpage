"""
Stats Router (V2.5 SaaS) - Overview statistics for dashboard.

Updated to remove campaigns. Now counts clients, active prompts, tasks, and results.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from db import database

router = APIRouter()


class PromptCounts(BaseModel):
    total: int
    active: int


class ResultCounts(BaseModel):
    total: int
    unanalyzed: int


class StatsOut(BaseModel):
    clients: int
    prompts: PromptCounts
    tasks: int
    results: ResultCounts


@router.get("/stats", response_model=StatsOut)
async def get_stats() -> StatsOut:
    """Get overview statistics for dashboard."""

    clients_count = await database.fetch_val("SELECT COUNT(*) FROM geo_clients") or 0
    prompts_total = await database.fetch_val("SELECT COUNT(*) FROM geo_client_prompts") or 0
    prompts_active = await database.fetch_val(
        "SELECT COUNT(*) FROM geo_client_prompts WHERE is_active = TRUE"
    ) or 0
    tasks_count = await database.fetch_val("SELECT COUNT(*) FROM geo_tasks") or 0
    results_count = await database.fetch_val("SELECT COUNT(*) FROM geo_results") or 0
    unanalyzed_count = await database.fetch_val(
        "SELECT COUNT(*) FROM geo_results WHERE analyzed_at IS NULL"
    ) or 0

    return StatsOut(
        clients=clients_count,
        prompts=PromptCounts(total=prompts_total, active=prompts_active),
        tasks=tasks_count,
        results=ResultCounts(total=results_count, unanalyzed=unanalyzed_count),
    )
