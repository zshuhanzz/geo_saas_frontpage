from __future__ import annotations

import pytest

import main as analyzer_main


CLIENT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class _Pool:
    def __init__(self, conn, events):
        self.conn = conn
        self.events = events

    async def acquire(self):
        self.events.append("pool_acquire")
        return self.conn

    async def release(self, conn):
        assert conn is self.conn
        self.events.append("pool_release")


@pytest.mark.asyncio
async def test_analyzer_holds_workspace_lifecycle_for_entire_job(monkeypatch):
    events: list[str] = []
    conn = object()
    pool = _Pool(conn, events)

    async def connect():
        return pool

    async def disconnect():
        events.append("disconnect")

    async def acquire_lifecycle(operation_conn, client_id):
        assert operation_conn is conn
        assert client_id == CLIENT_ID
        events.append("lifecycle_acquire")

    async def release_lifecycle(operation_conn, client_id):
        assert operation_conn is conn
        assert client_id == CLIENT_ID
        events.append("lifecycle_release")

    async def load_config(operation_conn, client_id):
        assert operation_conn is conn
        events.append("load_config")
        return object()

    async def no_batch(operation_conn, client_id, explicit):
        events.append("resolve_batch")
        return None

    monkeypatch.setenv("CLIENT_ID", CLIENT_ID)
    monkeypatch.delenv("FORCE_RUN", raising=False)
    monkeypatch.setattr(analyzer_main.db, "connect", connect)
    monkeypatch.setattr(analyzer_main.db, "disconnect", disconnect)
    monkeypatch.setattr(analyzer_main, "acquire_workspace_lifecycle_session_shared", acquire_lifecycle)
    monkeypatch.setattr(analyzer_main, "release_workspace_lifecycle_session_shared", release_lifecycle)
    monkeypatch.setattr(analyzer_main, "load_client_config", load_config)
    monkeypatch.setattr(analyzer_main, "_resolve_batch_id", no_batch)

    await analyzer_main.main_async()

    assert events == [
        "pool_acquire",
        "lifecycle_acquire",
        "load_config",
        "resolve_batch",
        "lifecycle_release",
        "pool_release",
        "disconnect",
    ]
