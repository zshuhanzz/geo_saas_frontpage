"""
Insights Router Package — aggregates sub-routers under a single `router`.

v1.2 additions:
- ``availability``        — 9-flag data-driven UI visibility endpoint
- ``product_visibility``  — product-level SOV (Spec §7.2 product_sov_own)
- ``shadow_cooccurrence`` — shadow × (own | shadow) product co-occurrence
- ``citation_role``       — citation breakdown by citation_role
- ``product_sentiment``   — product sentiment by product_role
- ``peer_sov``            — peer SOV via peers-list membership (correctness fix §7.3)
"""
from fastapi import APIRouter
from .visibility import router as visibility_router
from .citations import router as citations_router
from .fanouts import router as fanouts_router
from .prompt_metrics import router as prompt_metrics_router
from .cited_pages import router as cited_pages_router
from .cited_domains import router as cited_domains_router
from .availability import router as availability_router
from .product_visibility import router as product_visibility_router
from .topic_visibility import router as topic_visibility_router
from .shadow_cooccurrence import router as shadow_cooccurrence_router
from .citation_role import router as citation_role_router
from .product_sentiment import router as product_sentiment_router
from .peer_sov import router as peer_sov_router
from .published_url_tracking import router as published_url_tracking_router
from .overview import router as overview_router

router = APIRouter()
router.include_router(overview_router)
router.include_router(visibility_router)
router.include_router(citations_router)
router.include_router(fanouts_router)
router.include_router(prompt_metrics_router)
router.include_router(cited_pages_router)
router.include_router(cited_domains_router)

# v1.2 new endpoints
router.include_router(availability_router)
router.include_router(product_visibility_router)
router.include_router(topic_visibility_router)
router.include_router(shadow_cooccurrence_router)
router.include_router(citation_role_router)
router.include_router(product_sentiment_router)
router.include_router(peer_sov_router)
router.include_router(published_url_tracking_router)
