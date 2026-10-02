import pytest

from src.pipeline.phase3_write import _prompt_exists_for_client
from src.parsers.sentiment_parser import (
    _prompt_exists_for_client as sentiment_prompt_exists,
)


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
async def test_phase3_prompt_guard_true():
    conn = FakeConn(True)
    assert await _prompt_exists_for_client(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )
    assert "FOR KEY SHARE" in conn.calls[0][0]


@pytest.mark.anyio
async def test_phase3_prompt_guard_false():
    assert not await _prompt_exists_for_client(
        FakeConn(None),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )


@pytest.mark.anyio
async def test_sentiment_prompt_guard_true():
    conn = FakeConn(True)
    assert await sentiment_prompt_exists(
        conn,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )
    assert "FOR KEY SHARE" in conn.calls[0][0]


@pytest.mark.anyio
async def test_sentiment_prompt_guard_false():
    assert not await sentiment_prompt_exists(
        FakeConn(None),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "11111111-1111-1111-1111-111111111111",
    )
