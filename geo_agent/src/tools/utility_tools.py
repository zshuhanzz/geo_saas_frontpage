"""
Tier 1 Utility Tools for geo_agent.

Lightweight, non-LLM tools that provide system context:
  - get_available_platforms: platforms with data for current client
  - get_date_range: earliest/latest data dates for current client

Note: get_current_datetime and get_client_info are injected into
system prompts directly (not as tools) since they're needed every turn.
"""
import logging
from langchain_core.tools import tool
from middleware.tenant import tenant_scoped
from database import get_pool

logger = logging.getLogger(__name__)


@tool
async def get_available_platforms(client_id: str) -> dict:
    """Get the list of AI platforms that have data for this client.

    Returns platforms with data (e.g. chatgpt, gemini, perplexity) and
    the count of results per platform. Use this before analyzing data to
    know which platforms to include.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT LOWER(t.platform) AS platform, COUNT(DISTINCT r.result_id) AS result_count
           FROM geo_tasks t
           JOIN geo_results r ON r.task_id = t.task_id
           WHERE t.client_id = $1::uuid
           GROUP BY LOWER(t.platform)
           ORDER BY result_count DESC""",
        client_id,
    )
    platforms = [{"platform": r["platform"], "result_count": r["result_count"]} for r in rows]
    return {
        "platforms": platforms,
        "platform_names": [p["platform"] for p in platforms],
        "count": len(platforms),
    }


@tool
async def get_date_range(client_id: str) -> dict:
    """Get the date range of available data for this client.

    Returns the earliest and latest data dates. Use this to determine
    valid date ranges when the user asks about 'last week', 'last month', etc.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT MIN(t.created_at)::date AS earliest,
                  MAX(t.created_at)::date AS latest,
                  COUNT(DISTINCT t.id) AS total_tasks
           FROM geo_tasks t
           WHERE t.client_id = $1::uuid""",
        client_id,
    )
    if row and row["earliest"]:
        return {
            "earliest_date": str(row["earliest"]),
            "latest_date": str(row["latest"]),
            "total_tasks": row["total_tasks"],
        }
    return {"earliest_date": None, "latest_date": None, "total_tasks": 0}


# ── System Prompt Injection Helpers (not @tool, called directly) ───────

async def get_system_context(client_id: str) -> str:
    """Build system context string with current datetime and client info.

    This is injected into system prompts for all 3 entry points.
    """
    from datetime import datetime, timezone, timedelta

    # Current datetime
    tz = timezone(timedelta(hours=8))  # Asia/Shanghai = UTC+8
    now = datetime.now(tz)
    datetime_str = now.strftime("%Y-%m-%d %H:%M (%A)")

    # Client info
    pool = await get_pool()
    client_row = await pool.fetchrow(
        "SELECT name FROM geo_clients WHERE id = $1::uuid",
        client_id,
    )

    # Peers (competitors).
    # v1.2: geo_client_peers.is_own_brand column was dropped — every row in
    # this table is by definition a competitor. (A brand that is both a
    # Peer and a Shadow/Distributor is represented in geo_client_brands
    # with is_shadow=true, not as a peer row with is_own_brand=true.)
    peers = await pool.fetch(
        "SELECT primary_name FROM geo_client_peers WHERE client_id = $1::uuid",
        client_id,
    )
    peer_names = [r["primary_name"] for r in peers]

    # Domains — show the client's primary Own-brand domains only. v1.2
    # expanded geo_client_domains to cover Shadow/Peer scoping; filter by
    # is_primary AND (brand_id IS NULL OR owning brand is not shadow) so
    # the system prompt shows only the client's own "main" domains.
    domains = await pool.fetch(
        """
        SELECT d.domain
        FROM geo_client_domains d
        LEFT JOIN geo_client_brands b ON b.id = d.brand_id
        WHERE d.client_id = $1::uuid
          AND d.is_primary = true
          AND d.peer_id IS NULL
          AND (b.id IS NULL OR b.is_shadow = false)
        """,
        client_id,
    )
    domain_list = [r["domain"] for r in domains]

    parts = [
        "[系统信息]",
        f"当前时间: {datetime_str} (Asia/Shanghai)",
    ]

    if client_row:
        brand = client_row["name"] or "Unknown"
        parts.append(f"品牌: {brand}")
    if domain_list:
        parts.append(f"主域名: {', '.join(domain_list)}")
    if peer_names:
        parts.append(f"竞品: {', '.join(peer_names)}")

    return "\n".join(parts)
