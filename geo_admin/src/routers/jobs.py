"""
Jobs Router - Manual trigger endpoints for Collector and Analyzer Cloud Run Jobs.

These endpoints are called:
1. By GCP Cloud Scheduler (via HTTP target) for automated periodic runs
2. By Admin UI for manual one-off runs

Both endpoints use the Cloud Run Jobs API to execute:
- geo-prompt-expander (Collector): Expands client prompts into final prompts + tasks
- geo-analyzer (Analyzer): Processes results to extract mentions + citations
- geo-analyzer-llm-batch-discovery (LLM Discovery): Offline LLM extraction of
  new brand/product candidates from recent geo_results (v1.2 Phase 6).
"""
import logging
import os
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class JobTriggerOut(BaseModel):
    """Result payload for the three job-trigger endpoints. The two branches
    (live trigger vs. local-mode skip) populate slightly different fields, so
    everything beyond ``status`` / ``job_name`` / ``client_id`` is optional."""

    status: str
    job_name: str
    client_id: str
    args: Optional[List[str]] = None
    operation: Optional[str] = None
    app_env: Optional[str] = None
    message: Optional[str] = None
    batch_id: Optional[str] = None


class AnalyzerJobTriggerIn(BaseModel):
    batch_id: Optional[str] = None

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
REGION = os.environ.get("GCP_REGION", os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))

# ============================================================================
# Local-mode safety valve (added 2026-04-20 after prod blast-radius incident)
# ============================================================================
# When APP_ENV=local, the admin API is running on a developer laptop with
# ADC pointing at the production GCP project. Without this guard, clicking
# "Run X Now" in the Admin UI fires a real Cloud Run Job on prod that
# connects to prod Cloud SQL — a 1-click prod blast radius.
#
# In local mode we refuse to invoke Cloud Run Jobs and return a structured
# stub response. Developers must run the analyzer / collector / llm-discovery
# modules locally against local PG (see reference_local_dev_ui_automation.md)
# for end-to-end verification of the parsing pipeline.
#
# Production (Cloud Run) deployments never set APP_ENV=local, so the guard
# is inert there.
# ============================================================================
APP_ENV = os.environ.get("APP_ENV", "production").strip().lower()
_IS_LOCAL_MODE = APP_ENV in ("local", "dev", "development")

# Map job_type to Cloud Run Job name
CLOUD_RUN_JOB_NAMES = {
    "collector": "geo-prompt-expander",
    "analyzer": "geo-analyzer",
    "llm_discovery": "geo-analyzer-llm-batch-discovery",
}

# Extra CLI args passed to each job's container entrypoint.
# Collector/Analyzer consume CLIENT_ID from env; LLM Discovery requires it as a CLI flag.
EXTRA_ARGS = {
    "llm_discovery": ["--window-hours", "24"],
}


async def _trigger_cloud_run_job(
    job_name: str,
    client_id: str,
    extra_args: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
):
    """
    Execute a Cloud Run Job with CLIENT_ID env override.
    Uses the google-cloud-run SDK v2 API.

    If ``extra_args`` is provided, passes them as CLI args to the container
    (alongside the default command defined in the Cloud Run Job).
    ``--client-id <id>`` is always prepended so jobs whose entry module
    expects a flag (e.g. ``python -m src.jobs.llm_batch_discovery``) work
    uniformly with the env-based ones (collector/analyzer).

    In local/dev mode (APP_ENV=local), returns a stub response instead of
    invoking the real Cloud Run Job — prevents prod blast radius from
    developer laptops whose ADC credentials happen to target the prod
    project.
    """
    if _IS_LOCAL_MODE:
        logger.warning(
            "[JOBS] APP_ENV=%s — skipping Cloud Run Job '%s' for client %s. "
            "Run the job module locally against local PG instead.",
            APP_ENV, job_name, client_id,
        )
        return {
            "status": "skipped_local_mode",
            "app_env": APP_ENV,
            "job_name": job_name,
            "client_id": client_id,
            "message": (
                "Local mode: Cloud Run Job trigger suppressed to protect "
                "production. Run the job locally: "
                f"cd {job_name.replace('geo-', 'geo_')} && "
                f"CLIENT_ID={client_id} .venv/bin/python main.py"
            ),
        }

    try:
        from google.cloud import run_v2
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="google-cloud-run package not installed. Run: pip install google-cloud-run"
        )

    try:
        jobs_client = run_v2.JobsAsyncClient()
        # Cloud Run v2 override semantics (inferred from 400 responses):
        #   clear_args=False + empty args     → use image/template default args
        #   clear_args=False + non-empty args → replace default args entirely
        #   clear_args=True  + empty args     → strip all args (usually breaks)
        #   clear_args=True  + non-empty args → 400 (invalid combination)
        # So we always keep clear_args=False. When no CLI extras are needed
        # (expander / analyzer — CLIENT_ID env is enough) we pass empty args,
        # and the Dockerfile / template defaults kick in. When the caller
        # supplies extras (e.g. llm_discovery needs --client-id + --window-hours)
        # we include them; the job template's `command` still carries the
        # module path so Python starts correctly.
        if extra_args:
            override_args = ["--client-id", client_id] + extra_args
        else:
            override_args = []
        env_vars = [run_v2.EnvVar(name="CLIENT_ID", value=client_id)]
        for name, value in (env_overrides or {}).items():
            env_vars.append(run_v2.EnvVar(name=name, value=value))
        container_override = run_v2.RunJobRequest.Overrides.ContainerOverride(
            env=env_vars,
            args=override_args,
            clear_args=False,
        )
        request = run_v2.RunJobRequest(
            name=f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{job_name}",
            overrides=run_v2.RunJobRequest.Overrides(
                container_overrides=[container_override]
            )
        )
        operation = await jobs_client.run_job(request=request)
        logger.info(f"[JOBS] Triggered Cloud Run Job '{job_name}' for client {client_id} args={override_args}")
        return {
            "status": "triggered",
            "job_name": job_name,
            "client_id": client_id,
            "args": override_args,
            "batch_id": (env_overrides or {}).get("ANALYZER_BATCH_ID"),
            "operation": operation.metadata.name if hasattr(operation, 'metadata') else str(operation),
        }
    except Exception as e:
        logger.error(f"[JOBS] Failed to trigger Cloud Run Job '{job_name}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger {job_name}: {str(e)}")


