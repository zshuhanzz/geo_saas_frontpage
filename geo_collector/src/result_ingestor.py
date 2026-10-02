"""
Result Ingestor Service (V2)

Cloud Run Service that ingests Cloro API responses into the database.
Triggered by Pub/Sub (geo-cloro-callbacks) to process callback data.

V2 schema:
- Writes client_id, topic_id, client_prompt_id, final_prompt to geo_results
- Checks task completion directly

Phase 2.5a: migrated from `databases` lib to `geo_common.db` asyncpg pool.
JSONB columns are encoded with ``json.dumps`` because asyncpg sends raw
bytes/text — letting it serialize Python dicts to JSONB requires a custom
codec setup we don't need here.

Flow:
    Pub/Sub (geo-cloro-callbacks) → This Service → geo_results
"""
import base64
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import asyncpg
from fastapi import FastAPI, HTTPException, Request

from src.core import database as db
from src.services.unpackers.factory import UnpackerFactory

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ResultIngestor")


# FastAPI ``@app.on_event`` was deprecated; use ``lifespan`` context manager.
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[INGESTOR-S0] ========== Result Ingestor Service 启动 ==========")
    logger.info("[INGESTOR-S0] 连接数据库...")
    await db.connect()
    logger.info("[INGESTOR-S0] 数据库连接成功")
    try:
        yield
    finally:
        logger.info("[INGESTOR-S0] 断开数据库连接...")
        await db.disconnect()
        logger.info("[INGESTOR-S0] ========== Result Ingestor Service 关闭 ==========")


