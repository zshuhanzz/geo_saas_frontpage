"""
Clients Router (V2.5 SaaS) - CRUD for geo_clients, peers, domains, topics, personas

Phase 4 (2026-04-25): migrated to :class:`ClientRepository`. ClientRepository
is NOT tenant-scoped because it operates above the tenant scope (the table it
guards IS the tenant). Related collections (peers / domains / topics /
personas) are batch-loaded via ``ClientRepository.fetch_related_collections``.

Provides endpoints for managing clients and all their associated config
dimensions (Platforms, Countries, Languages). Removed `geo_client_products`
as Product is now just an attribute/part of Topic.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, List, Literal, Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from geo_common.auth import AuthenticatedUser
from geo_common.services import BrandRepository, ClientRepository, WorkspaceWriteCoordinator
from geo_common.services.workspace_lifecycle import (
    WorkspaceLifecycleBusy,
    WorkspaceLifecycleMissing,
    try_acquire_workspace_lifecycle_exclusive,
)
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from dependencies.auth import require_current_user
from db import database
from pool import get_pool
from services.gcp_scheduler import (
    get_scheduler_job_status,
    stop_all_scheduler_jobs,
    sync_scheduler_job,
)
from services.workspace_deletion import (
    WorkspaceActiveWork,
    WorkspaceCascadeFootprint,
    delete_non_cascading_workspace_residuals,
    get_cascade_footprint_limit,
    load_workspace_cascade_footprint,
    load_workspace_active_work,
)
from services.feature_entitlements import apply_workspace_entitlements
from services.workspace_lifecycle import (
    long_workspace_lifecycle_session,
    long_workspace_lifecycle_slot,
)

router = APIRouter(prefix="/clients", tags=["Clients"])

logger = logging.getLogger("GeoAdmin.clients")


def _scheduler_sync_failure(client_id: str, job_type: str, exc: Exception) -> HTTPException:
    logger.exception(
        "[SCHEDULER] Failed to synchronize %s for Workspace %s",
        job_type,
        client_id,
        exc_info=exc,
    )
    return HTTPException(
        status_code=502,
        detail={
            "code": "SCHEDULER_SYNC_FAILED",
            "message": (
                f"Workspace was saved, but the {job_type} Cloud Scheduler job "
                "could not be synchronized. Retry the save operation."
            ),
        },
    )


def _fire_scheduler_sync(client_id: str, job_type: str, cron_expr: str | None):
    """Launch scheduler sync as background task with error logging."""
    async def _wrapper():
        try:
            # The guard is held across the external mutation. Final deletion's
            # exclusive fence therefore drains any in-flight sync before it
            # removes all jobs, while a late sync observes a missing Workspace.
            async with long_workspace_lifecycle_session(
                database.pool(), client_id
            ) as conn:
                # A detached task may have been queued before Stop All. Read
                # the canonical value only after taking the shared lifecycle
                # fence so an old captured value can never recreate a job
                # after maintenance has cleared the Workspace cron fields.
                row = await conn.fetchrow(
                    "SELECT cron_collector, cron_analyzer, cron_llm_discovery "
                    "FROM geo_clients WHERE id = $1::uuid",
                    client_id,
                )
                if not row:
                    return
                cron_field = {
                    "collector": "cron_collector",
                    "analyzer": "cron_analyzer",
                    "llm_discovery": "cron_llm_discovery",
                }[job_type]
                await sync_scheduler_job(client_id, job_type, row[cron_field])
        except Exception as e:
            logger.error(
                f"[SCHEDULER] Failed to sync {job_type} for client {client_id}: {e}"
            )
    asyncio.create_task(_wrapper())


# ============================================================================
# Pydantic Models
# ============================================================================

_SCHEDULER_JOB_TYPES = ("collector", "analyzer", "llm_discovery")
_STOPPED_SCHEDULER_STATES = {"NOT_FOUND", "PAUSED", "DISABLED"}
_PROMPT_FACT_COUNT_FIELDS = (
    "tasks",
    "results",
    "citations",
    "brand_mentions",
    "product_mentions",
    "sentiment_results",
    "sentiment_themes",
)
_WORKSPACE_DELETE_LOCK_NAME = "workspace-delete:global"
WORKSPACE_DELETE_ACQUIRE_TIMEOUT_SECONDS = 2.0
WORKSPACE_DELETE_STATEMENT_TIMEOUT_MS = 15_000


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    client_prompt_quota: int = 50
    config_platforms: List[str] = []
    config_countries: List[str] = []
    config_languages: List[str] = []
    cron_collector: Optional[str] = None
    cron_analyzer: Optional[str] = None
    cron_llm_discovery: Optional[str] = None
    feature_package_key: Optional[str] = "full_platform"
    feature_keys: Optional[List[str]] = None

    @model_validator(mode="after")
    def validate_feature_selection(self):
        if self.feature_package_key and self.feature_keys is not None:
            raise ValueError(
                "Choose either feature_package_key or feature_keys, not both"
            )
        if not self.feature_package_key and self.feature_keys is None:
            raise ValueError(
                "feature_package_key or feature_keys is required"
            )
        return self


class ClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    client_prompt_quota: Optional[int] = None
    config_platforms: Optional[List[str]] = None
    config_countries: Optional[List[str]] = None
    config_languages: Optional[List[str]] = None
    cron_collector: Optional[str] = None
    cron_analyzer: Optional[str] = None
    cron_llm_discovery: Optional[str] = None
    agent_daily_token_quota: Optional[int] = None
    agent_rpm_limit: Optional[int] = None
    reuse_latest_final_prompt: Optional[bool] = None
    country_localization_mode: Optional[Literal["generic", "localized_by_country"]] = None
    final_prompt_per_client_prompt: Optional[int] = None
    default_calls_per_prompt: Optional[int] = None

    @field_validator("final_prompt_per_client_prompt", "default_calls_per_prompt")
    @classmethod
    def _positive_int_or_null(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 1:
            raise ValueError("must be greater than or equal to 1")
        return value


class ClientOut(BaseModel):
    id: str
    name: str
    client_prompt_quota: Optional[int] = None
    aliases: List[str] = []
    config_platforms: Optional[List[str]] = None
    config_countries: Optional[List[str]] = None
    config_languages: List[str] = []
    cron_collector: Optional[str] = None
    cron_analyzer: Optional[str] = None
    cron_llm_discovery: Optional[str] = None
    agent_daily_token_quota: Optional[int] = None
    agent_rpm_limit: Optional[int] = None
    reuse_latest_final_prompt: Optional[bool] = None
    country_localization_mode: Optional[Literal["generic", "localized_by_country"]] = None
    final_prompt_per_client_prompt: Optional[int] = None
    default_calls_per_prompt: Optional[int] = None
    # Related collections — full row dicts (schemas are wide and the raw
    # ``dict(record)`` form is what the admin UI consumes verbatim).
    peers: List[Any] = []
    domains: List[Any] = []
    topics: List[Any] = []
    personas: List[Any] = []


class ClientBrandOut(BaseModel):
    id: str
    brand_name: str
    aliases: List[str]
    is_shadow: bool


class BrandAliasesUpdate(BaseModel):
    aliases: List[str]


class SchedulerJobStatusOut(BaseModel):
    """Status payload for a single scheduler job. Shape comes from
    ``services.gcp_scheduler.get_scheduler_job_status`` and is intentionally
    open so we don't need to keep this model in lockstep with that helper."""

    model_config = {"extra": "allow"}


