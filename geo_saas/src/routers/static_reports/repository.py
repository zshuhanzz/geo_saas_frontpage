from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from array import array
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from typing import Any, Hashable

from database import GEO_STATIC_REPORTS
from geo_common.services import acquire_workspace_lifecycle_shared

from .models import (
    DYNAMIC_REPORT_VERSION,
    MAX_STATIC_REPORT_BLOB_BYTES,
    MAX_STATIC_REPORT_BLOB_ROWS,
    MAX_STATIC_REPORT_LOGICAL_LIST_ROWS,
    MAX_STATIC_REPORT_SNAPSHOT_BYTES,
    MAX_STATIC_REPORT_TOTAL_BYTES,
    MAX_STATIC_REPORT_TOTAL_ROWS,
    SNAPSHOT_VERSION,
    RenderingMode,
    ReportDates,
    StaticReportPayloadTooLarge,
    StaticReportStatus,
)
from .sorting import (
    STATIC_REPORT_LIST_SPECS,
    StaticReportListUnavailable,
    sort_static_report_rows,
    static_report_row_sort_key,
    validate_static_report_list_sort,
)

logger = logging.getLogger(__name__)

META_COLUMNS = """
    id::text, client_id::text, report_date, timezone, status,
    snapshot_version, data_window_start, data_window_end,
    window_days, rendering_mode, data_completeness, warnings, error_message,
    materialized_at, created_at, updated_at
"""

FULL_COLUMNS = """
    id::text, client_id::text, report_date, timezone, status,
    snapshot_version, snapshot_json, data_window_start, data_window_end,
    window_days, rendering_mode, data_completeness, warnings, error_message,
    materialized_at, created_at, updated_at
"""

MATERIALIZATION_LEASE_DEFAULT_SECONDS = 3600
MATERIALIZATION_LEASE_MIN_SECONDS = 900
MATERIALIZATION_LEASE_MAX_SECONDS = 86400
STATIC_REPORT_LIST_READ_CONCURRENCY = 2
_STATIC_REPORT_LIST_READ_SEMAPHORE = asyncio.Semaphore(STATIC_REPORT_LIST_READ_CONCURRENCY)
STATIC_REPORT_LIST_CACHE_DEFAULT_ENTRIES = 16
STATIC_REPORT_LIST_CACHE_DEFAULT_BYTES = 128 * 1024 * 1024
STATIC_REPORT_LIST_PACK_THRESHOLD_BYTES = 16 * 1024 * 1024
STATIC_REPORT_SORT_INDEX_MARKER = "@sort."


def parse_static_report_cache_limit(
    raw_value: str | None,
    *,
    default: int,
    ceiling: int,
) -> int:
    try:
        parsed = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return min(ceiling, max(0, parsed))


STATIC_REPORT_LIST_CACHE_MAX_ENTRIES = parse_static_report_cache_limit(
    os.getenv("STATIC_REPORT_LIST_CACHE_ENTRIES"),
    default=STATIC_REPORT_LIST_CACHE_DEFAULT_ENTRIES,
    ceiling=128,
)
STATIC_REPORT_LIST_CACHE_MAX_BYTES = parse_static_report_cache_limit(
    os.getenv("STATIC_REPORT_LIST_CACHE_BYTES"),
    default=STATIC_REPORT_LIST_CACHE_DEFAULT_BYTES,
    ceiling=256 * 1024 * 1024,
)
# Retain these repository-level names for compatibility with operational tests
# and callers that tune the persisted-row guard in isolation.
MAX_STATIC_REPORT_LIST_ROWS = MAX_STATIC_REPORT_BLOB_ROWS
MAX_STATIC_REPORT_LIST_BYTES = MAX_STATIC_REPORT_BLOB_BYTES
STATIC_REPORT_SHARD_SEPARATOR = "::"
STATIC_REPORT_SHARD_WIDTH = 6


@dataclass(frozen=True)
class _FrozenListCacheEntry:
    rows: Any
    weight_bytes: int


@dataclass(frozen=True)
class _PackedFrozenRows:
    """Compact immutable rows plus precomputed global metric order indexes."""

    payloads: tuple[bytes, ...]
    orders: dict[tuple[str, str], array]
    weight_bytes: int

    def decode(self, index: int) -> dict[str, Any]:
        return json.loads(self.payloads[index])


class _FrozenListCache:
    """Small process-local LRU for validated immutable report list payloads."""

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        self._max_entries = max(0, max_entries)
        self._max_bytes = max(0, max_bytes)
        self._entries: OrderedDict[Hashable, _FrozenListCacheEntry] = OrderedDict()
        self._current_bytes = 0
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry.rows

    def put(
        self,
        key: Hashable,
        rows: Any,
        *,
        weight_bytes: int,
    ) -> bool:
        if (
            self._max_entries == 0
            or self._max_bytes == 0
            or weight_bytes < 0
            or weight_bytes > self._max_bytes
        ):
            return False
        entry = _FrozenListCacheEntry(rows=rows, weight_bytes=weight_bytes)
        with self._lock:
            replaced = self._entries.pop(key, None)
            if replaced is not None:
                self._current_bytes -= replaced.weight_bytes
            self._entries[key] = entry
            self._current_bytes += weight_bytes
            while (
                len(self._entries) > self._max_entries
                or self._current_bytes > self._max_bytes
            ):
                _, evicted = self._entries.popitem(last=False)
                self._current_bytes -= evicted.weight_bytes
        return True

    def clear_report(self, pool: Any, report_id: str) -> None:
        with self._lock:
            stale_keys = [
                key
                for key in self._entries
                if isinstance(key, tuple)
                and len(key) == 4
                and key[0] is pool
                and key[1] == report_id
            ]
            for key in stale_keys:
                self._current_bytes -= self._entries.pop(key).weight_bytes


def _estimate_frozen_rows_memory(rows: tuple[Any, ...]) -> int:
    """Estimate retained Python heap size for one decoded JSON-compatible tree."""
    total = 0
    seen: set[int] = set()
    stack = [rows]
    while stack:
        value = stack.pop()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        total += sys.getsizeof(value)
        if isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend(value)
    return total


def _pack_frozen_rows(
    list_type: str,
    rows: tuple[dict[str, Any], ...],
) -> _PackedFrozenRows:
    """Pack a large list without retaining its expanded Python object tree."""
    payloads = tuple(
        json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        for row in rows
    )
    spec = STATIC_REPORT_LIST_SPECS[list_type]
    orders: dict[tuple[str, str], array] = {}
    for metric in spec.allowed_metrics:
        for order in ("asc", "desc"):
            indexes = sorted(
                range(len(rows)),
                key=lambda index: static_report_row_sort_key(
                    list_type,
                    rows[index],
                    sort_by=metric,
                    sort_order=order,
                ),
            )
            orders[(metric, order)] = array("I", indexes)

    weight_bytes = (
        sys.getsizeof(payloads)
        + sum(sys.getsizeof(payload) for payload in payloads)
        + sys.getsizeof(orders)
        + sum(sys.getsizeof(key) + sys.getsizeof(value) for key, value in orders.items())
    )
    return _PackedFrozenRows(
        payloads=payloads,
        orders=orders,
        weight_bytes=weight_bytes,
    )