app = FastAPI(title="GEO Result Ingestor Service (V2)", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Insert column ordering — kept as a module-level constant so the SQL string
# and the value-tuple stay in lockstep. asyncpg requires positional binding,
# unlike the ``databases`` lib's ``insert(table).values(**dict)`` style.
# ---------------------------------------------------------------------------

_GEO_RESULTS_INSERT_COLUMNS = (
    "task_id",
    "cloro_task_id",
    "call_index",
    "cloro_response",
    "http_status_code",
    "latency_ms",
    "text",
    "html",
    "markdown",
    "sources",
    "shopping_cards",
    "places",
    "entities",
    "search_queries",
    "citation_pills",
    # V2 関連
    "client_prompt_id",
    "client_id",
    "client_name",
    "peers",
    "owned_domains",
    "platform",
    "batch_id",
    "topic",
    "topic_id",
    "topic_name",
    "product",
    "country",
    "language",
    "intent",
    "client_prompt",
    "final_prompt",
)

_GEO_RESULTS_JSONB_COLUMNS = frozenset({
    "cloro_response",
    "sources",
    "shopping_cards",
    "places",
    "entities",
    "search_queries",
    "citation_pills",
})

_GEO_RESULTS_INSERT_SQL = (
    f"INSERT INTO {db.GEO_RESULTS} ("
    + ", ".join(_GEO_RESULTS_INSERT_COLUMNS)
    + ") VALUES ("
    + ", ".join(f"${i + 1}" for i in range(len(_GEO_RESULTS_INSERT_COLUMNS)))
    + ")"
)


async def _prompt_exists_for_client(
    conn, client_id: str, client_prompt_id: str
) -> bool:
    return bool(
        await conn.fetchval(
            f"""
            SELECT 1
            FROM {db.GEO_CLIENT_PROMPTS}
            WHERE client_id = $1::uuid
              AND id = $2::uuid
            FOR KEY SHARE
            """,
            client_id,
            client_prompt_id,
        )
    )


def _to_insert_values(row: dict) -> tuple:
    """
    Project the loosely-typed `row` dict into a positional tuple aligned with
    `_GEO_RESULTS_INSERT_COLUMNS`. JSONB columns are pre-serialized so that
    asyncpg sends them as text (matching the column type without requiring
    custom codec registration).
    """
    values: list[Any] = []
    for col in _GEO_RESULTS_INSERT_COLUMNS:
        value = row.get(col)
        if col in _GEO_RESULTS_JSONB_COLUMNS and value is not None:
            value = json.dumps(value)
        values.append(value)
    return tuple(values)


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

        logger.info(
            f"[INGESTOR-S1] 收到 ingest 消息 | task_id={task_id} | "
            f"call_index={call_index} | msg_id={msg_id}"
        )
        await process_ingestion(task_id, call_index, payload, task_meta)

        return {"status": "success"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[INGESTOR-ERR] 处理消息失败 | error={e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_ingestion(
    task_id: str,
    call_index: int,
    payload: dict,
    task_meta: Optional[dict] = None,
) -> None:
    """
    Core ingestion logic (V2):
    1. Unpack platform-specific response data
    2. Insert into geo_results (with client_id, topic_id, client_prompt_id, final_prompt)
    3. Update geo_tasks.completed_count
    4. Check task completion → update status
    """
    pool = db.get_pool()

    # If task_meta is missing, try to recover it from geo_tasks
    if not task_meta or not task_meta.get("client_prompt_id"):
        logger.warning(
            f"[INGESTOR-S1.5] task_meta 缺失或无 client_prompt_id，尝试从 DB 恢复 | "
            f"task_id={task_id}"
        )
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT * FROM {db.GEO_TASKS} WHERE task_id = $1",
                    task_id,
                )
                if row:
                    task_meta = _row_to_task_meta(row, call_index)
                    if row["client_prompt_id"]:
                        cp_row = await conn.fetchrow(
                            f"SELECT text FROM {db.GEO_CLIENT_PROMPTS} WHERE id = $1",
                            row["client_prompt_id"],
                        )
                        if cp_row:
                            task_meta["client_prompt_text"] = cp_row["text"]
                    logger.info(
                        f"[INGESTOR-S1.5] 从 DB 恢复 task_meta 成功 | task_id={task_id} | "
                        f"client_prompt_id={task_meta.get('client_prompt_id')}"
                    )
                else:
                    logger.warning(f"[INGESTOR-S1.5] Task 在 DB 中不存在 | task_id={task_id}")
        except Exception as e:
            logger.error(
                f"[INGESTOR-S1.5] 恢复 task_meta 失败 | task_id={task_id} | error={e}"
            )

    # Final guard: if still no client_prompt_id, skip (non-retryable)
    if not task_meta or not task_meta.get("client_prompt_id"):
        logger.warning(
            f"[INGESTOR-SKIP] 无法获取 client_prompt_id，跳过此消息 | "
            f"task_id={task_id} | call_index={call_index}"
        )
        return

    start_time = time.time()

    # [INGESTOR-S2] Identify platform
    if task_meta and task_meta.get("platform"):
        platform = task_meta["platform"]
    else:
        task_info = payload.get("task", {})
        task_type = task_info.get("taskType", "UNKNOWN")
        platform = task_type.lower()
        response_result = (payload.get("response", {}) or {}).get("result", {}) or {}
        if platform == "google" and any(
            key in response_result for key in ("aioverview", "aiOverview", "ai_overview")
        ):
            platform = "aioverview"

    cloro_task_id = payload.get("task", {}).get("id")

    logger.info(
        f"[INGESTOR-S2] 开始处理 | task_id={task_id} | call_index={call_index} | "
        f"platform={platform} | cloro_id={cloro_task_id}"
    )

    try:
        # [INGESTOR-S3] Unpack response
        logger.info(f"[INGESTOR-S3] 解包响应数据 | task_id={task_id} | platform={platform}")
        unpacker = UnpackerFactory.get_unpacker(platform)
        unpacked_data = unpacker.unpack(payload)

        text_value = unpacked_data.get("text") or ""
        text_preview = (text_value[:100] + "...") if text_value else "(empty)"
        sources_count = len(unpacked_data.get("sources") or [])
        logger.info(
            f"[INGESTOR-S3] 解包完成 | task_id={task_id} | "
            f"text_len={len(text_value)} | sources={sources_count}"
        )

        # [INGESTOR-S4] DB Transaction - Insert result + bump counter
        logger.info(
            f"[INGESTOR-S4] 写入 geo_results | task_id={task_id} | call_index={call_index}"
        )
        insert_row = {
            "task_id": task_id,
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

        if task_meta:
            insert_row.update({
                "client_prompt_id": task_meta.get("client_prompt_id"),
                "client_id": task_meta.get("client_id"),
                "client_name": task_meta.get("client_name"),
                "peers": task_meta.get("peers") or [],
                "owned_domains": task_meta.get("owned_domains") or [],
                "platform": task_meta.get("platform"),
                "batch_id": task_meta.get("batch_id"),
                "topic": task_meta.get("topic"),
                "topic_id": task_meta.get("topic_id"),
                "topic_name": task_meta.get("topic_name") or task_meta.get("topic"),
                "product": task_meta.get("product"),
                "country": task_meta.get("country"),
                "language": task_meta.get("language"),
                "intent": task_meta.get("intent"),
                "client_prompt": task_meta.get("client_prompt_text"),
                "final_prompt": task_meta.get("final_prompt"),
            })

        async with pool.acquire() as conn:
            async with conn.transaction():
                prompt_still_exists = await _prompt_exists_for_client(
                    conn,
                    str(insert_row.get("client_id")),
                    str(insert_row.get("client_prompt_id")),
                )
                if not prompt_still_exists:
                    logger.info(
                        "[INGESTOR-SKIP] client_prompt_id no longer exists; "
                        "skip stale result | task_id=%s | client_prompt_id=%s",
                        task_id,
                        insert_row.get("client_prompt_id"),
                    )
                    return

                await conn.execute(
                    _GEO_RESULTS_INSERT_SQL,
                    *_to_insert_values(insert_row),
                )

                # Update completed_count
                await conn.execute(
                    f"""
                    UPDATE {db.GEO_TASKS}
                       SET completed_count = completed_count + 1
                     WHERE task_id = $1
                    """,
                    task_id,
                )

        logger.info(
            f"[INGESTOR-S4] geo_results 写入成功 | task_id={task_id} | call_index={call_index}"
        )

        # [INGESTOR-S5] Check task completion
        logger.info(f"[INGESTOR-S5] 检查 task 完成状态 | task_id={task_id}")
        async with pool.acquire() as conn:
            task = await conn.fetchrow(
                f"""
                SELECT completed_count, calls_per_prompt
                  FROM {db.GEO_TASKS}
                 WHERE task_id = $1
                """,
                task_id,
            )

            if task and task["completed_count"] >= task["calls_per_prompt"]:
                await conn.execute(
                    f"UPDATE {db.GEO_TASKS} SET status = 'COMPLETED' WHERE task_id = $1",
                    task_id,
                )
                logger.info(
                    f"[INGESTOR-S5] Task 已完成 | task_id={task_id} | "
                    f"completed={task['completed_count']}/{task['calls_per_prompt']}"
                )
            else:
                completed = task["completed_count"] if task else "?"
                target = task["calls_per_prompt"] if task else "?"
                logger.info(
                    f"[INGESTOR-S5] Task 进行中 | task_id={task_id} | "
                    f"completed={completed}/{target}"
                )

        duration = (time.time() - start_time) * 1000
        logger.info(
            f"[INGESTOR-S5] Ingest 完成 | task_id={task_id} | "
            f"call_index={call_index} | time={duration:.2f}ms"
        )

    except asyncpg.exceptions.ForeignKeyViolationError:
        logger.warning(
            f"[INGESTOR-S4] Task 已不存在，跳过孤儿消息 | "
            f"task_id={task_id} | call_index={call_index}"
        )
        return
    except asyncpg.exceptions.UniqueViolationError:
        logger.warning(
            f"[INGESTOR-S4] 重复数据（幂等跳过）| "
            f"task_id={task_id} | call_index={call_index}"
        )
        return
    except asyncpg.exceptions.NotNullViolationError as e:
        logger.warning(
            f"[INGESTOR-S4] 必填字段缺失（不可重试）| "
            f"task_id={task_id} | call_index={call_index} | error={e}"
        )
        return
    except Exception as e:
        # Defensive fallback: keep the original substring matching for any
        # IntegrityError-shaped exception that doesn't surface as a typed
        # asyncpg subclass (e.g. wrapped by a transaction context).
        error_msg = str(e).lower()
        if "duplicate key" in error_msg or "already exists" in error_msg or "unique" in error_msg:
            logger.warning(
                f"[INGESTOR-S4] 重复数据（幂等跳过）| "
                f"task_id={task_id} | call_index={call_index}"
            )
            return
        if "foreign key" in error_msg or "fkey" in error_msg:
            logger.warning(
                f"[INGESTOR-S4] Task 已不存在，跳过孤儿消息 | "
                f"task_id={task_id} | call_index={call_index}"
            )
            return
        if "not-null constraint" in error_msg or "violates not-null" in error_msg:
            logger.warning(
                f"[INGESTOR-S4] 必填字段缺失（不可重试）| "
                f"task_id={task_id} | call_index={call_index} | error={e}"
            )
            return
        logger.error(
            f"[INGESTOR-ERR] Ingest 失败 | "
            f"task_id={task_id} | call_index={call_index} | error={e}"
        )
        raise


def _row_to_task_meta(row: asyncpg.Record, call_index: int) -> dict:
    """Recover the in-flight `task_meta` dict from a `geo_tasks` row."""
    keys = row.keys()

    def _opt(name: str):
        return row[name] if name in keys else None

    return {
        "client_prompt_id": str(_opt("client_prompt_id")) if _opt("client_prompt_id") else None,
        "client_id": str(_opt("client_id")) if _opt("client_id") else None,
        "client_name": _opt("client_name"),
        "peers": _opt("peers") or [],
        "owned_domains": _opt("owned_domains") or [],
        "platform": _opt("platform"),
        "batch_id": _opt("batch_id"),
        "topic": _opt("topic"),
        "topic_id": str(_opt("topic_id")) if _opt("topic_id") else None,
        "product": _opt("product"),
        "country": _opt("country"),
        "language": _opt("language"),
        "intent": _opt("intent"),
        "final_prompt": _opt("final_prompt"),
        "call_index": call_index,
    }


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "2.2.0"}
