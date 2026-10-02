"""
Pydantic request/response models for the Auto-Discovery onboarding endpoint.

Phase 3A.5 refactor (2026-04-25): extracted from monolithic ``auto_discovery.py``
so both the router and the pipeline can import them without circular deps.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

__all__ = ["AutoDiscoverRequest", "DiscoveredTopic", "SeedProduct", "AutoDiscoverResponse"]


class AutoDiscoverRequest(BaseModel):
    brand_name: str = Field(..., min_length=1, max_length=200)
    website_url: str = Field(..., min_length=4, max_length=500)
    # Free-form steering instruction from the user. Treated as a high-priority
    # constraint by the Gemini synthesis prompt (output language, scope
    # narrowing, distributor-site filtering, etc.). Empty string = behave as
    # before. Hard-capped at 800 chars to keep the prompt well within budget
    # and to bound the prompt-injection attack surface (though this endpoint
    # is only exposed to authenticated workspace users, it's good hygiene).
    instruction: Optional[str] = Field(default=None, max_length=800)
    # Optional list of "seed" category / listing URLs. For each one we fetch
    # the HTML and scrape real product-detail links; those links feed Layer 4
    # as high-signal evidence so the LLM doesn't hallucinate SKU paths. Use
    # cases: OEM-on-distributor-channel discovery (e.g. "all products on
    # this Rough Country category page are HT-series Tmax products"), or any
    # brand whose sitemap omits product pages.
    seed_urls: Optional[List[str]] = Field(default=None, max_length=10)


class DiscoveredTopic(BaseModel):
    topic_name: str
    products: List[str] = []


class SeedProduct(BaseModel):
    """A product scraped verbatim from a user-supplied seed (listing) URL.
    Unlike LLM-synthesized ``products`` (strings), seed products carry the
    real product-detail URL so downstream onboarding can write accurate
    ``geo_product_tracked_urls`` rows without the LLM's URL hallucination.
    """
    name: str
    url: str
    source: str = "layer0_seed"


class AutoDiscoverResponse(BaseModel):
    brand_name: str
    website_url: str
    source_layer: str  # "layer0_seed_urls" | "layer1_sitemap" | "layer2_common_paths" | "layer3_html_nav" | "layer4_llm" | "failed"
    topics: List[DiscoveredTopic]
    products: List[str]
    # Seed-scraped products with verified real URLs. Populated only when the
    # user supplied ``seed_urls`` AND Layer 0 succeeded in extracting anchor
    # products. These bypass the LLM entirely (no hallucinated URLs) and
    # are what the onboarding UI should persist into
    # geo_product_tracked_urls when the user accepts them.
    seed_products: List[SeedProduct] = []
    raw_urls_sample: List[str] = []
    notes: List[str] = []
