from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

import main as agent_main
from routers import tasks


CLIENT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.mark.asyncio
async def test_background_agent_pipeline_holds_lifecycle_for_full_runner(monkeypatch):
    events: list[str] = []
    finished = asyncio.Event()
    @asynccontextmanager
    async def lifecycle(client_id):
        assert client_id == CLIENT_ID
        events.append("guard_enter")
        try:
            yield object()
        finally:
            events.append("guard_exit")

    async def runner(task_id, inputs, client_id):
        assert (task_id, inputs, client_id) == ("task-1", {"x": 1}, CLIENT_ID)
        events.append("runner")
        finished.set()

    monkeypatch.setattr(tasks, "agent_workspace_lifecycle_session", lifecycle)
    monkeypatch.setitem(tasks._pipeline_registry, "analysis", runner)

    await tasks._fire_pipeline("task-1", "analysis", {"x": 1}, CLIENT_ID)
    await asyncio.wait_for(finished.wait(), timeout=0.2)
    await asyncio.sleep(0)

    assert events == ["guard_enter", "runner", "guard_exit"]


@pytest.mark.asyncio
async def test_background_checkpoint_compression_writes_inside_lifecycle(monkeypatch):
    events: list[str] = []
    @asynccontextmanager
    async def lifecycle(client_id):
        assert client_id == CLIENT_ID
        events.append("guard_enter")
        try:
            yield object()
        finally:
            events.append("guard_exit")

    async def compress(messages):
        events.append("compress")
        return messages[:1]

    class Graph:
        async def aupdate_state(self, config, values):
            assert config["configurable"]["thread_id"] == "thread-1"
            assert values == {"messages": ["first"]}
            events.append("checkpoint_write")

    monkeypatch.setattr(agent_main, "agent_workspace_lifecycle_session", lifecycle)
    monkeypatch.setattr(agent_main, "compress_messages", compress)
    monkeypatch.setattr(agent_main, "_graph", Graph())

    await agent_main._compress_context(
        {"configurable": {"thread_id": "thread-1"}},
        ["first", "second"],
        CLIENT_ID,
    )

    assert events == ["guard_enter", "compress", "checkpoint_write", "guard_exit"]


@pytest.mark.asyncio
async def test_brand_profile_upsert_uses_short_workspace_write_guard(monkeypatch):
    events: list[str] = []
    pool = object()

    async def get_pool():
        return pool

    class Conn:
        async def execute(self, sql, *args):
            assert "INSERT INTO geo_brand_profiles" in sql
            assert args[0] == CLIENT_ID
            events.append("write")

    class Coordinator:
        def __init__(self, operation_pool):
            assert operation_pool is pool

        async def execute(self, client_id, operation):
            assert client_id == CLIENT_ID
            events.append("guard_enter")
            await operation(Conn())
            events.append("guard_exit")

    monkeypatch.setattr(agent_main, "get_pool", get_pool)
    monkeypatch.setattr(agent_main, "WorkspaceWriteCoordinator", Coordinator)

    await agent_main.update_brand_profile(
        client_id=CLIENT_ID,
        data=agent_main.BrandProfileUpdate(brand_name="AnswerX"),
        current_user=None,
    )

    assert events == ["guard_enter", "write", "guard_exit"]
