from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import routers.static_reports.repository as repository_module
from routers.static_reports.models import (
    RenderingMode,
    SNAPSHOT_VERSION,
    StaticReportPayloadTooLarge,
    StaticReportStatus,
)
from routers.static_reports.repository import (
    StaticReportRepository,
    prepare_static_report_list_blobs,
)
from routers.static_reports.snapshot_builder import build_static_report_list_blobs
from routers.static_reports.sorting import STATIC_REPORT_LIST_SPECS


def _snapshot() -> dict:
    return {
        "visibility": {"dashboard": {
            "_complete_visibility_ranking": [
                {"brand_name": "Beta", "visibility_pct": None, "mention_count": 2, "rank": 2},
                {"brand_name": "Alpha", "visibility_pct": 80, "mention_count": 8, "rank": 1},
            ],
            "_complete_sov_ranking": [],
            "_complete_position_ranking": [],
            "_complete_topic_sov_ranking": [],
            "_complete_product_sov_ranking": [],
        }},
        "citations": {"dashboard": {"_complete_domain_ranking": [], "_complete_page_ranking": [], "category_breakdown": []}},
        "sentiment": {"dashboard": {"_complete_themes": []}},
        "prompts": {"_complete_ranking": []},
        "topics": {"_complete_ranking": []},
    }


def test_builder_materializes_exactly_one_versioned_blob_per_registered_list():
    snapshot = _snapshot()

    blobs = build_static_report_list_blobs(snapshot)

    assert len(blobs) == len(STATIC_REPORT_LIST_SPECS) == 17
    assert {blob["list_type"] for blob in blobs} == set(STATIC_REPORT_LIST_SPECS)
    assert all(blob["list_version"] == SNAPSHOT_VERSION for blob in blobs)
    assert all(blob["row_count"] == len(blob["rows_payload"]) for blob in blobs)
    visibility = next(blob for blob in blobs if blob["list_type"] == "visibility.brand_visibility")
    assert visibility["row_count"] == 2
    assert [row["brand_name"] for row in visibility["rows_payload"]] == ["Alpha", "Beta"]
    assert snapshot["frozen_lists"]["visibility.brand_visibility"]["total"] == 2


def test_embedded_default_lists_use_the_same_twenty_row_page_as_the_list_api():
    snapshot = _snapshot()
    snapshot["citations"]["dashboard"]["category_breakdown"] = [
        {"label": f"Category {index}", "count": 100 - index, "pct": index}
        for index in range(25)
    ]
    snapshot["sentiment"]["dashboard"]["_complete_themes"] = [
        {"theme_name": f"Theme {index}", "sentiment": "Positive", "occurrence_count": 100 - index}
        for index in range(25)
    ]
    snapshot["prompts"]["_complete_ranking"] = [
        {"prompt_id": f"prompt-{index}", "prompt_text": f"Prompt {index}", "mention_count": 100 - index}
        for index in range(25)
    ]
    snapshot["topics"]["_complete_ranking"] = [
        {"topic_name": f"Topic {index}", "mention_count": 100 - index}
        for index in range(25)
    ]

    build_static_report_list_blobs(snapshot)

    assert len(snapshot["citations"]["dashboard"]["category_breakdown"]) == 20
    assert len(snapshot["sentiment"]["dashboard"]["themes"]) == 20
    assert len(snapshot["prompts"]["ranking"]) == 20
    assert len(snapshot["topics"]["ranking"]) == 20


class _Transaction:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        self.events.append("transaction:enter")

    async def __aexit__(self, exc_type, _exc, _tb):
        self.events.append("transaction:rollback" if exc_type else "transaction:commit")


