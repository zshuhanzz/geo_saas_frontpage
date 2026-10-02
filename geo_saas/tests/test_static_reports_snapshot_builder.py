from datetime import date
import asyncio
from dataclasses import FrozenInstanceError

import pytest

from routers.static_reports.models import SNAPSHOT_VERSION, RenderingMode, ReportDates, compute_previous_report_dates
from routers.static_reports.repository import row_to_dict
from routers.static_reports.snapshot_builder import (
    MAX_STATIC_REPORT_AGGREGATE_BYTES,
    MAX_STATIC_REPORT_AGGREGATE_ROWS,
    MAX_STATIC_REPORT_VISIBILITY_GRANULAR_BYTES,
    MAX_STATIC_REPORT_VISIBILITY_GRANULAR_ROWS,
    STATIC_REPORT_SOURCE_ROW_LIMIT,
    build_citation_category_breakdown,
    build_citation_domain_ranking,
    build_citation_period_snapshots_from_aggregate_rows,
    build_static_report_list_blobs,
    choose_rendering_mode,
    choose_report_rendering_mode,
    empty_snapshot,
    iter_window_dates,
    materialize_previous_period,
    build_visibility_daily_series,
    build_citation_daily_series,
    build_sentiment_daily_series,
    build_sentiment_dashboard_from_aggregate_rows,
    load_sentiment_period_rows,
    load_visibility_dashboard_snapshot,
    load_previous_sections,
    load_prompt_topic_snapshot,
    load_snapshot_filter_config,
    SnapshotFilterConfig,
    build_snapshot,
    gather_snapshot_stages,
    fetch_bounded_aggregate_rows,
)


def test_citation_period_builder_preserves_full_current_universe_and_previous_shares():
    dates = ReportDates(
        report_date=date(2026, 7, 14),
        window_start=date(2026, 7, 8),
        window_end=date(2026, 7, 14),
        window_days=7,
    )
    previous_dates = compute_previous_report_dates(dates)
    rows = [
        {
            "source_url": "https://own.example/a",
            "source_domain": "own.example",
            "domain_category": "Owned Media",
            "current_citation_count": 10,
            "previous_citation_count": 5,
        },
        {
            "source_url": "https://external.example/a",
            "source_domain": "external.example",
            "domain_category": "Earned Media",
            "current_citation_count": 30,
            "previous_citation_count": 15,
        },
        {
            "source_url": "https://previous-only.example/a",
            "source_domain": "previous-only.example",
            "domain_category": "Earned Media",
            "current_citation_count": 0,
            "previous_citation_count": 80,
        },
    ]
    daily_rows = [
        {"date": "2026-07-14", "total_citations": 40, "own_citations": 10},
        {"date": str(previous_dates.window_end), "total_citations": 100, "own_citations": 5},
    ]

    result = build_citation_period_snapshots_from_aggregate_rows(
        rows, daily_rows, {"own.example"}, dates, previous_dates,
    )

    current = result["current"]["dashboard"]
    previous = result["previous"]["dashboard"]
    assert current["summary"]["total_citations"] == 40
    assert previous["summary"]["total_citations"] == 100
    assert current["summary"]["own_domain_share"] == 25.0
    assert previous["summary"]["own_domain_share"] == 5.0
    assert len(current["_complete_page_ranking"]) == 2
    assert current["_complete_page_ranking"][0]["url"] == "https://external.example/a"
    own_page = next(row for row in current["_complete_page_ranking"] if row["is_own"])
    assert own_page["_previous_share_pct"] == 5.0
    assert previous["page_ranking"][0]["url"] == "https://previous-only.example/a"
    assert len(current["time_series"]) == 7
    assert len(previous["time_series"]) == 7


def test_static_report_list_builder_splits_large_logical_lists_into_deterministic_shards(monkeypatch):
    snapshot = {"citations": {"dashboard": {"_complete_page_ranking": [
        {
            "rank": index + 1,
            "url": f"https://example.com/{index}",
            "domain": "example.com",
            "domain_category": "Earned Media",
            "is_own": False,
            "citation_count": 10 - index,
            "share_pct": float(10 - index),
            "change_pct": 0.0,
        }
        for index in range(3)
    ]}}}
    monkeypatch.setattr(
        "routers.static_reports.snapshot_builder.MAX_STATIC_REPORT_BLOB_ROWS", 2,
    )

    blobs = build_static_report_list_blobs(snapshot)
    page_blobs = [blob for blob in blobs if blob["list_type"].startswith("citation.page")]

    assert [blob["list_type"] for blob in page_blobs] == [
        "citation.page", "citation.page::000001",
    ]
    assert [blob["row_count"] for blob in page_blobs] == [2, 1]
    assert [row["rank"] for blob in page_blobs for row in blob["rows_payload"]] == [1, 2, 3]


def _cursor_from_fake_fetch(connection, sql, *args, prefetch):
    assert prefetch > 0

    async def iterate():
        for row in await connection.fetch(sql, *args):
            yield row

    return iterate()


def test_static_report_worker_budget_preserves_five_pool_connections(monkeypatch):
    from routers.static_reports.snapshot_builder import snapshot_worker_limit

    class Pool:
        @staticmethod
        def get_max_size():
            return 8

    monkeypatch.delenv("STATIC_REPORT_SNAPSHOT_CONCURRENCY", raising=False)
    monkeypatch.delenv("STATIC_REPORT_DB_CONNECTION_RESERVE", raising=False)
    # The global advisory-lock guard owns one connection in addition to the
    # snapshot coordinator, leaving one worker while five pool slots remain.
    assert snapshot_worker_limit(Pool()) == 1

    monkeypatch.setenv("STATIC_REPORT_SNAPSHOT_CONCURRENCY", "4")
    monkeypatch.setenv("STATIC_REPORT_DB_CONNECTION_RESERVE", "1")
    assert snapshot_worker_limit(Pool()) == 1


def test_static_report_work_mem_is_bounded_and_applied_locally(monkeypatch):
    from routers.static_reports.snapshot_builder import (
        configure_static_report_transaction,
        static_report_work_mem_mb,
    )

    class Connection:
        def __init__(self):
            self.sql = []

        async def execute(self, sql):
            self.sql.append(sql)

    monkeypatch.setenv("STATIC_REPORT_WORK_MEM_MB", "128")
    assert static_report_work_mem_mb() == 64
    conn = Connection()
    asyncio.run(configure_static_report_transaction(conn))
    assert conn.sql == ["SET LOCAL work_mem = '64MB'"]


