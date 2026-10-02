"""Prompt-level own-brand visibility metrics for the Prompts table."""
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from db import database
from ._helpers import parse_date_range
from .sorting import resolve_sort_or_422, sort_complete_rows

router = APIRouter()


class PromptMetricRow(BaseModel):
    mentioned: int = 0
    total_query: int = 0
    visibility_score: float = 0
    brand_rank: Optional[int] = None
    avg_position: Optional[float] = None
    position_sum: float = 0
    position_count: int = 0
    brand_response_counts: Dict[str, int] = Field(default_factory=dict)
    brand_mention_counts: Dict[str, int] = Field(default_factory=dict)
    own_brand_names: List[str] = Field(default_factory=list)

    # Back-compat fields used by older clients. They now mirror the own-brand
    # query-level definition instead of all-brand mention rows.
    mention_count: int = 0
    citation_count: int = 0


class PromptMetricsOut(BaseModel):
    metrics: Dict[str, PromptMetricRow]
    ordered_prompt_ids: List[str] = Field(default_factory=list)
    total: int = 0


@router.get("/prompts/metrics", response_model=PromptMetricsOut)
async def get_prompt_metrics(
    client_id: UUID,
    topic_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> PromptMetricsOut:
    """
    Per-prompt own-brand visibility metrics for the Prompts table.

    ``mentioned`` and ``total_query`` are query/result-level counts:
    - mentioned = distinct AI responses that mention the own brand
    - total_query = distinct AI responses collected for the prompt
    - visibility_score = mentioned / total_query
    """
    resolved_sort = resolve_sort_or_422("prompt_metrics", sort_by, sort_order)
    start_date, end_date = parse_date_range(date_from, date_to)

    response_where = [
        "gr.client_id = :client_id",
        "cp.is_active = TRUE",
        "gr.ingested_at::date >= :start_date",
        "gr.ingested_at::date <= :end_date",
    ]
    mention_where = [
        "bm.client_id = :client_id",
        "cp.is_active = TRUE",
        "bm.brand_role = 'own'",
        "bm.executed_at::date >= :start_date",
        "bm.executed_at::date <= :end_date",
    ]
    params = {
        "client_id": client_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if topic_id:
        response_where.append("cp.topic_id = :topic_id")
        mention_where.append("cp.topic_id = :topic_id")
        params["topic_id"] = topic_id

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
        response_where.append(f"cp.intent IN ({placeholders})")
        mention_where.append(f"cp.intent IN ({placeholders})")
        for i, name in enumerate(vis_intent_names):
            params[f"vis_intent_{i}"] = name
    else:
        response_where.append("1 = 0")
        mention_where.append("1 = 0")

    prompt_universe_where = ["client_id = :client_id", "is_active = TRUE"]
    if topic_id:
        prompt_universe_where.append("topic_id = :topic_id")
    prompt_universe_rows = await database.fetch_all(
        f"""
        SELECT id AS client_prompt_id
        FROM geo_client_prompts
        WHERE {" AND ".join(prompt_universe_where)}
        ORDER BY id
        """,
        params,
    )

    response_rows = await database.fetch_all(
        f"""
        SELECT
            gr.client_prompt_id,
            COUNT(DISTINCT gr.result_id)::int AS total_query,
            COUNT(DISTINCT CASE WHEN bm.result_id IS NOT NULL THEN gr.result_id END)::int AS mentioned
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        LEFT JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
         AND bm.brand_role = 'own'
        WHERE {" AND ".join(response_where)}
        GROUP BY gr.client_prompt_id
        """,
        params,
    )
    response_map = {
        str(r["client_prompt_id"]): {
            "mentioned": int(r["mentioned"] or 0),
            "total_query": int(r["total_query"] or 0),
        }
        for r in response_rows
    }

    position_rows = await database.fetch_all(
        f"""
        SELECT
            bm.client_prompt_id,
            SUM(bm.mention_position)::float AS position_sum,
            COUNT(*)::int AS position_count,
            AVG(bm.mention_position) AS avg_position
        FROM geo_brand_mentions bm
        JOIN geo_client_prompts cp ON cp.id = bm.client_prompt_id AND cp.client_id = bm.client_id
        WHERE {" AND ".join(mention_where)}
        GROUP BY bm.client_prompt_id
        """,
        params,
    )
    position_map = {
        str(r["client_prompt_id"]): {
            "position_sum": float(r["position_sum"] or 0),
            "position_count": int(r["position_count"] or 0),
            "avg_position": round(float(r["avg_position"]), 1) if r["avg_position"] is not None else None,
        }
        for r in position_rows
    }

    brand_rows = await database.fetch_all(
        f"""
        SELECT
            gr.client_prompt_id,
            bm.brand_name,
            COUNT(DISTINCT gr.result_id)::int AS response_count,
            COUNT(*)::int AS mention_count,
            MAX(CASE WHEN bm.brand_role = 'own' THEN 1 ELSE 0 END)::int AS is_own
        FROM geo_results gr
        JOIN geo_client_prompts cp ON cp.id = gr.client_prompt_id AND cp.client_id = gr.client_id
        JOIN geo_brand_mentions bm
          ON bm.result_id = gr.result_id
         AND bm.client_id = gr.client_id
        WHERE {" AND ".join(response_where)}
        GROUP BY gr.client_prompt_id, bm.brand_name
        """,
        params,
    )
    brand_response_map: Dict[str, Dict[str, int]] = {}
    brand_mention_map: Dict[str, Dict[str, int]] = {}
    own_brand_map: Dict[str, List[str]] = {}
    for r in brand_rows:
        pid = str(r["client_prompt_id"])
        brand = str(r["brand_name"] or "").strip()
        if not brand:
            continue
        brand_response_map.setdefault(pid, {})[brand] = int(r["response_count"] or 0)
        brand_mention_map.setdefault(pid, {})[brand] = int(r["mention_count"] or 0)
        if int(r["is_own"] or 0) == 1:
            own_brand_map.setdefault(pid, [])
            if brand not in own_brand_map[pid]:
                own_brand_map[pid].append(brand)

    def _own_brand_rank(
        total_query: int,
        response_counts: Dict[str, int],
        mention_counts: Dict[str, int],
        own_brand_names: List[str],
    ) -> Optional[int]:
        if total_query <= 0 or not own_brand_names:
            return None
        entries = sorted(
            response_counts.items(),
            key=lambda item: (
                -round((item[1] / total_query * 100), 1),
                -mention_counts.get(item[0], 0),
                item[0].lower(),
            ),
        )
        current_rank = 0
        prev_visibility: Optional[float] = None
        own_names = set(own_brand_names)
        for index, (brand, response_count) in enumerate(entries):
            visibility_pct = round((response_count / total_query * 100), 1)
            if visibility_pct != prev_visibility:
                current_rank = index + 1
                prev_visibility = visibility_pct
            if brand in own_names and response_count > 0:
                return current_rank
        return None

    all_prompt_ids = (
        {str(row["client_prompt_id"]) for row in prompt_universe_rows}
        | set(response_map.keys())
        | set(position_map.keys())
        | set(brand_response_map.keys())
    )
    metrics = {}
    for pid in all_prompt_ids:
        response = response_map.get(pid, {})
        position = position_map.get(pid, {})
        mentioned = response.get("mentioned", 0)
        total_query = response.get("total_query", 0)
        brand_response_counts = brand_response_map.get(pid, {})
        brand_mention_counts = brand_mention_map.get(pid, {})
        own_brand_names = own_brand_map.get(pid, [])
        score = round((mentioned / total_query * 100), 1) if total_query > 0 else 0
        metrics[pid] = {
            "mentioned": mentioned,
            "total_query": total_query,
            "visibility_score": score,
            "brand_rank": _own_brand_rank(
                total_query,
                brand_response_counts,
                brand_mention_counts,
                own_brand_names,
            ),
            "avg_position": position.get("avg_position"),
            "position_sum": position.get("position_sum", 0),
            "position_count": position.get("position_count", 0),
            "brand_response_counts": brand_response_counts,
            "brand_mention_counts": brand_mention_counts,
            "own_brand_names": own_brand_names,
            "mention_count": mentioned,
            "citation_count": 0,
        }

    metric_rows = sort_complete_rows(
        "prompt_metrics",
        [{"prompt_id": pid, **values} for pid, values in metrics.items()],
        resolved_sort.sort_by,
        resolved_sort.sort_order,
    )
    return PromptMetricsOut(
        metrics={
            row["prompt_id"]: PromptMetricRow(**{key: value for key, value in row.items() if key != "prompt_id"})
            for row in metric_rows
        },
        ordered_prompt_ids=[row["prompt_id"] for row in metric_rows],
        total=len(metric_rows),
    )
