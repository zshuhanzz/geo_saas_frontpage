"""Every Agent API route must be declared in the feature registry."""

from __future__ import annotations

from geo_common.permissions import resolve_backend_policies
from main import app


def test_all_agent_routes_are_registered() -> None:
    missing: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        for method in (getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}:
            if not resolve_backend_policies("agent", method, path):
                missing.append((method, path))
    assert missing == []
