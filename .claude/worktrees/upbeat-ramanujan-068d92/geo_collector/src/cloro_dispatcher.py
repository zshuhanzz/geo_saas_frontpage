"""
Cloro Dispatcher Service

Cloud Run Service that dispatches tasks to Cloro.dev API.
Triggered by Pub/Sub (geo-tasks-pending) to process individual tasks.

Features:
- Idempotent processing (checks task status before dispatch)
- Optimistic locking for concurrency control
- M concurrent calls per task
- Error handling with status updates

Flow:
    Pub/Sub (geo-tasks-pending) → This Service → Cloro API
"""
import base64
import json
import logging
import asyncio
import httpx
from fastapi import FastAPI, Request, HTTPException
from sqlalchemy import select, update
from src.core.database import database, geo_tasks
from src.clients.cloro import CloroService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CloroDispatcher")

app = FastAPI(title="GEO Cloro Dispatcher Service")

# Concurrency control
CONCURRENT_CLORO_CALLS = 10
semaphore = asyncio.Semaphore(CONCURRENT_CLORO_CALLS)


@app.on_event("startup")
async def startup():
    """Connect DB on startup"""
    logger.info("[DISPATCHER-S0] ========== Cloro Dispatcher Service 启动 ==========")
    logger.info("[DISPATCHER-S0] 连接数据库...")
    await database.connect()
    logger.info("[DISPATCHER-S0] 数据库连接成功")


@app.on_event("shutdown")
async def shutdown():
    """Disconnect DB on shutdown"""
    logger.info("[DISPATCHER-S0] 断开数据库连接...")
    await database.disconnect()
    logger.info("[DISPATCHER-S0] ========== Cloro Dispatcher Service 关闭 ==========")


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
    
    Idempotency:
    - Uses optimistic locking: only dispatches if status=PENDING
    - If already DISPATCHING/COMPLETED, returns "skipped"
    
    Returns:
        str: "success", "skipped", or "failed"
    """
    # [DISPATCHER-S2] Optimistic lock: try to update status to DISPATCHING
    logger.info(f"[DISPATCHER-S2] 尝试获取锁，更新状态为 DISPATCHING | task_id={task_id}")
    affected = await database.execute(
        update(geo_tasks)
        .where(geo_tasks.c.task_id == task_id)
        .where(geo_tasks.c.status == "PENDING")
        .values(status="DISPATCHING")
    )
    
    if affected == 0:
        task = await database.fetch_one(
            select(geo_tasks).where(geo_tasks.c.task_id == task_id)
        )
        if task:
            logger.info(f"[DISPATCHER-S2] 跳过，状态非 PENDING | task_id={task_id} | status={task['status']}")
        else:
            logger.warning(f"[DISPATCHER-S2] 跳过，task 不存在 | task_id={task_id}")
        return "skipped"
    
    logger.info(f"[DISPATCHER-S2] 获取锁成功 | task_id={task_id}")
    
    # [DISPATCHER-S3] Fetch full task data
    logger.info(f"[DISPATCHER-S3] 读取 task 数据 | task_id={task_id}")
    task = await database.fetch_one(
        select(geo_tasks).where(geo_tasks.c.task_id == task_id)
    )
    
    if not task:
        logger.error(f"[DISPATCHER-S3] Task 不存在 (状态更新后) | task_id={task_id}")
        return "failed"
    
    platform = task["platform"]
    m = task["calls_per_prompt"] or 1
    prompt_preview = (task["prompt_text"][:50] + "...") if len(task["prompt_text"]) > 50 else task["prompt_text"]
    
    logger.info(f"[DISPATCHER-S3] Task 数据已加载 | platform={platform} | calls={m} | prompt={prompt_preview}")
    
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
                        call_index=call_index
                    )
                    if cloro_task_id:
                        logger.info(f"[DISPATCHER-S4] Cloro 调用成功 | task_id={task_id} | call={call_index}/{m} | cloro_id={cloro_task_id}")
                        return True
                    else:
                        logger.error(f"[DISPATCHER-S4] Cloro 调用失败 | task_id={task_id} | call={call_index}/{m}")
                        return False
                except Exception as e:
                    logger.error(f"[DISPATCHER-S4] Cloro 调用异常 | task_id={task_id} | call={call_index}/{m} | error={e}")
                    return False
        
        results = await asyncio.gather(*[
            call_cloro_with_index(i) for i in range(1, m + 1)
        ], return_exceptions=True)
    
    # [DISPATCHER-S5] Count successes and update status
    success_count = sum(1 for r in results if r is True)
    
    logger.info(f"[DISPATCHER-S5] Cloro 调用汇总 | task_id={task_id} | success={success_count}/{m}")
    
    if success_count == m:
        await database.execute(
            update(geo_tasks)
            .where(geo_tasks.c.task_id == task_id)
            .values(dispatched_count=success_count)
        )
        logger.info(f"[DISPATCHER-S5] Task dispatch 完成 | task_id={task_id} | status=success")
        return "success"
    elif success_count == 0:
        await database.execute(
            update(geo_tasks)
            .where(geo_tasks.c.task_id == task_id)
            .values(status="DISPATCH_FAILED", dispatched_count=0)
        )
        logger.error(f"[DISPATCHER-S5] Task dispatch 全部失败 | task_id={task_id} | status=DISPATCH_FAILED")
        return "failed"
    else:
        await database.execute(
            update(geo_tasks)
            .where(geo_tasks.c.task_id == task_id)
            .values(dispatched_count=success_count)
        )
        logger.warning(f"[DISPATCHER-S5] Task dispatch 部分成功 | task_id={task_id} | success={success_count}/{m}")
        return "partial"


@app.get("/health")
def health_check():
    return {"status": "ok"}
