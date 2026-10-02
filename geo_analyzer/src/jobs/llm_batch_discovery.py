"""
LLM Batch Candidate Discovery Job (Phase 6.2 — main channel)
============================================================

Scheduled job that reads recent ``geo_results`` (per client), feeds the
response text + the client's configured brand / peer / product_variant lists
into Gemini Flash, and extracts **未配置的品牌 / 产品型号 / SKU 候选** into
``geo_settings_candidates`` (source='llm_batch').

Why this exists
---------------
N-gram fallback is pure algorithm and produces noisy output. The LLM path is
the main channel — it can distinguish a product code (ESR-70911-BLK) from
arbitrary punctuation, and it can label brand vs product vs peer. Running as
a nightly batch keeps spend predictable (~$1-2/mo per 2 clients on Flash).

Not wired into ``main.py`` — this is a dedicated offline job:

    python -m src.jobs.llm_batch_discovery --client-id <uuid> --window-hours 24

Or without ``--client-id`` to iterate all clients with results in the window.

Internals are split for readability — see ``src/jobs/_llm_batch/``:
    loaders.py     — DB readers + model_id resolver.
    prompt.py      — Bilingual extraction prompt builder.
    gemini_call.py — google-genai async invocation + tolerant JSON parse.
    upsert.py      — UPSERT into geo_settings_candidates.

Phase 2.5b: every DB call is async asyncpg via the shared pool. The CLI
driver opens / closes the pool once per invocation.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Dict, List, Optional

from geo_common.services import workspace_lifecycle_session
from src.core import database as db
from src.jobs._llm_batch.gemini_call import call_gemini
from src.jobs._llm_batch.loaders import (
    all_known_lc,
    load_clients_with_recent_results,
    load_known_config,
    load_recent_samples,
    resolve_model_id,
    resolve_model_region_overrides,
)
from src.jobs._llm_batch.prompt import build_prompt
from src.jobs._llm_batch.upsert import upsert_candidates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("LLMBatchDiscovery")


async def process_client(client_id: str, window_hours: int) -> Dict[str, Any]:
    """Run the full discovery pipeline for a single client.

    Two short-lived DB connections: one for reads (config + samples + model_id),
    one for the UPSERT after the LLM call returns. Keeping the DB connection
    out of the async LLM call avoids holding a pool slot open across an
    awaitable that can take many seconds.
    """
    pool = db.get_pool()
    # A dedicated shared lifecycle session fence spans the LLM await and the
    # later UPSERT. The small Analyzer pool still retains capacity for the
    # short-lived read/write connections below.
    async with workspace_lifecycle_session(pool, client_id):
        async with pool.acquire() as conn:
            config = await load_known_config(conn, client_id)
            samples = await load_recent_samples(conn, client_id, window_hours)
            if not samples:
                logger.info("client=%s no samples in last %dh, skip", client_id, window_hours)
                return {"client_id": client_id, "status": "no_samples", "upserted": 0}
            model_id = await resolve_model_id(conn, logger)
            model_region_overrides = await resolve_model_region_overrides(conn, logger)

        logger.info(
            "client=%s scanning %d samples (model=%s)",
            client_id, len(samples), model_id,
        )
        prompt = build_prompt(config, samples)
        known_lc = all_known_lc(config)
        result = await call_gemini(
            model_id,
            prompt,
            model_region_overrides=model_region_overrides,
        )
        if not result or not isinstance(result.get("candidates"), list):
            logger.warning("client=%s LLM returned no candidates", client_id)
            return {"client_id": client_id, "status": "llm_empty", "upserted": 0}

        candidates = [c for c in result["candidates"] if isinstance(c, dict)]
        sample_ids = [s["result_id"] for s in samples]
        async with pool.acquire() as conn:
            touched = await upsert_candidates(conn, client_id, candidates, known_lc, sample_ids)

        logger.info(
            "client=%s LLM proposed %d, upserted %d",
            client_id, len(candidates), touched,
        )
        return {
            "client_id": client_id,
            "status": "ok",
            "proposed": len(candidates),
            "upserted": touched,
        }


async def main_async(client_id: Optional[str], window_hours: int) -> int:
    await db.connect()
    try:
        if client_id:
            clients = [client_id]
        else:
            pool = db.get_pool()
            async with pool.acquire() as conn:
                clients = await load_clients_with_recent_results(conn, window_hours)
            logger.info("Auto-discovered %d clients with recent results", len(clients))

        summaries: List[Dict[str, Any]] = []
        for cid in clients:
            try:
                s = await process_client(cid, window_hours)
                summaries.append(s)
            except Exception as exc:
                logger.exception("client=%s crashed: %s", cid, exc)
                summaries.append({"client_id": cid, "status": "error", "error": str(exc)})
        logger.info("Done. %s", summaries)
        return 0
    finally:
        await db.disconnect()


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--client-id",
        default=None,
        help="Specific client UUID; omit to process all active clients",
    )
    p.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="Trailing hours window of geo_results",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    return asyncio.run(main_async(args.client_id, args.window_hours))


if __name__ == "__main__":
    sys.exit(main())
