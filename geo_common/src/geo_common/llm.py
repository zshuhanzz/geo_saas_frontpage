"""Shared helpers for Gemini / Vertex AI model configuration."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any


MODEL_REGION_OVERRIDES_KEY = "model_region_overrides"


def parse_model_region_overrides(
    overrides_value: str | Mapping[str, Any] | None,
) -> dict[str, str]:
    """Parse the optional model-id -> Vertex location override config.

    The primary format is a JSON object stored in ``geo_global_settings``:
    ``{"gemini-3.5-flash": "global"}``.

    A comma-separated ``model=region`` string is accepted as an operational
    escape hatch for environments where injecting JSON is cumbersome.
    """
    if not overrides_value:
        return {}

    if isinstance(overrides_value, Mapping):
        return {
            str(model_id).strip().lower(): str(region).strip()
            for model_id, region in overrides_value.items()
            if str(model_id).strip() and str(region).strip()
        }

    raw = str(overrides_value).strip()
    if not raw:
        return {}

    parsed: Any
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, Mapping):
        return parse_model_region_overrides(parsed)

    overrides: dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        model_id, region = item.split("=", 1)
        model_id = model_id.strip().lower()
        region = region.strip()
        if model_id and region:
            overrides[model_id] = region
    return overrides


def resolve_model_region(
    model_id: str,
    *,
    overrides_value: str | Mapping[str, Any] | None = None,
    default_region: str | None = None,
    global_region: str | None = None,
) -> str:
    """Resolve the Vertex AI location for a model ID.

    Region overrides are intentionally separate from model-id settings so
    existing ``*_model_id`` rows can remain plain strings. If no override is
    configured, we preserve the legacy behavior: preview models use the global
    endpoint, all other models use the default regional endpoint.
    """
    normalized_model_id = (model_id or "").strip().lower()
    effective_default_region = default_region or os.getenv("GCP_REGION", "us-central1")
    effective_global_region = global_region or os.getenv("GCP_REGION_GLOBAL", "global")

    env_overrides = parse_model_region_overrides(os.getenv("MODEL_REGION_OVERRIDES"))
    configured_overrides = parse_model_region_overrides(overrides_value)
    overrides = {**env_overrides, **configured_overrides}

    configured_region = overrides.get(normalized_model_id)
    if configured_region:
        return configured_region

    if "preview" in normalized_model_id:
        return effective_global_region
    return effective_default_region