class _Connection:
    def __init__(self):
        self.events = []
        self.executemany_args = []
        self.blob = None
        self.fetch_sql = []
        self.fetchrow_sql = []

    def transaction(self):
        return _Transaction(self.events)

    async def fetchval(self, sql, *_args):
        if "SELECT client_id::text" in sql:
            return "client-1"
        if "pg_try_advisory_xact_lock_shared" in sql or "FROM geo_clients" in sql:
            return True
        return None

    async def execute(self, sql, *_args):
        if "DELETE FROM geo_static_report_lists" in sql:
            self.events.append("blobs:delete")

    async def executemany(self, sql, args):
        assert "INSERT INTO geo_static_report_lists" in sql
        self.events.append("blobs:insert")
        self.executemany_args = list(args)

    async def fetchrow(self, sql, *args):
        self.fetchrow_sql.append((sql, args))
        if "FOR UPDATE" in sql:
            self.events.append("owner:lock")
            return {"id": "report-1", "status": StaticReportStatus.MATERIALIZING.value}
        if "UPDATE geo_static_reports" in sql:
            self.events.append("snapshot:update")
            return {"id": "report-1", "client_id": "client-1", "status": StaticReportStatus.COMPLETED.value}
        return None

    async def fetch(self, sql, *args):
        self.fetch_sql.append((sql, args))
        if "FROM geo_static_report_lists" not in sql or self.blob is None:
            return []
        if len(args) >= 3 and "@sort." in str(args[2]):
            return []
        return [{
            "list_type": args[2],
            **self.blob,
            "payload_bytes": len(str(self.blob.get("rows_payload", [])).encode("utf-8")),
        }]


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def test_complete_persists_all_blobs_and_snapshot_atomically():
    conn = _Connection()
    pool = _Pool(conn)
    repo = StaticReportRepository(pool)
    blobs = build_static_report_list_blobs(_snapshot())
    cache_key = (pool, "report-1", "client-1", "citation.domain")
    repository_module._STATIC_REPORT_LIST_CACHE.put(
        cache_key,
        ({"row_key": "stale"},),
        weight_bytes=64,
    )

    asyncio.run(repo.complete(
        "report-1",
        datetime(2026, 7, 14, tzinfo=timezone.utc),
        {"version": SNAPSHOT_VERSION},
        RenderingMode.MULTI_DAY,
        {},
        [],
        blobs,
    ))

    assert conn.events == [
        "transaction:enter", "owner:lock", "blobs:delete", "blobs:insert",
        "snapshot:update", "transaction:commit",
    ]
    assert len(conn.executemany_args) == 17
    assert repository_module._STATIC_REPORT_LIST_CACHE.get(cache_key) == ()


def test_complete_does_not_report_failure_after_durable_commit_if_cache_warm_fails(monkeypatch):
    conn = _Connection()
    repo = StaticReportRepository(_Pool(conn))
    blobs = build_static_report_list_blobs(_snapshot())
    monkeypatch.setattr(
        repository_module,
        "_warm_completed_report_lists",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("cache unavailable")),
    )

    result = asyncio.run(repo.complete(
        "report-1",
        datetime(2026, 7, 14, tzinfo=timezone.utc),
        {"version": SNAPSHOT_VERSION},
        RenderingMode.MULTI_DAY,
        {},
        [],
        blobs,
    ))

    assert result["status"] == StaticReportStatus.COMPLETED.value
    assert conn.events[-1] == "transaction:commit"


def test_complete_rejects_incomplete_blob_sets_before_opening_a_transaction():
    conn = _Connection()
    repo = StaticReportRepository(_Pool(conn))
    blobs = build_static_report_list_blobs(_snapshot())[:-1]

    try:
        asyncio.run(repo.complete(
            "report-1",
            datetime(2026, 7, 14, tzinfo=timezone.utc),
            {"version": SNAPSHOT_VERSION},
            RenderingMode.MULTI_DAY,
            {},
            [],
            blobs,
        ))
    except ValueError as exc:
        assert str(exc) == "static report list blobs do not match the registered contract"
    else:
        raise AssertionError("incomplete blob sets must not be persisted")

    assert conn.events == []


def _empty_registered_blobs() -> list[dict]:
    return [
        {
            "list_type": list_type,
            "list_version": SNAPSHOT_VERSION,
            "row_count": 0,
            "rows_payload": [],
        }
        for list_type in STATIC_REPORT_LIST_SPECS
    ]


