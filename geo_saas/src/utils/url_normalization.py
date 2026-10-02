"""URL normalization helpers for published-page tracking.

The normalized value is used as a stable matching key between user-maintained
Published Pages and citation URLs extracted from AI responses.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UrlNormalizationError(ValueError):
    """Raised when an input cannot be treated as a trackable HTTP(S) URL."""


_TRACKING_PARAMS = {
    "dclid",
    "fbclid",
    "gbraid",
    "gclid",
    "li_fat_id",
    "msclkid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "srsltid",
    "ttclid",
    "twclid",
    "wbraid",
}


def _is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("utm_") or lowered in _TRACKING_PARAMS


def normalize_url(value: str) -> str:
    """Return a canonical-ish URL string suitable for exact matching.

    We intentionally keep meaningful path and non-tracking query parameters:
    product URLs and article URLs can use query params as durable identifiers.
    Fragments and common campaign parameters are removed.
    """

    raw = (value or "").strip()
    if not raw:
        raise UrlNormalizationError("URL is required")

    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UrlNormalizationError("URL must start with http:// or https://")

    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise UrlNormalizationError("URL host is required")

    try:
        port = parts.port
    except ValueError as exc:
        raise UrlNormalizationError("URL port is invalid") from exc

    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"

    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    query = urlencode(sorted(query_pairs), doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))
