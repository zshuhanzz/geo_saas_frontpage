"""
geo_agent FastAPI Application.

Independent Cloud Run service for the Agent layer.
Provides SSE streaming chat endpoint and session management.
"""
import os
import json
import uuid
import asyncio
import logging
import traceback
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from geo_common.audit import AsyncAuditWriter, sanitize_query_params
from pydantic import BaseModel

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from geo_common.services import (
    WorkspaceWriteCoordinator,
    acquire_workspace_lifecycle_session_shared,
    release_workspace_lifecycle_session_shared,
)
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from langchain_core.messages import HumanMessage

from database import (
    agent_workspace_lifecycle_session,
    close_pool,
    get_pool,
    release_workspace_lifecycle_slot,
    reserve_workspace_lifecycle_slot,
)
from graphs.supervisor import build_supervisor_graph
from middleware.rate_limiter import check_rate_limit, get_limiter, get_quota_status, cleanup_old_token_usage
from context.compressor import should_compress, compress_messages, get_context_usage
from context.memory import evaluate_and_update_memory, load_memories, build_memory_context, get_memory_count
from context.user_profile import load_profile, build_profile_context, is_onboarded, COLD_START_INSTRUCTION
from tools.utility_tools import get_system_context
from llm.client import start_token_tracking, get_tracked_tokens
from routers.tasks import router as tasks_router, register_pipeline
from routers.templates import router as templates_router
from routers.framework import router as framework_router
from routers.content_preselect import router as content_preselect_router
from routers.strategy import router as strategy_router
from routers.export import router as export_router
from dependencies.auth import (
    AuthenticatedUser,
    require_feature_access_if_present,
    require_feature_or_system_task_job_access,
    user_identifier,
)
import pipelines.content_pipeline  # registers content_generation pipeline on import
import pipelines.analysis_pipeline  # registers analysis pipeline on import
import pipelines.opportunity_pipeline  # registers opportunity_discovery pipeline on import

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("GeoAgentAPI")

# ─────────────────────────────────────────────────────────────
# Globals (initialized in lifespan)
# ─────────────────────────────────────────────────────────────
_checkpointer: Optional[AsyncPostgresSaver] = None
_graph = None
_background_tasks: set[asyncio.Task] = set()


