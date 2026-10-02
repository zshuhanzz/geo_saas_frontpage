from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi import HTTPException

from routers import clients
from services import workspace_deletion


CLIENT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CLIENT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _count_row(client_id: UUID = CLIENT_A, **overrides):
    row = {
        "id": client_id,
        "name": "AnswerX",
        "cron_collector": None,
        "cron_analyzer": None,
        "cron_llm_discovery": None,
        "topics": 0,
        "logical_prompts": 0,
        "physical_prompts": 0,
        "tasks": 0,
        "results": 0,
        "citations": 0,
        "brand_mentions": 0,
        "product_mentions": 0,
        "sentiment_results": 0,
        "sentiment_themes": 0,
        "static_reports": 0,
        "agent_tasks": 0,
        "published_urls": 0,
    }
    row.update(overrides)
    return row


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ReadTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ReadConn:
    def __init__(self, row, *, existing_tables=None, footprint_counts=None, active_counts=None, lifecycle_available=True):
        self.row = row
        self.existing_tables = set(existing_tables or [])
        self.footprint_counts = dict(footprint_counts or {})
        self.active_counts = dict(active_counts or {})
        self.lifecycle_available = lifecycle_available
        self.fetchrow_calls = []
        self.fetch_calls = []
        self.fetchval_calls = []
        self.execute_calls = []

    def transaction(self):
        return _ReadTx()

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        return self.row

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        return "UPDATE 1"

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        if "pg_try_advisory_xact_lock" in sql:
            return self.lifecycle_available
        if "SELECT EXISTS" in sql:
            return True
        for table_name, query in workspace_deletion.WORKSPACE_CASCADE_COUNT_QUERIES.items():
            if query == sql:
                return self.footprint_counts.get(table_name, 0)
        for table_name, query in workspace_deletion.WORKSPACE_ACTIVE_COUNT_QUERIES.items():
            if query == sql:
                return self.active_counts.get(table_name, 0)
        return None

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return [{"tablename": name} for name in sorted(self.existing_tables)]


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


async def _scheduler_states(client_id: str, job_type: str):
    assert client_id == str(CLIENT_A)
    return {
        "collector": {"state": "NOT_FOUND"},
        "analyzer": {"state": "PAUSED"},
        "llm_discovery": {"state": "DISABLED"},
    }[job_type]


@pytest.mark.anyio
async def test_readiness_returns_all_tenant_counts_and_three_stopped_schedulers(monkeypatch):
    row = _count_row(
        topics=2,
        logical_prompts=3,
        physical_prompts=12,
        tasks=40,
        results=30,
        citations=20,
        brand_mentions=10,
        product_mentions=9,
        sentiment_results=8,
        sentiment_themes=7,
        static_reports=6,
        agent_tasks=5,
        published_urls=4,
    )
    conn = _ReadConn(row)
    monkeypatch.setattr(clients, "get_scheduler_job_status", _scheduler_states, raising=False)

    result = await clients.get_deletion_readiness(CLIENT_A, pool=_Pool(conn))

    assert result.workspace.id == str(CLIENT_A)
    assert result.workspace.name == "AnswerX"
    assert result.counts.model_dump() == {
        key: int(value) for key, value in row.items()
        if key not in {"id", "name", "cron_collector", "cron_analyzer", "cron_llm_discovery"}
    }
    assert all(state["stopped"] for state in result.schedulers.model_dump().values())
    assert result.recommended_next_action == "DELETE_PROMPTS"
    assert result.can_finalize is False
    assert {blocker.code for blocker in result.blockers} == {"PROMPTS_REMAIN", "TOPICS_REMAIN"}

    sql, args = conn.fetchrow_calls[0]
    assert args == (str(CLIENT_A),)
    for table in (
        "geo_client_topics", "geo_client_prompts", "geo_tasks", "geo_results",
        "geo_citations", "geo_brand_mentions", "geo_product_mentions",
        "geo_sentiment_results", "geo_sentiment_themes", "geo_static_reports",
        "geo_agent_tasks", "geo_published_urls",
    ):
        assert f"{table} WHERE client_id = $1::uuid" in sql


