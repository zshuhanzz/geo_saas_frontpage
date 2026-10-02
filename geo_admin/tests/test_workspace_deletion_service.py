from __future__ import annotations

import pytest

from services import workspace_deletion


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_cascade_footprint_budget_uses_default_clamps_bounds_and_recovers_invalid(monkeypatch):
    monkeypatch.delenv(workspace_deletion.CASCADE_FOOTPRINT_LIMIT_ENV, raising=False)
    assert (
        workspace_deletion.get_cascade_footprint_limit()
        == workspace_deletion.DEFAULT_CASCADE_FOOTPRINT_LIMIT
    )

    monkeypatch.setenv(workspace_deletion.CASCADE_FOOTPRINT_LIMIT_ENV, "1")
    assert (
        workspace_deletion.get_cascade_footprint_limit()
        == workspace_deletion.MIN_CASCADE_FOOTPRINT_LIMIT
    )

    monkeypatch.setenv(workspace_deletion.CASCADE_FOOTPRINT_LIMIT_ENV, "999999999")
    assert (
        workspace_deletion.get_cascade_footprint_limit()
        == workspace_deletion.MAX_CASCADE_FOOTPRINT_LIMIT
    )

    monkeypatch.setenv(workspace_deletion.CASCADE_FOOTPRINT_LIMIT_ENV, "not-an-int")
    assert (
        workspace_deletion.get_cascade_footprint_limit()
        == workspace_deletion.DEFAULT_CASCADE_FOOTPRINT_LIMIT
    )


class _Conn:
    def __init__(self, existing: set[str], counts: dict[str, int]):
        self.existing = existing
        self.counts = counts
        self.fetch_calls = []
        self.fetchval_calls = []
        self.execute_calls = []

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return [{"tablename": name} for name in sorted(self.existing)]

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        for name, query in workspace_deletion.WORKSPACE_CASCADE_COUNT_QUERIES.items():
            if query == sql:
                return self.counts.get(name, 0)
        for name, query in workspace_deletion.WORKSPACE_ACTIVE_COUNT_QUERIES.items():
            if query == sql:
                return self.counts.get(name, 0)
        raise AssertionError(f"unexpected SQL: {sql}")

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        return "DELETE 1"


@pytest.mark.anyio
async def test_footprint_counts_only_existing_real_tables_and_every_query_is_tenant_scoped():
    existing = {
        "geo_static_reports",
        "geo_static_report_list_rows",
        "agent_sessions",
        "agent_messages",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "geo_agent_tasks",
        "geo_content_assets",
        "geo_published_urls",
        "geo_published_url_topics",
        "geo_client_user_access",
        "geo_user_audit_events",
        "geo_report_templates",
    }
    counts = {name: index for index, name in enumerate(sorted(existing), start=1)}
    conn = _Conn(existing, counts)

    footprint = await workspace_deletion.load_workspace_cascade_footprint(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )

    assert footprint.by_table == counts
    assert footprint.total_rows == sum(counts.values())
    assert footprint.present_tables == frozenset(existing)
    queried_sql = {sql for sql, _ in conn.fetchval_calls}
    assert queried_sql == {
        workspace_deletion.WORKSPACE_CASCADE_COUNT_QUERIES[name] for name in existing
    }
    assert all(
        args == ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",)
        for _, args in conn.fetchval_calls
    )
    for name in existing:
        sql = workspace_deletion.WORKSPACE_CASCADE_COUNT_QUERIES[name]
        assert "$1::uuid" in sql
    assert "geo_tasks" not in workspace_deletion.WORKSPACE_CASCADE_COUNT_QUERIES
    assert "geo_results" not in workspace_deletion.WORKSPACE_CASCADE_COUNT_QUERIES
    assert "geo_citations" not in workspace_deletion.WORKSPACE_CASCADE_COUNT_QUERIES


@pytest.mark.anyio
async def test_non_cascading_cleanup_is_exactly_scoped_and_skips_absent_tables():
    existing = {
        "agent_sessions",
        "checkpoint_writes",
        "checkpoint_blobs",
        "checkpoints",
        "geo_agent_tasks",
        "geo_report_templates",
        "geo_settings_candidates",
    }
    conn = _Conn(existing, {})

    await workspace_deletion.delete_non_cascading_workspace_residuals(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        existing,
    )

    assert [sql for sql, _ in conn.execute_calls] == [
        workspace_deletion.NON_CASCADING_DELETE_QUERIES[name]
        for name in workspace_deletion.NON_CASCADING_DELETE_ORDER
        if name in existing
    ]
    assert all(
        args == ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",)
        for _, args in conn.execute_calls
    )
    assert all("$1::uuid" in sql for sql, _ in conn.execute_calls)


@pytest.mark.anyio
async def test_active_work_inventory_is_catalog_aware_and_tenant_scoped():
    existing = {
        "geo_agent_tasks",
        "geo_static_reports",
        "geo_prompt_import_batches",
    }
    counts = {name: index for index, name in enumerate(sorted(existing), start=1)}
    conn = _Conn(existing, counts)

    active = await workspace_deletion.load_workspace_active_work(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )

    assert active.by_table == counts
    assert active.total_items == sum(counts.values())
    assert {sql for sql, _ in conn.fetchval_calls} == {
        workspace_deletion.WORKSPACE_ACTIVE_COUNT_QUERIES[name] for name in existing
    }
    assert all(
        args == ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",)
        for _, args in conn.fetchval_calls
    )
    assert "status = 'RUNNING'" in workspace_deletion.WORKSPACE_ACTIVE_COUNT_QUERIES["geo_agent_tasks"]
    assert "status = 'MATERIALIZING'" in workspace_deletion.WORKSPACE_ACTIVE_COUNT_QUERIES["geo_static_reports"]
