from __future__ import annotations

import asyncio
import heapq
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from routers.insights._helpers import (
    build_sov_ranking,
    inject_sov_zero_own_brand,
    inject_visibility_zero_own_brand,
    rank_visibility_entries,
)

from .models import (
    MAX_STATIC_REPORT_BLOB_BYTES,
    MAX_STATIC_REPORT_BLOB_ROWS,
    MAX_STATIC_REPORT_LIST_ROWS,
    MAX_STATIC_REPORT_TOTAL_ROWS,
    SNAPSHOT_VERSION,
    RenderingMode,
    ReportDates,
    StaticReportPayloadTooLarge,
    compute_previous_report_dates,
    serialize_record_value,
    serialize_rows,
)
from .repository import static_report_shard_list_type
from .sorting import (
    STATIC_REPORT_LIST_DIMENSION_KEYS,
    STATIC_REPORT_LIST_SPECS,
    sort_static_report_default_rows,
    sort_visibility_ranking_matrix_defaults,
    stable_static_report_row_key,
)

logger = logging.getLogger(__name__)


def _frozen_list_row(
    list_type: str,
    source: dict[str, Any],
    dimension_keys: tuple[str, ...],
    metric_keys: tuple[str, ...],
    default_position: int,
) -> dict[str, Any]:
    registered_dimensions = STATIC_REPORT_LIST_DIMENSION_KEYS[list_type]
    if dimension_keys != registered_dimensions:
        raise ValueError(f"dimension registry mismatch for {list_type}")
    dimensions = {key: serialize_record_value(source.get(key)) for key in dimension_keys if key in source}
    metrics = {key: serialize_record_value(source.get(key)) for key in metric_keys if key in source}
    return {
        "list_type": list_type,
        "row_key": stable_static_report_row_key(list_type, dimensions),
        "dimension_payload": dimensions,
        "metric_payload": metrics,
        "default_position": default_position,
    }


def build_static_report_list_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Split every frozen metric list into immutable dimension/metric rows.

    Private ``_complete_*`` arrays are generation-only payloads. They let the
    online report retain a small default page in ``snapshot_json`` while this
    child table stores the complete historical universe.
    """
    rows: list[dict[str, Any]] = []
    next_positions: dict[str, int] = {}

    def add(
        list_type: str,
        values: list[dict[str, Any]],
        dimensions: tuple[str, ...],
        metrics: tuple[str, ...],
    ) -> None:
        position = next_positions.get(list_type, 0)
        if position + len(values) > MAX_STATIC_REPORT_LIST_ROWS:
            raise StaticReportPayloadTooLarge(
                f"static report list exceeds row limit: {list_type}",
            )
        if len(rows) + len(values) > MAX_STATIC_REPORT_TOTAL_ROWS:
            raise StaticReportPayloadTooLarge("static report exceeds total row limit")
        for value in values:
            rows.append(_frozen_list_row(list_type, dict(value), dimensions, metrics, position))
            position += 1
        next_positions[list_type] = position

    visibility = snapshot.get("visibility", {}).get("dashboard", {})
    add(
        "visibility.brand_visibility",
        visibility.get("_complete_visibility_ranking", visibility.get("visibility_ranking", [])),
        ("brand_name", "company_name", "is_own"),
        ("rank", "visibility_pct", "visibility_pct_change", "mention_count"),
    )
    add(
        "visibility.brand_sov",
        visibility.get("_complete_sov_ranking", visibility.get("sov_ranking", [])),
        ("brand_name", "company_name", "is_own"),
        ("rank", "sov_pct", "sov_pct_change", "visibility_pct", "visibility_pct_change", "mention_count"),
    )
    add(
        "visibility.brand_position",
        visibility.get("_complete_position_ranking", visibility.get("position_ranking", [])),
        ("brand_name", "company_name", "is_own"),
        ("rank", "avg_position", "mention_count"),
    )

    def add_matrix(group_kind: str, values: list[dict[str, Any]]) -> None:
        values = sort_visibility_ranking_matrix_defaults(values, group_kind)
        is_topic = group_kind == "topic"
        group_dimensions = ("topic_id", "topic_name") if is_topic else ("product",)
        prefix = f"visibility.{group_kind}"
        add(prefix, values, group_dimensions, ("prompt_count", "total_mentions"))
        for group in values:
            group_dimensions_payload = {key: group.get(key) for key in group_dimensions}
            for brand in group.get("brands", []):
                add(
                    f"{prefix}_brand",
                    [{**group_dimensions_payload, **dict(brand), "brand_name": brand.get("company_name")}],
                    (*group_dimensions, "brand_name", "is_own"),
                    ("rank", "mention_count"),
                )
            for prompt in group.get("prompts", []):
                prompt_source = {**group_dimensions_payload, **dict(prompt)}
                add(
                    f"{prefix}_prompt",
                    [prompt_source],
                    (*group_dimensions, "prompt_id", "prompt_text"),
                    ("total_mentions",),
                )
                for brand in prompt.get("brands", []):
                    add(
                        f"{prefix}_prompt_brand",
                        [{**prompt_source, **dict(brand), "brand_name": brand.get("company_name")}],
                        (*group_dimensions, "prompt_id", "prompt_text", "brand_name", "is_own"),
                        ("rank", "mention_count"),
                    )

    add_matrix("topic", visibility.get("_complete_topic_sov_ranking", visibility.get("topic_sov_ranking", [])))
    add_matrix("product", visibility.get("_complete_product_sov_ranking", visibility.get("product_sov_ranking", [])))

    citations = snapshot.get("citations", {}).get("dashboard", {})
    add(
        "citation.domain",
        citations.get("_complete_domain_ranking", citations.get("domain_ranking", [])),
        ("domain", "domain_category", "is_own"),
        ("rank", "citation_count", "share_pct", "change_pct"),
    )
    add(
        "citation.page",
        citations.get("_complete_page_ranking", citations.get("page_ranking", [])),
        ("url", "domain", "domain_category", "is_own"),
        ("rank", "citation_count", "share_pct", "change_pct"),
    )
    add(
        "citation.category",
        citations.get("category_breakdown", []),
        ("label",),
        ("count", "pct"),
    )

    sentiment = snapshot.get("sentiment", {}).get("dashboard", {})
    add(
        "sentiment.theme",
        sentiment.get("_complete_themes", sentiment.get("themes", [])),
        ("theme_name", "sentiment"),
        ("occurrence_count", "prev_occurrence_count", "occurrence_change"),
    )
    prompts = snapshot.get("prompts", {})
    add(
        "prompt.ranking",
        prompts.get("_complete_ranking", prompts.get("ranking", [])),
        ("prompt_id", "prompt_text", "intent", "platform", "country", "language"),
        ("mention_count", "citation_count"),
    )
    topics = snapshot.get("topics", {})
    add(
        "topic.ranking",
        topics.get("_complete_ranking", topics.get("ranking", [])),
        ("topic_name",),
        ("mention_count", "citation_count"),
    )
    hydrated_scopes: dict[str, set[tuple[str, str]]] = {}
    for group_kind in ("topic", "product"):
        groups = visibility.get(
            f"_complete_{group_kind}_sov_ranking",
            visibility.get(f"{group_kind}_sov_ranking", []),
        )
        parent_key_name = "topic_id" if group_kind == "topic" else "product"
        parent_scopes = {(str(group.get(parent_key_name) or ""), "") for group in groups}
        hydrated_scopes[f"visibility.{group_kind}_brand"] = parent_scopes
        hydrated_scopes[f"visibility.{group_kind}_prompt"] = parent_scopes
        hydrated_scopes[f"visibility.{group_kind}_prompt_brand"] = {
            (str(group.get(parent_key_name) or ""), str(prompt.get("prompt_id") or ""))
            for group in groups
            for prompt in group.get("prompts", [])
        }

    metadata: dict[str, Any] = {}
    for list_type, spec in STATIC_REPORT_LIST_SPECS.items():
        list_rows = [row for row in rows if row["list_type"] == list_type]
        entry: dict[str, Any] = {
            "total": len(list_rows),
            "default_sort_by": spec.default_sort_by,
            "default_sort_order": spec.default_sort_order,
        }
        if spec.parent_dimension_key:
            scoped_counts: dict[tuple[str, str], int] = {}
            for row in list_rows:
                dimensions = row["dimension_payload"]
                parent_key = str(dimensions.get(spec.parent_dimension_key) or "")
                prompt_key = str(dimensions.get(spec.prompt_dimension_key) or "") if spec.prompt_dimension_key else ""
                scoped_counts[(parent_key, prompt_key)] = scoped_counts.get((parent_key, prompt_key), 0) + 1
            allowed_scopes = hydrated_scopes.get(list_type, set())
            entry["scopes"] = [
                {"parent_key": parent_key, "prompt_key": prompt_key, "total": total}
                for (parent_key, prompt_key), total in sorted(scoped_counts.items())
                if (parent_key, prompt_key) in allowed_scopes
            ]
        metadata[list_type] = entry
    snapshot["frozen_lists"] = metadata
    return rows


def _flatten_frozen_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_key": row["row_key"],
        **row["dimension_payload"],
        **row["metric_payload"],
        "default_position": row["default_position"],
    }


def _public_frozen_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"row_key", "default_position"}}


def _apply_canonical_default_pages(
    snapshot: dict[str, Any],
    grouped_rows: dict[str, list[dict[str, Any]]],
) -> None:
    """Derive every online/offline default list from the canonical blob rows."""
    visibility = snapshot.setdefault("visibility", {}).setdefault("dashboard", {})
    visibility["visibility_ranking"] = [
        _public_frozen_row(row) for row in grouped_rows["visibility.brand_visibility"][:20]
    ]
    visibility["sov_ranking"] = [
        _public_frozen_row(row) for row in grouped_rows["visibility.brand_sov"][:20]
    ]
    visibility["position_ranking"] = [
        _public_frozen_row(row) for row in grouped_rows["visibility.brand_position"][:20]
    ]

    def matrix(group_kind: str) -> list[dict[str, Any]]:
        prefix = f"visibility.{group_kind}"
        parent_key = "topic_id" if group_kind == "topic" else "product"
        result: list[dict[str, Any]] = []
        for group_row in grouped_rows[prefix][:20]:
            parent_value = str(group_row.get(parent_key) or "")
            group = _public_frozen_row(group_row)
            group["brands"] = [
                _public_frozen_row(row)
                for row in grouped_rows[f"{prefix}_brand"]
                if str(row.get(parent_key) or "") == parent_value
            ][:20]
            prompts: list[dict[str, Any]] = []
            for prompt_row in grouped_rows[f"{prefix}_prompt"]:
                if str(prompt_row.get(parent_key) or "") != parent_value:
                    continue
                prompt = _public_frozen_row(prompt_row)
                prompt_value = str(prompt_row.get("prompt_id") or "")
                prompt["brands"] = [
                    _public_frozen_row(row)
                    for row in grouped_rows[f"{prefix}_prompt_brand"]
                    if str(row.get(parent_key) or "") == parent_value
                    and str(row.get("prompt_id") or "") == prompt_value
                ][:20]
                prompts.append(prompt)
                if len(prompts) == 20:
                    break
            group["prompts"] = prompts
            result.append(group)
        return result

    visibility["topic_sov_ranking"] = matrix("topic")
    visibility["product_sov_ranking"] = matrix("product")

    citations = snapshot.setdefault("citations", {}).setdefault("dashboard", {})
    citations["domain_ranking"] = [_public_frozen_row(row) for row in grouped_rows["citation.domain"][:20]]
    citations["page_ranking"] = [_public_frozen_row(row) for row in grouped_rows["citation.page"][:20]]
    citations["category_breakdown"] = [
        _public_frozen_row(row) for row in grouped_rows["citation.category"][:20]
    ]

    sentiment = snapshot.setdefault("sentiment", {}).setdefault("dashboard", {})
    sentiment["themes"] = [_public_frozen_row(row) for row in grouped_rows["sentiment.theme"][:20]]
    snapshot.setdefault("prompts", {})["ranking"] = [
        _public_frozen_row(row) for row in grouped_rows["prompt.ranking"][:20]
    ]
    snapshot.setdefault("topics", {})["ranking"] = [
        _public_frozen_row(row) for row in grouped_rows["topic.ranking"][:20]
    ]


def build_static_report_list_blobs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Build one immutable JSON payload per registered list type.

    The full canonical rows are materialized once. The bounded snapshot lists,
    frozen-list metadata, and persisted blobs are all projections of that same
    canonical collection.
    """
    canonical_rows = build_static_report_list_rows(snapshot)
    grouped_rows: dict[str, list[dict[str, Any]]] = {
        list_type: [] for list_type in STATIC_REPORT_LIST_SPECS
    }
    for row in canonical_rows:
        grouped_rows[row["list_type"]].append(_flatten_frozen_row(row))
    for list_type, rows in grouped_rows.items():
        ordered = sort_static_report_default_rows(list_type, rows)
        grouped_rows[list_type] = [
            {**row, "default_position": position}
            for position, row in enumerate(ordered)
        ]
    _apply_canonical_default_pages(snapshot, grouped_rows)
    blobs: list[dict[str, Any]] = []
    for list_type in STATIC_REPORT_LIST_SPECS:
        rows = grouped_rows[list_type]
        chunks: list[list[dict[str, Any]]] = []
        chunk: list[dict[str, Any]] = []
        # JSON array brackets. Repository serialization uses the default list
        # separator ", ", so account for those two bytes before persisting.
        chunk_bytes = 2
        for row in rows:
            row_bytes = len(json.dumps(row, ensure_ascii=False, default=str).encode("utf-8"))
            separator_bytes = 2 if chunk else 0
            if row_bytes + 2 > MAX_STATIC_REPORT_BLOB_BYTES:
                raise StaticReportPayloadTooLarge(
                    f"static report list row exceeds blob byte limit: {list_type}",
                )
            if chunk and (
                len(chunk) >= MAX_STATIC_REPORT_BLOB_ROWS
                or chunk_bytes + separator_bytes + row_bytes > MAX_STATIC_REPORT_BLOB_BYTES
            ):
                chunks.append(chunk)
                chunk = []
                chunk_bytes = 2
                separator_bytes = 0
            chunk.append(row)
            chunk_bytes += separator_bytes + row_bytes
        chunks.append(chunk)
        for shard_index, shard_rows in enumerate(chunks):
            blobs.append({
                "list_type": static_report_shard_list_type(list_type, shard_index),
                "list_version": SNAPSHOT_VERSION,
                "row_count": len(shard_rows),
                "rows_payload": shard_rows,
            })
    return blobs


