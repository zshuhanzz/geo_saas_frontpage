"""
Per-user rate limiter for geo_agent.

Two-layer limiting:
  1. RPM: N requests per minute (in-memory sliding window, fast)
  2. Daily token budget: M tokens per day (DB-backed, precise via Gemini usage_metadata)

Quota is configured per-client on the geo_clients table:
  - agent_daily_token_quota: tokens per user per day (resets at UTC 00:00)
  - agent_rpm_limit: requests per user per minute

Uses in-memory counters for RPM (no Redis). Each Cloud Run instance
maintains its own window, so the effective limit scales with instance count.
"""
import time
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Defaults (used if client-level config is missing) ─────────
DEFAULT_RPM = 10
DEFAULT_DAILY_TOKEN_QUOTA = 500000

# ── Client quota cache (per-client config from geo_clients) ───
_client_quota_cache: dict[str, dict] = {}
_client_quota_cache_ts: float = 0
_CLIENT_QUOTA_CACHE_TTL = 120  # Re-read from DB every 2 minutes


class RPMLimiter:
    """Per-minute sliding window rate limiter keyed by client_id:user_identifier."""

    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, rpm_limit: int) -> tuple[bool, dict]:
        """Check if a request is allowed within 60-second window.

        Returns (allowed, info).
        """
        now = time.time()
        window_start = now - 60

        self._windows[key] = [ts for ts in self._windows[key] if ts > window_start]
        count = len(self._windows[key])
        remaining = max(0, rpm_limit - count)

        if count >= rpm_limit:
            oldest = self._windows[key][0] if self._windows[key] else now
            retry_after = max(1, int(oldest + 60 - now) + 1)
            return False, {
                "used": count, "limit": rpm_limit, "remaining": 0, "retry_after": retry_after,
            }

        self._windows[key].append(now)
        return True, {
            "used": count + 1, "limit": rpm_limit, "remaining": remaining - 1,
        }

    def cleanup_stale(self, max_age_seconds: int = 120):
        """Remove entries that haven't had requests recently."""
        now = time.time()
        stale = [k for k, ts in self._windows.items() if not ts or ts[-1] < now - max_age_seconds]
        for k in stale:
            del self._windows[k]


_limiter = RPMLimiter()


def _user_key(client_id: str, user_id: str) -> str:
    return f"{client_id}:{user_id}"


async def get_client_quota(client_id: str) -> dict:
    """Get quota config for a client. Cached for 2 minutes."""
    global _client_quota_cache, _client_quota_cache_ts

    now = time.time()
    if now - _client_quota_cache_ts < _CLIENT_QUOTA_CACHE_TTL and client_id in _client_quota_cache:
        return _client_quota_cache[client_id]

    defaults = {"rpm_limit": DEFAULT_RPM, "daily_token_quota": DEFAULT_DAILY_TOKEN_QUOTA}

    try:
        from database import get_pool
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT agent_daily_token_quota, agent_rpm_limit FROM geo_clients WHERE id = $1::uuid",
            client_id,
        )
        if row:
            _client_quota_cache[client_id] = {
                "rpm_limit": row["agent_rpm_limit"] or DEFAULT_RPM,
                "daily_token_quota": row["agent_daily_token_quota"] or DEFAULT_DAILY_TOKEN_QUOTA,
            }
            _client_quota_cache_ts = now
            return _client_quota_cache[client_id]
    except Exception as e:
        logger.warning(f"[RATE_LIMIT] Failed to load client quota, using defaults: {e}")

    return defaults


async def get_daily_token_usage(client_id: str, user_id: str) -> dict:
    """Get today's token usage for a user (UTC day boundary).

    Returns dict with used, limit, reset_at_utc.
    """
    try:
        from database import get_pool
        from datetime import datetime, timezone
        pool = await get_pool()

        row = await pool.fetchrow(
            """SELECT COALESCE(SUM(tokens_input + tokens_output), 0) AS total_tokens
               FROM agent_token_usage
               WHERE client_id = $1::uuid
                 AND user_identifier = $2
                 AND created_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC')""",
            client_id, user_id,
        )

        quota = await get_client_quota(client_id)
        total = int(row["total_tokens"]) if row else 0

        # Calculate reset time (next UTC midnight)
        now = datetime.now(timezone.utc)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        if tomorrow <= now:
            tomorrow += timedelta(days=1)
        reset_at = tomorrow.isoformat()

        return {
            "used": total,
            "limit": quota["daily_token_quota"],
            "reset_at": reset_at,
            "percentage": min(100, total * 100 // max(quota["daily_token_quota"], 1)),
        }
    except Exception as e:
        logger.warning(f"[RATE_LIMIT] Failed to get daily token usage: {e}")
        return {"used": 0, "limit": DEFAULT_DAILY_TOKEN_QUOTA, "reset_at": "", "percentage": 0}


async def check_rate_limit(client_id: str, user_id: str) -> tuple[bool, dict]:
    """Check both RPM and daily token limits.

    Returns (allowed, info).
    """
    quota = await get_client_quota(client_id)
    key = _user_key(client_id, user_id)

    # Layer 1: RPM
    rpm_allowed, rpm_info = _limiter.check(key, quota["rpm_limit"])

    # Layer 2: Daily token budget
    token_info = await get_daily_token_usage(client_id, user_id)
    token_allowed = token_info["used"] < quota["daily_token_quota"]

    allowed = rpm_allowed and token_allowed

    info = {"rpm": rpm_info, "daily_quota": token_info}

    if not rpm_allowed:
        info["retry_after"] = rpm_info.get("retry_after", 5)
        info["reason"] = "rpm_exceeded"
    elif not token_allowed:
        info["retry_after"] = 60
        info["reason"] = "daily_token_quota_exceeded"

    return allowed, info


async def get_quota_status(client_id: str, user_id: str) -> dict:
    """Get current quota status for toolbar display. Does NOT consume a request."""
    token_info = await get_daily_token_usage(client_id, user_id)
    return {"daily_quota": token_info}


async def cleanup_old_token_usage():
    """Delete token usage records older than 7 days. Call periodically."""
    try:
        from database import get_pool
        pool = await get_pool()
        result = await pool.execute(
            "DELETE FROM agent_token_usage WHERE created_at < NOW() - INTERVAL '7 days'"
        )
        logger.info(f"[RATE_LIMIT] Cleaned up old token usage records: {result}")
    except Exception as e:
        logger.warning(f"[RATE_LIMIT] Failed to cleanup token usage: {e}")


def get_limiter() -> RPMLimiter:
    """Access the singleton limiter for cleanup tasks."""
    return _limiter
