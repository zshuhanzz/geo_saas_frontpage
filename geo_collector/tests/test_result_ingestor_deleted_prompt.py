import pytest

from src.result_ingestor import _prompt_exists_for_client


class FakeConn:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return self.value


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_prompt_exists_for_client_returns_true():
    conn = FakeConn(True)
    ok = await _prompt_exists_for_client(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )

    assert ok is True
    assert "geo_client_prompts" in conn.calls[0][0]
    assert "FOR KEY SHARE" in conn.calls[0][0]


@pytest.mark.anyio
async def test_prompt_exists_for_client_returns_false():
    conn = FakeConn(None)
    ok = await _prompt_exists_for_client(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )

    assert ok is False