@router.post("/clients/{client_id}/jobs/collector/run", response_model=JobTriggerOut)
async def run_collector_job(client_id: UUID) -> JobTriggerOut:
    """
    Trigger the geo-prompt-expander Cloud Run Job for a specific client.
    
    This will:
    1. Read active client prompts from the database
    2. Generate final prompts (via Gemini LLM fusion)
    3. Create geo_tasks entries
    4. Publish tasks to Pub/Sub for dispatch to Cloro API
    """
    logger.info(f"[JOBS] Collector job triggered for client {client_id}")
    return JobTriggerOut(**await _trigger_cloud_run_job(
        CLOUD_RUN_JOB_NAMES["collector"],
        str(client_id)
    ))


@router.post("/clients/{client_id}/jobs/analyzer/run", response_model=JobTriggerOut)
async def run_analyzer_job(
    client_id: UUID,
    data: Optional[AnalyzerJobTriggerIn] = None,
) -> JobTriggerOut:
    """
    Trigger the geo-analyzer Cloud Run Job for a specific client.

    This will:
    1. Read unanalyzed geo_results for the client
    2. Extract brand + product mentions (v1.2 dual-mode tracking) using
       the client's brands / peers / tracked products
    3. Parse citation sources with citation_role attribution
    4. Write structured data to geo_brand_mentions, geo_product_mentions,
       and geo_citations tables
    """
    batch_id = (data.batch_id.strip() if data and data.batch_id else None)
    logger.info(
        "[JOBS] Analyzer job triggered for client %s | batch_id=%s",
        client_id,
        batch_id or "(auto)",
    )
    env_overrides = {"ANALYZER_BATCH_ID": batch_id} if batch_id else None
    return JobTriggerOut(**await _trigger_cloud_run_job(
        CLOUD_RUN_JOB_NAMES["analyzer"],
        str(client_id),
        env_overrides=env_overrides,
    ))


@router.post("/clients/{client_id}/jobs/llm_discovery/run", response_model=JobTriggerOut)
async def run_llm_discovery_job(client_id: UUID) -> JobTriggerOut:
    """
    Trigger the geo-analyzer-llm-batch-discovery Cloud Run Job for a specific client.

    This is the v1.2 Phase 6 offline batch that:
    1. Reads recent geo_results text (past --window-hours, default 24)
    2. Calls Gemini Flash once with the full batch + the client's known
       brands/peers/products config
    3. Writes extracted candidates (未配置品牌 / 型号 / SKU) to
       geo_settings_candidates with source='llm_batch'

    The Admin UI's "Candidates" review surface picks them up for the user to
    accept/reject.
    """
    logger.info(f"[JOBS] LLM Discovery job triggered for client {client_id}")
    return JobTriggerOut(**await _trigger_cloud_run_job(
        CLOUD_RUN_JOB_NAMES["llm_discovery"],
        str(client_id),
        extra_args=EXTRA_ARGS["llm_discovery"],
    ))
