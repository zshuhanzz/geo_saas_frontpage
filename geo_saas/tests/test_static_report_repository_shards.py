from __future__ import annotations

import asyncio

import pytest

import routers.static_reports.repository as repository_module
from routers.static_reports.models import (
    MAX_STATIC_REPORT_BLOB_BYTES,
    MAX_STATIC_REPORT_BLOB_ROWS,
    MAX_STATIC_REPORT_TOTAL_BYTES,
    MAX_STATIC_REPORT_TOTAL_ROWS,
    SNAPSHOT_VERSION,
    StaticReportPayloadTooLarge,
)
from routers.static_reports.repository import (
    StaticReportRepository,
    prepare_static_report_list_blobs,
)
from routers.static_reports.sorting import STATIC_REPORT_LIST_SPECS
from routers.static_reports.sorting import StaticReportListUnavailable


def _registered_blobs() -> list[dict]:
    return [
        {
            "list_type": list_type,
            "list_version": SNAPSHOT_VERSION,
            "row_count": 0,
            "rows_payload": [],
        }
        for list_type in STATIC_REPORT_LIST_SPECS
    ]


def test_prepare_accepts_contiguous_shards_for_every_registered_base():
    blobs = _registered_blobs()
    base_blob = next(blob for blob in blobs if blob["list_type"] == "citation.domain")
    base_blob.update({
        "row_count": 1,
        "rows_payload": [{"row_key": "a", "domain": "a.example", "citation_count": 2}],
    })
    blobs.append({
        "list_type": "citation.domain::000001",
        "list_version": SNAPSHOT_VERSION,
        "row_count": 1,
        "rows_payload": [{"row_key": "b", "domain": "b.example", "citation_count": 1}],
    })

    prepared = prepare_static_report_list_blobs(blobs)

    assert "citation.domain" in [item[0] for item in prepared]
    assert "citation.domain::000001" in [item[0] for item in prepared]


def test_prepare_rejects_non_contiguous_shards():
    blobs = _registered_blobs()
    blobs.append({
        "list_type": "citation.domain::000002",
        "list_version": SNAPSHOT_VERSION,
        "row_count": 0,
        "rows_payload": [],
    })

    with pytest.raises(ValueError, match="registered contract"):
        prepare_static_report_list_blobs(blobs)


def test_capacity_contract_keeps_small_shards_and_dreamina_sized_logical_totals():
    assert MAX_STATIC_REPORT_BLOB_ROWS == 25_000
    assert MAX_STATIC_REPORT_BLOB_BYTES == 16 * 1024 * 1024
    assert MAX_STATIC_REPORT_TOTAL_ROWS == 300_000
    assert MAX_STATIC_REPORT_TOTAL_BYTES == 128 * 1024 * 1024


@pytest.mark.parametrize(
    ("raw", "default", "ceiling", "expected"),
    [
        (None, 16, 128, 16),
        ("invalid", 16, 128, 16),
        ("-1", 16, 128, 0),
        ("0", 16, 128, 0),
        ("8", 16, 128, 8),
        ("999", 16, 128, 128),
    ],
)
def test_cache_limit_config_is_safe_and_bounded(raw, default, ceiling, expected):
    assert repository_module.parse_static_report_cache_limit(
        raw,
        default=default,
        ceiling=ceiling,
    ) == expected


def test_prepare_enforces_logical_total_rows_across_shards(monkeypatch):
    blobs = _registered_blobs()
    base_blob = next(blob for blob in blobs if blob["list_type"] == "citation.domain")
    base_blob.update({"row_count": 1, "rows_payload": [{"row_key": "a"}]})
    blobs.append({
        "list_type": "citation.domain::000001",
        "list_version": SNAPSHOT_VERSION,
        "row_count": 1,
        "rows_payload": [{"row_key": "b"}],
    })
    monkeypatch.setattr(repository_module, "MAX_STATIC_REPORT_TOTAL_ROWS", 1)

    with pytest.raises(ValueError, match="registered contract"):
        prepare_static_report_list_blobs(blobs)