def strip_static_report_complete_lists(snapshot: dict[str, Any]) -> None:
    """Remove generation-only full arrays before snapshot_json serialization."""
    for section_name in ("visibility", "citations", "sentiment"):
        dashboard = snapshot.get(section_name, {}).get("dashboard", {})
        for key in tuple(dashboard):
            if key.startswith("_complete_"):
                dashboard.pop(key, None)
    for section_name in ("prompts", "topics"):
        section = snapshot.get(section_name, {})
        for key in tuple(section):
            if key.startswith("_complete_"):
                section.pop(key, None)


def bound_visibility_ranking_matrix(
    groups: list[dict[str, Any]],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Build the useful, bounded offline matrix without mutating full rows."""
    bounded: list[dict[str, Any]] = []
    for source_group in groups[:limit]:
        group = dict(source_group)
        group["brands"] = [dict(row) for row in source_group.get("brands", [])[:limit]]
        prompts: list[dict[str, Any]] = []
        for source_prompt in source_group.get("prompts", [])[:limit]:
            prompt = dict(source_prompt)
            prompt["brands"] = [dict(row) for row in source_prompt.get("brands", [])[:limit]]
            prompts.append(prompt)
        group["prompts"] = prompts
        bounded.append(group)
    return bounded


@dataclass(frozen=True)
class SnapshotFilterConfig:
    """Immutable enabled Global Intent sets shared by one snapshot build."""

    visibility_intents: tuple[str, ...]
    citation_intents: tuple[str, ...]
    sentiment_intents: tuple[str, ...]


def choose_rendering_mode(date_values: list[str]) -> RenderingMode:
    unique_days = {value for value in date_values if value}
    return RenderingMode.MULTI_DAY if len(unique_days) >= 2 else RenderingMode.SINGLE_DAY


def choose_report_rendering_mode(dates: ReportDates, date_values: list[str]) -> RenderingMode:
    if dates.window_days > 1:
        return RenderingMode.MULTI_DAY
    return choose_rendering_mode(date_values)


def report_filter_meta(dates: ReportDates) -> dict[str, Any]:
    previous = compute_previous_report_dates(dates)
    return {
        "date": dates.report_date.isoformat(),
        "timezone": dates.timezone,
        "window_start": dates.window_start.isoformat(),
        "window_end": dates.window_end.isoformat(),
        "window_days": dates.window_days,
        "prev_date_from": previous.window_start.isoformat(),
        "prev_date_to": previous.window_end.isoformat(),
    }


def iter_window_dates(dates: ReportDates) -> list[str]:
    values: list[str] = []
    current = dates.window_start
    while current <= dates.window_end:
        values.append(current.isoformat())
        current += timedelta(days=1)
    return values


def _date_key(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def build_visibility_daily_series(dates: ReportDates, rows: list[Any]) -> list[dict[str, Any]]:
    by_date = {_date_key(row["date"]): row for row in rows}
    return [
        {
            "date": day,
            "score": (
                round((int(row["own_count"] or 0) / int(row["total"])) * 100, 2)
                if row and int(row["total"] or 0) > 0 else None
            ),
            "total": int(row["total"] or 0) if row else 0,
            "own_count": int(row["own_count"] or 0) if row else 0,
        }
        for day in iter_window_dates(dates)
        for row in [by_date.get(day)]
    ]


def build_citation_daily_series(dates: ReportDates, rows: list[Any]) -> list[dict[str, Any]]:
    by_date = {_date_key(row["date"]): row for row in rows}
    return [
        {
            "date": day,
            "own_share": (
                round((int(row["own_citations"] or 0) / int(row["total_citations"])) * 100, 2)
                if row and int(row["total_citations"] or 0) > 0 else None
            ),
            "total_citations": int(row["total_citations"] or 0) if row else 0,
            "own_citations": int(row["own_citations"] or 0) if row else 0,
        }
        for day in iter_window_dates(dates)
        for row in [by_date.get(day)]
    ]


def _sentiment_rated_count(row: Any) -> int:
    if not row:
        return 0
    # V2 can legitimately have rated_count=0 while total_count>0 when every
    # response is Insufficient Evidence. Fall back to total only for legacy
    # aggregate shapes where rated_count is absent altogether.
    if "rated_count" in row:
        return int(row["rated_count"] or 0)
    return int(row["total_count"] or 0)


def build_sentiment_daily_series(dates: ReportDates, rows: list[Any]) -> list[dict[str, Any]]:
    by_date = {_date_key(row["date"]): row for row in rows}
    return [
        {
            "date": day,
            "positive_pct": round((int(row["positive_count"] or 0) / _sentiment_rated_count(row)) * 100, 2)
            if _sentiment_rated_count(row) > 0 else None,
            "mixed_neutral_pct": round((int(row.get("mixed_neutral_count") or 0) / _sentiment_rated_count(row)) * 100, 2)
            if _sentiment_rated_count(row) > 0 else None,
            "negative_pct": round((int(row["negative_count"] or 0) / _sentiment_rated_count(row)) * 100, 2)
            if _sentiment_rated_count(row) > 0 else None,
            "positive_count": int(row["positive_count"] or 0) if row else 0,
            "mixed_neutral_count": int(row.get("mixed_neutral_count") or 0) if row else 0,
            "negative_count": int(row["negative_count"] or 0) if row else 0,
            "insufficient_evidence_count": int(row.get("insufficient_evidence_count") or 0) if row else 0,
            "rated_count": _sentiment_rated_count(row),
            "total_count": int(row["total_count"] or 0) if row else 0,
        }
        for day in iter_window_dates(dates)
        for row in [by_date.get(day)]
    ]


def _difference(current: Any, previous: Any, *, digits: int = 2) -> float | None:
    if current is None or previous is None:
        return None
    return round(float(current) - float(previous), digits)


def _rank_difference(current: Any, previous: Any) -> int | None:
    if current is None or previous is None:
        return None
    return int(current) - int(previous)


def _row_key(row: dict[str, Any], *keys: str) -> tuple[str, ...]:
    return tuple(str(row.get(key) or "") for key in keys)


def _brand_key(row: dict[str, Any]) -> str:
    return str(row.get("brand_name") or row.get("company_name") or "")


def _sentiment_theme_key(row: dict[str, Any]) -> str:
    return "\u001f".join(_row_key(row, "theme_name", "sentiment"))


def materialize_previous_period(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> list[str]:
    """Freeze dashboard-equivalent previous-period fields into current sections.

    Percentage metrics are percentage-point differences. Rank and position deltas
    retain their numeric sign; the UI interprets lower values as improvements.
    """
    warnings: list[str] = []

    current_visibility = current["visibility"]["dashboard"]
    previous_visibility = previous["visibility"]["dashboard"]
    current_visibility_summary = current_visibility.setdefault("summary", {})
    previous_visibility_summary = previous_visibility.get("summary", {})
    previous_total_query = int(previous_visibility_summary.get("total_query") or 0)
    previous_total_mentions = int(previous_visibility_summary.get("total_mentions") or 0)
    has_visibility_responses = previous_total_query > 0
    has_visibility_mentions = previous_total_query > 0
    has_visibility_position = previous_total_mentions > 0 and previous_visibility_summary.get("avg_position") is not None
    if not (has_visibility_responses or has_visibility_mentions or has_visibility_position):
        warnings.append("previous_period_visibility_missing")
    current_visibility_summary["visibility_score_change"] = (
        _difference(current_visibility_summary.get("visibility_score"), previous_visibility_summary.get("visibility_score"))
        if has_visibility_responses else None
    )
    current_visibility_summary["visibility_rank_change"] = (
        _rank_difference(current_visibility_summary.get("visibility_rank"), previous_visibility_summary.get("visibility_rank"))
        if has_visibility_responses else None
    )
    current_visibility_summary["sov_pct_change"] = (
        _difference(current_visibility_summary.get("sov_pct"), previous_visibility_summary.get("sov_pct"))
        if has_visibility_mentions else None
    )
    current_visibility_summary["sov_rank_change"] = (
        _rank_difference(current_visibility_summary.get("sov_rank"), previous_visibility_summary.get("sov_rank"))
        if has_visibility_mentions else None
    )
    current_visibility_summary["avg_position_change"] = (
        _difference(current_visibility_summary.get("avg_position"), previous_visibility_summary.get("avg_position"))
        if has_visibility_position else None
    )
    current_visibility_summary["avg_position_rank_change"] = (
        _rank_difference(current_visibility_summary.get("avg_position_rank"), previous_visibility_summary.get("avg_position_rank"))
        if has_visibility_position else None
    )
    previous_sov_pct_lookup = previous_visibility.get("_sov_pct_lookup") or {
        _brand_key(row): row.get("sov_pct") for row in previous_visibility.get("sov_ranking", [])
    }
    previous_visibility_rows = {
        _brand_key(row): row
        for row in previous_visibility.get(
            "_complete_visibility_ranking",
            previous_visibility.get("visibility_ranking", []),
        )
    }
    for row in current_visibility.get("_complete_sov_ranking", current_visibility.get("sov_ranking", [])):
        previous_sov_pct = previous_sov_pct_lookup.get(_brand_key(row))
        row["sov_pct_change"] = (
            _difference(row.get("sov_pct"), previous_sov_pct)
            if has_visibility_mentions else None
        )
        prior_visibility = previous_visibility_rows.get(_brand_key(row))
        row["visibility_pct_change"] = (
            _difference(row.get("visibility_pct"), prior_visibility.get("visibility_pct"))
            if has_visibility_responses and prior_visibility else None
        )
    for row in current_visibility.get("_complete_visibility_ranking", current_visibility.get("visibility_ranking", [])):
        prior = previous_visibility_rows.get(_brand_key(row))
        row["visibility_pct_change"] = (
            _difference(row.get("visibility_pct"), prior.get("visibility_pct"))
            if has_visibility_responses and prior else None
        )
    current_visibility["prev_time_series"] = previous_visibility.get("time_series", [])
    current_visibility["prev_avg_position_series"] = previous_visibility.get("avg_position_series", [])
    current_visibility["previous"] = {
        "summary": previous_visibility_summary,
        "sov_ranking": previous_visibility.get("sov_ranking", []),
        "visibility_ranking": previous_visibility.get("visibility_ranking", []),
        "position_ranking": previous_visibility.get("position_ranking", []),
        "sov_pct_lookup": {
            _brand_key(row): previous_sov_pct_lookup.get(_brand_key(row))
            for row in current_visibility.get("sov_ranking", [])
            if _brand_key(row) in previous_sov_pct_lookup
        },
    }
    current_visibility.pop("_sov_pct_lookup", None)

    current_citations = current["citations"]["dashboard"]
    previous_citations = previous["citations"]["dashboard"]
    current_citation_summary = current_citations.setdefault("summary", {})
    previous_citation_summary = previous_citations.get("summary", {})
    has_citations = int(previous_citation_summary.get("total_citations") or 0) > 0
    if not has_citations:
        warnings.append("previous_period_citation_missing")
    current_citation_summary["own_domain_share_change"] = (
        _difference(current_citation_summary.get("own_domain_share"), previous_citation_summary.get("own_domain_share"))
        if has_citations else None
    )
    current_citation_summary["own_rank_change"] = (
        _rank_difference(current_citation_summary.get("own_rank"), previous_citation_summary.get("own_rank"))
        if has_citations else None
    )
    previous_domain_lookup = previous_citations.get("_domain_share_lookup") or {
        str(row.get("domain") or ""): row.get("share_pct")
        for row in previous_citations.get("domain_ranking", [])
    }
    previous_page_lookup = previous_citations.get("_page_share_lookup") or {
        "\u001f".join(_row_key(row, "url", "domain")): row.get("share_pct")
        for row in previous_citations.get("page_ranking", [])
    }
    for row in current_citations.get("_complete_domain_ranking", current_citations.get("domain_ranking", [])):
        prior_share = row.pop("_previous_share_pct", None)
        if prior_share is None:
            prior_share = previous_domain_lookup.get(str(row.get("domain") or ""))
        row["change_pct"] = _difference(row.get("share_pct"), prior_share) if has_citations else None
    for row in current_citations.get("_complete_page_ranking", current_citations.get("page_ranking", [])):
        lookup_key = "\u001f".join(_row_key(row, "url", "domain"))
        prior_share = row.pop("_previous_share_pct", None)
        if prior_share is None:
            prior_share = previous_page_lookup.get(lookup_key)
        row["change_pct"] = _difference(row.get("share_pct"), prior_share) if has_citations else None
    current_citations["prev_time_series"] = previous_citations.get("time_series", [])
    current_citations["previous"] = {
        "summary": previous_citation_summary,
        "domain_ranking": previous_citations.get("domain_ranking", []),
        "page_ranking": previous_citations.get("page_ranking", []),
        "domain_share_lookup": {
            str(row.get("domain") or ""): previous_domain_lookup.get(str(row.get("domain") or ""))
            for row in current_citations.get("domain_ranking", [])
            if str(row.get("domain") or "") in previous_domain_lookup
        },
        "page_share_lookup": {
            "\u001f".join(_row_key(row, "url", "domain")): previous_page_lookup.get("\u001f".join(_row_key(row, "url", "domain")))
            for row in current_citations.get("page_ranking", [])
            if "\u001f".join(_row_key(row, "url", "domain")) in previous_page_lookup
        },
    }
    current_citations.pop("_domain_share_lookup", None)
    current_citations.pop("_page_share_lookup", None)

    current_sentiment = current["sentiment"]["dashboard"]
    previous_sentiment = previous["sentiment"]["dashboard"]
    current_sentiment_summary = current_sentiment.setdefault("summary", {})
    previous_sentiment_summary = previous_sentiment.get("summary", {})
    has_sentiment = int(previous_sentiment_summary.get("total_count") or 0) > 0
    if not has_sentiment:
        warnings.append("previous_period_sentiment_missing")
    current_sentiment_summary["positive_pct_change"] = (
        _difference(current_sentiment_summary.get("positive_pct"), previous_sentiment_summary.get("positive_pct"))
        if has_sentiment else None
    )
    previous_theme_counts = previous_sentiment.get("_theme_occurrence_lookup")
    if previous_theme_counts is None:
        previous_theme_counts = {}
        for row in previous_sentiment.get("themes", []):
            theme_key = _sentiment_theme_key(row)
            previous_theme_counts[theme_key] = (
                previous_theme_counts.get(theme_key, 0)
                + int(row.get("occurrence_count") or 0)
            )
    for row in current_sentiment.get("_complete_themes", current_sentiment.get("themes", [])):
        previous_count = previous_theme_counts.get(_sentiment_theme_key(row), 0)
        row["prev_occurrence_count"] = previous_count
        row["occurrence_change"] = int(row.get("occurrence_count") or 0) - previous_count if has_sentiment else None
    current_sentiment["prev_time_series"] = previous_sentiment.get("time_series", [])
    current_sentiment["previous"] = {
        "summary": previous_sentiment_summary,
        "themes": previous_sentiment.get("themes", []),
        "theme_occurrence_lookup": {
            _sentiment_theme_key(row): previous_theme_counts.get(_sentiment_theme_key(row), 0)
            for row in current_sentiment.get("themes", [])
        },
    }
    current_sentiment.pop("_theme_occurrence_lookup", None)
    return warnings


STATIC_REPORT_SOURCE_ROW_LIMIT = 5000
STATIC_REPORT_LIST_LIMIT = 20
CITATION_DISPLAY_LIMIT = STATIC_REPORT_LIST_LIMIT
MAX_STATIC_REPORT_AGGREGATE_ROWS = 50_000
MAX_STATIC_REPORT_AGGREGATE_BYTES = 16 * 1024 * 1024
# Topic/Product/Prompt visibility matrices have one row per physical Prompt ×
# observed brand. Dreamina's real 30-day window is ~77k rows / ~30 MiB, so the
# generic guard rejects a valid monthly report. Keep a separate bounded budget
# with measured headroom instead of removing the guard globally.
MAX_STATIC_REPORT_VISIBILITY_GRANULAR_ROWS = 100_000
MAX_STATIC_REPORT_VISIBILITY_GRANULAR_BYTES = 48 * 1024 * 1024
MAX_STATIC_REPORT_CITATION_PERIOD_ROWS = 300_000
MAX_STATIC_REPORT_CITATION_PERIOD_BYTES = 96 * 1024 * 1024
# Fetch in bounded batches so Cloud SQL Proxy does not turn a large aggregate
# into hundreds of client/server round trips. A 4k batch is still bounded by
# the independent retained-row and serialized-byte guards below.
STATIC_REPORT_AGGREGATE_CURSOR_PREFETCH = 4096


async def fetch_bounded_aggregate_rows(
    conn,
    sql: str,
    *args,
    label: str,
    row_limit: int | None = None,
    byte_limit: int | None = None,
    truncate: bool = False,
) -> list[Any]:
    """Stream one aggregate while bounding retained rows and serialized bytes."""
    effective_row_limit = row_limit or MAX_STATIC_REPORT_AGGREGATE_ROWS
    effective_byte_limit = byte_limit or MAX_STATIC_REPORT_AGGREGATE_BYTES
    sql_limit = effective_row_limit if truncate else effective_row_limit + 1
    statement = f"{sql.rstrip().rstrip(';')}\nLIMIT {sql_limit}"
    rows: list[dict[str, Any]] = []
    retained_bytes = 0
    cursor = conn.cursor(
        statement,
        *args,
        prefetch=STATIC_REPORT_AGGREGATE_CURSOR_PREFETCH,
    )
    async for record in cursor:
        if len(rows) >= effective_row_limit:
            raise StaticReportPayloadTooLarge(f"{label} exceeds {effective_row_limit} rows")
        row = dict(record)
        row_bytes = len(
            json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"),
        )
        if retained_bytes + row_bytes > effective_byte_limit:
            raise StaticReportPayloadTooLarge(f"{label} exceeds {effective_byte_limit} bytes")
        retained_bytes += row_bytes
        rows.append(row)
    return rows


def serialize_limited_rows(rows: list[Any], limit: int = STATIC_REPORT_SOURCE_ROW_LIMIT) -> tuple[list[dict[str, Any]], bool]:
    values = serialize_rows(rows[:limit])
    return values, len(rows) > limit


def build_citation_domain_ranking(
    rows: list[Any],
    own_domains: set[str],
    total_citations: int,
    display_limit: int = CITATION_DISPLAY_LIMIT,
) -> tuple[list[dict[str, Any]], int, int | None]:
    """Build full-universe citation metrics while returning a display-limited list."""
    full_ranking: list[dict[str, Any]] = []
    own_citation_count = 0
    own_rank: int | None = None
    previous_count: int | None = None
    current_rank = 0
    for index, row in enumerate(rows):
        domain = row["source_domain"] or ""
        citation_count = int(row["citation_count"] or 0)
        if previous_count != citation_count:
            current_rank = index + 1
            previous_count = citation_count
        is_own = domain.lower() in own_domains
        if is_own:
            own_citation_count += citation_count
            own_rank = own_rank or current_rank
        full_ranking.append({
            "rank": index + 1,
            "domain": domain,
            "citation_count": citation_count,
            "share_pct": round((citation_count / total_citations * 100), 2) if total_citations else 0,
            "is_own": is_own,
            "domain_category": row["domain_category"] or "Other",
            "change_pct": None,
        })
    return full_ranking[:display_limit], own_citation_count, own_rank


def build_citation_category_breakdown(rows: list[Any], total_citations: int) -> list[dict[str, Any]]:
    return [
        {
            "label": row["domain_category"],
            "count": int(row["citation_count"] or 0),
            "pct": round((int(row["citation_count"] or 0) / total_citations * 100), 2) if total_citations else 0,
        }
        for row in rows
    ]


def empty_snapshot(
    client_id: str,
    client_name: str,
    dates: ReportDates,
    rendering_mode: RenderingMode,
    data_completeness: dict[str, Any],
) -> dict[str, Any]:
    previous_dates = compute_previous_report_dates(dates)
    return {
        "version": SNAPSHOT_VERSION,
        "client": {"id": client_id, "name": client_name},
        "report": {
            "date": dates.report_date.isoformat(),
            "timezone": dates.timezone,
            "window_start": dates.window_start.isoformat(),
            "window_end": dates.window_end.isoformat(),
            "window_days": dates.window_days,
            "previous_window_start": previous_dates.window_start.isoformat(),
            "previous_window_end": previous_dates.window_end.isoformat(),
            "rendering_mode": rendering_mode.value,
            "available_dates": [],
        },
        "data_completeness": data_completeness,
        "filters": {"topics": [], "platforms": []},
        "visibility": {
            "summary": {},
            "ranking": [],
            "ranking_by_day": [],
            "time_series": [],
            "dashboard": {
                "summary": {},
                "sov_ranking": [],
                "visibility_ranking": [],
                "position_ranking": [],
                "topic_sov_ranking": [],
                "product_sov_ranking": [],
                "competitive_series": {},
                "time_series": [],
                "prev_time_series": [],
                "avg_position_series": [],
                "prev_avg_position_series": [],
                "previous": {},
                "source_rows": [],
                "response_source_rows": [],
                "filters": {},
            },
        },
        "citations": {
            "summary": {},
            "domains": [],
            "domains_by_day": [],
            "pages": [],
            "pages_by_day": [],
            "categories": [],
            "categories_by_day": [],
            "dashboard": {
                "summary": {},
                "domain_ranking": [],
                "page_ranking": [],
                "category_breakdown": [],
                "time_series": [],
                "prev_time_series": [],
                "previous": {},
                "source_rows": [],
                "own_domains": [],
                "filters": {},
            },
        },
        "sentiment": {
            "summary": [],
            "summary_by_day": [],
            "themes": [],
            "themes_by_day": [],
            "examples": [],
            "dashboard": {
                "summary": {},
                "time_series": [],
                "prev_time_series": [],
                "previous": {},
                "themes": [],
                "examples": [],
                "source_rows": [],
                "response_source_rows": [],
                "filters": {},
            },
        },
        "prompts": {"ranking": [], "ranking_by_day": []},
        "topics": {"ranking": [], "ranking_by_day": []},
        "narrative": {"zh-CN": {}, "en-US": {}},
    }


async def load_snapshot_filter_config(conn) -> SnapshotFilterConfig:
    """Resolve enabled Global Intents once inside the coordinator snapshot."""
    rows = await conn.fetch(
        """
        SELECT gi.intent_name,
               ARRAY(
                   SELECT jsonb_array_elements_text(COALESCE(gi.categories, '[]'::jsonb))
               ) AS categories
        FROM geo_global_intents gi
        WHERE is_active = TRUE
        ORDER BY intent_name ASC
        """
    )
    by_category: dict[str, list[str]] = {
        "Visibility": [],
        "Citation": [],
        "Sentiment": [],
    }
    for row in rows:
        intent_name = str(row["intent_name"] or "").strip()
        if not intent_name:
            continue
        categories = row["categories"] or []
        for category in by_category:
            if category in categories:
                by_category[category].append(intent_name)
    return SnapshotFilterConfig(
        visibility_intents=tuple(sorted(set(by_category["Visibility"]))),
        citation_intents=tuple(sorted(set(by_category["Citation"]))),
        sentiment_intents=tuple(sorted(set(by_category["Sentiment"]))),
    )


async def load_client_name(conn, client_id: str) -> str:
    return await conn.fetchval(
        "SELECT name FROM geo_clients WHERE id = $1::uuid",
        client_id,
    ) or ""


async def load_primary_own_brand_name(conn, client_id: str) -> str | None:
    row = await conn.fetchrow(
        """
        SELECT brand_name
        FROM geo_client_brands
        WHERE client_id = $1::uuid
          AND is_shadow = FALSE
          AND is_active = TRUE
        ORDER BY created_at ASC, brand_name ASC
        LIMIT 1
        """,
        client_id,
    )
    if not row:
        return None
    return str(row["brand_name"] or "").strip() or None


async def load_filter_options(conn, client_id: str) -> dict[str, Any]:
    topic_rows = await conn.fetch(
        """
        SELECT DISTINCT cp.topic_id::text AS id,
               COALESCE(ct.topic_name, 'Uncategorized') AS name
        FROM geo_client_prompts cp
        LEFT JOIN geo_client_topics ct
          ON ct.id = cp.topic_id
         AND ct.client_id = cp.client_id
        WHERE cp.client_id = $1::uuid
          AND cp.is_active = TRUE
          AND cp.topic_id IS NOT NULL
        ORDER BY name ASC
        """,
        client_id,
    )
    platform_rows = await conn.fetch(
        """
        SELECT DISTINCT cp.platform AS id,
               COALESCE(gp.display_name, cp.platform) AS name
        FROM geo_client_prompts cp
        LEFT JOIN geo_global_platforms gp
          ON gp.platform_id = cp.platform
        WHERE cp.client_id = $1::uuid
          AND cp.is_active = TRUE
          AND cp.platform IS NOT NULL
        ORDER BY name ASC
        """,
        client_id,
    )
    return {
        "topics": serialize_rows(topic_rows),
        "platforms": serialize_rows(platform_rows),
    }


async def load_visibility_snapshot(
    conn,
    client_id: str,
    dates: ReportDates,
    visibility_intents: tuple[str, ...],
) -> dict[str, Any]:
    ranking = await conn.fetch(
        """
        SELECT brand_name, brand_role, COUNT(*)::int AS mention_count,
               ROUND(AVG(mention_position)::numeric, 2) AS avg_position
        FROM geo_brand_mentions
        WHERE client_id = $1::uuid
          AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
        GROUP BY brand_name, brand_role
        ORDER BY mention_count DESC, brand_name ASC
        LIMIT 20
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
    )
    series = await conn.fetch(
        """
        SELECT (executed_at AT TIME ZONE $4)::date AS date,
               brand_role,
               COUNT(*)::int AS mention_count
        FROM geo_brand_mentions
        WHERE client_id = $1::uuid
          AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
        GROUP BY date, brand_role
        ORDER BY date ASC, brand_role ASC
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
    )
    ranking_by_day = await conn.fetch(
        """
        SELECT (executed_at AT TIME ZONE $4)::date AS date,
               brand_name,
               brand_role,
               COUNT(*)::int AS mention_count,
               ROUND(AVG(mention_position)::numeric, 2) AS avg_position
        FROM geo_brand_mentions
        WHERE client_id = $1::uuid
          AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
        GROUP BY date, brand_name, brand_role
        ORDER BY date ASC, mention_count DESC, brand_name ASC
        LIMIT 700
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
    )
    total_mentions = sum(int(row["mention_count"] or 0) for row in ranking)
    own_mentions = sum(
        int(row["mention_count"] or 0)
        for row in ranking
        if row["brand_role"] == "own"
    )
    dashboard = await load_visibility_dashboard_snapshot(
        conn,
        client_id,
        dates,
        visibility_intents,
    )
    return {
        "summary": {
            "total_mentions": total_mentions,
            "own_mentions": own_mentions,
            "visibility_score": dashboard.get("summary", {}).get("visibility_score", 0),
            "mentioned": dashboard.get("summary", {}).get("mentioned", 0),
            "total_query": dashboard.get("summary", {}).get("total_query", 0),
            "sov_pct": dashboard.get("summary", {}).get("sov_pct", 0),
        },
        "ranking": serialize_rows(ranking),
        "ranking_by_day": serialize_rows(ranking_by_day),
        "time_series": serialize_rows(series),
        "dashboard": dashboard,
    }