@pytest.mark.anyio
async def test_readiness_marks_active_schedule_as_first_action(monkeypatch):
    row = _count_row(cron_collector="0 1 * * *")

    async def statuses(client_id: str, job_type: str):
        return {"state": "ENABLED" if job_type == "collector" else "NOT_FOUND"}

    monkeypatch.setattr(clients, "get_scheduler_job_status", statuses, raising=False)
    result = await clients.get_deletion_readiness(CLIENT_A, pool=_Pool(_ReadConn(row)))

    assert result.schedulers.collector.stopped is False
    assert result.recommended_next_action == "STOP_SCHEDULING"
    assert result.can_finalize is False
    assert result.blockers[0].code == "SCHEDULERS_RUNNING"


@pytest.mark.anyio
async def test_readiness_blocks_orphan_facts_for_internal_repair(monkeypatch):
    monkeypatch.setattr(clients, "get_scheduler_job_status", _scheduler_states, raising=False)
    result = await clients.get_deletion_readiness(
        CLIENT_A,
        pool=_Pool(_ReadConn(_count_row(results=13, citations=2))),
    )

    assert result.recommended_next_action == "INTERNAL_DATA_REPAIR"
    assert result.can_finalize is False
    blocker = next(item for item in result.blockers if item.code == "ORPHANED_FACTS")
    assert blocker.count == 15
    assert "internal" in blocker.message.lower()


@pytest.mark.anyio
async def test_readiness_blocks_abnormally_large_residual_cascade(monkeypatch):
    monkeypatch.setattr(clients, "get_scheduler_job_status", _scheduler_states, raising=False)
    limit = workspace_deletion.DEFAULT_CASCADE_FOOTPRINT_LIMIT
    result = await clients.get_deletion_readiness(
        CLIENT_A,
        pool=_Pool(
            _ReadConn(
                _count_row(agent_tasks=limit + 1),
                existing_tables={"geo_agent_tasks"},
                footprint_counts={"geo_agent_tasks": limit + 1},
            )
        ),
    )

    assert result.recommended_next_action == "INTERNAL_DATA_REPAIR"
    assert result.can_finalize is False
    blocker = next(item for item in result.blockers if item.code == "CASCADE_FOOTPRINT_TOO_LARGE")
    assert blocker.count == limit + 1
    assert result.cascade_footprint.total_rows == limit + 1
    assert result.cascade_footprint.max_rows == limit
    assert result.cascade_footprint.by_table == {"geo_agent_tasks": limit + 1}


@pytest.mark.anyio
async def test_readiness_blocks_guarded_or_persisted_active_work(monkeypatch):
    monkeypatch.setattr(clients, "get_scheduler_job_status", _scheduler_states, raising=False)
    conn = _ReadConn(
        _count_row(agent_tasks=1),
        existing_tables={"geo_agent_tasks"},
        active_counts={"geo_agent_tasks": 1},
        lifecycle_available=False,
    )

    result = await clients.get_deletion_readiness(CLIENT_A, pool=_Pool(conn))

    assert result.active_work.guarded_writer is True
    assert result.active_work.total_items == 1
    assert result.active_work.by_table == {"geo_agent_tasks": 1}
    blocker = next(item for item in result.blockers if item.code == "ACTIVE_WORK_IN_PROGRESS")
    assert blocker.count == 1
    assert result.can_finalize is False


@pytest.mark.anyio
async def test_readiness_isolates_client_id_in_query_and_scheduler_calls(monkeypatch):
    calls = []

    async def statuses(client_id: str, job_type: str):
        calls.append((client_id, job_type))
        return {"state": "NOT_FOUND"}

    conn = _ReadConn(_count_row(client_id=CLIENT_B))
    monkeypatch.setattr(clients, "get_scheduler_job_status", statuses, raising=False)
    result = await clients.get_deletion_readiness(CLIENT_B, pool=_Pool(conn))

    assert result.workspace.id == str(CLIENT_B)
    assert conn.fetchrow_calls[0][1] == (str(CLIENT_B),)
    assert {call[0] for call in calls} == {str(CLIENT_B)}


