"""
Shared helpers for the ``settings/`` router package.

Phase 3A.2 refactor (2026-04-25): extracted from monolithic ``routers/settings.py``
so each sub-router can import the same serialization + validation primitives
without re-defining them.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException

__all__ = ["serialize_row", "_normalize_host", "_validate_owner_exclusive"]


def serialize_row(row) -> dict:
    """Serialize asyncpg.Record (or any dict-like row) → JSON-safe dict.

    UUID columns are stringified, datetime columns are isoformatted. Returns
    ``{}`` for ``None`` so call sites can ``serialize_row(row) | {...}``
    safely.
    """
    if row is None:
        return {}
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


def _normalize_host(url: str) -> Optional[str]:
    """Extract lowercased host without leading www. from a URL.

    Returns None if the URL cannot be parsed to a host. Kept loose on purpose:
    users routinely paste "example.com/path" without a scheme, so we prefix
    ``https://`` when missing before parsing.
    """
    if not url:
        return None
    u = url.strip()
    if not re.match(r"^https?://", u, re.IGNORECASE):
        u = "https://" + u
    try:
        host = urlparse(u).netloc.lower()
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _validate_owner_exclusive(brand_id, peer_id) -> None:
    """A domain or tracked URL may belong to a Brand OR a Peer, not both."""
    if brand_id is not None and peer_id is not None:
        raise HTTPException(
            status_code=422,
            detail="A domain (or tracked URL) may belong to a Brand OR a Peer, not both.",
        )