def test_prepare_enforces_serialized_bytes_per_storage_shard(monkeypatch):
    blobs = _registered_blobs()
    base_blob = next(blob for blob in blobs if blob["list_type"] == "citation.domain")
    base_blob.update({"row_count": 1, "rows_payload": [{"row_key": "x" * 40}]})
    monkeypatch.setattr(repository_module, "MAX_STATIC_REPORT_LIST_BYTES", 10)

    with pytest.raises(StaticReportPayloadTooLarge, match="shard exceeds byte limit"):
        prepare_static_report_list_blobs(blobs)


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


class _ShardConnection:
    def __init__(self):
        self.fetch_calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        if len(args) >= 3 and "@sort." in str(args[2]):
            return []
        return [
            {
                "list_type": "citation.domain",
                "list_version": SNAPSHOT_VERSION,
                "row_count": 2,
                "payload_bytes": 128,
                "rows_payload": [
                    {"row_key": "a", "domain": "a.example", "citation_count": 5, "default_position": 0},
                    {"row_key": "c", "domain": "c.example", "citation_count": 1, "default_position": 2},
                ],
            },
            {
                "list_type": "citation.domain::000001",
                "list_version": SNAPSHOT_VERSION,
                "row_count": 2,
                "payload_bytes": 128,
                "rows_payload": [
                    {"row_key": "b", "domain": "b.example", "citation_count": 5, "default_position": 1},
                    {"row_key": "n", "domain": "null.example", "citation_count": None, "default_position": 3},
                ],
            },
        ]

    async def fetchval(self, *_args):
        return SNAPSHOT_VERSION


def test_reader_merges_all_shards_before_global_sort_and_pagination():
    connection = _ShardConnection()
    repository = StaticReportRepository(_Pool(connection))

    result = asyncio.run(repository.list_frozen_rows(
        "report-1",
        "client-1",
        "citation.domain",
        sort_by="citation_count",
        sort_order="desc",
        limit=2,
        offset=1,
    ))

    assert result["total"] == 4
    assert [item["domain"] for item in result["items"]] == ["b.example", "c.example"]
    base_calls = [call for call in connection.fetch_calls if call[1][2] == "citation.domain"]
    assert len(base_calls) == 1
    sql, args = base_calls[0]
    assert "list_type = $3" in sql
    assert "list_type LIKE" in sql
    assert args == ("report-1", "client-1", "citation.domain")


def test_reader_rejects_a_missing_middle_shard():
    class GapConnection(_ShardConnection):
        async def fetch(self, sql, *args):
            rows = await super().fetch(sql, *args)
            if not rows:
                return rows
            rows[1]["list_type"] = "citation.domain::000002"
            return rows

    repository = StaticReportRepository(_Pool(GapConnection()))

    with pytest.raises(StaticReportListUnavailable, match="frozen_list_payload_invalid"):
        asyncio.run(repository.list_frozen_rows(
            "report-1",
            "client-1",
            "citation.domain",
            sort_by="citation_count",
            sort_order="desc",
        ))


def test_reader_reuses_one_validated_immutable_payload_across_sort_and_page_requests():
    connection = _ShardConnection()
    pool = _Pool(connection)
    repository = StaticReportRepository(pool)

    first = asyncio.run(repository.list_frozen_rows(
        "report-cache-once",
        "client-cache-once",
        "citation.domain",
        sort_by="citation_count",
        sort_order="desc",
        limit=2,
        offset=0,
    ))
    second = asyncio.run(StaticReportRepository(pool).list_frozen_rows(
        "report-cache-once",
        "client-cache-once",
        "citation.domain",
        sort_by="citation_count",
        sort_order="asc",
        limit=1,
        offset=1,
    ))

    assert [item["domain"] for item in first["items"]] == ["a.example", "b.example"]
    assert [item["domain"] for item in second["items"]] == ["a.example"]
    assert len([call for call in connection.fetch_calls if call[1][2] == "citation.domain"]) == 1


