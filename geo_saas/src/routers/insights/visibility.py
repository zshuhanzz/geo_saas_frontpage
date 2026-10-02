"""
Visibility endpoint — response-level Visibility Score + SOV ranking.

v1.2 dual-mode tracking adaptation (Spec §7.3):
- Source table renamed: ``geo_company_mentions`` → ``geo_brand_mentions``.
- Column rename: ``company_name`` → ``brand_name``.
- ``is_own_brand = true`` → ``brand_role = 'own'``.
- ``is_own_brand = false`` → **peers-list membership EXISTS** (not
  ``brand_role = 'peer'``). Correctness fix: a Shadow brand can also be a Peer.

The JSON response shape is preserved (``company_name`` / ``is_own`` keys) so
existing frontend components read data without a breaking change.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import database

from ._helpers import (
    SHANGHAI_TZ,
    apply_common_filters,
    inject_sov_zero_own_brand,
    inject_visibility_zero_own_brand,
    build_sov_ranking,
    date_bucket_expr,
    date_range_filter_expr,
    iter_date_strings,
    logical_prompt_key_sql,
    parse_multi_value,
    parse_date_range,
    rank_visibility_entries,
)
from .sorting import resolve_sort_or_422, sort_complete_rows

router = APIRouter()


# ─── Output models ─────────────────────────────────────────────────────────


class VisibilitySovRow(BaseModel):
    company_name: Optional[str] = None
    brand_name: Optional[str] = None
    rank: Optional[int] = None
    mention_count: int
    sov_pct: float
    visibility_pct: Optional[float] = None
    avg_position: Optional[float] = None
    is_own: bool
    sov_pct_change: Optional[float] = None
    visibility_pct_change: Optional[float] = None


class VisibilityTimePoint(BaseModel):
    date: str
    score: Optional[float] = None
    total: int
    own_count: int


class AvgPositionPoint(BaseModel):
    date: str
    avg_position: Optional[float] = None


class CompetitiveSeriesPoint(BaseModel):
    date: str
    count: int


class VisibilitySummary(BaseModel):
    visibility_score: float
    visibility_score_change: Optional[float] = None
    visibility_rank: Optional[int] = None
    visibility_rank_change: Optional[int] = None
    mentioned: int = 0
    total_query: int = 0
    sov_pct: Optional[float] = None
    sov_pct_change: Optional[float] = None
    sov_rank: Optional[int] = None
    sov_rank_change: Optional[int] = None
    total_mentions: int
    own_mentions: int
    avg_position: Optional[float] = None
    avg_position_change: Optional[float] = None
    avg_position_rank: Optional[int] = None
    avg_position_rank_change: Optional[int] = None


class TopicSovEntry(BaseModel):
    topic_id: str
    topic_name: Optional[str] = None
    total_mentions: int = 0
    prompt_count: int = 0
    brands: List[Any]
    prompts: List[Any]


class ProductSovEntry(BaseModel):
    product: Optional[str] = None
    total_mentions: int = 0
    prompt_count: int = 0
    brands: List[Any]
    prompts: List[Any]


class VisibilityFilters(BaseModel):
    date_from: str
    date_to: str
    prev_date_from: str
    prev_date_to: str
    interval: str


class VisibilityOut(BaseModel):
    summary: VisibilitySummary
    time_series: List[VisibilityTimePoint]
    prev_time_series: List[VisibilityTimePoint]
    avg_position_series: List[AvgPositionPoint]
    prev_avg_position_series: List[AvgPositionPoint]
    competitive_series: Dict[str, List[CompetitiveSeriesPoint]]
    sov_ranking: List[VisibilitySovRow]
    visibility_ranking: List[VisibilitySovRow] = []
    position_ranking: List[VisibilitySovRow] = []
    topic_sov_ranking: List[TopicSovEntry]
    product_sov_ranking: List[ProductSovEntry]
    filters: VisibilityFilters


class VisibilityRankingGroup(BaseModel):
    group_key: str
    group_name: Optional[str] = None
    prompt_count: int
    total_mentions: int = 0
    brands: List[Any]


class VisibilityRankingGroupsOut(BaseModel):
    group_by: str
    items: List[VisibilityRankingGroup]
    filters: VisibilityFilters


class VisibilityRankingPrompt(BaseModel):
    prompt_id: str
    prompt_text: str
    total_mentions: int = 0
    brands: List[Any]


class VisibilityRankingPromptsOut(BaseModel):
    group_by: str
    group_key: str
    items: List[VisibilityRankingPrompt]
    total: int
    limit: int
    offset: int
    filters: VisibilityFilters


# ─── SQL fragments ─────────────────────────────────────────────────────────

# Shared FROM/JOIN clause used by all visibility sub-queries below. The own-vs-
# peer EXISTS detection lives in the SELECT/WHERE depending on need; the JOIN
# itself is constant.
_FROM_CLAUSE = """
    FROM geo_brand_mentions bm
    JOIN geo_client_prompts cp ON cp.id = bm.client_prompt_id
