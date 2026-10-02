"""
DB loaders for the LLM Batch Candidate Discovery job.

Phase 2.5b: every loader is now async and runs against an
``asyncpg.Connection`` from the shared pool. The job's CLI driver
(``src/jobs/llm_batch_discovery.py``) acquires the connection inside an
``async with pool.acquire()`` block and passes it down.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set
from geo_common.llm import MODEL_REGION_OVERRIDES_KEY


# Cap response texts per client to bound prompt size — well under Flash's
# 30k context but enough for representative coverage.
MAX_SAMPLES_PER_CLIENT = 40
# Truncate long responses — AI-search answers usually fit well under this.
MAX_CHARS_PER_SAMPLE = 3000


async def load_clients_with_recent_results(conn, window_hours: int) -> List[str]:
    """Return distinct client_ids that have geo_results in the trailing window."""
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = await conn.fetch(
        """
        SELECT DISTINCT client_id FROM geo_results
         WHERE ingested_at >= $1
           AND text IS NOT NULL AND LENGTH(text) > 0
        """,
        since,
    )
    return [str(r["client_id"]) for r in rows if r["client_id"]]


async def load_known_config(conn, client_id: str) -> Dict[str, List[str]]:
    """Load the client's currently-configured brands / peers / products.

    Returns a dict with keys: ``own_brands`` / ``shadow_brands`` / ``peers``
    / ``product_variants``. Each list is plain strings (no IDs).
    """
    brands = await conn.fetch(
        """
        SELECT brand_name, COALESCE(aliases, '{}'::text[]) AS aliases, is_shadow
          FROM geo_client_brands
         WHERE client_id = $1 AND is_active = true
        """,
        client_id,
    )
    own_brands: List[str] = []
    shadow_brands: List[str] = []
    seen_by_role: Dict[bool, Set[str]] = {False: set(), True: set()}
    for row in brands:
        is_shadow = bool(row["is_shadow"])
        target = shadow_brands if is_shadow else own_brands
        for raw_name in (row["brand_name"], *(row.get("aliases") or [])):
            name = str(raw_name or "").strip()
            normalized = name.lower()
            if not name or normalized in seen_by_role[is_shadow]:
                continue
            seen_by_role[is_shadow].add(normalized)
            target.append(name)

    peers = await conn.fetch(
        "SELECT primary_name FROM geo_client_peers WHERE client_id = $1",
        client_id,
    )
    peer_names = [r["primary_name"] for r in peers]

    prods = await conn.fetch(
        """
        SELECT product_name, COALESCE(match_variants, '{}'::text[]) AS mv, product_role
         FROM geo_client_topic_products WHERE client_id = $1 AND is_active = true
        """,
        client_id,
    )
    product_variants: List[str] = []
    for r in prods:
        if r["product_name"]:
            product_variants.append(r["product_name"])
        for v in (r["mv"] or []):
            if v:
                product_variants.append(v)

    return {
        "own_brands": own_brands,
        "shadow_brands": shadow_brands,
        "peers": peer_names,
        "product_variants": sorted(set(product_variants), key=str.lower),
    }


async def load_recent_samples(conn, client_id: str, window_hours: int) -> List[Dict]:
    """Return recent geo_results.text rows for ``client_id``, capped + truncated."""
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = await conn.fetch(
        """
        SELECT result_id, text FROM geo_results
         WHERE client_id = $1
           AND ingested_at >= $2
           AND text IS NOT NULL AND LENGTH(text) > 0
         ORDER BY result_id DESC
         LIMIT $3
        """,
        client_id,
        since,
        MAX_SAMPLES_PER_CLIENT,
    )
    return [
        {
            "result_id": int(r["result_id"]),
            "text": (r["text"] or "")[:MAX_CHARS_PER_SAMPLE],
        }
        for r in rows
    ]


def all_known_lc(config: Dict[str, List[str]]) -> Set[str]:
    """Return a flat lowercase set of every already-known string across buckets.

    Used to filter Gemini's output before UPSERT — Gemini occasionally
    re-emits known items even though the prompt instructs it not to.
    """
    s: Set[str] = set()
    for bucket in ("own_brands", "shadow_brands", "peers", "product_variants"):
        for v in config.get(bucket, []):
            if v:
                s.add(v.strip().lower())
    return s


# ---------------------------------------------------------------------------
# Model resolution lives here too — same DB read pattern.
# ---------------------------------------------------------------------------


# Flash 2.0 — cheap + reliable. **Do not change without asking** (see
# `feedback_fallback_model_id` rule in CLAUDE.md memory).
FALLBACK_MODEL_ID = "gemini-2.0-flash"


async def resolve_model_id(conn, logger) -> str:
    """Read ``llm_batch_discovery_model_id`` from geo_global_settings, fall back."""
    try:
        row = await conn.fetchrow(
            """
            SELECT value FROM geo_global_settings
             WHERE key = 'llm_batch_discovery_model_id'
            """
        )
        if row and row["value"]:
            return row["value"]
    except Exception as exc:
        logger.warning("Failed to read llm_batch_discovery_model_id: %s", exc)
    return FALLBACK_MODEL_ID


async def resolve_model_region_overrides(conn, logger) -> str | None:
    """Read optional model-id -> Vertex location overrides."""
    try:
        row = await conn.fetchrow(
            """
            SELECT value FROM geo_global_settings
             WHERE key = $1
            """,
            MODEL_REGION_OVERRIDES_KEY,
        )
        if row and row["value"]:
            return row["value"]
    except Exception as exc:
        logger.warning("Failed to read %s: %s", MODEL_REGION_OVERRIDES_KEY, exc)
    return None
