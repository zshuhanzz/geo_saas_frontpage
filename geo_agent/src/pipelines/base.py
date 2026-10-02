"""
Pipeline base helpers.

Shared utilities for all background task pipelines (content generation, analysis).
Provides status tracking, step management, and the fire-and-forget execution pattern.
"""
import json
import logging
import traceback
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from database import get_pool

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    num: int
    name: str
    label: str
    fn: Callable[..., Awaitable[dict]]


async def append_status_log(pool, task_id: str, entry: dict):
    """Append a status log entry to the task's status_logs JSONB array."""
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    await pool.execute(
        """UPDATE geo_agent_tasks
           SET status_logs = COALESCE(status_logs, '[]'::jsonb) || $2::jsonb,
               updated_at = NOW()
           WHERE id = $1::uuid""",
        task_id, json.dumps([entry]),
    )


async def update_step_status(pool, task_id: str, step_num: int, status: str):
    """Update a specific workflow step's status in the workflow_steps JSONB array."""
    await pool.execute(
        """UPDATE geo_agent_tasks
           SET workflow_steps = (
               SELECT jsonb_agg(
                   CASE WHEN (elem->>'step')::int = $2
                        THEN jsonb_set(elem, '{status}', to_jsonb($3::text))
                        ELSE elem
                   END
               )
               FROM jsonb_array_elements(workflow_steps) elem
           ),
           current_step = GREATEST(COALESCE(current_step, 0), $2),
           updated_at = NOW()
           WHERE id = $1::uuid""",
        task_id, step_num, status,
    )


async def set_task_running(pool, task_id: str):
    """Mark task as RUNNING with started_at timestamp."""
    await pool.execute(
        """UPDATE geo_agent_tasks
           SET status = 'RUNNING', started_at = NOW(), updated_at = NOW()
           WHERE id = $1::uuid""",
        task_id,
    )


async def complete_task(pool, task_id: str, output: dict, model_used: str | None = None):
    """Mark task as COMPLETED with output and timestamps."""
    await pool.execute(
        """UPDATE geo_agent_tasks
           SET status = 'COMPLETED', output = $2::jsonb, model_used = COALESCE($3, model_used),
               completed_at = NOW(), updated_at = NOW()
           WHERE id = $1::uuid""",
        task_id, json.dumps(output, ensure_ascii=False, default=str), model_used,
    )


async def fail_task(pool, task_id: str, error_message: str):
    """Mark task as FAILED with error message."""
    await pool.execute(
        """UPDATE geo_agent_tasks
           SET status = 'FAILED', error_message = $2,
               completed_at = NOW(), updated_at = NOW()
           WHERE id = $1::uuid""",
        task_id, error_message[:2000],
    )


async def run_pipeline(task_id: str, steps: list[WorkflowStep], inputs: dict, client_id: str):
    """Execute a multi-step pipeline as a background task.

    Each step receives (pool, task_id, inputs, client_id) and returns a dict
    that gets merged into inputs for the next step. Status is tracked in DB
    at each step boundary.
    """
    pool = await get_pool()
    accumulated: dict[str, Any] = dict(inputs)
    model_used = None

    try:
        await set_task_running(pool, task_id)
        logger.info(f"[PIPELINE] Starting task {task_id} with {len(steps)} steps")

        for step in steps:
            # Mark step as running
            await update_step_status(pool, task_id, step.num, "running")
            await append_status_log(pool, task_id, {
                "step": step.num, "event": "start", "label": f"{step.label}...",
            })

            # Execute step
            result = await step.fn(pool, task_id, accumulated, client_id)

            # Chain outputs
            if result:
                accumulated.update(result)
                if "model_used" in result:
                    model_used = result["model_used"]

            # Mark step as done
            await update_step_status(pool, task_id, step.num, "done")
            await append_status_log(pool, task_id, {
                "step": step.num, "event": "complete", "label": f"{step.label} 完成",
            })
            logger.info(f"[PIPELINE] Task {task_id} step {step.num}/{len(steps)} ({step.name}) completed")

        # Build final output from accumulated state
        await complete_task(pool, task_id, accumulated.get("_output", accumulated), model_used)
        logger.info(f"[PIPELINE] Task {task_id} completed successfully")

    except Exception as e:
        logger.error(f"[PIPELINE] Task {task_id} failed at step: {e}")
        logger.error(traceback.format_exc())

        # Try to mark current step as failed
        try:
            for step in steps:
                # Find the step that was running
                row = await pool.fetchrow(
                    "SELECT workflow_steps FROM geo_agent_tasks WHERE id = $1::uuid", task_id,
                )
                if row and row["workflow_steps"]:
                    ws = json.loads(row["workflow_steps"]) if isinstance(row["workflow_steps"], str) else row["workflow_steps"]
                    for s in ws:
                        if s.get("status") == "running":
                            await update_step_status(pool, task_id, s["step"], "failed")
                            break
                break
        except Exception:
            pass

        await append_status_log(pool, task_id, {
            "step": 0, "event": "error", "label": f"任务失败: {str(e)[:200]}",
        })
        await fail_task(pool, task_id, str(e))
