import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from geo_common.services import WorkspaceLifecycleMissing
from geo_common.services import acquire_workspace_lifecycle_exclusive
from routers import clients


@pytest.mark.anyio
async def test_cron_update_waits_for_scheduler_sync_inside_shared_guard(monkeypatch):
    events = []
    pool = object()

    class Repo:
        def __init__(self, actual_pool):
            assert actual_pool is pool

        async def get_by_id(self, client_id):
            return {"id": client_id}

        async def update(self, client_id, *, updates):
            events.append(("update", updates["cron_collector"]))

    @asynccontextmanager
    async def guard(actual_pool, client_id):
        assert actual_pool is pool
        events.append(("guard_enter", client_id))
        try:
            yield object()
        finally:
            events.append(("guard_exit", client_id))

    async def sync(client_id, job_type, cron):
        events.append(("sync", client_id, job_type, cron))

    async def get_client(client_id, *, pool):
        return "updated"

    monkeypatch.setattr(clients, "ClientRepository", Repo)
    monkeypatch.setattr(clients, "long_workspace_lifecycle_session", guard)
    monkeypatch.setattr(clients, "sync_scheduler_job", sync)
    monkeypatch.setattr(clients, "get_client", get_client)

    result = await clients.update_client(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        clients.ClientUpdate(cron_collector="0 * * * *"),
        pool=pool,
    )

    assert result == "updated"
    assert events == [
        ("guard_enter", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("update", "0 * * * *"),
        (
            "sync",
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "collector",
            "0 * * * *",
        ),
        ("guard_exit", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    ]


@pytest.mark.anyio
async def test_detached_scheduler_sync_holds_guard_across_external_mutation(monkeypatch):
    events = []
    sync_entered = asyncio.Event()
    release_sync = asyncio.Event()
    finished = asyncio.Event()

    class Conn:
        async def fetchrow(self, sql, *args):
            assert "cron_collector" in sql
            assert args == ("client-a",)
            return {
                "cron_collector": "15 * * * *",
                "cron_analyzer": None,
                "cron_llm_discovery": None,
            }

    @asynccontextmanager
    async def guard(pool, client_id):
        events.append("guard_enter")
        try:
            yield Conn()
        finally:
            events.append("guard_exit")

    async def sync(client_id, job_type, cron):
        events.append("scheduler_start")
        sync_entered.set()
        await release_sync.wait()
        events.append("scheduler_done")
        finished.set()

    monkeypatch.setattr(clients.database, "_pool", object())
    monkeypatch.setattr(clients, "long_workspace_lifecycle_session", guard)
    monkeypatch.setattr(clients, "sync_scheduler_job", sync)

    clients._fire_scheduler_sync("client-a", "collector", "0 * * * *")
    await sync_entered.wait()
    assert events == ["guard_enter", "scheduler_start"]
    release_sync.set()
    await finished.wait()
    await asyncio.sleep(0)
    assert events == [
        "guard_enter", "scheduler_start", "scheduler_done", "guard_exit"
    ]


@pytest.mark.anyio
async def test_queued_scheduler_sync_reloads_null_cron_and_cannot_recreate_after_stop(monkeypatch):
    calls = []
    finished = asyncio.Event()

    class Conn:
        async def fetchrow(self, sql, *args):
            assert "cron_collector" in sql
            assert args == ("client-a",)
            return {
                "cron_collector": None,
                "cron_analyzer": None,
                "cron_llm_discovery": None,
            }

    @asynccontextmanager
    async def guard(pool, client_id):
        yield Conn()

    async def sync(client_id, job_type, cron):
        calls.append((client_id, job_type, cron))
        finished.set()

    monkeypatch.setattr(clients.database, "_pool", object())
    monkeypatch.setattr(clients, "long_workspace_lifecycle_session", guard)
    monkeypatch.setattr(clients, "sync_scheduler_job", sync)

    # This value was captured by an update before Stop All cleared the DB row.
    clients._fire_scheduler_sync("client-a", "collector", "0 * * * *")
    await asyncio.wait_for(finished.wait(), timeout=0.2)

    assert calls == [("client-a", "collector", None)]


@pytest.mark.anyio
async def test_detached_scheduler_sync_after_delete_never_calls_scheduler(monkeypatch):
    calls = []

    @asynccontextmanager
    async def missing_guard(pool, client_id):
        raise WorkspaceLifecycleMissing(client_id)
        yield

    async def sync(*args):
        calls.append(args)

    monkeypatch.setattr(clients.database, "_pool", object())
    monkeypatch.setattr(clients, "long_workspace_lifecycle_session", missing_guard)
    monkeypatch.setattr(clients, "sync_scheduler_job", sync)

    clients._fire_scheduler_sync("deleted", "collector", "0 * * * *")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert calls == []


@pytest.mark.anyio
async def test_final_exclusive_drains_scheduler_sync_then_late_sync_is_rejected(monkeypatch):
    condition = asyncio.Condition()
    shared = 0
    exclusive = False
    workspace_exists = True
    sync_started = asyncio.Event()
    finish_sync = asyncio.Event()
    final_acquired = asyncio.Event()
    sync_calls = 0

    class Tx:
        async def __aenter__(self): return self
        async def __aexit__(self, *args):
            nonlocal exclusive
            async with condition:
                exclusive = False
                condition.notify_all()

    class Conn:
        def transaction(self): return Tx()
        async def fetchrow(self, sql, *args):
            if "cron_collector" in sql:
                return {
                    "cron_collector": "0 * * * *",
                    "cron_analyzer": None,
                    "cron_llm_discovery": None,
                }
            raise AssertionError(sql)
        async def fetchval(self, sql, *args):
            nonlocal shared, exclusive
            if "pg_try_advisory_lock_shared" in sql:
                async with condition:
                    if exclusive:
                        return False
                    shared += 1
                return True
            if "pg_advisory_unlock_shared" in sql:
                async with condition:
                    shared -= 1
                    condition.notify_all()
                return True
            if "pg_advisory_xact_lock(" in sql:
                async with condition:
                    await condition.wait_for(lambda: not exclusive and shared == 0)
                    exclusive = True
                return None
            if "SELECT EXISTS" in sql:
                return workspace_exists
            raise AssertionError(sql)

    class Acquire:
        async def __aenter__(self): return Conn()
        async def __aexit__(self, *args): return False

    class Pool:
        def acquire(self): return Acquire()

    async def sync(*args):
        nonlocal sync_calls
        sync_calls += 1
        sync_started.set()
        await finish_sync.wait()

    pool = Pool()
    monkeypatch.setattr(clients.database, "_pool", pool)
    monkeypatch.setattr(clients, "sync_scheduler_job", sync)

    clients._fire_scheduler_sync("client-a", "collector", "0 * * * *")
    await sync_started.wait()

    async def final_delete():
        nonlocal workspace_exists
        async with pool.acquire() as conn:
            async with conn.transaction():
                await acquire_workspace_lifecycle_exclusive(conn, "client-a")
                final_acquired.set()
                workspace_exists = False

    final_task = asyncio.create_task(final_delete())
    await asyncio.sleep(0)
    assert not final_acquired.is_set()
    finish_sync.set()
    await final_task
    assert sync_calls == 1

    clients._fire_scheduler_sync("client-a", "collector", "0 * * * *")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert sync_calls == 1
