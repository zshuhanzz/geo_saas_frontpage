from __future__ import annotations

import asyncio

import pytest

from geo_common.services.workspace_lifecycle import (
    WorkspaceLifecycleBusy,
    WorkspaceLifecycleMissing,
    WorkspaceLifecycleSessionLimiter,
    WorkspaceWriteCoordinator,
    acquire_workspace_lifecycle_session_shared,
    acquire_workspace_lifecycle_exclusive,
    acquire_workspace_lifecycle_shared,
    release_workspace_lifecycle_session_shared,
    workspace_lifecycle_session,
)


CLIENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class _Conn:
    def __init__(self, *, exists: bool = True):
        self.exists = exists
        self.calls: list[tuple[str, tuple]] = []

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        if "pg_try_advisory" in sql:
            return True
        if "FROM geo_clients" in sql:
            return self.exists
        return None


@pytest.mark.asyncio
async def test_shared_lifecycle_guard_locks_before_workspace_existence_check():
    conn = _Conn()

    await acquire_workspace_lifecycle_shared(conn, CLIENT_A)

    assert "pg_try_advisory_xact_lock_shared" in conn.calls[0][0]
    assert conn.calls[0][1] == (f"workspace-lifecycle:{CLIENT_A}",)
    assert "FROM geo_clients" in conn.calls[1][0]
    assert conn.calls[1][1] == (CLIENT_A,)


@pytest.mark.asyncio
async def test_exclusive_lifecycle_fence_uses_same_key_and_rejects_deleted_workspace():
    conn = _Conn(exists=False)

    with pytest.raises(WorkspaceLifecycleMissing):
        await acquire_workspace_lifecycle_exclusive(conn, CLIENT_A)

    assert "pg_advisory_xact_lock(" in conn.calls[0][0]
    assert "_shared" not in conn.calls[0][0]
    assert conn.calls[0][1] == (f"workspace-lifecycle:{CLIENT_A}",)
    assert "FROM geo_clients" in conn.calls[1][0]


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


@pytest.mark.asyncio
async def test_session_guard_covers_long_work_and_always_unlocks():
    conn = _Conn()

    async with workspace_lifecycle_session(_Pool(conn), CLIENT_A):
        assert "pg_try_advisory_lock_shared" in conn.calls[0][0]
        assert "FROM geo_clients" in conn.calls[1][0]

    assert "pg_advisory_unlock_shared" in conn.calls[-1][0]
    assert conn.calls[-1][1] == (f"workspace-lifecycle:{CLIENT_A}",)


@pytest.mark.asyncio
async def test_session_guard_unlocks_when_workspace_disappeared_before_acquisition():
    conn = _Conn(exists=False)

    with pytest.raises(WorkspaceLifecycleMissing):
        async with workspace_lifecycle_session(_Pool(conn), CLIENT_A):
            raise AssertionError("must not enter")

    assert "pg_advisory_unlock_shared" in conn.calls[-1][0]


@pytest.mark.asyncio
async def test_session_unlock_finishes_before_propagating_cancellation():
    class SlowUnlockConn:
        def __init__(self):
            self.started = asyncio.Event()
            self.allowed = asyncio.Event()
            self.finished = False

        async def fetchval(self, sql, *args):
            assert "pg_advisory_unlock_shared" in sql
            self.started.set()
            await self.allowed.wait()
            self.finished = True

    conn = SlowUnlockConn()
    task = asyncio.create_task(
        release_workspace_lifecycle_session_shared(conn, CLIENT_A)
    )
    await conn.started.wait()
    task.cancel()
    await asyncio.sleep(0)

    assert not task.done()
    conn.allowed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert conn.finished is True


