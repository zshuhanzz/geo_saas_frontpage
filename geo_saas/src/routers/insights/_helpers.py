"""
Shared helpers for the Insights sub-module.

Phase 2.5b (2026-04-26): rewritten to emit raw SQL fragments + named-param
dicts instead of SQLAlchemy ``Column`` expressions. Insights routers now
build ``WHERE`` clauses by appending ``(snippet, params)`` pairs onto a
local list and joining at the call site.

Public surface:
    - ``parse_date_range``        — date string → (start, end) defaults
    - ``parse_multi_value``       — comma-separated query param → list[str]
    - ``date_bucket_expr``        — interval → bucket SQL fragment for ``date_col``
    - ``apply_common_filters``    — append common filter snippets to a list
    - ``build_sov_ranking``       — group g_rows into topic/product SOV ranking
    - ``rank_visibility_entries`` — canonical standalone Visibility API ranks
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


def canonical_zero_own_brand_entry(brand_name: str) -> dict[str, Any]:
    """Build the canonical zero-observation own-brand row used by Visibility."""
    return {
        "company_name": brand_name,
        "brand_name": brand_name,
        "mention_count": 0,
        "sov_pct": 0,
        "visibility_pct": 0,
        "avg_position": None,
        "is_own": True,
    }


def competition_rank_entries(
    sorted_entries: list[dict[str, Any]],
    rank_value_key: str,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    previous_value = object()
    current_rank = 0
    for index, entry in enumerate(sorted_entries):
        value = entry.get(rank_value_key)
        if value != previous_value:
            current_rank = index + 1
            previous_value = value
        ranked.append({**entry, "rank": current_rank})
    return ranked


def rank_visibility_entries(
    entries: list[dict[str, Any]],
    rank_value_key: str,
    *,
    reverse: bool,
) -> list[dict[str, Any]]:
    """Apply the standalone Visibility APIs' ordering and competition rank."""
    return competition_rank_entries(
        sorted(
            entries,
            key=lambda entry: (
                -float(entry.get(rank_value_key) or 0) if reverse else float(entry.get(rank_value_key) or 0),
                -int(entry.get("mention_count") or 0),
                str(entry.get("brand_name") or entry.get("company_name") or "").lower(),
            ),
        ),
        rank_value_key,
    )


def _inject_zero_own_brand(
    entries: list[dict[str, Any]],
    *,
    universe_total: int,
    own_brand_name: str | None,
) -> list[dict[str, Any]]:
    copied = [{**entry} for entry in entries]
    if universe_total > 0 and not any(bool(entry.get("is_own")) for entry in copied) and own_brand_name:
        copied.append(canonical_zero_own_brand_entry(own_brand_name))
    return copied


def inject_visibility_zero_own_brand(
    entries: list[dict[str, Any]],
    *,
    total_responses: int,
    own_brand_name: str | None,
) -> list[dict[str, Any]]:
    """Visibility ranking uses the result-ingested response universe."""
    return _inject_zero_own_brand(entries, universe_total=total_responses, own_brand_name=own_brand_name)


def inject_sov_zero_own_brand(
    entries: list[dict[str, Any]],
    *,
    total_mentions: int,
    own_brand_name: str | None,
) -> list[dict[str, Any]]:
    """SOV ranking uses the mention-executed universe."""
    return _inject_zero_own_brand(entries, universe_total=total_mentions, own_brand_name=own_brand_name)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

SHANGHAI_TZ = "Asia/Shanghai"


def parse_date_range(date_from: Optional[str], date_to: Optional[str]):
    """Parse date range strings into ``date`` objects, with sensible defaults.

    Default window is the last 7 days ending today, which mirrors the legacy
    ``databases``-era behaviour.
    """
    today = datetime.now(ZoneInfo(SHANGHAI_TZ)).date()
    if date_to:
        try:
            end = date.fromisoformat(date_to)
        except ValueError:
            end = today
    else:
        end = today
    if date_from:
        try:
            start = date.fromisoformat(date_from)
        except ValueError:
            start = end - timedelta(days=6)
    else:
        start = end - timedelta(days=6)
    return start, end


def local_date_expr(date_col: str, timezone: str = SHANGHAI_TZ) -> str:
    return f"({date_col} AT TIME ZONE '{timezone}')::date"


def date_range_filter_expr(
    date_col: str,
    start_param: str,
    end_param: str,
    timezone: str = SHANGHAI_TZ,
) -> str:
    local_expr = local_date_expr(date_col, timezone)
    return f"{local_expr} >= :{start_param} AND {local_expr} <= :{end_param}"


def date_bucket_expr(date_col: str, interval: str, timezone: Optional[str] = None) -> str:
    """Return the SQL expression bucketing ``date_col`` by interval.

    ``date_col`` is interpolated directly (it must be a fully-qualified
    column name like ``bm.executed_at`` — never user input). The output is
    safe to drop into ``SELECT`` / ``GROUP BY`` clauses.
    """
    bucket_source = f"{date_col} AT TIME ZONE '{timezone}'" if timezone else date_col
    if interval == "weekly":
        return f"date_trunc('week', {bucket_source})::date"
    if interval == "monthly":
        return f"date_trunc('month', {bucket_source})::date"
    if timezone:
        return local_date_expr(date_col, timezone)
    return f"{date_col}::date"