async def load_visibility_comparison_series(
    conn,
    client_id: str,
    dates: ReportDates,
    visibility_intents: tuple[str, ...] | list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    time_rows = await conn.fetch(
        """
        SELECT (gr.ingested_at AT TIME ZONE $3)::date AS date,
               COUNT(DISTINCT gr.result_id)::int AS total,
               COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END)::int AS own_count
        FROM geo_results gr
        JOIN geo_client_prompts cp
          ON cp.id = gr.client_prompt_id
         AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
         AND bm.brand_role = 'own'
        WHERE gr.client_id = $1::uuid
          AND (gr.ingested_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY (gr.ingested_at AT TIME ZONE $3)::date
        ORDER BY (gr.ingested_at AT TIME ZONE $3)::date ASC
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
    )
    avg_position_rows = await conn.fetch(
        """
        SELECT (bm.executed_at AT TIME ZONE $3)::date AS date,
               ROUND(AVG(bm.mention_position)::numeric, 2) AS avg_position
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp
          ON cp.id = bm.client_prompt_id
         AND cp.client_id = bm.client_id
        WHERE bm.client_id = $1::uuid
          AND bm.brand_role = 'own'
          AND (bm.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY (bm.executed_at AT TIME ZONE $3)::date
        ORDER BY (bm.executed_at AT TIME ZONE $3)::date ASC
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
    )
    time_series = build_visibility_daily_series(dates, time_rows)
    avg_position_by_date = {
        row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]): row
        for row in avg_position_rows
    }
    avg_position_series = [
        {
            "date": day,
            "avg_position": float(row["avg_position"]) if row and row["avg_position"] is not None else None,
        }
        for day in iter_window_dates(dates)
        for row in [avg_position_by_date.get(day)]
    ]
    return time_series, avg_position_series


