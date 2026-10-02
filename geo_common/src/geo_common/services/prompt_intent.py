"""Database-backed Prompt Intent facets and canonical write validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from geo_common.db import tenant_scoped

from .base import BaseRepository


@dataclass(frozen=True)
class IntentFacets:
    """Current writable values and tenant-scoped read-only history."""

    active: list[str]
    unconfigured: list[str]
    has_unconfigured_blank: bool


class PromptIntentValidationError(ValueError):
    """Raised when a Prompt write does not use an active configured Intent."""

    def __init__(self, message: str, *, code: str, value: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.value = value


def normalize_case_insensitive(value: str) -> str:
    """Normalize exactly like PostgreSQL ``LOWER(TRIM(value))``."""
    return value.strip().lower()


def canonicalize_configured_values(values: Iterable[str]) -> list[str]:
    """Return a deterministic canonical literal for each lowercase key."""
    normalized_values = [str(value).strip() for value in values if str(value).strip()]
    unique: dict[str, str] = {}
    for value in sorted(
        normalized_values,
        key=lambda item: (normalize_case_insensitive(item), item),
    ):
        unique.setdefault(normalize_case_insensitive(value), value)
    return list(unique.values())


class PromptIntentService(BaseRepository):
    """Resolve live Global Config values without hardcoded fallbacks."""

    def __init__(self, pool) -> None:
        super().__init__(pool)
        self._active_names: list[str] | None = None

    async def _load_active(self) -> list[str]:
        if self._active_names is not None:
            return self._active_names

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT intent_name "
                "FROM geo_global_intents "
                "WHERE is_active = TRUE "
                "  AND NULLIF(TRIM(intent_name), '') IS NOT NULL "
                "ORDER BY LOWER(TRIM(intent_name)), TRIM(intent_name)"
            )

        names = canonicalize_configured_values(
            str(row["intent_name"]).strip()
            for row in rows
            if row.get("intent_name") is not None
            and str(row["intent_name"]).strip()
        )
        self._active_names = names
        return names

    @tenant_scoped
    async def facets(self, client_id: str) -> IntentFacets:
        active = await self._load_active()
        active_keys = {normalize_case_insensitive(value) for value in active}

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT NULLIF(TRIM(intent), '') AS intent "
                "FROM geo_client_prompts "
                "WHERE client_id = $1",
                client_id,
            )

        historical: list[str] = []
        blank_present = False
        for row in rows:
            raw = row.get("intent")
            value = str(raw).strip() if raw is not None else ""
            if not value:
                blank_present = True
            elif normalize_case_insensitive(value) not in active_keys:
                historical.append(value)
        return IntentFacets(
            active=list(active),
            unconfigured=canonicalize_configured_values(historical),
            has_unconfigured_blank=blank_present,
        )

    async def require_active(self, value: str | None) -> str:
        """Return the database canonical name or reject the write value."""
        normalized = value.strip() if isinstance(value, str) else ""
        if not normalized:
            raise PromptIntentValidationError(
                "Intent is required",
                code="intent_required",
                value=value,
            )

        for canonical in await self._load_active():
            if normalize_case_insensitive(canonical) == normalize_case_insensitive(normalized):
                return canonical

        raise PromptIntentValidationError(
            "Intent must match an active Global Config value",
            code="intent_not_active",
            value=normalized,
        )

    async def require_active_on_connection(self, conn, value: str | None) -> str:
        """Validate Intent using a caller-owned Prompt-write transaction."""
        normalized = value.strip() if isinstance(value, str) else ""
        if not normalized:
            raise PromptIntentValidationError(
                "Intent is required",
                code="intent_required",
                value=value,
            )

        rows = await conn.fetch(
            "SELECT intent_name "
            "FROM geo_global_intents "
            "WHERE is_active = TRUE "
            "  AND NULLIF(TRIM(intent_name), '') IS NOT NULL "
            "ORDER BY LOWER(TRIM(intent_name)), TRIM(intent_name)"
        )
        active = canonicalize_configured_values(
            str(row["intent_name"]).strip()
            for row in rows
            if row.get("intent_name") is not None
            and str(row["intent_name"]).strip()
        )
        for canonical in active:
            if normalize_case_insensitive(canonical) == normalize_case_insensitive(normalized):
                return canonical

        raise PromptIntentValidationError(
            "Intent must match an active Global Config value",
            code="intent_not_active",
            value=normalized,
        )