"""


def _period_bounds(params: dict) -> tuple[Any, Any] | None:
    if "start_date" in params and "end_date" in params:
        return params["start_date"], params["end_date"]
    if "prev_start" in params and "prev_end" in params:
        return params["prev_start"], params["prev_end"]
    return None


async def _get_primary_own_brand_name(client_id: UUID) -> Optional[str]:
    row = await database.fetch_one(
        """
        SELECT brand_name
        FROM geo_client_brands
        WHERE client_id = :client_id
          AND is_shadow = FALSE
          AND is_active = TRUE
        ORDER BY created_at ASC, brand_name ASC
        LIMIT 1
        """,
        {"client_id": client_id},
    )
    if not row:
        return None
    brand_name = row["brand_name"]
    return str(brand_name).strip() or None


async def _build_visibility_filter_context(
    *,
    client_id: UUID,
    topic_id: Optional[str],
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    product: Optional[str],
    prompt_id: Optional[str],
    prompt_ids: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> tuple[str, str, dict, Any, Any, Any, Any]:
    """Build the same common Visibility filter context used by matrix routes."""
    start_date, end_date = parse_date_range(date_from, date_to)
    period_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    mention_where_parts = ["bm.client_id = :client_id"]
    response_where_parts = ["gr.client_id = :client_id"]
    base_params: dict = {"client_id": client_id}
    prompt_id_list = parse_multi_value(prompt_ids)
    effective_prompt_id = None if prompt_id_list else prompt_id
    apply_common_filters(
        mention_where_parts, base_params,
        cp_alias="cp", mention_alias="bm",
        topic_id=topic_id, topic_ids=topic_ids, platform=platform,
        country=country, product=product, prompt_id=effective_prompt_id,
    )
    apply_common_filters(
        response_where_parts, base_params,
        cp_alias="cp", mention_alias="gr",
        topic_id=topic_id, topic_ids=topic_ids, platform=platform,
        country=country, product=product, prompt_id=effective_prompt_id,
    )
    if prompt_id_list:
        placeholders = ", ".join(f":apply_prompt_{i}" for i in range(len(prompt_id_list)))
        mention_where_parts.append(f"bm.client_prompt_id IN ({placeholders})")
        response_where_parts.append(f"gr.client_prompt_id IN ({placeholders})")
        for i, pid in enumerate(prompt_id_list):
            base_params[f"apply_prompt_{i}"] = pid

    vis_intent_rows = await database.fetch_all(
        """
        SELECT intent_name FROM geo_global_intents
        WHERE is_active = TRUE
          AND categories @> '["Visibility"]'::jsonb
        """
    )
    vis_intent_names = [r["intent_name"] for r in vis_intent_rows]
    if vis_intent_names:
        placeholders = ",".join(f":vis_intent_{i}" for i in range(len(vis_intent_names)))
        mention_where_parts.append(f"cp.intent IN ({placeholders})")
        response_where_parts.append(f"cp.intent IN ({placeholders})")
        for i, name in enumerate(vis_intent_names):
            base_params[f"vis_intent_{i}"] = name
    else:
        mention_where_parts.append("1 = 0")
        response_where_parts.append("1 = 0")

    mention_where_sql = " AND ".join(mention_where_parts)
    response_where_sql = " AND ".join(response_where_parts)
    curr_where_sql = mention_where_sql + " AND " + date_range_filter_expr("bm.executed_at", "start_date", "end_date")
    curr_response_where_sql = response_where_sql + " AND " + date_range_filter_expr("gr.ingested_at", "start_date", "end_date")
    curr_params = {**base_params, "start_date": start_date, "end_date": end_date}
    return curr_where_sql, curr_response_where_sql, curr_params, start_date, end_date, prev_start, prev_end


def _rank_brands_from_counts(counts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_brands = sorted(
        counts.items(),
        key=lambda item: (-int(item[1]["mention_count"]), str(item[0]).casefold(), str(item[0])),
    )
    return [
        {
            "rank": idx + 1,
            "company_name": brand_name,
            "brand_name": brand_name,
            "mention_count": int(data["mention_count"]),
            "is_own": bool(data["is_own"]),
        }
        for idx, (brand_name, data) in enumerate(sorted_brands)
    ]


def _sort_visibility_matrix(
    groups: List[Dict[str, Any]],
    *,
    group_sort_by: Optional[str] = None,
    group_sort_order: Optional[str] = None,
    prompt_sort_by: Optional[str] = None,
    prompt_sort_order: Optional[str] = None,
    brand_sort_by: Optional[str] = None,
    brand_sort_order: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Sort only explicitly requested matrix levels; preserve legacy order otherwise."""
    group_sort = (
        resolve_sort_or_422("visibility_matrix_groups", group_sort_by, group_sort_order)
        if group_sort_by is not None or group_sort_order is not None else None
    )
    prompt_sort = (
        resolve_sort_or_422("visibility_matrix_prompts", prompt_sort_by, prompt_sort_order)
        if prompt_sort_by is not None or prompt_sort_order is not None else None
    )
    brand_sort = (
        resolve_sort_or_422("visibility_matrix_brands", brand_sort_by, brand_sort_order)
        if brand_sort_by is not None or brand_sort_order is not None else None
    )
    shaped: List[Dict[str, Any]] = []
    for source_group in groups:
        group = {**source_group, "brands": list(source_group.get("brands", [])), "prompts": []}
        if brand_sort is not None:
            group["brands"] = sort_complete_rows(
                "visibility_matrix_brands", group["brands"], brand_sort.sort_by, brand_sort.sort_order
            )
        for source_prompt in source_group.get("prompts", []):
            prompt = {**source_prompt, "brands": list(source_prompt.get("brands", []))}
            if brand_sort is not None:
                prompt["brands"] = sort_complete_rows(
                    "visibility_matrix_brands", prompt["brands"], brand_sort.sort_by, brand_sort.sort_order
                )
            group["prompts"].append(prompt)
        if prompt_sort is not None:
            group["prompts"] = sort_complete_rows(
                "visibility_matrix_prompts", group["prompts"], prompt_sort.sort_by, prompt_sort.sort_order
            )
        shaped.append(group)
    if group_sort is not None:
        shaped = sort_complete_rows(
            "visibility_matrix_groups", shaped, group_sort.sort_by, group_sort.sort_order
        )
    return shaped