class SchedulerStatusOut(BaseModel):
    client_id: str
    collector: Optional[Any] = None
    analyzer: Optional[Any] = None
    llm_discovery: Optional[Any] = None
    cron_collector: Optional[str] = None
    cron_analyzer: Optional[str] = None
    cron_llm_discovery: Optional[str] = None


class SchedulerActionOut(BaseModel):
    message: str
    client_id: str


class WorkspaceIdentityOut(BaseModel):
    id: str
    name: str


class WorkspaceDeletionCountsOut(BaseModel):
    topics: int
    logical_prompts: int
    physical_prompts: int
    tasks: int
    results: int
    citations: int
    brand_mentions: int
    product_mentions: int
    sentiment_results: int
    sentiment_themes: int
    static_reports: int
    agent_tasks: int
    published_urls: int


class WorkspaceSchedulerStateOut(BaseModel):
    state: str
    cron_expression: Optional[str] = None
    stopped: bool
    error: Optional[str] = None


class WorkspaceSchedulersOut(BaseModel):
    collector: WorkspaceSchedulerStateOut
    analyzer: WorkspaceSchedulerStateOut
    llm_discovery: WorkspaceSchedulerStateOut


class WorkspaceDeletionBlockerOut(BaseModel):
    code: str
    message: str
    count: Optional[int] = None


class WorkspaceCascadeFootprintOut(BaseModel):
    total_rows: int
    max_rows: int
    by_table: dict[str, int]


class WorkspaceActiveWorkOut(BaseModel):
    guarded_writer: bool
    total_items: int
    by_table: dict[str, int]


class WorkspaceDeletionReadinessOut(BaseModel):
    workspace: WorkspaceIdentityOut
    schedulers: WorkspaceSchedulersOut
    counts: WorkspaceDeletionCountsOut
    cascade_footprint: WorkspaceCascadeFootprintOut
    active_work: WorkspaceActiveWorkOut
    blockers: List[WorkspaceDeletionBlockerOut]
    recommended_next_action: Literal[
        "STOP_SCHEDULING",
        "DELETE_PROMPTS",
        "DELETE_TOPICS",
        "INTERNAL_DATA_REPAIR",
        "FINALIZE_DELETE",
    ]
    can_finalize: bool


class WorkspaceDeleteConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_name: str


_WORKSPACE_DELETION_COUNTS_SQL = """
WITH workspace AS (
    SELECT id, name, cron_collector, cron_analyzer, cron_llm_discovery
    FROM geo_clients
    WHERE id = $1::uuid
), counts AS (
    SELECT
        (SELECT COUNT(*) FROM geo_client_topics WHERE client_id = $1::uuid) AS topics,
        (
            SELECT COUNT(*) FROM (
                SELECT 1
                FROM geo_client_prompts
                WHERE client_id = $1::uuid
                GROUP BY
                    topic_id,
                    LOWER(REGEXP_REPLACE(BTRIM(COALESCE(text, '')), '\\s+', ' ', 'g')),
                    LOWER(REGEXP_REPLACE(BTRIM(COALESCE(product, '')), '\\s+', ' ', 'g')),
                    LOWER(REGEXP_REPLACE(BTRIM(COALESCE(intent, '')), '\\s+', ' ', 'g')),
                    LOWER(REGEXP_REPLACE(BTRIM(COALESCE(language, '')), '\\s+', ' ', 'g'))
            ) logical_prompt_rows
        ) AS logical_prompts,
        (SELECT COUNT(*) FROM geo_client_prompts WHERE client_id = $1::uuid) AS physical_prompts,
        (SELECT COUNT(*) FROM geo_tasks WHERE client_id = $1::uuid) AS tasks,
        (SELECT COUNT(*) FROM geo_results WHERE client_id = $1::uuid) AS results,
        (SELECT COUNT(*) FROM geo_citations WHERE client_id = $1::uuid) AS citations,
        (SELECT COUNT(*) FROM geo_brand_mentions WHERE client_id = $1::uuid) AS brand_mentions,
        (SELECT COUNT(*) FROM geo_product_mentions WHERE client_id = $1::uuid) AS product_mentions,
        (SELECT COUNT(*) FROM geo_sentiment_results WHERE client_id = $1::uuid) AS sentiment_results,
        (SELECT COUNT(*) FROM geo_sentiment_themes WHERE client_id = $1::uuid) AS sentiment_themes,
        (SELECT COUNT(*) FROM geo_static_reports WHERE client_id = $1::uuid) AS static_reports,
        (SELECT COUNT(*) FROM geo_agent_tasks WHERE client_id = $1::uuid) AS agent_tasks,
        (SELECT COUNT(*) FROM geo_published_urls WHERE client_id = $1::uuid) AS published_urls
)
SELECT workspace.*, counts.*
FROM workspace CROSS JOIN counts
"""


async def _fetch_workspace_deletion_row(conn, client_id: UUID | str) -> dict[str, Any] | None:
    row = await conn.fetchrow(_WORKSPACE_DELETION_COUNTS_SQL, str(client_id))
    return dict(row) if row else None


def _scheduler_state(
    raw: dict[str, Any] | None,
    cron_expression: str | None,
) -> WorkspaceSchedulerStateOut:
    payload = raw or {"state": "UNKNOWN", "error": "Scheduler status unavailable"}
    state = str(payload.get("state") or "UNKNOWN").upper()
    # A persisted cron is still configured even if its Cloud job happens to be
    # absent. Stop All clears both the job and this source configuration.
    stopped = cron_expression is None and state in _STOPPED_SCHEDULER_STATES
    return WorkspaceSchedulerStateOut(
        state=state,
        cron_expression=cron_expression,
        stopped=stopped,
        error=str(payload["error"]) if payload.get("error") else None,
    )


