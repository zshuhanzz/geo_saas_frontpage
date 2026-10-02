import os
import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from geo_common.audit import AsyncAuditWriter, sanitize_query_params
from geo_common.auth import SessionExpiryAuditor
from pool import close_pool, open_pool
from routers import auth, insights, prompts, prompt_import, settings, clients, brainstorming, globals as globals_router, audit, me, published_urls, workspaces
from routers.sentiment import router as sentiment_router
from routers.onboarding import router as onboarding_router
from routers.static_reports.router import router as static_reports_router
from dependencies.auth import require_feature_access_if_present

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GeoSaaSAPI")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection lifecycle — Phase 2.5b unified asyncpg.

    The legacy ``databases`` lib + SQLAlchemy MetaData layer was removed in
    Phase 2.5b. A single ``asyncpg.Pool`` (owned by the ``db.database``
    singleton) backs both the raw-SQL routers (via the ``database`` adapter)
    and the ``geo_common.services.*Repository`` callsites that take a pool
    dependency.
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
    try:
        yield
    finally:
        await app.state.session_expiry_auditor.close()
        await app.state.audit_writer.close()
        logger.info("Closing shared asyncpg pool...")
        await close_pool(getattr(app.state, "pg_pool", None))

app = FastAPI(
    title="GEO SaaS API",
    description="Client-facing SaaS API for GEO Platform, independent from Admin Web.",
    version="2.5.0",
    lifespan=lifespan,
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
async def enqueue_registered_user_audit(request: Request, call_next):
    """Queue registered API actions after the primary response is produced."""
    response = await call_next(request)
    if request.url.path == "/api/audit/events" or request.url.path.startswith(
        "/api/auth/"
    ):
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
            for key in ("task_id", "prompt_id", "report_id", "topic_id", "brand_id")
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
            "action_label": None,
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
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Keep HTTP errors structured and visible in logs."""
    if exc.status_code >= 500:
        logger.warning(
            "HTTP error on %s %s: status=%s detail=%s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "message": exc.detail,
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return structured JSON for all unhandled exceptions."""
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return JSONResponse(
        status_code=500,
        content={
            "detail": detail,
            "error": True,
            "message": detail,
            "path": str(request.url.path),
        },
    )


auth_dependencies = [Depends(require_feature_access_if_present)]

app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(insights.router, prefix="/api/insights", tags=["Insights"], dependencies=auth_dependencies)
app.include_router(prompts.router, prefix="/api/prompts", tags=["Prompts"], dependencies=auth_dependencies)
app.include_router(prompt_import.router, prefix="/api/prompts", tags=["Prompt Import"], dependencies=auth_dependencies)
app.include_router(settings.router, prefix="/api/settings", tags=["Brand Settings"], dependencies=auth_dependencies)
app.include_router(clients.router, prefix="/api/clients", tags=["Clients"], dependencies=auth_dependencies)
app.include_router(brainstorming.router, prefix="/api/brainstorming", tags=["Brainstorming"], dependencies=auth_dependencies)
app.include_router(globals_router.router, prefix="/api", tags=["Global Dictionaries"], dependencies=auth_dependencies)
app.include_router(sentiment_router, tags=["Sentiment"], dependencies=auth_dependencies)
app.include_router(onboarding_router, tags=["Onboarding"], dependencies=auth_dependencies)
app.include_router(static_reports_router, tags=["Static Reports"], dependencies=auth_dependencies)
app.include_router(audit.router, prefix="/api/audit", tags=["Audit"], dependencies=auth_dependencies)
app.include_router(me.router, prefix="/api", tags=["Current User"])
app.include_router(workspaces.router, prefix="/api", tags=["Workspaces"], dependencies=auth_dependencies)
app.include_router(published_urls.router, prefix="/api/published-urls", tags=["Published URLs"], dependencies=auth_dependencies)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "geo_saas_api"}