def test_frozen_list_cache_is_lru_bounded_by_entry_count_and_memory_weight():
    cache = repository_module._FrozenListCache(max_entries=2, max_bytes=100)
    first = ("pool", "report-a", "client-a", "citation.domain")
    second = ("pool", "report-b", "client-a", "citation.domain")
    third = ("pool", "report-c", "client-a", "citation.domain")

    assert cache.put(first, ({"row_key": "a"},), weight_bytes=40) is True
    assert cache.put(second, ({"row_key": "b"},), weight_bytes=40) is True
    assert cache.get(first) == ({"row_key": "a"},)
    assert cache.put(third, ({"row_key": "c"},), weight_bytes=40) is True

    assert cache.get(first) == ({"row_key": "a"},)
    assert cache.get(second) is None
    assert cache.get(third) == ({"row_key": "c"},)
    assert cache.put(second, ({"row_key": "too-large"},), weight_bytes=101) is False
    assert cache.get(second) is None


def test_default_frozen_list_cache_can_retain_dreamina_sized_weekly_page_list():
    # The real Dreamina seven-day citation.page snapshot is slightly above the
    # former 32 MiB object-tree budget. Keep enough headroom for that hot list;
    # the global byte cap still prevents unbounded per-instance growth.
    assert repository_module.STATIC_REPORT_LIST_CACHE_DEFAULT_BYTES >= 128 * 1024 * 1024


def test_packed_frozen_rows_preserve_every_metric_order_without_expanded_tree():
    rows = (
        {"row_key": "a", "url": "a", "domain": "a.example", "citation_count": 2, "share_pct": 1.0, "change_pct": -1.0},
        {"row_key": "b", "url": "b", "domain": "b.example", "citation_count": 4, "share_pct": 0.5, "change_pct": 3.0},
        {"row_key": "c", "url": "c", "domain": "c.example", "citation_count": 1, "share_pct": 2.0, "change_pct": 1.0},
    )

    packed = repository_module._pack_frozen_rows("citation.page", rows)

    assert [packed.decode(index)["url"] for index in packed.orders[("citation_count", "desc")]] == ["b", "a", "c"]
    assert [packed.decode(index)["url"] for index in packed.orders[("share_pct", "asc")]] == ["b", "a", "c"]
    assert [packed.decode(index)["url"] for index in packed.orders[("change_pct", "desc")]] == ["b", "c", "a"]
    assert all(isinstance(payload, bytes) for payload in packed.payloads)


def test_reader_reuses_packed_large_citation_list_across_global_sorts(monkeypatch):
    connection = _ShardConnection()
    pool = _Pool(connection)
    repository = StaticReportRepository(pool)
    compact_cache = repository_module._FrozenListCache(max_entries=2, max_bytes=1024 * 1024)
    monkeypatch.setattr(repository_module, "_STATIC_REPORT_LIST_CACHE", compact_cache)
    monkeypatch.setattr(repository_module, "_estimate_frozen_rows_memory", lambda _rows: 2 * 1024 * 1024)

    first = asyncio.run(repository.list_frozen_rows(
        "report-packed",
        "client-packed",
        "citation.domain",
        sort_by="citation_count",
        sort_order="desc",
        limit=2,
    ))
    second = asyncio.run(repository.list_frozen_rows(
        "report-packed",
        "client-packed",
        "citation.domain",
        sort_by="citation_count",
        sort_order="asc",
        limit=2,
    ))

    assert [row["domain"] for row in first["items"]] == ["a.example", "b.example"]
    assert [row["domain"] for row in second["items"]] == ["c.example", "a.example"]
    assert len([call for call in connection.fetch_calls if call[1][2] == "citation.domain"]) == 1
    assert isinstance(
        compact_cache.get((pool, "report-packed", "client-packed", "citation.domain")),
        repository_module._PackedFrozenRows,
    )


