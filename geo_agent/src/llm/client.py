"""
LLM Client wrapper for geo_agent.

Thin wrapper around google-genai Client. Model IDs and timeout settings
are read from the geo_global_settings table.

DB keys:
  - agent_pro_model_id           → Analyze/Action agents (Gemini Pro)
  - agent_flash_model_id         → Supervisor/Chat (Gemini Flash)
  - agent_timeout_pro_seconds    → Timeout for Pro calls (default 60)
  - agent_timeout_flash_seconds  → Timeout for Flash calls (default 30)

Token tracking:
  Call start_token_tracking() before graph execution and get_tracked_tokens()
  after. Every generate_content call automatically accumulates input/output
  token counts from Gemini's usage_metadata via contextvars.
"""
import os
import time
import logging
import contextvars
from google import genai
from google.genai import types
from geo_common.llm import MODEL_REGION_OVERRIDES_KEY, resolve_model_region

logger = logging.getLogger(__name__)

# ── Per-request token accumulator (via contextvars) ───────────
# Each asyncio task gets its own copy, so concurrent requests don't clash.
_request_tokens: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "request_tokens", default=None
)


def start_token_tracking() -> None:
    """Call before graph execution to start accumulating token counts."""
    _request_tokens.set({"input": 0, "output": 0, "calls": 0})


def get_tracked_tokens() -> dict | None:
    """Get accumulated token counts for this request. Returns None if tracking not started."""
    return _request_tokens.get(None)


def _accumulate_usage(response) -> None:
    """Extract usage_metadata from a Gemini response and add to the accumulator."""
    tracker = _request_tokens.get(None)
    if tracker is None:
        return
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage:
            tracker["input"] += getattr(usage, "prompt_token_count", 0) or 0
            tracker["output"] += getattr(usage, "candidates_token_count", 0) or 0
            tracker["calls"] += 1
    except Exception:
        pass  # Never break the hot path for telemetry

# Bypass macOS system proxy for Vertex AI calls.
# macOS System Preferences proxy is detected by urllib/httpx even when
# env vars are unset, causing TLS handshake timeouts through local proxy.
os.environ.setdefault("NO_PROXY", "*")

# Module-level caches
_client_cache: dict[str, genai.Client] = {}
_model_id_cache: dict[str, str] = {}

# Timeout settings cache (separate from model cache — refreshed on TTL)
_timeout_cache: dict[str, int] = {}
_timeout_cache_ts: float = 0
_TIMEOUT_CACHE_TTL = 60  # Re-read from DB every 60 seconds
_region_overrides_cache: str | None = None
_region_overrides_cache_ts: float = 0

# Fallback defaults (only used if DB row is missing)
_FALLBACKS = {
    "pro": "gemini-3.1-pro-preview",
    "flash": "gemini-3-flash-preview",
}

_DEFAULT_TIMEOUTS = {
    "pro": 300,
    "flash": 30,
}


def _resolve_region(model_id: str, overrides_value: str | None = None) -> str:
    """Resolve Vertex region with DB-configured overrides when present."""
    return resolve_model_region(
        model_id,
        overrides_value=overrides_value,
        default_region=os.environ.get("GCP_REGION", "us-central1"),
        global_region=os.environ.get("GCP_REGION_GLOBAL", "global"),
    )


def _resolve_project() -> str:
    """Resolve GCP project ID: env var → google.auth.default() fallback."""
    project = os.environ.get("GCP_PROJECT_ID", "")
    if not project:
        try:
            import google.auth
            _, project = google.auth.default()
        except Exception:
            pass
    if not project:
        raise RuntimeError(
            "GCP_PROJECT_ID is not set and google.auth.default() failed. "
            "Run 'gcloud auth application-default login' or set GCP_PROJECT_ID."
        )
    return project


async def get_genai_client(model_id: str, role: str = "flash", timeout_seconds: int | None = None) -> genai.Client:
    """Get or create a cached genai.Client for the given model's region.

    Timeout is baked into the client at creation time (not per-request)
    to avoid the SDK creating new httpx clients that pick up system proxy.
    """
    project = _resolve_project()
    region = _resolve_region(model_id, await get_model_region_overrides())
    timeout = timeout_seconds if timeout_seconds and timeout_seconds > 0 else await get_timeout_seconds(role)
    cache_key = f"{project}:{region}:{timeout}"

    if cache_key not in _client_cache:
        logger.info(f"[LLM] Creating GenAI client | project={project} | region={region} | timeout={timeout}s")
        _client_cache[cache_key] = genai.Client(
            vertexai=True,
            project=project,
            location=region,
            http_options=types.HttpOptions(timeout=timeout * 1000),  # SDK expects milliseconds
        )
    return _client_cache[cache_key]