def test_prepare_accepts_continuous_deterministic_shards_for_each_registered_base():
    blobs = _empty_registered_blobs()
    base = "citation.domain"
    base_blob = next(blob for blob in blobs if blob["list_type"] == base)
    base_blob.update({
        "row_count": 1,
        "rows_payload": [{"row_key": "a", "domain": "a.example", "citation_count": 2}],
    })
    blobs.append({
        "list_type": f"{base}::000001",
        "list_version": SNAPSHOT_VERSION,
        "row_count": 1,
        "rows_payload": [{"row_key": "b", "domain": "b.example", "citation_count": 1}],
    })

    prepared = prepare_static_report_list_blobs(blobs)

    prepared_types = [item[0] for item in prepared]
    assert base in prepared_types
    assert f"{base}::000001" in prepared_types


def test_prepare_rejects_a_gap_in_registered_base_shards():
    blobs = _empty_registered_blobs()
    blobs.append({
        "list_type": "citation.domain::000002",
        "list_version": SNAPSHOT_VERSION,
        "row_count": 0,
        "rows_payload": [],
    })

    try:
        prepare_static_report_list_blobs(blobs)
    except ValueError as exc:
        assert str(exc) == "static report list blobs do not match the registered contract"
    else:
        raise AssertionError("a frozen-list shard sequence must start at the base and remain contiguous")


def test_builder_stops_when_one_list_exceeds_the_enforced_row_ceiling(monkeypatch):
    snapshot = _snapshot()
    snapshot["visibility"]["dashboard"]["_complete_visibility_ranking"].append(
        {"brand_name": "Gamma", "visibility_pct": 1, "mention_count": 1, "rank": 3},
    )
    monkeypatch.setattr("routers.static_reports.snapshot_builder.MAX_STATIC_REPORT_LIST_ROWS", 2)

    try:
        build_static_report_list_blobs(snapshot)
    except StaticReportPayloadTooLarge as exc:
        assert "visibility.brand_visibility" in str(exc)
    else:
        raise AssertionError("oversized list construction must stop before persistence")


def test_complete_rejects_oversized_serialized_payloads_before_opening_a_transaction(monkeypatch):
    conn = _Connection()
    repo = StaticReportRepository(_Pool(conn))
    blobs = build_static_report_list_blobs(_snapshot())
    monkeypatch.setattr("routers.static_reports.repository.MAX_STATIC_REPORT_LIST_BYTES", 10)

    try:
        asyncio.run(repo.complete(
            "report-1",
            datetime(2026, 7, 14, tzinfo=timezone.utc),
            {"version": SNAPSHOT_VERSION},
            RenderingMode.MULTI_DAY,
            {},
            [],
            blobs,
        ))
    except StaticReportPayloadTooLarge:
        pass
    else:
        raise AssertionError("oversized serialized blobs must be rejected")

    assert conn.events == []


def test_complete_rejects_oversized_snapshot_before_opening_a_transaction(monkeypatch):
    conn = _Connection()
    repo = StaticReportRepository(_Pool(conn))
    blobs = build_static_report_list_blobs(_snapshot())
    monkeypatch.setattr("routers.static_reports.repository.MAX_STATIC_REPORT_SNAPSHOT_BYTES", 10)

    try:
        asyncio.run(repo.complete(
            "report-1",
            datetime(2026, 7, 14, tzinfo=timezone.utc),
            {"version": SNAPSHOT_VERSION, "wide": "x" * 20},
            RenderingMode.MULTI_DAY,
            {},
            [],
            blobs,
        ))
    except StaticReportPayloadTooLarge as exc:
        assert "snapshot exceeds byte limit" in str(exc)
    else:
        raise AssertionError("oversized snapshot_json must be rejected")

    assert conn.events == []


