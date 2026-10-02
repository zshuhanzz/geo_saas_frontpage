"""
Cloro Dispatcher Service (V2)

Cloud Run Service that dispatches tasks to Cloro.dev API.
Triggered by Pub/Sub (geo-tasks-pending) to process individual tasks.

V2 schema:
- Reads final_prompt instead of prompt_text from geo_tasks
- Passes client_prompt_id, persona_used in task metadata

Phase 2.5a: migrated from `databases` lib to `geo_common.db` asyncpg pool.

Features:
- Idempotent processing (checks task status before dispatch)
- Optimistic locking for concurrency control
- M concurrent calls per task
- Error handling with status updates

Flow:
    Pub/Sub (geo-tasks-pending) → This Service → Cloro API
"""
import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request

from src.clients.cloro import CloroService
from src.core import database as db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CloroDispatcher")


# FastAPI ``@app.on_event`` was deprecated; use ``lifespan`` context manager.
# Same semantics: pre-yield runs on startup, post-yield runs on shutdown.
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[DISPATCHER-S0] ========== Cloro Dispatcher Service 启动 ==========")
    logger.info("[DISPATCHER-S0] 连接数据库...")
    await db.connect()
    logger.info("[DISPATCHER-S0] 数据库连接成功")
    try:
        yield
    finally:
        logger.info("[DISPATCHER-S0] 断开数据库连接...")
        await db.disconnect()
        logger.info("[DISPATCHER-S0] ========== Cloro Dispatcher Service 关闭 ==========")


app = FastAPI(title="GEO Cloro Dispatcher Service (V2)", lifespan=lifespan)

# Concurrency control
CONCURRENT_CLORO_CALLS = 10
semaphore = asyncio.Semaphore(CONCURRENT_CLORO_CALLS)


