"""
Task router — core CRUD + execution endpoints for ``geo_agent_tasks``.

Phase 3A refactor (2026-04-25): this file used to be 3404 lines and bundled
templates / framework / preselect / strategy / export / HTML rendering all
together. Those concerns now live in dedicated sibling modules; this file
only owns task lifecycle: create / list / get / progress / update / run /
rename / delete, plus the pipeline registry that pipelines import on load.

Sibling routers under ``/api/agent/tasks``:
    - ``routers/templates.py``         — template + workflow_config CRUD-ish
    - ``routers/framework.py``         — framework hierarchy + metric discovery
    - ``routers/content_preselect.py`` — AI Preselect for Content wizard
    - ``routers/strategy.py``          — content strategy generation
    - ``routers/export.py``            — HTML export (delegates to services/report_renderer)

Public re-exports kept for backward-compat with ``pipelines/*`` modules:
    - ``register_pipeline(task_type, runner)``
    - ``_row_to_dict(row)``  (used by ``routers.export``)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from geo_common.services import (
    WorkspaceLifecycleMissing,
    WorkspaceWriteCoordinator,
)
from pydantic import BaseModel, ConfigDict, Field

from database import agent_workspace_lifecycle_session, get_pool
from dependencies.auth import AuthenticatedUser, require_client_access_if_present, require_current_user, user_identifier
from services.citation_analysis import run_citation_analysis
from services.reddit_research import (
    RedditResearchError,
    RedditTargetingContext,
    build_reddit_research_fingerprint,
    discover_reddit_context,
    recommend_subreddits,
    resolve_manual_subreddits,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/tasks", tags=["tasks"])

# Registry of pipeline runners — populated by pipeline modules on import
_pipeline_registry: dict[str, callable] = {}


async def _guarded_execute(pool, client_id: str, sql: str, *args):
    async def operation(conn):
        return await conn.execute(sql, *args)

    try:
        return await WorkspaceWriteCoordinator(pool).execute(client_id, operation)
    except WorkspaceLifecycleMissing as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc


def register_pipeline(task_type: str, runner: callable):
    """Register a pipeline runner for a task type.

    Called by ``pipelines/*.py`` at import time. ``main.py`` imports both this
    router and the pipeline modules, so the registry is fully populated by the
    time the first request hits ``create_task``.
    """
    _pipeline_registry[task_type] = runner
    logger.info(f"[TASKS] Registered pipeline: {task_type}")


# ─── Request/Response Models ──────────────────────────────────────────

class CreateTaskRequest(BaseModel):
    client_id: str
    user_id: str
    task_type: str          # 'analysis' | 'content_generation'
    task_name: Optional[str] = None
    inputs: dict = {}
    template_id: Optional[str] = None
    thread_id: Optional[str] = None
    triggered_by: str = "manual"
    save_only: bool = False  # True = DRAFT, False = run immediately


class UpdateTaskRequest(BaseModel):
    client_id: str
    user_id: str
    task_name: Optional[str] = None
    inputs: Optional[dict] = None
    save_only: bool = False  # True = just save, False = save + run


class RunTaskRequest(BaseModel):
    client_id: str
    user_id: str


class CitationAnalysisPreviewRequest(BaseModel):
    client_id: str
    template_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class SubredditTargetingPreviewRequest(BaseModel):
    client_id: str
    template_id: str
    mode: str = "ai_recommend"
    manual_subreddits: str = ""
    keywords: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)


class RedditDiscoveryPreviewRequest(BaseModel):
    client_id: str
    template_id: str
    subreddit_targeting: dict[str, Any] | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class PromptArtifactsPreviewRequest(BaseModel):
    client_id: str
    template_id: str
    subreddit_targeting: dict[str, Any] | None = None
    reddit_discovery: dict[str, Any] | None = None
    citation_analysis_result: dict[str, Any] | None = None
    strategy: dict[str, Any] | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


# ─── Response Models ───────────────────────────────────────────────────

class TaskCreateOut(BaseModel):
    """Echo for ``POST /``: minimal lifecycle handshake."""

    id: str
    status: str
    task_name: Optional[str] = None


class TaskRunOut(BaseModel):
    """Echo for ``POST /{task_id}/run`` and the run-branch of ``PUT /{task_id}``."""

    id: str
    status: str


class TaskRenameOut(BaseModel):
    """Echo for ``PATCH /{task_id}/rename``."""

    ok: bool
    task_name: str


class TaskDeleteOut(BaseModel):
    """Echo for ``DELETE /{task_id}``."""

    ok: bool


class TaskRow(BaseModel):
    """Full task detail returned by ``GET /{task_id}`` and ``GET /{task_id}/progress``.

    Mirrors ``geo_agent_tasks`` columns after ``_row_to_dict`` hydration:
      - id / client_id are stringified UUIDs
      - workflow_steps / inputs / output / status_logs are jsonb-parsed
      - timestamps are raw ``datetime`` (Pydantic serializes to ISO 8601)

    Permissive on extras so progress payloads (subset of columns) and full
    detail payloads share a single shape without forcing every caller to read
    every column.
    """

    id: str
    client_id: Optional[str] = None
    user_id: Optional[str] = None
    task_type: Optional[str] = None
    task_name: Optional[str] = None
    status: Optional[str] = None
    workflow_steps: Optional[Any] = None
    current_step: Optional[int] = None
    inputs: Optional[Any] = None
    template_id: Optional[str] = None
    output: Optional[Any] = None
    status_logs: Optional[Any] = None
    error_message: Optional[str] = None
    thread_id: Optional[str] = None
    triggered_by: Optional[str] = None
    model_used: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(extra="allow")


class TaskListOut(BaseModel):
    """Wrapper for ``GET /`` — list payload uses a single ``data`` key so we
    can later add pagination metadata without breaking the frontend."""

    data: list[TaskRow] = Field(default_factory=list)
    pagination: Optional[dict[str, int]] = None


# ─── Workflow step definitions ────────────────────────────────────────

CONTENT_WORKFLOW_STEPS = [
    {"step": 1, "name": "citation_analysis", "label": "Citation Analysis", "status": "pending"},
    {"step": 2, "name": "strategy_generation", "label": "策略生成", "status": "pending"},
    {"step": 3, "name": "content_generation", "label": "内容生成", "status": "pending"},
    {"step": 4, "name": "quality_review", "label": "Quality Gate", "status": "pending"},
    {"step": 5, "name": "revise_round_1", "label": "第一轮 Revise", "status": "pending"},
    {"step": 6, "name": "quality_recheck", "label": "修订后复查", "status": "pending"},
    {"step": 7, "name": "revise_round_2", "label": "第二轮 Revise", "status": "pending"},
    {"step": 8, "name": "quality_recheck_round_2", "label": "第二轮后复查", "status": "pending"},
]

ANALYSIS_WORKFLOW_STEPS = [
    {"step": 1, "name": "validate_inputs", "label": "输入校验", "status": "pending"},
    {"step": 2, "name": "hydrate_metrics", "label": "指标水合", "status": "pending"},
    {"step": 3, "name": "generate_charts", "label": "图表生成", "status": "pending"},
    {"step": 4, "name": "synthesize_report", "label": "报告合成", "status": "pending"},
    {"step": 5, "name": "quality_check", "label": "质量评审", "status": "pending"},
]

OPPORTUNITY_WORKFLOW_STEPS = [
    {"step": 1, "name": "topic_quadrant", "label": "Topic 四象限定位", "status": "pending"},
    {"step": 2, "name": "content_opportunities", "label": "选题机会挖掘", "status": "pending"},
    {"step": 3, "name": "platform_analysis", "label": "平台引用关系分析", "status": "pending"},
    {"step": 4, "name": "synthesize_output", "label": "综合输出", "status": "pending"},
]


def _get_workflow_steps(task_type: str) -> list[dict]:
    if task_type == "content_generation":
        return [dict(s) for s in CONTENT_WORKFLOW_STEPS]
    elif task_type == "analysis":
        return [dict(s) for s in ANALYSIS_WORKFLOW_STEPS]
    elif task_type == "opportunity_discovery":
        return [dict(s) for s in OPPORTUNITY_WORKFLOW_STEPS]
    return []


def _coerce_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _template_runtime_config_from_row(row: Any) -> dict[str, Any]:
    defaults = _coerce_json_object(row["defaults"])
    wizard_config = _coerce_json_object(row["wizard_config"])
    steps = _coerce_json_object(wizard_config.get("steps"))
    generation_config = _coerce_json_object(steps.get("generation_config"))
    content_type_cfg = _coerce_json_object(steps.get("content_type"))
    return {
        "template_name": row["name"],
        "default_prompt": row["default_prompt"],
        "template_group": wizard_config.get("template_group") or defaults.get("template_group"),
        "platform_profile": wizard_config.get("platform_profile") or defaults.get("platform_profile"),
        "platform_playbook": wizard_config.get("platform_playbook") or defaults.get("platform_playbook"),
        "depth_profiles": wizard_config.get("depth_profiles") or defaults.get("depth_profiles") or {},
        "generation_requirements": wizard_config.get("generation_requirements") or defaults.get("generation_requirements"),
        "ratf_metric_jobs": wizard_config.get("ratf_metric_jobs") or defaults.get("ratf_metric_jobs") or {},
        "ratf_rendering": wizard_config.get("ratf_rendering") or defaults.get("ratf_rendering") or {},
        "prompt_input_policy": wizard_config.get("prompt_input_policy") or defaults.get("prompt_input_policy") or {},
        "reddit_native_contract": wizard_config.get("reddit_native_contract") or defaults.get("reddit_native_contract") or {},
        "experience_style_notes": wizard_config.get("experience_style_notes") or defaults.get("experience_style_notes") or {},
        "community_brief": wizard_config.get("community_brief") or defaults.get("community_brief") or {},
        "derived_prompt_artifacts": wizard_config.get("derived_prompt_artifacts") or defaults.get("derived_prompt_artifacts") or {},
        "segmented_generation": wizard_config.get("segmented_generation") or defaults.get("segmented_generation") or {},
        "quality_gate": wizard_config.get("quality_gate") or defaults.get("quality_gate") or {},
        "resource_link_policy": wizard_config.get("resource_link_policy") or defaults.get("resource_link_policy") or {},
        "reddit_research": wizard_config.get("reddit_research") or defaults.get("reddit_research") or {},
        "citation_analysis": wizard_config.get("citation_analysis") or defaults.get("citation_analysis") or {},
        "citation_analysis_step": steps.get("citation_analysis") or {},
        "default_publish_platform": generation_config.get("default_publish_platform") or defaults.get("publish_platform"),
        "default_depth": generation_config.get("default_depth") or defaults.get("depth"),
        "default_content_type": content_type_cfg.get("default") or defaults.get("content_type"),
    }


async def _load_template_runtime_config_by_id(pool, template_id: str) -> dict[str, Any]:
    row = await pool.fetchrow(
        """SELECT name, default_prompt, defaults, wizard_config
           FROM geo_report_templates
           WHERE id = $1::uuid""",
        template_id,
    )
    return _template_runtime_config_from_row(row) if row else {}


async def _load_brand_context_for_preview(pool, client_id: str) -> dict[str, Any]:
    bp_row = await pool.fetchrow(
        """SELECT brand_name, tone_of_voice, target_audience,
                  key_messages, brand_values, language
           FROM geo_brand_profiles WHERE client_id = $1::uuid""",
        client_id,
    )
    brand_context = dict(bp_row) if bp_row else {}
    try:
        own_rows = await pool.fetch(
            """SELECT brand_name, aliases
               FROM geo_client_brands
               WHERE client_id = $1::uuid
                 AND is_shadow = false
                 AND is_active = true
               ORDER BY brand_name ASC
               LIMIT 5""",
            client_id,
        )
    except Exception as exc:
        logger.warning("[TASKS] Citation preview own-brand lookup failed: %s", exc)
        own_rows = []
    own_brands = [
        {"brand_name": row["brand_name"], "aliases": row["aliases"] or []}
        for row in (own_rows or [])
    ]
    if own_brands:
        brand_context["own_brands"] = own_brands
        if not str(brand_context.get("brand_name") or "").strip():
            brand_context["brand_name"] = own_brands[0]["brand_name"]
            brand_context["brand_name_source"] = "geo_client_brands"
    return brand_context


async def _load_prompt_topic_context(pool, client_id: str, inputs: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    prompt_ids = inputs.get("prompt_ids") or inputs.get("target_prompt_ids") or []
    topic_ids = inputs.get("topic_ids") or []
    prompts: list[dict[str, Any]] = []
    topics: list[str] = []
    if isinstance(prompt_ids, list) and prompt_ids:
        rows = await pool.fetch(
            """SELECT text, platform, intent
               FROM geo_client_prompts
               WHERE id = ANY($1::uuid[]) AND client_id = $2::uuid""",
            prompt_ids,
            client_id,
        )
        prompts = [dict(r) for r in rows]
    if isinstance(topic_ids, list) and topic_ids:
        rows = await pool.fetch(
            """SELECT topic_name
               FROM geo_client_topics
               WHERE id = ANY($1::uuid[]) AND client_id = $2::uuid""",
            topic_ids,
            client_id,
        )
        topics = [str(r["topic_name"]) for r in rows]
    return prompts, topics


def _split_subreddit_input(value: str) -> list[str]:
    names = []
    for part in str(value or "").replace(",", "\n").splitlines():
        stripped = part.strip()
        if stripped:
            names.append(stripped)
    return names


def _reddit_discovery_rules_review_complete(reddit_discovery: dict[str, Any]) -> bool:
    subreddits = reddit_discovery.get("subreddits")
    if not isinstance(subreddits, list) or not subreddits:
        return False
    for item in subreddits:
        if not isinstance(item, dict):
            return False
        if item.get("rules_status") == "verified":
            continue
        if item.get("rules_skip_confirmed") is True:
            continue
        manual_rules = item.get("rules_manual_override")
        if isinstance(manual_rules, str) and manual_rules.strip():
            continue
        if isinstance(manual_rules, list) and manual_rules:
            continue
        return False
    return True


# ─── Endpoints ────────────────────────────────────────────────────────

@router.post("", response_model=TaskCreateOut)
async def create_task(
    data: CreateTaskRequest,
    current_user: AuthenticatedUser = Depends(require_current_user),
) -> TaskCreateOut:
    """Create a new task. If save_only=False, immediately fire the pipeline."""
    data.user_id = user_identifier(current_user)
    pool = await get_pool()
    task_id = str(uuid.uuid4())
    status = "DRAFT" if data.save_only else "RUNNING"
    workflow_steps = _get_workflow_steps(data.task_type)

    # Auto-generate task name if not provided
    task_name = data.task_name
    if not task_name:
        if data.template_id:
            tmpl_row = await pool.fetchrow(
                "SELECT name FROM geo_report_templates WHERE id = $1::uuid",
                data.template_id,
            )
            task_name = tmpl_row["name"] if tmpl_row else data.task_type
        else:
            task_name = data.inputs.get("topic", data.task_type)[:80]

    await _guarded_execute(
        pool,
        data.client_id,
        """INSERT INTO geo_agent_tasks
           (id, client_id, user_id, task_type, task_name, status, workflow_steps,
            inputs, template_id, thread_id, triggered_by, created_at, updated_at)
           VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::jsonb,
                   $8::jsonb, $9, $10, $11, NOW(), NOW())""",
        task_id, data.client_id, data.user_id, data.task_type, task_name,
        status, json.dumps(workflow_steps),
        json.dumps(data.inputs, ensure_ascii=False), data.template_id,
        data.thread_id, data.triggered_by,
    )

    if not data.save_only:
        await _fire_pipeline(task_id, data.task_type, data.inputs, data.client_id)

    return TaskCreateOut(id=task_id, status=status, task_name=task_name)


@router.post("/content/citation-analysis/preview")
async def preview_content_citation_analysis(
    data: CitationAnalysisPreviewRequest,
    current_user: AuthenticatedUser = Depends(require_client_access_if_present),
) -> dict[str, Any]:
    """Run Citation Analysis during the wizard preflight step."""
    _ = current_user
    pool = await get_pool()
    template_runtime_config = await _load_template_runtime_config_by_id(pool, data.template_id)
    if not template_runtime_config:
        raise HTTPException(status_code=404, detail="Template not found")
    brand_context = await _load_brand_context_for_preview(pool, data.client_id)
    return await run_citation_analysis(
        pool=pool,
        client_id=data.client_id,
        inputs=data.inputs or {},
        brand_context=brand_context,
        template_runtime_config=template_runtime_config,
    )


@router.post("/content/subreddit-targeting/preview")
async def preview_subreddit_targeting(
    data: SubredditTargetingPreviewRequest,
    current_user: AuthenticatedUser = Depends(require_client_access_if_present),
) -> dict[str, Any]:
    _ = current_user
    pool = await get_pool()
    template_runtime_config = await _load_template_runtime_config_by_id(pool, data.template_id)
    if not template_runtime_config:
        raise HTTPException(status_code=404, detail="Template not found")
    brand_context = await _load_brand_context_for_preview(pool, data.client_id)
    prompts, topics = await _load_prompt_topic_context(pool, data.client_id, data.inputs or {})
    try:
        if data.mode == "manual":
            return await resolve_manual_subreddits(
                pool=pool,
                names=_split_subreddit_input(data.manual_subreddits),
                template_runtime_config=template_runtime_config,
            )
        context = RedditTargetingContext(
            client_id=data.client_id,
            template_id=data.template_id,
            brand_context=brand_context,
            topics=topics,
            prompts=prompts,
            citation_analysis_result=(data.inputs or {}).get("citation_analysis_result"),
            content_type=str((data.inputs or {}).get("content_type") or (data.inputs or {}).get("default") or ""),
            keywords=data.keywords,
        )
        return await recommend_subreddits(
            pool=pool,
            context=context,
            template_runtime_config=template_runtime_config,
            mode=data.mode,
        )
    except RedditResearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/content/reddit-discovery/preview")
async def preview_reddit_discovery(
    data: RedditDiscoveryPreviewRequest,
    current_user: AuthenticatedUser = Depends(require_client_access_if_present),
) -> dict[str, Any]:
    _ = current_user
    if not isinstance(data.subreddit_targeting, dict):
        raise HTTPException(status_code=400, detail="Confirmed subreddit targets are required")
    pool = await get_pool()
    template_runtime_config = await _load_template_runtime_config_by_id(pool, data.template_id)
    if not template_runtime_config:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        prompts, topics = await _load_prompt_topic_context(pool, data.client_id, data.inputs or {})
        query = " ".join(topics + [str(p.get("text") or "") for p in prompts]).strip()
        return await discover_reddit_context(
            pool=pool,
            subreddit_targeting=data.subreddit_targeting,
            query=query,
            template_runtime_config=template_runtime_config,
        )
    except RedditResearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/content/prompt-artifacts/preview")
async def preview_prompt_artifacts(
    data: PromptArtifactsPreviewRequest,
    current_user: AuthenticatedUser = Depends(require_client_access_if_present),
) -> dict[str, Any]:
    _ = current_user
    if not isinstance(data.reddit_discovery, dict):
        raise HTTPException(status_code=400, detail="Confirmed Reddit Discovery output is required")
    if not _reddit_discovery_rules_review_complete(data.reddit_discovery):
        raise HTTPException(
            status_code=400,
            detail="Reddit Discovery has unavailable rules. Add manual rules or confirm skip before Artifact Preparation.",
        )
    pool = await get_pool()
    template_runtime_config = await _load_template_runtime_config_by_id(pool, data.template_id)
    if not template_runtime_config:
        raise HTTPException(status_code=404, detail="Template not found")
    brand_context = await _load_brand_context_for_preview(pool, data.client_id)
    prompts, _topics = await _load_prompt_topic_context(pool, data.client_id, data.inputs or {})
    try:
        from llm.client import get_genai_client
        from pipelines import content_pipeline

        model_id = str((template_runtime_config.get("derived_prompt_artifacts") or {}).get("model_id") or (data.inputs or {}).get("model_id") or "")
        if not model_id:
            from llm.client import get_model_id
            model_id = await get_model_id("flash")
        client_llm = await get_genai_client(model_id, role="flash")
        artifacts = await content_pipeline._prepare_derived_prompt_artifacts(
            pool=pool,
            task_id="",
            client_llm=client_llm,
            model_id=model_id,
            template_runtime_config=template_runtime_config,
            brand_context=brand_context,
            reddit_discovery=data.reddit_discovery,
            official_website_discovery=None,
            citation_analysis_result=data.citation_analysis_result,
            strategy=data.strategy or {},
            prompt_texts=prompts,
            prompt_debug=None,
        )
        fingerprint = artifacts.get("fingerprint") if isinstance(artifacts, dict) else None
        if isinstance(artifacts, dict) and not fingerprint:
            fingerprint = build_reddit_research_fingerprint({
                "step": "prompt_artifact_preparation",
                "reddit_discovery_fingerprint": data.reddit_discovery.get("fingerprint"),
                "citation_analysis_fingerprint": (data.citation_analysis_result or {}).get("fingerprint"),
                "strategy": data.strategy or {},
                "prompt_ids": (data.inputs or {}).get("prompt_ids"),
                "topic_ids": (data.inputs or {}).get("topic_ids"),
                "rendered_sections": artifacts.get("rendered_sections"),
            })
        return {
            **artifacts,
            "status": "ready",
            "source": "wizard_confirmed",
            "edited": False,
            "fingerprint": fingerprint,
            "input_fingerprint": fingerprint,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("[TASKS] Prompt artifact preview failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Prompt artifact preparation failed: {exc}") from exc


@router.get("", response_model=TaskListOut)
async def list_tasks(
    client_id: str,
    task_type: Optional[str] = None,
    task_types: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 20,
    page: int = 1,
    page_size: Optional[int] = None,
    current_user: AuthenticatedUser = Depends(require_current_user),
) -> TaskListOut:
    """List tasks for a client, optionally filtered by type."""
    user_id = user_identifier(current_user) if user_id else None
    requested_page = max(1, page)
    safe_page_size = max(1, min(page_size or limit or 20, 100))
    pool = await get_pool()
    conditions = ["client_id = $1::uuid"]
    params: list = [client_id]
    idx = 2

    parsed_task_types = [t.strip() for t in (task_types or "").split(",") if t.strip()]
    if parsed_task_types:
        conditions.append(f"task_type = ANY(${idx}::text[])")
        params.append(parsed_task_types)
        idx += 1
    elif task_type:
        conditions.append(f"task_type = ${idx}")
        params.append(task_type)
        idx += 1
    if user_id:
        conditions.append(f"user_id = ${idx}")
        params.append(user_id)
        idx += 1

    where = " AND ".join(conditions)
    total = await pool.fetchval(f"SELECT COUNT(*) FROM geo_agent_tasks WHERE {where}", *params)
    pages = max(1, math.ceil((total or 0) / safe_page_size))
    safe_page = min(requested_page, pages)
    offset = (safe_page - 1) * safe_page_size
    params.append(safe_page_size)
    limit_idx = idx
    idx += 1
    params.append(offset)

    rows = await pool.fetch(
        f"""SELECT id, task_type, task_name, status, workflow_steps, current_step,
                   template_id, triggered_by, started_at, completed_at, created_at,
                   error_message,
                   output->'quality_review'->'quality_gate'->>'status' AS quality_gate_status,
                   output->'quality_review'->>'overall_score' AS quality_overall_score
            FROM geo_agent_tasks
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${limit_idx}
            OFFSET ${idx}""",
        *params,
    )
    return TaskListOut(
        data=[TaskRow(**_row_to_dict(r)) for r in rows],
        pagination={
            "page": safe_page,
            "page_size": safe_page_size,
            "total": int(total or 0),
            "pages": pages,
        },
    )


@router.get("/{task_id}", response_model=TaskRow)
async def get_task(task_id: str, client_id: str) -> TaskRow:
    """Get full task detail including output."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT * FROM geo_agent_tasks WHERE id = $1::uuid AND client_id = $2::uuid""",
        task_id, client_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRow(**_row_to_dict(row))


@router.get("/{task_id}/progress", response_model=TaskRow)
async def get_task_progress(
    task_id: str, client_id: Optional[str] = None
) -> TaskRow:
    """Lightweight progress endpoint for polling (no heavy output field)."""
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT id, status, workflow_steps, current_step, status_logs,
                  error_message, started_at, completed_at
           FROM geo_agent_tasks WHERE id = $1::uuid AND client_id = $2::uuid""",
        task_id, client_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRow(**_row_to_dict(row))


@router.put("/{task_id}", response_model=TaskRunOut)
async def update_task(task_id: str, data: UpdateTaskRequest) -> TaskRunOut:
    """Update an existing task's inputs/name, optionally re-run it."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, task_type, status, client_id FROM geo_agent_tasks WHERE id = $1::uuid AND client_id = $2::uuid",
        task_id, data.client_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    if row["status"] == "RUNNING":
        raise HTTPException(status_code=400, detail="Cannot edit a running task")

    sets = ["updated_at = NOW()"]
    params: list = []
    idx = 1
    if data.task_name is not None:
        sets.append(f"task_name = ${idx}")
        params.append(data.task_name)
        idx += 1
    if data.inputs is not None:
        sets.append(f"inputs = ${idx}::jsonb")
        params.append(json.dumps(data.inputs, ensure_ascii=False))
        idx += 1

    if sets:
        params.append(task_id)
        await _guarded_execute(
            pool,
            str(row["client_id"]),
            f"UPDATE geo_agent_tasks SET {', '.join(sets)} WHERE id = ${idx}::uuid",
            *params,
        )

    if not data.save_only:
        workflow_steps = _get_workflow_steps(row["task_type"])
        inputs = data.inputs if data.inputs is not None else (
            json.loads(row.get("inputs", "{}")) if isinstance(row.get("inputs"), str) else (row.get("inputs") or {})
        )
        await _guarded_execute(
            pool,
            str(row["client_id"]),
            """UPDATE geo_agent_tasks
               SET status = 'RUNNING', workflow_steps = $2::jsonb, current_step = 0,
                   status_logs = '[]'::jsonb, error_message = NULL, output = NULL,
                   started_at = NOW(), completed_at = NULL, updated_at = NOW()
               WHERE id = $1::uuid""",
            task_id, json.dumps(workflow_steps),
        )
        await _fire_pipeline(task_id, row["task_type"], inputs, str(row["client_id"]))
        return TaskRunOut(id=task_id, status="RUNNING")

    return TaskRunOut(id=task_id, status="DRAFT")


@router.post("/{task_id}/run", response_model=TaskRunOut)
async def run_task(task_id: str, data: RunTaskRequest) -> TaskRunOut:
    """Execute a DRAFT or FAILED task."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT id, task_type, inputs, status, client_id
           FROM geo_agent_tasks
           WHERE id = $1::uuid AND client_id = $2::uuid""",
        task_id, data.client_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    # Allow re-running DRAFT, FAILED, or stuck RUNNING tasks (>10 min)
    if row["status"] == "RUNNING":
        started = row.get("started_at")
        if started:
            from datetime import datetime, timezone
            elapsed = (datetime.now(timezone.utc) - started.replace(tzinfo=timezone.utc)).total_seconds()
            if elapsed < 600:
                raise HTTPException(status_code=400, detail=f"Task is still running ({int(elapsed)}s elapsed). Wait or retry after 10 min.")
        logger.warning(f"[TASKS] Re-running stuck RUNNING task {task_id}")
    elif row["status"] not in ("DRAFT", "FAILED"):
        raise HTTPException(status_code=400, detail=f"Cannot run task in {row['status']} status")

    workflow_steps = _get_workflow_steps(row["task_type"])
    await _guarded_execute(
        pool,
        str(row["client_id"]),
        """UPDATE geo_agent_tasks
           SET status = 'RUNNING', workflow_steps = $2::jsonb, current_step = 0,
               status_logs = '[]'::jsonb, error_message = NULL,
               started_at = NOW(), completed_at = NULL, updated_at = NOW()
           WHERE id = $1::uuid""",
        task_id, json.dumps(workflow_steps),
    )

    inputs = json.loads(row["inputs"]) if isinstance(row["inputs"], str) else (row["inputs"] or {})
    await _fire_pipeline(task_id, row["task_type"], inputs, str(row["client_id"]))

    return TaskRunOut(id=task_id, status="RUNNING")


@router.post("/{task_id}/trigger_cron", response_model=TaskRunOut)
async def trigger_cron_task(task_id: str, triggered_by: str = "cron") -> TaskRunOut:
    """Execute a scheduled Agent task from Cloud Scheduler."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT id, task_type, inputs, status, client_id, started_at
           FROM geo_agent_tasks
           WHERE id = $1::uuid""",
        task_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    if row["status"] == "RUNNING":
        started = row["started_at"]
        if started:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            if elapsed < 600:
                raise HTTPException(
                    status_code=400,
                    detail=f"Task is still running ({int(elapsed)}s elapsed). Wait or retry after 10 min.",
                )
        logger.warning(f"[TASKS] Re-running stuck scheduled task {task_id}")

    workflow_steps = _get_workflow_steps(row["task_type"])
    await _guarded_execute(
        pool,
        str(row["client_id"]),
        """UPDATE geo_agent_tasks
           SET status = 'RUNNING', workflow_steps = $2::jsonb, current_step = 0,
               status_logs = '[]'::jsonb, error_message = NULL,
               started_at = NOW(), completed_at = NULL, updated_at = NOW(),
               triggered_by = $3
           WHERE id = $1::uuid""",
        task_id, json.dumps(workflow_steps), triggered_by,
    )

    inputs = json.loads(row["inputs"]) if isinstance(row["inputs"], str) else (row["inputs"] or {})
    await _fire_pipeline(task_id, row["task_type"], inputs, str(row["client_id"]))

    return TaskRunOut(id=task_id, status="RUNNING")


@router.patch("/{task_id}/rename", response_model=TaskRenameOut)
async def rename_task(
    task_id: str, client_id: str, body: dict = Body(...)
) -> TaskRenameOut:
    """Rename a task's task_name."""
    new_name = (body.get("task_name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="task_name is required")
    pool = await get_pool()
    result = await _guarded_execute(
        pool,
        client_id,
        "UPDATE geo_agent_tasks SET task_name = $1, updated_at = NOW() WHERE id = $2::uuid AND client_id = $3::uuid",
        new_name, task_id, client_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRenameOut(ok=True, task_name=new_name)


@router.delete("/{task_id}", response_model=TaskDeleteOut)
async def delete_task(task_id: str, client_id: str) -> TaskDeleteOut:
    """Delete a task."""
    pool = await get_pool()
    result = await _guarded_execute(
        pool,
        client_id,
        "DELETE FROM geo_agent_tasks WHERE id = $1::uuid AND client_id = $2::uuid",
        task_id, client_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskDeleteOut(ok=True)


# ─── Internal helpers ─────────────────────────────────────────────────

async def _fire_pipeline(task_id: str, task_type: str, inputs: dict, client_id: str):
    """Launch the appropriate pipeline as a background asyncio task."""
    runner = _pipeline_registry.get(task_type)
    if not runner:
        logger.error(f"[TASKS] No pipeline registered for task_type={task_type}")
        pool = await get_pool()
        await _guarded_execute(
            pool,
            client_id,
            "UPDATE geo_agent_tasks SET status = 'FAILED', error_message = $2 WHERE id = $1::uuid",
            task_id, f"No pipeline registered for task_type '{task_type}'",
        )
        return

    async def guarded_runner():
        # Covers every pipeline status/content write for the entire background
        # workflow without requiring each step to keep its own connection.
        async with agent_workspace_lifecycle_session(client_id):
            await runner(task_id, inputs, client_id)

    asyncio.create_task(guarded_runner())


def _row_to_dict(row) -> dict:
    """Convert asyncpg Record to dict, parsing JSONB strings.

    Re-exported for use by ``routers.export.export_task_html`` (sibling
    router needs the same hydration logic).
    """
    d = dict(row)
    for key in ("workflow_steps", "inputs", "output", "status_logs"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    for key in ("id", "client_id"):
        if key in d and d[key] is not None:
            d[key] = str(d[key])
    return d
