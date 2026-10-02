"""
LLM topic synthesis (Layer 4) + path-segment heuristic fallback for Auto-Discovery.

Phase 3A.5 refactor (2026-04-25): extracted from monolithic ``auto_discovery.py``.

Two complementary strategies:
    - **Layer 4 (LLM, primary)**: Gemini Flash/Pro receives the harvested
      signals and synthesizes semantic topics + product lines. Always runs,
      even with zero signals (uses model training knowledge for known brands).
    - **Heuristic fallback**: pure path-segment parsing (``/products/foo/bar``
      → topic=products, product=foo). Used only if the LLM is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from geo_common.llm import MODEL_REGION_OVERRIDES_KEY, resolve_model_region

from db import database

from ._discovery_fetchers import MAX_LLM_INPUT_URLS
from ._discovery_models import DiscoveredTopic

logger = logging.getLogger("GeoSaaSAPI.AutoDiscovery")

__all__ = [
    "resolve_auto_discovery_model_id",
    "build_llm_prompt",
    "llm_extract_topics",
    "heuristic_topics_from_urls",
]


async def resolve_auto_discovery_model_id() -> str:
    """
    Resolve the Gemini model ID for Topic & Product Auto-Discovery synthesis.

    Reads from the ``topic_and_product_auto_discovery_model_id`` global setting,
    which is a dedicated key (NOT shared with ``brainstorming_model_id``) so
    Auto-Discovery can run on Pro for higher-quality semantic synthesis while
    the cheaper brainstorming endpoint can stay on Flash.

    Fallback (when the DB row is missing entirely — e.g. a fresh deploy
    forgot to seed the key): ``gemini-3-flash-preview``. Deliberately
    conservative — if the expected row isn't there, use a cheap working
    model rather than silently billing the user for Pro.
    """
    row = await database.fetch_one(
        """
        SELECT value FROM geo_global_settings
        WHERE key = 'topic_and_product_auto_discovery_model_id'
        """
    )
    if row and row["value"]:
        return row["value"]
    return "gemini-3-flash-preview"


async def resolve_model_region_overrides() -> str | None:
    """Resolve optional model-id -> Vertex location overrides."""
    row = await database.fetch_one(
        """
        SELECT value FROM geo_global_settings
        WHERE key = :key
        """,
        {"key": MODEL_REGION_OVERRIDES_KEY},
    )
    return row["value"] if row and row["value"] else None


def build_llm_prompt(
    brand_name: str,
    website_url: str,
    signals: List[Dict[str, str]],
    instruction: Optional[str] = None,
) -> str:
    """
    Build the Gemini prompt for semantic-topic synthesis.

    ``signals`` is a list of ``{url, text}`` pairs harvested by Layers 1-3. When
    the site is a fully client-rendered SPA and we cannot harvest anything, we
    pass an empty list — the prompt explicitly falls back to letting Gemini use
    its training knowledge about the brand. This "zero-signal" path is what
    keeps well-known brands (Roborock, Anker, DJI, Xiaomi, ...) from returning
    an empty onboarding result just because their homepage is JS-hydrated.

    ``instruction`` is an optional free-form steering directive from the user
    (e.g. "output everything in English even though the site is Chinese",
    "only include products in the HT series", "this is a distributor site —
    only extract our brand's SKUs"). It is wrapped in triple quotes and
    declared as the highest-priority constraint below the default rules.
    """
    signals_slice = signals[:MAX_LLM_INPUT_URLS]
    signal_lines = []
    for s in signals_slice:
        line = f"- {s['url']}"
        if s.get("text"):
            line += f"  [{s['text']}]"
        signal_lines.append(line)

    if signal_lines:
        signals_block = "\n".join(signal_lines)
        guidance = (
            "Use these signals as the primary evidence. If the signals are sparse, "
            "you MAY supplement them with your training knowledge of the brand."
        )
    else:
        signals_block = (
            "(no signals were harvestable — the site is likely a client-rendered SPA "
            "or blocked our crawler)"
        )
        guidance = (
            "We could not harvest any signals from the website. Use your training "
            "knowledge of this brand to propose the most likely semantic topics and "
            "product lines. If the brand is unknown to you, return a short best-guess "
            "list based on the domain name rather than an empty result."
        )

    # User steering block — injected with a strong priority marker so Gemini
    # treats it as overriding the defaults (language rule / scope rule below).
    clean_instruction = (instruction or "").strip()
    if clean_instruction:
        instruction_block = (
            "Additional instructions from the user (treat as HIGH-PRIORITY "
            "constraints that override the default language/scope rules when "
            "they conflict):\n"
            '"""\n'
            f"{clean_instruction}\n"
            '"""'
        )
    else:
        instruction_block = "(no additional user instructions — use default rules below)"

    return f"""You are an e-commerce onboarding assistant for a GEO (Generative Engine Optimization) SaaS platform.

Given a brand and whatever website signals we managed to harvest, extract:
- A list of **semantic topics** — broad themes the brand wants to be found for in AI search engines. A topic is NOT a SKU; it is a category of user intent (e.g. "robot vacuums", "wet & dry cleaning", "air purification"). Aim for 3-8 topics.
- A list of **products** — concrete product lines / sub-categories / SKU families. Each product belongs to exactly one topic. Aim for 5-25 products.

Brand name: {brand_name}
Website: {website_url}

Signals:
{signals_block}

Guidance: {guidance}

{instruction_block}

Default output-language rule (overridden by user instructions above if any):
- Use the brand's own language / the site's language for topic and product names.

Default scope rule (overridden by user instructions above if any):
- Extract the full breadth of topics and products the brand covers.
- If the site is a shared marketplace / distributor hosting many brands, it is
  fine to include products from multiple brands UNLESS the user instruction
  narrows the scope.

Return ONLY a JSON object matching this schema exactly — no prose, no markdown fences:
{{
  "topics": [
    {{"topic_name": "<string>", "products": ["<string>", ...]}},
    ...
  ],
  "products": ["<string>", ...]
}}

Rules:
- "products" at the top level is the flat union of all per-topic product lists.
- Deduplicate case-insensitively. Prefer the most commonly used form.
- NEVER return an empty topics array — always provide at least 3 best-effort topics.
""".strip()


