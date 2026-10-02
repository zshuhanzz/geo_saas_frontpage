import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.cloro_client import CloroService
from src.config import Settings

# Mock settings to avoid needing a real .env file during tests
@pytest.fixture
def mock_settings():
    with patch("src.services.cloro_client.settings") as mock_settings:
        mock_settings.CLORO_BASE_URL = "https://api.mock.cloro"
        mock_settings.CLORO_API_KEY = "mock_key"
        mock_settings.WEBHOOK_PUBLIC_URL = "https://mock.webhook"
        yield mock_settings

@pytest.mark.asyncio
async def test_construct_url(mock_settings):
    service = CloroService()
    
    assert service._construct_url("chatgpt") == "https://api.mock.cloro/v1/monitor/chatgpt"
    assert service._construct_url("gemini") == "https://api.mock.cloro/v1/monitor/gemini"
    # Test case insensitivity
    assert service._construct_url("ChatGPT") == "https://api.mock.cloro/v1/monitor/chatgpt"
    # Test fallback
    assert service._construct_url("unknown_platform") == "https://api.mock.cloro/v1/monitor/chatgpt"

@pytest.mark.asyncio
async def test_dispatch_task_success(mock_settings):
    service = CloroService()
    
    # Mock httpx client
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response

    task = {
        "task_id": "123e4567-e89b-12d3-a456-426614174000",
        "platform": "gemini",
        "prompt_text": "Hello AI",
        "country": "US"
    }

    result = await service.dispatch_task(mock_client, task)

    assert result is True
    
    # Verify the API call
    expected_url = "https://api.mock.cloro/v1/monitor/gemini"
    expected_payload = {
        "prompt": "Hello AI",
        "webhook": "https://mock.webhook/callback/cloro?task_id=123e4567-e89b-12d3-a456-426614174000",
        "country": "US"
    }
    
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == expected_url
    assert call_args[1]["json"] == expected_payload
    assert call_args[1]["headers"]["Authorization"] == "Bearer mock_key"

@pytest.mark.asyncio
async def test_dispatch_task_failure(mock_settings):
    service = CloroService()
    
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    # Simulate HTTP error
    mock_client.post.side_effect = httpx.HTTPStatusError(
        "400 Bad Request", request=MagicMock(), response=MagicMock(status_code=400)
    )

    task = {
        "task_id": "uuid",
        "platform": "chatgpt",
        "prompt_text": "fail me"
    }

    result = await service.dispatch_task(mock_client, task)
    assert result is False