"""
Topic-level visibility — ranking + time series aggregated at the topic
granularity.

v1.2 Spec §8.4 "View By" dimension switch: the Insights toolbar lets the
user pivot the Visibility dashboard between ``brand / product / topic /
cross``. This endpoint feeds the ``topic`` pivot.

Shape mirrors ``/visibility`` so the existing dashboard component can
render it with minimal branching:

  {
    "dimension": "topic",
    "ranking":   [{ "topic_id", "topic_name", "mention_count",
                     "own_mention_count", "own_sov_pct", ... }],
    "time_series": [{ "date", "total", "own_count", "score" }],
    "top_entities_series": { "<topic_name>": [{ "date", "count" }] },
    "totals":    { "topics", "mentions", "own_mentions" }
  }

Empty-state: ``{"data": [], "reason": "no_data"}`` when the client has zero
topic-tagged mentions in the window.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import database

from ._helpers import SHANGHAI_TZ, apply_common_filters, date_bucket_expr, date_range_filter_expr, parse_date_range
from .sorting import resolve_sort_or_422, sort_complete_rows

router = APIRouter()


class TopicVisibilityRankingRow(BaseModel):
    topic_id: str
    topic_name: Optional[str] = None
    mention_count: int
    own_mention_count: int
    own_sov_pct: float
    sov_pct: float


class TopicVisibilityTimePoint(BaseModel):
    date: str
    total: int
    own_count: int
    score: float


class TopicVisibilityTopSeriesPoint(BaseModel):
    date: str
    count: int


class TopicVisibilityTotals(BaseModel):
    topics: int
    mentions: int
    own_mentions: int


class TopicVisibilityOut(BaseModel):
    dimension: str
    ranking: List[TopicVisibilityRankingRow]
    time_series: List[TopicVisibilityTimePoint]
    top_entities_series: Dict[str, List[TopicVisibilityTopSeriesPoint]]
    totals: TopicVisibilityTotals
    reason: Optional[str] = None


@router.get("/topic-visibility", response_model=TopicVisibilityOut)
async def get_topic_visibility(
    client_id: UUID,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    prompt_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> TopicVisibilityOut:
    resolved_sort = resolve_sort_or_422("topic_visibility", sort_by, sort_order)
    start_date, end_date = parse_date_range(date_from, date_to)

    where_parts = [
        "bm.client_id = :client_id",
        "cp.topic_id IS NOT NULL",
        date_range_filter_expr("bm.executed_at", "start_date", "end_date"),
    ]
    params: dict = {
        "client_id": client_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    apply_common_filters(
        where_parts, params,
        cp_alias="cp", mention_alias="bm",
        topic_ids=topic_ids, platform=platform,
        country=country, prompt_id=prompt_id,
    )
    where_sql = " AND ".join(where_parts)

    own_expr = "CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END"

    # Ranking: total + own mentions per topic, sorted by total desc.
    rank_rows = await database.fetch_all(
        f"""
        SELECT
            cp.topic_id AS topic_id,
            ct.topic_name AS topic_name,
            COUNT(*) AS mention_count,
            SUM({own_expr})::int AS own_count
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp ON cp.id = bm.client_prompt_id
        JOIN geo_client_topics ct ON ct.id = cp.topic_id
        WHERE {where_sql}
        GROUP BY cp.topic_id, ct.topic_name
        ORDER BY COUNT(*) DESC
        """,
        params,
    )

    if not rank_rows:
        return TopicVisibilityOut(
            dimension="topic",
            ranking=[],
            time_series=[],
            top_entities_series={},
            totals=TopicVisibilityTotals(topics=0, mentions=0, own_mentions=0),
            reason="no_data",
        )

    total_mentions = sum(r["mention_count"] for r in rank_rows)
    total_own = sum((r["own_count"] or 0) for r in rank_rows)

    ranking = []
    for r in rank_rows:
        count = int(r["mention_count"])
        own = int(r["own_count"] or 0)
        ranking.append({
            "topic_id": str(r["topic_id"]),
            "topic_name": r["topic_name"],
            "mention_count": count,
            "own_mention_count": own,
            "own_sov_pct": round((own / count * 100), 2) if count > 0 else 0.0,
            "sov_pct": round((count / total_mentions * 100), 2) if total_mentions > 0 else 0.0,
        })
    ranking = sort_complete_rows(
        "topic_visibility", ranking, resolved_sort.sort_by, resolved_sort.sort_order
    )

    # Time series: daily own-SOV across ALL topics in scope.
    bucket_sql = date_bucket_expr("bm.executed_at", interval, timezone=SHANGHAI_TZ)
    ts_rows = await database.fetch_all(
        f"""
        SELECT
            {bucket_sql} AS bucket,
            COUNT(*) AS total,
            SUM({own_expr})::int AS own_count
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp ON cp.id = bm.client_prompt_id
        JOIN geo_client_topics ct ON ct.id = cp.topic_id
        WHERE {where_sql}
        GROUP BY {bucket_sql}
        ORDER BY {bucket_sql}
        """,
        params,
    )
    time_series = []
    for r in ts_rows:
        d = r["bucket"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        total = int(r["total"])
        own = int(r["own_count"] or 0)
        time_series.append({
            "date": date_str,
            "total": total,
            "own_count": own,
            "score": round((own / total * 100), 2) if total > 0 else 0.0,
        })

    # Per-topic time series (top 5 topics) for the competitive chart.
    top_topic_ids = [r["topic_id"] for r in rank_rows[:5]]
    top_series: dict = {}
    if top_topic_ids:
        top_placeholders = ",".join(f":top_tid_{i}" for i in range(len(top_topic_ids)))
        top_params = {**params}
        for i, tid in enumerate(top_topic_ids):
            top_params[f"top_tid_{i}"] = tid
        per_topic_rows = await database.fetch_all(
            f"""
            SELECT
                {bucket_sql} AS bucket,
                ct.topic_name AS topic_name,
                COUNT(*) AS mention_count
            FROM geo_brand_mentions bm
            JOIN geo_client_prompts cp ON cp.id = bm.client_prompt_id
            JOIN geo_client_topics ct ON ct.id = cp.topic_id
            WHERE {where_sql}
              AND cp.topic_id IN ({top_placeholders})
            GROUP BY {bucket_sql}, ct.topic_name
            ORDER BY {bucket_sql}
            """,
            top_params,
        )
        for r in per_topic_rows:
            d = r["bucket"]
            date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
            name = r["topic_name"]
            top_series.setdefault(name, []).append({
                "date": date_str,
                "count": int(r["mention_count"]),
            })

    return TopicVisibilityOut(
        dimension="topic",
        ranking=[TopicVisibilityRankingRow(**r) for r in ranking],
        time_series=[TopicVisibilityTimePoint(**p) for p in time_series],
        top_entities_series={
            k: [TopicVisibilityTopSeriesPoint(**p) for p in v]
            for k, v in top_series.items()
        },
        totals=TopicVisibilityTotals(
            topics=len(ranking),
            mentions=total_mentions,
            own_mentions=total_own,
        ),
    )
