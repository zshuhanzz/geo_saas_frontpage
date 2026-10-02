"""Small, deterministic redaction helpers for audit metadata."""

from __future__ import annotations

from collections.abc import Iterable

_SENSITIVE_FRAGMENTS = (
    "authorization",
    "token",
    "secret",
    "password",
    "credential",
    "prompt",
    "message",
    "content",
    "query",
)


def sanitize_query_params(
    items: Iterable[tuple[str, str]],
    *,
    max_value_length: int = 200,
) -> dict[str, str | list[str]]:
    """Keep useful filters/IDs while redacting likely user or secret content."""
    grouped: dict[str, list[str]] = {}
    for raw_key, raw_value in items:
        key = str(raw_key)[:120]
        lowered = key.lower()
        value = (
            "[REDACTED]"
            if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)
            else str(raw_value)[:max_value_length]
        )
        grouped.setdefault(key, []).append(value)
    return {
        key: values[0] if len(values) == 1 else values
        for key, values in grouped.items()
    }
