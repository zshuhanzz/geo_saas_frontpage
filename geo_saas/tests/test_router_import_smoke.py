"""
Router import smoke tests — v1.2 dual-mode tracking.

These tests don't exercise HTTP behaviour (that requires a live DB and event
loop), but they DO guarantee every router module is syntactically valid and
its imports resolve against the new schema adapter.

If any ``from database import ...`` references a table that was dropped /
renamed without a compat alias, these tests fail immediately at collection.
"""
from __future__ import annotations

import importlib

import pytest


ROUTER_MODULES = [
    "routers.settings",
    "routers.clients",
    "routers.brainstorming",
    "routers.sentiment",
    "routers.globals",
    "routers.prompts",
    "routers.insights",
    "routers.insights.visibility",
    "routers.insights.citations",
    "routers.insights.prompt_metrics",
    "routers.insights.cited_pages",
    "routers.insights.cited_domains",
    "routers.insights.fanouts",
    "routers.insights.availability",
    "routers.insights.product_visibility",
    "routers.insights.shadow_cooccurrence",
    "routers.insights.citation_role",
    "routers.insights.product_sentiment",
    "routers.insights.peer_sov",
    "routers.onboarding",
]


@pytest.mark.parametrize("module", ROUTER_MODULES)
def test_router_module_imports(module):
    mod = importlib.import_module(module)
    assert mod is not None


def test_main_app_builds():
    """Importing main.py should construct the FastAPI app without errors.

    We don't start the lifespan (which would try to connect to Postgres); we
    merely ensure ``app.routes`` is populated, i.e. every ``include_router``
    call succeeded.
    """
    from main import app
    assert app is not None
    # FastAPI 0.124+ may keep included routers as lazy ``_IncludedRouter``
    # entries in ``app.routes``.  The generated OpenAPI contract is the stable
    # public surface and forces those routers to be resolved.
    schema = app.openapi()
    route_paths = set(schema["paths"])
    # Health route + at least the new /availability endpoint should exist
    assert "/health" in route_paths
    assert "/api/insights/availability" in route_paths
    assert "/api/insights/product-visibility" in route_paths
    assert "/api/insights/shadow-product-cooccurrence" in route_paths
    assert "/api/insights/shadow-peer-product-cooccurrence" in route_paths
    assert "/api/insights/citation-by-role" in route_paths
    assert "/api/insights/cited-domains" in route_paths
    assert "/api/insights/cited-domains/count" in route_paths
    assert "/api/insights/cited-pages" in route_paths
    assert "/api/insights/cited-pages/count" in route_paths
    assert "/api/insights/product-sentiment-by-role" in route_paths
    assert "/api/insights/peer-sov-via-list" in route_paths
    # Settings endpoints
    assert "/api/settings/brands" in route_paths
    assert "/api/settings/onboarding_status" in route_paths
    assert "/api/settings/complete_onboarding" in route_paths
    # Phase 6 — Suggestions system endpoints
    assert "/api/settings/candidates" in route_paths
    assert "/api/settings/candidates/counts" in route_paths
    assert "/api/settings/candidates/{candidate_id}/accept" in route_paths
    assert "/api/settings/candidates/{candidate_id}/reject" in route_paths
    assert "/api/settings/candidates/{candidate_id}/ignore" in route_paths
    assert "/api/onboarding/auto_discovery" in route_paths
    # Auth/profile endpoints and prompt paths should be canonical without
    # relying on 307 slash redirects, because some browser flows can drop auth
    # headers across redirects.
    assert "/api/me" in route_paths
    assert "/api/prompts" in route_paths
    assert "/api/prompts/batch-delete" in route_paths
    paths = schema["paths"]
    batch_delete = paths["/api/prompts/batch-delete"]["post"]
    body_ref = batch_delete["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert body_ref.endswith("/BatchDeleteInput")
    batch_schema = schema["components"]["schemas"]["BatchDeleteInput"]
    assert batch_schema["properties"]["batch_size"] == {
        "type": "integer",
        "maximum": 100.0,
        "minimum": 1.0,
        "default": 25,
        "title": "Batch Size",
    }
    assert batch_schema["properties"]["prompt_ids"]["maxItems"] == 100