async def llm_extract_topics(
    brand_name: str,
    website_url: str,
    signals: List[Dict[str, str]],
    instruction: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    try:
        from google import genai
        from google.genai import types
        import google.auth
    except Exception as exc:
        logger.warning("google-genai not available for auto-discovery: %s", exc)
        return None

    model_id = await resolve_auto_discovery_model_id()
    project_id = os.getenv("GCP_PROJECT_ID")
    region = resolve_model_region(
        model_id,
        overrides_value=await resolve_model_region_overrides(),
        default_region=os.getenv("GCP_REGION", "us-central1"),
        global_region=os.getenv("GCP_REGION_GLOBAL", "global"),
    )
    if not project_id:
        try:
            _, project_id = google.auth.default()
        except Exception:
            pass
    if not project_id:
        logger.warning("GCP_PROJECT_ID not set; skipping LLM layer")
        return None

    prompt_text = build_llm_prompt(brand_name, website_url, signals, instruction)

    try:
        client = genai.Client(vertexai=True, project=project_id, location=region)
        # max_output_tokens bumped from 4096 -> 8192 to accommodate Pro's
        # more verbose output (richer topic/product descriptions) and leave
        # headroom for channel-site cases with 20+ product lines. Pro does
        # NOT consume thinking tokens from this budget, so 8192 is actual
        # content capacity, well above the ~2k-3k typical JSON payload.
        gen_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
            max_output_tokens=8192,
        )
        response = await client.aio.models.generate_content(
            model=model_id,
            contents=prompt_text,
            config=gen_config,
        )
        text = (response.text or "").strip()
        if not text:
            return None
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:
        logger.warning("LLM extraction failed: %s", exc)
        return None


def heuristic_topics_from_urls(urls: List[str]) -> Tuple[List[DiscoveredTopic], List[str]]:
    """
    Very lightweight heuristic: take the first path segment as topic, second
    as product. Used as a pre-LLM signal and as an ultra-fallback if the LLM
    is unavailable.
    """
    topic_products: Dict[str, set] = {}
    for url in urls:
        try:
            parsed = urlparse(url)
            parts = [p for p in parsed.path.split("/") if p]
            if not parts:
                continue
            # Skip file-ish first parts and language codes
            first = parts[0].lower()
            if first in {"en", "cn", "us", "uk", "de", "fr", "jp", "kr", "zh-cn", "en-us"}:
                parts = parts[1:]
            if not parts:
                continue
            if "." in parts[0] or parts[0] in {"blog", "news", "press", "support", "contact", "about"}:
                continue
            topic = parts[0].replace("-", " ").replace("_", " ").strip()
            if not topic:
                continue
            product = None
            if len(parts) >= 2 and "." not in parts[1]:
                product = parts[1].replace("-", " ").replace("_", " ").strip()
            topic_products.setdefault(topic, set())
            if product:
                topic_products[topic].add(product)
        except Exception:
            continue

    topics: List[DiscoveredTopic] = []
    all_products: set = set()
    for topic, prods in sorted(topic_products.items(), key=lambda kv: -len(kv[1])):
        prod_list = sorted(prods)[:20]
        topics.append(DiscoveredTopic(topic_name=topic, products=prod_list))
        all_products.update(prod_list)
        if len(topics) >= 10:
            break
    return topics, sorted(all_products)
