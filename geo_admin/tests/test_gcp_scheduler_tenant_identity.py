from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.api_core.exceptions import NotFound

from services import gcp_scheduler


CLIENT_A = "12345678-1111-1111-1111-111111111111"
CLIENT_B = "12345678-2222-2222-2222-222222222222"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _legacy_job(client_id: str, job_type: str = "collector"):
    return SimpleNamespace(
        description=gcp_scheduler._get_job_description(client_id, job_type),
        http_target=SimpleNamespace(
            uri=f"https://admin.example/api/clients/{client_id}/jobs/{job_type}/run",
            body=b"",
        ),
        state=gcp_scheduler.scheduler_v1.Job.State.ENABLED,
    )


def test_scheduler_client_uses_rest_transport_by_default(monkeypatch):
    created = []

    monkeypatch.delenv("SCHEDULER_TRANSPORT", raising=False)
    monkeypatch.setattr(
        gcp_scheduler.scheduler_v1,
        "CloudSchedulerClient",
        lambda **kwargs: created.append(kwargs) or object(),
    )

    client = gcp_scheduler._create_scheduler_client()

    assert client is not None
    assert created == [{"transport": "rest"}]


@pytest.mark.parametrize("job_type", ["collector", "analyzer", "llm_discovery"])
def test_primary_scheduler_names_match_the_existing_short_name_contract(
    monkeypatch,
    job_type,
):
    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "LOCATION", "region")

    name_a = gcp_scheduler._get_primary_job_name(CLIENT_A, job_type)
    name_b = gcp_scheduler._get_primary_job_name(CLIENT_B, job_type)

    assert name_a == name_b
    assert name_a.endswith(f"geo-{job_type}-12345678")


@pytest.mark.anyio
async def test_colliding_legacy_name_cannot_pause_another_workspace_job(monkeypatch):
    calls: list[tuple[str, str]] = []

    class Client:
        def get_job(self, *, name, **_kwargs):
            calls.append(("get", name))
            if name == gcp_scheduler._get_job_name(CLIENT_B, "collector"):
                raise NotFound("canonical missing")
            return _legacy_job(CLIENT_A)

        def pause_job(self, *, name, **_kwargs):
            calls.append(("pause", name))

    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client())

    with pytest.raises(gcp_scheduler.SchedulerOwnershipError):
        await gcp_scheduler.pause_scheduler_job(CLIENT_B, "collector")

    assert not any(action == "pause" for action, _name in calls)


@pytest.mark.anyio
async def test_owned_legacy_job_can_be_paused_after_exact_identity_verification(monkeypatch):
    paused: list[str] = []

    class Client:
        def get_job(self, *, name, **_kwargs):
            if name == gcp_scheduler._get_job_name(CLIENT_A, "collector"):
                raise NotFound("canonical missing")
            return _legacy_job(CLIENT_A)

        def pause_job(self, *, name, **_kwargs):
            paused.append(name)

    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client())

    await gcp_scheduler.pause_scheduler_job(CLIENT_A, "collector")

    assert paused == [gcp_scheduler._get_legacy_job_name(CLIENT_A, "collector")]


@pytest.mark.anyio
async def test_sync_updates_verified_legacy_job_in_place(monkeypatch):
    created: list[object] = []
    deleted: list[str] = []
    updated: list[tuple[object, object, object]] = []

    class Client:
        def get_job(self, *, name, **_kwargs):
            if name == gcp_scheduler._get_job_name(CLIENT_A, "collector"):
                raise NotFound("canonical missing")
            return _legacy_job(CLIENT_A)

        def create_job(self, *, parent, job, **_kwargs):
            created.append(job)

        def update_job(self, *, job, update_mask, retry, **_kwargs):
            updated.append((job, update_mask, retry))

        def delete_job(self, *, name, **_kwargs):
            deleted.append(name)

    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "LOCATION", "region")
    monkeypatch.setattr(gcp_scheduler, "ADMIN_API_URL", "https://admin.example")
    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client())

    await gcp_scheduler.sync_scheduler_job(
        CLIENT_A,
        "collector",
        "0 * * * *",
    )

    assert created == []
    assert deleted == []
    assert len(updated) == 1
    assert updated[0][0].name == gcp_scheduler._get_legacy_job_name(CLIENT_A, "collector")
    assert updated[0][0].schedule == "0 * * * *"
    assert updated[0][1]["paths"] == ["schedule", "time_zone"]
    assert updated[0][2] is not None