def _get_db_uri() -> str:
    """Build postgres URI for LangGraph checkpointer (psycopg).

    Reuses the same default as database.py so local dev works without .env.
    """
    uri = os.environ.get(
        "DATABASE_URL",
        "postgresql://answer-x-geo-db-user:answer-x-geo-db-user-123@localhost:5432/answer-x-geo-db",
    )
    # Strip asyncpg driver prefix if present — psycopg needs plain postgresql://
    return uri.replace("postgresql+asyncpg://", "postgresql://")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database pool and LangGraph checkpointer lifecycle."""
    global _checkpointer, _graph

    logger.info("Starting geo_agent...")

    # Initialize asyncpg pool (for data tools)
    pool = await get_pool()
    app.state.audit_writer = AsyncAuditWriter(pool)
    app.state.audit_writer.start()

    # Recover orphaned RUNNING tasks from previous server restart
    orphaned = await pool.fetch(
        "UPDATE geo_agent_tasks SET status = 'FAILED', error_message = '服务重启，任务中断。请重新运行。', completed_at = NOW(), updated_at = NOW() WHERE status = 'RUNNING' RETURNING id"
    )
    if orphaned:
        logger.warning(f"[STARTUP] Recovered {len(orphaned)} orphaned RUNNING tasks → FAILED")

    # Initialize LangGraph checkpointer with a connection pool (not a single conn).
    # A single AsyncConnection dies when the server closes it (idle timeout, Cloud SQL
    # proxy restart, etc.) and has no way to reconnect. AsyncConnectionPool handles this.
    db_uri = _get_db_uri()
    async with AsyncConnectionPool(
        conninfo=db_uri,
        min_size=2,
        max_size=10,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    ) as cp_pool:
        await cp_pool.open()
        _checkpointer = AsyncPostgresSaver(conn=cp_pool)
        await _checkpointer.setup()
        logger.info("[CHECKPOINTER] AsyncPostgresSaver initialized (pool mode)")

        # Build and compile the supervisor graph with checkpointer
        supervisor = build_supervisor_graph()
        _graph = supervisor.compile(checkpointer=_checkpointer)
        logger.info("[GRAPH] Supervisor graph compiled")

        # Periodic cleanup tasks (every 5 minutes)
        async def _periodic_cleanup():
            while True:
                await asyncio.sleep(300)
                get_limiter().cleanup_stale()
                await cleanup_old_token_usage()
                logger.debug("[CLEANUP] Rate limiter + token usage cleanup done")

        cleanup_task = asyncio.create_task(_periodic_cleanup())

        yield

        logger.info("Shutting down geo_agent...")
        cleanup_task.cancel()
        await app.state.audit_writer.close()
    # Wait for background tasks (title generation etc.) to complete
    if _background_tasks:
        logger.info(f"[SHUTDOWN] Waiting for {len(_background_tasks)} background tasks...")
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    await close_pool()


app = FastAPI(
    title="GEO Agent API",
    description="Agent layer for AnswerX GEO platform — Anthony Chat + Analyze/Action Agents",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount task routers.
# Phase 3A refactor (2026-04-25): tasks.py was split into 6 files. Order matters:
# all routers with non-path-param routes (templates, framework, preselect, strategy)
# MUST be registered BEFORE the export + tasks routers so that paths like
# `/templates`, `/framework/metrics`, `/metrics/list`, `/generate-strategy` match
# before the catch-all `/{task_id}` endpoint in tasks_router.
agent_auth_dependencies = [Depends(require_feature_access_if_present)]
agent_task_auth_dependencies = [Depends(require_feature_or_system_task_job_access)]

app.include_router(templates_router, dependencies=agent_auth_dependencies)         # /templates, /templates/{id}, /workflow-config
app.include_router(framework_router, dependencies=agent_auth_dependencies)         # /framework/*, /metrics/*
app.include_router(content_preselect_router, dependencies=agent_auth_dependencies) # /client-platforms, /prompts/ranked, /topics/ranked, /content/preselect
app.include_router(strategy_router, dependencies=agent_auth_dependencies)          # /generate-strategy
app.include_router(export_router, dependencies=agent_auth_dependencies)            # /{task_id}/export — must precede tasks_router (more specific suffix)
app.include_router(tasks_router, dependencies=agent_task_auth_dependencies)        # core CRUD + scheduled /trigger_cron

# CORS
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enqueue_registered_user_audit(request: Request, call_next):
    """Best-effort server-side audit for registered Agent actions."""
    response = await call_next(request)
    if getattr(request.state, "system_job_auth", False):
        return response
    user = getattr(request.state, "current_user", None)
    policy = getattr(request.state, "audit_policy", None)
    client_id = getattr(request.state, "authorized_client_id", None)
    if user is None or policy is None or not policy.audit or not client_id:
        return response
    route = request.scope.get("route")
    route_template = getattr(route, "path", request.url.path)
    path_params = dict(request.path_params)
    target_key = next(
        (
            key
            for key in ("task_id", "thread_id", "template_id")
            if path_params.get(key)
        ),
        None,
    )
    app.state.audit_writer.enqueue(
        {
            "user_id": user.id,
            "client_id": client_id,
            "event_type": "api_action",
            "action_key": (
                f"{getattr(request.state, 'feature_key', 'unknown')}."
                f"{policy.capability}"
            ),
            "route": route_template,
            "method": request.method,
            "status_code": response.status_code,
            "target_type": target_key.removesuffix("_id") if target_key else None,
            "target_id": str(path_params[target_key]) if target_key else None,
            "metadata": {
                "query_params": sanitize_query_params(
                    request.query_params.multi_items()
                ),
                "source": "server_interceptor",
            },
            "ip_address": request.headers.get("x-forwarded-for", "").split(",", 1)[0] or (
                request.client.host if request.client else None
            ),
            "user_agent": request.headers.get("user-agent"),
        }
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    logger.debug(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": True, "message": "Internal server error", "path": str(request.url.path)},
    )


# ─────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    client_id: str
    user_id: str
    thread_id: Optional[str] = None  # Auto-generated if not provided
    entry_point: Optional[str] = None  # "content" | "analysis" | "chat" | None
    model_override: Optional[str] = None  # "pro" | "flash" | None (auto)


class HITLRequest(BaseModel):
    thread_id: str
    client_id: str
    user_id: str
    approved: bool
    feedback: Optional[str] = None  # Required when approved=False


# ─── Response models (Phase 4 sweep #2 — main.py endpoints) ────────────────
# Added 2026-04-26 after the routers/ sweep to close the OpenAPI codegen gap
# for the agent service. SSE streaming endpoints (chat, action/review) and
# the HTML export endpoint stay unannotated — see comments at each decorator.


class StatusOkOut(BaseModel):
    """Generic ack response used by several mutation endpoints."""
    ok: bool


class HealthOut(BaseModel):
    status: str
    service: str


class SessionListItem(BaseModel):
    """One row from ``GET /api/agent/sessions``."""
    thread_id: str
    title: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SessionMessageItem(BaseModel):
    """One row from ``GET /api/agent/sessions/{thread_id}/messages``.

    ``tool_results`` is parsed JSONB — its inner shape varies by tool
    (chart payloads, NL2SQL plans, widget definitions, etc.) so we keep
    it loosely typed at this boundary. The frontend has its own
    type-narrowing for each tool.
    """
    role: Optional[str] = None
    content: Optional[str] = None
    tool_results: Optional[list[dict]] = None
    created_at: Optional[datetime] = None


class SessionRenameOut(BaseModel):
    ok: bool
    title: str


class ContextUsage(BaseModel):
    tokens_used: int
    tokens_max: int
    turns: int
    compressed: bool
    percentage: float


class CompressOut(BaseModel):
    """Dual-shape: ``compressed=True`` carries ``context_usage``;
    ``compressed=False`` carries ``reason``. Both branches share ``ok``.
    """
    ok: bool
    compressed: bool
    context_usage: Optional[ContextUsage] = None
    reason: Optional[str] = None


class ToolbarModelInfo(BaseModel):
    id: Optional[str] = None
    tier: str
    label: str


class ToolbarModelsBlock(BaseModel):
    available: list[ToolbarModelInfo]


class ToolbarStatusOut(BaseModel):
    """Aggregate toolbar payload returned by ``GET /api/agent/toolbar/status``.

    ``quota`` carries the daily-quota nested dict from
    ``get_quota_status`` — its shape can evolve with rate-limiter changes,
    so we keep it as ``dict[str, Any]`` to avoid forcing a model migration
    every time a token-usage field is added. See
    ``middleware/rate_limiter.get_quota_status``.
    """
    quota: dict
    memory_count: int
    models: ToolbarModelsBlock
    context_usage: ContextUsage


class MemoryItem(BaseModel):
    """One row from ``GET /api/agent/memories/list``."""
    id: str
    memory_type: Optional[str] = None
    content: Optional[str] = None
    shared: Optional[bool] = None
    created_at: Optional[datetime] = None


class BrandProfileOut(BaseModel):
    """Output of ``GET /api/agent/brand-profile``.

    All fields are nullable: when no row exists for the client we return
    a stub with ``brand_name=None`` + empty list defaults rather than 404,
    so the frontend can render the empty-state form without an extra call.
    """
    brand_name: Optional[str] = None
    tone_of_voice: Optional[str] = None
    target_audience: Optional[str] = None
    key_messages: list[str] = []
    brand_values: list[str] = []
    language: Optional[str] = None
    updated_at: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────
# SSE Chat Endpoint
# ─────────────────────────────────────────────────────────────

# Streaming response — response_model= incompatible with StreamingResponse.
@app.post("/api/agent/chat")
async def agent_chat(
    data: ChatRequest,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
):
    """
    Main chat endpoint. Streams SSE events as the agent processes.

    SSE event types:
    - {"type": "intent", "value": "analyze|action|chat"}
    - {"type": "tool_start", "name": "...", "args": {...}}
    - {"type": "tool_result", "name": "...", "status": "done"}
    - {"type": "chart", "data": {...}}
    - {"type": "token", "text": "..."}
    - {"type": "done", "thread_id": "..."}
    - {"type": "error", "message": "..."}
    """
    data.user_id = user_identifier(current_user)

    # Rate limit check (per-user, dual: frequency + token)
    allowed, rl_info = await check_rate_limit(data.client_id, data.user_id)
    if not allowed:
        reason = rl_info.get("reason", "request_frequency")
        if reason == "daily_token_quota_exceeded":
            quota_info = rl_info.get("daily_quota", {})
            reset_at = quota_info.get("reset_at", "明日")
            msg = (
                f"😊 您今日的对话额度已用完（已使用 {quota_info.get('used', 0):,} / "
                f"{quota_info.get('limit', 0):,} tokens）。\n\n"
                f"额度将于 **{reset_at}** (UTC) 自动重置。"
                f"如需更多额度，请联系 AnswerX 团队。"
            )
        else:
            msg = "请求过于频繁，请稍等几秒再试。"

        # Return 200 with SSE so the message appears in chat naturally
        async def quota_stream():
            yield _sse({"type": "token", "text": msg})
            yield _sse({
                "type": "done",
                "thread_id": data.thread_id or "",
                "daily_quota": rl_info.get("daily_quota"),
            })

        return StreamingResponse(
            quota_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    thread_id = data.thread_id or f"{data.client_id}:{uuid.uuid4().hex[:12]}"

    async def event_stream():
        lifecycle_conn = None
        lifecycle_acquired = False
        lifecycle_slot_reserved = False
        try:
            await reserve_workspace_lifecycle_slot()
            lifecycle_slot_reserved = True
            pool = await get_pool()
            # Hold one session-scoped shared lifecycle fence across the full
            # graph stream. This also fences LangGraph's library-owned
            # checkpoint writes, which use a separate psycopg pool.
            lifecycle_conn = await pool.acquire()
            await acquire_workspace_lifecycle_session_shared(
                lifecycle_conn,
                data.client_id,
            )
            lifecycle_acquired = True

            # Upsert session + persist human message BEFORE streaming starts.
            # This way the conversation survives page refresh/close during streaming.
            initial_title = data.message[:80] + ("..." if len(data.message) > 80 else "")
            await _upsert_session(pool, thread_id, data.client_id, data.user_id, data.message)
            await _save_message(pool, thread_id, "human", data.message)

            # Tell frontend about the session immediately so sidebar updates
            yield _sse({
                "type": "session_created",
                "thread_id": thread_id,
                "title": initial_title,
            })

            # ── Export intent detection (pre-graph shortcut) ──────────
            # If user asks to export analysis, bypass graph and trigger export directly.
            # This works regardless of which sub-graph the Supervisor would route to.
            if _is_export_intent(data.message):
                from tools.export_tools import aggregate_chat_analysis
                agg = await aggregate_chat_analysis(thread_id, data.client_id)
                if agg["has_content"]:
                    export_msg = (
                        f"好的，已为您整理本次对话中的分析内容。"
                        f"共 {agg['turn_count']} 轮分析"
                        + (f"，{agg['chart_count']} 个图表" if agg["chart_count"] else "")
                        + "。\n\n请点击下方按钮下载 HTML 报告。"
                    )
                    await _save_message(pool, thread_id, "ai", export_msg)
                    # Stream the response text with typewriter effect
                    for ci in range(0, len(export_msg), 6):
                        yield _sse({"type": "token", "text": export_msg[ci:ci + 6]})
                        await asyncio.sleep(0.015)
                    # Emit export_ready event for frontend download button
                    yield _sse({
                        "type": "export_ready",
                        "thread_id": thread_id,
                        "turn_count": agg["turn_count"],
                        "chart_count": agg["chart_count"],
                    })
                    yield _sse({"type": "done", "thread_id": thread_id})
                    return
                # else: no analysis content, fall through to normal graph flow

            # Load client context at API boundary
            client_name, brand_profile = await _load_client_context(pool, data.client_id)

            # Configure LangGraph invocation
            config = {"configurable": {"thread_id": thread_id}}

            # On subsequent turns (checkpoint exists), only pass the new message.
            # Passing full state with empty defaults (task_inputs={}, intent="")
            # would OVERWRITE accumulated slot-fill inputs and routing decisions.
            existing_checkpoint = await _graph.aget_state(config)
            is_continuation = (
                existing_checkpoint
                and existing_checkpoint.values
                and existing_checkpoint.values.get("messages")
            )

            if is_continuation:
                # Continuation: only new message + widgets reset (per-turn)
                input_state = {
                    "messages": [HumanMessage(content=data.message)],
                    "widgets": [],
                }
                # Always refresh entry_point (allows frontend to enforce intent scope)
                if data.entry_point:
                    input_state["entry_point"] = data.entry_point
            else:
                # First turn: load memories, profile, and system context
                memories = await load_memories(data.client_id, data.user_id)
                memory_context = build_memory_context(memories)
                profile_md = await load_profile(data.client_id, data.user_id)
                profile_context = build_profile_context(profile_md)
                system_context = await get_system_context(data.client_id)

                # Cold-start: if user hasn't been onboarded, add interview instructions
                onboarded = await is_onboarded(data.client_id, data.user_id)
                cold_start = "" if onboarded else COLD_START_INSTRUCTION

                # Inject all context into brand_profile for system prompt
                extra_context = "\n\n".join(filter(None, [
                    system_context, profile_context, memory_context, cold_start,
                ]))
                if extra_context:
                    if brand_profile is not None:
                        brand_profile["_memory_context"] = extra_context
                    else:
                        brand_profile = {"_memory_context": extra_context}

                # First turn: initialize all fields
                input_state = {
                    "messages": [HumanMessage(content=data.message)],
                    "client_id": data.client_id,
                    "thread_id": thread_id,
                    "client_name": client_name,
                    "brand_profile": brand_profile,
                    "intent": "",
                    "entry_point": data.entry_point or "",
                    "widgets": [],
                    # Analyze Agent fields (NL2SQL + slot-filling)
                    "nl2sql_plan": {},
                    "query_results": [],
                    "query_sql": "",
                    "charts": [],
                    "insights": "",
                    "_mode": "",
                    # Action Agent fields (slot-filling)
                    "content_type": "",
                    "action_topic": "",
                    "task_inputs": {},
                    "task_ready": False,
                    "task_id": None,
                }

            # Start token tracking for this request (accumulated via contextvars)
            start_token_tracking()

            # Stream graph execution with thinking steps, widgets, and charts
            thinking_steps: list[dict] = []
            streamed_widgets: list[dict] = []
            streamed_charts: list[dict] = []

            # Map node names to tier labels for thinking panel
            TIER_MAP = {
                "classify": {"tier": 4, "label": "Supervisor 路由"},
                "nl2sql_generator": {"tier": 3, "label": "NL2SQL 生成"},
                "query_executor": {"tier": 1, "label": "SQL 查询执行"},
                "chart_builder": {"tier": 2, "label": "图表生成"},
                "synthesizer": {"tier": 2, "label": "上下文感知分析"},
                "chat": {"tier": 2, "label": "上下文感知对话"},
                "intent_router": {"tier": 4, "label": "分析模式判断"},
                "opportunity_slot_filler": {"tier": 3, "label": "优化机会发现配置"},
                "analysis_slot_filler": {"tier": 3, "label": "分析任务配置"},
                "action_planner": {"tier": 3, "label": "内容生成规划"},
                "generator": {"tier": 3, "label": "内容生成工作流"},
                "off_topic": {"tier": 4, "label": "域限制拦截"},
                "system_command": {"tier": 4, "label": "系统命令"},
            }

            async for namespace, event in _graph.astream(input_state, config, stream_mode="updates", subgraphs=True):
                for node_name, node_output in event.items():
                    # With subgraphs=True, events are emitted at both subgraph
                    # and parent level.  Only process parent-level for "classify"
                    # and "off_topic" — everything else runs inside subgraphs.
                    if not namespace and node_name not in ("classify", "off_topic", "system_command"):
                        continue

                    tier_info = TIER_MAP.get(node_name)

                    # Widget events — any node can push interactive cards for slot-filling
                    if "widgets" in node_output and node_output["widgets"]:
                        for w in node_output["widgets"]:
                            streamed_widgets.append(w)
                            yield _sse({"type": "widget", **w})

                    # Intent classified
                    if node_name == "classify" and "intent" in node_output:
                        intent = node_output["intent"]
                        yield _sse({"type": "intent", "value": intent})
                        step = {
                            "node": "classify",
                            "tier": 4,
                            "label": "Supervisor 路由",
                            "detail": f"意图识别: {intent}",
                        }
                        thinking_steps.append(step)
                        yield _sse({"type": "thinking", "step": step})

                    # NL2SQL generator produced SQL plan
                    elif node_name == "nl2sql_generator" and "nl2sql_plan" in node_output:
                        plan = node_output["nl2sql_plan"]
                        step = {
                            "node": "nl2sql_generator",
                            "tier": 3,
                            "label": "NL2SQL 生成",
                            "detail": plan.get("explanation", "SQL 已生成"),
                            "sql": plan.get("sql", ""),
                        }
                        thinking_steps.append(step)
                        yield _sse({"type": "thinking", "step": step})

                    # Query executor completed
                    elif node_name == "query_executor" and "query_results" in node_output:
                        rows = node_output.get("query_results", [])
                        sql = node_output.get("query_sql", "")
                        step = {
                            "node": "query_executor",
                            "tier": 1,
                            "label": "SQL 查询执行",
                            "detail": f"返回 {len(rows)} 行数据",
                        }
                        if sql:
                            step["sql"] = sql
                        thinking_steps.append(step)
                        yield _sse({"type": "thinking", "step": step})

                    # Chart builder produced charts
                    elif node_name == "chart_builder" and "charts" in node_output:
                        for chart in node_output["charts"]:
                            streamed_charts.append(chart)
                            yield _sse({"type": "chart", "data": chart})
                        if node_output["charts"]:
                            step = {
                                "node": "chart_builder",
                                "tier": 2,
                                "label": "图表生成",
                                "detail": f"生成 {len(node_output['charts'])} 个图表",
                            }
                            thinking_steps.append(step)
                            yield _sse({"type": "thinking", "step": step})

                    # Analyze Agent: slot-fillers emit task_ready when guided config done
                    elif node_name in ("opportunity_slot_filler", "analysis_slot_filler") and node_output.get("task_ready"):
                        raw_inputs = node_output.get("task_inputs", {})
                        # Strip internal bookkeeping keys (prefixed with "_") from
                        # the inputs payload — except _summary_display, which
                        # carries the translated Chinese-label rows the frontend
                        # ChatTaskCard renders. The frontend treats it as a
                        # presentation-layer hint and never sends it back to the
                        # backend on task creation.
                        # Strip internal bookkeeping (`_*`) and project chat
                        # schema keys (`default_*`) to plain pipeline keys
                        # AT THE BOUNDARY. LangGraph state intentionally
                        # keeps `default_*` so the LLM's slot-fill prompt
                        # (whose step_specs reference field keys) stays in
                        # sync. The plain-key projection happens here so DB
                        # `geo_agent_tasks.inputs` and downstream pipelines
                        # see one shape regardless of chat vs wizard origin.
                        task_inputs = {k: v for k, v in raw_inputs.items() if not k.startswith("_")}
                        from services.workflow_config import normalize_chat_inputs_to_pipeline_shape
                        task_inputs = normalize_chat_inputs_to_pipeline_shape(task_inputs)
                        summary_display = raw_inputs.get("_summary_display") or []
                        # Determine task_type: opportunity flow uses "opportunity_discovery", analysis uses "analysis"
                        emit_task_type = "opportunity_discovery" if node_name == "opportunity_slot_filler" else "analysis"
                        # IMPORTANT — order:
                        #   1) thinking step (informational)
                        #   2) message tokens stream (frontend appends into the
                        #      currently-streaming assistant message)
                        #   3) task_ready (frontend marks streaming=false and
                        #      pushes a new role:"task_card" message)
                        # Reversing this drops trailing tokens — `task_ready`
                        # finalizes the streaming bubble, so subsequent token
                        # events have nowhere to land.
                        label = "优化机会发现任务准备就绪" if node_name == "opportunity_slot_filler" else "分析任务准备就绪"
                        step = {
                            "node": node_name,
                            "tier": 3,
                            "label": label,
                            "detail": f"收集完成: 维度 {', '.join(task_inputs.get('domains', []))}",
                        }
                        thinking_steps.append(step)
                        yield _sse({"type": "thinking", "step": step})
                        if "messages" in node_output:
                            for msg in node_output["messages"]:
                                if hasattr(msg, "content") and msg.content:
                                    text = msg.content
                                    chunk_size = 6
                                    for ci in range(0, len(text), chunk_size):
                                        yield _sse({"type": "token", "text": text[ci:ci + chunk_size]})
                                        await asyncio.sleep(0.015)
                        yield _sse({
                            "type": "task_ready",
                            "task_type": emit_task_type,
                            "inputs": task_inputs,
                            "summary_display": summary_display,
                        })

                    # Action Agent: planner emits task_ready when slots filled
                    elif node_name == "action_planner" and node_output.get("task_ready"):
                        raw_inputs = node_output.get("task_inputs", {})
                        # Same boundary normalization as analysis branch
                        # (see comment there).
                        task_inputs = {k: v for k, v in raw_inputs.items() if not k.startswith("_")}
                        from services.workflow_config import normalize_chat_inputs_to_pipeline_shape
                        task_inputs = normalize_chat_inputs_to_pipeline_shape(task_inputs)
                        summary_display = raw_inputs.get("_summary_display") or []
                        # Same ordering rule as the analyze branch above:
                        # thinking → tokens → task_ready. See the comment there
                        # for the rationale.
                        step = {
                            "node": "action_planner",
                            "tier": 3,
                            "label": "内容任务准备就绪",
                            "detail": f"收集完成: {task_inputs.get('content_type', '')}",
                        }
                        thinking_steps.append(step)
                        yield _sse({"type": "thinking", "step": step})
                        if "messages" in node_output:
                            for msg in node_output["messages"]:
                                if hasattr(msg, "content") and msg.content:
                                    text = msg.content
                                    chunk_size = 6
                                    for ci in range(0, len(text), chunk_size):
                                        yield _sse({"type": "token", "text": text[ci:ci + chunk_size]})
                                        await asyncio.sleep(0.015)
                        yield _sse({
                            "type": "task_ready",
                            "task_type": "content_generation",
                            "inputs": task_inputs,
                            "summary_display": summary_display,
                        })

                    # Synthesizer, chat, or action_planner produced final answer
                    elif "messages" in node_output:
                        if tier_info:
                            step = {
                                "node": node_name,
                                "tier": tier_info["tier"],
                                "label": tier_info["label"],
                                "detail": "生成回答中...",
                            }
                            thinking_steps.append(step)
                            yield _sse({"type": "thinking", "step": step})

                        for msg in node_output["messages"]:
                            if hasattr(msg, "content") and msg.content:
                                # Stream in chunks for typewriter effect
                                text = msg.content
                                chunk_size = 6
                                for ci in range(0, len(text), chunk_size):
                                    yield _sse({"type": "token", "text": text[ci:ci + chunk_size]})
                                    await asyncio.sleep(0.015)

            # ── Post-stream: persist + title gen (parallelized) ──
            final_state = await _graph.aget_state(config)

            ai_messages = [
                m for m in final_state.values.get("messages", [])
                if hasattr(m, "type") and m.type == "ai"
            ]
            title_task = None
            if ai_messages:
                last_ai = ai_messages[-1]
                # Use charts captured during streaming — AnalyzeState.charts
                # doesn't propagate to SupervisorState after sub-graph completes
                charts = streamed_charts

                # Fire title generation immediately — runs in parallel with DB writes
                title_task = asyncio.create_task(
                    _generate_session_title(pool, thread_id, data.message, last_ai.content)
                )
                _background_tasks.add(title_task)
                title_task.add_done_callback(_background_tasks.discard)

                # Persist AI message (human already saved before streaming)
                await _save_message(
                    pool, thread_id, "ai", last_ai.content,
                    charts, thinking_steps if thinking_steps else None,
                    streamed_widgets if streamed_widgets else None,
                )

            # Calculate context usage for frontend indicator
            all_messages = final_state.values.get("messages", [])
            ctx_usage = get_context_usage(all_messages)

            # Collect precise token usage from Gemini usage_metadata
            token_usage = get_tracked_tokens()
            if token_usage:
                ctx_usage["request_tokens"] = {
                    "input": token_usage["input"],
                    "output": token_usage["output"],
                    "total": token_usage["input"] + token_usage["output"],
                }
                # Log to DB for quota tracking (fire-and-forget)
                usage_task = asyncio.create_task(
                    _log_token_usage(
                        data.client_id, data.user_id, thread_id,
                        token_usage["input"], token_usage["output"],
                        data.entry_point or "chat",
                        model_id=data.model_override or "auto",
                    )
                )
                _background_tasks.add(usage_task)
                usage_task.add_done_callback(_background_tasks.discard)

            # Gather toolbar data for done event (avoids frontend polling)
            try:
                mem_count = await get_memory_count(data.client_id, data.user_id)
                daily_q = await get_quota_status(data.client_id, data.user_id)
            except Exception:
                mem_count = 0
                daily_q = {}

            # Send done with all toolbar data — frontend unblocks here
            yield _sse({
                "type": "done",
                "thread_id": thread_id,
                "context_usage": ctx_usage,
                "memory_count": mem_count,
                "daily_quota": daily_q.get("daily_quota", {}),
            })

            # Title gen is already running; await it and push the result.
            # Stream is still open but the frontend UI is already unblocked.
            if title_task is not None:
                title = await title_task
                if title:
                    yield _sse({"type": "session_title", "thread_id": thread_id, "title": title})

            # Trigger context compression in background (next turn will use compressed context)
            if await should_compress(all_messages):
                compress_task = asyncio.create_task(
                    _compress_context(config, all_messages, data.client_id)
                )
                _background_tasks.add(compress_task)
                compress_task.add_done_callback(_background_tasks.discard)

            # Evaluate user message for memory/profile updates (per-message, async)
            memory_task = asyncio.create_task(
                _evaluate_memory(data.message, data.client_id, data.user_id)
            )
            _background_tasks.add(memory_task)
            memory_task.add_done_callback(_background_tasks.discard)

        except Exception as e:
            logger.error(f"[CHAT] Stream error: {e}")
            logger.error(traceback.format_exc())
            yield _sse({"type": "error", "message": str(e)})
        finally:
            try:
                if lifecycle_conn is not None:
                    try:
                        if lifecycle_acquired:
                            await release_workspace_lifecycle_session_shared(
                                lifecycle_conn,
                                data.client_id,
                            )
                    finally:
                        await pool.release(lifecycle_conn)
            finally:
                if lifecycle_slot_reserved:
                    release_workspace_lifecycle_slot()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────
# Session Management Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/api/agent/sessions", response_model=list[SessionListItem])
async def list_sessions(
    client_id: str,
    user_id: str,
    limit: int = 20,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> list[SessionListItem]:
    """List chat sessions for a user within a client workspace, most recent first."""
    user_id = user_identifier(current_user)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT thread_id, title, created_at, updated_at
        FROM agent_sessions
        WHERE client_id = $1 AND user_id = $2
        ORDER BY updated_at DESC
        LIMIT $3
        """,
        client_id, user_id, limit,
    )
    return [SessionListItem(**dict(r)) for r in rows]