def test_global_capacity_uses_a_session_lock_without_a_long_idle_transaction():
    from routers.static_reports.snapshot_builder import static_report_global_capacity

    events = []

    class Connection:
        async def fetchval(self, sql, namespace, slot):
            assert isinstance(namespace, int) and isinstance(slot, int)
            if "pg_try_advisory_lock" in sql:
                events.append("capacity:locked")
            else:
                assert "pg_advisory_unlock" in sql
                events.append("capacity:unlocked")
            return True

    class Acquire:
        async def __aenter__(self):
            events.append("connection:acquire")
            return Connection()

        async def __aexit__(self, *_args):
            events.append("connection:release")

    class Pool:
        def acquire(self):
            return Acquire()

    async def scenario():
        async with static_report_global_capacity(Pool()):
            events.append("body")

    asyncio.run(scenario())
    assert events == [
        "connection:acquire",
        "capacity:locked",
        "body",
        "capacity:unlocked",
        "connection:release",
    ]
from routers.insights._helpers import (
    inject_sov_zero_own_brand,
    inject_visibility_zero_own_brand,
    rank_visibility_entries,
)


def test_choose_rendering_mode_single_day():
    assert choose_rendering_mode(["2026-05-27"]) == RenderingMode.SINGLE_DAY


def test_choose_rendering_mode_multi_day():
    assert choose_rendering_mode(["2026-05-26", "2026-05-27"]) == RenderingMode.MULTI_DAY


def test_report_window_forces_multi_day_rendering():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 14),
        window_end=date(2026, 5, 27),
        window_days=14,
    )
    assert choose_report_rendering_mode(dates, ["2026-05-27"]) == RenderingMode.MULTI_DAY


def test_iter_window_dates_matches_selected_window():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 25),
        window_end=date(2026, 5, 27),
        window_days=3,
    )
    assert iter_window_dates(dates) == ["2026-05-25", "2026-05-26", "2026-05-27"]


def test_static_daily_series_use_null_for_missing_dates_like_dynamic_apis():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 25),
        window_end=date(2026, 5, 27),
        window_days=3,
    )
    visibility = build_visibility_daily_series(
        dates,
        [{"date": date(2026, 5, 26), "total": 2, "own_count": 1}],
    )
    citations = build_citation_daily_series(
        dates,
        [{"date": date(2026, 5, 26), "total_citations": 2, "own_citations": 1}],
    )
    sentiment = build_sentiment_daily_series(
        dates,
        [{"date": date(2026, 5, 26), "total_count": 2, "positive_count": 1, "negative_count": 1}],
    )

    assert [point["score"] for point in visibility] == [None, 50.0, None]
    assert [point["own_share"] for point in citations] == [None, 50.0, None]
    assert [point["positive_pct"] for point in sentiment] == [None, 50.0, None]
    assert visibility[0]["total"] == citations[0]["total_citations"] == sentiment[0]["total_count"] == 0

    previous_dates = compute_previous_report_dates(dates)
    previous_visibility = build_visibility_daily_series(previous_dates, [])
    previous_citations = build_citation_daily_series(previous_dates, [])
    previous_sentiment = build_sentiment_daily_series(previous_dates, [])
    assert all(point["score"] is None for point in previous_visibility)
    assert all(point["own_share"] is None for point in previous_citations)
    assert all(point["positive_pct"] is None for point in previous_sentiment)


def test_static_sentiment_v2_uses_three_way_rated_denominator_and_tracks_insufficient():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 27),
        window_end=date(2026, 5, 27),
        window_days=1,
    )
    result = build_sentiment_dashboard_from_aggregate_rows(
        [
            {"date": "2026-05-27", "sentiment": "Positive", "count": 3, "avg_confidence": 0.9},
            {"date": "2026-05-27", "sentiment": "Mixed/Neutral", "count": 4, "avg_confidence": 0.8},
            {"date": "2026-05-27", "sentiment": "Negative", "count": 2, "avg_confidence": 0.9},
            {"date": "2026-05-27", "sentiment": "Insufficient Evidence", "count": 1, "avg_confidence": 0.2},
        ],
        [],
        [],
        dates,
        comparison_only=False,
    )

    summary = result["summary"]
    assert summary["total_count"] == 10
    assert summary["rated_count"] == 9
    assert summary["positive_pct"] == 33.33
    assert summary["mixed_neutral_pct"] == 44.44
    assert summary["negative_pct"] == 22.22
    assert summary["insufficient_evidence_count"] == 1
    assert result["time_series"][0]["rated_count"] == 9
    assert len(result["response_source_rows"]) == 4
    assert result["response_source_rows_limited"] is False


def test_static_sentiment_queries_match_dynamic_active_prompt_scope():
    class Connection:
        def __init__(self):
            self.queries = []

        async def fetch(self, sql, *_args):
            self.queries.append(" ".join(sql.split()))
            return []

        cursor = _cursor_from_fake_fetch

    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 27),
        window_end=date(2026, 5, 27),
        window_days=1,
    )
    conn = Connection()

    asyncio.run(load_sentiment_period_rows(
        conn,
        "11111111-1111-1111-1111-111111111111",
        dates,
        ("Competitive",),
    ))

    assert len(conn.queries) == 3
    assert all("cp.is_active = TRUE" in query for query in conn.queries)
    summary_query = conn.queries[0]
    assert "cp.topic_id::text AS topic_id" in summary_query
    assert "cp.platform" in summary_query


def test_static_sentiment_v2_does_not_treat_insufficient_only_day_as_rated():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 27),
        window_end=date(2026, 5, 27),
        window_days=1,
    )

    series = build_sentiment_daily_series(dates, [{
        "date": date(2026, 5, 27),
        "total_count": 2,
        "rated_count": 0,
        "positive_count": 0,
        "mixed_neutral_count": 0,
        "negative_count": 0,
        "insufficient_evidence_count": 2,
    }])

    assert series[0]["rated_count"] == 0
    assert series[0]["positive_pct"] is None
    assert series[0]["mixed_neutral_pct"] is None
    assert series[0]["negative_pct"] is None