def _build_readiness_from_row(
    row: dict[str, Any],
    scheduler_states: dict[str, dict[str, Any] | None],
    cascade_footprint: WorkspaceCascadeFootprint | None = None,
    cascade_footprint_limit: int | None = None,
    active_work: WorkspaceActiveWork | None = None,
    guarded_writer_active: bool = False,
) -> WorkspaceDeletionReadinessOut:
    counts = WorkspaceDeletionCountsOut(
        **{field: int(row.get(field) or 0) for field in WorkspaceDeletionCountsOut.model_fields}
    )
    schedulers = WorkspaceSchedulersOut(
        **{
            job_type: _scheduler_state(
                scheduler_states.get(job_type),
                row.get(f"cron_{job_type}"),
            )
            for job_type in _SCHEDULER_JOB_TYPES
        }
    )
    footprint = cascade_footprint or WorkspaceCascadeFootprint(
        by_table={},
        total_rows=0,
        present_tables=frozenset(),
    )
    footprint_limit = (
        get_cascade_footprint_limit()
        if cascade_footprint_limit is None
        else cascade_footprint_limit
    )
    active = active_work or WorkspaceActiveWork(by_table={}, total_items=0)
    blockers: list[WorkspaceDeletionBlockerOut] = []
    if not all(item.stopped for item in (schedulers.collector, schedulers.analyzer, schedulers.llm_discovery)):
        blockers.append(
            WorkspaceDeletionBlockerOut(
                code="SCHEDULERS_RUNNING",
                message="Stop all Workspace scheduling before final deletion",
            )
        )
    if counts.physical_prompts or counts.logical_prompts:
        blockers.append(
            WorkspaceDeletionBlockerOut(
                code="PROMPTS_REMAIN",
                message="Delete all Prompts through Workspace Cleanup",
                count=counts.physical_prompts,
            )
        )
    if counts.topics:
        blockers.append(
            WorkspaceDeletionBlockerOut(
                code="TOPICS_REMAIN",
                message="Delete all Topics after Prompt cleanup",
                count=counts.topics,
            )
        )
    fact_count = sum(getattr(counts, field) for field in _PROMPT_FACT_COUNT_FIELDS)
    if not counts.physical_prompts and fact_count:
        blockers.append(
            WorkspaceDeletionBlockerOut(
                code="ORPHANED_FACTS",
                message="Internal data repair is required before this Workspace can be deleted",
                count=fact_count,
            )
        )
    if footprint.total_rows > footprint_limit:
        blockers.append(
            WorkspaceDeletionBlockerOut(
                code="CASCADE_FOOTPRINT_TOO_LARGE",
                message="Internal data repair is required because the final cascade footprint is too large",
                count=footprint.total_rows,
            )
        )
    if guarded_writer_active or active.total_items:
        blockers.append(
            WorkspaceDeletionBlockerOut(
                code="ACTIVE_WORK_IN_PROGRESS",
                message="Wait for active Workspace work to finish before final deletion",
                count=active.total_items or None,
            )
        )

    if any(blocker.code == "SCHEDULERS_RUNNING" for blocker in blockers):
        action = "STOP_SCHEDULING"
    elif counts.physical_prompts or counts.logical_prompts:
        action = "DELETE_PROMPTS"
    elif counts.topics:
        action = "DELETE_TOPICS"
    elif fact_count or footprint.total_rows > footprint_limit or guarded_writer_active or active.total_items:
        action = "INTERNAL_DATA_REPAIR"
    else:
        action = "FINALIZE_DELETE"

    return WorkspaceDeletionReadinessOut(
        workspace=WorkspaceIdentityOut(id=str(row["id"]), name=str(row["name"])),
        schedulers=schedulers,
        counts=counts,
        cascade_footprint=WorkspaceCascadeFootprintOut(
            total_rows=footprint.total_rows,
            max_rows=footprint_limit,
            by_table=footprint.by_table,
        ),
        active_work=WorkspaceActiveWorkOut(
            guarded_writer=guarded_writer_active,
            total_items=active.total_items,
            by_table=active.by_table,
        ),
        blockers=blockers,
        recommended_next_action=action,
        can_finalize=not blockers,
    )


def _data_blockers(readiness: WorkspaceDeletionReadinessOut) -> list[WorkspaceDeletionBlockerOut]:
    return [blocker for blocker in readiness.blockers if blocker.code != "SCHEDULERS_RUNNING"]


def _blocked_delete_detail(
    readiness: WorkspaceDeletionReadinessOut,
    blockers: list[WorkspaceDeletionBlockerOut],
) -> dict[str, Any]:
    return {
        "code": "WORKSPACE_DELETE_BLOCKED",
        "message": "Workspace cleanup is incomplete",
        "recommended_next_action": readiness.recommended_next_action,
        "blockers": [item.model_dump(exclude_none=True) for item in blockers],
        "counts": readiness.counts.model_dump(),
    }


@asynccontextmanager
async def _acquire_delete_connection(pool):
    acquire_cm = pool.acquire()
    try:
        async with asyncio.timeout(WORKSPACE_DELETE_ACQUIRE_TIMEOUT_SECONDS):
            conn = await acquire_cm.__aenter__()
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DATABASE_BUSY",
                "message": "Workspace deletion could not acquire a database connection",
            },
        ) from exc
    try:
        yield conn
    finally:
        await acquire_cm.__aexit__(None, None, None)


async def _set_workspace_delete_statement_timeout(conn) -> None:
    await conn.fetchval(
        "SELECT set_config('statement_timeout', $1, true)",
        f"{WORKSPACE_DELETE_STATEMENT_TIMEOUT_MS}ms",
    )


async def _readiness_on_connection(
    conn,
    client_id: UUID | str,
    scheduler_states: dict[str, dict[str, Any] | None],
) -> tuple[WorkspaceDeletionReadinessOut, WorkspaceCascadeFootprint] | None:
    row = await _fetch_workspace_deletion_row(conn, client_id)
    if not row:
        return None
    footprint = await load_workspace_cascade_footprint(conn, str(client_id))
    active_work = await load_workspace_active_work(conn, str(client_id))
    return (
        _build_readiness_from_row(
            row,
            scheduler_states,
            footprint,
            get_cascade_footprint_limit(),
            active_work,
            False,
        ),
        footprint,
    )