@app.get(
    "/api/agent/sessions/{thread_id}/messages",
    response_model=list[SessionMessageItem],
)
async def get_session_messages(
    thread_id: str,
    client_id: str,
    user_id: str,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> list[SessionMessageItem]:
    """Get message history for a session."""
    user_id = user_identifier(current_user)
    pool = await get_pool()

    # Verify session belongs to this user + client
    session = await pool.fetchrow(
        "SELECT client_id, user_id FROM agent_sessions WHERE thread_id = $1",
        thread_id,
    )
    if not session or str(session["client_id"]) != client_id or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    rows = await pool.fetch(
        """
        SELECT role, content, tool_results, created_at
        FROM agent_messages
        WHERE thread_id = $1
        ORDER BY created_at ASC
        """,
        thread_id,
    )
    result = []
    for r in rows:
        d = dict(r)
        # asyncpg returns JSONB as raw string — parse to object for frontend
        if d.get("tool_results") and isinstance(d["tool_results"], str):
            try:
                d["tool_results"] = json.loads(d["tool_results"])
            except (json.JSONDecodeError, TypeError):
                d["tool_results"] = None
        result.append(SessionMessageItem(**d))
    return result


@app.delete("/api/agent/sessions/{thread_id}", response_model=StatusOkOut)
async def delete_session(
    thread_id: str,
    client_id: str,
    user_id: str,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> StatusOkOut:
    """Delete a chat session and its messages."""
    user_id = user_identifier(current_user)
    pool = await get_pool()
    session = await pool.fetchrow(
        "SELECT client_id, user_id FROM agent_sessions WHERE thread_id = $1",
        thread_id,
    )
    if not session or str(session["client_id"]) != client_id or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    # CASCADE will delete agent_messages automatically
    async def delete_operation(conn):
        await conn.execute("DELETE FROM agent_sessions WHERE thread_id = $1", thread_id)

    await WorkspaceWriteCoordinator(pool).execute(client_id, delete_operation)
    return StatusOkOut(ok=True)


class RenameSessionRequest(BaseModel):
    client_id: str
    user_id: str
    title: str


@app.put("/api/agent/sessions/{thread_id}", response_model=SessionRenameOut)
async def rename_session(
    thread_id: str,
    data: RenameSessionRequest,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> SessionRenameOut:
    """Rename a chat session title."""
    data.user_id = user_identifier(current_user)
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    pool = await get_pool()
    session = await pool.fetchrow(
        "SELECT client_id, user_id FROM agent_sessions WHERE thread_id = $1",
        thread_id,
    )
    if not session or str(session["client_id"]) != data.client_id or session["user_id"] != data.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    async def rename_operation(conn):
        await conn.execute(
            "UPDATE agent_sessions SET title = $1, updated_at = NOW() WHERE thread_id = $2",
            title, thread_id,
        )

    await WorkspaceWriteCoordinator(pool).execute(data.client_id, rename_operation)
    return SessionRenameOut(ok=True, title=title)


# ─────────────────────────────────────────────────────────────
# Chat Export Endpoint
# ─────────────────────────────────────────────────────────────

# Non-JSON response — response_model= n/a (returns HTMLResponse).
@app.get("/api/agent/chat/{thread_id}/export")
async def export_chat_analysis(
    thread_id: str,
    client_id: str,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
):
    """Export analysis insights and charts from a chat session as styled HTML."""
    from tools.export_tools import render_chat_analysis_html

    pool = await get_pool()
    session = await pool.fetchrow(
        "SELECT client_id FROM agent_sessions WHERE thread_id = $1",
        thread_id,
    )
    if not session or str(session["client_id"]) != client_id:
        raise HTTPException(status_code=404, detail="Session not found")

    html = await render_chat_analysis_html(thread_id, client_id)
    if not html:
        raise HTTPException(status_code=400, detail="No analysis content to export")

    return HTMLResponse(content=html, headers={
        "Content-Disposition": f'attachment; filename="chat-analysis-{thread_id[:8]}.html"',
    })


# ─────────────────────────────────────────────────────────────
# HITL (Human-in-the-Loop) Endpoint
# ─────────────────────────────────────────────────────────────

# Streaming response — response_model= incompatible with StreamingResponse.
@app.post("/api/agent/action/review")
async def action_review(
    data: HITLRequest,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
):
    """Resume an interrupted Action Agent graph after HITL review.

    Streams SSE events as the graph continues (either finalizing
    approved content or regenerating with feedback).

    SSE events:
    - {"type": "token", "text": "..."}         — approval confirmation or new draft
    - {"type": "draft_content", "data": {...}} — regenerated content (if not approved)
    - {"type": "hitl_pending", "thread_id": ...} — new HITL pause (on regeneration)
    - {"type": "done", "thread_id": "..."}
    """
    data.user_id = user_identifier(current_user)

    # Rate limit check (HITL resumptions also count against the limit)
    allowed, rl_info = await check_rate_limit(data.client_id, data.user_id)
    if not allowed:
        reason = rl_info.get("reason", "request_frequency")
        if reason == "daily_token_quota_exceeded":
            quota_info = rl_info.get("daily_quota", {})
            msg = (
                f"😊 您今日的对话额度已用完（已使用 {quota_info.get('used', 0):,} / "
                f"{quota_info.get('limit', 0):,} tokens）。\n\n"
                f"额度将于明日 (UTC 00:00) 自动重置。如需更多额度，请联系 AnswerX 团队。"
            )
        else:
            msg = "请求过于频繁，请稍等几秒再试。"

        async def quota_stream():
            yield _sse({"type": "token", "text": msg})
            yield _sse({"type": "done", "thread_id": data.thread_id, "daily_quota": rl_info.get("daily_quota")})

        return StreamingResponse(
            quota_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Verify session ownership before touching graph state
    pool = await get_pool()
    session = await pool.fetchrow(
        "SELECT client_id, user_id FROM agent_sessions WHERE thread_id = $1",
        data.thread_id,
    )
    if not session or str(session["client_id"]) != data.client_id or session["user_id"] != data.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_stream():
        lifecycle_conn = None
        lifecycle_acquired = False
        lifecycle_slot_reserved = False
        try:
            await reserve_workspace_lifecycle_slot()
            lifecycle_slot_reserved = True
            lifecycle_pool = await get_pool()
            lifecycle_conn = await lifecycle_pool.acquire()
            await acquire_workspace_lifecycle_session_shared(
                lifecycle_conn,
                data.client_id,
            )
            lifecycle_acquired = True
            config = {"configurable": {"thread_id": data.thread_id}}

            # Update the graph state with HITL decision
            await _graph.aupdate_state(
                config,
                {
                    "approved": data.approved,
                    "regenerate_feedback": data.feedback or "",
                },
            )

            # Resume graph execution
            async for event in _graph.astream(None, config, stream_mode="updates"):
                for node_name, node_output in event.items():
                    if node_name == "generator" and "draft_content" in node_output:
                        yield _sse({"type": "draft_content", "data": node_output["draft_content"]})

                    if "messages" in node_output:
                        for msg in node_output["messages"]:
                            if hasattr(msg, "content") and msg.content:
                                text = msg.content
                                chunk_size = 6
                                for ci in range(0, len(text), chunk_size):
                                    yield _sse({"type": "token", "text": text[ci:ci + chunk_size]})
                                    await asyncio.sleep(0.015)

            # Check if graph is interrupted again (regeneration creates new HITL pause)
            final_state = await _graph.aget_state(config)
            if final_state.next:
                yield _sse({"type": "hitl_pending", "thread_id": data.thread_id})
            else:
                # Persist final messages
                pool = await get_pool()
                ai_messages = [
                    m for m in final_state.values.get("messages", [])
                    if hasattr(m, "type") and m.type == "ai"
                ]
                if ai_messages:
                    draft = final_state.values.get("draft_content", {})
                    tool_data = None
                    if draft:
                        tool_data = [{"type": "draft_content", "data": draft}]
                    await _save_message(
                        pool, data.thread_id, "ai",
                        ai_messages[-1].content,
                        tool_data,
                    )

            yield _sse({"type": "done", "thread_id": data.thread_id})

        except Exception as e:
            logger.error(f"[HITL] Review error: {e}")
            logger.error(traceback.format_exc())
            yield _sse({"type": "error", "message": str(e)})
        finally:
            try:
                if lifecycle_conn is not None:
                    try:
                        if lifecycle_acquired:
                            await release_workspace_lifecycle_session_shared(
                                lifecycle_conn,
                                data.client_id,
                            )
                    finally:
                        await lifecycle_pool.release(lifecycle_conn)
            finally:
                if lifecycle_slot_reserved:
                    release_workspace_lifecycle_slot()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────
# Context Compression Endpoint
# ─────────────────────────────────────────────────────────────

class CompressRequest(BaseModel):
    thread_id: str
    client_id: str
    user_id: str


@app.post("/api/agent/chat/compress", response_model=CompressOut)
async def manual_compress(
    data: CompressRequest,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> CompressOut:
    """Manually trigger context compression for a conversation."""
    data.user_id = user_identifier(current_user)
    # Quota check — compression calls LLM
    allowed, rl_info = await check_rate_limit(data.client_id, data.user_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="配额已用尽，无法压缩。")

    pool = await get_pool()
    session = await pool.fetchrow(
        "SELECT client_id, user_id FROM agent_sessions WHERE thread_id = $1",
        data.thread_id,
    )
    if not session or str(session["client_id"]) != data.client_id or session["user_id"] != data.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    async with agent_workspace_lifecycle_session(data.client_id):
        config = {"configurable": {"thread_id": data.thread_id}}
        state = await _graph.aget_state(config)
        if not state or not state.values.get("messages"):
            raise HTTPException(status_code=400, detail="No messages to compress")

        messages = state.values["messages"]
        compressed = await compress_messages(messages)

        if len(compressed) < len(messages):
            # Update the checkpoint with compressed messages while the full
            # workflow lifecycle fence covers the library-owned write.
            await _graph.aupdate_state(config, {"messages": compressed})
            ctx_usage = get_context_usage(compressed)
            return CompressOut(
                ok=True, compressed=True, context_usage=ContextUsage(**ctx_usage)
            )

    return CompressOut(
        ok=True, compressed=False, reason="Below compression threshold"
    )


# ─────────────────────────────────────────────────────────────
# Toolbar Status API
# ─────────────────────────────────────────────────────────────

@app.get("/api/agent/toolbar/status", response_model=ToolbarStatusOut)
async def toolbar_status(
    client_id: str,
    user_id: str,
    thread_id: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> ToolbarStatusOut:
    """Get all toolbar indicators in one call: quota, memory count, models, context."""
    user_id = user_identifier(current_user)
    pool = await get_pool()

    # Quota status (frequency + token)
    quota = await get_quota_status(client_id, user_id)

    # Memory count
    mem_row = await pool.fetchrow(
        """SELECT COUNT(*) AS cnt FROM agent_memories
           WHERE client_id = $1::uuid AND (user_identifier = $2 OR shared = true)""",
        client_id, user_id,
    )
    memory_count = int(mem_row["cnt"]) if mem_row else 0

    # Available models (from global settings)
    from llm.client import get_model_id
    flash_model = await get_model_id("flash")
    pro_model = await get_model_id("pro")

    # Context usage (default 0% for new conversations)
    context_usage = {
        "tokens_used": 0,
        "tokens_max": 1_000_000,
        "turns": 0,
        "compressed": False,
        "percentage": 0,
    }
    if thread_id and _graph:
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state = await _graph.aget_state(config)
            if state and state.values and state.values.get("messages"):
                context_usage = get_context_usage(state.values["messages"])
        except Exception:
            pass

    return ToolbarStatusOut(
        quota=quota,
        memory_count=memory_count,
        models=ToolbarModelsBlock(
            available=[
                ToolbarModelInfo(id=flash_model, tier="flash", label="Flash"),
                ToolbarModelInfo(id=pro_model, tier="pro", label="Pro"),
            ],
        ),
        context_usage=ContextUsage(**context_usage),
    )


@app.get("/api/agent/memories/list", response_model=list[MemoryItem])
async def list_user_memories(
    client_id: str,
    user_id: str,
    limit: int = 20,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> list[MemoryItem]:
    """List memories for a user (including shared). For toolbar popover."""
    user_id = user_identifier(current_user)
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, memory_type, content, shared, created_at
           FROM agent_memories
           WHERE client_id = $1::uuid AND (user_identifier = $2 OR shared = true)
           ORDER BY updated_at DESC LIMIT $3""",
        client_id, user_id, limit,
    )
    return [MemoryItem(**dict(r)) for r in rows]


@app.get("/health", response_model=HealthOut)
def health_check() -> HealthOut:
    return HealthOut(status="ok", service="geo_agent")


# ─────────────────────────────────────────────────────────────
# Brand Profile CRUD
# ─────────────────────────────────────────────────────────────

class BrandProfileUpdate(BaseModel):
    brand_name: Optional[str] = None
    tone_of_voice: Optional[str] = None
    target_audience: Optional[str] = None
    key_messages: Optional[list[str]] = None
    brand_values: Optional[list[str]] = None
    language: Optional[str] = None


@app.get("/api/agent/brand-profile", response_model=BrandProfileOut)
async def get_brand_profile(
    client_id: str,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> BrandProfileOut:
    """Get the brand profile for a client."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT brand_name, tone_of_voice, target_audience,
               key_messages, brand_values, language, updated_at
        FROM geo_brand_profiles
        WHERE client_id = $1::uuid
        """,
        client_id,
    )
    if not row:
        return BrandProfileOut()
    d = dict(row)
    # ``key_messages`` and ``brand_values`` are JSONB columns — asyncpg may
    # return them as JSON strings depending on the codec. Normalize to lists.
    for k in ("key_messages", "brand_values"):
        v = d.get(k)
        if v is None:
            d[k] = []
        elif isinstance(v, str):
            try:
                d[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                d[k] = []
    return BrandProfileOut(**d)


@app.put("/api/agent/brand-profile", response_model=StatusOkOut)
async def update_brand_profile(
    client_id: str,
    data: BrandProfileUpdate,
    current_user: AuthenticatedUser = Depends(require_feature_access_if_present),
) -> StatusOkOut:
    """Create or update the brand profile for a client."""
    pool = await get_pool()
    km = json.dumps(data.key_messages) if data.key_messages is not None else None
    bv = json.dumps(data.brand_values) if data.brand_values is not None else None

    async def operation(conn):
        await conn.execute(
            """
            INSERT INTO geo_brand_profiles (id, client_id, brand_name, tone_of_voice,
                target_audience, key_messages, brand_values, language, updated_at)
            VALUES (gen_random_uuid(), $1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb, $7, NOW())
            ON CONFLICT (client_id) DO UPDATE SET
                brand_name = COALESCE($2, geo_brand_profiles.brand_name),
                tone_of_voice = COALESCE($3, geo_brand_profiles.tone_of_voice),
                target_audience = COALESCE($4, geo_brand_profiles.target_audience),
                key_messages = COALESCE($5::jsonb, geo_brand_profiles.key_messages),
                brand_values = COALESCE($6::jsonb, geo_brand_profiles.brand_values),
                language = COALESCE($7, geo_brand_profiles.language),
                updated_at = NOW()
            """,
            client_id, data.brand_name, data.tone_of_voice, data.target_audience,
            km, bv, data.language,
        )

    await WorkspaceWriteCoordinator(pool).execute(client_id, operation)
    return StatusOkOut(ok=True)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


import re as _re

# Export intent keywords — matches Chinese phrases for "export analysis/report/HTML"
_EXPORT_PATTERNS = _re.compile(
    r"(导出|生成报告|下载|保存).{0,8}(分析|报告|洞察|insights|HTML|图表|可视化)",
    _re.IGNORECASE,
)


def _is_export_intent(message: str) -> bool:
    """Check if user message is requesting to export chat analysis to HTML."""
    return bool(_EXPORT_PATTERNS.search(message))


async def _log_token_usage(
    client_id: str, user_id: str, thread_id: str,
    tokens_input: int, tokens_output: int, entry_point: str,
    model_id: str = "auto",
) -> None:
    """Log token usage for quota tracking. Best-effort, never raises."""
    try:
        pool = await get_pool()
        async def operation(conn):
            await conn.execute(
                """INSERT INTO agent_token_usage
                   (client_id, user_identifier, tokens_input, tokens_output, model_id, entry_point, thread_id)
                   VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)""",
                client_id, user_id, tokens_input, tokens_output, model_id, entry_point, thread_id,
            )

        await WorkspaceWriteCoordinator(pool).execute(client_id, operation)
        logger.info(
            f"[TOKENS] Logged usage | in={tokens_input} out={tokens_output} "
            f"total={tokens_input + tokens_output} | entry={entry_point}"
        )
    except Exception as e:
        logger.warning(f"[TOKENS] Failed to log usage: {e}")


async def _upsert_session(pool, thread_id: str, client_id: str, user_id: str, first_message: str):
    """Create or update an agent session. Uses truncated message as initial title."""
    title = first_message[:80] + ("..." if len(first_message) > 80 else "")
    await pool.execute(
        """
        INSERT INTO agent_sessions (id, thread_id, client_id, user_id, title, created_at, updated_at)
        VALUES (gen_random_uuid(), $1, $2::uuid, $3, $4, NOW(), NOW())
        ON CONFLICT (thread_id) DO UPDATE SET updated_at = NOW()
        """,
        thread_id, client_id, user_id, title,
    )


async def _generate_session_title(pool, thread_id: str, user_msg: str, ai_msg: str) -> str | None:
    """Use Gemini Flash to generate a concise session title, then update DB.

    Only runs on the first exchange (0 messages saved yet). Returns the
    generated title, or None if skipped/failed.
    """
    try:
        # Guard: only generate title on the first exchange.
        # At this point the human message is already saved (count=1),
        # so <=1 means this is the first exchange.
        msg_count = await pool.fetchval(
            "SELECT COUNT(*) FROM agent_messages WHERE thread_id = $1", thread_id,
        )
        if msg_count > 1:
            return None

        from llm.client import get_model_id, get_genai_client
        from google.genai import types

        model_id = await get_model_id("flash")
        client = await get_genai_client(model_id, role="flash")

        response = await client.aio.models.generate_content(
            model=model_id,
            contents=(
                f"根据以下对话生成一个简短的中文会话标题（8-15字，不加引号，不加标点）。\n"
                f"标题应该概括用户的核心问题，例如：Roborock近30天SOV趋势分析、品牌情感分析对比。\n\n"
                f"用户：{user_msg[:200]}\n"
                f"回复：{ai_msg[:300]}\n\n"
                f"标题："
            ),
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=512,
            ),
        )
        title = (response.text or "").strip().strip('"\'「」【】')[:80]
        if title:
            await pool.execute(
                "UPDATE agent_sessions SET title = $1 WHERE thread_id = $2",
                title, thread_id,
            )
            logger.info(f"[TITLE] Generated title for {thread_id}: {title}")
            return title
    except Exception as e:
        logger.warning(f"[TITLE] Failed to generate title: {e}")
    return None


async def _load_client_context(pool, client_id: str) -> tuple[str, dict | None]:
    """Load client name and brand profile from DB.

    Returns (client_name, brand_profile_dict_or_None).
    """
    client_row = await pool.fetchrow(
        "SELECT name FROM geo_clients WHERE id = $1::uuid", client_id
    )
    client_name = client_row["name"] if client_row else "Unknown"

    bp_row = await pool.fetchrow(
        """
        SELECT brand_name, tone_of_voice, target_audience,
               key_messages, brand_values, language
        FROM geo_brand_profiles
        WHERE client_id = $1::uuid
        """,
        client_id,
    )
    brand_profile = dict(bp_row) if bp_row else None

    return client_name, brand_profile


async def _save_message(
    pool, thread_id: str, role: str, content: str,
    charts: list | None = None, thinking_steps: list | None = None,
    widgets: list | None = None,
):
    """Persist a message to agent_messages.

    tool_results JSONB stores charts, thinking steps, and widgets.
    """
    tool_data: list[dict] = []
    if charts:
        tool_data.extend(charts)
    if thinking_steps:
        tool_data.append({"type": "thinking", "steps": thinking_steps})
    if widgets:
        tool_data.append({"type": "widgets", "items": widgets})
    def _json_default(obj):
        """Handle Decimal, datetime, and other non-serializable types."""
        from decimal import Decimal
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    try:
        tool_results = json.dumps(tool_data, default=_json_default) if tool_data else None
    except Exception as e:
        logger.error(f"[SAVE_MSG] Failed to serialize tool_results: {e}")
        tool_results = None
    await pool.execute(
        """
        INSERT INTO agent_messages (id, thread_id, role, content, tool_results, created_at)
        VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb, NOW())
        """,
        thread_id, role, content, tool_results,
    )


async def _compress_context(config: dict, messages: list, client_id: str):
    """Background task: compress context and update checkpoint."""
    try:
        async with agent_workspace_lifecycle_session(client_id):
            compressed = await compress_messages(messages)
            if len(compressed) < len(messages):
                await _graph.aupdate_state(config, {"messages": compressed})
                logger.info(f"[COMPRESS] Background compression complete | thread={config['configurable']['thread_id']}")
    except Exception as e:
        logger.error(f"[COMPRESS] Background compression failed: {e}")


async def _evaluate_memory(user_message: str, client_id: str, user_identifier: str):
    """Background task: evaluate single user message for memory/profile updates."""
    try:
        async with agent_workspace_lifecycle_session(client_id):
            result = await evaluate_and_update_memory(user_message, client_id, user_identifier)
        logger.info(
            f"[MEMORY] Eval complete | action={result['action']} changed={result['changed']} "
            f"| msg_preview={user_message[:80]!r}"
        )
    except Exception as e:
        logger.error(f"[MEMORY] Evaluation failed: {e}", exc_info=True)