def test_visibility_rankings_inject_canonical_zero_own_brand_like_dynamic_api():
    entries = [{
            "company_name": "Peer",
            "brand_name": "Peer",
            "mention_count": 4,
            "sov_pct": 100.0,
            "visibility_pct": 100.0,
            "avg_position": 2.0,
            "is_own": False,
        }]
    visibility_entries = inject_visibility_zero_own_brand(entries, total_responses=2, own_brand_name="Own Brand")
    sov_entries = inject_sov_zero_own_brand(entries, total_mentions=4, own_brand_name="Own Brand")
    visibility_ranking = rank_visibility_entries(visibility_entries, "visibility_pct", reverse=True)
    sov_ranking = rank_visibility_entries(sov_entries, "mention_count", reverse=True)
    position_ranking = rank_visibility_entries(
        [entry for entry in entries if entry["avg_position"] is not None], "avg_position", reverse=False
    )

    own_sov = next(row for row in sov_ranking if row["is_own"])
    own_visibility = next(row for row in visibility_ranking if row["is_own"])
    assert (own_sov["brand_name"], own_sov["mention_count"], own_sov["rank"]) == ("Own Brand", 0, 2)
    assert (own_visibility["visibility_pct"], own_visibility["rank"]) == (0, 2)
    assert not any(row["is_own"] for row in position_ranking)


def test_visibility_rankings_do_not_inject_zero_own_without_responses():
    assert inject_visibility_zero_own_brand([], total_responses=0, own_brand_name="Own Brand") == []
    assert inject_sov_zero_own_brand([], total_mentions=0, own_brand_name="Own Brand") == []


def test_snapshot_filter_config_loads_enabled_intents_once_as_immutable_tuples():
    class ConfigConn:
        def __init__(self):
            self.queries = []

        async def fetch(self, sql, *_args):
            self.queries.append(sql)
            return [
                {"intent_name": "Discovery", "categories": ["Visibility", "Citation"]},
                {"intent_name": "Competitive", "categories": ["Visibility", "Sentiment"]},
                {"intent_name": "Disabled is excluded by SQL", "categories": ["Sentiment"]},
            ]

    conn = ConfigConn()
    config = asyncio.run(load_snapshot_filter_config(conn))

    assert len(conn.queries) == 1
    assert "is_active = TRUE" in conn.queries[0]
    assert config == SnapshotFilterConfig(
        visibility_intents=("Competitive", "Discovery"),
        citation_intents=("Discovery",),
        sentiment_intents=("Competitive", "Disabled is excluded by SQL"),
    )
    with pytest.raises(FrozenInstanceError):
        config.visibility_intents = ()


def test_previous_comparison_loaders_skip_outer_tables_examples_and_source_payloads(monkeypatch):
    class PreviousConn:
        def __init__(self):
            self.queries = []

        async def fetchrow(self, sql, *_args):
            self.queries.append(sql)
            if "AS total_mentions" in sql:
                return {"total_mentions": 0, "own_mentions": 0, "own_avg_position": None}
            if "AS total_responses" in sql:
                return {"total_responses": 0, "own_response_count": 0}
            if "geo_sentiment_results" in sql:
                return {"total": 0, "positive": 0, "negative": 0}
            raise AssertionError(sql)

        async def fetchval(self, sql, *_args):
            self.queries.append(sql)
            if "FROM geo_citations" in sql:
                return 0
            raise AssertionError(sql)

        async def fetch(self, sql, *_args):
            self.queries.append(sql)
            return []

        cursor = _cursor_from_fake_fetch

    async def reject_full_loader(*_args, **_kwargs):
        raise AssertionError("previous period must not call a full outer snapshot loader")

    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_visibility_snapshot", reject_full_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_citation_snapshot", reject_full_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_sentiment_snapshot", reject_full_loader)
    config = SnapshotFilterConfig(
        visibility_intents=("Discovery",),
        citation_intents=("Discovery",),
        sentiment_intents=("Discovery",),
    )
    dates = ReportDates(
        report_date=date(2026, 5, 24),
        window_start=date(2026, 5, 22),
        window_end=date(2026, 5, 24),
        window_days=3,
    )
    conn = PreviousConn()

    sections = asyncio.run(load_previous_sections(conn, "client-1", dates, config))

    assert set(sections) == {"visibility", "citations", "sentiment"}
    assert len(conn.queries) == 10
    sql = "\n".join(conn.queries)
    assert sum("GROUP BY (c.executed_at AT TIME ZONE $3)::date" in query for query in conn.queries) == 1
    assert "LIMIT 700" not in sql
    assert "LIMIT 1000" not in sql
    assert "st.excerpt" not in sql
    assert "GROUP BY COALESCE(c.domain_category" not in sql


def test_prompt_topic_totals_preaggregate_each_fact_table_before_joining():
    class Connection:
        def __init__(self):
            self.queries = []

        async def fetch(self, sql, *_args):
            self.queries.append(" ".join(sql.split()))
            return []

        cursor = _cursor_from_fake_fetch

    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 21),
        window_end=date(2026, 5, 27),
        window_days=7,
    )
    conn = Connection()

    asyncio.run(load_prompt_topic_snapshot(conn, "client-1", dates))

    prompt_totals, topic_totals = conn.queries[:2]
    assert "WITH mention_totals AS" in prompt_totals
    assert "citation_totals AS" in prompt_totals
    assert "COUNT(DISTINCT bm.id)" not in prompt_totals
    assert "COUNT(DISTINCT c.id)" not in prompt_totals
    assert "result_mentions AS" in topic_totals
    assert "result_citations AS" in topic_totals
    assert "LEFT JOIN geo_brand_mentions bm" not in topic_totals
    assert "LEFT JOIN geo_citations c" not in topic_totals


def test_bounded_aggregate_fetch_adds_a_guard_row_and_rejects_overflow(monkeypatch):
    class Cursor:
        def __init__(self, rows):
            self.rows = iter(rows)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.rows)
            except StopIteration:
                raise StopAsyncIteration

    class Connection:
        def __init__(self):
            self.sql = ""

        def cursor(self, sql, *_args, prefetch):
            assert prefetch >= 256
            self.sql = " ".join(sql.split())
            return Cursor([{"value": index} for index in range(4)])

    conn = Connection()
    monkeypatch.setattr(
        "routers.static_reports.snapshot_builder.MAX_STATIC_REPORT_AGGREGATE_ROWS",
        3,
    )

    with pytest.raises(RuntimeError, match="citation aggregate exceeds 3 rows"):
        asyncio.run(fetch_bounded_aggregate_rows(
            conn,
            "SELECT value FROM source_rows ORDER BY value",
            label="citation aggregate",
        ))

    assert "LIMIT 4" in conn.sql
    assert MAX_STATIC_REPORT_AGGREGATE_ROWS >= 25_000


