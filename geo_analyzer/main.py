"""
GEO Analyzer - Main Entry Point (v1.2 dual-mode tracking)

Cloud Run Job that processes ``geo_results`` for a specific Client,
extracting Brand / Product mentions and Citations into structured
tables per the v1.2 schema.

Pipeline:
    Phase 0 — Load client config: brands / peers / tracked_products /
              domains / tracked_urls.
    Phase 1 — Per result, run BrandParser + ProductParser + CitationParser
              in memory, collecting structured outputs.
    Phase 2a — Batch domain_classifier on unique domains.
    Phase 2b — Batch sentiment parse per sub-batch.
    Phase 3 — Write brand_mentions / product_mentions / citations.
    Phase B — Normalize sentiment themes against the dictionary.

This file is the orchestrator. Each phase lives in ``src/pipeline/``:
    src/pipeline/phase0_load_config.py
    src/pipeline/phase1_per_result_parse.py
    src/pipeline/phase2a_domain_classify.py
    src/pipeline/phase2b_sentiment.py
    src/pipeline/phase3_write.py
    src/pipeline/phase_b_normalize_themes.py

Phase 2.5b: every DB call is now async (asyncpg) and every LLM call uses
``client.aio.models.generate_content`` so the analyzer is fully
non-blocking. LLM phases run outside long write transactions; each batch
opens a short transaction only for structured writes and ``analyzed_at``
stamping.

Usage:
    CLIENT_ID=xxx python main.py
"""
import asyncio
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass

from geo_common.llm import MODEL_REGION_OVERRIDES_KEY
from geo_common.services import (
    acquire_workspace_lifecycle_session_shared,
    release_workspace_lifecycle_session_shared,
)
from src.core import database as db
from src.pipeline.phase0_load_config import load_client_config
from src.pipeline.phase1_per_result_parse import parse_batch
from src.pipeline.phase2a_domain_classify import classify_batch_domains
from src.pipeline.phase2b_sentiment import extract_sentiment_for_batch
from src.pipeline.phase3_write import write_batch
from src.pipeline.phase_b_normalize_themes import normalize_themes_for_client
from src.parsers.sentiment_parser import write_sentiment_results

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("GeoAnalyzer")


# Per-batch row count for the geo_results scan loop. Keep small enough that
# a single batch's Gemini-classified domains + sentiment calls don't blow
# the request timeout, but large enough to amortize per-batch overhead.
RESULTS_BATCH_SIZE = 100


@dataclass(frozen=True)
class ShardConfig:
    task_index: int
    task_count: int


def resolve_shard_config(env=os.environ) -> ShardConfig:
    """Resolve Cloud Run Job task sharding env with local defaults."""
    try:
        task_index = int(env.get("CLOUD_RUN_TASK_INDEX", "0"))
    except ValueError:
        task_index = 0
    try:
        task_count = int(env.get("CLOUD_RUN_TASK_COUNT", "1"))
    except ValueError:
        task_count = 1
    if task_count < 1:
        task_count = 1
    if task_index < 0 or task_index >= task_count:
        logger.warning(
            "[ANALYZER-S0] Invalid shard env task_index=%s task_count=%s; using 0/1",
            task_index,
            task_count,
        )
        return ShardConfig(task_index=0, task_count=1)
    return ShardConfig(task_index=task_index, task_count=task_count)


def build_shard_predicate(
    column_name: str = "result_id",
    *,
    task_count_param: str = "$3",
    task_index_param: str = "$4",
) -> str:
    """Return deterministic shard predicate for UUID/int result identifiers."""
    return (
        f"MOD((hashtext({column_name}::text)::bigint & 2147483647), "
        f"{task_count_param}) = {task_index_param}"
    )


def _int32_from_digest(chunk: bytes) -> int:
    value = int.from_bytes(chunk, byteorder="big", signed=False)
    if value >= 2**31:
        value -= 2**32
    return value


