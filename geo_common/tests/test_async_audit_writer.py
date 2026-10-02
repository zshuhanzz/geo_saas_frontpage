"""Availability contracts for the best-effort audit writer."""

from __future__ import annotations

import pytest

from geo_common.audit import AsyncAuditWriter, sanitize_query_params


class FakeConnection:
    def __init__(self) -> None:
        self.batches = []

    async def executemany(self, sql, values):
        self.batches.append((sql, list(values)))


class AcquireContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def acquire(self):
        return AcquireContext(self.connection)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _event() -> dict:
    return {
        "user_id": "77246f8b-84b8-4e3b-a085-7a79b7a1e825",
        "client_id": "b0e10518-5f70-426f-b09e-dbe025984ba1",
        "event_type": "api_action",
        "action_key": "actions.content.execute",
    }


def test_enqueue_drops_immediately_when_queue_is_full() -> None:
    writer = AsyncAuditWriter(FakePool(), queue_size=1)
    assert writer.enqueue(_event()) is True
    assert writer.enqueue(_event()) is False
    assert writer.dropped_events == 1


@pytest.mark.anyio
async def test_writer_batches_without_blocking_request_path() -> None:
    pool = FakePool()
    writer = AsyncAuditWriter(pool, flush_interval_seconds=0.01)
    writer.start()
    assert writer.enqueue(_event()) is True
    assert writer.enqueue({**_event(), "action_key": "actions.analysis.execute"}) is True
    await writer.close()

    assert len(pool.connection.batches) == 1
    sql, values = pool.connection.batches[0]
    assert "INSERT INTO geo_user_audit_events" in sql
    assert [value[3] for value in values] == [
        "actions.content.execute",
        "actions.analysis.execute",
    ]


def test_query_audit_keeps_filters_and_redacts_content() -> None:
    assert sanitize_query_params(
        [
            ("client_id", "b0e10518"),
            ("platform", "chatgpt"),
            ("prompt_text", "private prompt"),
            ("token", "secret"),
        ]
    ) == {
        "client_id": "b0e10518",
        "platform": "chatgpt",
        "prompt_text": "[REDACTED]",
        "token": "[REDACTED]",
    }