async def _query_visibility(
    mention_where_sql: str,
    response_where_sql: str,
    base_params: dict,
    interval: str,
) -> dict:
    """Reusable per-period query helper.

    ``visibility_score`` is response-level coverage:
    distinct AI responses mentioning own brand / all AI responses.

    ``sov_ranking`` remains mention-volume Share of Voice:
    brand mention rows / all brand mention rows.
    """
    bucket_sql = date_bucket_expr("bm.executed_at", interval, timezone=SHANGHAI_TZ)
    response_bucket_sql = date_bucket_expr("gr.ingested_at", interval, timezone=SHANGHAI_TZ)

    # ----- Summary: full-period own metrics, independent of display ranking limits -----
    mention_summary_row = await database.fetch_one(
        f"""
        SELECT
            COUNT(*)::int AS total_mentions,
            COUNT(CASE WHEN bm.brand_role = 'own' THEN 1 END)::int AS own_mentions,
            AVG(CASE WHEN bm.brand_role = 'own' THEN bm.mention_position END) AS own_avg_position
        {_FROM_CLAUSE}
        WHERE {mention_where_sql}
        """,
        base_params,
    )
    total_mentions = int(mention_summary_row["total_mentions"]) if mention_summary_row else 0
    own_mention_count = int(mention_summary_row["own_mentions"]) if mention_summary_row else 0
    own_avg_position = (
        round(float(mention_summary_row["own_avg_position"]), 2)
        if mention_summary_row and mention_summary_row["own_avg_position"] is not None
        else None
    )
    own_sov = round((own_mention_count / total_mentions * 100), 2) if total_mentions > 0 else 0

    # ----- Brand mention stats: full universe used for summaries and rankings -----
    mention_stats_rows = await database.fetch_all(
        f"""
        SELECT
            bm.brand_name,
            COUNT(*) AS mention_count,
            MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS is_own,
            AVG(bm.mention_position) AS avg_position
        {_FROM_CLAUSE}
        WHERE {mention_where_sql}
        GROUP BY bm.brand_name
        """,
        base_params,
    )

    mention_entries: List[Dict[str, Any]] = []
    for r in mention_stats_rows:
        pct = round((r["mention_count"] / total_mentions * 100), 2) if total_mentions > 0 else 0
        avg_pos = round(float(r["avg_position"]), 2) if r["avg_position"] else None
        mention_entries.append({
            # Legacy key "company_name" kept for frontend compatibility during
            # the v1.2 roll-out; the value is the v1.2 ``brand_name``.
            "company_name": r["brand_name"],
            "brand_name": r["brand_name"],
            "mention_count": int(r["mention_count"]),
            "sov_pct": pct,
            "visibility_pct": 0,
            "avg_position": avg_pos,
            "is_own": int(r["is_own"]) == 1,
        })

    # ----- Visibility Score: response-level coverage -----
    visibility_row = await database.fetch_one(
        f"""
        SELECT
            COUNT(DISTINCT gr.result_id) AS total_responses,
            COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END) AS own_response_count
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
         AND bm.brand_role = 'own'
        WHERE {response_where_sql}
        """,
        base_params,
    )
    total_responses = visibility_row["total_responses"] if visibility_row else 0
    own_response_count = visibility_row["own_response_count"] if visibility_row else 0
    visibility_score = (
        round((own_response_count / total_responses * 100), 2)
        if total_responses > 0 else 0
    )

    # ----- Brand ranking: response-level visibility by brand -----
    brand_visibility_rows = await database.fetch_all(
        f"""
        SELECT
            bm.brand_name,
            COUNT(DISTINCT gr.result_id) AS response_count
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
        WHERE {response_where_sql}
        GROUP BY bm.brand_name
        """,
        base_params,
    )
    visibility_by_brand = {
        r["brand_name"]: (
            round((r["response_count"] / total_responses * 100), 2)
            if total_responses > 0 else 0
        )
        for r in brand_visibility_rows
    }
    own_brand_name = None
    if (total_responses > 0 or total_mentions > 0) and not any(entry["is_own"] for entry in mention_entries):
        own_brand_name = await _get_primary_own_brand_name(base_params["client_id"])
    sov_entries = inject_sov_zero_own_brand(
        mention_entries,
        total_mentions=total_mentions,
        own_brand_name=own_brand_name,
    )
    sov_full_ranking = rank_visibility_entries(sov_entries, "mention_count", reverse=True)
    sov_ranking = sov_full_ranking
    visibility_entries = [{**entry, "visibility_pct": visibility_by_brand.get(entry["brand_name"], 0)} for entry in mention_entries]
    visibility_entries = inject_visibility_zero_own_brand(
        visibility_entries,
        total_responses=int(total_responses or 0),
        own_brand_name=own_brand_name,
    )
    visibility_full_ranking = rank_visibility_entries(visibility_entries, "visibility_pct", reverse=True)
    position_full_ranking = rank_visibility_entries(
        [entry for entry in mention_entries if entry["avg_position"] is not None],
        "avg_position",
        reverse=False,
    )
    own_sov_rank = next((int(row["rank"]) for row in sov_full_ranking if row["is_own"]), None)
    own_rank = next((int(row["rank"]) for row in visibility_full_ranking if row["is_own"]), None)
    own_avg_position_rank = next((int(row["rank"]) for row in position_full_ranking if row["is_own"]), None)

    # ----- Time Series: response-level visibility score -----
    ts_rows = await database.fetch_all(
        f"""
        SELECT
            {response_bucket_sql} AS bucket,
            COUNT(DISTINCT gr.result_id) AS total,
            COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END)::int AS own_count
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
         AND bm.brand_role = 'own'
        WHERE {response_where_sql}
        GROUP BY {response_bucket_sql}
        ORDER BY {response_bucket_sql}
        """,
        base_params,
    )
    time_series = []
    for r in ts_rows:
        d = r["bucket"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        total = r["total"]
        own = r["own_count"]
        score = round((own / total * 100), 2) if total > 0 else 0
        time_series.append({"date": date_str, "score": score, "total": total, "own_count": own})
    if interval == "daily" and (bounds := _period_bounds(base_params)):
        by_date = {row["date"]: row for row in time_series}
        time_series = [
            by_date.get(day, {"date": day, "score": None, "total": 0, "own_count": 0})
            for day in iter_date_strings(bounds[0], bounds[1])
        ]

    # ----- Avg Position Time Series (own only) -----
    avg_pos_rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_sql} AS bucket,
            AVG(bm.mention_position) AS avg_pos
        {_FROM_CLAUSE}
        WHERE {mention_where_sql} AND bm.brand_role = 'own'
        GROUP BY {bucket_sql}
        ORDER BY {bucket_sql}
        """,
        base_params,
    )
    avg_position_series = []
    for r in avg_pos_rows:
        d = r["bucket"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        avg_position_series.append({
            "date": date_str,
            "avg_position": round(float(r["avg_pos"]), 2) if r["avg_pos"] else None,
        })
    if interval == "daily" and (bounds := _period_bounds(base_params)):
        by_date = {row["date"]: row for row in avg_position_series}
        avg_position_series = [
            by_date.get(day, {"date": day, "avg_position": None})
            for day in iter_date_strings(bounds[0], bounds[1])
        ]

    return {
        "visibility_score": visibility_score,
        "mentioned": int(own_response_count or 0),
        "total_query": int(total_responses or 0),
        "own_sov": own_sov,
        "own_sov_rank": own_sov_rank,
        "own_rank": own_rank,
        "total_mentions": total_mentions,
        "own_mentions": own_mention_count,
        "own_avg_position": own_avg_position,
        "own_avg_position_rank": own_avg_position_rank,
        "sov_ranking": sov_ranking,
        "visibility_ranking": visibility_full_ranking,
        "position_ranking": position_full_ranking,
        "time_series": time_series,
        "avg_position_series": avg_position_series,
    }


def _calc_change(curr_val, prev_val):
    if curr_val is None or prev_val is None:
        return None
    return round(curr_val - prev_val, 2)


def _calc_rank_change(curr_rank, prev_rank):
    if curr_rank is None or prev_rank is None:
        return None
    return int(curr_rank) - int(prev_rank)


def _empty_visibility_summary(**overrides: Any) -> VisibilitySummary:
    values = {
        "visibility_score": 0,
        "visibility_score_change": None,
        "visibility_rank": None,
        "visibility_rank_change": None,
        "mentioned": 0,
        "total_query": 0,
        "sov_pct": 0,
        "sov_pct_change": None,
        "sov_rank": None,
        "sov_rank_change": None,
        "total_mentions": 0,
        "own_mentions": 0,
        "avg_position": None,
        "avg_position_change": None,
        "avg_position_rank": None,
        "avg_position_rank_change": None,
    }
    values.update(overrides)
    return VisibilitySummary(**values)


def _empty_visibility_out(
    *,
    filters: VisibilityFilters,
    summary: Optional[VisibilitySummary] = None,
    time_series: Optional[List[Dict[str, Any]]] = None,
    prev_time_series: Optional[List[Dict[str, Any]]] = None,
    avg_position_series: Optional[List[Dict[str, Any]]] = None,
    prev_avg_position_series: Optional[List[Dict[str, Any]]] = None,
    competitive_series: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    sov_ranking: Optional[List[Dict[str, Any]]] = None,
    visibility_ranking: Optional[List[Dict[str, Any]]] = None,
    position_ranking: Optional[List[Dict[str, Any]]] = None,
) -> VisibilityOut:
    return VisibilityOut(
        summary=summary or _empty_visibility_summary(),
        time_series=[VisibilityTimePoint(**p) for p in (time_series or [])],
        prev_time_series=[VisibilityTimePoint(**p) for p in (prev_time_series or [])],
        avg_position_series=[AvgPositionPoint(**p) for p in (avg_position_series or [])],
        prev_avg_position_series=[AvgPositionPoint(**p) for p in (prev_avg_position_series or [])],
        competitive_series={
            k: [CompetitiveSeriesPoint(**p) for p in v]
            for k, v in (competitive_series or {}).items()
        },
        sov_ranking=[VisibilitySovRow(**r) for r in (sov_ranking or [])],
        visibility_ranking=[VisibilitySovRow(**r) for r in (visibility_ranking or [])],
        position_ranking=[VisibilitySovRow(**r) for r in (position_ranking or [])],
        topic_sov_ranking=[],
        product_sov_ranking=[],
        filters=filters,
    )


async def _visibility_chart_context(
    *,
    client_id: UUID,
    topic_id: Optional[str],
    topic_ids: Optional[str],
    platform: Optional[str],
    country: Optional[str],
    product: Optional[str],
    prompt_id: Optional[str],
    prompt_ids: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    interval: str,
) -> Dict[str, Any]:
    curr_where_sql, curr_response_where_sql, curr_params, start_date, end_date, prev_start, prev_end = await _build_visibility_filter_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
    )
    base_params = {
        k: v
        for k, v in curr_params.items()
        if k not in {"start_date", "end_date"}
    }
    prev_where_sql = (
        curr_where_sql
        .replace(":start_date", ":prev_start")
        .replace(":end_date", ":prev_end")
    )
    prev_response_where_sql = (
        curr_response_where_sql
        .replace(":start_date", ":prev_start")
        .replace(":end_date", ":prev_end")
    )
    filters = VisibilityFilters(
        date_from=start_date.isoformat(),
        date_to=end_date.isoformat(),
        prev_date_from=prev_start.isoformat(),
        prev_date_to=prev_end.isoformat(),
        interval=interval,
    )
    return {
        "curr_where_sql": curr_where_sql,
        "curr_response_where_sql": curr_response_where_sql,
        "curr_params": curr_params,
        "prev_where_sql": prev_where_sql,
        "prev_response_where_sql": prev_response_where_sql,
        "prev_params": {**base_params, "prev_start": prev_start, "prev_end": prev_end},
        "start_date": start_date,
        "end_date": end_date,
        "prev_start": prev_start,
        "prev_end": prev_end,
        "interval": interval,
        "filters": filters,
    }


async def _query_visibility_score_chart(response_where_sql: str, params: dict, interval: str) -> Dict[str, Any]:
    response_bucket_sql = date_bucket_expr("gr.ingested_at", interval, timezone=SHANGHAI_TZ)
    summary_row = await database.fetch_one(
        f"""
        SELECT
            COUNT(DISTINCT gr.result_id) AS total_responses,
            COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END) AS own_response_count
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
         AND bm.brand_role = 'own'
        WHERE {response_where_sql}
        """,
        params,
    )
    total_responses = int(summary_row["total_responses"] or 0) if summary_row else 0
    own_response_count = int(summary_row["own_response_count"] or 0) if summary_row else 0
    visibility_score = round((own_response_count / total_responses * 100), 2) if total_responses > 0 else 0

    rows = await database.fetch_all(
        f"""
        SELECT
            {response_bucket_sql} AS bucket,
            COUNT(DISTINCT gr.result_id) AS total,
            COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END)::int AS own_count
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
         AND bm.brand_role = 'own'
        WHERE {response_where_sql}
        GROUP BY {response_bucket_sql}
        ORDER BY {response_bucket_sql}
        """,
        params,
    )
    time_series = []
    for row in rows:
        d = row["bucket"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        total = int(row["total"] or 0)
        own = int(row["own_count"] or 0)
        time_series.append({
            "date": date_str,
            "score": round((own / total * 100), 2) if total > 0 else 0,
            "total": total,
            "own_count": own,
        })
    if interval == "daily" and (bounds := _period_bounds(params)):
        by_date = {row["date"]: row for row in time_series}
        time_series = [
            by_date.get(day, {"date": day, "score": None, "total": 0, "own_count": 0})
            for day in iter_date_strings(bounds[0], bounds[1])
        ]
    return {
        "visibility_score": visibility_score,
        "mentioned": own_response_count,
        "total_query": total_responses,
        "time_series": time_series,
    }


def _ranked_visibility_entries(entries: List[Dict[str, Any]], rank_value_key: str, reverse: bool = True) -> List[Dict[str, Any]]:
    return rank_visibility_entries(entries, rank_value_key, reverse=reverse)


async def _query_visibility_brand_ranking_chart(
    response_where_sql: str,
    response_params: dict,
) -> Dict[str, Any]:
    total_responses = await database.fetch_val(
        f"""
        SELECT COUNT(DISTINCT gr.result_id)
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        WHERE {response_where_sql}
        """,
        response_params,
    ) or 0
    rows = await database.fetch_all(
        f"""
        SELECT
            bm.brand_name,
            COUNT(DISTINCT gr.result_id) AS response_count,
            COUNT(*) AS mention_count,
            MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS is_own
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
        WHERE {response_where_sql}
        GROUP BY bm.brand_name
        """,
        response_params,
    )
    entries = [
        {
            "company_name": row["brand_name"],
            "brand_name": row["brand_name"],
            "mention_count": int(row["mention_count"] or 0),
            "sov_pct": 0,
            "visibility_pct": round((int(row["response_count"] or 0) / int(total_responses) * 100), 2) if total_responses else 0,
            "avg_position": None,
            "is_own": int(row["is_own"] or 0) == 1,
        }
        for row in rows
    ]
    own_brand_name = None
    if int(total_responses) > 0 and not any(entry["is_own"] for entry in entries):
        own_brand_name = await _get_primary_own_brand_name(response_params["client_id"])
    entries = inject_visibility_zero_own_brand(
        entries,
        total_responses=int(total_responses),
        own_brand_name=own_brand_name,
    )
    ranking = _ranked_visibility_entries(entries, "visibility_pct", reverse=True)
    own_entry = next((entry for entry in ranking if entry["is_own"]), None)
    return {
        "ranking": ranking,
        "own_rank": int(own_entry["rank"]) if own_entry else None,
        "own_visibility_pct": float(own_entry["visibility_pct"]) if own_entry else 0,
    }


async def _query_visibility_sov_chart(mention_where_sql: str, params: dict, interval: str) -> Dict[str, Any]:
    total_mentions = await database.fetch_val(
        f"SELECT COUNT(*) {_FROM_CLAUSE} WHERE {mention_where_sql}",
        params,
    ) or 0
    rows = await database.fetch_all(
        f"""
        SELECT
            bm.brand_name,
            COUNT(*) AS mention_count,
            MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS is_own,
            AVG(bm.mention_position) AS avg_position
        {_FROM_CLAUSE}
        WHERE {mention_where_sql}
        GROUP BY bm.brand_name
        """,
        params,
    )
    entries = []
    own_mentions = 0
    for row in rows:
        mention_count = int(row["mention_count"] or 0)
        is_own = int(row["is_own"] or 0) == 1
        if is_own:
            own_mentions += mention_count
        entries.append({
            "company_name": row["brand_name"],
            "brand_name": row["brand_name"],
            "mention_count": mention_count,
            "sov_pct": round((mention_count / int(total_mentions) * 100), 2) if total_mentions else 0,
            "visibility_pct": 0,
            "avg_position": round(float(row["avg_position"]), 2) if row["avg_position"] is not None else None,
            "is_own": is_own,
        })
    own_brand_name = None
    if int(total_mentions) > 0 and not any(entry["is_own"] for entry in entries):
        own_brand_name = await _get_primary_own_brand_name(params["client_id"])
    entries = inject_sov_zero_own_brand(
        entries,
        total_mentions=int(total_mentions),
        own_brand_name=own_brand_name,
    )
    ranking = _ranked_visibility_entries(entries, "mention_count", reverse=True)
    own_entry = next((entry for entry in ranking if entry["is_own"]), None)

    top_brands = [entry.get("brand_name") for entry in ranking[:5]]
    competitive_series: Dict[str, List[Dict[str, Any]]] = {}
    if top_brands:
        bucket_sql = date_bucket_expr("bm.executed_at", interval, timezone=SHANGHAI_TZ)
        placeholders = ",".join(f":top_brand_{i}" for i in range(len(top_brands)))
        comp_params = {**params}
        for i, name in enumerate(top_brands):
            comp_params[f"top_brand_{i}"] = name
        comp_rows = await database.fetch_all(
            f"""
            SELECT
                {bucket_sql} AS bucket,
                bm.brand_name,
                COUNT(*) AS mention_count
            {_FROM_CLAUSE}
            WHERE {mention_where_sql}
              AND bm.brand_name IN ({placeholders})
            GROUP BY {bucket_sql}, bm.brand_name
            ORDER BY {bucket_sql}
            """,
            comp_params,
        )
        for row in comp_rows:
            d = row["bucket"]
            date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
            competitive_series.setdefault(row["brand_name"], []).append({
                "date": date_str,
                "count": int(row["mention_count"] or 0),
            })
    return {
        "ranking": ranking,
        "own_sov": round((own_mentions / int(total_mentions) * 100), 2) if total_mentions else 0,
        "own_rank": int(own_entry["rank"]) if own_entry else None,
        "total_mentions": int(total_mentions),
        "own_mentions": own_mentions,
        "competitive_series": competitive_series,
    }


async def _query_visibility_position_chart(mention_where_sql: str, params: dict, interval: str) -> Dict[str, Any]:
    rows = await database.fetch_all(
        f"""
        SELECT
            bm.brand_name,
            COUNT(*) AS mention_count,
            MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS is_own,
            AVG(bm.mention_position) AS avg_position
        {_FROM_CLAUSE}
        WHERE {mention_where_sql}
        GROUP BY bm.brand_name
        HAVING AVG(bm.mention_position) IS NOT NULL
        """,
        params,
    )
    entries = [
        {
            "company_name": row["brand_name"],
            "brand_name": row["brand_name"],
            "mention_count": int(row["mention_count"] or 0),
            "sov_pct": 0,
            "visibility_pct": 0,
            "avg_position": round(float(row["avg_position"]), 2) if row["avg_position"] is not None else None,
            "is_own": int(row["is_own"] or 0) == 1,
        }
        for row in rows
    ]
    ranking = _ranked_visibility_entries(
        [entry for entry in entries if entry["avg_position"] is not None],
        "avg_position",
        reverse=False,
    )
    own_entry = next((entry for entry in ranking if entry["is_own"]), None)
    bucket_sql = date_bucket_expr("bm.executed_at", interval, timezone=SHANGHAI_TZ)
    ts_rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_sql} AS bucket,
            AVG(bm.mention_position) AS avg_pos
        {_FROM_CLAUSE}
        WHERE {mention_where_sql} AND bm.brand_role = 'own'
        GROUP BY {bucket_sql}
        ORDER BY {bucket_sql}
        """,
        params,
    )
    avg_position_series = []
    for row in ts_rows:
        d = row["bucket"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        avg_position_series.append({
            "date": date_str,
            "avg_position": round(float(row["avg_pos"]), 2) if row["avg_pos"] is not None else None,
        })
    if interval == "daily" and (bounds := _period_bounds(params)):
        by_date = {row["date"]: row for row in avg_position_series}
        avg_position_series = [
            by_date.get(day, {"date": day, "avg_position": None})
            for day in iter_date_strings(bounds[0], bounds[1])
        ]
    return {
        "ranking": ranking,
        "own_avg_position": float(own_entry["avg_position"]) if own_entry and own_entry["avg_position"] is not None else None,
        "own_rank": int(own_entry["rank"]) if own_entry else None,
        "avg_position_series": avg_position_series,
    }


@router.get("/visibility", response_model=VisibilityOut)
async def get_visibility(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    include_matrix: bool = True,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    visibility_sort_by: Optional[str] = None,
    visibility_sort_order: Optional[str] = None,
    sov_sort_by: Optional[str] = None,
    sov_sort_order: Optional[str] = None,
    position_sort_by: Optional[str] = None,
    position_sort_order: Optional[str] = None,
    topic_group_sort_by: Optional[str] = None,
    topic_group_sort_order: Optional[str] = None,
    product_group_sort_by: Optional[str] = None,
    product_group_sort_order: Optional[str] = None,
    matrix_prompt_sort_by: Optional[str] = None,
    matrix_prompt_sort_order: Optional[str] = None,
    matrix_brand_sort_by: Optional[str] = None,
    matrix_brand_sort_order: Optional[str] = None,
) -> VisibilityOut:
    """Pre-aggregated Visibility metrics with previous period comparison."""
    visibility_sort = resolve_sort_or_422(
        "visibility_visibility_ranking",
        visibility_sort_by if visibility_sort_by is not None else sort_by,
        visibility_sort_order if visibility_sort_order is not None else sort_order,
    )
    sov_sort = resolve_sort_or_422(
        "visibility_sov_ranking",
        sov_sort_by,
        sov_sort_order,
    )
    position_sort = resolve_sort_or_422(
        "visibility_position_ranking",
        position_sort_by,
        position_sort_order,
    )
    for list_type, scoped_by, scoped_order in (
        ("visibility_matrix_groups", topic_group_sort_by, topic_group_sort_order),
        ("visibility_matrix_groups", product_group_sort_by, product_group_sort_order),
        ("visibility_matrix_prompts", matrix_prompt_sort_by, matrix_prompt_sort_order),
        ("visibility_matrix_brands", matrix_brand_sort_by, matrix_brand_sort_order),
    ):
        if scoped_by is not None or scoped_order is not None:
            resolve_sort_or_422(list_type, scoped_by, scoped_order)
    start_date, end_date = parse_date_range(date_from, date_to)
    period_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    # Build base WHERE clauses (without date filters; those vary per period).
    mention_where_parts = ["bm.client_id = :client_id"]
    response_where_parts = ["gr.client_id = :client_id"]
    base_params: dict = {"client_id": client_id}
    prompt_id_list = parse_multi_value(prompt_ids)
    effective_prompt_id = None if prompt_id_list else prompt_id
    apply_common_filters(
        mention_where_parts, base_params,
        cp_alias="cp", mention_alias="bm",
        topic_id=topic_id, topic_ids=topic_ids, platform=platform,
        country=country, product=product, prompt_id=effective_prompt_id,
    )
    apply_common_filters(
        response_where_parts, base_params,
        cp_alias="cp", mention_alias="gr",
        topic_id=topic_id, topic_ids=topic_ids, platform=platform,
        country=country, product=product, prompt_id=effective_prompt_id,
    )
    if prompt_id_list:
        placeholders = ", ".join(f":apply_prompt_{i}" for i in range(len(prompt_id_list)))
        mention_where_parts.append(f"bm.client_prompt_id IN ({placeholders})")
        response_where_parts.append(f"gr.client_prompt_id IN ({placeholders})")
        for i, pid in enumerate(prompt_id_list):
            base_params[f"apply_prompt_{i}"] = pid

    vis_intent_rows = await database.fetch_all(
        """
        SELECT intent_name FROM geo_global_intents
        WHERE is_active = TRUE
          AND categories @> '["Visibility"]'::jsonb
        """
    )
    vis_intent_names = [r["intent_name"] for r in vis_intent_rows]
    if vis_intent_names:
        placeholders = ",".join(f":vis_intent_{i}" for i in range(len(vis_intent_names)))
        mention_where_parts.append(f"cp.intent IN ({placeholders})")
        response_where_parts.append(f"cp.intent IN ({placeholders})")
        for i, name in enumerate(vis_intent_names):
            base_params[f"vis_intent_{i}"] = name
    else:
        mention_where_parts.append("1 = 0")
        response_where_parts.append("1 = 0")

    mention_where_sql = " AND ".join(mention_where_parts)
    response_where_sql = " AND ".join(response_where_parts)

    # Current period
    curr_where_sql = mention_where_sql + " AND " + date_range_filter_expr("bm.executed_at", "start_date", "end_date")
    curr_response_where_sql = response_where_sql + " AND " + date_range_filter_expr("gr.ingested_at", "start_date", "end_date")
    curr_params = {**base_params, "start_date": start_date, "end_date": end_date}
    curr = await _query_visibility(curr_where_sql, curr_response_where_sql, curr_params, interval)

    # Previous period (reuse base WHERE with different date bounds via fresh keys)
    prev_where_sql = mention_where_sql + " AND " + date_range_filter_expr("bm.executed_at", "prev_start", "prev_end")
    prev_response_where_sql = response_where_sql + " AND " + date_range_filter_expr("gr.ingested_at", "prev_start", "prev_end")
    prev_params = {**base_params, "prev_start": prev_start, "prev_end": prev_end}
    prev = await _query_visibility(prev_where_sql, prev_response_where_sql, prev_params, interval)

    # Calculate changes
    def calc_change(curr_val, prev_val):
        if curr_val is None or prev_val is None:
            return None
        return round(curr_val - prev_val, 2)

    def calc_rank_change(curr_rank, prev_rank):
        if curr_rank is None or prev_rank is None:
            return None
        return int(curr_rank) - int(prev_rank)

    vis_change = calc_change(curr["visibility_score"], prev["visibility_score"])
    sov_change = calc_change(curr["own_sov"], prev["own_sov"])
    avg_pos_change = calc_change(curr["own_avg_position"], prev["own_avg_position"])
    vis_rank_change = calc_rank_change(curr["own_rank"], prev["own_rank"])
    sov_rank_change = calc_rank_change(curr["own_sov_rank"], prev["own_sov_rank"])
    avg_pos_rank_change = calc_rank_change(curr["own_avg_position_rank"], prev["own_avg_position_rank"])

    # Add change to sov_ranking (match on brand_name; fall back to legacy key)
    prev_sov_map = {r.get("brand_name", r.get("company_name")): r["sov_pct"] for r in prev["sov_ranking"]}
    prev_visibility_map = {
        r.get("brand_name", r.get("company_name")): r.get("visibility_pct")
        for r in prev["visibility_ranking"]
    }
    for r in curr["sov_ranking"]:
        brand_key = r.get("brand_name", r.get("company_name"))
        prev_pct = prev_sov_map.get(brand_key)
        r["sov_pct_change"] = round(r["sov_pct"] - prev_pct, 2) if prev_pct is not None else None
        prev_visibility_pct = prev_visibility_map.get(brand_key)
        r["visibility_pct_change"] = (
            round(r["visibility_pct"] - prev_visibility_pct, 2)
            if prev_visibility_pct is not None else None
        )
    for r in curr["visibility_ranking"]:
        brand_key = r.get("brand_name", r.get("company_name"))
        prev_visibility_pct = prev_visibility_map.get(brand_key)
        r["visibility_pct_change"] = (
            round(r["visibility_pct"] - prev_visibility_pct, 2)
            if prev_visibility_pct is not None else None
        )
    # Competitive Time Series (current period only)
    top_brands = [
        r.get("brand_name", r.get("company_name"))
        for r in curr["sov_ranking"][:5]
    ]
    competitive_series: Dict[str, List[Dict[str, Any]]] = {}
    if top_brands:
        bucket_sql = date_bucket_expr("bm.executed_at", interval, timezone=SHANGHAI_TZ)
        comp_placeholders = ",".join(f":top_brand_{i}" for i in range(len(top_brands)))
        comp_params = {**curr_params}
        for i, name in enumerate(top_brands):
            comp_params[f"top_brand_{i}"] = name
        comp_rows = await database.fetch_all(
            f"""
            SELECT
                {bucket_sql} AS bucket,
                bm.brand_name,
                COUNT(*) AS mention_count
            {_FROM_CLAUSE}
            WHERE {curr_where_sql}
              AND bm.brand_name IN ({comp_placeholders})
            GROUP BY {bucket_sql}, bm.brand_name
            ORDER BY {bucket_sql}
            """,
            comp_params,
        )
        for r in comp_rows:
            d = r["bucket"]
            date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
            name = r["brand_name"]
            competitive_series.setdefault(name, []).append(
                {"date": date_str, "count": r["mention_count"]}
            )

    topic_sov_ranking: List[Dict[str, Any]] = []
    product_sov_ranking: List[Dict[str, Any]] = []
    if include_matrix:
        # ----- Topic x Prompt x Brand ranking matrix (with drill-down) -----
        granular_rows = await database.fetch_all(
            f"""
            SELECT
                cp.topic_id,
                ct.topic_name,
                cp.id AS prompt_id,
                cp.text AS prompt_text,
                cp.product,
                cp.intent,
                cp.language,
                bm.brand_name AS company_name,
                COUNT(*) AS mention_count,
                MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END) AS is_own
            {_FROM_CLAUSE}
            JOIN geo_client_topics ct ON ct.id = cp.topic_id
            WHERE {curr_where_sql}
            GROUP BY cp.topic_id, ct.topic_name, cp.id, cp.text, cp.product, cp.intent, cp.language, bm.brand_name
            ORDER BY cp.topic_id, cp.id, COUNT(*) DESC
            """,
            curr_params,
        )

        topic_ranking = build_sov_ranking(
            granular_rows,
            group_key_fn=lambda r: str(r["topic_id"]),
            group_name_fn=lambda r: r["topic_name"],
        )
        topic_ranking = _sort_visibility_matrix(
            topic_ranking,
            group_sort_by=topic_group_sort_by,
            group_sort_order=topic_group_sort_order,
            prompt_sort_by=matrix_prompt_sort_by,
            prompt_sort_order=matrix_prompt_sort_order,
            brand_sort_by=matrix_brand_sort_by,
            brand_sort_order=matrix_brand_sort_order,
        )
        topic_sov_ranking = [
            {
                "topic_id": t["group_key"],
                "topic_name": t["group_name"],
                "total_mentions": t["total_mentions"],
                "prompt_count": t["prompt_count"],
                "brands": t["brands"],
                "prompts": t["prompts"],
            }
            for t in topic_ranking
        ]

        product_ranking = build_sov_ranking(
            granular_rows,
            group_key_fn=lambda r: (dict(r).get("product") or "Uncategorized"),
            group_name_fn=lambda r: (dict(r).get("product") or "Uncategorized"),
        )
        product_ranking = _sort_visibility_matrix(
            product_ranking,
            group_sort_by=product_group_sort_by,
            group_sort_order=product_group_sort_order,
            prompt_sort_by=matrix_prompt_sort_by,
            prompt_sort_order=matrix_prompt_sort_order,
            brand_sort_by=matrix_brand_sort_by,
            brand_sort_order=matrix_brand_sort_order,
        )
        product_sov_ranking = [
            {
                "product": p["group_name"],
                "total_mentions": p["total_mentions"],
                "prompt_count": p["prompt_count"],
                "brands": p["brands"],
                "prompts": p["prompts"],
            }
            for p in product_ranking
        ]

    curr["visibility_ranking"] = sort_complete_rows("visibility_visibility_ranking", curr["visibility_ranking"], visibility_sort.sort_by, visibility_sort.sort_order)
    curr["sov_ranking"] = sort_complete_rows("visibility_sov_ranking", curr["sov_ranking"], sov_sort.sort_by, sov_sort.sort_order)
    curr["position_ranking"] = sort_complete_rows("visibility_position_ranking", curr["position_ranking"], position_sort.sort_by, position_sort.sort_order)

    return VisibilityOut(
        summary=VisibilitySummary(
            visibility_score=curr["visibility_score"],
            visibility_score_change=vis_change,
            visibility_rank=curr["own_rank"],
            visibility_rank_change=vis_rank_change,
            mentioned=curr["mentioned"],
            total_query=curr["total_query"],
            sov_pct=curr["own_sov"],
            sov_pct_change=sov_change,
            sov_rank=curr["own_sov_rank"],
            sov_rank_change=sov_rank_change,
            total_mentions=curr["total_mentions"],
            own_mentions=curr["own_mentions"],
            avg_position=curr["own_avg_position"],
            avg_position_change=avg_pos_change,
            avg_position_rank=curr["own_avg_position_rank"],
            avg_position_rank_change=avg_pos_rank_change,
        ),
        time_series=[VisibilityTimePoint(**p) for p in curr["time_series"]],
        prev_time_series=[VisibilityTimePoint(**p) for p in prev["time_series"]],
        avg_position_series=[AvgPositionPoint(**p) for p in curr["avg_position_series"]],
        prev_avg_position_series=[AvgPositionPoint(**p) for p in prev["avg_position_series"]],
        competitive_series={
            k: [CompetitiveSeriesPoint(**p) for p in v]
            for k, v in competitive_series.items()
        },
        sov_ranking=[VisibilitySovRow(**r) for r in curr["sov_ranking"]],
        visibility_ranking=[VisibilitySovRow(**r) for r in curr["visibility_ranking"]],
        position_ranking=[VisibilitySovRow(**r) for r in curr["position_ranking"]],
        topic_sov_ranking=[TopicSovEntry(**t) for t in topic_sov_ranking],
        product_sov_ranking=[ProductSovEntry(**p) for p in product_sov_ranking],
        filters=VisibilityFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            prev_date_from=prev_start.isoformat(),
            prev_date_to=prev_end.isoformat(),
            interval=interval,
        ),
    )


