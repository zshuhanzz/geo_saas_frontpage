"""
Phase 3 — Persist parser outputs into the analyzer's write tables.

Writes happen per-result so any single bad row only loses that row, not the
whole batch (the outer caller commits per-batch via an enclosing
``conn.transaction()``).

Tables written:
- ``geo_brand_mentions`` — one row per brand mention.
- ``geo_product_mentions`` — one row per product mention with denormalized
  owner identity fields.
- ``geo_citations`` — one row per citation with both the v1.2 attribution
  (``citation_role`` + ``matched_*_id``) and the global ``domain_category``.
- ``geo_results.analyzed_at`` is stamped to mark each row processed.

Phase 2.5b: every write is now ``await conn.execute(...)`` with positional
``$1, $2, …`` placeholders. Asyncpg ``Record`` rows expose dict-style access
only (``result["client_id"]``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

from src.pipeline.phase1_per_result_parse import BatchParseResult

logger = logging.getLogger("GeoAnalyzer.phase3")


async def _prompt_exists_for_client(
    conn, client_id: str, client_prompt_id: str
) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1
            FROM geo_client_prompts
            WHERE client_id = $1::uuid
              AND id = $2::uuid
            FOR KEY SHARE
            """,
            client_id,
            client_prompt_id,
        )
    )


@dataclass
class WriteCounts:
    brand_mentions: int = 0
    product_mentions: int = 0
    citations: int = 0


async def write_batch(
    conn,
    parse_result: BatchParseResult,
    domain_categories: Dict[str, str],
) -> WriteCounts:
    """Persist the per-batch parser output and stamp ``analyzed_at``.

    ``domain_categories`` is the dict from Phase 2a (lowercase domain →
    category enum string). Citations whose domain is missing from the map
    fall back to ``"Other"`` — the same behavior the previous monolithic
    main.py had.
    """
    counts = WriteCounts()

    for result, brand_mentions, product_mentions, citations in parse_result.per_result:
        if not await _prompt_exists_for_client(
            conn,
            str(result["client_id"]),
            str(result["client_prompt_id"]),
        ):
            logger.info(
                "[Phase3] Skip stale analyzer writes because prompt was deleted "
                "| result_id=%s | client_prompt_id=%s",
                result["result_id"],
                result["client_prompt_id"],
            )
            continue

        # --- geo_brand_mentions ---
        for m in brand_mentions:
            await conn.execute(
                """
                INSERT INTO geo_brand_mentions
                (client_prompt_id, task_id, result_id, client_id,
                 brand_name, mention_position, brand_role, executed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                result["client_prompt_id"],
                result["task_id"],
                result["result_id"],
                result["client_id"],
                m["brand_name"],
                m["mention_position"],
                m["brand_role"],
                result["ingested_at"],
            )

        # --- geo_product_mentions (with denormalized owner identity) ---
        for pm in product_mentions:
            await conn.execute(
                """
                INSERT INTO geo_product_mentions
                (client_prompt_id, task_id, result_id, client_id,
                 product_id, product_name, product_role, shadow_sub_role,
                 owner_brand_id, owner_brand_name,
                 owner_peer_id, owner_peer_name,
                 mention_position, executed_at)
                VALUES ($1, $2, $3, $4,
                        $5, $6, $7, $8,
                        $9, $10,
                        $11, $12,
                        $13, $14)
                """,
                result["client_prompt_id"],
                result["task_id"],
                result["result_id"],
                result["client_id"],
                pm["product_id"],
                pm["product_name"],
                pm["product_role"],
                pm["shadow_sub_role"],
                pm["owner_brand_id"],
                pm["owner_brand_name"],
                pm["owner_peer_id"],
                pm["owner_peer_name"],
                pm["mention_position"],
                result["ingested_at"],
            )

        # --- geo_citations (v1.2 citation_role + matched_* + domain_category) ---
        for c in citations:
            # Spec §6 Stage 3 fallback: when citation_role is None the
            # global classifier's category fills the slot; otherwise we
            # still record it so dashboards can split site-nature vs
            # citation-role independently. Missing domain → "Other".
            final_category = domain_categories.get(
                c.get("source_domain", "").lower(), "Other"
            )

            await conn.execute(
                """
                INSERT INTO geo_citations
                (client_prompt_id, task_id, result_id, client_id,
                 source_url, source_domain, source_position, source_label,
                 is_citation_pill, domain_category,
                 citation_role, matched_brand_id, matched_product_id, matched_peer_id,
                 executed_at)
                VALUES ($1, $2, $3, $4,
                        $5, $6, $7, $8,
                        $9, $10,
                        $11, $12, $13, $14,
                        $15)
                """,
                result["client_prompt_id"],
                result["task_id"],
                result["result_id"],
                result["client_id"],
                c["source_url"],
                c["source_domain"],
                c.get("source_position"),
                c.get("source_label"),
                c["is_citation_pill"],
                final_category,
                c.get("citation_role"),
                c.get("matched_brand_id"),
                c.get("matched_product_id"),
                c.get("matched_peer_id"),
                result["ingested_at"],
            )

        # Mark this row analyzed so the main loop terminates.
        await conn.execute(
            "UPDATE geo_results SET analyzed_at = NOW() WHERE result_id = $1",
            result["result_id"],
        )

        counts.brand_mentions += len(brand_mentions)
        counts.product_mentions += len(product_mentions)
        counts.citations += len(citations)

    return counts