async def get_model_id(role: str) -> str:
    """Get the model ID for a given agent role from geo_global_settings.

    Roles:
      - "pro"   → Analyze/Action agents (precision work)
      - "flash" → Supervisor/Chat (fast, cheap)

    Results are cached for the process lifetime. To refresh,
    restart the service or call clear_model_cache().
    """
    if role in _model_id_cache:
        return _model_id_cache[role]

    from database import get_pool

    key = f"agent_{role}_model_id"
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT value FROM geo_global_settings WHERE key = $1", key
    )

    if row and row["value"]:
        model_id = row["value"].strip()
    else:
        model_id = _FALLBACKS.get(role, _FALLBACKS["flash"])
        logger.warning(
            f"[LLM] No DB setting for '{key}', using fallback: {model_id}"
        )

    _model_id_cache[role] = model_id
    logger.info(f"[LLM] Resolved {role} model: {model_id}")
    return model_id


async def get_model_region_overrides() -> str | None:
    """Read optional model-id -> Vertex location overrides from global settings."""
    global _region_overrides_cache, _region_overrides_cache_ts

    now = time.time()
    if now - _region_overrides_cache_ts < _TIMEOUT_CACHE_TTL:
        return _region_overrides_cache

    try:
        from database import get_pool

        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT value FROM geo_global_settings WHERE key = $1",
            MODEL_REGION_OVERRIDES_KEY,
        )
        _region_overrides_cache = row["value"].strip() if row and row["value"] else None
        _region_overrides_cache_ts = now
    except Exception as e:
        logger.warning(f"[LLM] Failed to load model region overrides: {e}")
        _region_overrides_cache = None
        _region_overrides_cache_ts = now

    return _region_overrides_cache


async def get_timeout_seconds(role: str) -> int:
    """Get the timeout in seconds for a given agent role from geo_global_settings.

    Roles:
      - "pro"   → Analyze/Action (default 60s)
      - "flash" → Supervisor/Chat (default 30s)

    Results are cached for 60 seconds.
    """
    global _timeout_cache, _timeout_cache_ts

    now = time.time()
    if now - _timeout_cache_ts < _TIMEOUT_CACHE_TTL and _timeout_cache:
        return _timeout_cache.get(role, _DEFAULT_TIMEOUTS.get(role, 60))

    try:
        from database import get_pool
        pool = await get_pool()

        rows = await pool.fetch(
            """
            SELECT key, value FROM geo_global_settings
            WHERE key IN ('agent_timeout_pro_seconds', 'agent_timeout_flash_seconds')
            """,
        )

        for row in rows:
            try:
                if row["key"] == "agent_timeout_pro_seconds":
                    _timeout_cache["pro"] = int(row["value"])
                elif row["key"] == "agent_timeout_flash_seconds":
                    _timeout_cache["flash"] = int(row["value"])
            except (ValueError, TypeError):
                pass

        _timeout_cache_ts = now
    except Exception as e:
        logger.warning(f"[LLM] Failed to load timeout settings, using defaults: {e}")

    return _timeout_cache.get(role, _DEFAULT_TIMEOUTS.get(role, 60))


async def generate_content(client: genai.Client, model_id: str, **kwargs):
    """Wrapper around client.aio.models.generate_content that auto-tracks tokens.

    Use this instead of calling client.aio.models.generate_content directly
    so token usage is automatically accumulated for quota tracking.
    """
    response = await client.aio.models.generate_content(model=model_id, **kwargs)
    _accumulate_usage(response)
    return response


def clear_model_cache():
    """Clear the model ID cache (e.g. after admin updates settings)."""
    _model_id_cache.clear()


def clear_timeout_cache():
    """Clear the timeout cache (e.g. after admin updates settings)."""
    global _timeout_cache_ts
    _timeout_cache.clear()
    _timeout_cache_ts = 0


def clear_region_overrides_cache():
    """Clear model-region override cache after admin updates settings."""
    global _region_overrides_cache, _region_overrides_cache_ts
    _region_overrides_cache = None
    _region_overrides_cache_ts = 0