@router.get("/visibility/overview", response_model=VisibilityOut)
async def get_visibility_overview(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
) -> VisibilityOut:
    return await get_visibility(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
        include_matrix=False,
    )


@router.get("/visibility/score", response_model=VisibilityOut)
async def get_visibility_score_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
) -> VisibilityOut:
    ctx = await _visibility_chart_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
    )
    curr = await _query_visibility_score_chart(ctx["curr_response_where_sql"], ctx["curr_params"], interval)
    prev = await _query_visibility_score_chart(ctx["prev_response_where_sql"], ctx["prev_params"], interval)
    return _empty_visibility_out(
        filters=ctx["filters"],
        summary=_empty_visibility_summary(
            visibility_score=curr["visibility_score"],
            visibility_score_change=_calc_change(curr["visibility_score"], prev["visibility_score"]),
            mentioned=curr["mentioned"],
            total_query=curr["total_query"],
        ),
        time_series=curr["time_series"],
        prev_time_series=prev["time_series"],
    )


@router.get("/visibility/brand-ranking", response_model=VisibilityOut)
async def get_visibility_brand_ranking_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> VisibilityOut:
    resolved_sort = resolve_sort_or_422("visibility_visibility_ranking", sort_by, sort_order)
    ctx = await _visibility_chart_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
    )
    curr = await _query_visibility_brand_ranking_chart(ctx["curr_response_where_sql"], ctx["curr_params"])
    prev = await _query_visibility_brand_ranking_chart(ctx["prev_response_where_sql"], ctx["prev_params"])
    prev_pct_map = {row.get("brand_name", row.get("company_name")): row.get("visibility_pct") for row in prev["ranking"]}
    for row in curr["ranking"]:
        prev_pct = prev_pct_map.get(row.get("brand_name", row.get("company_name")))
        row["visibility_pct_change"] = _calc_change(row.get("visibility_pct"), prev_pct)
    curr["ranking"] = sort_complete_rows(
        "visibility_visibility_ranking", curr["ranking"], resolved_sort.sort_by, resolved_sort.sort_order
    )
    return _empty_visibility_out(
        filters=ctx["filters"],
        summary=_empty_visibility_summary(
            visibility_rank=curr["own_rank"],
            visibility_rank_change=_calc_rank_change(curr["own_rank"], prev["own_rank"]),
        ),
        visibility_ranking=curr["ranking"],
    )


