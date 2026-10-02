from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cmp_to_key
import hashlib
import json
from typing import Any


class StaticReportListUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class StaticReportListSpec:
    allowed_metrics: frozenset[str]
    default_sort_by: str
    default_sort_order: str
    tie_dimension_keys: tuple[str, ...]
    parent_dimension_key: str | None = None
    prompt_dimension_key: str | None = None
    search_dimension_keys: tuple[str, ...] = ()
    exact_filters: tuple[tuple[str, str], ...] = ()


def _spec(
    metrics: tuple[str, ...],
    default_sort_by: str,
    default_sort_order: str,
    *tie_dimension_keys: str,
    parent_dimension_key: str | None = None,
    prompt_dimension_key: str | None = None,
    search_dimension_keys: tuple[str, ...] = (),
    exact_filters: tuple[tuple[str, str], ...] = (),
) -> StaticReportListSpec:
    return StaticReportListSpec(
        allowed_metrics=frozenset(metrics),
        default_sort_by=default_sort_by,
        default_sort_order=default_sort_order,
        tie_dimension_keys=tuple(tie_dimension_keys),
        parent_dimension_key=parent_dimension_key,
        prompt_dimension_key=prompt_dimension_key,
        search_dimension_keys=search_dimension_keys,
        exact_filters=exact_filters,
    )


STATIC_REPORT_LIST_SPECS: dict[str, StaticReportListSpec] = {
    "visibility.brand_visibility": _spec(
        ("visibility_pct", "visibility_pct_change", "mention_count"),
        "visibility_pct", "desc", "brand_name",
    ),
    "visibility.brand_sov": _spec(
        ("sov_pct", "sov_pct_change", "visibility_pct", "visibility_pct_change", "mention_count"),
        "sov_pct", "desc", "brand_name",
    ),
    "visibility.brand_position": _spec(
        ("avg_position", "mention_count"),
        "avg_position", "asc", "brand_name",
    ),
    "visibility.topic": _spec(
        ("prompt_count", "total_mentions"), "total_mentions", "desc", "topic_name", "topic_id",
        search_dimension_keys=("topic_name",),
    ),
    "visibility.product": _spec(
        ("prompt_count", "total_mentions"), "total_mentions", "desc", "product",
        search_dimension_keys=("product",),
    ),
    "visibility.topic_prompt": _spec(
        ("total_mentions",), "total_mentions", "desc", "prompt_text", "prompt_id",
        parent_dimension_key="topic_id", search_dimension_keys=("prompt_text",),
    ),
    "visibility.product_prompt": _spec(
        ("total_mentions",), "total_mentions", "desc", "prompt_text", "prompt_id",
        parent_dimension_key="product", search_dimension_keys=("prompt_text",),
    ),
    "visibility.topic_brand": _spec(
        ("rank", "mention_count"), "rank", "asc", "brand_name", "topic_name",
        parent_dimension_key="topic_id", search_dimension_keys=("brand_name",),
    ),
    "visibility.product_brand": _spec(
        ("rank", "mention_count"), "rank", "asc", "brand_name", "product",
        parent_dimension_key="product", search_dimension_keys=("brand_name",),
    ),
    "visibility.topic_prompt_brand": _spec(
        ("rank", "mention_count"), "rank", "asc", "brand_name", "prompt_text",
        parent_dimension_key="topic_id", prompt_dimension_key="prompt_id", search_dimension_keys=("brand_name",),
    ),
    "visibility.product_prompt_brand": _spec(
        ("rank", "mention_count"), "rank", "asc", "brand_name", "prompt_text",
        parent_dimension_key="product", prompt_dimension_key="prompt_id", search_dimension_keys=("brand_name",),
    ),
    "citation.domain": _spec(
        ("citation_count", "share_pct", "change_pct"),
        "citation_count", "desc", "domain",
        search_dimension_keys=("domain", "domain_category"),
    ),
    "citation.page": _spec(
        ("citation_count", "share_pct", "change_pct"),
        "citation_count", "desc", "url", "domain",
        search_dimension_keys=("url", "domain", "domain_category"),
    ),
    "citation.category": _spec(
        ("count", "pct"), "count", "desc", "label",
    ),
    "sentiment.theme": _spec(
        ("occurrence_count", "prev_occurrence_count", "occurrence_change"),
        "occurrence_count", "desc", "theme_name", "sentiment",
        search_dimension_keys=("theme_name",), exact_filters=(("sentiment", "sentiment"),),
    ),
    "prompt.ranking": _spec(
        ("mention_count", "citation_count"), "mention_count", "desc", "prompt_text", "prompt_id",
        search_dimension_keys=("prompt_text", "intent", "platform", "country", "language"),
    ),
    "topic.ranking": _spec(
        ("mention_count", "citation_count"), "mention_count", "desc", "topic_name",
        search_dimension_keys=("topic_name",),
    ),
}