def test_bounded_cursor_can_preserve_a_display_truncation_without_a_guard_failure():
    class Cursor:
        def __init__(self):
            self.index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.index >= 2:
                raise StopAsyncIteration
            self.index += 1
            return {"value": self.index}

    class Connection:
        def __init__(self):
            self.sql = ""

        def cursor(self, sql, *_args, prefetch):
            assert prefetch >= 256
            self.sql = " ".join(sql.split())
            return Cursor()

    conn = Connection()
    rows = asyncio.run(fetch_bounded_aggregate_rows(
        conn,
        "SELECT value FROM source_rows ORDER BY value",
        label="display rows",
        row_limit=2,
        truncate=True,
    ))

    assert rows == [{"value": 1}, {"value": 2}]
    assert "LIMIT 2" in conn.sql
    assert "LIMIT 3" not in conn.sql


def test_bounded_aggregate_fetch_rejects_cumulative_bytes_before_retaining_rows(monkeypatch):
    class Cursor:
        def __init__(self):
            self.index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.index >= 3:
                raise StopAsyncIteration
            self.index += 1
            return {"value": "x" * 20}

    class Connection:
        def cursor(self, _sql, *_args, prefetch):
            assert prefetch > 0
            return Cursor()

    monkeypatch.setattr(
        "routers.static_reports.snapshot_builder.MAX_STATIC_REPORT_AGGREGATE_BYTES",
        50,
    )

    with pytest.raises(RuntimeError, match="prompt aggregate exceeds 50 bytes"):
        asyncio.run(fetch_bounded_aggregate_rows(
            Connection(),
            "SELECT value FROM source_rows",
            label="prompt aggregate",
        ))

    assert MAX_STATIC_REPORT_AGGREGATE_BYTES >= 8 * 1024 * 1024


def test_visibility_complete_brand_queries_use_the_bounded_cursor_path():
    class EmptyCursor:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Connection:
        def __init__(self):
            self.fetch_queries = []
            self.cursor_queries = []

        async def fetchrow(self, _sql, *_args):
            return {}

        async def fetch(self, sql, *_args):
            self.fetch_queries.append(" ".join(sql.split()))
            return []

        def cursor(self, sql, *_args, prefetch):
            assert prefetch > 0
            self.cursor_queries.append(" ".join(sql.split()))
            return EmptyCursor()

    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 21),
        window_end=date(2026, 5, 27),
        window_days=7,
    )
    conn = Connection()

    asyncio.run(load_visibility_dashboard_snapshot(
        conn,
        "client-1",
        dates,
        ("Solution Discovery",),
    ))

    brand_queries = [query for query in conn.cursor_queries if "GROUP BY bm.brand_name" in query]
    assert len(brand_queries) == 2
    assert all("LIMIT 50001" in query for query in brand_queries)
    assert not any("GROUP BY bm.brand_name" in query for query in conn.fetch_queries)
    granular_queries = [query for query in conn.cursor_queries if "GROUP BY cp.topic_id" in query]
    assert len(granular_queries) == 1
    assert "LIMIT 100001" in granular_queries[0]
    assert MAX_STATIC_REPORT_VISIBILITY_GRANULAR_ROWS == 100_000
    assert MAX_STATIC_REPORT_VISIBILITY_GRANULAR_BYTES == 48 * 1024 * 1024


def test_build_snapshot_uses_one_exported_repeatable_read_snapshot_and_bounded_workers(monkeypatch):
    events = []
    config_calls = []
    received_intents = []

    class Transaction:
        def __init__(self, conn, isolation, readonly):
            self.conn = conn
            self.isolation = isolation
            self.readonly = readonly

        async def __aenter__(self):
            events.append(("transaction_enter", self.conn.name, self.isolation, self.readonly))
            return self

        async def __aexit__(self, exc_type, _exc, _tb):
            events.append(("transaction_rollback" if exc_type else "transaction_commit", self.conn.name))

    class Connection:
        def __init__(self, name):
            self.name = name
            self.snapshot_set = False

        def transaction(self, *, isolation, readonly):
            return Transaction(self, isolation, readonly)

        async def fetchval(self, sql, *_args):
            if "pg_try_advisory_xact_lock" in sql:
                events.append(("capacity_lock", self.name))
                return True
            assert sql.strip() == "SELECT pg_export_snapshot()"
            events.append(("export_snapshot", self.name))
            return "00000003-0000001B-1"

        async def execute(self, sql, *_args):
            if sql.startswith("SET LOCAL work_mem"):
                events.append(("work_mem", self.name))
                return
            assert sql == "SET TRANSACTION SNAPSHOT '00000003-0000001B-1'"
            self.snapshot_set = True
            events.append(("set_snapshot", self.name))

    class Acquire:
        def __init__(self, pool):
            self.pool = pool

        async def __aenter__(self):
            name = "coordinator" if self.pool.created == 0 else f"worker-{self.pool.created}"
            self.pool.created += 1
            self.conn = Connection(name)
            self.pool.active += 1
            self.pool.max_active = max(self.pool.max_active, self.pool.active)
            events.append(("acquire", name))
            return self.conn

        async def __aexit__(self, *_args):
            events.append(("release", self.conn.name))
            self.pool.active -= 1

    class Pool:
        def __init__(self):
            self.created = 0
            self.active = 0
            self.max_active = 0

        def acquire(self):
            return Acquire(self)

        def get_max_size(self):
            return 8

    config = SnapshotFilterConfig(
        visibility_intents=("Visibility intent",),
        citation_intents=("Citation intent",),
        sentiment_intents=("Sentiment intent",),
    )
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 25),
        window_end=date(2026, 5, 27),
        window_days=3,
    )
    frozen = empty_snapshot("client-1", "Client", dates, RenderingMode.MULTI_DAY, {})

    async def config_loader(conn):
        assert conn.name == "coordinator"
        config_calls.append(conn)
        events.append(("config", conn.name))
        return config

    async def stage_value(conn, value):
        assert conn.snapshot_set
        events.append(("loader", conn.name))
        await asyncio.sleep(0.01)
        return value

    async def client_loader(conn, _client_id):
        return await stage_value(conn, "Client")

    async def visibility_loader(conn, _client_id, _dates, intents):
        received_intents.append(intents)
        return await stage_value(conn, frozen["visibility"])

    async def citation_loader(conn, _client_id, _dates, _previous_dates, intents):
        received_intents.append(intents)
        return await stage_value(conn, {
            "current": frozen["citations"],
            "previous": frozen["citations"],
        })

    async def sentiment_loader(conn, _client_id, _dates, _previous_dates, intents):
        received_intents.append(intents)
        return await stage_value(conn, {
            "current": frozen["sentiment"],
            "previous": frozen["sentiment"],
        })

    async def prompt_loader(conn, _client_id, _dates):
        return await stage_value(conn, {"prompts": frozen["prompts"], "topics": frozen["topics"]})

    async def filter_loader(conn, _client_id):
        return await stage_value(conn, frozen["filters"])

    async def dates_loader(conn, _client_id, _dates):
        return await stage_value(conn, [])

    async def previous_loader(conn, _client_id, _dates, received_config):
        assert received_config is config
        received_intents.extend([
            received_config.visibility_intents,
        ])
        return await stage_value(conn, {
            "visibility": frozen["visibility"],
        })

    monkeypatch.setenv("STATIC_REPORT_SNAPSHOT_CONCURRENCY", "2")
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_snapshot_filter_config", config_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_client_name", client_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_visibility_snapshot", visibility_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_citation_period_snapshots", citation_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_sentiment_period_snapshots", sentiment_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_prompt_topic_snapshot", prompt_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_filter_options", filter_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_available_dates", dates_loader)
    monkeypatch.setattr("routers.static_reports.snapshot_builder.load_previous_visibility_section", previous_loader)

    pool = Pool()
    asyncio.run(build_snapshot(pool, "client-1", dates, {}))

    assert len(config_calls) == 1
    assert received_intents == [
        config.visibility_intents,
        config.citation_intents,
        config.sentiment_intents,
        config.visibility_intents,
    ]
    # build_snapshot owns one coordinator plus one worker; the outer global
    # capacity guard owns the third report connection in production.
    assert pool.max_active == 2
    assert events.index(("config", "coordinator")) < events.index(("export_snapshot", "coordinator"))
    transaction_entries = [event for event in events if event[0] == "transaction_enter"]
    assert all(event[2:] == ("repeatable_read", True) for event in transaction_entries)
    worker_loaders = [event for event in events if event[0] == "loader"]
    assert len(worker_loaders) == 8
    for _, worker_name in worker_loaders:
        assert events.index(("set_snapshot", worker_name)) < events.index(("loader", worker_name))


