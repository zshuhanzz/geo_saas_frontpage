from __future__ import annotations

import asyncio

import pytest

import geo_common.services as services


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Transaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.events.append(f"{self.conn.name}:tx_enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.events.append(f"{self.conn.name}:tx_exit")
        if self.conn.owns_lock:
            self.conn.owns_lock = False
            self.conn.lock.release()
        return False


class _Connection:
    def __init__(self, name, lock, events):
        self.name = name
        self.lock = lock
        self.events = events
        self.owns_lock = False

    def transaction(self):
        return _Transaction(self)

    async def fetchval(self, sql, *args):
        if "pg_try_advisory_xact_lock_shared" in sql:
            assert args == ("workspace-lifecycle:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",)
            self.events.append(f"{self.name}:lifecycle")
            return True
        if "FROM geo_clients" in sql:
            assert args == ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",)
            self.events.append(f"{self.name}:exists")
            return True
        assert "pg_advisory_xact_lock" in sql
        assert args == ("prompt-write:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",)
        await self.lock.acquire()
        self.owns_lock = True
        self.events.append(f"{self.name}:prompt_lock")


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.events = []
        self.counter = 0

    def acquire(self):
        self.counter += 1
        return _Acquire(_Connection(str(self.counter), self.lock, self.events))


@pytest.mark.anyio
async def test_prompt_write_coordinator_serializes_import_single_and_batch_callbacks():
    assert hasattr(services, "PromptWriteCoordinator"), "shared Prompt-write coordinator is required"
    coordinator = services.PromptWriteCoordinator(_Pool())
    entered = asyncio.Event()
    release = asyncio.Event()
    operation_events: list[str] = []

    async def import_operation(conn):
        operation_events.append("import:start")
        entered.set()
        await release.wait()
        operation_events.append("import:end")
        return "import"

    async def normal_write_operation(conn):
        operation_events.append("normal:start")
        operation_events.append("normal:end")
        return "normal"

    import_task = asyncio.create_task(
        coordinator.execute("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", import_operation)
    )
    await entered.wait()
    single_task = asyncio.create_task(
        coordinator.execute("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", normal_write_operation)
    )
    batch_task = asyncio.create_task(
        coordinator.execute("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", normal_write_operation)
    )
    await asyncio.sleep(0)
    assert operation_events == ["import:start"]

    release.set()
    assert await asyncio.gather(import_task, single_task, batch_task) == [
        "import", "normal", "normal"
    ]
    assert operation_events == [
        "import:start", "import:end", "normal:start", "normal:end",
        "normal:start", "normal:end",
    ]
    first_events = coordinator._pool.events[:4]
    assert first_events == [
        "1:tx_enter", "1:lifecycle", "1:exists", "1:prompt_lock",
    ]


@pytest.mark.anyio
async def test_transaction_setup_runs_inside_transaction_before_advisory_locks():
    pool = _Pool()
    coordinator = services.PromptWriteCoordinator(pool)

    async def setup(conn):
        conn.events.append(f"{conn.name}:setup")

    async def operation(conn):
        conn.events.append(f"{conn.name}:operation")

    await coordinator.execute(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        operation,
        transaction_setup=setup,
    )

    assert pool.events == [
        "1:tx_enter",
        "1:setup",
        "1:lifecycle",
        "1:exists",
        "1:prompt_lock",
        "1:operation",
        "1:tx_exit",
    ]
