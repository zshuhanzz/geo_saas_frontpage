"""
google-genai async invocation + tolerant JSON parsing for the LLM Batch
Candidate Discovery job.

Why per-client online ``client.aio.models.generate_content`` (not Vertex
Batch Prediction):

1. Per-client batches stay well under Flash's 30k context; online generate
   is cheap at this volume and has far simpler auth / error handling.
2. Single code path between dev runs and the Cloud Run Job — no batch-file
   upload / polling / timeout dance.

Region routing supports DB-configured model-id overrides. If no override is
present, legacy behavior is preserved: preview models go to
``GCP_REGION_GLOBAL`` and all other models go to ``GCP_REGION``.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

from geo_common.llm import resolve_model_region


logger = logging.getLogger("LLMBatchDiscovery.gemini")


# Flash may eat thinking tokens; 40-sample batches with reasoning need >= 12k.
# Bumped from 4096 after observing truncation in Layer 5b 验证.
MAX_RESPONSE_TOKENS = 16384


async def call_gemini(
    model_id: str,
    prompt: str,
    model_region_overrides: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Call Gemini once, return parsed JSON dict or None on any failure."""
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        logger.warning("google-genai import failed: %s", exc)
        return None

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    if not project_id:
        try:
            import google.auth
            _, project_id = google.auth.default()
        except Exception:
            pass
    if not project_id:
        logger.warning("GCP_PROJECT_ID not set; skipping LLM call")
        return None

    region = resolve_model_region(
        model_id,
        overrides_value=model_region_overrides,
        default_region=os.environ.get("GCP_REGION", "us-central1"),
        global_region=os.environ.get("GCP_REGION_GLOBAL", "global"),
    )

    try:
        client = genai.Client(vertexai=True, project=project_id, location=region)
        # Flash preview eats thinking tokens; for "pure extraction + structured
        # output" tasks we disable internal chain-of-thought via
        # ``thinking_budget=0`` to avoid 16k being eaten halfway through then
        # output truncating mid-stream (observed in Layer 5b 验证).
        thinking_cfg = None
        try:
            thinking_cfg = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass  # Older SDK versions may not expose ThinkingConfig
        gen_cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=MAX_RESPONSE_TOKENS,
            **({"thinking_config": thinking_cfg} if thinking_cfg is not None else {}),
        )
        resp = await client.aio.models.generate_content(
            model=model_id,
            contents=prompt,
            config=gen_cfg,
        )
        raw = (resp.text or "").strip()
        if not raw:
            return None
        return _parse_tolerant_json(raw)
    except Exception as exc:
        logger.warning("Gemini call failed: %s", exc)
        return None


def _parse_tolerant_json(raw: str) -> Optional[Dict[str, Any]]:
    """Strip markdown fences + retry common-malformed cases.

    Gemini preview occasionally outputs:
    - Trailing commas before ``]`` or ``}``
    - Python-style single quotes for short string literals

    We parse strictly first, then run two cleanup passes before giving up.
    Returns the parsed dict or None.
    """
    # Strip accidental markdown fences (```json ... ```)
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()

    # Strict pass.
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    # Cleanup pass 1: trailing commas before ] or }.
    cleaned = re.sub(r',(\s*[}\]])', r'\1', raw)
    # Cleanup pass 2: single quotes → double quotes (conservative — only
    # applies to ``'value':`` and ``'value',`` patterns, not free-text).
    cleaned2 = re.sub(r"(?<!\\)'([^']*?)'(\s*[:,}\]])", r'"\1"\2', cleaned)

    for candidate in (cleaned, cleaned2):
        try:
            data = json.loads(candidate)
            logger.info("JSON decode recovered via tolerant cleanup")
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            continue

    logger.warning(
        "JSON decode failed even after cleanup (first 800 chars): %s",
        raw[:800],
    )
    return None