def test_snapshot_stage_failure_cancels_and_awaits_siblings_before_returning():
    events = []

    async def failing_stage():
        await asyncio.sleep(0)
        raise RuntimeError("stage failed")

    async def sibling_stage():
        try:
            await asyncio.sleep(60)
        finally:
            events.append("sibling cleaned up")

    async def run():
        with pytest.raises(RuntimeError, match="stage failed"):
            await gather_snapshot_stages([failing_stage(), sibling_stage()])
        events.append("gather returned")

    asyncio.run(run())
    assert events == ["sibling cleaned up", "gather returned"]


def test_static_visibility_loader_fills_null_dates_and_injects_zero_own_row():
    class VisibilityConn:
        async def fetchrow(self, sql, *_args):
            if "AS total_mentions" in sql:
                return {"total_mentions": 4, "own_mentions": 0, "own_avg_position": None}
            if "AS total_responses" in sql:
                return {"total_responses": 2, "own_response_count": 0}
            if "FROM geo_client_brands" in sql:
                return {"brand_name": "Own Brand"}
            raise AssertionError(sql)

        async def fetch(self, sql, *_args):
            if "SELECT bm.brand_name," in sql and "COUNT(DISTINCT gr.result_id)" not in sql:
                return [{"brand_name": "Mention Peer", "mention_count": 4, "is_own": 0, "avg_position": 2.0}]
            if "SELECT bm.brand_name," in sql and "COUNT(DISTINCT gr.result_id)" in sql:
                return [{"brand_name": "Response Peer", "response_count": 1, "mention_count": 1, "is_own": 0}]
            if "AS total_response_count" in sql:
                return []
            if "AS company_name" in sql:
                return []
            if "COUNT(DISTINCT gr.result_id)::int AS total" in sql:
                return [{"date": date(2026, 5, 26), "total": 2, "own_count": 0}]
            if "AS avg_position" in sql:
                return []
            raise AssertionError(sql)

        cursor = _cursor_from_fake_fetch

    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 25),
        window_end=date(2026, 5, 27),
        window_days=3,
    )
    dashboard = asyncio.run(load_visibility_dashboard_snapshot(
        VisibilityConn(), "client-1", dates, ["Solution Discovery"]
    ))

    own = next(row for row in dashboard["sov_ranking"] if row["is_own"])
    assert (own["brand_name"], own["rank"], dashboard["summary"]["sov_rank"]) == ("Own Brand", 2, 2)
    own_visibility = next(row for row in dashboard["visibility_ranking"] if row["is_own"])
    assert (own_visibility["brand_name"], dashboard["summary"]["visibility_rank"]) == ("Own Brand", 2)
    assert {row["brand_name"] for row in dashboard["sov_ranking"]} == {"Mention Peer", "Own Brand"}
    assert {row["brand_name"] for row in dashboard["visibility_ranking"]} == {"Response Peer", "Own Brand"}
    assert not any(row["is_own"] for row in dashboard["position_ranking"])
    assert dashboard["summary"]["avg_position_rank"] is None
    assert [point["score"] for point in dashboard["time_series"]] == [None, 0.0, None]


