"""Every protected SaaS API route must be declared in the feature registry."""

from __future__ import annotations

from geo_common.permissions import resolve_backend_policies
from main import app


def test_all_protected_saas_routes_are_registered() -> None:
    core_routes = {
        "/api/me",
        "/api/me/workspaces",
        "/api/me/feature-catalog",
        "/api/audit/events",
        "/api/auth/session",
        "/api/auth/logout",
    }
    missing: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in core_routes:
            continue
        for method in (getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}:
            if not resolve_backend_policies("saas", method, path):
                missing.append((method, path))
    assert missing == []