async def load_visibility_dashboard_snapshot(
    conn,
    client_id: str,
    dates: ReportDates,
    visibility_intents: tuple[str, ...] | list[str],
    *,
    comparison_only: bool = False,
) -> dict[str, Any]:
    if not visibility_intents:
        return {
            "summary": {
                "visibility_score": 0,
                "visibility_rank": None,
                "mentioned": 0,
                "total_query": 0,
                "sov_pct": 0,
                "sov_rank": None,
                "total_mentions": 0,
                "own_mentions": 0,
                "avg_position": None,
                "avg_position_rank": None,
            },
            "sov_ranking": [],
            "visibility_ranking": [],
            "position_ranking": [],
            "topic_sov_ranking": [],
            "product_sov_ranking": [],
            "competitive_series": {},
            "time_series": [],
            "avg_position_series": [],
            "source_rows": [],
            "response_source_rows": [],
            "filters": report_filter_meta(dates),
        }

    mention_summary = await conn.fetchrow(
        """
        SELECT COUNT(*)::int AS total_mentions,
               COUNT(*) FILTER (WHERE bm.brand_role = 'own')::int AS own_mentions,
               ROUND(AVG(bm.mention_position) FILTER (WHERE bm.brand_role = 'own')::numeric, 2) AS own_avg_position
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp
          ON cp.id = bm.client_prompt_id
         AND cp.client_id = bm.client_id
        WHERE bm.client_id = $1::uuid
          AND (bm.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
    )
    total_mentions = int(mention_summary["total_mentions"] or 0) if mention_summary else 0
    own_mentions = int(mention_summary["own_mentions"] or 0) if mention_summary else 0
    own_avg_position = (
        float(mention_summary["own_avg_position"])
        if mention_summary and mention_summary["own_avg_position"] is not None
        else None
    )
    own_sov = round((own_mentions / total_mentions * 100), 2) if total_mentions else 0

    mention_rows = await fetch_bounded_aggregate_rows(
        conn,
        """
        SELECT bm.brand_name,
               COUNT(*)::int AS mention_count,
               MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END)::int AS is_own,
               ROUND(AVG(bm.mention_position)::numeric, 2) AS avg_position
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp
          ON cp.id = bm.client_prompt_id
         AND cp.client_id = bm.client_id
        WHERE bm.client_id = $1::uuid
          AND (bm.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY bm.brand_name
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
        label="visibility brand mention aggregate",
    )
    entries = []
    for row in mention_rows:
        mention_count = int(row["mention_count"] or 0)
        entries.append({
            "company_name": row["brand_name"],
            "brand_name": row["brand_name"],
            "mention_count": mention_count,
            "sov_pct": round((mention_count / total_mentions * 100), 2) if total_mentions else 0,
            "visibility_pct": 0,
            "avg_position": float(row["avg_position"]) if row["avg_position"] is not None else None,
            "is_own": int(row["is_own"] or 0) == 1,
        })

    response_row = await conn.fetchrow(
        """
        SELECT COUNT(DISTINCT gr.result_id)::int AS total_responses,
               COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END)::int AS own_response_count
        FROM geo_results gr
        JOIN geo_client_prompts cp
          ON cp.id = gr.client_prompt_id
         AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
         AND bm.brand_role = 'own'
        WHERE gr.client_id = $1::uuid
          AND (gr.ingested_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
    )
    total_query = int(response_row["total_responses"] or 0) if response_row else 0
    mentioned = int(response_row["own_response_count"] or 0) if response_row else 0
    visibility_score = round((mentioned / total_query * 100), 2) if total_query else 0

    visibility_rows = await fetch_bounded_aggregate_rows(
        conn,
        """
        SELECT bm.brand_name,
               COUNT(DISTINCT gr.result_id)::int AS response_count,
               COUNT(*)::int AS mention_count,
               MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END)::int AS is_own
        FROM geo_results gr
        JOIN geo_client_prompts cp
          ON cp.id = gr.client_prompt_id
         AND cp.client_id = gr.client_id
        JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
        WHERE gr.client_id = $1::uuid
          AND (gr.ingested_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY bm.brand_name
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
        label="visibility brand response aggregate",
    )
    visibility_entries = [
        {
            "company_name": row["brand_name"],
            "brand_name": row["brand_name"],
            "mention_count": int(row["mention_count"] or 0),
            "sov_pct": 0,
            "visibility_pct": round((int(row["response_count"] or 0) / total_query * 100), 2) if total_query else 0,
            "avg_position": None,
            "is_own": int(row["is_own"] or 0) == 1,
        }
        for row in visibility_rows
    ]
    own_brand_name = None
    needs_visibility_zero = total_query > 0 and not any(entry["is_own"] for entry in visibility_entries)
    needs_sov_zero = total_mentions > 0 and not any(entry["is_own"] for entry in entries)
    if needs_visibility_zero or needs_sov_zero:
        own_brand_name = await load_primary_own_brand_name(conn, client_id)
    sov_entries = inject_sov_zero_own_brand(
        entries,
        total_mentions=total_mentions,
        own_brand_name=own_brand_name,
    )
    sov_full = rank_visibility_entries(sov_entries, "mention_count", reverse=True)
    sov_ranking = sov_full[:20]
    sov_pct_lookup = {_brand_key(row): row.get("sov_pct") for row in sov_full}
    sov_rank = next((int(row["rank"]) for row in sov_full if row["is_own"]), None)
    visibility_entries = inject_visibility_zero_own_brand(
        visibility_entries,
        total_responses=total_query,
        own_brand_name=own_brand_name,
    )
    visibility_ranking_full = rank_visibility_entries(visibility_entries, "visibility_pct", reverse=True)
    visibility_rank = next((int(row["rank"]) for row in visibility_ranking_full if row["is_own"]), None)
    position_ranking_full = rank_visibility_entries(
        [entry for entry in entries if entry["avg_position"] is not None],
        "avg_position",
        reverse=False,
    )
    avg_position_rank = next((int(row["rank"]) for row in position_ranking_full if row["is_own"]), None)
    visibility_ranking = visibility_ranking_full[:20]
    position_ranking = position_ranking_full[:20]

    if comparison_only:
        time_series, avg_position_series = await load_visibility_comparison_series(
            conn,
            client_id,
            dates,
            visibility_intents,
        )
        return {
            "summary": {
                "visibility_score": visibility_score,
                "visibility_rank": visibility_rank,
                "mentioned": mentioned,
                "total_query": total_query,
                "sov_pct": own_sov,
                "sov_rank": sov_rank,
                "total_mentions": total_mentions,
                "own_mentions": own_mentions,
                "avg_position": own_avg_position,
                "avg_position_rank": avg_position_rank,
            },
            "sov_ranking": sov_ranking,
            "_complete_sov_ranking": sov_full,
            "_sov_pct_lookup": sov_pct_lookup,
            "visibility_ranking": visibility_ranking,
            "_complete_visibility_ranking": visibility_ranking_full,
            "position_ranking": position_ranking,
            "_complete_position_ranking": position_ranking_full,
            "time_series": time_series,
            "avg_position_series": avg_position_series,
        }

    granular_rows = await fetch_bounded_aggregate_rows(
        conn,
        """
        SELECT cp.topic_id::text AS topic_id,
               COALESCE(ct.topic_name, 'Uncategorized') AS topic_name,
               cp.id::text AS prompt_id,
               cp.text AS prompt_text,
               cp.platform,
               cp.product,
               bm.brand_name AS company_name,
               COUNT(*)::int AS mention_count,
               COUNT(DISTINCT bm.result_id)::int AS response_count,
               ROUND(AVG(bm.mention_position)::numeric, 2) AS avg_position,
               MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END)::int AS is_own
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp
          ON cp.id = bm.client_prompt_id
         AND cp.client_id = bm.client_id
        LEFT JOIN geo_client_topics ct
          ON ct.id = cp.topic_id
         AND ct.client_id = cp.client_id
        WHERE bm.client_id = $1::uuid
          AND (bm.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY cp.topic_id, ct.topic_name, cp.id, cp.text, cp.platform, cp.product, bm.brand_name
        ORDER BY cp.topic_id, cp.id, COUNT(*) DESC
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
        label="visibility granular aggregate",
        row_limit=MAX_STATIC_REPORT_VISIBILITY_GRANULAR_ROWS,
        byte_limit=MAX_STATIC_REPORT_VISIBILITY_GRANULAR_BYTES,
    )
    topic_ranking = build_sov_ranking(
        granular_rows,
        group_key_fn=lambda row: str(row["topic_id"] or "uncategorized"),
        group_name_fn=lambda row: row["topic_name"] or "Uncategorized",
    )
    product_ranking = build_sov_ranking(
        granular_rows,
        group_key_fn=lambda row: dict(row).get("product") or "Uncategorized",
        group_name_fn=lambda row: dict(row).get("product") or "Uncategorized",
    )
    time_rows = await conn.fetch(
        """
        SELECT (gr.ingested_at AT TIME ZONE $3)::date AS date,
               COUNT(DISTINCT gr.result_id)::int AS total,
               COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END)::int AS own_count
        FROM geo_results gr
        JOIN geo_client_prompts cp
          ON cp.id = gr.client_prompt_id
         AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
         AND bm.brand_role = 'own'
        WHERE gr.client_id = $1::uuid
          AND (gr.ingested_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY (gr.ingested_at AT TIME ZONE $3)::date
        ORDER BY (gr.ingested_at AT TIME ZONE $3)::date ASC
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
    )
    avg_position_rows = await conn.fetch(
        """
        SELECT (bm.executed_at AT TIME ZONE $3)::date AS date,
               ROUND(AVG(bm.mention_position)::numeric, 2) AS avg_position
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp
          ON cp.id = bm.client_prompt_id
         AND cp.client_id = bm.client_id
        WHERE bm.client_id = $1::uuid
          AND bm.brand_role = 'own'
          AND (bm.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY (bm.executed_at AT TIME ZONE $3)::date
        ORDER BY (bm.executed_at AT TIME ZONE $3)::date ASC
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        visibility_intents,
        dates.window_end,
    )
    time_series = build_visibility_daily_series(dates, time_rows)
    avg_position_by_date = {
        row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]): row
        for row in avg_position_rows
    }
    avg_position_series = [
        {
            "date": day,
            "avg_position": float(row["avg_position"]) if row and row["avg_position"] is not None else None,
        }
        for day in iter_window_dates(dates)
        for row in [avg_position_by_date.get(day)]
    ]
    topic_matrix = sort_visibility_ranking_matrix_defaults([
        {
            "topic_id": row["group_key"],
            "topic_name": row["group_name"],
            "prompt_count": row["prompt_count"],
            "total_mentions": row["total_mentions"],
            "brands": row["brands"],
            "prompts": row["prompts"],
        }
        for row in topic_ranking
    ], "topic")
    product_matrix = sort_visibility_ranking_matrix_defaults([
        {
            "product": row["group_name"],
            "prompt_count": row["prompt_count"],
            "total_mentions": row["total_mentions"],
            "brands": row["brands"],
            "prompts": row["prompts"],
        }
        for row in product_ranking
    ], "product")

    return {
        "summary": {
            "visibility_score": visibility_score,
            "visibility_score_change": None,
            "visibility_rank": visibility_rank,
            "mentioned": mentioned,
            "total_query": total_query,
            "sov_pct": own_sov,
            "sov_rank": sov_rank,
            "total_mentions": total_mentions,
            "own_mentions": own_mentions,
            "avg_position": own_avg_position,
            "avg_position_change": None,
            "avg_position_rank": avg_position_rank,
        },
        "sov_ranking": sov_ranking,
        "_complete_sov_ranking": sov_full,
        "_sov_pct_lookup": sov_pct_lookup,
        "visibility_ranking": visibility_ranking,
        "_complete_visibility_ranking": visibility_ranking_full,
        "position_ranking": position_ranking,
        "_complete_position_ranking": position_ranking_full,
        "topic_sov_ranking": bound_visibility_ranking_matrix(topic_matrix),
        "product_sov_ranking": bound_visibility_ranking_matrix(product_matrix),
        "_complete_topic_sov_ranking": topic_matrix,
        "_complete_product_sov_ranking": product_matrix,
        "competitive_series": {},
        "time_series": time_series,
        "avg_position_series": avg_position_series,
        "source_rows": [],
        "response_source_rows": [],
        "source_rows_limited": True,
        "response_source_rows_limited": True,
        "filters": report_filter_meta(dates),
    }


async def load_citation_snapshot(
    conn,
    client_id: str,
    dates: ReportDates,
    citation_intents: tuple[str, ...],
) -> dict[str, Any]:
    own_domains, aggregate_rows = await load_citation_aggregate_rows(
        conn, client_id, dates, citation_intents,
    )
    return build_citation_snapshot_from_aggregate_rows(aggregate_rows, own_domains, dates)


def build_citation_snapshot_from_aggregate_rows(
    aggregate_rows: list[dict[str, Any]],
    own_domains: set[str],
    dates: ReportDates,
) -> dict[str, Any]:
    dashboard = build_citation_dashboard_from_aggregate_rows(
        aggregate_rows, own_domains, dates, comparison_only=False,
    )
    domains = [
        {
            "source_domain": row["domain"],
            "domain_category": row["domain_category"],
            "citation_role": "own_domain" if row["is_own"] else "external",
            "citation_count": row["citation_count"],
        }
        for row in dashboard["_complete_domain_ranking"][:20]
    ]
    pages = [
        {
            "source_url": row["url"],
            "source_domain": row["domain"],
            "domain_category": row["domain_category"],
            "citation_count": row["citation_count"],
        }
        for row in dashboard["_complete_page_ranking"][:100]
    ]
    categories = [
        {"domain_category": row["label"], "citation_count": row["count"]}
        for row in dashboard["category_breakdown"]
    ]
    domains_by_day, pages_by_day, categories_by_day = build_citation_legacy_daily_rows(
        aggregate_rows, own_domains,
    )
    total_citations = int(dashboard["summary"]["total_citations"])
    own_citations = int(dashboard["summary"]["own_citation_count"])
    own_share = float(dashboard["summary"]["own_domain_share"])
    return {
        "summary": {
            "total_citations": total_citations,
            "own_citations": own_citations,
            "own_share_pct": own_share,
        },
        "domains": serialize_rows(domains),
        "domains_by_day": serialize_rows(domains_by_day),
        "pages": serialize_rows(pages),
        "pages_by_day": serialize_rows(pages_by_day),
        "categories": serialize_rows(categories),
        "categories_by_day": serialize_rows(categories_by_day),
        "dashboard": dashboard,
    }


async def load_citation_period_snapshots(
    conn,
    client_id: str,
    dates: ReportDates,
    previous_dates: ReportDates,
    citation_intents: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    own_domain_rows = await conn.fetch(
        "SELECT LOWER(domain) AS domain FROM geo_client_domains WHERE client_id = $1::uuid",
        client_id,
    )
    own_domains = {str(row["domain"]) for row in own_domain_rows if row["domain"]}
    period_rows = await fetch_citation_period_aggregate_rows(
        conn, client_id, dates, previous_dates, citation_intents,
    )
    daily_rows = await fetch_citation_period_daily_rows(
        conn, client_id, dates, previous_dates, citation_intents, own_domains,
    )
    return build_citation_period_snapshots_from_aggregate_rows(
        period_rows,
        daily_rows,
        own_domains,
        dates,
        previous_dates,
    )


async def fetch_citation_period_aggregate_rows(
    conn,
    client_id: str,
    dates: ReportDates,
    previous_dates: ReportDates,
    citation_intents: tuple[str, ...] | list[str],
) -> list[dict[str, Any]]:
    """Fetch one row per URL/domain across both comparison periods.

    The former day x URL shape grew to more than half a million rows for a
    Dreamina monthly report. Conditional period aggregation preserves the
    complete current list and its comparison values without transferring that
    high-cardinality intermediate result to Python.
    """
    if not citation_intents:
        return []
    rows = await fetch_bounded_aggregate_rows(
        conn,
        """
        SELECT c.source_url,
               c.source_domain,
               COALESCE(MIN(c.domain_category), 'Other') AS domain_category,
               COUNT(*) FILTER (
                   WHERE (c.executed_at AT TIME ZONE $6)::date BETWEEN $2 AND $3
               )::int AS current_citation_count,
               COUNT(*) FILTER (
                   WHERE (c.executed_at AT TIME ZONE $6)::date BETWEEN $4 AND $5
               )::int AS previous_citation_count
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE c.client_id = $1::uuid
          AND (c.executed_at AT TIME ZONE $6)::date BETWEEN $4 AND $3
          AND cp.intent = ANY($7::text[])
        GROUP BY c.source_url, c.source_domain
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        previous_dates.window_start,
        previous_dates.window_end,
        dates.timezone,
        citation_intents,
        label="citation period aggregate",
        row_limit=MAX_STATIC_REPORT_CITATION_PERIOD_ROWS,
        byte_limit=MAX_STATIC_REPORT_CITATION_PERIOD_BYTES,
    )
    return serialize_rows(rows)