def test_static_visibility_current_and_previous_windows_keep_exact_rank_changes_and_no_position_row():
    class WindowedVisibilityConn:
        def __init__(self):
            self.window_starts = []

        async def fetchrow(self, sql, *_args):
            if "FROM geo_client_brands" in sql:
                return {"brand_name": "Own Brand"}
            window_start = _args[1]
            self.window_starts.append(window_start)
            is_current = window_start == date(2026, 5, 25)
            if "AS total_mentions" in sql:
                return (
                    {"total_mentions": 4, "own_mentions": 0, "own_avg_position": None}
                    if is_current else
                    {"total_mentions": 3, "own_mentions": 2, "own_avg_position": 3.0}
                )
            if "AS total_responses" in sql:
                return (
                    {"total_responses": 2, "own_response_count": 0}
                    if is_current else
                    {"total_responses": 3, "own_response_count": 2}
                )
            raise AssertionError(sql)

        async def fetch(self, sql, *_args):
            window_start = _args[1]
            self.window_starts.append(window_start)
            is_current = window_start == date(2026, 5, 25)
            if "SELECT bm.brand_name," in sql and "COUNT(DISTINCT gr.result_id)" not in sql:
                if is_current:
                    return [{"brand_name": "Mention Peer", "mention_count": 4, "is_own": 0, "avg_position": 2.0}]
                return [
                    {"brand_name": "Own Brand", "mention_count": 2, "is_own": 1, "avg_position": 3.0},
                    {"brand_name": "Mention Peer", "mention_count": 1, "is_own": 0, "avg_position": 2.0},
                ]
            if "SELECT bm.brand_name," in sql and "COUNT(DISTINCT gr.result_id)" in sql:
                if is_current:
                    return [{"brand_name": "Response Peer", "response_count": 1, "mention_count": 1, "is_own": 0}]
                return [
                    {"brand_name": "Own Brand", "response_count": 2, "mention_count": 2, "is_own": 1},
                    {"brand_name": "Response Peer", "response_count": 1, "mention_count": 1, "is_own": 0},
                ]
            if "COUNT(DISTINCT gr.result_id)::int AS total" in sql:
                return []
            if "AS total_response_count" in sql or "AS company_name" in sql or "AS avg_position" in sql:
                return []
            raise AssertionError(sql)

        cursor = _cursor_from_fake_fetch

    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 25),
        window_end=date(2026, 5, 27),
        window_days=3,
    )
    previous_dates = compute_previous_report_dates(dates)
    conn = WindowedVisibilityConn()
    current_dashboard = asyncio.run(load_visibility_dashboard_snapshot(conn, "client-1", dates, ["Solution Discovery"]))
    previous_dashboard = asyncio.run(
        load_visibility_dashboard_snapshot(conn, "client-1", previous_dates, ["Solution Discovery"])
    )

    current, previous = _comparison_sections()
    current["visibility"]["dashboard"] = current_dashboard
    previous["visibility"]["dashboard"] = previous_dashboard
    materialize_previous_period(current, previous)

    summary = current_dashboard["summary"]
    assert (summary["visibility_rank"], summary["visibility_rank_change"]) == (2, 1)
    assert (summary["sov_rank"], summary["sov_rank_change"]) == (2, 1)
    assert summary["avg_position_rank"] is None
    assert summary["avg_position_rank_change"] is None
    assert not any(row["is_own"] for row in current_dashboard["position_ranking"])
    assert previous_dashboard["summary"]["avg_position_rank"] == 2
    assert set(conn.window_starts) == {date(2026, 5, 22), date(2026, 5, 25)}


def test_empty_snapshot_has_required_sections():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 21),
        window_end=date(2026, 5, 27),
    )
    snapshot = empty_snapshot("client-1", "Roborock", dates, RenderingMode.SINGLE_DAY, {})
    assert snapshot["version"] == SNAPSHOT_VERSION
    assert snapshot["client"]["name"] == "Roborock"
    assert snapshot["report"]["window_days"] == 7
    assert "visibility" in snapshot
    assert "citations" in snapshot
    assert "sentiment" in snapshot
    assert snapshot["filters"] == {"topics": [], "platforms": []}
    assert "available_dates" in snapshot["report"]


def test_empty_snapshot_prepares_dashboard_compatible_sections():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 27),
        window_end=date(2026, 5, 27),
    )
    snapshot = empty_snapshot("client-1", "Roborock", dates, RenderingMode.SINGLE_DAY, {})
    assert "dashboard" in snapshot["visibility"]
    assert "dashboard" in snapshot["citations"]
    assert "dashboard" in snapshot["sentiment"]
    assert "time_series" in snapshot["visibility"]["dashboard"]
    assert "avg_position_series" in snapshot["visibility"]["dashboard"]
    assert "time_series" in snapshot["citations"]["dashboard"]
    assert "time_series" in snapshot["sentiment"]["dashboard"]


def test_empty_snapshot_prepares_visibility_dashboard_trend_slots():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 14),
        window_end=date(2026, 5, 27),
        window_days=14,
    )
    snapshot = empty_snapshot("client-1", "Roborock", dates, RenderingMode.MULTI_DAY, {})
    dashboard = snapshot["visibility"]["dashboard"]
    assert "time_series" in dashboard
    assert "avg_position_series" in dashboard


def test_empty_snapshot_prepares_citation_and_sentiment_trend_slots():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 14),
        window_end=date(2026, 5, 27),
        window_days=14,
    )
    snapshot = empty_snapshot("client-1", "Roborock", dates, RenderingMode.MULTI_DAY, {})
    assert "time_series" in snapshot["citations"]["dashboard"]
    assert "time_series" in snapshot["sentiment"]["dashboard"]


def _comparison_sections():
    current = {
        "visibility": {"dashboard": {
            "summary": {
                "visibility_score": 60.0, "visibility_rank": 2,
                "sov_pct": 30.0, "sov_rank": 3,
                "total_query": 10, "total_mentions": 20,
                "avg_position": 4.0, "avg_position_rank": 2,
            },
            "sov_ranking": [{"brand_name": "Own", "sov_pct": 30.0}],
            "visibility_ranking": [{"brand_name": "Own", "visibility_pct": 60.0}],
            "time_series": [{"date": "2026-05-27", "score": 60.0}],
            "avg_position_series": [{"date": "2026-05-27", "avg_position": 4.0}],
        }},
        "citations": {"dashboard": {
            "summary": {"total_citations": 20, "own_domain_share": 25.0, "own_rank": 2},
            "domain_ranking": [{"domain": "own.test", "share_pct": 25.0}],
            "page_ranking": [{"url": "https://own.test/a", "share_pct": 10.0}],
            "time_series": [{"date": "2026-05-27", "own_share": 25.0}],
        }},
        "sentiment": {"dashboard": {
            "summary": {"positive_pct": 70.0, "total_count": 10},
            "themes": [{"theme_name": "Quality", "sentiment": "Positive", "occurrence_count": 7}],
            "time_series": [{"date": "2026-05-27", "positive_pct": 70.0}],
        }},
    }
    previous = {
        "visibility": {"dashboard": {
            "summary": {
                "visibility_score": 50.0, "visibility_rank": 4,
                "sov_pct": 20.0, "sov_rank": 5,
                "total_query": 10, "total_mentions": 20,
                "avg_position": 6.0, "avg_position_rank": 4,
            },
            "sov_ranking": [{"brand_name": "Own", "sov_pct": 20.0}],
            "visibility_ranking": [{"brand_name": "Own", "visibility_pct": 50.0}],
            "time_series": [{"date": "2026-05-20", "score": 50.0}],
            "avg_position_series": [{"date": "2026-05-20", "avg_position": 6.0}],
        }},
        "citations": {"dashboard": {
            "summary": {"total_citations": 10, "own_domain_share": 20.0, "own_rank": 4},
            "domain_ranking": [{"domain": "own.test", "share_pct": 20.0}],
            "page_ranking": [{"url": "https://own.test/a", "share_pct": 5.0}],
            "time_series": [{"date": "2026-05-20", "own_share": 20.0}],
        }},
        "sentiment": {"dashboard": {
            "summary": {"positive_pct": 40.0, "total_count": 10},
            "themes": [{"theme_name": "Quality", "sentiment": "Positive", "occurrence_count": 4}],
            "time_series": [{"date": "2026-05-20", "positive_pct": 40.0}],
        }},
    }
    return current, previous


