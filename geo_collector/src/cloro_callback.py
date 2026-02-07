"""
Cloro Callback Service

Cloud Run Service that receives async callbacks from Cloro.dev API.
Receives the callback JSON, enriches with task metadata, and publishes to Pub/Sub.

Flow:
    Cloro API → HTTP POST → This Service → Pub/Sub (geo-cloro-callbacks)
"""
from fastapi import FastAPI, Request, HTTPException, Query
from pydantic import UUID4
import logging
import json
import time
from sqlalchemy import select
from src.clients.pubsub import PubSubService
from src.core.config import get_settings
from src.core.database import database, geo_tasks

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CloroCallback")

app = FastAPI(title="GEO Cloro Callback Service")
settings = get_settings()
pubsub_service = PubSubService()


@app.on_event("startup")
async def startup():
    """Connect to DB on startup."""
    logger.info("[CALLBACK-S0] ========== Cloro Callback Service 启动 ==========")
    logger.info("[CALLBACK-S0] 连接数据库...")
    await database.connect()
    logger.info("[CALLBACK-S0] 数据库连接成功")


@app.on_event("shutdown")
async def shutdown():
    logger.info("[CALLBACK-S0] 断开数据库连接...")
    await database.disconnect()
    logger.info("[CALLBACK-S0] ========== Cloro Callback Service 关闭 ==========")


@app.post("/callback/cloro")
async def receive_cloro_callback(
    request: Request,
    task_id: UUID4 = Query(..., description="The UUID of the original task"),
    call_index: int = Query(1, description="Which call number for this task (1~M)"),
):
    """
    Receives async callback from Cloro.dev API.
    
    Design:
    - Uses URL query params (task_id, call_index) for routing
    - Resilient to Cloro JSON schema changes
    - ELT pattern: extract raw, load to Pub/Sub, transform later
    
    Flow:
    1. Receive JSON body
    2. Query task metadata from geo_tasks
    3. Publish to Pub/Sub (geo-cloro-callbacks)
    4. Return 200 OK immediately
    """
    start_time = time.time()
    
    # [CALLBACK-S1] 接收 Cloro 回调
    logger.info(f"[CALLBACK-S1] 收到 Cloro 回调 | task_id={task_id} | call_index={call_index} | client={request.client.host}")
    
    try:
        body = await request.json()
    except Exception:
        logger.warning(f"[CALLBACK-S1] JSON 解析失败 | task_id={task_id}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    payload_size = len(json.dumps(body))
    logger.info(f"[CALLBACK-S1] 回调数据已接收 | task_id={task_id} | size={payload_size} bytes")

    # [CALLBACK-S2] Query geo_tasks for metadata
    logger.info(f"[CALLBACK-S2] 查询 task 元数据 | task_id={task_id}")
    task_meta = None
    try:
        query = select(geo_tasks).where(geo_tasks.c.task_id == str(task_id))
        row = await database.fetch_one(query)
        if row:
            task_meta = {
                "platform": row["platform"],
                "batch_id": row["batch_id"],
                "client_name": row["client_name"],
                "peers": row["peers"],
                "topic": row["topic"],
                "product": row["product"],
                "country": row["country"],
                "intent": row["intent"],
                "prompt_text": row["prompt_text"],
                "target_user": row["target_user"],
                "call_index": call_index,
            }
            logger.info(f"[CALLBACK-S2] 元数据已加载 | task_id={task_id} | client={task_meta['client_name']} | platform={task_meta['platform']}")
        else:
            logger.warning(f"[CALLBACK-S2] Task 不存在，继续处理 | task_id={task_id}")
    except Exception as e:
        logger.error(f"[CALLBACK-S2] 查询元数据失败 | task_id={task_id} | error={e}")

    # [CALLBACK-S3] Publish to Pub/Sub
    logger.info(f"[CALLBACK-S3] 发布消息到 Pub/Sub | task_id={task_id}")
    try:
        message_id = pubsub_service.publish_callback_message(str(task_id), body, task_meta)
        duration = (time.time() - start_time) * 1000
        logger.info(f"[CALLBACK-S3] Pub/Sub 发布成功 | task_id={task_id} | msg_id={message_id} | time={duration:.2f}ms")
    except Exception as e:
        logger.error(f"[CALLBACK-S3] Pub/Sub 发布失败 | task_id={task_id} | error={e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    return {"status": "received", "task_id": str(task_id)}


@app.get("/health")
def health_check():
    return {"status": "ok"}