def _client_row_to_out(client: dict[str, Any], related: dict[str, list]) -> ClientOut:
    return ClientOut(
        id=str(client["id"]),
        name=client["name"],
        client_prompt_quota=client["client_prompt_quota"],
        aliases=client["aliases"] or [],
        config_platforms=client["config_platforms"],
        config_countries=client["config_countries"],
        config_languages=client["config_languages"] or [],
        cron_collector=client["cron_collector"],
        cron_analyzer=client["cron_analyzer"],
        cron_llm_discovery=client["cron_llm_discovery"],
        agent_daily_token_quota=client["agent_daily_token_quota"],
        agent_rpm_limit=client["agent_rpm_limit"],
        reuse_latest_final_prompt=client.get("reuse_latest_final_prompt"),
        country_localization_mode=client.get("country_localization_mode"),
        final_prompt_per_client_prompt=client.get("final_prompt_per_client_prompt"),
        default_calls_per_prompt=client.get("default_calls_per_prompt"),
        peers=related.get("peers", []),
        domains=related.get("domains", []),
        topics=related.get("topics", []),
        personas=related.get("personas", []),
    )


# ============================================================================
# Client CRUD
# ============================================================================

@router.get("", response_model=List[ClientOut])
async def list_clients(
    search: Optional[str] = None, pool=Depends(get_pool)
) -> List[ClientOut]:
    """List all clients with their peers, domains, topics, personas."""
    repo = ClientRepository(pool)
    clients = await repo.list_all(search=search)
    if not clients:
        return []

    client_ids = [c["id"] for c in clients]
    related_all = await repo.fetch_related_collections(client_ids)

    return [
        _client_row_to_out(
            c,
            {
                "peers": related_all["peers"].get(c["id"], []),
                "domains": related_all["domains"].get(c["id"], []),
                "topics": related_all["topics"].get(c["id"], []),
                "personas": related_all["personas"].get(c["id"], []),
            },
        )
        for c in clients
    ]


@router.post("", status_code=201, response_model=ClientOut)
async def create_client(data: ClientCreate, pool=Depends(get_pool)) -> ClientOut:
    """Create a new client with configuration pools, peers, and domains."""
    repo = ClientRepository(pool)
    if await repo.get_by_name(data.name):
        raise HTTPException(
            status_code=400, detail="Client with this name already exists"
        )

    async with pool.acquire() as conn:
        async with conn.transaction():
            new_row = await repo.add(
                name=data.name,
                client_prompt_quota=data.client_prompt_quota,
                config_platforms=data.config_platforms,
                config_countries=data.config_countries,
                config_languages=data.config_languages,
                cron_collector=data.cron_collector,
                cron_analyzer=data.cron_analyzer,
                cron_llm_discovery=data.cron_llm_discovery,
                conn=conn,
            )
            await apply_workspace_entitlements(
                conn,
                client_id=str(new_row["id"]),
                package_key=data.feature_package_key,
                feature_keys=data.feature_keys,
            )
    client_id = new_row["id"]

    # A creation response must not claim success before the corresponding
    # external jobs exist. Admin normally creates a Workspace first and saves
    # cron configuration afterwards, but API callers may supply cron fields in
    # the initial request and receive the same confirmed behaviour.
    for job_type, cron_expr in (
        ("collector", data.cron_collector),
        ("analyzer", data.cron_analyzer),
        ("llm_discovery", data.cron_llm_discovery),
    ):
        if not cron_expr:
            continue
        try:
            await sync_scheduler_job(str(client_id), job_type, cron_expr)
        except Exception as exc:
            raise _scheduler_sync_failure(str(client_id), job_type, exc) from exc

    return await get_client(client_id, pool=pool)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(client_id: UUID, pool=Depends(get_pool)) -> ClientOut:
    """Get a single client by ID with all associated data."""
    repo = ClientRepository(pool)
    client = await repo.get_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    related_all = await repo.fetch_related_collections([client_id])
    return _client_row_to_out(
        client,
        {
            "peers": related_all["peers"].get(client["id"], []),
            "domains": related_all["domains"].get(client["id"], []),
            "topics": related_all["topics"].get(client["id"], []),
            "personas": related_all["personas"].get(client["id"], []),
        },
    )


@router.get("/{client_id}/brands", response_model=List[ClientBrandOut])
async def list_client_brands(
    client_id: UUID,
    pool=Depends(get_pool),
) -> List[ClientBrandOut]:
    """List active Own and Shadow brands from the canonical brand table."""
    rows = await BrandRepository(pool).list_for_client(
        str(client_id),
        include_shadow=True,
        only_active=True,
    )
    return [
        ClientBrandOut(
            id=str(row["id"]),
            brand_name=row["brand_name"],
            aliases=list(row["aliases"] or []),
            is_shadow=bool(row["is_shadow"]),
        )
        for row in rows
    ]