def test_previous_period_materialization_uses_percentage_points_and_rank_direction():
    current, previous = _comparison_sections()
    warnings = materialize_previous_period(current, previous)

    visibility = current["visibility"]["dashboard"]
    assert visibility["summary"]["visibility_score_change"] == 10.0
    assert visibility["summary"]["visibility_rank_change"] == -2
    assert visibility["summary"]["sov_pct_change"] == 10.0
    assert visibility["summary"]["sov_rank_change"] == -2
    assert visibility["summary"]["avg_position_change"] == -2.0
    assert visibility["summary"]["avg_position_rank_change"] == -2
    assert visibility["prev_time_series"] == previous["visibility"]["dashboard"]["time_series"]
    assert visibility["prev_avg_position_series"] == previous["visibility"]["dashboard"]["avg_position_series"]
    assert visibility["previous"]["summary"]["visibility_score"] == 50.0

    citations = current["citations"]["dashboard"]
    assert citations["summary"]["own_domain_share_change"] == 5.0
    assert citations["summary"]["own_rank_change"] == -2
    assert citations["domain_ranking"][0]["change_pct"] == 5.0
    assert citations["page_ranking"][0]["change_pct"] == 5.0
    assert citations["previous"]["summary"]["own_domain_share"] == 20.0

    sentiment = current["sentiment"]["dashboard"]
    assert sentiment["summary"]["positive_pct_change"] == 30.0
    assert sentiment["themes"][0]["prev_occurrence_count"] == 4
    assert sentiment["themes"][0]["occurrence_change"] == 3
    assert sentiment["previous"]["summary"]["positive_pct"] == 40.0
    assert warnings == []


def test_zero_previous_baseline_matches_dynamic_dashboard_percentage_point_formulas():
    current, previous = _comparison_sections()
    previous["visibility"]["dashboard"]["summary"].update({
        "total_query": 10,
        "total_mentions": 0,
        "visibility_score": 0.0,
        "sov_pct": 0.0,
        "avg_position": None,
        "visibility_rank": None,
        "sov_rank": None,
        "avg_position_rank": None,
    })
    previous["citations"]["dashboard"]["summary"].update({
        "total_citations": 10,
        "own_domain_share": 0.0,
        "own_rank": None,
    })
    previous["sentiment"]["dashboard"]["summary"].update({
        "total_count": 10,
        "positive_pct": 0.0,
    })
    previous["visibility"]["dashboard"]["sov_ranking"] = []
    previous["visibility"]["dashboard"]["visibility_ranking"] = []
    previous["citations"]["dashboard"]["domain_ranking"] = []
    previous["citations"]["dashboard"]["page_ranking"] = []
    previous["sentiment"]["dashboard"]["themes"] = []

    warnings = materialize_previous_period(current, previous)

    visibility = current["visibility"]["dashboard"]["summary"]
    assert visibility["visibility_score_change"] == 60.0
    assert visibility["sov_pct_change"] == 30.0
    assert visibility["visibility_rank_change"] is None
    assert visibility["sov_rank_change"] is None
    assert visibility["avg_position_change"] is None
    assert visibility["avg_position_rank_change"] is None
    assert current["citations"]["dashboard"]["summary"]["own_domain_share_change"] == 25.0
    assert current["citations"]["dashboard"]["summary"]["own_rank_change"] is None
    assert current["citations"]["dashboard"]["domain_ranking"][0]["change_pct"] is None
    assert current["citations"]["dashboard"]["page_ranking"][0]["change_pct"] is None
    assert current["visibility"]["dashboard"]["sov_ranking"][0]["sov_pct_change"] is None
    assert current["visibility"]["dashboard"]["visibility_ranking"][0]["visibility_pct_change"] is None
    assert current["sentiment"]["dashboard"]["summary"]["positive_pct_change"] == 70.0
    assert current["sentiment"]["dashboard"]["themes"][0]["occurrence_change"] == 7
    assert warnings == []


def test_empty_previous_windows_are_missing_not_zero_metric_baselines():
    current, previous = _comparison_sections()
    previous["visibility"]["dashboard"]["summary"].update({
        "total_query": 0,
        "total_mentions": 0,
        "visibility_score": 0.0,
        "sov_pct": 0.0,
        "avg_position": None,
    })
    previous["citations"]["dashboard"]["summary"].update({
        "total_citations": 0,
        "own_domain_share": 0.0,
    })
    previous["sentiment"]["dashboard"]["summary"].update({
        "total_count": 0,
        "positive_pct": 0.0,
    })

    warnings = materialize_previous_period(current, previous)

    assert current["visibility"]["dashboard"]["summary"]["visibility_score_change"] is None
    assert current["visibility"]["dashboard"]["summary"]["sov_pct_change"] is None
    assert current["citations"]["dashboard"]["summary"]["own_domain_share_change"] is None
    assert current["sentiment"]["dashboard"]["summary"]["positive_pct_change"] is None
    assert warnings == [
        "previous_period_visibility_missing",
        "previous_period_citation_missing",
        "previous_period_sentiment_missing",
    ]


