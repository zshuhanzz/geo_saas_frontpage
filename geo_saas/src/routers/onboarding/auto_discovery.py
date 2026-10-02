"""
Auto-Discovery onboarding router (Phase 3 onboarding feature).

Phase 3A.5 refactor (2026-04-25): the original 1156-line god-file was split
into 5 focused modules:

    - ``_discovery_models.py``   — Pydantic request/response models
    - ``_discovery_fetchers.py`` — Layer 1-3 helpers (HTTP / sitemap / HTML nav)
    - ``_discovery_llm.py``      — Layer 4 (Gemini synthesis) + heuristic fallback
    - ``_discovery_pipeline.py`` — Main async-generator pipeline orchestrator
    - ``auto_discovery.py`` (this) — FastAPI router + 2 endpoints

Given ``{brand_name, website_url}``, this endpoint tries a 4-layer fallback
strategy to extract a reasonable first-cut list of ``topics`` and ``products``
for the client's Tracking Strategy.

Why 4 layers:
  - Layer 1 (robots.txt → sitemap) is deterministic and cheap when it works.
  - Layer 2 (common sitemap paths) catches sites that serve a sitemap but
    omit the robots.txt hint.
  - Layer 3 (HTML nav/header parsing) catches modern SPA sites where there
    is no machine-readable sitemap but navigation still has category anchors.
  - Layer 4 (Gemini Flash/Pro LLM) is the escape hatch: feed whatever we
    collected (URLs, titles, link text) and let the model synthesize topics
    and products.

This endpoint is intentionally stateless and does NOT write to the DB.
The frontend displays the results, lets the user edit them, and then calls
the existing client/topic endpoints to persist.

Scope note: This is NOT in geo_agent (no LangGraph dependency). Onboarding is
one-off and idempotent; keeping it here avoids dragging agent complexity into
setup.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ._discovery_models import AutoDiscoverRequest, AutoDiscoverResponse
from ._discovery_pipeline import run_discovery_pipeline

logger = logging.getLogger("GeoSaaSAPI.AutoDiscovery")

router = APIRouter(prefix="/api/onboarding")


@router.post("/auto-discover", response_model=AutoDiscoverResponse)
async def auto_discover(data: AutoDiscoverRequest) -> AutoDiscoverResponse:
    """
    Non-streaming variant: runs the pipeline to completion and returns the
    final ``AutoDiscoverResponse``. Used by programmatic callers / tests. The
    frontend modal uses the streaming variant below.
    """
    final_result: Optional[AutoDiscoverResponse] = None
    async for event in run_discovery_pipeline(
        data.brand_name, data.website_url, data.instruction, data.seed_urls,
    ):
        if event.get("type") == "final":
            # Re-validate into the Pydantic model for response_model serialization
            final_result = AutoDiscoverResponse(**event["result"])
    if final_result is None:
        # Defensive: pipeline should always yield a final event
        raise HTTPException(
            status_code=500,
            detail="Auto-discovery pipeline did not produce a final result",
        )
    return final_result


# Streaming response — response_model= incompatible with StreamingResponse
@router.post("/auto-discover/stream")
async def auto_discover_stream(data: AutoDiscoverRequest):
    """
    Streaming variant: pipes every pipeline event to the client as SSE frames.
    Frontend reads via ``fetch()`` + ``ReadableStream`` (matches the
    brainstorming generate pattern) and renders live progress in the
    Auto-Discovery modal.
    """

    async def event_stream():
        try:
            async for event in run_discovery_pipeline(
                data.brand_name, data.website_url, data.instruction, data.seed_urls,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except HTTPException as http_exc:
            yield f"data: {json.dumps({'type': 'error', 'message': http_exc.detail}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("Auto-discovery streaming failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