async def fetch_citation_period_daily_rows(
    conn,
    client_id: str,
    dates: ReportDates,
    previous_dates: ReportDates,
    citation_intents: tuple[str, ...] | list[str],
    own_domains: set[str],
) -> list[dict[str, Any]]:
    if not citation_intents:
        return []
    rows = await conn.fetch(
        """
        SELECT (c.executed_at AT TIME ZONE $4)::date AS date,
               COUNT(*)::int AS total_citations,
               COUNT(*) FILTER (
                   WHERE LOWER(c.source_domain) = ANY($6::text[])
               )::int AS own_citations
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE c.client_id = $1::uuid
          AND (c.executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
          AND cp.intent = ANY($5::text[])
        GROUP BY (c.executed_at AT TIME ZONE $4)::date
        ORDER BY (c.executed_at AT TIME ZONE $4)::date ASC
        """,
        client_id,
        previous_dates.window_start,
        dates.window_end,
        dates.timezone,
        citation_intents,
        list(own_domains),
    )
    return serialize_rows(rows)


def build_citation_period_snapshots_from_aggregate_rows(
    rows: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
    own_domains: set[str],
    dates: ReportDates,
    previous_dates: ReportDates,
) -> dict[str, Any]:
    """Build current/previous Citation snapshots from a period-level universe."""
    current_domains: dict[str, dict[str, Any]] = {}
    previous_domains: dict[str, dict[str, Any]] = {}
    current_categories: dict[str, dict[str, Any]] = {}
    current_total = 0
    previous_total = 0

    for row in rows:
        current_count = int(row.get("current_citation_count") or 0)
        previous_count = int(row.get("previous_citation_count") or 0)
        current_total += current_count
        previous_total += previous_count
        domain = str(row.get("source_domain") or "")
        category = str(row.get("domain_category") or "Other")
        if current_count:
            _increment_aggregate(current_domains, domain, {
                "source_domain": domain,
                "domain_category": category,
                "citation_count": current_count,
                "previous_citation_count": previous_count,
            })
            _increment_aggregate(current_categories, category, {
                "domain_category": category,
                "citation_count": current_count,
            })
        if previous_count:
            _increment_aggregate(previous_domains, domain, {
                "source_domain": domain,
                "domain_category": category,
                "citation_count": previous_count,
            })

    current_domain_rows = sorted(
        current_domains.values(),
        key=lambda row: (-int(row["citation_count"]), str(row["source_domain"])),
    )
    current_domain_ranking, own_count, own_rank = build_citation_domain_ranking(
        current_domain_rows, own_domains, current_total, display_limit=len(current_domain_rows),
    )
    previous_domain_rows = sorted(
        previous_domains.values(),
        key=lambda row: (-int(row["citation_count"]), str(row["source_domain"])),
    )
    previous_domain_ranking, previous_own_count, previous_own_rank = build_citation_domain_ranking(
        previous_domain_rows, own_domains, previous_total, display_limit=20,
    )
    previous_domain_share = {
        str(row["source_domain"]): round(int(row["citation_count"]) / previous_total * 100, 2)
        if previous_total else 0
        for row in previous_domain_rows
    }
    for row in current_domain_ranking:
        row["_previous_share_pct"] = previous_domain_share.get(str(row.get("domain") or ""))

    current_page_rows: list[dict[str, Any]] = []
    for row in rows:
        current_count = int(row.get("current_citation_count") or 0)
        previous_count = int(row.get("previous_citation_count") or 0)
        url = row.get("source_url")
        if not url:
            continue
        domain = str(row.get("source_domain") or "")
        category = str(row.get("domain_category") or "Other")
        if current_count:
            current_page_rows.append({
                "url": url,
                "domain": domain,
                "citation_count": current_count,
                "share_pct": round(current_count / current_total * 100, 2) if current_total else 0,
                "is_own": domain.lower() in own_domains,
                "domain_category": category,
                "change_pct": None,
                "_previous_share_pct": round(previous_count / previous_total * 100, 2)
                if previous_total and previous_count else None,
            })
    current_page_rows.sort(key=lambda row: (-int(row["citation_count"]), str(row["url"])))
    for index, row in enumerate(current_page_rows):
        row["rank"] = index + 1
    previous_page_ranking = heapq.nsmallest(20, (
        {
            "url": row.get("source_url"),
            "domain": str(row.get("source_domain") or ""),
            "citation_count": int(row.get("previous_citation_count") or 0),
            "share_pct": round(int(row.get("previous_citation_count") or 0) / previous_total * 100, 2)
            if previous_total else 0,
            "is_own": str(row.get("source_domain") or "").lower() in own_domains,
            "domain_category": str(row.get("domain_category") or "Other"),
            "change_pct": None,
        }
        for row in rows
        if row.get("source_url") and int(row.get("previous_citation_count") or 0) > 0
    ), key=lambda row: (-int(row["citation_count"]), str(row["url"])))
    for index, row in enumerate(previous_page_ranking):
        row["rank"] = index + 1

    current_daily = [
        row for row in daily_rows
        if str(dates.window_start) <= str(row.get("date") or "")[:10] <= str(dates.window_end)
    ]
    previous_daily = [
        row for row in daily_rows
        if str(previous_dates.window_start) <= str(row.get("date") or "")[:10] <= str(previous_dates.window_end)
    ]
    current_time_series = build_citation_daily_series(dates, current_daily)
    previous_time_series = build_citation_daily_series(previous_dates, previous_daily)
    own_share = round(own_count / current_total * 100, 2) if current_total else 0
    previous_own_share = round(previous_own_count / previous_total * 100, 2) if previous_total else 0
    category_rows = sorted(
        current_categories.values(),
        key=lambda row: (-int(row["citation_count"]), str(row["domain_category"])),
    )
    current_dashboard = {
        "summary": {
            "total_citations": current_total,
            "own_domain_share": own_share,
            "own_citation_count": own_count,
            "own_rank": own_rank,
            "own_domain_share_change": None,
        },
        "domain_ranking": current_domain_ranking[:20],
        "_complete_domain_ranking": current_domain_ranking,
        "page_ranking": current_page_rows[:20],
        "_complete_page_ranking": current_page_rows,
        "category_breakdown": build_citation_category_breakdown(category_rows, current_total),
        "time_series": current_time_series,
        "source_rows": [],
        "source_rows_limited": True,
        "own_domains": sorted(own_domains),
        "filters": report_filter_meta(dates),
    }
    current = {
        "summary": {
            "total_citations": current_total,
            "own_citations": own_count,
            "own_share_pct": own_share,
        },
        "domains": serialize_rows([
            {
                "source_domain": row["domain"],
                "domain_category": row["domain_category"],
                "citation_role": "own_domain" if row["is_own"] else "external",
                "citation_count": row["citation_count"],
            }
            for row in current_domain_ranking[:20]
        ]),
        "domains_by_day": [],
        "pages": serialize_rows([
            {
                "source_url": row["url"],
                "source_domain": row["domain"],
                "domain_category": row["domain_category"],
                "citation_count": row["citation_count"],
            }
            for row in current_page_rows[:100]
        ]),
        "pages_by_day": [],
        "categories": serialize_rows([
            {"domain_category": row["label"], "citation_count": row["count"]}
            for row in current_dashboard["category_breakdown"]
        ]),
        "categories_by_day": [],
        "dashboard": current_dashboard,
    }
    previous = {
        "dashboard": {
            "summary": {
                "total_citations": previous_total,
                "own_domain_share": previous_own_share,
                "own_citation_count": previous_own_count,
                "own_rank": previous_own_rank,
            },
            "domain_ranking": previous_domain_ranking,
            "page_ranking": previous_page_ranking,
            "time_series": previous_time_series,
        },
    }
    return {"current": current, "previous": previous}