@router.get("/visibility/sov", response_model=VisibilityOut)
async def get_visibility_sov_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> VisibilityOut:
    resolved_sort = resolve_sort_or_422("visibility_sov_ranking", sort_by, sort_order)
    ctx = await _visibility_chart_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
    )
    curr = await _query_visibility_sov_chart(ctx["curr_where_sql"], ctx["curr_params"], interval)
    prev = await _query_visibility_sov_chart(ctx["prev_where_sql"], ctx["prev_params"], interval)
    prev_pct_map = {row.get("brand_name", row.get("company_name")): row.get("sov_pct") for row in prev["ranking"]}
    for row in curr["ranking"]:
        prev_pct = prev_pct_map.get(row.get("brand_name", row.get("company_name")))
        row["sov_pct_change"] = _calc_change(row.get("sov_pct"), prev_pct)
    curr["ranking"] = sort_complete_rows(
        "visibility_sov_ranking", curr["ranking"], resolved_sort.sort_by, resolved_sort.sort_order
    )
    return _empty_visibility_out(
        filters=ctx["filters"],
        summary=_empty_visibility_summary(
            sov_pct=curr["own_sov"],
            sov_pct_change=_calc_change(curr["own_sov"], prev["own_sov"]),
            sov_rank=curr["own_rank"],
            sov_rank_change=_calc_rank_change(curr["own_rank"], prev["own_rank"]),
            total_mentions=curr["total_mentions"],
            own_mentions=curr["own_mentions"],
        ),
        sov_ranking=curr["ranking"],
        competitive_series=curr["competitive_series"],
    )