def test_repository_point_reads_blob_then_sorts_all_rows_before_pagination():
    conn = _Connection()
    conn.blob = {
        "list_version": SNAPSHOT_VERSION,
        "row_count": 4,
        "rows_payload": [
            {"row_key": "n", "domain": "null.example", "citation_count": None, "default_position": 3},
            {"row_key": "b", "domain": "b.example", "citation_count": 5, "default_position": 1},
            {"row_key": "a", "domain": "a.example", "citation_count": 5, "default_position": 0},
            {"row_key": "c", "domain": "c.example", "citation_count": 1, "default_position": 2},
        ],
    }
    repo = StaticReportRepository(_Pool(conn))

    result = asyncio.run(repo.list_frozen_rows(
        "report-1", "client-1", "citation.domain",
        sort_by="citation_count", sort_order="desc", limit=2, offset=1,
    ))

    assert [item["domain"] for item in result["items"]] == ["b.example", "c.example"]
    assert result["total"] == 4
    list_calls = [
        call for call in conn.fetch_sql
        if "FROM geo_static_report_lists" in call[0] and call[1][2] == "citation.domain"
    ]
    assert len(list_calls) == 1
    sql, args = list_calls[0]
    assert "pg_column_size(rows_payload)" in sql
    assert "rows_payload::text AS rows_payload_json" in sql
    assert "CASE" not in sql
    assert "ORDER BY LIST_TYPE" in sql.upper()
    assert args == ("report-1", "client-1", "citation.domain")


def test_repository_merges_all_shards_before_global_sort_filter_and_pagination():
    class ShardConnection(_Connection):
        def __init__(self):
            super().__init__()
            self.fetch_calls = []

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

    conn = ShardConnection()
    repo = StaticReportRepository(_Pool(conn))

    result = asyncio.run(repo.list_frozen_rows(
        "report-1", "client-1", "citation.domain",
        sort_by="citation_count", sort_order="desc", limit=2, offset=1,
    ))

    assert result["total"] == 4
    assert [item["domain"] for item in result["items"]] == ["b.example", "c.example"]
    assert len([call for call in conn.fetch_calls if call[1][2] == "citation.domain"]) == 1
    sql, args = next(call for call in conn.fetch_calls if call[1][2] == "citation.domain")
    assert "list_type = $3" in sql
    assert "list_type LIKE" in sql
    assert args == ("report-1", "client-1", "citation.domain")


def test_repository_serializes_blob_reads_through_the_instance_memory_budget(monkeypatch):
    import routers.static_reports.repository as repository_module

    events = []

    class BlockingConnection(_Connection):
        async def fetch(self, sql, *args):
            events.append(f"fetch:{args[0]}")
            if args[0] == "report-1":
                await first_read_started.wait()
                release_first_read.clear()
                first_read_started.clear()
                release_first_read.set()
                await allow_first_read_to_finish.wait()
            return [{
                "list_type": args[2],
                "list_version": SNAPSHOT_VERSION,
                "row_count": 0,
                "payload_bytes": 2,
                "rows_payload": [],
            }]

    first_read_started = asyncio.Event()
    allow_first_read_to_finish = asyncio.Event()
    release_first_read = asyncio.Event()
    conn = BlockingConnection()
    repo = StaticReportRepository(_Pool(conn))

    async def scenario():
        monkeypatch.setattr(
            repository_module,
            "_STATIC_REPORT_LIST_READ_SEMAPHORE",
            asyncio.Semaphore(1),
        )

        original_fetch = conn.fetch

        async def tracked_fetch(sql, *args):
            if args[0] == "report-1":
                first_read_started.set()
            return await original_fetch(sql, *args)

        conn.fetch = tracked_fetch
        first = asyncio.create_task(repo.list_frozen_rows(
            "report-1", "client-1", "citation.domain",
            sort_by="citation_count", sort_order="desc",
        ))
        await first_read_started.wait()
        second = asyncio.create_task(repo.list_frozen_rows(
            "report-2", "client-1", "citation.domain",
            sort_by="citation_count", sort_order="desc",
        ))
        await asyncio.sleep(0)
        assert events == ["fetch:report-1"]
        allow_first_read_to_finish.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())
    assert events == ["fetch:report-1", "fetch:report-2"]
