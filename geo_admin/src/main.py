"""
GEO Admin API (V2)

Internal admin backend for managing GEO Collector pipeline.
Refactored for the Two-Stage Prompt Workflow architecture.

Provides REST API for:
- Global configuration management (settings, platforms, intents)
- Client management (with topics, products, personas)
- Prompts lifecycle (create, trigger, analyze)
- Task & result browsing
- Dashboard statistics
"""
import os
import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from geo_common.audit import AsyncAuditWriter, sanitize_query_params
from geo_common.auth import SessionExpiryAuditor

__import__("sys").path.insert(0, ".") # To ensure routers package is reachable if not already
# v1.2 [2026-04-20]: the legacy Admin-side `brainstorming` router is gone.
# The V1 Admin brainstorming endpoint was superseded by the SaaS-side
# brainstorming router (geo_saas/src/routers/brainstorming.py) and had no
# remaining UI caller.
from pool import close_pool, open_pool
from routers import auth, global_configs, clients, prompts, tasks, stats, analysis, jobs, languages, report_templates, report_runs, brand_profiles, memories, agent_sessions, agent_token_usage, user_profiles, content_framework, analysis_metrics, access_control, feature_access, static_reports
from dependencies.auth import require_admin_or_scheduler_job_access, require_admin_request_access

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("GeoAdmin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection lifecycle — Phase 2.5b unified asyncpg.

    The legacy ``databases`` lib + SQLAlchemy MetaData layer was removed in
    Phase 2.5b. A single ``asyncpg.Pool`` (owned by the ``db.database``
    singleton) backs both raw-SQL routers (via the ``database`` adapter)
    and ``geo_common.services.*Repository`` callsites.
    """
    logger.info("Opening shared asyncpg pool...")
    app.state.pg_pool = await open_pool()
    app.state.audit_writer = AsyncAuditWriter(app.state.pg_pool)
    app.state.audit_writer.start()
    app.state.session_expiry_auditor = SessionExpiryAuditor(
        app.state.pg_pool,
        app.state.audit_writer,
    )
    app.state.session_expiry_auditor.start()
    logger.info("Database pool ready.")
    try:
        yield
    finally:
        await app.state.session_expiry_auditor.close()
        await app.state.audit_writer.close()
        logger.info("Closing shared asyncpg pool...")
        await close_pool(getattr(app.state, "pg_pool", None))
        logger.info("Database pool closed.")


app = FastAPI(
    title="GEO Admin API",
    description="Internal admin API for GEO Platform (V2 - Two-Stage Prompt Workflow)",
    version="2.0.0",
    lifespan=lifespan
)

# CORS — restrict origins in production via ALLOWED_ORIGINS env var
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
async def enqueue_admin_user_audit(request: Request, call_next):
    """Record Admin user mutations without coupling them to business writes."""
    response = await call_next(request)
    if request.url.path.startswith("/api/auth/"):
        return response
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return response
    if getattr(request.state, "system_job_auth", False):
        return response
    user = getattr(request.state, "current_user", None)
    if user is None:
        return response

    route = request.scope.get("route")
    route_template = getattr(route, "path", request.url.path)
    path_params = dict(request.path_params)
    target_key = next(
        (
            key
            for key in (
                "client_id",
                "user_id",
                "brand_id",
                "prompt_id",
                "task_id",
                "package_key",
            )
            if path_params.get(key)
        ),
        None,
    )
    client_id = path_params.get("client_id")
    # The Workspace row no longer exists after the delete response, so using
    # it as a foreign key would make best-effort audit fail.
    if request.method == "DELETE" and route_template == "/api/clients/{client_id}":
        client_id = None

    app.state.audit_writer.enqueue(
        {
            "user_id": user.id,
            "client_id": str(client_id) if client_id else None,
            "event_type": "api_action",
            "action_key": (
                f"admin.{request.method.lower()}."
                f"{route_template.strip('/').replace('/', '.')}"
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


# Unified error response handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return structured JSON for all unhandled exceptions."""
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    logger.debug(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "path": str(request.url.path),
        },
    )


# Register routers
admin_auth_dependencies = [Depends(require_admin_request_access)]
jobs_auth_dependencies = [Depends(require_admin_or_scheduler_job_access)]

app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(stats.router, prefix="/api", tags=["Stats"], dependencies=admin_auth_dependencies)
app.include_router(global_configs.router, prefix="/api", tags=["Global Configs"], dependencies=admin_auth_dependencies)
app.include_router(clients.router, prefix="/api", tags=["Clients"], dependencies=admin_auth_dependencies)
app.include_router(jobs.router, prefix="/api", tags=["Jobs"], dependencies=jobs_auth_dependencies)
app.include_router(prompts.router, prefix="/api", tags=["Prompts"], dependencies=admin_auth_dependencies)
app.include_router(tasks.router, prefix="/api", tags=["Tasks"], dependencies=admin_auth_dependencies)
app.include_router(analysis.router, prefix="/api", tags=["Analysis"], dependencies=admin_auth_dependencies)
# v1.2 [2026-04-20]: legacy Admin brainstorming router physically deleted
# (SaaS-side brainstorming router is the canonical endpoint).
app.include_router(languages.router, prefix="/api", tags=["Languages"], dependencies=admin_auth_dependencies)
app.include_router(report_templates.router, prefix="/api", tags=["Report Templates"], dependencies=admin_auth_dependencies)
app.include_router(analysis_metrics.router, prefix="/api", tags=["Analysis Metrics"], dependencies=admin_auth_dependencies)
app.include_router(report_runs.router, prefix="/api", tags=["Agent Tasks"], dependencies=admin_auth_dependencies)
app.include_router(brand_profiles.router, prefix="/api", tags=["Brand Profiles"], dependencies=admin_auth_dependencies)
app.include_router(memories.router, prefix="/api", tags=["Memories"], dependencies=admin_auth_dependencies)
app.include_router(agent_sessions.router, prefix="/api", tags=["Agent Sessions"], dependencies=admin_auth_dependencies)
app.include_router(agent_token_usage.router, prefix="/api", tags=["Agent Token Usage"], dependencies=admin_auth_dependencies)
app.include_router(user_profiles.router, prefix="/api", tags=["User Profiles"], dependencies=admin_auth_dependencies)
app.include_router(content_framework.router, prefix="/api", tags=["Content Framework"], dependencies=admin_auth_dependencies)
app.include_router(access_control.router, prefix="/api", tags=["Access Control"], dependencies=admin_auth_dependencies)
app.include_router(feature_access.router, prefix="/api", tags=["Feature Access"], dependencies=admin_auth_dependencies)
app.include_router(static_reports.router, prefix="/api", tags=["Static Reports"], dependencies=admin_auth_dependencies)


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}
