"""
Phase 2a — Batch-classify the unique source domains seen in this batch.

Thin wrapper around ``domain_classifier.classify_domains`` that hides the
extra ``owned_domain_strs`` plumbing from ``main.py``.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Set

from src.parsers.domain_classifier import classify_domains

logger = logging.getLogger("GeoAnalyzer.phase2a")


async def classify_batch_domains(
    conn,
    domains: Set[str],
    owned_domain_strs,
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> Dict[str, str]:
    """Classify ``domains`` against the cached mapping table + Gemini.

    ``owned_domain_strs`` is the whole-domain Own Brand subset prepared in
    Phase 0 — those domains are short-circuited to ``"Owned Media"`` without
    a Gemini call.

    Returns a dict mapping ``domain.lower() -> category``.
    """
    logger.info("[ANALYZER-S2] Batch has %d unique domains to classify", len(domains))
    return await classify_domains(
        conn,
        domains,
        owned_domain_strs,
        model_id=model_id,
        model_region_overrides=model_region_overrides,
    )