@router.put(
    "/{client_id}/brands/{brand_id}/aliases",
    response_model=ClientBrandOut,
)
async def update_client_brand_aliases(
    client_id: UUID,
    brand_id: UUID,
    data: BrandAliasesUpdate,
    actor: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> ClientBrandOut:
    """Atomically replace aliases.

    Request audit is handled asynchronously by the Admin API interceptor so
    audit availability can never roll back this business write.
    """
    client_key = str(client_id)
    brand_key = str(brand_id)
    repository = BrandRepository(pool)

    async def update_aliases(conn):
        row = await repository.update_aliases_on_connection(
            client_key,
            brand_key,
            data.aliases,
            conn=conn,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Brand not found")
        return row

    row = await WorkspaceWriteCoordinator(pool).execute(
        client_key,
        update_aliases,
    )
    return ClientBrandOut(
        id=str(row["id"]),
        brand_name=row["brand_name"],
        aliases=list(row["aliases"] or []),
        is_shadow=bool(row["is_shadow"]),
    )


@router.put("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: UUID, data: ClientUpdate, pool=Depends(get_pool)
) -> ClientOut:
    """Update client core configs and pools."""
    repo = ClientRepository(pool)
    if not await repo.get_by_id(client_id):
        raise HTTPException(status_code=404, detail="Client not found")

    updates = data.model_dump(exclude_unset=True)
    if updates:
        try:
            # Persist and synchronize cron changes under one lifecycle fence.
            # The request only reports success after Cloud Scheduler confirms
            # the create/update/delete operation, preventing DB/UI false
            # positives and blocking deletion from racing an external write.
            async with long_workspace_lifecycle_session(
                pool,
                str(client_id),
            ):
                await repo.update(client_id, updates=updates)
                for job_type, field_name in (
                    ("collector", "cron_collector"),
                    ("analyzer", "cron_analyzer"),
                    ("llm_discovery", "cron_llm_discovery"),
                ):
                    if field_name not in data.model_fields_set:
                        continue
                    try:
                        await sync_scheduler_job(
                            str(client_id),
                            job_type,
                            updates.get(field_name),
                        )
                    except Exception as exc:
                        raise _scheduler_sync_failure(
                            str(client_id),
                            job_type,
                            exc,
                        ) from exc
        except WorkspaceLifecycleMissing as exc:
            raise HTTPException(status_code=404, detail="Client not found") from exc
        except WorkspaceLifecycleBusy as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ACTIVE_WORK_IN_PROGRESS",
                    "message": "Workspace maintenance is in progress",
                },
            ) from exc

    return await get_client(client_id, pool=pool)


@router.get(
    "/{client_id}/deletion-readiness",
    response_model=WorkspaceDeletionReadinessOut,
)
async def get_deletion_readiness(
    client_id: UUID,
    pool=Depends(get_pool),
) -> WorkspaceDeletionReadinessOut:
    """Read-only inventory and guided next step for safe Workspace deletion."""
    try:
        async with _acquire_delete_connection(pool) as conn:
            async with conn.transaction():
                await _set_workspace_delete_statement_timeout(conn)
                lifecycle_fenced = await try_acquire_workspace_lifecycle_exclusive(
                    conn,
                    str(client_id),
                )
                row = await _fetch_workspace_deletion_row(conn, client_id)
                if not row:
                    raise HTTPException(status_code=404, detail="Client not found")
                footprint = await load_workspace_cascade_footprint(conn, str(client_id))
                active_work = await load_workspace_active_work(conn, str(client_id))
    except asyncpg.QueryCanceledError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "WORKSPACE_READINESS_TIMEOUT",
                "message": "Workspace deletion readiness exceeded the database statement timeout",
            },
        ) from exc

    states = await asyncio.gather(
        *(get_scheduler_job_status(str(client_id), job_type) for job_type in _SCHEDULER_JOB_TYPES)
    )
    return _build_readiness_from_row(
        row,
        dict(zip(_SCHEDULER_JOB_TYPES, states, strict=True)),
        footprint,
        get_cascade_footprint_limit(),
        active_work,
        not lifecycle_fenced,
    )


