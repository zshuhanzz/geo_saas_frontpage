"""
Expander Entry Point

从 geo_requests 读取待处理数据，调用 Gemini 扩展为 geo_tasks。
可作为 Cloud Run Job 或独立脚本运行。
"""
import asyncio
import logging
from src.core.database import database
from src.services.prompt_expander import get_expander_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Expander")


async def process_pending_requests():
    """处理所有待扩展的 requests"""
    expander = get_expander_service()
    
    # [EXPANDER-S1] 获取待处理的 requests
    logger.info("[EXPANDER-S1] 查询待扩展的 geo_requests...")
    pending_requests = await expander.get_pending_requests(limit=10)
    
    if not pending_requests:
        logger.info("[EXPANDER-S1] 没有待处理的 geo_requests，退出")
        return
    
    logger.info(f"[EXPANDER-S1] 找到 {len(pending_requests)} 条待扩展的 requests")
    
    total_tasks = 0
    for idx, request in enumerate(pending_requests, start=1):
        request_id = str(request["request_id"])
        
        # [EXPANDER-S2] 处理单个 request
        logger.info(f"[EXPANDER-S2] 开始处理 Request ({idx}/{len(pending_requests)}) | request_id={request_id}")
        
        try:
            count = await expander.expand_request(request_id)
            total_tasks += count
            logger.info(f"[EXPANDER-S2] Request {request_id} 扩展完成 | 生成 {count} 条 tasks")
        except Exception as e:
            logger.error(f"[EXPANDER-S2] Request {request_id} 处理失败 | error={e}")
            # 继续处理下一个 request
            continue
    
    # [EXPANDER-S3] 汇总
    logger.info(f"[EXPANDER-S3] 本次运行完成 | 处理 {len(pending_requests)} 条 requests | 共生成 {total_tasks} 条 geo_tasks")


async def main():
    """主入口"""
    logger.info("[EXPANDER-S0] ========== Prompt Expander Job 启动 ==========")
    
    await database.connect()
    logger.info("[EXPANDER-S0] 数据库连接成功")
    
    try:
        await process_pending_requests()
    finally:
        await database.disconnect()
        logger.info("[EXPANDER-S0] 数据库连接已关闭")
    
    logger.info("[EXPANDER-S0] ========== Prompt Expander Job 结束 ==========")


if __name__ == "__main__":
    asyncio.run(main())