async def load_citation_aggregate_rows(
    conn,
    client_id: str,
    dates: ReportDates,
    citation_intents: tuple[str, ...] | list[str],
) -> tuple[set[str], list[dict[str, Any]]]:
    own_domain_rows = await conn.fetch(
        "SELECT LOWER(domain) AS domain FROM geo_client_domains WHERE client_id = $1::uuid",
        client_id,
    )
    own_domains = {str(row["domain"]) for row in own_domain_rows if row["domain"]}
    rows = await fetch_citation_aggregate_rows(conn, client_id, dates, citation_intents)
    return own_domains, rows


async def fetch_citation_aggregate_rows(
    conn,
    client_id: str,
    dates: ReportDates,
    citation_intents: tuple[str, ...] | list[str],
) -> list[dict[str, Any]]:
    if not citation_intents:
        return []
    rows = await fetch_bounded_aggregate_rows(
        conn,
        """
        SELECT (c.executed_at AT TIME ZONE $3)::date AS date,
               c.source_url,
               c.source_domain,
               COALESCE(MIN(c.domain_category), 'Other') AS domain_category,
               COUNT(*)::int AS citation_count
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE c.client_id = $1::uuid
          AND (c.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY (c.executed_at AT TIME ZONE $3)::date,
                 c.source_url, c.source_domain
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        citation_intents,
        dates.window_end,
        label="citation aggregate",
    )
    return serialize_rows(rows)


def _increment_aggregate(mapping: dict[Any, dict[str, Any]], key: Any, row: dict[str, Any]) -> None:
    entry = mapping.get(key)
    if entry is None:
        entry = dict(row)
        entry["citation_count"] = 0
        mapping[key] = entry
    entry["citation_count"] += int(row.get("citation_count") or 0)


def build_citation_legacy_daily_rows(
    rows: list[dict[str, Any]],
    own_domains: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    domains: dict[tuple[str, str], dict[str, Any]] = {}
    pages: dict[tuple[str, str], dict[str, Any]] = {}
    categories: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        day = str(row.get("date") or "")
        domain = str(row.get("source_domain") or "")
        category = str(row.get("domain_category") or "Other")
        _increment_aggregate(domains, (day, domain), {
            "date": day,
            "source_domain": domain,
            "domain_category": category,
            "citation_role": "own_domain" if domain.lower() in own_domains else "external",
            "citation_count": row.get("citation_count"),
        })
        url = row.get("source_url")
        if url:
            _increment_aggregate(pages, (day, str(url)), {
                "date": day,
                "source_url": url,
                "source_domain": domain,
                "domain_category": category,
                "citation_count": row.get("citation_count"),
            })
        _increment_aggregate(categories, (day, category), {
            "date": day,
            "domain_category": category,
            "citation_count": row.get("citation_count"),
        })
    order = lambda item: (str(item.get("date") or ""), -int(item.get("citation_count") or 0))
    return (
        sorted(domains.values(), key=order)[:140],
        sorted(pages.values(), key=order)[:140],
        sorted(categories.values(), key=order),
    )


async def load_citation_comparison_series(
    conn,
    client_id: str,
    dates: ReportDates,
    citation_intents: tuple[str, ...] | list[str],
    own_domains: set[str],
) -> list[dict[str, Any]]:
    time_rows = await conn.fetch(
        """
        SELECT (c.executed_at AT TIME ZONE $3)::date AS date,
               COUNT(*)::int AS total_citations,
               COUNT(*) FILTER (
                   WHERE LOWER(c.source_domain) = ANY($6::text[])
               )::int AS own_citations
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE c.client_id = $1::uuid
          AND (c.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
          AND cp.intent = ANY($4::text[])
        GROUP BY (c.executed_at AT TIME ZONE $3)::date
        ORDER BY (c.executed_at AT TIME ZONE $3)::date ASC
        """,
        client_id,
        dates.window_start,
        dates.timezone,
        citation_intents,
        dates.window_end,
        list(own_domains),
    )
    return build_citation_daily_series(dates, time_rows)


def build_citation_dashboard_from_aggregate_rows(
    rows: list[dict[str, Any]],
    own_domains: set[str],
    dates: ReportDates,
    *,
    comparison_only: bool,
) -> dict[str, Any]:
    domain_map: dict[str, dict[str, Any]] = {}
    page_map: dict[tuple[str, str], dict[str, Any]] = {}
    category_map: dict[str, dict[str, Any]] = {}
    date_map: dict[str, dict[str, int]] = {}
    for row in rows:
        count = int(row.get("citation_count") or 0)
        domain = str(row.get("source_domain") or "")
        category = str(row.get("domain_category") or "Other")
        _increment_aggregate(domain_map, domain, {
            "source_domain": domain,
            "domain_category": category,
            "citation_count": count,
        })
        url = row.get("source_url")
        if url:
            _increment_aggregate(page_map, (str(url), domain), {
                "source_url": url,
                "source_domain": domain,
                "domain_category": category,
                "citation_count": count,
            })
        _increment_aggregate(category_map, category, {
            "domain_category": category,
            "citation_count": count,
        })
        day = str(row.get("date") or "")
        daily = date_map.setdefault(day, {"total_citations": 0, "own_citations": 0})
        daily["total_citations"] += count
        if domain.lower() in own_domains:
            daily["own_citations"] += count

    total_citations = sum(int(row["citation_count"]) for row in domain_map.values())
    domain_rows = sorted(
        domain_map.values(),
        key=lambda row: (-int(row["citation_count"]), str(row["source_domain"])),
    )
    domain_ranking_full, own_citation_count, own_rank = build_citation_domain_ranking(
        domain_rows, own_domains, total_citations, display_limit=len(domain_rows),
    )
    page_rows = sorted(
        page_map.values(),
        key=lambda row: (-int(row["citation_count"]), str(row["source_url"])),
    )
    page_ranking_full = [
        {
            "rank": index + 1,
            "url": row["source_url"],
            "domain": row["source_domain"],
            "citation_count": int(row["citation_count"]),
            "share_pct": round((int(row["citation_count"]) / total_citations * 100), 2)
            if total_citations else 0,
            "is_own": str(row["source_domain"]).lower() in own_domains,
            "domain_category": row["domain_category"],
            "change_pct": None,
        }
        for index, row in enumerate(page_rows)
    ]
    category_rows = sorted(
        category_map.values(),
        key=lambda row: (-int(row["citation_count"]), str(row["domain_category"])),
    )
    time_rows = [
        {"date": day, **counts}
        for day, counts in sorted(date_map.items())
        if day
    ]
    time_series = build_citation_daily_series(dates, time_rows)
    own_share = round((own_citation_count / total_citations * 100), 2) if total_citations else 0
    domain_share_lookup = {
        str(row["source_domain"]): round((int(row["citation_count"]) / total_citations * 100), 2)
        if total_citations else 0
        for row in domain_rows
    }
    page_share_lookup = {
        "\u001f".join((str(row["source_url"]), str(row["source_domain"]))):
        round((int(row["citation_count"]) / total_citations * 100), 2) if total_citations else 0
        for row in page_rows
    }
    result = {
        "summary": {
            "total_citations": total_citations,
            "own_domain_share": own_share,
            "own_citation_count": own_citation_count,
            "own_rank": own_rank,
        },
        "domain_ranking": domain_ranking_full[:20],
        "_complete_domain_ranking": domain_ranking_full,
        "page_ranking": page_ranking_full[:20],
        "_complete_page_ranking": page_ranking_full,
        "_domain_share_lookup": domain_share_lookup,
        "_page_share_lookup": page_share_lookup,
        "time_series": time_series,
    }
    if comparison_only:
        return result
    result.update({
        "summary": {**result["summary"], "own_domain_share_change": None},
        "category_breakdown": build_citation_category_breakdown(category_rows, total_citations),
        "source_rows": [],
        "source_rows_limited": True,
        "own_domains": sorted(own_domains),
        "filters": report_filter_meta(dates),
    })
    return result


async def load_citation_dashboard_snapshot(
    conn,
    client_id: str,
    dates: ReportDates,
    citation_intents: tuple[str, ...] | list[str],
    *,
    comparison_only: bool = False,
) -> dict[str, Any]:
    own_domains, aggregate_rows = await load_citation_aggregate_rows(
        conn, client_id, dates, citation_intents,
    )
    return build_citation_dashboard_from_aggregate_rows(
        aggregate_rows, own_domains, dates, comparison_only=comparison_only,
    )


def _aggregate_sentiment_result_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        sentiment = str(row.get("sentiment") or "")
        count = int(row.get("count") or 0)
        entry = grouped.setdefault(sentiment, {
            "sentiment": sentiment, "count": 0, "confidence_total": 0.0,
        })
        entry["count"] += count
        if row.get("avg_confidence") is not None:
            entry["confidence_total"] += float(row["avg_confidence"]) * count
    return sorted([
        {
            "sentiment": entry["sentiment"],
            "count": entry["count"],
            "avg_confidence": round(entry["confidence_total"] / entry["count"], 3)
            if entry["count"] else None,
        }
        for entry in grouped.values()
    ], key=lambda row: (-int(row["count"]), str(row["sentiment"])))


def _aggregate_sentiment_theme_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("theme_name") or ""), str(row.get("sentiment") or ""))
        entry = grouped.setdefault(key, {
            "theme_name": key[0], "sentiment": key[1], "occurrence_count": 0,
        })
        entry["occurrence_count"] += int(row.get("occurrence_count") or 0)
    return sorted(
        grouped.values(),
        key=lambda row: (-int(row["occurrence_count"]), str(row["theme_name"])),
    )


def build_sentiment_dashboard_from_aggregate_rows(
    result_rows: list[dict[str, Any]],
    theme_rows: list[dict[str, Any]],
    examples: list[dict[str, Any]],
    dates: ReportDates,
    *,
    comparison_only: bool,
) -> dict[str, Any]:
    summary_rows = _aggregate_sentiment_result_rows(result_rows)
    total = sum(int(row["count"]) for row in summary_rows)
    positive = sum(int(row["count"]) for row in summary_rows if row["sentiment"] == "Positive")
    mixed_neutral = sum(int(row["count"]) for row in summary_rows if row["sentiment"] == "Mixed/Neutral")
    negative = sum(int(row["count"]) for row in summary_rows if row["sentiment"] == "Negative")
    insufficient_evidence = sum(int(row["count"]) for row in summary_rows if row["sentiment"] == "Insufficient Evidence")
    rated = positive + mixed_neutral + negative
    positive_pct = round((positive / rated * 100), 2) if rated else 0
    mixed_neutral_pct = round((mixed_neutral / rated * 100), 2) if rated else 0
    negative_pct = round((negative / rated * 100), 2) if rated else 0
    all_themes = [
        {**row, "prev_occurrence_count": 0, "occurrence_change": None}
        for row in _aggregate_sentiment_theme_rows(theme_rows)
    ]
    theme_occurrence_lookup: dict[str, int] = {}
    for row in all_themes:
        theme_key = _sentiment_theme_key(row)
        theme_occurrence_lookup[theme_key] = int(row["occurrence_count"])
    daily: dict[str, dict[str, int]] = {}
    for row in result_rows:
        day = str(row.get("date") or "")
        entry = daily.setdefault(day, {
            "total_count": 0,
            "rated_count": 0,
            "positive_count": 0,
            "mixed_neutral_count": 0,
            "negative_count": 0,
            "insufficient_evidence_count": 0,
        })
        count = int(row.get("count") or 0)
        entry["total_count"] += count
        if row.get("sentiment") == "Positive":
            entry["positive_count"] += count
            entry["rated_count"] += count
        if row.get("sentiment") == "Mixed/Neutral":
            entry["mixed_neutral_count"] += count
            entry["rated_count"] += count
        if row.get("sentiment") == "Negative":
            entry["negative_count"] += count
            entry["rated_count"] += count
        if row.get("sentiment") == "Insufficient Evidence":
            entry["insufficient_evidence_count"] += count
    time_series = build_sentiment_daily_series(
        dates, [{"date": day, **counts} for day, counts in sorted(daily.items()) if day],
    )
    result = {
        "summary": {
            "positive_pct": positive_pct,
            "mixed_neutral_pct": mixed_neutral_pct,
            "negative_pct": negative_pct,
            "positive_count": positive,
            "mixed_neutral_count": mixed_neutral,
            "negative_count": negative,
            "insufficient_evidence_count": insufficient_evidence,
            "rated_count": rated,
            "total_count": total,
        },
        "time_series": time_series,
        "themes": all_themes[:100],
        "_complete_themes": all_themes,
        "_theme_occurrence_lookup": theme_occurrence_lookup,
    }
    if comparison_only:
        return result
    source_rows, source_rows_limited = serialize_limited_rows(theme_rows)
    response_source_rows, response_source_rows_limited = serialize_limited_rows(result_rows)
    result.update({
        "summary": {
            **result["summary"],
            "positive_pct_change": None,
            "positive_top3_themes": [row["theme_name"] for row in all_themes if row["sentiment"] == "Positive"][:3],
            "negative_top3_themes": [row["theme_name"] for row in all_themes if row["sentiment"] == "Negative"][:3],
        },
        "examples": examples,
        "source_rows": source_rows,
        "source_rows_limited": source_rows_limited,
        "response_source_rows": response_source_rows,
        "response_source_rows_limited": response_source_rows_limited,
        "filters": report_filter_meta(dates),
    })
    return result


def build_sentiment_snapshot_from_aggregate_rows(
    result_rows: list[dict[str, Any]],
    theme_rows: list[dict[str, Any]],
    examples: list[dict[str, Any]],
    dates: ReportDates,
) -> dict[str, Any]:
    summary = _aggregate_sentiment_result_rows(result_rows)
    themes = _aggregate_sentiment_theme_rows(theme_rows)
    themes_by_day = _aggregate_sentiment_themes_by_day(theme_rows)
    return {
        "summary": summary,
        "summary_by_day": sorted(result_rows, key=lambda row: (str(row.get("date") or ""), -int(row.get("count") or 0))),
        "themes": [{"theme_name": row["theme_name"], "sentiment": row["sentiment"], "count": row["occurrence_count"]} for row in themes[:50]],
        "themes_by_day": themes_by_day[:350],
        "examples": examples,
        "dashboard": build_sentiment_dashboard_from_aggregate_rows(
            result_rows, theme_rows, examples, dates, comparison_only=False,
        ),
    }


def _aggregate_sentiment_themes_by_day(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("date") or ""), str(row.get("theme_name") or ""), str(row.get("sentiment") or ""))
        entry = grouped.setdefault(key, {
            "date": key[0], "theme_name": key[1], "sentiment": key[2], "count": 0,
        })
        entry["count"] += int(row.get("occurrence_count") or 0)
    return sorted(grouped.values(), key=lambda row: (row["date"], -int(row["count"]), row["theme_name"]))


async def load_sentiment_period_rows(
    conn,
    client_id: str,
    dates: ReportDates,
    sentiment_intents: tuple[str, ...] | list[str],
    *,
    include_examples: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not sentiment_intents:
        return [], [], []
    result_rows = serialize_rows(await fetch_bounded_aggregate_rows(
        conn,
        """
        SELECT 'current'::text AS period,
               (sr.executed_at AT TIME ZONE $3)::date AS date,
               cp.topic_id::text AS topic_id,
               COALESCE(ct.topic_name, 'Uncategorized') AS topic_name,
               cp.platform,
               sr.sentiment,
               COUNT(*)::int AS count,
               ROUND(AVG(sr.confidence)::numeric, 3) AS avg_confidence
        FROM geo_sentiment_results sr
        JOIN geo_client_prompts cp
          ON cp.id = sr.client_prompt_id
         AND cp.client_id = sr.client_id
        LEFT JOIN geo_client_topics ct
          ON ct.id = cp.topic_id
         AND ct.client_id = cp.client_id
        WHERE sr.client_id = $1::uuid
          AND (sr.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $4
          AND cp.is_active = TRUE
          AND cp.intent = ANY($5::text[])
        GROUP BY period, (sr.executed_at AT TIME ZONE $3)::date,
                 cp.topic_id, ct.topic_name, cp.platform, sr.sentiment
        """,
        client_id, dates.window_start, dates.timezone, dates.window_end, sentiment_intents,
        label="sentiment summary aggregate",
    ))
    theme_rows = serialize_rows(await fetch_bounded_aggregate_rows(
        conn,
        """
        SELECT 'current'::text AS period,
               (st.executed_at AT TIME ZONE $3)::date AS date,
               cp.topic_id::text AS topic_id,
               COALESCE(ct.topic_name, 'Uncategorized') AS topic_name,
               cp.platform, st.theme_name, st.sentiment,
               COUNT(*)::int AS occurrence_count
        FROM geo_sentiment_themes st
        JOIN geo_client_prompts cp
          ON cp.id = st.client_prompt_id
         AND cp.client_id = st.client_id
        LEFT JOIN geo_client_topics ct
          ON ct.id = cp.topic_id
         AND ct.client_id = cp.client_id
        WHERE st.client_id = $1::uuid
          AND (st.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $4
          AND cp.is_active = TRUE
          AND cp.intent = ANY($5::text[])
        GROUP BY period, (st.executed_at AT TIME ZONE $3)::date,
                 cp.topic_id, ct.topic_name, cp.platform, st.theme_name, st.sentiment
        """,
        client_id, dates.window_start, dates.timezone, dates.window_end, sentiment_intents,
        label="sentiment theme aggregate",
    ))
    examples: list[dict[str, Any]] = []
    if include_examples:
        examples = serialize_rows(await fetch_bounded_aggregate_rows(
            conn,
            """
            SELECT (st.executed_at AT TIME ZONE $3)::date AS date,
                   cp.topic_id::text AS topic_id,
                   COALESCE(ct.topic_name, 'Uncategorized') AS topic_name,
                   cp.platform, st.theme_name, st.sentiment, st.excerpt,
                   st.result_id::text AS result_id
            FROM geo_sentiment_themes st
            JOIN geo_client_prompts cp
              ON cp.id = st.client_prompt_id
             AND cp.client_id = st.client_id
            LEFT JOIN geo_client_topics ct
              ON ct.id = cp.topic_id
             AND ct.client_id = cp.client_id
            WHERE st.client_id = $1::uuid
              AND st.excerpt IS NOT NULL
              AND (st.executed_at AT TIME ZONE $3)::date BETWEEN $2 AND $5
              AND cp.is_active = TRUE
              AND cp.intent = ANY($4::text[])
            ORDER BY st.executed_at DESC
            """,
            client_id, dates.window_start, dates.timezone, sentiment_intents, dates.window_end,
            label="sentiment examples",
            row_limit=50,
            truncate=True,
        ))
    return result_rows, theme_rows, examples


def _without_period(rows: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in row.items() if key != "period"}
        for row in rows if row.get("period") == period
    ]


async def load_sentiment_period_snapshots(
    conn,
    client_id: str,
    dates: ReportDates,
    previous_dates: ReportDates,
    sentiment_intents: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    current_result_rows, current_theme_rows, examples = await load_sentiment_period_rows(
        conn, client_id, dates, sentiment_intents,
    )
    previous_result_rows, previous_theme_rows, _ = await load_sentiment_period_rows(
        conn, client_id, previous_dates, sentiment_intents, include_examples=False,
    )
    current_results = _without_period(current_result_rows, "current")
    current_themes = _without_period(current_theme_rows, "current")
    previous_results = _without_period(previous_result_rows, "current")
    previous_themes = _without_period(previous_theme_rows, "current")
    return {
        "current": build_sentiment_snapshot_from_aggregate_rows(
            current_results, current_themes, examples, dates,
        ),
        "previous": {
            "dashboard": build_sentiment_dashboard_from_aggregate_rows(
                previous_results, previous_themes, [], previous_dates, comparison_only=True,
            ),
        },
    }


async def load_sentiment_snapshot(
    conn, client_id: str, dates: ReportDates, sentiment_intents: tuple[str, ...],
) -> dict[str, Any]:
    result_rows, theme_rows, examples = await load_sentiment_period_rows(
        conn, client_id, dates, sentiment_intents,
    )
    return build_sentiment_snapshot_from_aggregate_rows(
        _without_period(result_rows, "current"),
        _without_period(theme_rows, "current"),
        examples, dates,
    )


async def load_sentiment_dashboard_snapshot(
    conn,
    client_id: str,
    dates: ReportDates,
    sentiment_intents: tuple[str, ...] | list[str],
    *,
    comparison_only: bool = False,
) -> dict[str, Any]:
    result_rows, theme_rows, examples = await load_sentiment_period_rows(
        conn, client_id, dates, sentiment_intents, include_examples=not comparison_only,
    )
    return build_sentiment_dashboard_from_aggregate_rows(
        _without_period(result_rows, "current"),
        _without_period(theme_rows, "current"),
        examples, dates, comparison_only=comparison_only,
    )


async def load_prompt_topic_snapshot(conn, client_id: str, dates: ReportDates) -> dict[str, Any]:
    prompts = await fetch_bounded_aggregate_rows(
        conn,
        """
        WITH mention_totals AS (
            SELECT client_prompt_id AS prompt_id,
                   COUNT(*)::int AS mention_count
            FROM geo_brand_mentions
            WHERE client_id = $1::uuid
              AND client_prompt_id IS NOT NULL
              AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            GROUP BY client_prompt_id
        ), citation_totals AS (
            SELECT client_prompt_id AS prompt_id,
                   COUNT(*)::int AS citation_count
            FROM geo_citations
            WHERE client_id = $1::uuid
              AND client_prompt_id IS NOT NULL
              AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            GROUP BY client_prompt_id
        )
        SELECT cp.id::text AS prompt_id,
               cp.text AS prompt_text,
               cp.intent,
               cp.platform,
               cp.country,
               cp.language,
               COALESCE(mt.mention_count, 0)::int AS mention_count,
               COALESCE(ct.citation_count, 0)::int AS citation_count
        FROM geo_client_prompts cp
        LEFT JOIN mention_totals mt ON mt.prompt_id = cp.id
        LEFT JOIN citation_totals ct ON ct.prompt_id = cp.id
        WHERE cp.client_id = $1::uuid
          AND (COALESCE(mt.mention_count, 0) > 0 OR COALESCE(ct.citation_count, 0) > 0)
        ORDER BY mention_count DESC, citation_count DESC
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
        label="prompt ranking aggregate",
    )
    topics = await fetch_bounded_aggregate_rows(
        conn,
        """
        WITH window_results AS (
            SELECT result_id,
                   COALESCE(topic_name, topic, 'Unclassified') AS topic_name
            FROM geo_results
            WHERE client_id = $1::uuid
              AND (ingested_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
        ), result_mentions AS (
            SELECT bm.result_id, COUNT(*)::int AS mention_count
            FROM geo_brand_mentions bm
            JOIN window_results wr ON wr.result_id = bm.result_id
            WHERE bm.client_id = $1::uuid
            GROUP BY bm.result_id
        ), result_citations AS (
            SELECT c.result_id, COUNT(*)::int AS citation_count
            FROM geo_citations c
            JOIN window_results wr ON wr.result_id = c.result_id
            WHERE c.client_id = $1::uuid
            GROUP BY c.result_id
        )
        SELECT wr.topic_name,
               COALESCE(SUM(rm.mention_count), 0)::int AS mention_count,
               COALESCE(SUM(rc.citation_count), 0)::int AS citation_count
        FROM window_results wr
        LEFT JOIN result_mentions rm ON rm.result_id = wr.result_id
        LEFT JOIN result_citations rc ON rc.result_id = wr.result_id
        GROUP BY wr.topic_name
        ORDER BY mention_count DESC, citation_count DESC
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
        label="topic ranking aggregate",
    )
    prompts_by_day = await fetch_bounded_aggregate_rows(
        conn,
        """
        WITH prompt_events AS (
            SELECT client_prompt_id AS prompt_id,
                   (executed_at AT TIME ZONE $4)::date AS date,
                   COUNT(*)::int AS mention_count,
                   0::int AS citation_count
            FROM geo_brand_mentions
            WHERE client_id = $1::uuid
              AND client_prompt_id IS NOT NULL
              AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            GROUP BY client_prompt_id, date
            UNION ALL
            SELECT client_prompt_id AS prompt_id,
                   (executed_at AT TIME ZONE $4)::date AS date,
                   0::int AS mention_count,
                   COUNT(*)::int AS citation_count
            FROM geo_citations
            WHERE client_id = $1::uuid
              AND client_prompt_id IS NOT NULL
              AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            GROUP BY client_prompt_id, date
        )
        SELECT pe.date,
               cp.id::text AS prompt_id,
               cp.text AS prompt_text,
               cp.intent,
               cp.platform,
               cp.country,
               cp.language,
               SUM(pe.mention_count)::int AS mention_count,
               SUM(pe.citation_count)::int AS citation_count
        FROM geo_client_prompts cp
        JOIN prompt_events pe
          ON pe.prompt_id = cp.id
        WHERE cp.client_id = $1::uuid
        GROUP BY pe.date, cp.id, cp.text, cp.intent, cp.platform, cp.country, cp.language
        ORDER BY date ASC, mention_count DESC, citation_count DESC
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
        label="prompt daily snapshot rows",
        row_limit=700,
        truncate=True,
    )
    topics_by_day = await fetch_bounded_aggregate_rows(
        conn,
        """
        WITH window_results AS (
            SELECT result_id,
                   (ingested_at AT TIME ZONE $4)::date AS date,
                   COALESCE(topic_name, topic, 'Unclassified') AS topic_name
            FROM geo_results
            WHERE client_id = $1::uuid
              AND (ingested_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
        ), result_mentions AS (
            SELECT bm.result_id, COUNT(*)::int AS mention_count
            FROM geo_brand_mentions bm
            JOIN window_results wr ON wr.result_id = bm.result_id
            WHERE bm.client_id = $1::uuid
            GROUP BY bm.result_id
        ), result_citations AS (
            SELECT c.result_id, COUNT(*)::int AS citation_count
            FROM geo_citations c
            JOIN window_results wr ON wr.result_id = c.result_id
            WHERE c.client_id = $1::uuid
            GROUP BY c.result_id
        )
        SELECT wr.date,
               wr.topic_name,
               COALESCE(SUM(rm.mention_count), 0)::int AS mention_count,
               COALESCE(SUM(rc.citation_count), 0)::int AS citation_count
        FROM window_results wr
        LEFT JOIN result_mentions rm ON rm.result_id = wr.result_id
        LEFT JOIN result_citations rc ON rc.result_id = wr.result_id
        GROUP BY wr.date, wr.topic_name
        ORDER BY date ASC, mention_count DESC, citation_count DESC
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
        label="topic daily snapshot rows",
        row_limit=700,
        truncate=True,
    )
    return {
        "prompts": {
            "ranking": serialize_rows(prompts[:100]),
            "_complete_ranking": serialize_rows(prompts),
            "ranking_by_day": serialize_rows(prompts_by_day),
        },
        "topics": {
            "ranking": serialize_rows(topics[:100]),
            "_complete_ranking": serialize_rows(topics),
            "ranking_by_day": serialize_rows(topics_by_day),
        },
    }


async def load_available_dates(conn, client_id: str, dates: ReportDates) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT (ingested_at AT TIME ZONE $4)::date::text AS date
        FROM geo_results
        WHERE client_id = $1::uuid
          AND analyzed_at IS NOT NULL
          AND (ingested_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
        ORDER BY date
        """,
        client_id,
        dates.window_start,
        dates.window_end,
        dates.timezone,
    )
    return [row["date"] for row in rows]


MAX_STATIC_REPORT_SNAPSHOT_CONCURRENCY = 2
DEFAULT_STATIC_REPORT_SNAPSHOT_CONCURRENCY = 2
DEFAULT_STATIC_REPORT_DB_CONNECTION_RESERVE = 5
MIN_STATIC_REPORT_WORK_MEM_MB = 16
DEFAULT_STATIC_REPORT_WORK_MEM_MB = 32
MAX_STATIC_REPORT_WORK_MEM_MB = 64
STATIC_REPORT_ADVISORY_LOCK_NAMESPACE = 724835
STATIC_REPORT_ADVISORY_LOCK_SLOT = 1
_EXPORTED_SNAPSHOT_ID_RE = re.compile(r"[0-9A-Fa-f-]+")


class StaticReportCapacityBusy(RuntimeError):
    pass


def static_report_work_mem_mb() -> int:
    try:
        configured = int(os.environ.get("STATIC_REPORT_WORK_MEM_MB", str(DEFAULT_STATIC_REPORT_WORK_MEM_MB)))
    except ValueError:
        configured = DEFAULT_STATIC_REPORT_WORK_MEM_MB
    return max(MIN_STATIC_REPORT_WORK_MEM_MB, min(configured, MAX_STATIC_REPORT_WORK_MEM_MB))


async def configure_static_report_transaction(conn) -> None:
    work_mem_mb = static_report_work_mem_mb()
    await conn.execute(f"SET LOCAL work_mem = '{work_mem_mb}MB'")


def snapshot_worker_limit(pool) -> int:
    try:
        configured = int(os.environ.get(
            "STATIC_REPORT_SNAPSHOT_CONCURRENCY",
            str(DEFAULT_STATIC_REPORT_SNAPSHOT_CONCURRENCY),
        ))
    except ValueError:
        configured = DEFAULT_STATIC_REPORT_SNAPSHOT_CONCURRENCY
    configured = max(1, min(configured, MAX_STATIC_REPORT_SNAPSHOT_CONCURRENCY))
    get_max_size = getattr(pool, "get_max_size", None)
    pool_max_size = int(get_max_size()) if callable(get_max_size) else int(os.environ.get("DB_POOL_MAX_SIZE", "8"))
    try:
        reserve = int(os.environ.get(
            "STATIC_REPORT_DB_CONNECTION_RESERVE",
            str(DEFAULT_STATIC_REPORT_DB_CONNECTION_RESERVE),
        ))
    except ValueError:
        reserve = DEFAULT_STATIC_REPORT_DB_CONNECTION_RESERVE
    reserve = max(DEFAULT_STATIC_REPORT_DB_CONNECTION_RESERVE, reserve)
    # One connection is held by the global capacity guard and one by the
    # exported-snapshot coordinator for the lifetime of the build.
    return min(configured, max(0, pool_max_size - reserve - 2))


@asynccontextmanager
async def static_report_global_capacity(pool):
    """Hold a cross-instance gate without a multi-minute idle transaction."""
    async with pool.acquire() as guard:
        has_capacity = await guard.fetchval(
            "SELECT pg_try_advisory_lock($1::integer, $2::integer)",
            STATIC_REPORT_ADVISORY_LOCK_NAMESPACE,
            STATIC_REPORT_ADVISORY_LOCK_SLOT,
        )
        if not has_capacity:
            raise StaticReportCapacityBusy("static report materialization capacity is busy")
        try:
            yield
        finally:
            try:
                await guard.fetchval(
                    "SELECT pg_advisory_unlock($1::integer, $2::integer)",
                    STATIC_REPORT_ADVISORY_LOCK_NAMESPACE,
                    STATIC_REPORT_ADVISORY_LOCK_SLOT,
                )
            except Exception:
                # A closed PostgreSQL session has already released its lock.
                logger.warning(
                    "[STATIC_REPORT] capacity guard connection closed before explicit unlock",
                    exc_info=True,
                )


def bind_exported_snapshot_sql(snapshot_id: str) -> str:
    """Validate PostgreSQL's server-generated snapshot identifier before SET."""
    if not _EXPORTED_SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise ValueError("PostgreSQL returned an invalid exported snapshot identifier")
    return f"SET TRANSACTION SNAPSHOT '{snapshot_id}'"


async def run_snapshot_stage(
    pool,
    semaphore: asyncio.Semaphore,
    snapshot_id: str,
    stage: str,
    loader,
    *args,
):
    started = time.perf_counter()
    async with semaphore:
        async with pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                await configure_static_report_transaction(conn)
                await conn.execute(bind_exported_snapshot_sql(snapshot_id))
                result = await loader(conn, *args)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    logger.info("[STATIC_REPORT] snapshot_stage_completed stage=%s elapsed_ms=%s", stage, elapsed_ms)
    return result


async def run_snapshot_stage_on_connection(conn, stage: str, loader, *args):
    started = time.perf_counter()
    result = await loader(conn, *args)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    logger.info("[STATIC_REPORT] snapshot_stage_completed stage=%s elapsed_ms=%s", stage, elapsed_ms)
    return result


async def gather_snapshot_stages(awaitables: list[Any]) -> list[Any]:
    """Cancel and await every worker before the exporting transaction exits."""
    tasks = [asyncio.create_task(awaitable) for awaitable in awaitables]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def load_previous_visibility_comparison(
    conn,
    client_id: str,
    dates: ReportDates,
    visibility_intents: tuple[str, ...],
) -> dict[str, Any]:
    dashboard = await load_visibility_dashboard_snapshot(
        conn,
        client_id,
        dates,
        visibility_intents,
        comparison_only=True,
    )
    return {"dashboard": dashboard}


async def load_previous_citation_comparison(
    conn,
    client_id: str,
    dates: ReportDates,
    citation_intents: tuple[str, ...],
) -> dict[str, Any]:
    dashboard = await load_citation_dashboard_snapshot(
        conn,
        client_id,
        dates,
        citation_intents,
        comparison_only=True,
    )
    return {"dashboard": dashboard}


async def load_previous_sentiment_comparison(
    conn,
    client_id: str,
    dates: ReportDates,
    sentiment_intents: tuple[str, ...],
) -> dict[str, Any]:
    dashboard = await load_sentiment_dashboard_snapshot(
        conn,
        client_id,
        dates,
        sentiment_intents,
        comparison_only=True,
    )
    return {"dashboard": dashboard}


async def load_previous_sections(
    conn,
    client_id: str,
    dates: ReportDates,
    filter_config: SnapshotFilterConfig,
) -> dict[str, Any]:
    """Load only fields consumed by previous-period comparisons."""
    return {
        "visibility": await load_previous_visibility_comparison(
            conn, client_id, dates, filter_config.visibility_intents
        ),
        "citations": await load_previous_citation_comparison(
            conn, client_id, dates, filter_config.citation_intents
        ),
        "sentiment": await load_previous_sentiment_comparison(
            conn, client_id, dates, filter_config.sentiment_intents
        ),
    }


async def load_previous_visibility_section(
    conn,
    client_id: str,
    dates: ReportDates,
    filter_config: SnapshotFilterConfig,
) -> dict[str, Any]:
    return {
        "visibility": await load_previous_visibility_comparison(
            conn, client_id, dates, filter_config.visibility_intents,
        ),
    }


async def build_snapshot(
    pool,
    client_id: str,
    dates: ReportDates,
    data_completeness: dict[str, Any],
) -> tuple[dict[str, Any], RenderingMode, list[str]]:
    previous_dates = compute_previous_report_dates(dates)
    async with pool.acquire() as coordinator:
        async with coordinator.transaction(isolation="repeatable_read", readonly=True):
            await configure_static_report_transaction(coordinator)
            filter_config = await load_snapshot_filter_config(coordinator)
            stages = [
                ("client", load_client_name, (client_id,)),
                ("visibility", load_visibility_snapshot, (client_id, dates, filter_config.visibility_intents)),
                ("citation_periods", load_citation_period_snapshots, (
                    client_id, dates, previous_dates, filter_config.citation_intents,
                )),
                ("sentiment_periods", load_sentiment_period_snapshots, (
                    client_id, dates, previous_dates, filter_config.sentiment_intents,
                )),
                ("prompt_topic", load_prompt_topic_snapshot, (client_id, dates)),
                ("filters", load_filter_options, (client_id,)),
                ("available_dates", load_available_dates, (client_id, dates)),
                ("previous_period", load_previous_visibility_section, (
                    client_id, previous_dates, filter_config,
                )),
            ]
            worker_limit = snapshot_worker_limit(pool)
            if worker_limit == 0:
                results = [
                    await run_snapshot_stage_on_connection(coordinator, stage, loader, *args)
                    for stage, loader, args in stages
                ]
            else:
                snapshot_id = str(await coordinator.fetchval("SELECT pg_export_snapshot()"))
                semaphore = asyncio.Semaphore(worker_limit)
                results = await gather_snapshot_stages([
                    run_snapshot_stage(pool, semaphore, snapshot_id, stage, loader, *args)
                    for stage, loader, args in stages
                ])
    (
        client_name,
        visibility,
        citation_periods,
        sentiment_periods,
        prompt_topic,
        filter_options,
        available_dates,
        previous_sections,
    ) = results
    citations = citation_periods["current"]
    sentiment = sentiment_periods["current"]
    previous_sections["citations"] = citation_periods["previous"]
    previous_sections["sentiment"] = sentiment_periods["previous"]

    rendering_mode = choose_report_rendering_mode(dates, available_dates)
    snapshot = empty_snapshot(client_id, client_name, dates, rendering_mode, data_completeness)
    snapshot["report"]["available_dates"] = available_dates
    snapshot["visibility"] = visibility
    snapshot["citations"] = citations
    snapshot["sentiment"] = sentiment
    snapshot["filters"] = filter_options
    snapshot["prompts"] = prompt_topic["prompts"]
    snapshot["topics"] = prompt_topic["topics"]
    warnings = materialize_previous_period(snapshot, previous_sections)
    snapshot["data_completeness"] = {
        **data_completeness,
        "previous_period": {
            "window_start": previous_dates.window_start.isoformat(),
            "window_end": previous_dates.window_end.isoformat(),
            "visibility": "previous_period_visibility_missing" not in warnings,
            "citation": "previous_period_citation_missing" not in warnings,
            "sentiment": "previous_period_sentiment_missing" not in warnings,
        },
    }
    if rendering_mode == RenderingMode.SINGLE_DAY:
        warnings.append("single_day_report")
    return snapshot, rendering_mode, warnings