STATIC_REPORT_LIST_DIMENSION_KEYS: dict[str, tuple[str, ...]] = {
    "visibility.brand_visibility": ("brand_name", "company_name", "is_own"),
    "visibility.brand_sov": ("brand_name", "company_name", "is_own"),
    "visibility.brand_position": ("brand_name", "company_name", "is_own"),
    "visibility.topic": ("topic_id", "topic_name"),
    "visibility.product": ("product",),
    "visibility.topic_prompt": ("topic_id", "topic_name", "prompt_id", "prompt_text"),
    "visibility.product_prompt": ("product", "prompt_id", "prompt_text"),
    "visibility.topic_brand": ("topic_id", "topic_name", "brand_name", "is_own"),
    "visibility.product_brand": ("product", "brand_name", "is_own"),
    "visibility.topic_prompt_brand": (
        "topic_id", "topic_name", "prompt_id", "prompt_text", "brand_name", "is_own",
    ),
    "visibility.product_prompt_brand": (
        "product", "prompt_id", "prompt_text", "brand_name", "is_own",
    ),
    "citation.domain": ("domain", "domain_category", "is_own"),
    "citation.page": ("url", "domain", "domain_category", "is_own"),
    "citation.category": ("label",),
    "sentiment.theme": ("theme_name", "sentiment"),
    "prompt.ranking": ("prompt_id", "prompt_text", "intent", "platform", "country", "language"),
    "topic.ranking": ("topic_name",),
}


def stable_static_report_row_key(list_type: str, dimensions: dict[str, Any]) -> str:
    canonical = json.dumps(dimensions, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{list_type}\x1f{canonical}".encode("utf-8")).hexdigest()


def validate_static_report_list_sort(
    list_type: str,
    sort_by: str | None,
    sort_order: str | None,
    limit: int,
    offset: int,
) -> tuple[StaticReportListSpec, str, str]:
    spec = STATIC_REPORT_LIST_SPECS.get(list_type)
    if spec is None:
        raise ValueError("unsupported list_type")
    selected_metric = sort_by or spec.default_sort_by
    if selected_metric not in spec.allowed_metrics:
        raise ValueError("unsupported sort_by for list_type")
    selected_order = (sort_order or spec.default_sort_order).lower()
    if selected_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be asc or desc")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be nonnegative")
    return spec, selected_metric, selected_order


def _dimension_value(row: dict[str, Any], key: str) -> Any:
    if key == "brand_name":
        return row.get("brand_name") or row.get("company_name")
    return row.get(key)


def _numeric_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _row_dimensions(list_type: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in STATIC_REPORT_LIST_DIMENSION_KEYS[list_type]
        if key in row
    }