def _sort_index_base_type(list_type: str, metric: str, order: str) -> str:
    return f"{list_type}{STATIC_REPORT_SORT_INDEX_MARKER}{metric}.{order}"


def _sort_index_shard_type(
    list_type: str,
    metric: str,
    order: str,
    shard_index: int,
) -> str:
    base = _sort_index_base_type(list_type, metric, order)
    if shard_index == 0:
        return base
    return f"{base}{STATIC_REPORT_SHARD_SEPARATOR}{shard_index:0{STATIC_REPORT_SHARD_WIDTH}d}"


def _prepare_persisted_sort_indexes(
    list_rows: list[dict[str, Any]],
) -> tuple[list[tuple[str, str, int, str]], dict[str, _PackedFrozenRows]]:
    """Build compact cross-instance sort indexes for oversized Citation lists."""
    grouped: dict[str, dict[int, list[Any]]] = {
        "citation.page": {},
        "citation.domain": {},
    }
    for item in list_rows:
        parsed = parse_static_report_shard_list_type(item.get("list_type"))
        if parsed is None or parsed[0] not in grouped:
            continue
        grouped[parsed[0]][parsed[1]] = item.get("rows_payload") or []

    prepared: list[tuple[str, str, int, str]] = []
    packed_by_base: dict[str, _PackedFrozenRows] = {}
    for base, shards in grouped.items():
        if sorted(shards) != list(range(len(shards))):
            continue
        rows = tuple(
            row
            for shard_index in range(len(shards))
            for row in shards[shard_index]
        )
        if _estimate_frozen_rows_memory(rows) <= STATIC_REPORT_LIST_PACK_THRESHOLD_BYTES:
            continue
        packed = _pack_frozen_rows(base, rows)
        packed_by_base[base] = packed
        for (metric, order), indexes in packed.orders.items():
            for shard_index, start in enumerate(range(0, len(indexes), MAX_STATIC_REPORT_LIST_ROWS)):
                values = list(indexes[start:start + MAX_STATIC_REPORT_LIST_ROWS])
                payload = json.dumps(values, separators=(",", ":"))
                if len(payload.encode("utf-8")) > MAX_STATIC_REPORT_LIST_BYTES:
                    raise StaticReportPayloadTooLarge("static report sort index shard exceeds byte limit")
                prepared.append((
                    _sort_index_shard_type(base, metric, order, shard_index),
                    SNAPSHOT_VERSION,
                    len(values),
                    payload,
                ))
    return prepared, packed_by_base


_STATIC_REPORT_LIST_CACHE = _FrozenListCache(
    max_entries=STATIC_REPORT_LIST_CACHE_MAX_ENTRIES,
    max_bytes=STATIC_REPORT_LIST_CACHE_MAX_BYTES,
)


def _warm_completed_report_lists(
    pool: Any,
    report_id: str,
    client_id: str,
    list_rows: list[dict[str, Any]],
    *,
    packed_by_base: dict[str, _PackedFrozenRows] | None = None,
) -> None:
    """Seed the immutable-list cache from rows already held by the generator."""
    grouped: dict[str, dict[int, list[Any]]] = {
        base: {} for base in STATIC_REPORT_LIST_SPECS
    }
    for item in list_rows:
        parsed = parse_static_report_shard_list_type(item.get("list_type"))
        if parsed is None:
            continue
        base, shard_index = parsed
        grouped[base][shard_index] = item.get("rows_payload") or []

    candidates: list[tuple[int, str, tuple[Any, ...]]] = []
    for base, shards in grouped.items():
        if sorted(shards) != list(range(len(shards))):
            continue
        rows = tuple(
            item
            for shard_index in range(len(shards))
            for item in shards[shard_index]
        )
        candidates.append((_estimate_frozen_rows_memory(rows), base, rows))

    # Insert small lists first and the largest hot list last so LRU eviction
    # retains the expensive list whenever it fits within the global byte cap.
    for weight_bytes, base, rows in sorted(candidates):
        cache_key = (pool, report_id, client_id, base)
        prepared_packed = (packed_by_base or {}).get(base)
        if prepared_packed is not None:
            retained = _STATIC_REPORT_LIST_CACHE.put(
                cache_key,
                prepared_packed,
                weight_bytes=prepared_packed.weight_bytes,
            )
            logger.info(
                "[STATIC_REPORT] compact_cache_warm report_id=%s list_type=%s rows=%s bytes=%s retained=%s",
                report_id,
                base,
                len(rows),
                prepared_packed.weight_bytes,
                retained,
            )
            continue
        should_pack = (
            base in {"citation.page", "citation.domain"}
            and weight_bytes > STATIC_REPORT_LIST_PACK_THRESHOLD_BYTES
        )
        retained = False
        if not should_pack:
            retained = _STATIC_REPORT_LIST_CACHE.put(
                cache_key,
                rows,
                weight_bytes=weight_bytes,
            )
        if not retained and base in {"citation.page", "citation.domain"}:
            packed = _pack_frozen_rows(base, rows)
            retained = _STATIC_REPORT_LIST_CACHE.put(
                cache_key,
                packed,
                weight_bytes=packed.weight_bytes,
            )
            logger.info(
                "[STATIC_REPORT] compact_cache_warm report_id=%s list_type=%s rows=%s bytes=%s retained=%s",
                report_id,
                base,
                len(rows),
                packed.weight_bytes,
                retained,
            )

AUTHORIZED_REPORT_ACCESS_SQL = """
    AND (
        EXISTS (
            SELECT 1
            FROM geo_client_user_access cua
            WHERE cua.user_id = $2::uuid
              AND cua.client_id = sr.client_id
              AND cua.is_active = true
        )
        OR EXISTS (
            SELECT 1
            FROM geo_admin_user_access aua
            WHERE aua.user_id = $2::uuid
              AND aua.role = 'super_admin'
              AND aua.support_all_clients = true
              AND aua.is_active = true
        )
    )
"""


def parse_materialization_lease_seconds(raw_value: str | None) -> int:
    try:
        parsed = int(raw_value) if raw_value else MATERIALIZATION_LEASE_DEFAULT_SECONDS
    except (TypeError, ValueError):
        parsed = MATERIALIZATION_LEASE_DEFAULT_SECONDS
    return min(
        MATERIALIZATION_LEASE_MAX_SECONDS,
        max(MATERIALIZATION_LEASE_MIN_SECONDS, parsed),
    )


# One hour is deliberately longer than the normal snapshot build envelope.
MATERIALIZATION_LEASE_SECONDS = parse_materialization_lease_seconds(
    os.getenv("STATIC_REPORT_MATERIALIZATION_LEASE_SECONDS"),
)


class MaterializationLeaseLost(RuntimeError):
    pass


def row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key, fallback in (
        ("snapshot_json", None),
        ("client", {}),
        ("report", {}),
        ("filters", {}),
        ("data", {}),
        ("data_completeness", {}),
        ("warnings", []),
        ("frozen_lists", {}),
        ("dimension_payload", {}),
        ("metric_payload", {}),
        ("rows_payload", []),
    ):
        value = data.get(key)
        if isinstance(value, str):
            try:
                data[key] = json.loads(value)
            except json.JSONDecodeError:
                data[key] = fallback
        elif value is None and fallback is not None:
            data[key] = fallback
    return data


