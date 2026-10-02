"""Canonical keys shared by every Prompt read/write surface."""

from __future__ import annotations

import re
from typing import Any


def canonical_prompt_text(value: str) -> str:
    """Collapse whitespace, trim, and lowercase like PostgreSQL ``LOWER``."""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def canonical_prompt_logical_key(text: str, topic_id: Any) -> tuple[str, str]:
    return (canonical_prompt_text(text), str(topic_id))


def canonical_prompt_physical_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row["topic_id"]),
        canonical_prompt_text(str(row.get("text", row.get("prompt", "")))),
        str(row.get("platform") or "").strip().lower(),
        str(row.get("country") or "").strip().lower(),
        str(row.get("language") or "").strip().lower(),
    )


def canonical_prompt_metadata(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("product") or "").strip().lower(),
        str(row.get("intent") or "").strip().lower(),
    )
