"""Safe, reusable Product and Prompt target filters for dynamic dashboards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import HTTPException


MAX_PROMPT_FILTER_IDS = 100
MAX_PROMPT_FILTER_CHARS = 4096
MAX_PRODUCT_FILTER_CHARS = 8192
MAX_PRODUCT_FILTER_VALUES = 50
MAX_PRODUCT_VALUE_CHARS = 256
MAX_TARGET_FILTER_CHARS = 8192


@dataclass(frozen=True)
class TargetFilter:
    clause: str
    params: dict[str, str]


def _parse_prompt_ids(prompt_id: Optional[str], prompt_ids: Optional[str]) -> list[str]:
    raw_prompt_id = str(prompt_id) if prompt_id is not None else ""
    raw_prompt_ids = str(prompt_ids) if prompt_ids is not None else ""
    if len(raw_prompt_id) + len(raw_prompt_ids) > MAX_PROMPT_FILTER_CHARS:
        raise HTTPException(status_code=422, detail="Prompt filter is too large")
    raw_values: list[str] = []
    if prompt_id is not None:
        raw_values.append(str(prompt_id).strip())
    if prompt_ids is not None:
        raw_values.extend(value.strip() for value in str(prompt_ids).split(","))

    supplied = prompt_id is not None or prompt_ids is not None
    values = [value for value in raw_values if value]
    if supplied and not values:
        raise HTTPException(status_code=422, detail="Prompt filter must contain at least one UUID")
    if len(values) > MAX_PROMPT_FILTER_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_PROMPT_FILTER_IDS} prompt IDs may be filtered at once",
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            canonical = str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(status_code=422, detail="Invalid prompt UUID") from exc
        if canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)
    if len(normalized) > MAX_PROMPT_FILTER_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_PROMPT_FILTER_IDS} prompt IDs may be filtered at once",
        )
    return normalized


def _parse_products(products: Optional[str]) -> list[str]:
    if products is None:
        return []
    if len(products) > MAX_PRODUCT_FILTER_CHARS:
        raise HTTPException(status_code=422, detail="Product filter is too large")
    raw_values = [value.strip() for value in products.split(",") if value.strip()]
    if len(raw_values) > MAX_PRODUCT_FILTER_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_PRODUCT_FILTER_VALUES} products may be filtered at once",
        )
    if any(len(value) > MAX_PRODUCT_VALUE_CHARS for value in raw_values):
        raise HTTPException(status_code=422, detail="Product filter value is too large")
    values = [value.lower() for value in raw_values]
    if not values:
        raise HTTPException(status_code=422, detail="Product filter must contain a value")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def build_target_filter(
    *,
    products: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    product_column: str = "cp.product",
    prompt_column: str = "c.client_prompt_id",
    prefix: str = "target",
) -> TargetFilter:
    """Build bound SQL predicates for Product and Prompt dashboard targets.

    Column names are supplied only by server-owned call sites. User values are
    always bound parameters. Product values are case-insensitive literals;
    prompt UUIDs from both inputs are unioned and deduplicated.
    """
    raw_total_chars = sum(
        len(str(value))
        for value in (products, prompt_id, prompt_ids)
        if value is not None
    )
    if raw_total_chars > MAX_TARGET_FILTER_CHARS:
        raise HTTPException(status_code=422, detail="Target filter is too large")

    product_values = _parse_products(products)
    prompt_values = _parse_prompt_ids(prompt_id, prompt_ids)
    clauses: list[str] = []
    params: dict[str, str] = {}

    if product_values:
        placeholders = []
        for index, value in enumerate(product_values):
            key = f"{prefix}_product_{index}"
            placeholders.append(f":{key}")
            params[key] = value
        clauses.append(
            f"LOWER(TRIM(COALESCE({product_column}, ''))) IN ({','.join(placeholders)})"
        )

    if prompt_values:
        placeholders = []
        for index, value in enumerate(prompt_values):
            key = f"{prefix}_prompt_{index}"
            placeholders.append(f":{key}")
            params[key] = value
        clauses.append(f"{prompt_column} IN ({','.join(placeholders)})")

    return TargetFilter(clause=" AND ".join(clauses), params=params)