def test_reader_uses_persisted_sort_index_without_loading_the_full_json_list():
    class IndexedConnection:
        def __init__(self):
            self.fetch_calls = []

        async def fetch(self, sql, *args):
            self.fetch_calls.append((sql, args))
            if "@sort." in str(args[2]):
                return [{
                    "list_type": "citation.page@sort.change_pct.desc",
                    "list_version": SNAPSHOT_VERSION,
                    "row_count": 3,
                    "rows_payload": [2, 0, 1],
                }]
            assert "UNNEST" in sql
            rows = {
                0: {"url": "zero", "change_pct": 1},
                1: {"url": "one", "change_pct": 0},
                2: {"url": "two", "change_pct": 2},
            }
            return [
                {"ordinality": position + 1, "row_payload": rows[index]}
                for position, index in enumerate(args[4])
            ]

        async def fetchval(self, _sql, *_args):
            return 3

    connection = IndexedConnection()
    result = asyncio.run(StaticReportRepository(_Pool(connection)).list_frozen_rows(
        "report-indexed",
        "client-indexed",
        "citation.page",
        sort_by="change_pct",
        sort_order="desc",
        limit=2,
        offset=0,
    ))

    assert result["total"] == 3
    assert [row["url"] for row in result["items"]] == ["two", "zero"]
    assert len(connection.fetch_calls) == 2
    assert all("pg_column_size(rows_payload)" not in sql for sql, _args in connection.fetch_calls)


def test_large_citation_lists_prepare_compact_cross_instance_indexes(monkeypatch):
    blobs = _registered_blobs()
    page_blob = next(blob for blob in blobs if blob["list_type"] == "citation.page")
    page_blob.update({
        "row_count": 2,
        "rows_payload": [
            {"row_key": "a", "url": "a", "domain": "a", "citation_count": 1, "share_pct": 2, "change_pct": -1},
            {"row_key": "b", "url": "b", "domain": "b", "citation_count": 2, "share_pct": 1, "change_pct": 3},
        ],
    })
    monkeypatch.setattr(repository_module, "STATIC_REPORT_LIST_PACK_THRESHOLD_BYTES", 0)

    indexes, packed = repository_module._prepare_persisted_sort_indexes(blobs)

    assert "citation.page" in packed
    index_types = {item[0] for item in indexes}
    assert "citation.page@sort.change_pct.desc" in index_types
    change_desc = next(item for item in indexes if item[0] == "citation.page@sort.change_pct.desc")
    assert change_desc[2] == 2
    assert change_desc[3] == "[1,0]"


def test_reader_rejects_a_truncated_persisted_sort_index():
    class TruncatedIndexConnection:
        async def fetch(self, sql, *args):
            if "@sort." in str(args[2]):
                return [{
                    "list_type": "citation.page@sort.change_pct.desc",
                    "list_version": SNAPSHOT_VERSION,
                    "row_count": 2,
                    "rows_payload": [0, 1],
                }]
            raise AssertionError(sql)

        async def fetchval(self, _sql, *_args):
            return 3

    with pytest.raises(StaticReportListUnavailable, match="frozen_list_sort_index_invalid"):
        asyncio.run(StaticReportRepository(_Pool(TruncatedIndexConnection())).list_frozen_rows(
            "report-truncated",
            "client-truncated",
            "citation.page",
            sort_by="change_pct",
            sort_order="desc",
        ))


def test_frozen_list_cache_key_keeps_tenants_isolated():
    connection = _ShardConnection()
    pool = _Pool(connection)
    repository = StaticReportRepository(pool)

    for client_id in ("client-cache-a", "client-cache-b"):
        asyncio.run(repository.list_frozen_rows(
            "report-cache-tenant",
            client_id,
            "citation.domain",
            sort_by="citation_count",
            sort_order="desc",
        ))

    assert [call[1][1] for call in connection.fetch_calls if call[1][2] == "citation.domain"] == [
        "client-cache-a",
        "client-cache-b",
    ]