@pytest.mark.anyio
async def test_public_readiness_applies_statement_timeout_and_maps_query_timeout(monkeypatch):
    class QueryTimedOut(Exception):
        pass

    class TimeoutConn(_ReadConn):
        async def fetchrow(self, sql, *args):
            raise QueryTimedOut("statement timeout")

    scheduler_calls = []

    async def statuses(client_id: str, job_type: str):
        scheduler_calls.append((client_id, job_type))
        return {"state": "NOT_FOUND"}

    conn = TimeoutConn(_count_row())
    monkeypatch.setattr(clients.asyncpg, "QueryCanceledError", QueryTimedOut)
    monkeypatch.setattr(clients, "get_scheduler_job_status", statuses)

    with pytest.raises(HTTPException) as exc:
        await clients.get_deletion_readiness(CLIENT_A, pool=_Pool(conn))

    assert exc.value.status_code == 504
    assert exc.value.detail["code"] == "WORKSPACE_READINESS_TIMEOUT"
    assert conn.fetchval_calls[0][0].startswith("SELECT set_config('statement_timeout'")
    assert scheduler_calls == []


@pytest.mark.anyio
async def test_stop_all_scheduling_holds_exclusive_fence_through_final_readiness(monkeypatch):
    conn = _DeleteConn(_count_row())
    stopped = []

    async def stop_all(client_id: str):
        stopped.append(client_id)

    async def status(client_id, job_type):
        assert client_id == str(CLIENT_A)
        return {"state": "NOT_FOUND"}

    async def unexpected_refresh(*args, **kwargs):
        raise AssertionError("Stop All must build readiness inside its exclusive fence")

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all, raising=False)
    monkeypatch.setattr(clients, "get_scheduler_job_status", status)
    monkeypatch.setattr(clients, "get_deletion_readiness", unexpected_refresh)

    result = await clients.stop_all_scheduling(CLIENT_A, pool=_Pool(conn))

    assert result.workspace.id == str(CLIENT_A)
    assert result.can_finalize is True
    assert stopped == [str(CLIENT_A)]
    sql, args = next(
        (sql, args)
        for sql, args in conn.execute_calls
        if "cron_collector = NULL" in sql
    )
    assert "cron_collector = NULL" in sql
    assert "cron_analyzer = NULL" in sql
    assert "cron_llm_discovery = NULL" in sql
    assert args == (str(CLIENT_A),)
    lifecycle_index = next(
        index
        for index, (sql, args) in enumerate(conn.fetchval_calls)
        if "pg_try_advisory_xact_lock" in sql
        and args == (f"workspace-lifecycle:{CLIENT_A}",)
    )
    assert conn.events[0] == "tx_enter"
    assert lifecycle_index >= 1  # statement timeout is scoped before the fence
    assert conn.events[-1] == "tx_commit"


@pytest.mark.anyio
async def test_stop_all_fails_fast_while_scheduler_sync_owns_shared_fence(monkeypatch):
    conn = _DeleteConn(_count_row(), lifecycle_available=False)
    stopped = []

    async def stop_all(client_id: str):
        stopped.append(client_id)

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all)

    with pytest.raises(HTTPException) as exc:
        await clients.stop_all_scheduling(CLIENT_A, pool=_Pool(conn))

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "ACTIVE_WORK_IN_PROGRESS"
    assert stopped == []
    assert conn.execute_calls == []
    assert conn.events == ["tx_enter", "tx_rollback"]