@pytest.mark.anyio
async def test_sync_updates_existing_canonical_job_in_place(monkeypatch):
    canonical = _legacy_job(CLIENT_A)
    canonical.name = gcp_scheduler._get_job_name(CLIENT_A, "collector")
    updated: list[object] = []

    class Client:
        def get_job(self, *, name, **_kwargs):
            if name == gcp_scheduler._get_legacy_job_name(CLIENT_A, "collector"):
                raise NotFound("legacy missing")
            return canonical

        def update_job(self, *, job, update_mask, **_kwargs):
            updated.append(job)

    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "LOCATION", "region")
    monkeypatch.setattr(gcp_scheduler, "ADMIN_API_URL", "https://admin.example")
    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client())

    await gcp_scheduler.sync_scheduler_job(CLIENT_A, "collector", "5 * * * *")

    assert len(updated) == 1
    assert updated[0].name == gcp_scheduler._get_job_name(CLIENT_A, "collector")


@pytest.mark.anyio
async def test_sync_creates_short_job_only_when_no_existing_job_exists(monkeypatch):
    created: list[tuple[object, object]] = []

    class Client:
        def get_job(self, *, name, **_kwargs):
            raise NotFound("missing")

        def create_job(self, *, parent, job, retry, **_kwargs):
            created.append((job, retry))

    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "LOCATION", "region")
    monkeypatch.setattr(gcp_scheduler, "ADMIN_API_URL", "https://admin.example")
    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client())

    await gcp_scheduler.sync_scheduler_job(CLIENT_A, "collector", "10 * * * *")

    assert len(created) == 1
    assert created[0][0].name == gcp_scheduler._get_primary_job_name(CLIENT_A, "collector")
    assert created[0][1] is not None


@pytest.mark.anyio
async def test_sync_refuses_to_reuse_short_job_with_mismatched_identity(monkeypatch):
    created: list[object] = []
    deleted: list[str] = []

    class Client:
        def get_job(self, *, name, **_kwargs):
            if name == gcp_scheduler._get_job_name(CLIENT_B, "collector"):
                raise NotFound("canonical missing")
            return _legacy_job(CLIENT_A)

        def create_job(self, *, parent, job, **_kwargs):
            created.append(job)

        def delete_job(self, *, name, **_kwargs):
            deleted.append(name)

    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "LOCATION", "region")
    monkeypatch.setattr(gcp_scheduler, "ADMIN_API_URL", "https://admin.example")
    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client())

    with pytest.raises(gcp_scheduler.SchedulerOwnershipError):
        await gcp_scheduler.sync_scheduler_job(
            CLIENT_B,
            "collector",
            "0 * * * *",
        )

    assert created == []
    assert deleted == []


@pytest.mark.anyio
async def test_strict_delete_refuses_mismatched_legacy_job(monkeypatch):
    delete_attempts: list[str] = []

    class Client:
        def get_job(self, *, name, **_kwargs):
            return _legacy_job(CLIENT_A)

        def delete_job(self, *, name, **_kwargs):
            delete_attempts.append(name)
            if name == gcp_scheduler._get_job_name(CLIENT_B, "collector"):
                raise NotFound("canonical missing")
            raise AssertionError("unowned legacy job must not be deleted")

    monkeypatch.setattr(gcp_scheduler, "PROJECT_ID", "project")
    monkeypatch.setattr(gcp_scheduler, "scheduler_client", Client())

    with pytest.raises(gcp_scheduler.SchedulerOwnershipError):
        await gcp_scheduler.delete_scheduler_job(CLIENT_B, "collector")

    assert delete_attempts == []
