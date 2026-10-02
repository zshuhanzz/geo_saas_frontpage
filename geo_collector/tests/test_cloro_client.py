"""
Unit tests for `src.clients.cloro.CloroService`.

Phase 2.5a: refreshed alongside the DB-pool migration. The previous test file
referenced `src.services.cloro_client` and `src.config` — both stale paths
since the V2 module restructure. These tests now hit the actual current
locations and the V2 `dispatch_task_async` payload shape (nested
`payload`/`webhook` blocks, `taskType`, `idempotencyKey`).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.clients.cloro import CloroService


@pytest.fixture
def mock_settings():
    """Patch the module-level `settings` singleton inside `src.clients.cloro`."""
    with patch("src.clients.cloro.settings") as mock:
        mock.CLORO_BASE_URL = "https://api.mock.cloro"
        mock.CLORO_API_KEY = "mock_key"
        mock.WEBHOOK_PUBLIC_URL = "https://mock.webhook"
        yield mock


def test_strategy_routing(mock_settings):
    service = CloroService()

    # Sync endpoint suffixes (used by /v1/monitor/*)
    assert service._get_strategy("chatgpt").get_sync_endpoint_suffix() == "/v1/monitor/chatgpt"
    assert service._get_strategy("gemini").get_sync_endpoint_suffix() == "/v1/monitor/gemini"
    assert service._get_strategy("aimode").get_sync_endpoint_suffix() == "/v1/monitor/aimode"
    assert service._get_strategy("perplexity").get_sync_endpoint_suffix() == "/v1/monitor/perplexity"
    assert service._get_strategy("aioverview").get_sync_endpoint_suffix() == "/v1/monitor/google"
    assert service._get_strategy("ai-overview").get_sync_endpoint_suffix() == "/v1/monitor/google"
    assert service._get_strategy("google_ai_overview").get_sync_endpoint_suffix() == "/v1/monitor/google"
    # Case-insensitive
    assert service._get_strategy("ChatGPT").get_sync_endpoint_suffix() == "/v1/monitor/chatgpt"
    # Unknown platform falls back to ChatGPT
    assert service._get_strategy("unknown_platform").get_sync_endpoint_suffix() == "/v1/monitor/chatgpt"


def test_construct_webhook_url(mock_settings):
    service = CloroService()
    url = service._construct_webhook_url("task-123", call_index=2)
    assert url == "https://mock.webhook/callback/cloro?task_id=task-123&call_index=2"


@pytest.mark.asyncio
async def test_dispatch_task_async_success(mock_settings):
    service = CloroService()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.json.return_value = {"task": {"id": "cloro-abc"}}
    mock_client.post.return_value = mock_response

    task = {
        "task_id": "123e4567-e89b-12d3-a456-426614174000",
        "platform": "gemini",
        "final_prompt": "Hello AI",
        "country": "US",
    }

    cloro_id = await service.dispatch_task_async(mock_client, task, call_index=1)
    assert cloro_id == "cloro-abc"

    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://api.mock.cloro/v1/async/task"
    assert kwargs["headers"]["Authorization"] == "Bearer mock_key"
    assert kwargs["json"]["taskType"] == "GEMINI"
    assert kwargs["json"]["payload"]["prompt"] == "Hello AI"
    assert kwargs["json"]["payload"]["country"] == "US"
    assert kwargs["json"]["webhook"]["url"].endswith("call_index=1")


@pytest.mark.asyncio
async def test_dispatch_ai_overview_uses_google_search_payload(mock_settings):
    service = CloroService()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.json.return_value = {"task": {"id": "cloro-google"}}
    mock_client.post.return_value = mock_response

    task = {
        "task_id": "123e4567-e89b-12d3-a456-426614174001",
        "platform": "aioverview",
        "final_prompt": "What is the best robot vacuum?",
        "country": "US",
    }

    cloro_id = await service.dispatch_task_async(mock_client, task, call_index=3)
    assert cloro_id == "cloro-google"

    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://api.mock.cloro/v1/async/task"
    assert kwargs["json"]["taskType"] == "GOOGLE"
    assert kwargs["json"]["payload"]["query"] == "What is the best robot vacuum?"
    assert "prompt" not in kwargs["json"]["payload"]
    assert kwargs["json"]["payload"]["include"] == {"aioverview": {"markdown": True}}
    assert kwargs["json"]["webhook"]["url"].endswith("call_index=3")


def test_perplexity_include_options_request_supported_assets(mock_settings):
    service = CloroService()
    include = service._get_strategy("perplexity").get_default_include_options()
    assert include == {
        "html": False,
        "markdown": False,
        "rawResponse": False,
    }


@pytest.mark.asyncio
async def test_dispatch_task_async_failure(mock_settings):
    service = CloroService()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 500
    mock_response.text = "boom"
    mock_client.post.return_value = mock_response

    task = {
        "task_id": "00000000-0000-0000-0000-000000000000",
        "platform": "chatgpt",
        "final_prompt": "fail me",
    }

    cloro_id = await service.dispatch_task_async(mock_client, task)
    assert cloro_id is None
