"""
Phase B — Theme normalization (runs once per analyzer run, after all batches).

Looks up the client's most-common industry from the dictionary (so Gemini
can scope its synonym suggestions), then delegates to
``sentiment_parser.normalize_themes``. Failures here are non-fatal — the
raw theme rows are still queryable; only the canonical labels are missing.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.parsers.sentiment_parser import normalize_themes

logger = logging.getLogger("GeoAnalyzer.phase_b")


async def normalize_themes_for_client(
    conn,
    client_id: str,
    sentiment_model_id: Optional[str],
    model_region_overrides: Optional[str] = None,
) -> None:
    """Run Phase B normalization for ``client_id``.

    No-op when called with no client_id (defensive). Looks up the client's
    inferred industry from prior dictionary usage to give Gemini context.
    """
    if not client_id:
        return

    logger.info(
        "[ANALYZER-S3] Running Phase B: theme normalization for client %s",
        client_id,
    )
    try:
        # Find the most common industry the dictionary has assigned to this
        # client's themes — we use it to scope Gemini's synonym lookup.
        # NULL when the client is brand new (no themes in dictionary yet) →
        # normalize_themes will ask Gemini to infer the industry instead.
        industry_row = await conn.fetchrow(
            """
            SELECT d.industry
            FROM geo_sentiment_themes t
            JOIN geo_sentiment_theme_dictionary d ON d.theme_name = t.theme_name
            WHERE t.client_id = $1 AND d.industry IS NOT NULL
            GROUP BY d.industry ORDER BY COUNT(*) DESC LIMIT 1
            """,
            client_id,
        )
        client_industry = industry_row["industry"] if industry_row else None

        await normalize_themes(
            conn,
            client_id=client_id,
            industry=client_industry,
            model_id=sentiment_model_id,
            model_region_overrides=model_region_overrides,
        )
    except Exception as exc:
        logger.warning("[ANALYZER-S3] Phase B normalization failed (non-fatal): %s", exc)