@router.get("/visibility/sov-ranking", response_model=VisibilityOut)
async def get_visibility_sov_ranking_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> VisibilityOut:
    return await get_visibility_sov_chart(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/visibility/position", response_model=VisibilityOut)
async def get_visibility_position_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> VisibilityOut:
    resolved_sort = resolve_sort_or_422("visibility_position_ranking", sort_by, sort_order)
    ctx = await _visibility_chart_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
    )
    curr = await _query_visibility_position_chart(ctx["curr_where_sql"], ctx["curr_params"], interval)
    prev = await _query_visibility_position_chart(ctx["prev_where_sql"], ctx["prev_params"], interval)
    curr["ranking"] = sort_complete_rows(
        "visibility_position_ranking", curr["ranking"], resolved_sort.sort_by, resolved_sort.sort_order
    )
    return _empty_visibility_out(
        filters=ctx["filters"],
        summary=_empty_visibility_summary(
            avg_position=curr["own_avg_position"],
            avg_position_change=_calc_change(curr["own_avg_position"], prev["own_avg_position"]),
            avg_position_rank=curr["own_rank"],
            avg_position_rank_change=_calc_rank_change(curr["own_rank"], prev["own_rank"]),
        ),
        avg_position_series=curr["avg_position_series"],
        prev_avg_position_series=prev["avg_position_series"],
        position_ranking=curr["ranking"],
    )


