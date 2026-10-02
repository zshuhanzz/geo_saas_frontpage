import asyncio
import json
import os
from urllib.parse import urlsplit
from google.api_core.exceptions import AlreadyExists, NotFound
from google.api_core.retry import Retry
from google.cloud import scheduler_v1
import logging

logger = logging.getLogger(__name__)

def _create_scheduler_client():
    """Build the Scheduler client with a stable, explicitly selected transport.

    The Admin image is rebuilt independently from feature scope.  Leaving the
    transport implicit allowed a transitive gRPC upgrade to change production
    write behaviour even though Scheduler code had not changed.  REST uses the
    same official SDK and IAM identity, while avoiding that transport-specific
    regression.
    """
    transport = os.environ.get("SCHEDULER_TRANSPORT", "rest").strip() or "rest"
    return scheduler_v1.CloudSchedulerClient(transport=transport)


# Initialize GCP Scheduler Client
try:
    scheduler_client = _create_scheduler_client()
except Exception as e:
    logger.warning(f"Could not initialize CloudSchedulerClient. Make sure GOOGLE_APPLICATION_CREDENTIALS is set. Error: {e}")
    scheduler_client = None

# Read from GCP_PROJECT_ID (consistent with Terraform env naming)
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
LOCATION = os.environ.get("GCP_REGION", os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
ADMIN_API_URL = os.environ.get("ADMIN_API_URL", "")
SERVICE_ACCOUNT_EMAIL = os.environ.get("INVOKER_SERVICE_ACCOUNT", "")

# Default timezone: Asia/Shanghai (China Standard Time)
DEFAULT_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Shanghai")
SCHEDULER_READ_TIMEOUT_SECONDS = 5.0
SCHEDULER_WRITE_TIMEOUT_SECONDS = 20.0
SCHEDULER_WRITE_RETRY = Retry(
    initial=0.5,
    maximum=2.0,
    multiplier=2.0,
    deadline=30.0,
)


class SchedulerOwnershipError(RuntimeError):
    """A legacy short-name job does not prove ownership by this Workspace."""


def _get_short_id(client_id: str) -> str:
    """Extract first 8 characters of the UUID for short naming."""
    return client_id.split("-")[0] if "-" in client_id else client_id[:8]


def _get_legacy_job_name(client_id: str, job_type: str) -> str:
    """Return the pre-migration short scheduler name."""
    return (
        f"projects/{PROJECT_ID}/locations/{LOCATION}/jobs/"
        f"geo-{job_type}-{_get_short_id(client_id)}"
    )


def _get_primary_job_name(client_id: str, job_type: str) -> str:
    """Return the established production job identity used by Admin."""
    return _get_legacy_job_name(client_id, job_type)


def _get_job_name(client_id: str, job_type: str) -> str:
    """Return the full-UUID compatibility name created by a prior regression."""
    return (
        f"projects/{PROJECT_ID}/locations/{LOCATION}/jobs/"
        f"geo-{job_type}-{client_id}"
    )


_JOB_TYPE_LABELS = {
    "collector": "Collector",
    "analyzer": "Analyzer",
    "llm_discovery": "LLM Discovery",
}


def _get_job_description(client_id: str, job_type: str) -> str:
    """Generate descriptive job description with full UUID."""
    type_label = _JOB_TYPE_LABELS.get(job_type, job_type.title())
    return f"GEO {type_label} for client {client_id}"


def _body_has_exact_client_id(body: object, client_id: str) -> bool:
    if not body:
        return False
    if isinstance(body, str):
        raw = body
    elif isinstance(body, (bytes, bytearray)):
        try:
            raw = bytes(body).decode("utf-8")
        except UnicodeDecodeError:
            return False
    else:
        return False
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return False

    def contains(value: object) -> bool:
        if isinstance(value, dict):
            return any(
                (key == "client_id" and child == client_id) or contains(child)
                for key, child in value.items()
            )
        if isinstance(value, list):
            return any(contains(child) for child in value)
        return False

    return contains(payload)


def _legacy_job_is_owned(job: object, client_id: str, job_type: str) -> bool:
    """Verify ambiguous legacy ownership from description and HTTP target."""
    if getattr(job, "description", None) != _get_job_description(client_id, job_type):
        return False
    target = getattr(job, "http_target", None)
    if target is None:
        return False
    uri = str(getattr(target, "uri", "") or "")
    expected_path = f"/api/clients/{client_id}/jobs/{job_type}/run"
    uri_owned = bool(uri) and urlsplit(uri).path.endswith(expected_path)
    return uri_owned or _body_has_exact_client_id(getattr(target, "body", None), client_id)


def _get_verified_legacy_job(
    client_id: str,
    job_type: str,
    *,
    reject_mismatch: bool,
) -> tuple[str, object] | None:
    legacy_name = _get_legacy_job_name(client_id, job_type)
    try:
        legacy_job = scheduler_client.get_job(
            name=legacy_name,
            retry=None,
            timeout=SCHEDULER_READ_TIMEOUT_SECONDS,
        )
    except NotFound:
        return None
    if not _legacy_job_is_owned(legacy_job, client_id, job_type):
        message = (
            f"Legacy scheduler job {legacy_name} does not belong to Workspace "
            f"{client_id}"
        )
        if reject_mismatch:
            raise SchedulerOwnershipError(message)
        logger.warning(message)
        return None
    return legacy_name, legacy_job


def _get_actionable_job_name(client_id: str, job_type: str) -> str:
    primary = _get_verified_legacy_job(
        client_id,
        job_type,
        reject_mismatch=True,
    )
    if primary is not None:
        return primary[0]

    compatibility_name = _get_job_name(client_id, job_type)
    try:
        scheduler_client.get_job(
            name=compatibility_name,
            retry=None,
            timeout=SCHEDULER_READ_TIMEOUT_SECONDS,
        )
        return compatibility_name
    except NotFound:
        raise


def _delete_verified_legacy_job(
    client_id: str,
    job_type: str,
    *,
    reject_mismatch: bool,
) -> None:
    legacy = _get_verified_legacy_job(
        client_id,
        job_type,
        reject_mismatch=reject_mismatch,
    )
    if legacy is None:
        return
    scheduler_client.delete_job(
        name=legacy[0],
        retry=None,
        timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
    )


def _sync_scheduler_job_blocking(
    client_id: str,
    job_type: str,
    schedule: str | None = None,
    is_paused: bool = False,
) -> None:
    """
    Creates, updates, pauses, or resumes a Cloud Scheduler job for a specific client.
    job_type should be 'collector' or 'analyzer'.
    If schedule is None or empty, tries to delete the existing job.
    """
    if not scheduler_client:
        raise RuntimeError("CloudSchedulerClient is not initialized")

    if not PROJECT_ID:
        raise RuntimeError("GCP_PROJECT_ID is not configured")

    compatibility_name = _get_job_name(client_id, job_type)

    # Existing verified short-name jobs remain authoritative. Ordinary cron
    # edits update the selected job in place; name migration is a separate
    # maintenance concern and must never create/delete jobs behind a UI edit.
    primary = _get_verified_legacy_job(
        client_id,
        job_type,
        reject_mismatch=True,
    )
    existing_job = primary[1] if primary is not None else None
    job_name = primary[0] if primary is not None else _get_primary_job_name(
        client_id,
        job_type,
    )

    if existing_job is None:
        try:
            existing_job = scheduler_client.get_job(
                name=compatibility_name,
                retry=None,
                timeout=SCHEDULER_READ_TIMEOUT_SECONDS,
            )
            job_name = compatibility_name
        except NotFound:
            existing_job = None
    
    if not schedule:
        if existing_job is None:
            return
        try:
            scheduler_client.delete_job(
                name=job_name,
                retry=None,
                timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
            )
            logger.info(f"Deleted scheduler job {job_name} (schedule cleared)")
        except NotFound:
            pass
        return

    if not ADMIN_API_URL:
        raise RuntimeError("ADMIN_API_URL is not configured")

    # Define the HTTP target (our manual run endpoint)
    uri = f"{ADMIN_API_URL}/api/clients/{client_id}/jobs/{job_type}/run"
    
    job = scheduler_v1.Job(
        name=job_name,
        description=_get_job_description(client_id, job_type),
        schedule=schedule,
        time_zone=DEFAULT_TIMEZONE,
        http_target=scheduler_v1.HttpTarget(
            uri=uri,
            http_method=scheduler_v1.HttpMethod.POST,
            oidc_token=scheduler_v1.OidcToken(
                service_account_email=SERVICE_ACCOUNT_EMAIL,
                audience=ADMIN_API_URL.rstrip("/"),
            ) if SERVICE_ACCOUNT_EMAIL else None
        )
    )

    if existing_job is not None:
        # A schedule edit must not rewrite the HTTP target or OIDC token.  Apart
        # from being unnecessary, the wider mask made an otherwise ordinary
        # cron edit substantially slower and caused Scheduler 504 responses.
        update_mask = {"paths": ["schedule", "time_zone"]}
        scheduler_client.update_job(
            job=job,
            update_mask=update_mask,
            retry=SCHEDULER_WRITE_RETRY,
            timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
        )
        logger.info(f"Updated scheduler job {job_name} with schedule {schedule}")
        
        if is_paused and existing_job.state != scheduler_v1.Job.State.PAUSED:
            scheduler_client.pause_job(
                name=job_name,
                retry=None,
                timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
            )
        elif not is_paused and existing_job.state == scheduler_v1.Job.State.PAUSED:
            scheduler_client.resume_job(
                name=job_name,
                retry=None,
                timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
            )
    else:
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
        try:
            scheduler_client.create_job(
                parent=parent,
                job=job,
                retry=SCHEDULER_WRITE_RETRY,
                timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
            )
            logger.info(f"Created new scheduler job {job_name} with schedule {schedule}")
            if is_paused:
                scheduler_client.pause_job(
                    name=job_name,
                    retry=None,
                    timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
                )
        except AlreadyExists:
            # The first CreateJob attempt may have reached Scheduler even if
            # its response timed out. A bounded retry then sees the canonical
            # job and should be treated as successful idempotent creation.
            logger.info("Scheduler job %s already exists after create retry", job_name)
        except Exception as create_err:
            logger.exception(f"Failed to create scheduler job {job_name}: {create_err}")
            raise


async def sync_scheduler_job(
    client_id: str,
    job_type: str,
    schedule: str | None = None,
    is_paused: bool = False,
) -> None:
    """Synchronize one Scheduler job without blocking the FastAPI event loop."""
    await asyncio.to_thread(
        _sync_scheduler_job_blocking,
        client_id,
        job_type,
        schedule,
        is_paused,
    )


async def get_scheduler_job_status(client_id: str, job_type: str) -> dict:
    """Get the status of a specific scheduler job."""
    if not scheduler_client:
        return {"state": "UNKNOWN", "error": "CloudSchedulerClient not initialized"}

    job_name = _get_primary_job_name(client_id, job_type)
    try:
        try:
            primary = await asyncio.to_thread(
                _get_verified_legacy_job,
                client_id,
                job_type,
                reject_mismatch=True,
            )
            if primary is None:
                raise NotFound("primary scheduler job is absent")
            job_name, job = primary
        except NotFound:
            job_name = _get_job_name(client_id, job_type)
            job = await asyncio.to_thread(
                scheduler_client.get_job,
                name=job_name,
                retry=None,
                timeout=SCHEDULER_READ_TIMEOUT_SECONDS,
            )
        return {
            "state": scheduler_v1.Job.State(job.state).name,
            "schedule": job.schedule,
            "time_zone": job.time_zone,
            "last_attempt_time": str(job.last_attempt_time) if job.last_attempt_time else None,
            "next_run_time": str(job.schedule_time) if job.schedule_time else None,
        }
    except NotFound:
        return {"state": "NOT_FOUND"}
    except SchedulerOwnershipError:
        logger.exception("Refused unowned legacy scheduler job %s", job_name)
        return {"state": "UNKNOWN", "error": "Scheduler ownership mismatch"}
    except Exception:
        logger.exception("Failed to read scheduler job status for %s", job_name)
        return {"state": "UNKNOWN", "error": "Scheduler status unavailable"}


async def pause_scheduler_job(client_id: str, job_type: str):
    """Pause a scheduler job."""
    if not scheduler_client:
        raise RuntimeError("CloudSchedulerClient not initialized")
    job_name = await asyncio.to_thread(
        _get_actionable_job_name,
        client_id,
        job_type,
    )
    await asyncio.to_thread(
        scheduler_client.pause_job,
        name=job_name,
        retry=SCHEDULER_WRITE_RETRY,
        timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
    )
    logger.info(f"Paused scheduler job {job_name}")


async def resume_scheduler_job(client_id: str, job_type: str):
    """Resume a paused scheduler job."""
    if not scheduler_client:
        raise RuntimeError("CloudSchedulerClient not initialized")
    job_name = await asyncio.to_thread(
        _get_actionable_job_name,
        client_id,
        job_type,
    )
    await asyncio.to_thread(
        scheduler_client.resume_job,
        name=job_name,
        retry=SCHEDULER_WRITE_RETRY,
        timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
    )
    logger.info(f"Resumed scheduler job {job_name}")


async def force_run_scheduler_job(client_id: str, job_type: str):
    """Force-run a scheduler job immediately (one-off execution)."""
    if not scheduler_client:
        raise RuntimeError("CloudSchedulerClient not initialized")
    job_name = await asyncio.to_thread(
        _get_actionable_job_name,
        client_id,
        job_type,
    )
    await asyncio.to_thread(
        scheduler_client.run_job,
        name=job_name,
        retry=SCHEDULER_WRITE_RETRY,
        timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
    )
    logger.info(f"Force-ran scheduler job {job_name}")


async def delete_scheduler_job(client_id: str, job_type: str) -> None:
    """Delete one scheduler job and surface operational failures.

    ``sync_scheduler_job`` keeps its best-effort behavior for ordinary config
    editing. Workspace deletion needs a strict variant: it may ignore an
    already-absent job, but it must not claim success when Scheduler is
    unavailable or a real API error occurs.
    """
    if not scheduler_client:
        raise RuntimeError("CloudSchedulerClient not initialized")
    if not PROJECT_ID:
        raise RuntimeError("GCP_PROJECT_ID is not configured")

    primary = await asyncio.to_thread(
        _get_verified_legacy_job,
        client_id,
        job_type,
        reject_mismatch=True,
    )
    compatibility_name = _get_job_name(client_id, job_type)
    try:
        await asyncio.to_thread(
            scheduler_client.delete_job,
            name=compatibility_name,
            retry=None,
            timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
        )
    except NotFound:
        pass
    if primary is not None:
        try:
            await asyncio.to_thread(
                scheduler_client.delete_job,
                name=primary[0],
                retry=None,
                timeout=SCHEDULER_WRITE_TIMEOUT_SECONDS,
            )
        except NotFound:
            pass
    logger.info("Deleted Workspace scheduler jobs for %s/%s", client_id, job_type)


async def stop_all_scheduler_jobs(client_id: str) -> None:
    """Strictly remove every Workspace-owned recurring scheduler job."""
    for job_type in ("collector", "analyzer", "llm_discovery"):
        await delete_scheduler_job(client_id, job_type)
