from __future__ import annotations

import pytest
from google.api_core.exceptions import NotFound

from services import gcp_scheduler


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_status_distinguishes_absent_job_from_operational_failure(monkeypatch):
    class MissingClient:
        def get_job(self, **kwargs):
            raise NotFound("missing")

    monkeypatch.setattr(gcp_scheduler, "scheduler_client", MissingClient())
    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    assert await gcp_scheduler.get_scheduler_job_status("client", "collector") == {
        "state": "NOT_FOUND"
    }

    class BrokenClient:
        def get_job(self, **kwargs):
            raise RuntimeError("permission denied")

    monkeypatch.setattr(gcp_scheduler, "scheduler_client", BrokenClient())
    assert await gcp_scheduler.get_scheduler_job_status("client", "collector") == {
        "state": "UNKNOWN",
        "error": "Scheduler status unavailable",
    }


@pytest.mark.anyio
async def test_stop_all_scheduler_jobs_is_strict_and_covers_all_three_types(monkeypatch):
    calls = []

    async def delete(client_id: str, job_type: str):
        calls.append((client_id, job_type))

    monkeypatch.setattr(gcp_scheduler, "delete_scheduler_job", delete)
    await gcp_scheduler.stop_all_scheduler_jobs("workspace-id")

    assert calls == [
        ("workspace-id", "collector"),
        ("workspace-id", "analyzer"),
        ("workspace-id", "llm_discovery"),
    ]


@pytest.mark.anyio
async def test_delete_scheduler_job_ignores_only_not_found(monkeypatch):
    class Client:
        def __init__(self, error):
            self.error = error

        def delete_job(self, **kwargs):
            raise self.error

        def get_job(self, **kwargs):
            raise NotFound("legacy missing")

    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client(NotFound("missing")))
    await gcp_scheduler.delete_scheduler_job("client", "collector")

    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client(RuntimeError("denied")))
    with pytest.raises(RuntimeError, match="denied"):
        await gcp_scheduler.delete_scheduler_job("client", "collector")