def test_missing_previous_baseline_materializes_null_changes_and_warnings():
    current, previous = _comparison_sections()
    previous["visibility"]["dashboard"]["summary"] = {}
    previous["visibility"]["dashboard"]["sov_ranking"] = []
    previous["visibility"]["dashboard"]["visibility_ranking"] = []
    previous["citations"]["dashboard"]["summary"] = {}
    previous["citations"]["dashboard"]["domain_ranking"] = []
    previous["citations"]["dashboard"]["page_ranking"] = []
    previous["sentiment"]["dashboard"]["summary"] = {}
    previous["sentiment"]["dashboard"]["themes"] = []

    warnings = materialize_previous_period(current, previous)

    assert current["visibility"]["dashboard"]["summary"]["visibility_score_change"] is None
    assert current["visibility"]["dashboard"]["summary"]["sov_pct_change"] is None
    assert current["citations"]["dashboard"]["summary"]["own_domain_share_change"] is None
    assert current["sentiment"]["dashboard"]["summary"]["positive_pct_change"] is None
    assert current["sentiment"]["dashboard"]["themes"][0]["occurrence_change"] is None
    assert warnings == [
        "previous_period_visibility_missing",
        "previous_period_citation_missing",
        "previous_period_sentiment_missing",
    ]


def test_previous_lookup_covers_rows_outside_previous_display_page():
    current, previous = _comparison_sections()
    previous["visibility"]["dashboard"]["sov_ranking"] = []
    previous["visibility"]["dashboard"]["_sov_pct_lookup"] = {"Own": 20.0}
    previous["citations"]["dashboard"]["domain_ranking"] = []
    previous["citations"]["dashboard"]["page_ranking"] = []
    current["citations"]["dashboard"]["page_ranking"][0]["domain"] = "own.test"
    previous["citations"]["dashboard"]["_domain_share_lookup"] = {"own.test": 20.0}
    previous["citations"]["dashboard"]["_page_share_lookup"] = {"https://own.test/a\u001fown.test": 5.0}
    previous["sentiment"]["dashboard"]["themes"] = []
    previous["sentiment"]["dashboard"]["_theme_occurrence_lookup"] = {"Quality\u001fPositive": 4}

    materialize_previous_period(current, previous)

    assert current["visibility"]["dashboard"]["sov_ranking"][0]["sov_pct_change"] == 10.0
    assert current["citations"]["dashboard"]["domain_ranking"][0]["change_pct"] == 5.0
    assert current["citations"]["dashboard"]["page_ranking"][0]["change_pct"] == 5.0
    assert current["sentiment"]["dashboard"]["themes"][0]["occurrence_change"] == 3


def test_previous_period_matches_visibility_and_sentiment_by_complete_composite_keys():
    current, previous = _comparison_sections()
    current_visibility = current["visibility"]["dashboard"]
    previous_visibility = previous["visibility"]["dashboard"]
    current_visibility["_complete_visibility_ranking"] = [
        *current_visibility["visibility_ranking"],
        {"brand_name": "Outside Page", "visibility_pct": 30.0},
    ]
    previous_visibility["_complete_visibility_ranking"] = [
        *previous_visibility["visibility_ranking"],
        {"brand_name": "Outside Page", "visibility_pct": 20.0},
    ]
    current["sentiment"]["dashboard"]["_complete_themes"] = [
        {"theme_name": "Quality", "sentiment": "Positive", "occurrence_count": 7},
        {"theme_name": "Quality", "sentiment": "Negative", "occurrence_count": 2},
    ]
    previous["sentiment"]["dashboard"]["_theme_occurrence_lookup"] = {
        "Quality\u001fPositive": 4,
        "Quality\u001fNegative": 1,
    }

    materialize_previous_period(current, previous)

    assert current_visibility["_complete_visibility_ranking"][1]["visibility_pct_change"] == 10.0
    assert [
        (row["prev_occurrence_count"], row["occurrence_change"])
        for row in current["sentiment"]["dashboard"]["_complete_themes"]
    ] == [(4, 3), (1, 1)]


def test_legacy_empty_snapshot_comparison_fields_remain_absent_instead_of_live_fallback():
    dates = ReportDates(
        report_date=date(2026, 5, 27),
        window_start=date(2026, 5, 21),
        window_end=date(2026, 5, 27),
    )
    snapshot = empty_snapshot("client-1", "Roborock", dates, RenderingMode.MULTI_DAY, {})
    assert snapshot["visibility"]["dashboard"].get("prev_time_series", []) == []
    assert snapshot["citations"]["dashboard"].get("prev_time_series", []) == []
    assert snapshot["sentiment"]["dashboard"].get("prev_time_series", []) == []


def test_citation_domain_ranking_matches_static_report_first_page_scope():
    rows = [
        {"source_domain": f"domain-{index}.com", "citation_count": 100 - index, "domain_category": "Other"}
        for index in range(60)
    ]
    rows.append({"source_domain": "own.example", "citation_count": 1, "domain_category": "Owned Media"})

    ranking, own_count, own_rank = build_citation_domain_ranking(rows, {"own.example"}, total_citations=5000)

    assert len(ranking) == 20
    assert ranking[-1]["rank"] == 20
    assert own_count == 1
    assert own_rank == 61


def test_citation_own_rank_uses_competition_rank_for_ties():
    rows = [
        {"source_domain": "first.example", "citation_count": 50, "domain_category": "Other"},
        {"source_domain": "second.example", "citation_count": 40, "domain_category": "Other"},
        {"source_domain": "own.example", "citation_count": 40, "domain_category": "Owned Media"},
        {"source_domain": "third.example", "citation_count": 40, "domain_category": "Other"},
    ]

    _ranking, own_count, own_rank = build_citation_domain_ranking(rows, {"own.example"}, total_citations=170)

    assert own_count == 40
    assert own_rank == 2


def test_citation_category_breakdown_uses_full_universe_scope():
    category_rows = [
        {"domain_category": "Owned Media", "citation_count": 30},
        {"domain_category": "Social Media", "citation_count": 20},
    ]

    breakdown = build_citation_category_breakdown(category_rows, total_citations=50)

    assert breakdown == [
        {"label": "Owned Media", "count": 30, "pct": 60.0},
        {"label": "Social Media", "count": 20, "pct": 40.0},
    ]


def test_static_report_source_rows_have_hard_limit():
    assert STATIC_REPORT_SOURCE_ROW_LIMIT <= 5000


def test_row_to_dict_normalizes_json_fields():
    row = {
        "snapshot_json": '{"version": "x"}',
        "data_completeness": '{"raw_results": 3}',
        "warnings": '["single_day_report"]',
    }
    data = row_to_dict(row)
    assert data["snapshot_json"]["version"] == "x"
    assert data["data_completeness"]["raw_results"] == 3
    assert data["warnings"] == ["single_day_report"]