@dataclass(frozen=True)
class _Actor:
    id: str = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class _Tx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.events.append("tx_enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.events.append("tx_rollback" if exc else "tx_commit")
        return False


class _DeleteConn(_ReadConn):
    def __init__(
        self,
        row,
        *,
        lock_available=True,
        lifecycle_available=True,
        delete_error=None,
        existing_tables=None,
    ):
        super().__init__(
            row,
            existing_tables=existing_tables or {"geo_agent_tasks"},
        )
        self.lock_available = lock_available
        self.lifecycle_available = lifecycle_available
        self.delete_error = delete_error
        self.events = []
        self.fetchval_calls = []

    def transaction(self):
        return _Tx(self)

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        if (
            "pg_try_advisory_xact_lock" in sql
            and args == (clients._WORKSPACE_DELETE_LOCK_NAME,)
        ):
            return self.lock_available
        if "pg_try_advisory_xact_lock" in sql:
            return self.lifecycle_available
        if "SELECT EXISTS" in sql:
            return True
        for table_name, query in workspace_deletion.WORKSPACE_CASCADE_COUNT_QUERIES.items():
            if query == sql:
                return self.footprint_counts.get(table_name, 0)
        for table_name, query in workspace_deletion.WORKSPACE_ACTIVE_COUNT_QUERIES.items():
            if query == sql:
                return self.active_counts.get(table_name, 0)
        return None

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        if "FOR UPDATE" in sql:
            return {"id": self.row["id"], "name": self.row["name"]}
        return self.row

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        if sql.startswith("DELETE FROM geo_clients") and self.delete_error:
            raise self.delete_error
        if sql.startswith("DELETE FROM geo_clients"):
            self.events.append("delete")
            return "DELETE 1"
        if "INSERT INTO geo_user_audit_events" in sql:
            self.events.append("audit")
        return "UPDATE 1"


@pytest.mark.anyio
async def test_final_delete_rejects_structured_data_blockers_before_delete(monkeypatch):
    conn = _DeleteConn(_count_row(physical_prompts=2, logical_prompts=1))

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "WORKSPACE_DELETE_BLOCKED"
    assert exc.value.detail["blockers"][0]["code"] == "PROMPTS_REMAIN"
    assert not any(sql.startswith("DELETE FROM geo_clients") for sql, _ in conn.execute_calls)


@pytest.mark.anyio
async def test_final_delete_rejects_persisted_active_work_under_exclusive_fence():
    conn = _DeleteConn(_count_row())
    conn.active_counts = {"geo_agent_tasks": 1}

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert exc.value.status_code == 409
    blocker_codes = {
        blocker["code"] for blocker in exc.value.detail["blockers"]
    }
    assert "ACTIVE_WORK_IN_PROGRESS" in blocker_codes
    assert not any(
        sql.startswith("DELETE FROM geo_clients")
        for sql, _ in conn.execute_calls
    )


@pytest.mark.anyio
async def test_final_delete_requires_exact_workspace_name(monkeypatch):
    conn = _DeleteConn(_count_row())

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="answerx"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "WORKSPACE_NAME_MISMATCH"


@pytest.mark.anyio
async def test_final_delete_fails_fast_when_single_flight_lock_is_held(monkeypatch):
    conn = _DeleteConn(_count_row(), lock_available=False)

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert exc.value.status_code == 423
    assert exc.value.detail["code"] == "WORKSPACE_DELETE_IN_PROGRESS"
    assert conn.events == ["tx_enter", "tx_rollback"]
    assert conn.fetchrow_calls == []
    assert conn.fetch_calls == []


@pytest.mark.anyio
async def test_final_delete_fails_fast_when_workspace_writer_guard_is_active(monkeypatch):
    scheduler_calls = []

    async def stop_all(client_id: str):
        scheduler_calls.append(client_id)

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all, raising=False)
    conn = _DeleteConn(_count_row(), lifecycle_available=False)

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "ACTIVE_WORK_IN_PROGRESS"
    assert exc.value.detail["blockers"] == [
        {
            "code": "ACTIVE_WORK_IN_PROGRESS",
            "message": "Wait for active Workspace work to finish before final deletion",
        }
    ]
    assert scheduler_calls == []
    assert conn.fetchrow_calls == []
    assert conn.fetch_calls == []
    assert not any(
        args == (f"prompt-write:{CLIENT_A}",)
        for _sql, args in conn.fetchval_calls
    )