@pytest.mark.asyncio
async def test_cancelled_session_acquire_attempts_unlock_before_returning_connection():
    class CancelAcquireConn:
        def __init__(self):
            self.lock_started = asyncio.Event()
            self.unlocked = False

        async def fetchval(self, sql, *args):
            if "pg_try_advisory_lock_shared" in sql:
                self.lock_started.set()
                await asyncio.Event().wait()
            if "pg_advisory_unlock_shared" in sql:
                self.unlocked = True
                return True
            raise AssertionError(sql)

    conn = CancelAcquireConn()
    task = asyncio.create_task(
        acquire_workspace_lifecycle_session_shared(conn, CLIENT_A)
    )
    await conn.lock_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert conn.unlocked is True


class _Transaction:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        self.events.append("tx_enter")

    async def __aexit__(self, exc_type, exc, tb):
        self.events.append("tx_commit" if exc_type is None else "tx_rollback")
        return False


class _CoordinatorConn(_Conn):
    def __init__(self):
        super().__init__()
        self.events: list[str] = []

    def transaction(self):
        return _Transaction(self.events)


@pytest.mark.asyncio
async def test_short_writer_coordinator_guards_and_mutates_on_one_transaction_connection():
    conn = _CoordinatorConn()

    async def operation(operation_conn):
        assert operation_conn is conn
        conn.events.append("mutation")
        return "ok"

    result = await WorkspaceWriteCoordinator(_Pool(conn)).execute(CLIENT_A, operation)

    assert result == "ok"
    assert conn.events == ["tx_enter", "mutation", "tx_commit"]
    assert "pg_try_advisory_xact_lock_shared" in conn.calls[0][0]


@pytest.mark.asyncio
async def test_short_writer_fails_fast_without_running_operation_when_delete_is_active():
    class BusyConn(_CoordinatorConn):
        async def fetchval(self, sql, *args):
            self.calls.append((sql, args))
            if "pg_try_advisory_xact_lock_shared" in sql:
                return False
            raise AssertionError(sql)

    conn = BusyConn()
    operation_called = False

    async def operation(_conn):
        nonlocal operation_called
        operation_called = True

    with pytest.raises(WorkspaceLifecycleBusy):
        await WorkspaceWriteCoordinator(_Pool(conn)).execute(CLIENT_A, operation)

    assert operation_called is False
    assert conn.events == ["tx_enter", "tx_rollback"]
    assert len(conn.calls) == 1


@pytest.mark.asyncio
async def test_long_session_fails_fast_without_unlocking_an_unowned_guard():
    class BusySessionConn:
        def __init__(self):
            self.calls = []

        async def fetchval(self, sql, *args):
            self.calls.append((sql, args))
            if "pg_try_advisory_lock_shared" in sql:
                return False
            raise AssertionError(sql)

    conn = BusySessionConn()
    with pytest.raises(WorkspaceLifecycleBusy):
        async with workspace_lifecycle_session(_Pool(conn), CLIENT_A):
            raise AssertionError("must not enter")

    assert len(conn.calls) == 1
    assert "pg_try_advisory_lock_shared" in conn.calls[0][0]


class _LifecycleManager:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.shared: dict[str, int] = {}
        self.exclusive: set[str] = set()

    async def acquire_shared(self, key: str):
        async with self.condition:
            await self.condition.wait_for(lambda: key not in self.exclusive)
            self.shared[key] = self.shared.get(key, 0) + 1

    async def acquire_exclusive(self, key: str):
        async with self.condition:
            await self.condition.wait_for(
                lambda: key not in self.exclusive and self.shared.get(key, 0) == 0
            )
            self.exclusive.add(key)

    async def release(self, held: list[tuple[str, str]]):
        async with self.condition:
            for mode, key in held:
                if mode == "shared":
                    self.shared[key] -= 1
                else:
                    self.exclusive.remove(key)
            self.condition.notify_all()


class _RaceTx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.conn.manager.release(self.conn.held)
        self.conn.held = []
        return False