@router.post(
    "/{client_id}/deletion-readiness/stop-all-scheduling",
    response_model=WorkspaceDeletionReadinessOut,
)
async def stop_all_scheduling(
    client_id: UUID,
    pool=Depends(get_pool),
) -> WorkspaceDeletionReadinessOut:
    """Strictly remove all three jobs, clear cron config, and refresh readiness."""
    async with long_workspace_lifecycle_slot():
        async with _acquire_delete_connection(pool) as conn:
            async with conn.transaction():
                await _set_workspace_delete_statement_timeout(conn)
                lifecycle_fenced = await try_acquire_workspace_lifecycle_exclusive(
                    conn,
                    str(client_id),
                )
                if not lifecycle_fenced:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "ACTIVE_WORK_IN_PROGRESS",
                            "message": "Wait for active Workspace work before stopping scheduling",
                        },
                    )
                client_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM geo_clients WHERE id = $1::uuid)",
                    str(client_id),
                )
                if not client_exists:
                    raise HTTPException(status_code=404, detail="Client not found")

                await conn.execute(
                    "UPDATE geo_clients SET "
                    "cron_collector = NULL, cron_analyzer = NULL, cron_llm_discovery = NULL, "
                    "updated_at = NOW() WHERE id = $1::uuid",
                    str(client_id),
                )
                try:
                    await stop_all_scheduler_jobs(str(client_id))
                except Exception as exc:
                    logger.exception(
                        "Failed to stop all scheduler jobs for Workspace %s",
                        client_id,
                    )
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "code": "SCHEDULER_STOP_FAILED",
                            "message": "One or more Workspace schedules could not be stopped",
                        },
                    ) from exc

                states = await asyncio.gather(
                    *(
                        get_scheduler_job_status(str(client_id), job_type)
                        for job_type in _SCHEDULER_JOB_TYPES
                    )
                )
                locked_result = await _readiness_on_connection(
                    conn,
                    client_id,
                    dict(zip(_SCHEDULER_JOB_TYPES, states, strict=True)),
                )
                if not locked_result:
                    raise HTTPException(status_code=404, detail="Client not found")
                readiness, _footprint = locked_result
                return readiness


# 204 No Content — response_model= is incompatible with empty-body responses.
@router.delete("/{client_id}", status_code=204)
async def delete_client(
    client_id: UUID,
    data: WorkspaceDeleteConfirm,
    actor: AuthenticatedUser = Depends(require_current_user),
    pool=Depends(get_pool),
) -> None:
    """Guarded low-volume final delete after guided Workspace cleanup."""
    try:
        async with _acquire_delete_connection(pool) as conn:
            async with conn.transaction():
                # The transaction-scoped global single-flight decision is
                # deliberately the first business SQL. It is released by
                # PostgreSQL on commit, rollback, request cancellation, or
                # connection failure; no pooled session can retain it.
                acquired = await conn.fetchval(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))",
                    _WORKSPACE_DELETE_LOCK_NAME,
                )
                if not acquired:
                    raise HTTPException(
                        status_code=423,
                        detail={
                            "code": "WORKSPACE_DELETE_IN_PROGRESS",
                            "message": "Another Workspace deletion is already in progress",
                        },
                    )
                await _set_workspace_delete_statement_timeout(conn)
                # Lock order is lifecycle fence before subsystem locks.
                # Do not block while guarded writers own it: failing fast
                # avoids holding this scarce pool connection in a convoy.
                lifecycle_fenced = await try_acquire_workspace_lifecycle_exclusive(
                    conn,
                    str(client_id),
                )
                if not lifecycle_fenced:
                    blocker = {
                        "code": "ACTIVE_WORK_IN_PROGRESS",
                        "message": "Wait for active Workspace work to finish before final deletion",
                    }
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "ACTIVE_WORK_IN_PROGRESS",
                            "message": blocker["message"],
                            "recommended_next_action": "INTERNAL_DATA_REPAIR",
                            "blockers": [blocker],
                        },
                    )
                client_row = await conn.fetchrow(
                    "SELECT id, name FROM geo_clients WHERE id = $1::uuid FOR UPDATE",
                    str(client_id),
                )
                if not client_row:
                    raise HTTPException(status_code=404, detail="Client not found")
                if data.workspace_name != str(client_row["name"]):
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "WORKSPACE_NAME_MISMATCH",
                            "message": "Workspace name confirmation must match exactly",
                        },
                    )
                # Serialize against every SaaS Prompt create/update/delete
                # path after owning the broader lifecycle fence.
                await conn.fetchval(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    f"prompt-write:{client_id}",
                )

                locked_result = await _readiness_on_connection(
                    conn,
                    client_id,
                    {job_type: {"state": "NOT_FOUND"} for job_type in _SCHEDULER_JOB_TYPES},
                )
                if not locked_result:
                    raise HTTPException(status_code=404, detail="Client not found")
                locked_readiness, locked_footprint = locked_result
                locked_blockers = _data_blockers(locked_readiness)
                if locked_blockers:
                    raise HTTPException(
                        status_code=409,
                        detail=_blocked_delete_detail(locked_readiness, locked_blockers),
                    )

                try:
                    await stop_all_scheduler_jobs(str(client_id))
                except Exception as exc:
                    logger.exception(
                        "Failed to remove scheduler jobs during Workspace deletion %s",
                        client_id,
                    )
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "code": "SCHEDULER_STOP_FAILED",
                            "message": "Workspace schedules could not be removed",
                        },
                    ) from exc

                await conn.execute(
                    "UPDATE geo_clients SET "
                    "cron_collector = NULL, cron_analyzer = NULL, cron_llm_discovery = NULL, "
                    "updated_at = NOW() WHERE id = $1::uuid",
                    str(client_id),
                )
                await delete_non_cascading_workspace_residuals(
                    conn,
                    str(client_id),
                    locked_footprint.present_tables,
                )
                status = await conn.execute(
                    "DELETE FROM geo_clients WHERE id = $1::uuid",
                    str(client_id),
                )
                if status.rsplit(" ", 1)[-1] == "0":
                    raise HTTPException(status_code=404, detail="Client not found")
    except asyncpg.QueryCanceledError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "WORKSPACE_DELETE_TIMEOUT",
                "message": "Workspace deletion exceeded the database statement timeout",
            },
        ) from exc
    return None