@pytest.mark.anyio
async def test_final_delete_rechecks_counts_under_prompt_write_lock(monkeypatch):
    conn = _DeleteConn(_count_row(physical_prompts=1, logical_prompts=1))

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["blockers"][0]["code"] == "PROMPTS_REMAIN"
    assert any(
        "pg_advisory_xact_lock" in sql
        and args == (f"prompt-write:{CLIENT_A}",)
        for sql, args in conn.fetchval_calls
    )
    lifecycle_index = next(
        index for index, (sql, _args) in enumerate(conn.fetchval_calls)
        if "pg_try_advisory_xact_lock(" in sql and "workspace-lifecycle:" in str(_args)
    )
    prompt_index = next(
        index for index, (sql, args) in enumerate(conn.fetchval_calls)
        if "pg_advisory_xact_lock(" in sql and args == (f"prompt-write:{CLIENT_A}",)
    )
    assert lifecycle_index < prompt_index
    assert conn.events == ["tx_enter", "tx_rollback"]
    assert not any(sql.startswith("DELETE FROM geo_clients") for sql, _ in conn.execute_calls)


@pytest.mark.anyio
async def test_final_delete_stops_jobs_and_deletes_without_inline_audit(monkeypatch):
    stopped = []

    async def stop_all(client_id: str):
        stopped.append(client_id)

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all, raising=False)
    conn = _DeleteConn(_count_row())

    result = await clients.delete_client(
        CLIENT_A,
        clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
        actor=_Actor(),
        pool=_Pool(conn),
    )

    assert result is None
    assert stopped == [str(CLIENT_A)]
    assert conn.events == ["tx_enter", "delete", "tx_commit"]
    assert not any(
        "INSERT INTO geo_user_audit_events" in sql
        for sql, _ in conn.execute_calls
    )
    assert any(
        sql.startswith("DELETE FROM geo_agent_tasks WHERE client_id")
        and args == (str(CLIENT_A),)
        for sql, args in conn.execute_calls
    )
    assert not any("pg_advisory_unlock" in sql for sql, _ in conn.fetchval_calls)
    assert "pg_try_advisory_xact_lock" in conn.fetchval_calls[0][0]
    assert conn.fetchval_calls[0][1] == (clients._WORKSPACE_DELETE_LOCK_NAME,)


class _BlockingAcquire:
    async def __aenter__(self):
        await asyncio.sleep(60)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _BlockedPool:
    def acquire(self):
        return _BlockingAcquire()


class _SlotAcquire:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        await self.pool.slots.acquire()
        self.pool.active += 1
        self.pool.max_active = max(self.pool.max_active, self.pool.active)
        return self.pool.conn

    async def __aexit__(self, exc_type, exc, tb):
        self.pool.active -= 1
        self.pool.slots.release()
        return False


class _TwoSlotPool:
    def __init__(self, conn):
        self.conn = conn
        self.slots = asyncio.Semaphore(2)
        self.active = 0
        self.max_active = 0

    def acquire(self):
        return _SlotAcquire(self)


class _QueueAcquire:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return self.pool.connections.pop(0)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _QueuePool:
    def __init__(self, *connections):
        self.connections = list(connections)

    def acquire(self):
        return _QueueAcquire(self)


@pytest.mark.anyio
async def test_final_delete_pool_acquire_timeout_is_explainable_and_bounded(monkeypatch):
    monkeypatch.setattr(clients, "WORKSPACE_DELETE_ACQUIRE_TIMEOUT_SECONDS", 0.01, raising=False)

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_BlockedPool(),
        )

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "DATABASE_BUSY"