def static_report_shard_list_type(base_list_type: str, shard_index: int) -> str:
    """Return the deterministic persisted list_type for one logical-list shard."""
    if base_list_type not in STATIC_REPORT_LIST_SPECS:
        raise ValueError("unsupported static report list base")
    if shard_index < 0:
        raise ValueError("static report shard index must be nonnegative")
    if shard_index == 0:
        return base_list_type
    return f"{base_list_type}{STATIC_REPORT_SHARD_SEPARATOR}{shard_index:0{STATIC_REPORT_SHARD_WIDTH}d}"


def parse_static_report_shard_list_type(list_type: Any) -> tuple[str, int] | None:
    """Parse a base or canonical shard list_type without accepting aliases."""
    if not isinstance(list_type, str):
        return None
    if list_type in STATIC_REPORT_LIST_SPECS:
        return list_type, 0
    base, separator, suffix = list_type.rpartition(STATIC_REPORT_SHARD_SEPARATOR)
    if (
        separator != STATIC_REPORT_SHARD_SEPARATOR
        or base not in STATIC_REPORT_LIST_SPECS
        or len(suffix) != STATIC_REPORT_SHARD_WIDTH
        or not suffix.isascii()
        or not suffix.isdigit()
    ):
        return None
    shard_index = int(suffix)
    if shard_index < 1 or static_report_shard_list_type(base, shard_index) != list_type:
        return None
    return base, shard_index


def prepare_static_report_list_blobs(
    list_rows: list[dict[str, Any]],
) -> list[tuple[str, str, int, str]]:
    grouped: dict[str, dict[int, dict[str, Any]]] = {
        base: {} for base in STATIC_REPORT_LIST_SPECS
    }
    valid_blobs = True
    for item in list_rows:
        parsed = parse_static_report_shard_list_type(item.get("list_type"))
        rows_payload = item.get("rows_payload")
        row_count = item.get("row_count")
        if (
            parsed is None
            or item.get("list_version") != SNAPSHOT_VERSION
            or not isinstance(rows_payload, list)
            or not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count != len(rows_payload)
            or row_count < 0
            or row_count > MAX_STATIC_REPORT_LIST_ROWS
        ):
            valid_blobs = False
            break
        base, shard_index = parsed
        if shard_index in grouped[base] or (shard_index > 0 and row_count == 0):
            valid_blobs = False
            break
        grouped[base][shard_index] = item

    if valid_blobs:
        for shards in grouped.values():
            if not shards or sorted(shards) != list(range(len(shards))):
                valid_blobs = False
                break

    total_rows = sum(
        int(item["row_count"])
        for shards in grouped.values()
        for item in shards.values()
    )
    if not valid_blobs or total_rows > MAX_STATIC_REPORT_TOTAL_ROWS:
        raise ValueError("static report list blobs do not match the registered contract")

    prepared: list[tuple[str, str, int, str]] = []
    total_bytes = 0
    for base in STATIC_REPORT_LIST_SPECS:
        for shard_index in range(len(grouped[base])):
            item = grouped[base][shard_index]
            payload = json.dumps(item["rows_payload"], ensure_ascii=False, default=str)
            payload_bytes = len(payload.encode("utf-8"))
            if payload_bytes > MAX_STATIC_REPORT_LIST_BYTES:
                raise StaticReportPayloadTooLarge(
                    f"static report list shard exceeds byte limit: {item['list_type']}",
                )
            total_bytes += payload_bytes
            if total_bytes > MAX_STATIC_REPORT_TOTAL_BYTES:
                raise StaticReportPayloadTooLarge("static report exceeds total byte limit")
            prepared.append((item["list_type"], item["list_version"], item["row_count"], payload))
    return prepared


class StaticReportRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    @staticmethod
    async def _client_id_for_report(conn, report_id: str) -> str:
        client_id = await conn.fetchval(
            f"SELECT client_id::text FROM {GEO_STATIC_REPORTS} WHERE id = $1::uuid",
            report_id,
        )
        if not client_id:
            raise MaterializationLeaseLost("static report no longer exists")
        return str(client_id)

    @staticmethod
    async def _lock_materialization_owner(conn, report_id: str, materialization_token: Any) -> None:
        if materialization_token is None:
            raise MaterializationLeaseLost("materialization fencing token is missing")
        owner = await conn.fetchrow(
            f"""
            SELECT id::text, status, updated_at
            FROM {GEO_STATIC_REPORTS}
            WHERE id = $1::uuid
              AND status = $2
              AND updated_at IS NOT DISTINCT FROM $3::timestamptz
            FOR UPDATE
            """,
            report_id,
            StaticReportStatus.MATERIALIZING.value,
            materialization_token,
        )
        if not owner:
            raise MaterializationLeaseLost("materialization lease is no longer owned by this worker")

    async def list_for_client(self, client_id: str, limit: int = 50) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {META_COLUMNS}
                FROM {GEO_STATIC_REPORTS}
                WHERE client_id = $1::uuid
                ORDER BY report_date DESC
                LIMIT $2
                """,
                client_id,
                limit,
            )
        return [row_to_dict(row) for row in rows if row is not None]

    async def get_by_id(self, report_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {FULL_COLUMNS}
                FROM {GEO_STATIC_REPORTS}
                WHERE id = $1::uuid
                """,
                report_id,
            )
        return row_to_dict(row)

    async def get_authorized_by_id(self, report_id: str, user_id: str) -> dict[str, Any] | None:
        """Load a full report only when the user can access its tenant."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {FULL_COLUMNS}
                FROM {GEO_STATIC_REPORTS} sr
                WHERE sr.id = $1::uuid
                {AUTHORIZED_REPORT_ACCESS_SQL}
                """,
                report_id,
                user_id,
            )
        return row_to_dict(row)

    async def get_for_date(self, client_id: str, report_date: date, window_days: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {META_COLUMNS}
                FROM {GEO_STATIC_REPORTS}
                WHERE client_id = $1::uuid AND report_date = $2 AND window_days = $3
                """,
                client_id,
                report_date,
                window_days,
            )
        return row_to_dict(row)

    async def get_summary_by_id(self, report_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {META_COLUMNS},
                       snapshot_json -> 'client' AS client,
                       snapshot_json -> 'report' AS report,
                       COALESCE(snapshot_json -> 'filters', '{{}}'::jsonb) AS filters,
                       COALESCE(snapshot_json -> 'frozen_lists', '{{}}'::jsonb) AS frozen_lists
                FROM {GEO_STATIC_REPORTS}
                WHERE id = $1::uuid
                """,
                report_id,
            )
        return row_to_dict(row)

    async def get_authorized_summary_by_id(self, report_id: str, user_id: str) -> dict[str, Any] | None:
        """Load report metadata only when access is proven in the same SQL query."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {META_COLUMNS},
                       snapshot_json -> 'client' AS client,
                       snapshot_json -> 'report' AS report,
                       COALESCE(snapshot_json -> 'filters', '{{}}'::jsonb) AS filters,
                       COALESCE(snapshot_json -> 'frozen_lists', '{{}}'::jsonb) AS frozen_lists
                FROM {GEO_STATIC_REPORTS} sr
                WHERE sr.id = $1::uuid
                {AUTHORIZED_REPORT_ACCESS_SQL}
                """,
                report_id,
                user_id,
            )
        return row_to_dict(row)

    @staticmethod
    def _snapshot_part_expression(part: str) -> str:
        if part not in {"filters", "visibility", "citations", "sentiment"}:
            raise ValueError(f"Unsupported static report snapshot part: {part}")
        data_expr = f"snapshot_json -> '{part}'"
        if part == "visibility":
            data_expr = """
                jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            jsonb_set(
                                snapshot_json -> 'visibility',
                                '{dashboard,source_rows}',
                                '[]'::jsonb,
                                true
                            ),
                            '{dashboard,response_source_rows}',
                            '[]'::jsonb,
                            true
                        ),
                        '{dashboard,source_rows_limited}',
                        'true'::jsonb,
                        true
                    ),
                    '{dashboard,response_source_rows_limited}',
                    'true'::jsonb,
                    true
                )
            """
        elif part == "citations":
            data_expr = """
                jsonb_set(
                    jsonb_set(
                        snapshot_json -> 'citations',
                        '{dashboard,source_rows}',
                        '[]'::jsonb,
                        true
                    ),
                    '{dashboard,source_rows_limited}',
                    'true'::jsonb,
                    true
                )
            """
        return data_expr

    async def get_snapshot_part_by_id(self, report_id: str, part: str) -> dict[str, Any] | None:
        data_expr = self._snapshot_part_expression(part)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id::text, client_id::text, status, {data_expr} AS data
                FROM {GEO_STATIC_REPORTS}
                WHERE id = $1::uuid
                """,
                report_id,
            )
        return row_to_dict(row)

    async def get_authorized_snapshot_part_by_id(
        self,
        report_id: str,
        part: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        data_expr = self._snapshot_part_expression(part)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id::text, client_id::text, status, {data_expr} AS data
                FROM {GEO_STATIC_REPORTS} sr
                WHERE sr.id = $1::uuid
                {AUTHORIZED_REPORT_ACCESS_SQL}
                """,
                report_id,
                user_id,
            )
        return row_to_dict(row)

    @staticmethod
    def _snapshot_view_expression(view: str) -> str:
        view_exprs = {
            "visibility_score": """
                jsonb_build_object(
                    'dashboard', jsonb_build_object(
                        'summary', COALESCE(snapshot_json #> '{visibility,dashboard,summary}', '{}'::jsonb),
                        'time_series', COALESCE(snapshot_json #> '{visibility,dashboard,time_series}', '[]'::jsonb),
                        'prev_time_series', COALESCE(snapshot_json #> '{visibility,dashboard,prev_time_series}', '[]'::jsonb),
                        'filters', COALESCE(snapshot_json #> '{visibility,dashboard,filters}', '{}'::jsonb),
                        'source_rows_limited', 'true'::jsonb,
                        'response_source_rows_limited', 'true'::jsonb
                    )
                )
            """,
            "visibility_brand_ranking": """
                jsonb_build_object(
                    'dashboard', jsonb_build_object(
                        'summary', COALESCE(snapshot_json #> '{visibility,dashboard,summary}', '{}'::jsonb),
                        'visibility_ranking', COALESCE(snapshot_json #> '{visibility,dashboard,visibility_ranking}', '[]'::jsonb),
                        'filters', COALESCE(snapshot_json #> '{visibility,dashboard,filters}', '{}'::jsonb)
                    )
                )
            """,
            "visibility_sov": """
                jsonb_build_object(
                    'dashboard', jsonb_build_object(
                        'summary', COALESCE(snapshot_json #> '{visibility,dashboard,summary}', '{}'::jsonb),
                        'sov_ranking', COALESCE(snapshot_json #> '{visibility,dashboard,sov_ranking}', '[]'::jsonb),
                        'competitive_series', COALESCE(snapshot_json #> '{visibility,dashboard,competitive_series}', '{}'::jsonb),
                        'topic_sov_ranking', COALESCE(snapshot_json #> '{visibility,dashboard,topic_sov_ranking}', '[]'::jsonb),
                        'product_sov_ranking', COALESCE(snapshot_json #> '{visibility,dashboard,product_sov_ranking}', '[]'::jsonb),
                        'filters', COALESCE(snapshot_json #> '{visibility,dashboard,filters}', '{}'::jsonb)
                    )
                )
            """,
            "visibility_position": """
                jsonb_build_object(
                    'dashboard', jsonb_build_object(
                        'summary', COALESCE(snapshot_json #> '{visibility,dashboard,summary}', '{}'::jsonb),
                        'avg_position_series', COALESCE(snapshot_json #> '{visibility,dashboard,avg_position_series}', '[]'::jsonb),
                        'prev_avg_position_series', COALESCE(snapshot_json #> '{visibility,dashboard,prev_avg_position_series}', '[]'::jsonb),
                        'position_ranking', COALESCE(snapshot_json #> '{visibility,dashboard,position_ranking}', '[]'::jsonb),
                        'filters', COALESCE(snapshot_json #> '{visibility,dashboard,filters}', '{}'::jsonb)
                    )
                )
            """,
            "citations_share": """
                jsonb_build_object(
                    'dashboard', jsonb_build_object(
                        'summary', COALESCE(snapshot_json #> '{citations,dashboard,summary}', '{}'::jsonb),
                        'time_series', COALESCE(snapshot_json #> '{citations,dashboard,time_series}', '[]'::jsonb),
                        'prev_time_series', COALESCE(snapshot_json #> '{citations,dashboard,prev_time_series}', '[]'::jsonb),
                        'source_rows_limited', 'true'::jsonb
                    )
                )
            """,
            "citations_ranking": """
                jsonb_build_object(
                    'dashboard', jsonb_build_object(
                        'summary', COALESCE(snapshot_json #> '{citations,dashboard,summary}', '{}'::jsonb),
                        'domain_ranking', COALESCE(snapshot_json #> '{citations,dashboard,domain_ranking}', '[]'::jsonb),
                        'page_ranking', COALESCE(snapshot_json #> '{citations,dashboard,page_ranking}', '[]'::jsonb),
                        'source_rows_limited', 'true'::jsonb
                    )
                )
            """,
            "citations_categories": """
                jsonb_build_object(
                    'dashboard', jsonb_build_object(
                        'summary', COALESCE(snapshot_json #> '{citations,dashboard,summary}', '{}'::jsonb),
                        'category_breakdown', COALESCE(snapshot_json #> '{citations,dashboard,category_breakdown}', '[]'::jsonb),
                        'source_rows_limited', 'true'::jsonb
                    )
                )
            """,
            "prompt_topic": """
                jsonb_build_object(
                    'prompts', COALESCE(snapshot_json -> 'prompts', '{}'::jsonb),
                    'topics', COALESCE(snapshot_json -> 'topics', '{}'::jsonb)
                )
            """,
        }
        data_expr = view_exprs.get(view)
        if not data_expr:
            raise ValueError(f"Unsupported static report snapshot view: {view}")
        return data_expr

    async def get_snapshot_view_by_id(self, report_id: str, view: str) -> dict[str, Any] | None:
        data_expr = self._snapshot_view_expression(view)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id::text, client_id::text, status, {data_expr} AS data
                FROM {GEO_STATIC_REPORTS}
                WHERE id = $1::uuid
                """,
                report_id,
            )
        return row_to_dict(row)

    async def get_authorized_snapshot_view_by_id(
        self,
        report_id: str,
        view: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        data_expr = self._snapshot_view_expression(view)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id::text, client_id::text, status, {data_expr} AS data
                FROM {GEO_STATIC_REPORTS} sr
                WHERE sr.id = $1::uuid
                {AUTHORIZED_REPORT_ACCESS_SQL}
                """,
                report_id,
                user_id,
            )
        return row_to_dict(row)

    async def claim_materialization(
        self,
        client_id: str,
        dates: ReportDates,
        user_id: str,
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await acquire_workspace_lifecycle_shared(conn, client_id)
                inserted = await conn.fetchrow(
                    f"""
                    INSERT INTO {GEO_STATIC_REPORTS} (
                        client_id, report_date, timezone, status, snapshot_version,
                        data_window_start, data_window_end, window_days, rendering_mode,
                        materialized_by_user_id
                    )
                    VALUES (
                        $1::uuid, $2, $3, $4, $5,
                        $6, $7, $8, $9, $10::uuid
                    )
                    ON CONFLICT (client_id, report_date, window_days) DO NOTHING
                    RETURNING {META_COLUMNS}
                    """,
                    client_id,
                    dates.report_date,
                    dates.timezone,
                    StaticReportStatus.MATERIALIZING.value,
                    DYNAMIC_REPORT_VERSION,
                    dates.window_start,
                    dates.window_end,
                    dates.window_days,
                    RenderingMode.SINGLE_DAY.value,
                    user_id,
                )
                if inserted:
                    report = row_to_dict(inserted)
                    return {
                        "report": report,
                        "acquired_materialization": True,
                        "materialization_token": report["updated_at"],
                    }

                current = await conn.fetchrow(
                    f"""
                    SELECT {META_COLUMNS}
                    FROM {GEO_STATIC_REPORTS}
                    WHERE client_id = $1::uuid AND report_date = $2 AND window_days = $3
                    """,
                    client_id,
                    dates.report_date,
                    dates.window_days,
                )
                current_data = row_to_dict(current)
                if not current_data:
                    raise RuntimeError("static report claim conflict row disappeared")
                if current_data["status"] == StaticReportStatus.COMPLETED.value:
                    return {
                        "report": current_data,
                        "acquired_materialization": False,
                        "materialization_token": None,
                    }

                if current_data["status"] == StaticReportStatus.MATERIALIZING.value:
                    recovered = await conn.fetchrow(
                        f"""
                        UPDATE {GEO_STATIC_REPORTS}
                        SET error_message = NULL,
                            materialized_by_user_id = $4::uuid,
                            snapshot_version = $5,
                            updated_at = clock_timestamp()
                        WHERE id = $1::uuid
                          AND status = $2
                          AND updated_at IS NOT DISTINCT FROM $3::timestamptz
                          AND updated_at < NOW() - ($6 * INTERVAL '1 second')
                        RETURNING {META_COLUMNS}
                        """,
                        current_data["id"],
                        StaticReportStatus.MATERIALIZING.value,
                        current_data.get("updated_at"),
                        user_id,
                        DYNAMIC_REPORT_VERSION,
                        MATERIALIZATION_LEASE_SECONDS,
                    )
                    if recovered:
                        report = row_to_dict(recovered)
                        return {
                            "report": report,
                            "acquired_materialization": True,
                            "materialization_token": report["updated_at"],
                        }
                    winner = await conn.fetchrow(
                        f"SELECT {META_COLUMNS} FROM {GEO_STATIC_REPORTS} WHERE id = $1::uuid",
                        current_data["id"],
                    )
                    winner_data = row_to_dict(winner)
                    if not winner_data:
                        raise RuntimeError("static report lease row disappeared")
                    return {
                        "report": winner_data,
                        "acquired_materialization": False,
                        "materialization_token": None,
                    }

                claimed = await conn.fetchrow(
                    f"""
                    UPDATE {GEO_STATIC_REPORTS}
                    SET status = $4,
                        error_message = NULL,
                        materialized_by_user_id = $5::uuid,
                        snapshot_version = $6,
                        updated_at = clock_timestamp()
                    WHERE id = $1::uuid
                      AND status = $2
                      AND updated_at IS NOT DISTINCT FROM $3::timestamptz
                    RETURNING {META_COLUMNS}
                    """,
                    current_data["id"],
                    current_data["status"],
                    current_data.get("updated_at"),
                    StaticReportStatus.MATERIALIZING.value,
                    user_id,
                    DYNAMIC_REPORT_VERSION,
                )
                if claimed:
                    report = row_to_dict(claimed)
                    return {
                        "report": report,
                        "acquired_materialization": True,
                        "materialization_token": report["updated_at"],
                    }

                winner = await conn.fetchrow(
                    f"SELECT {META_COLUMNS} FROM {GEO_STATIC_REPORTS} WHERE id = $1::uuid",
                    current_data["id"],
                )
                winner_data = row_to_dict(winner)
                if not winner_data:
                    raise RuntimeError("static report claim winner row disappeared")
                return {
                    "report": winner_data,
                    "acquired_materialization": False,
                    "materialization_token": None,
                }

    async def mark_not_ready(
        self,
        report_id: str,
        materialization_token: Any,
        reasons: list[str],
        data_completeness: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                client_id = await self._client_id_for_report(conn, report_id)
                await acquire_workspace_lifecycle_shared(conn, client_id)
                await self._lock_materialization_owner(conn, report_id, materialization_token)
                row = await conn.fetchrow(
                    f"""
                    UPDATE {GEO_STATIC_REPORTS}
                    SET status = $4,
                        warnings = $5::jsonb,
                        data_completeness = $6::jsonb,
                        updated_at = clock_timestamp()
                    WHERE id = $1::uuid
                      AND status = $2
                      AND updated_at IS NOT DISTINCT FROM $3::timestamptz
                    RETURNING {META_COLUMNS}
                    """,
                    report_id,
                    StaticReportStatus.MATERIALIZING.value,
                    materialization_token,
                    StaticReportStatus.NOT_READY.value,
                    json.dumps(reasons, ensure_ascii=False),
                    json.dumps(data_completeness, ensure_ascii=False),
                )
                if not row:
                    raise MaterializationLeaseLost("materialization lease changed before not-ready finalization")
        return row_to_dict(row)

    async def complete(
        self,
        report_id: str,
        materialization_token: Any,
        snapshot: dict[str, Any],
        rendering_mode: RenderingMode,
        data_completeness: dict[str, Any],
        warnings: list[str],
        list_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        frozen_lists = prepare_static_report_list_blobs(list_rows)
        sort_indexes, packed_by_base = _prepare_persisted_sort_indexes(list_rows)
        frozen_lists.extend(sort_indexes)
        total_frozen_bytes = sum(len(item[3].encode("utf-8")) for item in frozen_lists)
        if total_frozen_bytes > MAX_STATIC_REPORT_TOTAL_BYTES:
            raise StaticReportPayloadTooLarge("static report and sort indexes exceed total byte limit")
        snapshot_payload = json.dumps(snapshot, ensure_ascii=False, default=str)
        if len(snapshot_payload.encode("utf-8")) > MAX_STATIC_REPORT_SNAPSHOT_BYTES:
            raise StaticReportPayloadTooLarge("static report snapshot exceeds byte limit")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                client_id = await self._client_id_for_report(conn, report_id)
                await acquire_workspace_lifecycle_shared(conn, client_id)
                await self._lock_materialization_owner(conn, report_id, materialization_token)
                await conn.execute(
                    "DELETE FROM geo_static_report_lists WHERE report_id = $1::uuid",
                    report_id,
                )
                if frozen_lists:
                    await conn.executemany(
                        f"""
                        INSERT INTO geo_static_report_lists (
                            report_id, client_id, list_type, list_version,
                            row_count, rows_payload, materialized_at
                        )
                        SELECT $1::uuid, sr.client_id, $2, $3,
                               $4, $5::jsonb, NOW()
                        FROM {GEO_STATIC_REPORTS} sr
                        WHERE sr.id = $1::uuid
                        """,
                        [(report_id, *item) for item in frozen_lists],
                    )
                row = await conn.fetchrow(
                    f"""
                    UPDATE {GEO_STATIC_REPORTS}
                    SET status = $4,
                        snapshot_json = $5::jsonb,
                        snapshot_version = $9,
                        rendering_mode = $6,
                        data_completeness = $7::jsonb,
                        warnings = $8::jsonb,
                        materialized_at = NOW(),
                        error_message = NULL,
                        updated_at = clock_timestamp()
                    WHERE id = $1::uuid
                      AND status = $2
                      AND updated_at IS NOT DISTINCT FROM $3::timestamptz
                    RETURNING {META_COLUMNS}
                    """,
                    report_id,
                    StaticReportStatus.MATERIALIZING.value,
                    materialization_token,
                    StaticReportStatus.COMPLETED.value,
                    snapshot_payload,
                    rendering_mode.value,
                    json.dumps(data_completeness, ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    SNAPSHOT_VERSION,
                )
                if not row:
                    raise MaterializationLeaseLost("materialization lease changed before completion")
        completed = row_to_dict(row)
        try:
            _STATIC_REPORT_LIST_CACHE.clear_report(self._pool, report_id)
            if completed is not None:
                _warm_completed_report_lists(
                    self._pool,
                    report_id,
                    str(completed["client_id"]),
                    list_rows,
                    packed_by_base=packed_by_base,
                )
        except Exception:
            # Cache warming is an optimization after the durable transaction;
            # it must never turn a committed report into an apparent failure.
            logger.exception(
                "[STATIC_REPORT] post-commit cache warm failed report_id=%s",
                report_id,
            )
        return completed

    async def complete_dynamic(
        self,
        report_id: str,
        materialization_token: Any,
        dates: ReportDates,
        data_completeness: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        """Fence and complete a lightweight date-range report in one transaction."""
        rendering_mode = (
            RenderingMode.SINGLE_DAY
            if dates.window_days == 1
            else RenderingMode.MULTI_DAY
        )
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                client_id = await self._client_id_for_report(conn, report_id)
                await acquire_workspace_lifecycle_shared(conn, client_id)
                await self._lock_materialization_owner(
                    conn,
                    report_id,
                    materialization_token,
                )
                client_name = await conn.fetchval(
                    "SELECT name FROM geo_clients WHERE id = $1::uuid",
                    client_id,
                )
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
                descriptor = {
                    "version": DYNAMIC_REPORT_VERSION,
                    "client": {
                        "id": client_id,
                        "name": str(client_name or ""),
                    },
                    "report": {
                        "date": dates.report_date,
                        "timezone": dates.timezone,
                        "window_start": dates.window_start,
                        "window_end": dates.window_end,
                        "window_days": dates.window_days,
                        "rendering_mode": rendering_mode.value,
                    },
                    "filters": {
                        "topics": [
                            {"id": str(item["id"]), "name": str(item["name"])}
                            for item in topic_rows
                        ],
                        "platforms": [
                            {"id": str(item["id"]), "name": str(item["name"])}
                            for item in platform_rows
                        ],
                    },
                }
                descriptor_payload = json.dumps(
                    descriptor,
                    ensure_ascii=False,
                    default=str,
                )
                if len(descriptor_payload.encode("utf-8")) > MAX_STATIC_REPORT_SNAPSHOT_BYTES:
                    raise StaticReportPayloadTooLarge(
                        "dynamic report descriptor exceeds byte limit",
                    )
                row = await conn.fetchrow(
                    f"""
                    UPDATE {GEO_STATIC_REPORTS}
                    SET status = $4,
                        snapshot_json = $5::jsonb,
                        snapshot_version = $9,
                        rendering_mode = $6,
                        data_completeness = $7::jsonb,
                        warnings = $8::jsonb,
                        materialized_at = NOW(),
                        error_message = NULL,
                        updated_at = clock_timestamp()
                    WHERE id = $1::uuid
                      AND status = $2
                      AND updated_at IS NOT DISTINCT FROM $3::timestamptz
                    RETURNING {META_COLUMNS}
                    """,
                    report_id,
                    StaticReportStatus.MATERIALIZING.value,
                    materialization_token,
                    StaticReportStatus.COMPLETED.value,
                    descriptor_payload,
                    rendering_mode.value,
                    json.dumps(data_completeness, ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    DYNAMIC_REPORT_VERSION,
                )
                if not row:
                    raise MaterializationLeaseLost(
                        "materialization lease changed before dynamic completion",
                    )
        return row_to_dict(row)

    async def list_frozen_rows(
        self,
        report_id: str,
        client_id: str,
        list_type: str,
        *,
        sort_by: str | None,
        sort_order: str | None,
        limit: int = 20,
        offset: int = 0,
        parent_key: str | None = None,
        prompt_key: str | None = None,
        search: str | None = None,
        sentiment: str | None = None,
    ) -> dict[str, Any]:
        spec, selected_metric, selected_order = validate_static_report_list_sort(
            list_type,
            sort_by,
            sort_order,
            limit,
            offset,
        )
        if spec.parent_dimension_key is not None and parent_key is None:
            raise ValueError("parent_key is required for list_type")
        if parent_key is not None:
            if spec.parent_dimension_key is None:
                raise ValueError("parent_key is unsupported for list_type")
        if spec.prompt_dimension_key is not None and prompt_key is None:
            raise ValueError("prompt_key is required for list_type")
        if prompt_key is not None:
            if spec.prompt_dimension_key is None:
                raise ValueError("prompt_key is unsupported for list_type")
        normalized_search = (search or "").strip()
        if normalized_search and not spec.search_dimension_keys:
            raise ValueError("search is unsupported for list_type")
        exact_values = {"sentiment": sentiment}
        allowed_exact = dict(spec.exact_filters)
        normalized_exact: dict[str, str] = {}
        for request_key, value in exact_values.items():
            if value is None or not value.strip():
                continue
            dimension_key = allowed_exact.get(request_key)
            if dimension_key is None:
                raise ValueError(f"{request_key} is unsupported for list_type")
            normalized_exact[dimension_key] = value.strip()

        async with _STATIC_REPORT_LIST_READ_SEMAPHORE:
            return await self._read_sort_and_page_frozen_rows(
                report_id,
                client_id,
                list_type,
                spec=spec,
                selected_metric=selected_metric,
                selected_order=selected_order,
                limit=limit,
                offset=offset,
                parent_key=parent_key,
                prompt_key=prompt_key,
                normalized_search=normalized_search,
                normalized_exact=normalized_exact,
            )

    async def _read_sort_and_page_frozen_rows(
        self,
        report_id: str,
        client_id: str,
        list_type: str,
        *,
        spec: Any,
        selected_metric: str,
        selected_order: str,
        limit: int,
        offset: int,
        parent_key: str | None,
        prompt_key: str | None,
        normalized_search: str,
        normalized_exact: dict[str, str],
    ) -> dict[str, Any]:
        cache_key = (self._pool, report_id, client_id, list_type)
        rows = _STATIC_REPORT_LIST_CACHE.get(cache_key)
        if rows is None:
            has_filters = bool(
                parent_key is not None
                or prompt_key is not None
                or normalized_search
                or normalized_exact
            )
            if not has_filters and list_type in {"citation.page", "citation.domain"}:
                persisted_page = await self._read_persisted_sort_index_page(
                    report_id,
                    client_id,
                    list_type,
                    selected_metric,
                    selected_order,
                    limit,
                    offset,
                )
                if persisted_page is not None:
                    return persisted_page
            rows = await self._load_validated_frozen_rows(
                report_id,
                client_id,
                list_type,
            )
            weight_bytes = _estimate_frozen_rows_memory(rows)
            should_pack = (
                list_type in {"citation.page", "citation.domain"}
                and weight_bytes > STATIC_REPORT_LIST_PACK_THRESHOLD_BYTES
            )
            retained = False
            if not should_pack:
                retained = _STATIC_REPORT_LIST_CACHE.put(
                    cache_key,
                    rows,
                    weight_bytes=weight_bytes,
                )
            if not retained and list_type in {"citation.page", "citation.domain"}:
                packed = _pack_frozen_rows(list_type, rows)
                if _STATIC_REPORT_LIST_CACHE.put(
                    cache_key,
                    packed,
                    weight_bytes=packed.weight_bytes,
                ):
                    rows = packed

        normalized_needle = normalized_search.casefold()

        def matches(row: dict[str, Any]) -> bool:
            if parent_key is not None and str(row.get(spec.parent_dimension_key) or "") != parent_key:
                return False
            if prompt_key is not None and str(row.get(spec.prompt_dimension_key) or "") != prompt_key:
                return False
            if normalized_needle:
                if not any(normalized_needle in str(row.get(key) or "").casefold() for key in spec.search_dimension_keys):
                    return False
            return all(str(row.get(key) or "") == value for key, value in normalized_exact.items())

        if isinstance(rows, _PackedFrozenRows):
            ordered_indexes = rows.orders[(selected_metric, selected_order)]
            has_filters = bool(
                parent_key is not None
                or prompt_key is not None
                or normalized_needle
                or normalized_exact
            )
            if not has_filters:
                total = len(ordered_indexes)
                items = [
                    rows.decode(index)
                    for index in ordered_indexes[offset:offset + limit]
                ]
                return {
                    "items": items,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "sort_by": selected_metric,
                    "sort_order": selected_order,
                }
            items: list[dict[str, Any]] = []
            total = 0
            page_end = offset + limit
            for index in ordered_indexes:
                row = rows.decode(index)
                if not matches(row):
                    continue
                if offset <= total < page_end:
                    items.append(row)
                total += 1
            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "sort_by": selected_metric,
                "sort_order": selected_order,
            }

        filtered = [row for row in rows if isinstance(row, dict) and matches(row)]
        ordered = sort_static_report_rows(
            list_type,
            filtered,
            sort_by=selected_metric,
            sort_order=selected_order,
        )
        total = len(ordered)
        items = ordered[offset:offset + limit]
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "sort_by": selected_metric,
            "sort_order": selected_order,
        }

    async def _read_persisted_sort_index_page(
        self,
        report_id: str,
        client_id: str,
        list_type: str,
        metric: str,
        order: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any] | None:
        index_base = _sort_index_base_type(list_type, metric, order)
        index_cache_key = (self._pool, report_id, client_id, index_base)
        cached_indexes = _STATIC_REPORT_LIST_CACHE.get(index_cache_key)
        async with self._pool.acquire() as conn:
            if isinstance(cached_indexes, array):
                indexes = cached_indexes
            else:
                index_records = await conn.fetch(
                    """
                    SELECT list_type, list_version, row_count, rows_payload
                    FROM geo_static_report_lists
                    WHERE report_id = $1::uuid
                      AND client_id = $2::uuid
                      AND (list_type = $3 OR list_type LIKE $3 || '::%')
                    ORDER BY list_type
                    """,
                    report_id,
                    client_id,
                    index_base,
                )
                if not index_records:
                    return None
                if dict(index_records[0]).get("list_type") != index_base:
                    # Defensive fallback for legacy/test adapters that cannot
                    # distinguish the optional index lookup from a base-list read.
                    return None

                loaded_indexes: list[int] = []
                for shard_index, record in enumerate(index_records):
                    data = row_to_dict(record) or {}
                    expected_type = (
                        index_base
                        if shard_index == 0
                        else f"{index_base}{STATIC_REPORT_SHARD_SEPARATOR}{shard_index:0{STATIC_REPORT_SHARD_WIDTH}d}"
                    )
                    payload = data.get("rows_payload")
                    if (
                        data.get("list_type") != expected_type
                        or data.get("list_version") != SNAPSHOT_VERSION
                        or not isinstance(payload, list)
                        or int(data.get("row_count") or 0) != len(payload)
                        or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in payload)
                    ):
                        raise StaticReportListUnavailable("frozen_list_sort_index_invalid")
                    loaded_indexes.extend(payload)
                    if len(loaded_indexes) > MAX_STATIC_REPORT_LOGICAL_LIST_ROWS:
                        raise StaticReportListUnavailable("frozen_list_sort_index_invalid")

                if len(set(loaded_indexes)) != len(loaded_indexes):
                    raise StaticReportListUnavailable("frozen_list_sort_index_invalid")
                canonical_total = await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(row_count), 0)::bigint
                    FROM geo_static_report_lists
                    WHERE report_id = $1::uuid
                      AND client_id = $2::uuid
                      AND (list_type = $3 OR list_type LIKE $3 || '::%')
                    """,
                    report_id,
                    client_id,
                    list_type,
                )
                if (
                    int(canonical_total or 0) != len(loaded_indexes)
                    or (loaded_indexes and max(loaded_indexes) >= int(canonical_total or 0))
                ):
                    raise StaticReportListUnavailable("frozen_list_sort_index_invalid")
                indexes = array("I", loaded_indexes)
                _STATIC_REPORT_LIST_CACHE.put(
                    index_cache_key,
                    indexes,
                    weight_bytes=sys.getsizeof(indexes),
                )

            total = len(indexes)
            selected = indexes[offset:offset + limit]
            if not selected:
                items: list[dict[str, Any]] = []
            else:
                shard_types = [
                    static_report_shard_list_type(
                        list_type,
                        index // MAX_STATIC_REPORT_LIST_ROWS,
                    )
                    for index in selected
                ]
                local_indexes = [index % MAX_STATIC_REPORT_LIST_ROWS for index in selected]
                item_records = await conn.fetch(
                    """
                    SELECT requested.ordinality,
                           stored.rows_payload -> requested.local_index AS row_payload
                    FROM UNNEST($4::text[], $5::integer[]) WITH ORDINALITY
                         AS requested(list_type, local_index, ordinality)
                    JOIN geo_static_report_lists stored
                      ON stored.report_id = $1::uuid
                     AND stored.client_id = $2::uuid
                     AND stored.list_version = $3
                     AND stored.list_type = requested.list_type
                    ORDER BY requested.ordinality
                    """,
                    report_id,
                    client_id,
                    SNAPSHOT_VERSION,
                    shard_types,
                    local_indexes,
                )
                if len(item_records) != len(selected):
                    raise StaticReportListUnavailable("frozen_list_sort_index_invalid")
                items = []
                for record in item_records:
                    value = dict(record).get("row_payload")
                    if isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError as exc:
                            raise StaticReportListUnavailable("frozen_list_payload_invalid") from exc
                    if not isinstance(value, dict):
                        raise StaticReportListUnavailable("frozen_list_payload_invalid")
                    items.append(value)

        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "sort_by": metric,
            "sort_order": order,
        }

    async def _load_validated_frozen_rows(
        self,
        report_id: str,
        client_id: str,
        list_type: str,
    ) -> tuple[Any, ...]:
        async with self._pool.acquire() as conn:
            records = await conn.fetch(
                f"""
                SELECT list_type,
                       list_version,
                       row_count,
                       pg_column_size(rows_payload) AS payload_bytes,
                       rows_payload::text AS rows_payload_json
                FROM geo_static_report_lists
                WHERE report_id = $1::uuid
                  AND client_id = $2::uuid
                  AND (list_type = $3 OR list_type LIKE $3 || '::%')
                ORDER BY list_type
                """,
                report_id,
                client_id,
                list_type,
            )
            if not records:
                version = await conn.fetchval(
                    f"""
                    SELECT snapshot_version
                    FROM {GEO_STATIC_REPORTS}
                    WHERE id = $1::uuid AND client_id = $2::uuid
                    """,
                    report_id,
                    client_id,
                )
                if version != SNAPSHOT_VERSION:
                    raise StaticReportListUnavailable("sorting_unavailable_for_snapshot_version")
                raise StaticReportListUnavailable("frozen_list_payload_missing")

        shards: dict[int, dict[str, Any]] = {}
        total_rows = 0
        total_bytes = 0
        for record in records:
            data = row_to_dict(record) or {}
            parsed = parse_static_report_shard_list_type(data.get("list_type"))
            if parsed is None or parsed[0] != list_type or parsed[1] in shards:
                raise StaticReportListUnavailable("frozen_list_payload_invalid")
            if data.get("list_version") != SNAPSHOT_VERSION:
                raise StaticReportListUnavailable("sorting_unavailable_for_snapshot_version")
            row_count = int(data.get("row_count") or 0)
            payload_bytes = int(data.get("payload_bytes") or 0)
            if row_count > MAX_STATIC_REPORT_LIST_ROWS or payload_bytes > MAX_STATIC_REPORT_LIST_BYTES:
                raise StaticReportListUnavailable("frozen_list_payload_too_large")
            shard_rows = data.get("rows_payload")
            if shard_rows is None and isinstance(data.get("rows_payload_json"), str):
                try:
                    shard_rows = json.loads(data["rows_payload_json"])
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise StaticReportListUnavailable("frozen_list_payload_invalid") from exc
            if not isinstance(shard_rows, list) or row_count != len(shard_rows):
                raise StaticReportListUnavailable("frozen_list_payload_invalid")
            total_rows += row_count
            total_bytes += payload_bytes
            if total_rows > MAX_STATIC_REPORT_LOGICAL_LIST_ROWS or total_bytes > MAX_STATIC_REPORT_TOTAL_BYTES:
                raise StaticReportListUnavailable("frozen_list_payload_too_large")
            shards[parsed[1]] = data

        if sorted(shards) != list(range(len(shards))):
            raise StaticReportListUnavailable("frozen_list_payload_invalid")
        return tuple(
            row
            for shard_index in range(len(shards))
            for row in shards[shard_index]["rows_payload"]
        )

    async def release_materialization(
        self,
        report_id: str,
        materialization_token: Any,
    ) -> dict[str, Any]:
        """Release a fenced claim when global generation capacity is busy."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                client_id = await self._client_id_for_report(conn, report_id)
                await acquire_workspace_lifecycle_shared(conn, client_id)
                await self._lock_materialization_owner(conn, report_id, materialization_token)
                row = await conn.fetchrow(
                    f"""
                    UPDATE {GEO_STATIC_REPORTS}
                    SET status = $4,
                        error_message = NULL,
                        updated_at = clock_timestamp()
                    WHERE id = $1::uuid
                      AND status = $2
                      AND updated_at IS NOT DISTINCT FROM $3::timestamptz
                    RETURNING {META_COLUMNS}
                    """,
                    report_id,
                    StaticReportStatus.MATERIALIZING.value,
                    materialization_token,
                    StaticReportStatus.PENDING.value,
                )
                if not row:
                    raise MaterializationLeaseLost("materialization lease changed before capacity release")
        return row_to_dict(row)

    async def fail(self, report_id: str, materialization_token: Any, message: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                client_id = await self._client_id_for_report(conn, report_id)
                await acquire_workspace_lifecycle_shared(conn, client_id)
                await self._lock_materialization_owner(conn, report_id, materialization_token)
                row = await conn.fetchrow(
                    f"""
                    UPDATE {GEO_STATIC_REPORTS}
                    SET status = $4,
                        error_message = $5,
                        updated_at = clock_timestamp()
                    WHERE id = $1::uuid
                      AND status = $2
                      AND updated_at IS NOT DISTINCT FROM $3::timestamptz
                    RETURNING {META_COLUMNS}
                    """,
                    report_id,
                    StaticReportStatus.MATERIALIZING.value,
                    materialization_token,
                    StaticReportStatus.FAILED.value,
                    message[:2000],
                )
                if not row:
                    raise MaterializationLeaseLost("materialization lease changed before failure finalization")
        return row_to_dict(row)
