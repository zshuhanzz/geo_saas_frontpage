"""Onboarding routers — one-off idempotent setup endpoints (Auto-Discovery, etc.)."""

from fastapi import APIRouter
from .auto_discovery import router as auto_discovery_router
from .auto_discovery_candidates import router as auto_discovery_candidates_router

router = APIRouter()
router.include_router(auto_discovery_router, tags=["Onboarding"])
# Phase 6.4 candidate-writing variant — mounts at /api/onboarding/auto_discovery
router.include_router(auto_discovery_candidates_router, tags=["Onboarding"])