@app.post("/dispatch/task")
async def dispatch_task(request: Request):
    """
    Pub/Sub Push endpoint for dispatching a single task.

    Message format: {"task_id": "uuid", "action": "dispatch"}

    Idempotency:
    - Only processes tasks with status=PENDING
    - Updates to DISPATCHING before sending
    - Pub/Sub will retry on 5xx, skip on 2xx/4xx
    """
    try:
        envelope = await request.json()
        if not envelope.get("message"):
            logger.warning("[DISPATCHER-S1] Bad Request: no message field")
            return {"status": "ignored"}

        pubsub_message = envelope["message"]
        msg_id = pubsub_message.get("messageId")

        # Decode message
        data_str = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        message_data = json.loads(data_str)

        task_id = message_data.get("task_id")
        action = message_data.get("action")

        if not task_id or action != "dispatch":
            logger.warning(f"[DISPATCHER-S1] 无效消息格式 | msg_id={msg_id}")
            return {"status": "ignored"}

        logger.info(f"[DISPATCHER-S1] 收到 dispatch 消息 | task_id={task_id} | msg_id={msg_id}")

        result = await process_dispatch(task_id)

        logger.info(f"[DISPATCHER-S1] Dispatch 完成 | task_id={task_id} | result={result}")
        return {"status": result}

    except Exception as e:
        logger.error(f"[DISPATCHER-ERR] 处理消息失败 | error={e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_dispatch(task_id: str) -> str:
    """
    Dispatch a single task to Cloro with M concurrent calls.
    Uses V2 final_prompt field.

    Returns:
        str: "success", "skipped", or "failed"
    """
    pool = db.get_pool()

    # [DISPATCHER-S2] Optimistic lock — atomically transition PENDING → DISPATCHING.
    # asyncpg's UPDATE returns "UPDATE <rowcount>"; parse the trailing int to mimic
    # the previous `databases.execute` semantics ("affected row count").
    logger.info(f"[DISPATCHER-S2] 尝试获取锁 | task_id={task_id}")
    async with pool.acquire() as conn:
        update_status = await conn.execute(
            f"""
            UPDATE {db.GEO_TASKS}
               SET status = 'DISPATCHING'
             WHERE task_id = $1
               AND status = 'PENDING'
            """,
            task_id,
        )
        affected = _parse_affected(update_status)

        if affected == 0:
            task = await conn.fetchrow(
                f"SELECT status FROM {db.GEO_TASKS} WHERE task_id = $1",
                task_id,
            )
            if task:
                logger.info(
                    f"[DISPATCHER-S2] 跳过，状态非 PENDING | "
                    f"task_id={task_id} | status={task['status']}"
                )
            else:
                logger.warning(f"[DISPATCHER-S2] 跳过，task 不存在 | task_id={task_id}")
            return "skipped"

        logger.info(f"[DISPATCHER-S2] 获取锁成功 | task_id={task_id}")

        # [DISPATCHER-S3] Fetch full task data (V2 fields)
        logger.info(f"[DISPATCHER-S3] 读取 task 数据 | task_id={task_id}")
        task = await conn.fetchrow(
            f"SELECT * FROM {db.GEO_TASKS} WHERE task_id = $1",
            task_id,
        )

    if not task:
        logger.error(f"[DISPATCHER-S3] Task 不存在 | task_id={task_id}")
        return "failed"

    platform = task["platform"]
    m = task["calls_per_prompt"] or 1
    # V2: use final_prompt instead of prompt_text
    prompt = task["final_prompt"] or ""
    prompt_preview = (prompt[:50] + "...") if len(prompt) > 50 else prompt

    logger.info(
        f"[DISPATCHER-S3] Task 数据已加载 | platform={platform} | "
        f"calls={m} | prompt={prompt_preview}"
    )

    # [DISPATCHER-S4] Dispatch M concurrent Cloro calls
    logger.info(f"[DISPATCHER-S4] 开始并发调用 Cloro API | task_id={task_id} | calls={m}")
    cloro_service = CloroService()

    async with httpx.AsyncClient() as client:
        async def call_cloro_with_index(call_index: int) -> bool:
            async with semaphore:
                try:
                    cloro_task_id = await cloro_service.dispatch_task_async(
                        client,
                        dict(task),
                        call_index=call_index,
                    )
                    if cloro_task_id:
                        logger.info(
                            f"[DISPATCHER-S4] Cloro 调用成功 | task_id={task_id} | "
                            f"call={call_index}/{m} | cloro_id={cloro_task_id}"
                        )
                        return True
                    logger.error(
                        f"[DISPATCHER-S4] Cloro 调用失败 | task_id={task_id} | "
                        f"call={call_index}/{m}"
                    )
                    return False
                except Exception as e:
                    logger.error(
                        f"[DISPATCHER-S4] Cloro 调用异常 | task_id={task_id} | "
                        f"call={call_index}/{m} | error={e}"
                    )
                    return False

        results = await asyncio.gather(
            *[call_cloro_with_index(i) for i in range(1, m + 1)],
            return_exceptions=True,
        )

    # [DISPATCHER-S5] Count successes and update status
    success_count = sum(1 for r in results if r is True)
    logger.info(
        f"[DISPATCHER-S5] Cloro 调用汇总 | task_id={task_id} | success={success_count}/{m}"
    )

    async with pool.acquire() as conn:
        if success_count == m:
            await conn.execute(
                f"""
                UPDATE {db.GEO_TASKS}
                   SET status = 'DISPATCHED',
                       dispatched_count = $2
                 WHERE task_id = $1
                """,
                task_id,
                success_count,
            )
            logger.info(
                f"[DISPATCHER-S5] Task dispatch 完成 | task_id={task_id} | status=DISPATCHED"
            )
            return "success"
        if success_count == 0:
            await conn.execute(
                f"""
                UPDATE {db.GEO_TASKS}
                   SET status = 'DISPATCH_FAILED',
                       dispatched_count = 0
                 WHERE task_id = $1
                """,
                task_id,
            )
            logger.error(
                f"[DISPATCHER-S5] Task dispatch 全部失败 | "
                f"task_id={task_id} | status=DISPATCH_FAILED"
            )
            return "failed"

        await conn.execute(
            f"""
            UPDATE {db.GEO_TASKS}
               SET dispatched_count = $2
             WHERE task_id = $1
            """,
            task_id,
            success_count,
        )
        logger.warning(
            f"[DISPATCHER-S5] Task dispatch 部分成功 | "
            f"task_id={task_id} | success={success_count}/{m}"
        )
        return "partial"


def _parse_affected(status_string: str) -> int:
    """
    Parse asyncpg's command-status string (e.g. ``"UPDATE 1"``) into an
    affected-row count. Returns 0 on any unexpected shape so that callers
    treat the operation as a no-op (matching the prior ``databases`` lib
    behaviour where ``execute()`` for an UPDATE returned the row count).
    """
    if not status_string:
        return 0
    parts = status_string.strip().split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        return 0


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}
