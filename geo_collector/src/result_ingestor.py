"""
Result Ingestor Service

Cloud Run Service that ingests Cloro API responses into the database.
Triggered by Pub/Sub (geo-cloro-callbacks) to process callback data.

Features:
- Unpacks platform-specific response formats
- Writes to geo_results table
- Updates task/request completion status
- Idempotent via unique constraint on (task_id, call_index)

Flow:
from src.core.database import database, geo_results, geo_tasks, geo_requests, geo_reports
"""
import base64
import json
import logging
import time
from fastapi import FastAPI, Request, HTTPException
from sqlalchemy import insert, update, select, func
from sqlalchemy.exc import IntegrityError
from src.core.database import database, geo_results, geo_tasks, geo_requests, geo_reports
from src.services.unpackers.factory import UnpackerFactory

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ResultIngestor")

app = FastAPI(title="GEO Result Ingestor Service")


@app.on_event("startup")
async def startup():
    """Connect to database on startup."""
    logger.info("[INGESTOR-S0] ========== Result Ingestor Service 启动 ==========")
    logger.info("[INGESTOR-S0] 连接数据库...")
    await database.connect()
    logger.info("[INGESTOR-S0] 数据库连接成功")


@app.on_event("shutdown")
async def shutdown():
    """Disconnect from database on shutdown."""
    logger.info("[INGESTOR-S0] 断开数据库连接...")
    await database.disconnect()
    logger.info("[INGESTOR-S0] ========== Result Ingestor Service 关闭 ==========")


