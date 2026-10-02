"""
Brand Settings package — aggregates 9 sibling sub-routers.

Phase 3A.2 refactor (2026-04-25): the 1793-line monolithic ``routers/settings.py``
was split into focused sibling modules along entity / lifecycle boundaries.
This ``__init__.py`` re-exports a single aggregated ``router`` so the existing
``main.py`` ``app.include_router(settings.router, prefix='/api/settings', ...)``
call continues to work unchanged.

Sub-routers (in mount order):
    - info        — /info, /config, /workflow-config
    - brands      — /brands, /brands/{id}/products
    - peers       — /peers, /peers/{id}/products
    - domains     — /domains
    - topics      — /topics, /topics/bulk, /topics/{id}/products
    - products    — /products/{id}/tracked_urls, /products/{id}/sales_channels
    - personas    — /personas
    - onboarding  — /onboarding_status, /complete_onboarding
    - candidates  — /candidates, /candidates/{id}/accept|reject|ignore

Path coverage is identical to the pre-refactor monolithic router (verified
1:1 against the original via grep). Sub-router tags differ for OpenAPI
clarity ("Brand Settings - Brands" / "- Peers" / etc).
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    brands,
    candidates,
    domains,
    info,
    onboarding,
    peers,
    personas,
    products,
    topics,
)

router = APIRouter()

# Mount order: doesn't strictly matter here since none of the sub-routers
# share path-param prefixes that would collide. Order is by entity/lifecycle:
# read-only first, then entity CRUDs, then sub-resources, then onboarding +
# candidate suggestions on top.
router.include_router(info.router)
router.include_router(brands.router)
router.include_router(peers.router)
router.include_router(domains.router)
router.include_router(topics.router)
router.include_router(products.router)
router.include_router(personas.router)
router.include_router(onboarding.router)
router.include_router(candidates.router)

__all__ = ["router"]