def stable_advisory_lock_keys(
    client_id: str,
    batch_id: str,
    task_index: int,
    task_count: int,
) -> tuple[int, int]:
    """Derive stable signed 32-bit PostgreSQL advisory lock keys."""
    digest = hashlib.sha256(
        f"{client_id}:{batch_id}:{task_index}:{task_count}".encode("utf-8")
    ).digest()
    return _int32_from_digest(digest[:4]), _int32_from_digest(digest[4:8])


async def _resolve_batch_id(conn, client_id: str, explicit_batch_id: str | None) -> str | None:
    if explicit_batch_id:
        pending = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_results
            WHERE client_id = $1
              AND batch_id = $2
              AND analyzed_at IS NULL
            """,
            client_id,
            explicit_batch_id,
        )
        logger.info(
            "[ANALYZER-S1] Explicit ANALYZER_BATCH_ID=%s pending=%d",
            explicit_batch_id,
            pending,
        )
        return explicit_batch_id if pending or os.environ.get("FORCE_RUN") else None

    return await conn.fetchval(
        """
        SELECT batch_id
        FROM geo_results
        WHERE client_id = $1
          AND analyzed_at IS NULL
          AND batch_id IS NOT NULL
        GROUP BY batch_id
        ORDER BY batch_id ASC
        LIMIT 1
        """,
        client_id,
    )


async def _try_acquire_shard_lock(conn, client_id: str, batch_id: str, shard: ShardConfig) -> tuple[bool, tuple[int, int]]:
    key1, key2 = stable_advisory_lock_keys(
        client_id,
        batch_id,
        shard.task_index,
        shard.task_count,
    )
    acquired = await conn.fetchval("SELECT pg_try_advisory_lock($1, $2)", key1, key2)
    return bool(acquired), (key1, key2)


async def _release_shard_lock(conn, keys: tuple[int, int] | None) -> None:
    if not keys:
        return
    await conn.execute("SELECT pg_advisory_unlock($1, $2)", keys[0], keys[1])


async def _load_model_ids(conn):
    """Fetch the per-task model IDs from ``geo_global_settings``.

    Returns ``(classifier_model_id, sentiment_model_id, model_region_overrides)``.
    Model IDs may be ``None`` — callers fall back to env defaults inside their
    helpers.
    """
    classifier_row = await conn.fetchrow(
        "SELECT value FROM geo_global_settings WHERE key = 'domain_classifier_model_id'"
    )
    classifier_model_id = classifier_row["value"] if classifier_row else None
    logger.info(
        "[ANALYZER-S1] Domain classifier model: %s",
        classifier_model_id or "(env default)",
    )

    sentiment_row = await conn.fetchrow(
        "SELECT value FROM geo_global_settings WHERE key = 'sentiment_model_id'"
    )
    sentiment_model_id = sentiment_row["value"] if sentiment_row else None
    logger.info(
        "[ANALYZER-S1] Sentiment model: %s",
        sentiment_model_id or "(env default)",
    )

    overrides_row = await conn.fetchrow(
        "SELECT value FROM geo_global_settings WHERE key = $1",
        MODEL_REGION_OVERRIDES_KEY,
    )
    model_region_overrides = overrides_row["value"] if overrides_row else None

    return classifier_model_id, sentiment_model_id, model_region_overrides


async def main_async() -> None:
    """Async orchestrator (v1.2 pipeline)."""
    client_id = os.environ.get("CLIENT_ID")
    if not client_id:
        logger.error("CLIENT_ID environment variable is required")
        sys.exit(1)

    logger.info("[ANALYZER-S0] ========== GEO Analyzer v1.2 启动 ==========")
    logger.info("[ANALYZER-S0] Client ID: %s", client_id)
    explicit_batch_id = os.environ.get("ANALYZER_BATCH_ID")
    shard = resolve_shard_config(os.environ)
    logger.info(
        "[ANALYZER-S0] Shard config: task_index=%d task_count=%d",
        shard.task_index,
        shard.task_count,
    )

    pool = await db.connect()
    lock_keys: tuple[int, int] | None = None
    lifecycle_acquired = False
    conn = None
    try:
        conn = await pool.acquire()
        try:
            # One shared session fence covers configuration reads, LLM work,
            # every short write transaction, and Analyzer-owned late writers.
            # It reuses the job's existing dedicated connection, so no extra
            # pool slot is held.
            await acquire_workspace_lifecycle_session_shared(conn, client_id)
            lifecycle_acquired = True
            # ===== Phase 0 — Load client config =====
            config = await load_client_config(conn, client_id)

            resolved_batch_id = await _resolve_batch_id(
                conn,
                client_id,
                explicit_batch_id,
            )
            logger.info("[ANALYZER-S1] Resolved batch_id=%s", resolved_batch_id)
            if not resolved_batch_id and not os.environ.get("FORCE_RUN"):
                logger.info("[ANALYZER-S1] 没有需要分析的 batch，退出")
                return

            if resolved_batch_id:
                acquired, lock_keys = await _try_acquire_shard_lock(
                    conn,
                    client_id,
                    resolved_batch_id,
                    shard,
                )
                if not acquired:
                    logger.info(
                        "[ANALYZER-S1] Shard lock already held; exiting | "
                        "client_id=%s batch_id=%s task_index=%d task_count=%d",
                        client_id,
                        resolved_batch_id,
                        shard.task_index,
                        shard.task_count,
                    )
                    return
                logger.info(
                    "[ANALYZER-S1] Shard lock acquired | keys=%s | client_id=%s | batch_id=%s",
                    lock_keys,
                    client_id,
                    resolved_batch_id,
                )

            # ===== Pre-flight — count work =====
            logger.info("[ANALYZER-S1] 查询未分析的 results 数量...")
            shard_predicate = build_shard_predicate(
                "result_id",
                task_count_param="$3",
                task_index_param="$4",
            )
            total_unanalyzed = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM geo_results
                WHERE client_id = $1
                  AND batch_id = $2
                  AND analyzed_at IS NULL
                  AND {shard_predicate}
                """,
                client_id,
                resolved_batch_id,
                shard.task_count,
                shard.task_index,
            )
            logger.info(
                "[ANALYZER-S1] 找到 %d 条未分析记录 | batch_id=%s | shard=%d/%d",
                total_unanalyzed,
                resolved_batch_id,
                shard.task_index,
                shard.task_count,
            )

            if total_unanalyzed == 0 and not os.environ.get("FORCE_RUN"):
                logger.info("[ANALYZER-S1] 没有需要分析的数据，退出")
                return

            classifier_model_id, sentiment_model_id, model_region_overrides = await _load_model_ids(conn)

            # ===== Main batch loop — Phases 1 / 2a / 2b / 3 =====
            total_processed = 0
            total_brand_mentions = 0
            total_product_mentions = 0
            total_citations = 0
            total_sentiment = 0

            while True:
                logger.info(
                    "[ANALYZER-S2] Fetching next batch (limit=%d)...",
                    RESULTS_BATCH_SIZE,
                )
                fetch_started = time.perf_counter()
                results = await conn.fetch(
                    f"""
                    SELECT * FROM geo_results
                    WHERE client_id = $1
                      AND batch_id = $2
                      AND analyzed_at IS NULL
                      AND {shard_predicate}
                    ORDER BY result_id
                    LIMIT $5
                    """,
                    client_id,
                    resolved_batch_id,
                    shard.task_count,
                    shard.task_index,
                    RESULTS_BATCH_SIZE,
                )
                fetch_seconds = time.perf_counter() - fetch_started

                if not results:
                    break

                batch_count = len(results)
                logger.info("[ANALYZER-S2] Processing batch of %d results...", batch_count)

                # Phase 1 — in-memory per-result parse.
                parse_started = time.perf_counter()
                parse_result = parse_batch(results, config)
                parse_seconds = time.perf_counter() - parse_started

                # Phase 2a — classify the batch's unique domains.
                domain_started = time.perf_counter()
                domain_categories = await classify_batch_domains(
                    conn,
                    parse_result.all_domains,
                    config.owned_domain_strs,
                    model_id=classifier_model_id,
                    model_region_overrides=model_region_overrides,
                )
                domain_seconds = time.perf_counter() - domain_started

                # Phase 2b — sentiment extraction in sub-batches. Gemini calls
                # are outside the write transaction; persistence happens below.
                sentiment_started = time.perf_counter()
                sentiment_results = await extract_sentiment_for_batch(
                    parse_result.sentiment_inputs,
                    model_id=sentiment_model_id,
                    model_region_overrides=model_region_overrides,
                )
                sentiment_seconds = time.perf_counter() - sentiment_started

                write_started = time.perf_counter()
                async with conn.transaction():
                    total_sentiment += await write_sentiment_results(
                        conn,
                        parse_result.sentiment_inputs,
                        sentiment_results,
                    )
                    counts = await write_batch(conn, parse_result, domain_categories)
                    total_brand_mentions += counts.brand_mentions
                    total_product_mentions += counts.product_mentions
                    total_citations += counts.citations
                write_seconds = time.perf_counter() - write_started

                total_processed += batch_count
                logger.info(
                    "[ANALYZER-S2] Batch committed | batch_id=%s | shard=%d/%d | "
                    "batch=%d | total_processed=%d | "
                    "timing fetch=%.2fs parse=%.2fs domain_classify=%.2fs sentiment=%.2fs write=%.2fs",
                    resolved_batch_id,
                    shard.task_index,
                    shard.task_count,
                    batch_count,
                    total_processed,
                    fetch_seconds,
                    parse_seconds,
                    domain_seconds,
                    sentiment_seconds,
                    write_seconds,
                )

            # ===== Phase B — theme normalization (once per run) =====
            if total_sentiment > 0:
                async with conn.transaction():
                    await normalize_themes_for_client(
                        conn,
                        client_id=client_id,
                        sentiment_model_id=sentiment_model_id,
                        model_region_overrides=model_region_overrides,
                    )

            logger.info("[ANALYZER-S3] ========== 分析周期结束 ==========")
            logger.info("[ANALYZER-S3] 本次共处理 results: %d", total_processed)
            logger.info("[ANALYZER-S3] 提取 brand mentions: %d", total_brand_mentions)
            logger.info("[ANALYZER-S3] 提取 product mentions: %d", total_product_mentions)
            logger.info("[ANALYZER-S3] 提取 citations: %d", total_citations)
            logger.info("[ANALYZER-S3] 提取 sentiment: %d results", total_sentiment)
        finally:
            if lock_keys:
                try:
                    await _release_shard_lock(conn, lock_keys)
                    logger.info("[ANALYZER-S3] Shard lock released | keys=%s", lock_keys)
                except Exception as exc:
                    logger.warning("[ANALYZER-S3] Failed to release shard lock: %s", exc)
            if lifecycle_acquired:
                try:
                    await release_workspace_lifecycle_session_shared(conn, client_id)
                except Exception as exc:
                    logger.warning(
                        "[ANALYZER-S3] Failed to release Workspace lifecycle lock: %s",
                        exc,
                    )
            if conn is not None:
                await pool.release(conn)
    finally:
        await db.disconnect()


def main() -> None:
    """Cloud Run Job entrypoint — top-level event-loop wrapper."""
    try:
        asyncio.run(main_async())
    except Exception as exc:
        logger.error("[ANALYZER-ERR] 分析失败: %s", exc)
        raise


if __name__ == "__main__":
    main()