@pytest.mark.anyio
async def test_final_delete_uses_one_pool_slot_while_ordinary_client_query_remains_available(monkeypatch):
    scheduler_entered = asyncio.Event()
    release_scheduler = asyncio.Event()

    async def stop_all(client_id: str):
        scheduler_entered.set()
        await release_scheduler.wait()

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all, raising=False)
    pool = _TwoSlotPool(_DeleteConn(_count_row()))
    delete_task = asyncio.create_task(
        clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=pool,
        )
    )
    await asyncio.wait_for(scheduler_entered.wait(), timeout=0.2)

    ordinary_row = await asyncio.wait_for(
        clients.ClientRepository(pool).get_by_name("Other Workspace"),
        timeout=0.2,
    )
    assert ordinary_row["name"] == "AnswerX"
    assert pool.max_active == 2

    release_scheduler.set()
    await delete_task


@pytest.mark.anyio
async def test_concurrent_delete_loser_runs_zero_readiness_counts(monkeypatch):
    scheduler_entered = asyncio.Event()
    release_scheduler = asyncio.Event()

    async def stop_all(client_id: str):
        scheduler_entered.set()
        await release_scheduler.wait()

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all, raising=False)
    winner_conn = _DeleteConn(_count_row())
    loser_conn = _DeleteConn(_count_row(), lock_available=False)
    pool = _QueuePool(winner_conn, loser_conn)

    winner = asyncio.create_task(
        clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=pool,
        )
    )
    await asyncio.wait_for(scheduler_entered.wait(), timeout=0.2)

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_B,
            clients.WorkspaceDeleteConfirm(workspace_name="Other"),
            actor=_Actor(),
            pool=pool,
        )

    assert exc.value.status_code == 423
    assert loser_conn.fetchrow_calls == []
    assert loser_conn.fetch_calls == []
    assert loser_conn.execute_calls == []
    assert len(loser_conn.fetchval_calls) == 1
    assert "pg_try_advisory_xact_lock" in loser_conn.fetchval_calls[0][0]

    release_scheduler.set()
    await winner


@pytest.mark.anyio
async def test_failed_final_delete_rolls_back_and_releases_global_lock(monkeypatch):
    async def stop_all(client_id: str):
        return None

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all, raising=False)
    conn = _DeleteConn(_count_row(), delete_error=RuntimeError("delete failed"))

    with pytest.raises(RuntimeError, match="delete failed"):
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert conn.events == ["tx_enter", "tx_rollback"]
    assert not any("pg_advisory_unlock" in sql for sql, _ in conn.fetchval_calls)


@pytest.mark.anyio
async def test_final_delete_maps_statement_timeout_to_explainable_gateway_timeout(monkeypatch):
    class QueryTimedOut(Exception):
        pass

    monkeypatch.setattr(clients.asyncpg, "QueryCanceledError", QueryTimedOut)

    async def stop_all(client_id: str):
        return None

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all, raising=False)
    conn = _DeleteConn(_count_row(), delete_error=QueryTimedOut("statement timeout"))

    with pytest.raises(HTTPException) as exc:
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert exc.value.status_code == 504
    assert exc.value.detail["code"] == "WORKSPACE_DELETE_TIMEOUT"
    assert conn.events == ["tx_enter", "tx_rollback"]
    assert not any("pg_advisory_unlock" in sql for sql, _ in conn.fetchval_calls)


@pytest.mark.anyio
async def test_cancelled_final_delete_rolls_back_without_session_unlock(monkeypatch):
    scheduler_entered = asyncio.Event()

    async def stop_all(client_id: str):
        scheduler_entered.set()
        raise asyncio.CancelledError

    monkeypatch.setattr(clients, "stop_all_scheduler_jobs", stop_all)
    conn = _DeleteConn(_count_row())

    with pytest.raises(asyncio.CancelledError):
        await clients.delete_client(
            CLIENT_A,
            clients.WorkspaceDeleteConfirm(workspace_name="AnswerX"),
            actor=_Actor(),
            pool=_Pool(conn),
        )

    assert scheduler_entered.is_set()
    assert conn.events == ["tx_enter", "tx_rollback"]
    assert not any("pg_advisory_unlock" in sql for sql, _ in conn.fetchval_calls)
