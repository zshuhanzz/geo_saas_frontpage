import pytest

from geo_common.services.prompt_deletion import PromptCascadeDeletionService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeTransaction:
    def __init__(self, events=None):
        self.events = events

    async def __aenter__(self):
        if self.events is not None:
            self.events.append("begin")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.events is not None:
            self.events.append("rollback" if exc else "commit")
        return False


class FakeConn:
    def __init__(self, prompt_rows):
        self.prompt_rows = prompt_rows
        self.fetch_calls = []
        self.execute_calls = []

    def transaction(self):
        return FakeTransaction()

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        if "FROM geo_client_prompts" in sql:
            return self.prompt_rows
        return []

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        if "geo_sentiment_themes" in sql:
            return "DELETE 2"
        if "geo_sentiment_results" in sql:
            return "DELETE 3"
        if "geo_citations" in sql:
            return "DELETE 4"
        if "geo_product_mentions" in sql:
            return "DELETE 5"
        if "geo_brand_mentions" in sql:
            return "DELETE 6"
        if "geo_results" in sql:
            return "DELETE 7"
        if "geo_tasks" in sql:
            return "DELETE 8"
        if "geo_client_prompts" in sql:
            return "DELETE 1"
        return "DELETE 0"


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


@pytest.mark.anyio
async def test_cascade_delete_deletes_downstream_before_prompts():
    conn = FakeConn(prompt_rows=[{"id": "11111111-1111-1111-1111-111111111111"}])
    service = PromptCascadeDeletionService(FakePool(conn))

    result = await service.delete_many(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ["11111111-1111-1111-1111-111111111111"],
    )

    tables = [call[0] for call in conn.execute_calls]
    assert "FOR UPDATE" in conn.fetch_calls[0][0]
    assert "DELETE FROM geo_sentiment_themes" in tables[0]
    assert "DELETE FROM geo_sentiment_results" in tables[1]
    assert "DELETE FROM geo_citations" in tables[2]
    assert "DELETE FROM geo_product_mentions" in tables[3]
    assert "DELETE FROM geo_brand_mentions" in tables[4]
    assert "DELETE FROM geo_results" in tables[5]
    assert "DELETE FROM geo_tasks" in tables[6]
    assert "DELETE FROM geo_client_prompts" in tables[7]
    assert result.deleted_prompts == 1
    assert result.deleted_results == 7
    assert result.deleted_tasks == 8


@pytest.mark.anyio
async def test_cascade_delete_ignores_prompt_ids_outside_client():
    conn = FakeConn(prompt_rows=[])
    service = PromptCascadeDeletionService(FakePool(conn))

    result = await service.delete_many(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ["22222222-2222-2222-2222-222222222222"],
    )

    assert result.deleted_prompts == 0
    assert conn.execute_calls == []


@pytest.mark.anyio
async def test_cascade_delete_can_run_inside_caller_owned_transaction():
    conn = FakeConn(prompt_rows=[{"id": "11111111-1111-1111-1111-111111111111"}])
    service = PromptCascadeDeletionService(FakePool(conn))

    result = await service.delete_many_on_connection(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        conn,
        ["11111111-1111-1111-1111-111111111111"],
    )

    assert result.deleted_prompts == 1
    assert len(conn.fetch_calls) == 1


@pytest.mark.anyio
async def test_cascade_delete_rolls_back_entire_batch_on_downstream_failure():
    class FailingConn(FakeConn):
        def __init__(self):
            super().__init__([{"id": "11111111-1111-1111-1111-111111111111"}])
            self.tx_events = []

        def transaction(self):
            return FakeTransaction(self.tx_events)

        async def execute(self, sql, *args):
            await super().execute(sql, *args)
            if "geo_citations" in sql:
                raise RuntimeError("citation delete failed")
            return "DELETE 1"

    conn = FailingConn()
    service = PromptCascadeDeletionService(FakePool(conn))

    with pytest.raises(RuntimeError, match="citation delete failed"):
        await service.delete_many(
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            ["11111111-1111-1111-1111-111111111111"],
        )

    assert conn.tx_events == ["begin", "rollback"]
    assert not any("DELETE FROM geo_client_prompts" in sql for sql, _ in conn.execute_calls)