def iter_date_strings(start: date, end: date) -> list[str]:
    values: list[str] = []
    current = start
    while current <= end:
        values.append(current.isoformat())
        current += timedelta(days=1)
    return values


# ---------------------------------------------------------------------------
# Query-string parsing
# ---------------------------------------------------------------------------


def parse_multi_value(param: Optional[str]) -> List[str]:
    """Parse a comma-separated query parameter into a list of trimmed values."""
    if not param:
        return []
    return [v.strip() for v in param.split(",") if v.strip()]


# ---------------------------------------------------------------------------
# Common WHERE-fragment builder
# ---------------------------------------------------------------------------


def apply_common_filters(
    where_parts: List[str],
    params: dict,
    *,
    cp_alias: str = "cp",
    mention_alias: Optional[str] = None,
    topic_id: Optional[Any] = None,
    topic_ids: Optional[str] = None,
    platform: Optional[str] = None,
    country: Optional[str] = None,
    product: Optional[str] = None,
    prompt_id: Optional[Any] = None,
) -> None:
    """Append common-filter SQL fragments + their bound params.

    Mutates ``where_parts`` and ``params`` in place. Each appended snippet is
    parameter-safe (no string interpolation of user values). The caller chooses
    aliases for the joined ``geo_client_prompts`` table (default ``cp``) and
    the mention/citation table (must be supplied if ``prompt_id`` filtering is
    requested) so the snippets compose with whatever JOIN shape the route uses.

    Param names are scoped with ``apply_`` / ``apply_top_`` / ``apply_plat_``
    prefixes to avoid collisions with caller-supplied params (``client_id``,
    ``start_date``, etc.).
    """
    # Dashboard metrics describe the currently enabled monitoring universe.
    # Historical rows for disabled prompts remain in fact tables for audit,
    # but must not contribute to current dynamic dashboards or date reports.
    where_parts.append(f"{cp_alias}.is_active = TRUE")
    if prompt_id is not None and mention_alias is not None:
        where_parts.append(f"{mention_alias}.client_prompt_id = :apply_prompt_id")
        params["apply_prompt_id"] = prompt_id
    if topic_id:
        where_parts.append(f"{cp_alias}.topic_id = :apply_topic_id")
        params["apply_topic_id"] = topic_id
    if topic_ids:
        tid_list = parse_multi_value(topic_ids)
        if tid_list:
            placeholders = ", ".join(
                f":apply_top_{i}" for i in range(len(tid_list))
            )
            where_parts.append(f"{cp_alias}.topic_id IN ({placeholders})")
            for i, tid in enumerate(tid_list):
                params[f"apply_top_{i}"] = tid
    if platform:
        plat_list = parse_multi_value(platform)
        if len(plat_list) == 1:
            where_parts.append(f"{cp_alias}.platform = :apply_platform")
            params["apply_platform"] = plat_list[0]
        elif plat_list:
            placeholders = ", ".join(
                f":apply_plat_{i}" for i in range(len(plat_list))
            )
            where_parts.append(f"{cp_alias}.platform IN ({placeholders})")
            for i, p in enumerate(plat_list):
                params[f"apply_plat_{i}"] = p
    if country:
        country_list = parse_multi_value(country)
        if country_list:
            placeholders = ", ".join(
                f":apply_country_{i}" for i in range(len(country_list))
            )
            where_parts.append(f"{cp_alias}.country IN ({placeholders})")
            for i, c in enumerate(country_list):
                params[f"apply_country_{i}"] = c
    if product:
        where_parts.append(f"{cp_alias}.product = :apply_product")
        params["apply_product"] = product


# ---------------------------------------------------------------------------
# SOV ranking (data-shape transform — no DB)
# ---------------------------------------------------------------------------


def normalize_prompt_identity_value(value: Any) -> str:
    """Normalize like the SQL identity: trim, collapse whitespace, lowercase."""
    return " ".join(str(value or "").strip().split()).lower()


def logical_prompt_identity(row: Any) -> tuple[str, str, str, str, str]:
    data = dict(row)
    return (
        str(data.get("topic_id") or ""),
        normalize_prompt_identity_value(data.get("prompt_text", data.get("text"))),
        normalize_prompt_identity_value(data.get("product")),
        normalize_prompt_identity_value(data.get("intent")),
        normalize_prompt_identity_value(data.get("language")),
    )


def normalized_prompt_sql(column_sql: str) -> str:
    return f"LOWER(REGEXP_REPLACE(BTRIM(COALESCE({column_sql}, '')), '\\s+', ' ', 'g'))"


def logical_prompt_key_sql(alias: str = "cp") -> str:
    """Single server-owned SQL expression for the logical Prompt concept key."""
    return (
        "CONCAT_WS(CHR(31), "
        f"COALESCE({alias}.topic_id::text, ''), "
        f"{normalized_prompt_sql(f'{alias}.text')}, "
        f"{normalized_prompt_sql(f'{alias}.product')}, "
        f"{normalized_prompt_sql(f'{alias}.intent')}, "
        f"{normalized_prompt_sql(f'{alias}.language')})"
    )


