"""Validated metric sorting shared by dynamic insight endpoints.

Only constants declared in this module can become SQL fragments.  Request
values are used solely as dictionary keys and direction enum values.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from fastapi import HTTPException


class InvalidSortKey(ValueError):
    """Raised when a list does not expose the requested metric."""


class InvalidSortOrder(ValueError):
    """Raised when a direction is not exactly ``asc`` or ``desc``."""


@dataclass(frozen=True)
class MetricSort:
    expression: str
    default_order: str = "desc"


@dataclass(frozen=True)
class ListSortDescriptor:
    metrics: Mapping[str, MetricSort]
    default_metric: str
    tie_breakers: tuple[str, ...]
    tie_fields: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedSort:
    list_type: str
    sort_by: str
    sort_order: str
    expression: str
    direction: str
    tie_breakers: tuple[str, ...]
    tie_fields: tuple[str, ...]

    @property
    def tie_breaker(self) -> str:
        return ", ".join(self.tie_breakers)

    @property
    def tie_field(self) -> str:
        return self.tie_fields[0]

    @property
    def order_by_sql(self) -> str:
        return (
            f"{self.expression} {self.direction} NULLS LAST, "
            + ", ".join(f"{expression} ASC" for expression in self.tie_breakers)
        )


def _metrics(**values: tuple[str, str]) -> Mapping[str, MetricSort]:
    return MappingProxyType(
        {name: MetricSort(expression, direction) for name, (expression, direction) in values.items()}
    )


_DESCRIPTORS: Mapping[str, ListSortDescriptor] = MappingProxyType({
    "visibility_visibility_ranking": ListSortDescriptor(
        metrics=_metrics(
            mention_count=("mention_count", "desc"), visibility_pct=("visibility_pct", "desc"),
            visibility_pct_change=("visibility_pct_change", "desc"),
        ), default_metric="visibility_pct", tie_breakers=("LOWER(brand_name)", "brand_name"), tie_fields=("brand_name", "brand_name"),
    ),
    "visibility_sov_ranking": ListSortDescriptor(
        metrics=_metrics(
            mention_count=("mention_count", "desc"), sov_pct=("sov_pct", "desc"),
            sov_pct_change=("sov_pct_change", "desc"),
        ), default_metric="sov_pct", tie_breakers=("LOWER(brand_name)", "brand_name"), tie_fields=("brand_name", "brand_name"),
    ),
    "visibility_position_ranking": ListSortDescriptor(
        metrics=_metrics(
            mention_count=("mention_count", "desc"), avg_position=("avg_position", "asc"),
        ), default_metric="avg_position", tie_breakers=("LOWER(brand_name)", "brand_name"), tie_fields=("brand_name", "brand_name"),
    ),
    "visibility_matrix_groups": ListSortDescriptor(
        metrics=_metrics(prompt_count=("prompt_count", "desc"), total_mentions=("total_mentions", "desc")),
        default_metric="total_mentions", tie_breakers=("LOWER(group_name)", "group_key"), tie_fields=("group_name", "group_key"),
    ),
    "visibility_matrix_prompts": ListSortDescriptor(
        metrics=_metrics(total_mentions=("total_mentions", "desc")),
        default_metric="total_mentions", tie_breakers=("LOWER(prompt_text)", "prompt_id"), tie_fields=("prompt_text", "prompt_id"),
    ),
    "visibility_matrix_brands": ListSortDescriptor(
        metrics=_metrics(rank=("rank", "asc"), mention_count=("mention_count", "desc")),
        default_metric="rank", tie_breakers=("LOWER(company_name)", "company_name"), tie_fields=("company_name", "company_name"),
    ),
    "visibility_ranking_groups": ListSortDescriptor(
        metrics=_metrics(prompt_count=("prompt_count", "desc"), total_mentions=("total_mentions", "desc")),
        default_metric="total_mentions", tie_breakers=("LOWER(group_name)", "group_key"), tie_fields=("group_name", "group_key"),
    ),
    "visibility_ranking_prompts": ListSortDescriptor(
        metrics=_metrics(total_mentions=("COUNT(*)", "desc")),
        default_metric="total_mentions", tie_breakers=("LOWER(MIN(cp.text))", "MIN(cp.id::text)"), tie_fields=("prompt_text", "prompt_id"),
    ),
    "topic_visibility": ListSortDescriptor(
        metrics=_metrics(
            mention_count=("COUNT(*)", "desc"), own_mention_count=("SUM(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END)", "desc"),
            own_sov_pct=("own_sov_pct", "desc"), sov_pct=("sov_pct", "desc"),
        ),
        default_metric="mention_count", tie_breakers=("LOWER(topic_name)", "topic_id"), tie_fields=("topic_name", "topic_id"),
    ),
    "product_visibility": ListSortDescriptor(
        metrics=_metrics(
            mention_count=("COUNT(*)", "desc"), response_count=("response_count", "desc"),
            visibility_pct=("visibility_pct", "desc"), sov_pct=("sov_pct", "desc"),
            avg_position=("AVG(pm.mention_position)", "asc"),
        ),
        default_metric="mention_count", tie_breakers=("LOWER(pm.product_name)", "pm.product_name", "COALESCE(pm.owner_brand_name, '')", "COALESCE(pm.owner_peer_name, '')", "COALESCE(pm.shadow_sub_role, '')"), tie_fields=("product_name", "product_name", "owner_brand_name", "owner_peer_name", "shadow_sub_role"),
    ),
    "citation_domains": ListSortDescriptor(
        metrics=_metrics(
            citation_count=("citation_count", "desc"), share_pct=("share_pct", "desc"),
            change_pct=("change_pct", "desc"),
        ),
        default_metric="citation_count", tie_breakers=("LOWER(domain)", "domain"), tie_fields=("domain", "domain"),
    ),
    "citation_pages": ListSortDescriptor(
        metrics=_metrics(
            citation_count=("citation_count", "desc"), share_pct=("share_pct", "desc"),
            change_pct=("change_pct", "desc"),
        ),
        default_metric="citation_count", tie_breakers=("LOWER(url)", "url", "domain"), tie_fields=("url", "url", "domain"),
    ),
    "citation_categories": ListSortDescriptor(
        metrics=_metrics(count=("citation_count", "desc"), pct=("pct", "desc")),
        default_metric="count", tie_breakers=("LOWER(domain_category)", "domain_category"), tie_fields=("label", "label"),
    ),
    "published_url_tracking": ListSortDescriptor(
        metrics=_metrics(
            citation_count=("citation_count", "desc"), share_pct=("share_pct", "desc"),
            previous_citation_count=("previous_citation_count", "desc"), change_count=("change_count", "desc"),
            previous_share_pct=("previous_share_pct", "desc"), change_share_pct=("change_share_pct", "desc"),
        ),
        default_metric="citation_count", tie_breakers=("LOWER(published_url)", "published_url_id"), tie_fields=("published_url", "published_url_id"),
    ),
    "published_url_prompts": ListSortDescriptor(
        metrics=_metrics(citation_count=("COUNT(*)", "desc")),
        default_metric="citation_count", tie_breakers=("LOWER(MIN(cp.text))", "MIN(cp.id::text)"), tie_fields=("client_prompt_text", "client_prompt_id"),
    ),
    "published_url_topics": ListSortDescriptor(
        metrics=_metrics(citation_count=("citation_count", "desc")),
        default_metric="citation_count", tie_breakers=("LOWER(topic_name)", "topic_id"), tie_fields=("topic_name", "id"),
    ),
    "published_url_platforms": ListSortDescriptor(
        metrics=_metrics(citation_count=("citation_count", "desc")),
        default_metric="citation_count", tie_breakers=("LOWER(platform)", "platform"), tie_fields=("platform", "platform"),
    ),
    "published_url_countries": ListSortDescriptor(
        metrics=_metrics(citation_count=("citation_count", "desc")),
        default_metric="citation_count", tie_breakers=("LOWER(country)", "country"), tie_fields=("country", "country"),
    ),
    "sentiment_themes": ListSortDescriptor(
        metrics=_metrics(
            occurrence_count=("occurrence_count", "desc"), prev_occurrence_count=("prev_occurrence_count", "desc"),
            occurrence_change=("occurrence_change", "desc"),
        ),
        default_metric="occurrence_count", tie_breakers=("LOWER(theme_name)", "theme_name", "sentiment"), tie_fields=("theme_name", "theme_name", "sentiment"),
    ),
    # Kept as a descriptor boundary so a future aggregate theme-results table
    # cannot accidentally accept dimensions.  The current result endpoint is a
    # pure text/detail list and does not expose these parameters.
    "sentiment_theme_results": ListSortDescriptor(
        metrics=_metrics(positive_percentage=("positive_percentage", "desc")),
        default_metric="positive_percentage", tie_breakers=("st.id",), tie_fields=("id",),
    ),
    "prompt_metrics": ListSortDescriptor(
        metrics=_metrics(
            mentioned=("mentioned", "desc"), total_query=("total_query", "desc"),
            visibility_score=("visibility_score", "desc"), brand_rank=("brand_rank", "asc"),
            avg_position=("avg_position", "asc"), citation_count=("citation_count", "desc"),
        ),
        default_metric="visibility_score", tie_breakers=("prompt_id",), tie_fields=("prompt_id",),
    ),
})


def resolve_sort(list_type: str, sort_by: str | None, sort_order: str | None) -> ResolvedSort:
    try:
        descriptor = _DESCRIPTORS[list_type]
    except KeyError as exc:
        raise InvalidSortKey(f"Unsupported sortable list: {list_type}") from exc

    metric_name = sort_by if sort_by is not None else descriptor.default_metric
    try:
        metric = descriptor.metrics[metric_name]
    except KeyError as exc:
        raise InvalidSortKey(f"Unsupported metric '{metric_name}' for {list_type}") from exc

    order = sort_order if sort_order is not None else metric.default_order
    if order not in ("asc", "desc"):
        raise InvalidSortOrder("sort_order must be exactly 'asc' or 'desc'")
    return ResolvedSort(
        list_type=list_type,
        sort_by=metric_name,
        sort_order=order,
        expression=metric.expression,
        direction=order.upper(),
        tie_breakers=descriptor.tie_breakers,
        tie_fields=descriptor.tie_fields,
    )


def resolve_sort_or_422(list_type: str, sort_by: str | None, sort_order: str | None) -> ResolvedSort:
    """Resolve request parameters before any database work."""
    try:
        return resolve_sort(list_type, sort_by, sort_order)
    except (InvalidSortKey, InvalidSortOrder) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _value(row: Any, field: str) -> Any:
    if isinstance(row, Mapping):
        value = row.get(field)
        if value is None and field == "brand_name":
            value = row.get("company_name")
        return value
    return getattr(row, field, None)


def sort_complete_rows(
    list_type: str,
    rows: Sequence[Any] | Iterable[Any],
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> list[Any]:
    """Return a new list with null-last metric ordering and stable text ties."""
    resolved = resolve_sort(list_type, sort_by, sort_order)

    def compare(left: Any, right: Any) -> int:
        left_value = _value(left, resolved.sort_by)
        right_value = _value(right, resolved.sort_by)
        if left_value is None and right_value is not None:
            return 1
        if left_value is not None and right_value is None:
            return -1
        if left_value is not None and right_value is not None and left_value != right_value:
            result = -1 if left_value < right_value else 1
            return result if resolved.sort_order == "asc" else -result
        for index, field in enumerate(resolved.tie_fields):
            left_field_value = _value(left, field)
            right_field_value = _value(right, field)
            if left_field_value is None and right_field_value is not None:
                return 1
            if left_field_value is not None and right_field_value is None:
                return -1
            left_raw = str(left_field_value or "")
            right_raw = str(right_field_value or "")
            left_tie = left_raw.casefold() if index == 0 else left_raw
            right_tie = right_raw.casefold() if index == 0 else right_raw
            if left_tie != right_tie:
                return -1 if left_tie < right_tie else 1
        return 0

    return sorted(list(rows), key=cmp_to_key(compare))


def materialize_default_ranks(
    list_type: str,
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Freeze canonical one-based ranks before caller-selected ordering."""
    ordered = sort_complete_rows(list_type, rows)
    return [
        {**dict(row), "rank": position}
        for position, row in enumerate(ordered, start=1)
    ]


__all__ = [
    "InvalidSortKey", "InvalidSortOrder", "ListSortDescriptor", "MetricSort",
    "ResolvedSort", "materialize_default_ranks", "resolve_sort", "resolve_sort_or_422",
    "sort_complete_rows",
]