# ============================================================================
# Scheduler Management
# ============================================================================

@router.get("/{client_id}/scheduler/status", response_model=SchedulerStatusOut)
async def get_scheduler_status(
    client_id: UUID, pool=Depends(get_pool)
) -> SchedulerStatusOut:
    """Get the status of GCP Cloud Scheduler jobs for this client."""
    from services.gcp_scheduler import get_scheduler_job_status

    repo = ClientRepository(pool)
    client = await repo.get_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    collector_status = await get_scheduler_job_status(str(client_id), "collector")
    analyzer_status = await get_scheduler_job_status(str(client_id), "analyzer")
    llm_discovery_status = await get_scheduler_job_status(str(client_id), "llm_discovery")

    return SchedulerStatusOut(
        client_id=str(client_id),
        collector=collector_status,
        analyzer=analyzer_status,
        llm_discovery=llm_discovery_status,
        cron_collector=client["cron_collector"],
        cron_analyzer=client["cron_analyzer"],
        cron_llm_discovery=client["cron_llm_discovery"],
    )


def _validate_job_type(job_type: str) -> None:
    if job_type not in _SCHEDULER_JOB_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"job_type must be one of {_SCHEDULER_JOB_TYPES}",
        )


@router.post("/{client_id}/scheduler/{job_type}/pause", response_model=SchedulerActionOut)
async def pause_scheduler(client_id: UUID, job_type: str) -> SchedulerActionOut:
    """Pause a GCP Cloud Scheduler job."""
    _validate_job_type(job_type)
    from services.gcp_scheduler import pause_scheduler_job
    await pause_scheduler_job(str(client_id), job_type)
    return SchedulerActionOut(
        message=f"{job_type} scheduler paused",
        client_id=str(client_id),
    )


@router.post("/{client_id}/scheduler/{job_type}/enable", response_model=SchedulerActionOut)
async def enable_scheduler(
    client_id: UUID,
    job_type: str,
    pool=Depends(get_pool),
) -> SchedulerActionOut:
    """Create a missing Scheduler job from the Workspace's saved cron."""
    _validate_job_type(job_type)
    client = await ClientRepository(pool).get_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    cron_field = {
        "collector": "cron_collector",
        "analyzer": "cron_analyzer",
        "llm_discovery": "cron_llm_discovery",
    }[job_type]
    cron_expr = client[cron_field]
    if not cron_expr:
        raise HTTPException(
            status_code=400,
            detail=f"Configure the {job_type} cron schedule before enabling it",
        )

    try:
        await sync_scheduler_job(str(client_id), job_type, cron_expr)
    except Exception as exc:
        raise _scheduler_sync_failure(str(client_id), job_type, exc) from exc
    return SchedulerActionOut(
        message=f"{job_type} scheduler enabled",
        client_id=str(client_id),
    )


@router.post("/{client_id}/scheduler/{job_type}/resume", response_model=SchedulerActionOut)
async def resume_scheduler(client_id: UUID, job_type: str) -> SchedulerActionOut:
    """Resume a GCP Cloud Scheduler job."""
    _validate_job_type(job_type)
    from services.gcp_scheduler import resume_scheduler_job
    await resume_scheduler_job(str(client_id), job_type)
    return SchedulerActionOut(
        message=f"{job_type} scheduler resumed",
        client_id=str(client_id),
    )


@router.post("/{client_id}/scheduler/{job_type}/run-once", response_model=SchedulerActionOut)
async def run_scheduler_once(client_id: UUID, job_type: str) -> SchedulerActionOut:
    """Manually trigger a Cloud Scheduler job to execute once."""
    _validate_job_type(job_type)
    from services.gcp_scheduler import force_run_scheduler_job
    await force_run_scheduler_job(str(client_id), job_type)
    return SchedulerActionOut(
        message=f"{job_type} scheduler triggered",
        client_id=str(client_id),
    )