def build_sov_ranking(g_rows, group_key_fn, group_name_fn):
    """Build a generic SOV ranking with per-prompt drill-down.

    Used by both topic-based and product-based SOV rankings in visibility.

    Args:
        g_rows: granular query rows (topic_id, prompt_id, company_name, ...) —
                each row must support ``r["key"]`` access (asyncpg.Record or dict).
        group_key_fn: ``callable(row) -> group key`` (e.g. topic_id or product)
        group_name_fn: ``callable(row) -> group display name``

    Returns:
        list of ranking dicts with ``brands`` and ``prompts`` sub-lists.
    """
    # 1) Group-level aggregation
    group_agg: dict = {}
    for r in g_rows:
        key = group_key_fn(r)
        cname = r["company_name"]
        if key not in group_agg:
            group_agg[key] = {"name": group_name_fn(r), "companies": {}}
        if cname not in group_agg[key]["companies"]:
            group_agg[key]["companies"][cname] = {"mention_count": 0, "is_own": 0}
        group_agg[key]["companies"][cname]["mention_count"] += r["mention_count"]
        group_agg[key]["companies"][cname]["is_own"] = max(
            group_agg[key]["companies"][cname]["is_own"], int(r["is_own"])
        )

    ranking = []
    for key, info in group_agg.items():
        sorted_brands = sorted(
            info["companies"].items(),
            key=lambda x: (-int(x[1]["mention_count"]), str(x[0]).casefold(), str(x[0])),
        )
        ranking.append(
            {
                "group_key": key,
                "group_name": info["name"],
                "total_mentions": sum(int(item["mention_count"]) for item in info["companies"].values()),
                "prompt_count": 0,
                "brands": [
                    {
                        "rank": i + 1,
                        "company_name": name,
                        "mention_count": d["mention_count"],
                        "is_own": d["is_own"] == 1,
                    }
                    for i, (name, d) in enumerate(sorted_brands)
                ],
                "prompts": [],
            }
        )

    # 2) Prompt-level within each group
    prompt_agg: dict = {}
    for r in g_rows:
        key = group_key_fn(r)
        row_dict = dict(r)
        prompt_text = " ".join(str(r["prompt_text"] or "").strip().split())
        # Matrix drill-down is a SaaS-facing logical Prompt view. Platform and
        # country fanout rows collapse, while topic, normalized text, product,
        # intent, and language remain identity-defining dimensions.
        pkey = (str(key), logical_prompt_identity(row_dict))
        if pkey not in prompt_agg:
            # asyncpg.Record supports .get via dict() conversion; check membership
            # safely so missing 'product' columns don't blow up.
            prompt_agg[pkey] = {
                "group_key": key,
                "prompt_id": str(row_dict.get("prompt_id") or ""),
                "prompt_text": prompt_text,
                "product": (row_dict.get("product") or ""),
                "companies": {},
            }
        else:
            candidate_id = str(row_dict.get("prompt_id") or "")
            if candidate_id and (
                not prompt_agg[pkey]["prompt_id"] or candidate_id < prompt_agg[pkey]["prompt_id"]
            ):
                prompt_agg[pkey]["prompt_id"] = candidate_id
                prompt_agg[pkey]["prompt_text"] = prompt_text
        cname = r["company_name"]
        if cname not in prompt_agg[pkey]["companies"]:
            prompt_agg[pkey]["companies"][cname] = {"mention_count": 0, "is_own": 0}
        prompt_agg[pkey]["companies"][cname]["mention_count"] += r["mention_count"]
        prompt_agg[pkey]["companies"][cname]["is_own"] = max(
            prompt_agg[pkey]["companies"][cname]["is_own"], int(r["is_own"])
        )

    # Attach prompts to their groups
    group_key_map = {r["group_key"]: r for r in ranking}
    for pkey, pinfo in prompt_agg.items():
        sorted_brands = sorted(
            pinfo["companies"].items(),
            key=lambda x: (-int(x[1]["mention_count"]), str(x[0]).casefold(), str(x[0])),
        )
        prompt_entry = {
            "prompt_id": pinfo["prompt_id"],
            "prompt_text": pinfo["prompt_text"],
            "total_mentions": sum(int(item["mention_count"]) for item in pinfo["companies"].values()),
            "brands": [
                {
                    "rank": i + 1,
                    "company_name": name,
                    "mention_count": d["mention_count"],
                    "is_own": d["is_own"] == 1,
                }
                for i, (name, d) in enumerate(sorted_brands)
            ],
        }
        group_obj = group_key_map.get(pinfo["group_key"])
        if group_obj:
            group_obj["prompts"].append(prompt_entry)
            group_obj["prompt_count"] += 1

    return ranking


# Backwards-compat alias for the old name (some routers still call it).
def build_date_bucket(date_col_or_str, interval: str) -> str:
    """Compatibility wrapper. Accepts a string column name (preferred) or any
    object whose ``str()`` is the column name; returns the SQL bucket
    expression."""
    return date_bucket_expr(str(date_col_or_str), interval)
