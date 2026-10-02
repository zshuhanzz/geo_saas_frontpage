"""
Backfill Script — Classify domain_category for existing geo_citations records.

This script:
1. Fetches all DISTINCT source_domain from geo_citations WHERE domain_category IS NULL
2. Classifies them using the domain_classifier (mapping table + Gemini)
3. Batch-updates all NULL records with the resolved categories

Usage:
    cd geo_analyzer
    python -m scripts.backfill_domain_categories

Phase 2.5b: ported to async asyncpg via the shared pool.
"""
import asyncio
import os
import sys
import logging

# Add parent dir to path so we can import src modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import database as db
from src.core.database import parse_affected
from src.parsers.domain_classifier import classify_domains

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BackfillDomainCategories")


async def main_async() -> None:
    logger.info("=== Backfill domain_category for existing geo_citations ===")

    pool = await db.connect()
    try:
        async with pool.acquire() as conn:
            # 1. Get all distinct domains with NULL category
            rows = await conn.fetch(
                """
                SELECT DISTINCT source_domain
                FROM geo_citations
                WHERE domain_category IS NULL AND source_domain IS NOT NULL
                """
            )

            domains = {r["source_domain"].lower() for r in rows if r["source_domain"]}
            logger.info(f"Found {len(domains)} unique domains with NULL domain_category")

            if not domains:
                logger.info("Nothing to backfill. Done.")
                return

            # 2. Load all owned domains (across all clients)
            owned_rows = await conn.fetch("SELECT DISTINCT domain FROM geo_client_domains")
            owned_domains = {r["domain"].lower() for r in owned_rows}
            logger.info(f"Loaded {len(owned_domains)} owned domains")

            # 3. Load classifier model from global settings
            model_row = await conn.fetchrow(
                "SELECT value FROM geo_global_settings WHERE key = 'domain_classifier_model_id'"
            )
            classifier_model_id = model_row["value"] if model_row else None
            logger.info(f"Using classifier model: {classifier_model_id or '(env default)'}")

            # 4. Classify all domains
            domain_map = await classify_domains(
                conn, domains, owned_domains, model_id=classifier_model_id,
            )

            logger.info(f"Classified {len(domain_map)} domains")
            for cat in set(domain_map.values()):
                count = sum(1 for v in domain_map.values() if v == cat)
                logger.info(f"  {cat}: {count} domains")

            # 5. Batch update geo_citations. Each per-domain UPDATE is atomic at
            # the statement level; no enclosing transaction since the script is
            # idempotent (re-running just no-ops on already-classified rows).
            updated = 0
            for domain, category in domain_map.items():
                status = await conn.execute(
                    """
                    UPDATE geo_citations
                    SET domain_category = $1
                    WHERE LOWER(source_domain) = $2 AND domain_category IS NULL
                    """,
                    category,
                    domain,
                )
                updated += parse_affected(status)

            logger.info(f"Updated {updated} citation records. Done.")
    finally:
        await db.disconnect()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