class _RaceConn:
    def __init__(self, manager, workspaces, residuals):
        self.manager = manager
        self.workspaces = workspaces
        self.residuals = residuals
        self.held: list[tuple[str, str]] = []

    def transaction(self):
        return _RaceTx(self)

    async def fetchval(self, sql, *args):
        if "pg_try_advisory_xact_lock_shared" in sql:
            if args[0] in self.manager.exclusive:
                return False
            await self.manager.acquire_shared(args[0])
            self.held.append(("shared", args[0]))
            return True
        if "pg_advisory_xact_lock(" in sql:
            await self.manager.acquire_exclusive(args[0])
            self.held.append(("exclusive", args[0]))
            return None
        if "FROM geo_clients" in sql:
            return args[0] in self.workspaces
        raise AssertionError(sql)


class _RacePool:
    def __init__(self, manager, workspaces, residuals):
        self.manager = manager
        self.workspaces = workspaces
        self.residuals = residuals

    def acquire(self):
        return _Acquire(_RaceConn(self.manager, self.workspaces, self.residuals))


@pytest.mark.asyncio
async def test_writer_started_before_delete_drains_then_no_residual_can_reappear():
    manager = _LifecycleManager()
    workspaces = {CLIENT_A}
    residuals: dict[str, list[str]] = {CLIENT_A: []}
    pool = _RacePool(manager, workspaces, residuals)
    writer_entered = asyncio.Event()
    release_writer = asyncio.Event()

    async def writer(conn):
        writer_entered.set()
        await release_writer.wait()
        residuals[CLIENT_A].append("row")

    writer_task = asyncio.create_task(WorkspaceWriteCoordinator(pool).execute(CLIENT_A, writer))
    await writer_entered.wait()

    async def final_delete():
        async with pool.acquire() as conn:
            async with conn.transaction():
                await acquire_workspace_lifecycle_exclusive(conn, CLIENT_A)
                residuals[CLIENT_A].clear()
                workspaces.remove(CLIENT_A)

    delete_task = asyncio.create_task(final_delete())
    await asyncio.sleep(0)
    assert not delete_task.done()
    release_writer.set()
    await asyncio.gather(writer_task, delete_task)
    assert residuals[CLIENT_A] == []

    with pytest.raises(WorkspaceLifecycleMissing):
        await WorkspaceWriteCoordinator(pool).execute(
            CLIENT_A,
            lambda _conn: _async_value(residuals[CLIENT_A].append("late")),
        )
    assert residuals[CLIENT_A] == []


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_lifecycle_fences_are_isolated_between_workspaces():
    manager = _LifecycleManager()
    client_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    workspaces = {CLIENT_A, client_b}
    residuals = {CLIENT_A: [], client_b: []}
    pool = _RacePool(manager, workspaces, residuals)
    hold_a = asyncio.Event()
    release_a = asyncio.Event()

    async def writer_a(_conn):
        hold_a.set()
        await release_a.wait()

    task_a = asyncio.create_task(WorkspaceWriteCoordinator(pool).execute(CLIENT_A, writer_a))
    await hold_a.wait()

    async with pool.acquire() as conn_b:
        async with conn_b.transaction():
            await asyncio.wait_for(
                acquire_workspace_lifecycle_exclusive(conn_b, client_b),
                timeout=0.1,
            )

    release_a.set()
    await task_a