@router.get("/visibility/position-ranking", response_model=VisibilityOut)
async def get_visibility_position_ranking_chart(
    client_id: UUID,
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> VisibilityOut:
    return await get_visibility_position_chart(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/visibility/ranking-groups", response_model=VisibilityRankingGroupsOut)
async def get_visibility_ranking_groups(
    client_id: UUID,
    group_by: str = Query("topic", pattern="^(topic|product)$"),
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    brand_sort_by: Optional[str] = None,
    brand_sort_order: Optional[str] = None,
) -> VisibilityRankingGroupsOut:
    resolved_sort = resolve_sort_or_422("visibility_ranking_groups", sort_by, sort_order)
    resolved_brand_sort = resolve_sort_or_422("visibility_matrix_brands", brand_sort_by, brand_sort_order)
    curr_where_sql, _, curr_params, start_date, end_date, prev_start, prev_end = await _build_visibility_filter_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
    )
    if group_by == "topic":
        group_key_sql = "cp.topic_id::text"
        group_name_sql = "ct.topic_name"
        join_sql = "LEFT JOIN geo_client_topics ct ON ct.id = cp.topic_id AND ct.client_id = cp.client_id"
    else:
        group_key_sql = "COALESCE(NULLIF(cp.product, ''), 'Uncategorized')"
        group_name_sql = "COALESCE(NULLIF(cp.product, ''), 'Uncategorized')"
        join_sql = ""
    prompt_key_sql = logical_prompt_key_sql("cp")

    rows = await database.fetch_all(
        f"""
        SELECT
            {group_key_sql} AS group_key,
            {group_name_sql} AS group_name,
            {prompt_key_sql} AS prompt_key,
            bm.brand_name,
            COUNT(*)::int AS mention_count,
            MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END)::int AS is_own
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp
          ON cp.id = bm.client_prompt_id
         AND cp.client_id = bm.client_id
        {join_sql}
        WHERE {curr_where_sql}
        GROUP BY {group_key_sql}, {group_name_sql}, {prompt_key_sql}, bm.brand_name
        """,
        curr_params,
    )

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = row["group_key"] or "Uncategorized"
        if key not in grouped:
            grouped[key] = {
                "group_key": key,
                "group_name": row["group_name"] or key,
                "prompt_keys": set(),
                "brands": {},
                "total_mentions": 0,
            }
        grouped[key]["prompt_keys"].add(row["prompt_key"])
        grouped[key]["total_mentions"] += int(row["mention_count"])
        brand_counts = grouped[key]["brands"]
        brand = row["brand_name"]
        if brand not in brand_counts:
            brand_counts[brand] = {"mention_count": 0, "is_own": False}
        brand_counts[brand]["mention_count"] += int(row["mention_count"])
        brand_counts[brand]["is_own"] = brand_counts[brand]["is_own"] or int(row["is_own"]) == 1

    group_rows = [
        {
            **value,
            "prompt_count": len(value["prompt_keys"]),
        }
        for value in grouped.values()
    ]
    group_rows = sort_complete_rows(
        "visibility_ranking_groups", group_rows, resolved_sort.sort_by, resolved_sort.sort_order
    )
    items = [
        VisibilityRankingGroup(
            group_key=value["group_key"],
            group_name=value["group_name"],
            prompt_count=value["prompt_count"],
            total_mentions=value["total_mentions"],
            brands=sort_complete_rows(
                "visibility_matrix_brands",
                _rank_brands_from_counts(value["brands"]),
                resolved_brand_sort.sort_by,
                resolved_brand_sort.sort_order,
            ),
        )
        for value in group_rows
    ]
    return VisibilityRankingGroupsOut(
        group_by=group_by,
        items=items,
        filters=VisibilityFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            prev_date_from=prev_start.isoformat(),
            prev_date_to=prev_end.isoformat(),
            interval="daily",
        ),
    )


