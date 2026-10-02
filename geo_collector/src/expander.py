"""
Expander Entry Point (V2.5 SaaS) — Client-based FinalPromptBuilder

Reads CLIENT_ID (and optionally TOPIC_ID) environment variables,
calls FinalPromptBuilder to expand active prompts into geo_tasks.
Can be run as a Cloud Run Job or standalone script.

Phase 2.5a: connect/disconnect now drive the shared `geo_common.db` asyncpg pool.
"""
import asyncio
import logging
import os

from src.core import database as db
from src.services.prompt_expander import get_builder_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Expander")


async def process_client(client_id: str, topic_id: str = None) -> int:
    """Process active prompts for a client."""
    builder = get_builder_service()

    if topic_id:
        logger.info(
            f"[EXPANDER-S1] 开始处理 Client Topic | "
            f"client_id={client_id} | topic_id={topic_id}"
        )
    else:
        logger.info(f"[EXPANDER-S1] 开始处理全部 Client Prompts | client_id={client_id}")

    try:
        count = await builder.expand_client(client_id, topic_id)
        logger.info(f"[EXPANDER-S1] Client 扩展完成 | 生成 {count} 条 tasks")
        return count
    except Exception as e:
        logger.error(f"[EXPANDER-S1] Client 处理失败 | client_id={client_id} | error={e}")
        raise


async def main() -> None:
    """主入口"""
    logger.info("[EXPANDER-S0] ========== FinalPromptBuilder Job 启动 ==========")

    await db.connect()
    logger.info("[EXPANDER-S0] 数据库连接成功")

    try:
        client_id = os.getenv("CLIENT_ID")
        topic_id = os.getenv("TOPIC_ID")

        if client_id:
            logger.info(f"[EXPANDER-S0] 指定 Client 模式 | CLIENT_ID={client_id}")
            total = await process_client(client_id, topic_id)
        else:
            logger.warning("[EXPANDER-S0] 未指定 CLIENT_ID，必须指定 CLIENT_ID 环境变量")
            total = 0

        logger.info(f"[EXPANDER-S0] 本次运行完成 | 共生成 {total} 条 geo_tasks")

    finally:
        await db.disconnect()
        logger.info("[EXPANDER-S0] 数据库连接已关闭")

    logger.info("[EXPANDER-S0] ========== FinalPromptBuilder Job 结束 ==========")


if __name__ == "__main__":
    asyncio.run(main())
