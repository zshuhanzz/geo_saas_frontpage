"""
Cloro Callback Service (V2)

Cloud Run Service that receives async callbacks from Cloro.dev API.
Receives the callback JSON, enriches with task metadata, and publishes to Pub/Sub.

V2 schema: reads client_id, topic_id, client_prompt_id, final_prompt from geo_tasks.

Phase 2.5a: migrated from `databases` lib to `geo_common.db` asyncpg pool.

Flow:
    Cloro API → HTTP POST → This Service → Pub/Sub (geo-cloro-callbacks)
"""
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import UUID4

from src.clients.pubsub import PubSubService
from src.core import database as db
from src.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CloroCallback")


# FastAPI ``@app.on_event("startup"/"shutdown")`` was deprecated in favour of
# the ``lifespan`` context manager (FastAPI >=0.93). Same semantics: code before
# ``yield`` runs on app boot, code after runs on shutdown — but in one place,
# and exception-safe for resources spanning both phases.
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[CALLBACK-S0] ========== Cloro Callback Service 启动 ==========")
    logger.info("[CALLBACK-S0] 连接数据库...")
    await db.connect()
    logger.info("[CALLBACK-S0] 数据库连接成功")
    try:
        yield
    finally:
        logger.info("[CALLBACK-S0] 断开数据库连接...")
        await db.disconnect()
        logger.info("[CALLBACK-S0] ========== Cloro Callback Service 关闭 ==========")


app = FastAPI(title="GEO Cloro Callback Service (V2)", lifespan=lifespan)
settings = get_settings()
pubsub_service = PubSubService()


@app.post("/callback/cloro")
async def receive_cloro_callback(
    request: Request,
    task_id: UUID4 = Query(..., description="The UUID of the original task"),
    call_index: int = Query(1, description="Which call number for this task (1~M)"),
):
    """
    Receives async callback from Cloro.dev API.

    Flow:
    1. Receive JSON body
    2. Query task metadata from geo_tasks (V2 fields)
    3. Publish to Pub/Sub (geo-cloro-callbacks)
    4. Return 200 OK immediately
    """
    start_time = time.time()

    logger.info(
        f"[CALLBACK-S1] 收到 Cloro 回调 | task_id={task_id} | "
        f"call_index={call_index} | client={request.client.host}"
    )

    try:
        body = await request.json()
    except Exception:
        logger.warning(f"[CALLBACK-S1] JSON 解析失败 | task_id={task_id}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    payload_size = len(json.dumps(body))
    logger.info(
        f"[CALLBACK-S1] 回调数据已接收 | task_id={task_id} | size={payload_size} bytes"
    )

    # [CALLBACK-S2] Query geo_tasks for metadata (V2 schema)
    logger.info(f"[CALLBACK-S2] 查询 task 元数据 | task_id={task_id}")
    task_meta = None
    pool = db.get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {db.GEO_TASKS} WHERE task_id = $1",
                str(task_id),
            )
            if row:
                task_meta = {
                    # V2 关联
                    "client_prompt_id": str(row["client_prompt_id"]) if row["client_prompt_id"] else None,
                    # Client 信息
                    "client_id": str(row["client_id"]) if row["client_id"] else None,
                    "client_name": row["client_name"],
                    "peers": row["peers"] or [],
                    "owned_domains": row["owned_domains"] or [],
                    # 请求参数
                    "platform": row["platform"],
                    "batch_id": row["batch_id"],
                    "topic_id": str(row["topic_id"]) if row["topic_id"] else None,
                    "topic": row["topic"],
                    "product": row["product"],
                    "country": row["country"],
                    "language": row["language"],
                    "intent": row["intent"],
                    "final_prompt": row["final_prompt"],
                    "persona_used": row["persona_used"],
                    "call_index": call_index,
                }
                # Fetch client_prompt original text
                if row["client_prompt_id"]:
                    cp_row = await conn.fetchrow(
                        f"SELECT text FROM {db.GEO_CLIENT_PROMPTS} WHERE id = $1",
                        row["client_prompt_id"],
                    )
                    if cp_row:
                        task_meta["client_prompt_text"] = cp_row["text"]
                logger.info(
                    f"[CALLBACK-S2] 元数据已加载 | task_id={task_id} | "
                    f"client={task_meta['client_name']} | platform={task_meta['platform']}"
                )
            else:
                logger.warning(f"[CALLBACK-S2] Task 不存在，继续处理 | task_id={task_id}")
    except Exception as e:
        logger.error(f"[CALLBACK-S2] 查询元数据失败 | task_id={task_id} | error={e}")

    # [CALLBACK-S3] Publish to Pub/Sub
    logger.info(f"[CALLBACK-S3] 发布消息到 Pub/Sub | task_id={task_id}")
    try:
        message_id = pubsub_service.publish_callback_message(str(task_id), body, task_meta)
        duration = (time.time() - start_time) * 1000
        logger.info(
            f"[CALLBACK-S3] Pub/Sub 发布成功 | task_id={task_id} | "
            f"msg_id={message_id} | time={duration:.2f}ms"
        )
    except Exception as e:
        logger.error(f"[CALLBACK-S3] Pub/Sub 发布失败 | task_id={task_id} | error={e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    return {"status": "received", "task_id": str(task_id)}


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}