@app.post("/ingest/result")
async def ingest_result(request: Request):
    """
    Pub/Sub Push endpoint for ingesting Cloro callback results.
    
    Message format: {
        "task_id": "uuid",
        "payload": {...},
        "task_meta": {...}
    }
    """
    try:
        envelope = await request.json()
        if not envelope.get("message"):
            logger.error("[INGESTOR-S1] Bad Request: no message field")
            raise HTTPException(status_code=400, detail="Bad Request")

        pubsub_message = envelope["message"]
        msg_id = pubsub_message.get("messageId")
        
        # Decode Base64 data
        data_str = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        message_data = json.loads(data_str)
        
        task_id = message_data.get("task_id")
        payload = message_data.get("payload")
        task_meta = message_data.get("task_meta")

        if not task_id or not payload:
            logger.error(f"[INGESTOR-S1] 无效消息格式 | msg_id={msg_id}")
            return {"status": "ignored"}

        call_index = task_meta.get("call_index", 1) if task_meta else 1

        logger.info(f"[INGESTOR-S1] 收到 ingest 消息 | task_id={task_id} | call_index={call_index} | msg_id={msg_id}")
        await process_ingestion(task_id, call_index, payload, task_meta)
        
        return {"status": "success"}

    except Exception as e:
        logger.error(f"[INGESTOR-ERR] 处理消息失败 | error={e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_ingestion(task_id: str, call_index: int, payload: dict, task_meta: dict = None):
    """
    Core ingestion logic:
    1. Unpack platform-specific response data
    2. Insert into geo_results
    3. Update geo_tasks.completed_count
    4. Check task completion -> update status
    5. Check request completion -> update geo_requests status
    """
    start_time = time.time()
    
    # [INGESTOR-S2] Identify platform
    if task_meta and task_meta.get("platform"):
        platform = task_meta["platform"]
    else:
        task_info = payload.get("task", {})
        task_type = task_info.get("taskType", "UNKNOWN")
        platform = task_type.lower()
    
    cloro_task_id = payload.get("task", {}).get("id")
    
    logger.info(f"[INGESTOR-S2] 开始处理 | task_id={task_id} | call_index={call_index} | platform={platform} | cloro_id={cloro_task_id}")
    
    try:
        # [INGESTOR-S3] Unpack response
        logger.info(f"[INGESTOR-S3] 解包响应数据 | task_id={task_id} | platform={platform}")
        unpacker = UnpackerFactory.get_unpacker(platform)
        unpacked_data = unpacker.unpack(payload)
        
        text_preview = (unpacked_data.get("text", "")[:100] + "...") if unpacked_data.get("text") else "(empty)"
        sources_count = len(unpacked_data.get("sources") or [])
        logger.info(f"[INGESTOR-S3] 解包完成 | task_id={task_id} | text_len={len(unpacked_data.get('text', ''))} | sources={sources_count}")

        # [INGESTOR-S4] DB Transaction - Insert result
        logger.info(f"[INGESTOR-S4] 写入 geo_results | task_id={task_id} | call_index={call_index}")
        async with database.transaction():
            insert_values = {
                "task_id": task_id,
                "request_id": task_meta.get("request_id") if task_meta else None,
                "cloro_task_id": cloro_task_id,
                "call_index": call_index,
                "cloro_response": payload,
                "http_status_code": 200,
                "latency_ms": 0,
                
                # Unpacked fields
                "text": unpacked_data.get("text"),
                "html": unpacked_data.get("html"),
                "markdown": unpacked_data.get("markdown"),
                "sources": unpacked_data.get("sources"),
                "shopping_cards": unpacked_data.get("shopping_cards"),
                "places": unpacked_data.get("places"),
                "entities": unpacked_data.get("entities"),
                "search_queries": unpacked_data.get("search_queries"),
                "citation_pills": unpacked_data.get("citation_pills"),
            }
            
            # Task metadata (from geo_tasks)
            if task_meta:
                insert_values.update({
                    # Report 关联
                    "report_id": task_meta.get("report_id"),
                    "report_name": task_meta.get("report_name"),
                    # Client 信息
                    "client_id": task_meta.get("client_id"),
                    "client_name": task_meta.get("client_name"),
                    "peers": task_meta.get("peers") or [],
                    "owned_domains": task_meta.get("owned_domains") or [],
                    # 请求参数
                    "platform": task_meta.get("platform"),
                    "batch_id": task_meta.get("batch_id"),
                    "topic": task_meta.get("topic"),
                    "product": task_meta.get("product"),
                    "country": task_meta.get("country"),
                    "intent": task_meta.get("intent"),
                    "prompt_text": task_meta.get("prompt_text"),
                    "target_user": task_meta.get("target_user"),
                })
            
            await database.execute(insert(geo_results).values(**insert_values))
            
            # Update completed_count
            await database.execute(
                update(geo_tasks)
                .where(geo_tasks.c.task_id == task_id)
                .values(completed_count=geo_tasks.c.completed_count + 1)
            )

            # [INGESTOR-S4.1] Reset Report Status if needed
            # If report is 'completed', it implies previous analysis is done.
            # New data means it's no longer 'completed' in terms of coverage.
            if task_meta and task_meta.get("report_id"):
                report_id = task_meta.get("report_id")
                # Optimistically update to 'analyzing' if currently 'completed'
                # This reflects that the report is in a state where analysis is pending/ongoing
                await database.execute(
                    update(geo_reports)
                    .where(geo_reports.c.id == report_id)
                    .where(geo_reports.c.status == "completed")
                    .values(status="analyzing")
                )
        
        logger.info(f"[INGESTOR-S4] geo_results 写入成功 | task_id={task_id} | call_index={call_index}")
        
        # [INGESTOR-S5] Check task completion
        logger.info(f"[INGESTOR-S5] 检查 task 完成状态 | task_id={task_id}")
        task = await database.fetch_one(
            select(geo_tasks).where(geo_tasks.c.task_id == task_id)
        )
        
        if task and task["completed_count"] >= task["calls_per_prompt"]:
            await database.execute(
                update(geo_tasks)
                .where(geo_tasks.c.task_id == task_id)
                .values(status="COMPLETED")
            )
            logger.info(f"[INGESTOR-S5] Task 已完成 | task_id={task_id} | completed={task['completed_count']}/{task['calls_per_prompt']}")
            
            # [INGESTOR-S6] Check request completion
            await check_request_completion(str(task["request_id"]))
        else:
            logger.info(f"[INGESTOR-S5] Task 进行中 | task_id={task_id} | completed={task['completed_count']}/{task['calls_per_prompt']}")

        duration = (time.time() - start_time) * 1000
        logger.info(f"[INGESTOR-S5] Ingest 完成 | task_id={task_id} | call_index={call_index} | time={duration:.2f}ms")
        
    except IntegrityError:
        logger.warning(f"[INGESTOR-S4] 重复数据，跳过 | task_id={task_id} | call_index={call_index}")
    except Exception as e:
        logger.error(f"[INGESTOR-ERR] Ingest 失败 | task_id={task_id} | call_index={call_index} | error={e}")
        raise


async def check_request_completion(request_id: str):
    """
    Check if all tasks in a request are completed.
    If so, update geo_requests.status to COMPLETED.
    """
    logger.info(f"[INGESTOR-S6] 检查 request 完成状态 | request_id={request_id}")
    try:
        pending_count = await database.fetch_val(
            select(func.count()).select_from(geo_tasks).where(
                geo_tasks.c.request_id == request_id,
                geo_tasks.c.status != "COMPLETED"
            )
        )
        
        if pending_count == 0:
            await database.execute(
                update(geo_requests)
                .where(geo_requests.c.request_id == request_id)
                .values(status="COMPLETED")
            )
            logger.info(f"[INGESTOR-S6] Request 已完成 | request_id={request_id} | 所有 tasks 已完成")
        else:
            logger.info(f"[INGESTOR-S6] Request 进行中 | request_id={request_id} | pending_tasks={pending_count}")
    except Exception as e:
        logger.error(f"[INGESTOR-S6] 检查 request 完成状态失败 | request_id={request_id} | error={e}")


@app.get("/health")
def health_check():
    return {"status": "ok"}
