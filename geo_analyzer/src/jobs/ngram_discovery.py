"""
N-gram Candidate Discovery Job (Phase 6.1 backup channel)
=========================================================

Run as a standalone script / Cloud Run Job:

    python -m src.jobs.ngram_discovery --client-id <uuid> --window-hours 24

Reads the given client's ``geo_results.text`` over the trailing N hours, runs
``extract_ngram_candidates`` against each, aggregates globally, and UPSERTs
into ``geo_settings_candidates`` with ``source='n_gram'``.

This is the cost-free fallback for when the LLM Batch job is unavailable. It
produces higher noise than the LLM path but zero API spend.

Not wired into ``main.py`` — kept as a dedicated job so the main analyzer
pipeline stays lean and the n-gram pass can be scheduled independently (or
skipped entirely).

Phase 2.5b: every DB call is async asyncpg via the shared pool. The metadata
JSONB column accepts a Python dict directly thanks to the JSONB codec
registered on the pool.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set

from geo_common.services import (
    acquire_workspace_lifecycle_session_shared,
    release_workspace_lifecycle_session_shared,
)
from src.core import database as db
from src.parsers.ngram_extractor import extract_ngram_candidates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("NGramDiscovery")


async def _load_known_variants_and_aliases(conn, client_id: str) -> tuple:
    """Return (variants_set, aliases_set) — both flat lowercase sets."""
    variants: Set[str] = set()
    rows = await conn.fetch(
        """
        SELECT product_name, COALESCE(match_variants, '{}'::text[]) AS mv
          FROM geo_client_topic_products
         WHERE client_id = $1 AND is_active = true
        """,
        client_id,
    )
    for r in rows:
        if r["product_name"]:
            variants.add(r["product_name"].strip().lower())
        for v in (r["mv"] or []):
            if v:
                variants.add(v.strip().lower())

    aliases: Set[str] = set()
    rows = await conn.fetch(
        """
        SELECT brand_name, COALESCE(aliases, '{}'::text[]) AS al
          FROM geo_client_brands
         WHERE client_id = $1 AND is_active = true
        """,
        client_id,
    )
    for r in rows:
        if r["brand_name"]:
            aliases.add(r["brand_name"].strip().lower())
        for a in (r["al"] or []):
            if a:
                aliases.add(a.strip().lower())

    rows = await conn.fetch(
        """
        SELECT primary_name, COALESCE(aliases, '{}'::text[]) AS al
          FROM geo_client_peers
         WHERE client_id = $1
        """,
        client_id,
    )
    for r in rows:
        if r["primary_name"]:
            aliases.add(r["primary_name"].strip().lower())
        for a in (r["al"] or []):
            if a:
                aliases.add(a.strip().lower())

    return variants, aliases


async def _load_recent_results(conn, client_id: str, window_hours: int) -> List:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    return await conn.fetch(
        """
        SELECT result_id, text FROM geo_results
         WHERE client_id = $1
           AND ingested_at >= $2
           AND text IS NOT NULL AND LENGTH(text) > 0
        """,
        client_id,
        since,
    )


_UPSERT_SQL = """
    INSERT INTO geo_settings_candidates (
        client_id, candidate_string, candidate_type, source,
        frequency, first_seen, last_seen, status,
        sample_response_ids, metadata
    ) VALUES (
        $1, $2, 'own_product', 'n_gram',
        $3, NOW(), NOW(), 'pending',
        $4, $5
    )
    ON CONFLICT (client_id, candidate_string, candidate_type) DO UPDATE SET
        frequency = geo_settings_candidates.frequency + EXCLUDED.frequency,
        last_seen = NOW(),
        source = CASE
            WHEN geo_settings_candidates.source = EXCLUDED.source
                THEN geo_settings_candidates.source
            WHEN position(EXCLUDED.source in geo_settings_candidates.source) > 0
                THEN geo_settings_candidates.source
            ELSE geo_settings_candidates.source || '+' || EXCLUDED.source
        END,
        sample_response_ids = (
            SELECT ARRAY(
                SELECT DISTINCT unnest(
                    COALESCE(geo_settings_candidates.sample_response_ids, ARRAY[]::int[])
                    || COALESCE(EXCLUDED.sample_response_ids, ARRAY[]::int[])
                )
                LIMIT 10
            )
        )
"""


async def _upsert_candidates(conn, client_id: str, agg: Dict[str, Dict]) -> int:
    """UPSERT aggregated candidates; returns rows touched."""
    if not agg:
        return 0

    touched = 0
    async with conn.transaction():
        for cstr, info in agg.items():
            await conn.execute(
                _UPSERT_SQL,
                client_id,
                cstr,
                int(info["frequency"]),
                list(info["sample_response_ids"])[:3],
                {
                    "sample_position": int(info["sample_position"]),
                    "discovered_via": "ngram_heuristic",
                },
            )
            touched += 1
    return touched


async def run(client_id: str, window_hours: int = 24) -> Dict:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await acquire_workspace_lifecycle_session_shared(conn, client_id)
        try:
            variants, aliases = await _load_known_variants_and_aliases(conn, client_id)
            results = await _load_recent_results(conn, client_id, window_hours)
            logger.info(
                "Loaded %d variants, %d aliases; scanning %d results (window=%dh)",
                len(variants), len(aliases), len(results), window_hours,
            )

            # Aggregate across all results: {cstr: {frequency, sample_position, sample_response_ids}}
            agg: Dict[str, Dict] = {}
            for r in results:
                cand_list = extract_ngram_candidates(r["text"], variants, aliases)
                for c in cand_list:
                    cstr = c["candidate_string"]
                    slot = agg.get(cstr)
                    if slot is None:
                        agg[cstr] = {
                            "frequency": c["frequency"],
                            "sample_position": c["sample_position"],
                            "sample_response_ids": [r["result_id"]],
                        }
                    else:
                        slot["frequency"] += c["frequency"]
                        if len(slot["sample_response_ids"]) < 3:
                            slot["sample_response_ids"].append(r["result_id"])

            # Only UPSERT candidates seen at least twice — cuts one-off noise hard.
            filtered = {k: v for k, v in agg.items() if v["frequency"] >= 2}
            logger.info(
                "Aggregated %d unique candidates; %d passed freq>=2 filter",
                len(agg), len(filtered),
            )
            touched = await _upsert_candidates(conn, client_id, filtered)
            logger.info("UPSERTed %d candidate rows", touched)
        finally:
            await release_workspace_lifecycle_session_shared(conn, client_id)

    return {
        "client_id": client_id,
        "window_hours": window_hours,
        "results_scanned": len(results),
        "candidates_before_filter": len(agg),
        "candidates_upserted": touched,
    }


async def main_async(client_id: str, window_hours: int) -> int:
    await db.connect()
    try:
        summary = await run(client_id, window_hours)
        logger.info("Done: %s", summary)
        return 0
    finally:
        await db.disconnect()


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--client-id", required=True, help="Client UUID")
    p.add_argument("--window-hours", type=int, default=24, help="Trailing hours window")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    return asyncio.run(main_async(args.client_id, args.window_hours))


if __name__ == "__main__":
    sys.exit(main())