@router.get("/visibility/ranking-prompts", response_model=VisibilityRankingPromptsOut)
async def get_visibility_ranking_prompts(
    client_id: UUID,
    group_by: str = Query("topic", pattern="^(topic|product)$"),
    group_key: str = Query(...),
    topic_id: Optional[str] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[str] = None,
    prompt_ids: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    brand_sort_by: Optional[str] = None,
    brand_sort_order: Optional[str] = None,
) -> VisibilityRankingPromptsOut:
    resolved_sort = resolve_sort_or_422("visibility_ranking_prompts", sort_by, sort_order)
    resolved_brand_sort = resolve_sort_or_422("visibility_matrix_brands", brand_sort_by, brand_sort_order)
    limit = int(limit) if isinstance(limit, int) else 20
    offset = int(offset) if isinstance(offset, int) else 0
    curr_where_sql, _, curr_params, start_date, end_date, prev_start, prev_end = await _build_visibility_filter_context(
        client_id=client_id,
        topic_id=topic_id,
        topic_ids=topic_ids,
        platform=platform,
        country=country,
        product=product,
        prompt_id=prompt_id,
        prompt_ids=prompt_ids,
        date_from=date_from,
        date_to=date_to,
    )
    params = {**curr_params, "group_key": group_key, "limit": limit, "offset": offset}
    if group_by == "topic":
        group_filter_sql = "cp.topic_id::text = :group_key"
    else:
        group_filter_sql = "COALESCE(NULLIF(cp.product, ''), 'Uncategorized') = :group_key"
    prompt_key_sql = logical_prompt_key_sql("cp")

    total = await database.fetch_val(
        f"""
        SELECT COUNT(*) FROM (
            SELECT {prompt_key_sql} AS prompt_key
            FROM geo_brand_mentions bm
            JOIN geo_client_prompts cp
              ON cp.id = bm.client_prompt_id
             AND cp.client_id = bm.client_id
            WHERE {curr_where_sql}
              AND {group_filter_sql}
            GROUP BY {prompt_key_sql}
        ) prompt_groups
        """,
        params,
    ) or 0

    rows = await database.fetch_all(
        f"""
        WITH prompt_page AS (
            SELECT
                {prompt_key_sql} AS prompt_key,
                MIN(cp.id::text) AS prompt_id,
                MIN(cp.text) AS prompt_text,
                COUNT(*)::int AS total_mentions,
                ROW_NUMBER() OVER (ORDER BY {resolved_sort.order_by_sql})::int AS page_ordinal
            FROM geo_brand_mentions bm
            JOIN geo_client_prompts cp
              ON cp.id = bm.client_prompt_id
             AND cp.client_id = bm.client_id
            WHERE {curr_where_sql}
              AND {group_filter_sql}
            GROUP BY {prompt_key_sql}
            ORDER BY {resolved_sort.order_by_sql}
            OFFSET :offset
            LIMIT :limit
        )
        SELECT
            pp.prompt_key,
            pp.prompt_id,
            pp.prompt_text,
            pp.page_ordinal,
            pp.total_mentions,
            bm.brand_name,
            COUNT(*)::int AS mention_count,
            MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END)::int AS is_own
        FROM prompt_page pp
        JOIN geo_brand_mentions bm
          ON bm.client_id = :client_id
        JOIN geo_client_prompts cp
          ON cp.id = bm.client_prompt_id
         AND cp.client_id = bm.client_id
         AND {prompt_key_sql} = pp.prompt_key
        WHERE {curr_where_sql}
          AND {group_filter_sql}
        GROUP BY pp.prompt_key, pp.prompt_id, pp.prompt_text, pp.page_ordinal, pp.total_mentions, bm.brand_name
        ORDER BY pp.page_ordinal ASC, COUNT(*) DESC, LOWER(bm.brand_name) ASC, bm.brand_name ASC
        """,
        params,
    )

    prompt_map: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = row["prompt_key"]
        if key not in prompt_map:
            row_data = dict(row)
            prompt_map[key] = {
                "prompt_id": str(row_data.get("prompt_id") or key),
                "prompt_text": row["prompt_text"],
                "total_mentions": int(row_data.get("total_mentions") or 0),
                "brands": {},
            }
        brand = row["brand_name"]
        prompt_map[key]["brands"][brand] = {
            "mention_count": int(row["mention_count"]),
            "is_own": int(row["is_own"]) == 1,
        }

    for prompt in prompt_map.values():
        if prompt["total_mentions"] == 0:
            prompt["total_mentions"] = sum(
                int(brand["mention_count"]) for brand in prompt["brands"].values()
            )

    items = [
        VisibilityRankingPrompt(
            prompt_id=value["prompt_id"],
            prompt_text=value["prompt_text"],
            total_mentions=value["total_mentions"],
            brands=sort_complete_rows(
                "visibility_matrix_brands",
                _rank_brands_from_counts(value["brands"]),
                resolved_brand_sort.sort_by,
                resolved_brand_sort.sort_order,
            ),
        )
        for value in prompt_map.values()
    ]
    return VisibilityRankingPromptsOut(
        group_by=group_by,
        group_key=group_key,
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
        filters=VisibilityFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            prev_date_from=prev_start.isoformat(),
            prev_date_to=prev_end.isoformat(),
            interval="daily",
        ),
    )