@pytest.mark.asyncio
async def test_limiter_queues_before_pool_and_preserves_half_for_operation_connections():
    class CapacityAcquire:
        def __init__(self, pool):
            self.pool = pool
            self.conn = _Conn()

        async def __aenter__(self):
            self.pool.acquire_calls += 1
            await self.pool.capacity.acquire()
            self.pool.in_use += 1
            self.pool.max_in_use = max(self.pool.max_in_use, self.pool.in_use)
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            self.pool.in_use -= 1
            self.pool.capacity.release()

    class CapacityPool:
        def __init__(self):
            self.capacity = asyncio.Semaphore(4)
            self.in_use = 0
            self.max_in_use = 0
            self.acquire_calls = 0

        def acquire(self):
            return CapacityAcquire(self)

    pool = CapacityPool()
    limiter = WorkspaceLifecycleSessionLimiter(
        "TEST_UNUSED_LIFECYCLE_LIMIT",
        default=2,
        pool_capacity=4,
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    count = 0

    async def workflow():
        nonlocal count
        async with limiter.session(pool, CLIENT_A):
            count += 1
            if count == 2:
                entered.set()
            async with pool.acquire():
                await release.wait()

    tasks = [asyncio.create_task(workflow()) for _ in range(3)]
    await entered.wait()
    await asyncio.sleep(0)
    assert pool.acquire_calls == 4  # 2 lifecycle + 2 operation connections
    assert pool.max_in_use == 4
    release.set()
    await asyncio.gather(*tasks)
    assert pool.acquire_calls == 6


@pytest.mark.asyncio
async def test_limiter_releases_slot_when_guard_cleanup_raises():
    class BrokenAcquire:
        def __init__(self): self.conn = _Conn()
        async def __aenter__(self): return self.conn
        async def __aexit__(self, *args): raise RuntimeError("pool release failed")

    class BrokenPool:
        def acquire(self): return BrokenAcquire()

    limiter = WorkspaceLifecycleSessionLimiter(
        "TEST_UNUSED_LIFECYCLE_LIMIT_ERROR",
        default=1,
        pool_capacity=2,
    )

    async def run_once():
        async with limiter.session(BrokenPool(), CLIENT_A):
            pass

    with pytest.raises(RuntimeError, match="pool release failed"):
        await run_once()
    with pytest.raises(RuntimeError, match="pool release failed"):
        await asyncio.wait_for(run_once(), timeout=0.1)


@pytest.mark.asyncio
async def test_writer_flood_does_not_hold_pool_while_delete_waits_on_slow_scheduler():
    class CapacityTx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class CapacityConn:
        def transaction(self):
            return CapacityTx()

        async def fetchval(self, sql, *args):
            if "pg_try_advisory_xact_lock_shared" in sql:
                return False
            raise AssertionError(sql)

    class CapacityAcquire:
        def __init__(self, pool):
            self.pool = pool

        async def __aenter__(self):
            await self.pool.capacity.acquire()
            self.pool.in_use += 1
            self.pool.max_in_use = max(self.pool.max_in_use, self.pool.in_use)
            return CapacityConn()

        async def __aexit__(self, exc_type, exc, tb):
            self.pool.in_use -= 1
            self.pool.capacity.release()
            return False

    class CapacityPool:
        def __init__(self):
            self.capacity = asyncio.Semaphore(2)
            self.in_use = 0
            self.max_in_use = 0

        def acquire(self):
            return CapacityAcquire(self)

    pool = CapacityPool()
    scheduler_started = asyncio.Event()
    scheduler_release = asyncio.Event()
    operation_calls = 0

    async def operation(_conn):
        nonlocal operation_calls
        operation_calls += 1

    async def delete_with_slow_scheduler():
        async with pool.acquire():
            # This connection models final deletion holding its transaction
            # and lifecycle fence during a slow external Scheduler delete.
            scheduler_started.set()
            await scheduler_release.wait()

    delete_task = asyncio.create_task(delete_with_slow_scheduler())
    await scheduler_started.wait()
    writers = [
        asyncio.create_task(
            WorkspaceWriteCoordinator(pool).execute(CLIENT_A, operation)
        )
        for _ in range(25)
    ]
    results = await asyncio.wait_for(
        asyncio.gather(*writers, return_exceptions=True),
        timeout=0.2,
    )
    assert all(isinstance(result, WorkspaceLifecycleBusy) for result in results)
    assert not delete_task.done()
    scheduler_release.set()
    await delete_task

    assert operation_calls == 0
    assert pool.max_in_use == 2
