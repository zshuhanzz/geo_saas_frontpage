"""
Phase 2b — Sentiment extraction in sub-batches.

Splits the per-batch sentiment inputs into smaller LLM batches (responses
are long, ~750 tok each) and extracts sentiment data without writing it.
The main orchestrator persists extracted rows inside the short write
transaction.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from src.parsers.sentiment_parser import extract_sentiment_results
from src.pipeline.phase1_per_result_parse import SentimentInput

logger = logging.getLogger("GeoAnalyzer.phase2b")


# Hardcoded sub-batch size — responses average ~3000 chars / ~750 tokens
# each, and Gemini Flash preview budget is the constraining factor here.
SENTIMENT_BATCH_SIZE = 15


async def extract_sentiment_for_batch(
    sentiment_inputs: List[SentimentInput],
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> dict[int, dict]:
    """Run Phase 2b on the inputs collected in Phase 1.

    Returns the count of inputs that produced persisted sentiment output.
    """
    if not sentiment_inputs:
        return {}

    logger.info(
        "[ANALYZER-S2] Extracting sentiment for %d results (batch_size=%d)",
        len(sentiment_inputs),
        SENTIMENT_BATCH_SIZE,
    )

    extracted: dict[int, dict] = {}
    for i in range(0, len(sentiment_inputs), SENTIMENT_BATCH_SIZE):
        sub_batch = sentiment_inputs[i:i + SENTIMENT_BATCH_SIZE]
        try:
            extracted.update(await extract_sentiment_results(
                sub_batch,
                model_id=model_id,
                model_region_overrides=model_region_overrides,
            ))
        except Exception as exc:
            logger.warning("[ANALYZER-S2] Sentiment sub-batch failed: %s", exc)
    return extracted