def sort_static_report_default_rows(
    list_type: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the registry's exact default ordering to in-memory frozen rows."""
    spec = STATIC_REPORT_LIST_SPECS[list_type]

    return sort_static_report_rows(
        list_type,
        rows,
        sort_by=spec.default_sort_by,
        sort_order=spec.default_sort_order,
    )


def sort_static_report_rows(
    list_type: str,
    rows: list[dict[str, Any]],
    *,
    sort_by: str,
    sort_order: str,
) -> list[dict[str, Any]]:
    """Sort a complete frozen list in memory before applying pagination."""
    spec = STATIC_REPORT_LIST_SPECS[list_type]
    if sort_by not in spec.allowed_metrics:
        raise ValueError("unsupported sort_by for list_type")
    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be asc or desc")

    def compare(left: dict[str, Any], right: dict[str, Any]) -> int:
        return compare_static_report_rows(
            list_type,
            left,
            right,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    return sorted((dict(row) for row in rows), key=cmp_to_key(compare))


def compare_static_report_rows(
    list_type: str,
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    sort_by: str,
    sort_order: str,
) -> int:
    """Compare two frozen rows using the public list sorting contract."""
    spec = STATIC_REPORT_LIST_SPECS[list_type]
    if sort_by not in spec.allowed_metrics:
        raise ValueError("unsupported sort_by for list_type")
    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be asc or desc")

    def compare() -> int:
        left_metric = _numeric_value(left.get(sort_by))
        right_metric = _numeric_value(right.get(sort_by))
        if left_metric is None and right_metric is not None:
            return 1
        if right_metric is None and left_metric is not None:
            return -1
        if left_metric is not None and right_metric is not None and left_metric != right_metric:
            result = -1 if left_metric < right_metric else 1
            return result if sort_order == "asc" else -result
        for key in spec.tie_dimension_keys:
            left_tie = str(_dimension_value(left, key) or "").lower()
            right_tie = str(_dimension_value(right, key) or "").lower()
            if left_tie != right_tie:
                return -1 if left_tie < right_tie else 1
        left_key = left.get("row_key") or stable_static_report_row_key(list_type, _row_dimensions(list_type, left))
        right_key = right.get("row_key") or stable_static_report_row_key(list_type, _row_dimensions(list_type, right))
        if left_key != right_key:
            return -1 if left_key < right_key else 1
        left_position = left.get("default_position")
        right_position = right.get("default_position")
        if left_position is None or right_position is None or left_position == right_position:
            return 0
        return -1 if left_position < right_position else 1

    return compare()


def static_report_row_sort_key(
    list_type: str,
    row: dict[str, Any],
    *,
    sort_by: str,
    sort_order: str,
) -> tuple[Any, ...]:
    """Return the comparator-equivalent key used by compact sort indexes."""
    spec = STATIC_REPORT_LIST_SPECS[list_type]
    if sort_by not in spec.allowed_metrics:
        raise ValueError("unsupported sort_by for list_type")
    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be asc or desc")
    metric = _numeric_value(row.get(sort_by))
    ordered_metric = Decimal(0) if metric is None else metric
    if metric is not None and sort_order == "desc":
        ordered_metric = -ordered_metric
    ties = tuple(
        str(_dimension_value(row, key) or "").lower()
        for key in spec.tie_dimension_keys
    )
    row_key = row.get("row_key") or stable_static_report_row_key(
        list_type,
        _row_dimensions(list_type, row),
    )
    position = row.get("default_position")
    return (
        metric is None,
        ordered_metric,
        *ties,
        str(row_key),
        position is None,
        0 if position is None else position,
    )


def sort_visibility_ranking_matrix_defaults(
    groups: list[dict[str, Any]],
    group_kind: str,
) -> list[dict[str, Any]]:
    """Sort groups and every nested collection using the same API registry."""
    if group_kind not in {"topic", "product"}:
        raise ValueError("group_kind must be topic or product")
    prefix = f"visibility.{group_kind}"
    normalized: list[dict[str, Any]] = []
    for source_group in groups:
        group = dict(source_group)
        group["brands"] = sort_static_report_default_rows(f"{prefix}_brand", source_group.get("brands", []))
        prompts: list[dict[str, Any]] = []
        for source_prompt in source_group.get("prompts", []):
            prompt = dict(source_prompt)
            prompt["brands"] = sort_static_report_default_rows(
                f"{prefix}_prompt_brand", source_prompt.get("brands", []),
            )
            prompts.append(prompt)
        group["prompts"] = sort_static_report_default_rows(f"{prefix}_prompt", prompts)
        normalized.append(group)
    return sort_static_report_default_rows(prefix, normalized)
