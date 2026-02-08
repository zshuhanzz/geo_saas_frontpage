"""
Prompt Expander Service

Expands geo_requests into N geo_tasks and publishes dispatch messages.
"""
import logging
import uuid
from typing import Optional, List
from sqlalchemy import select, update, insert
from src.core.database import database, geo_requests, geo_tasks
from src.clients.gemini import get_gemini_client
from src.clients.pubsub import PubSubService

logger = logging.getLogger(__name__)


class PromptExpanderService:
    """Prompt Expansion Service: generates geo_tasks from geo_requests"""
    
    def __init__(self):
        self.gemini = get_gemini_client()
        self.pubsub = PubSubService()
    
    async def expand_request(self, request_id: str) -> int:
        """
        Expands a geo_request into N geo_tasks.
        After creating tasks, publishes dispatch messages to Pub/Sub.
        
        Args:
            request_id: geo_requests.request_id
            
        Returns:
            int: Number of tasks created
        """
        # [EXPAND-S1] Fetch request data
        logger.info(f"[EXPAND-S1] 读取 request 数据 | request_id={request_id}")
        query = select(geo_requests).where(geo_requests.c.request_id == request_id)
        request = await database.fetch_one(query)
        
        if not request:
            logger.error(f"[EXPAND-S1] Request 不存在 | request_id={request_id}")
            raise ValueError(f"Request {request_id} not found")
        
        logger.info(f"[EXPAND-S1] Request 数据已加载 | client={request['client_name']} | platform={request['platform']} | country={request['country']}")
        
        # [EXPAND-S2] Optimistic lock: try to update status to EXPANDING
        logger.info(f"[EXPAND-S2] 尝试获取锁，更新状态为 EXPANDING | request_id={request_id}")
        affected = await database.execute(
            update(geo_requests)
            .where(geo_requests.c.request_id == request_id)
            .where(geo_requests.c.status == "PENDING")
            .values(status="EXPANDING")
        )
        
        if affected == 0:
            logger.warning(f"[EXPAND-S2] 获取锁失败，request 可能已被处理或状态非 PENDING | request_id={request_id}")
            return 0
        
        logger.info(f"[EXPAND-S2] 获取锁成功，开始扩展 | request_id={request_id}")
        
        try:
            # [EXPAND-S3] Call Gemini to generate prompts
            n = request["prompts_per_request"] or 20
            logger.info(f"[EXPAND-S3] 调用 Gemini 生成 prompts | n={n} | intent={request['intent']}")
            
            prompts = await self.gemini.generate_prompts(
                client_name=request["client_name"],
                peers=request["peers"],
                topic=request["topic"],
                product=request["product"],
                target_user=request["target_user"],
                intent=request["intent"] or "Solution Discovery",
                n=n
            )
            
            logger.info(f"[EXPAND-S3] Gemini 生成完成 | 实际返回 {len(prompts)} 条 prompts | request_id={request_id}")
            
            # [EXPAND-S4] Batch create geo_tasks
            logger.info(f"[EXPAND-S4] 开始创建 geo_tasks | request_id={request_id}")
            tasks_to_insert = []
            task_ids = []
            
            for i, prompt_text in enumerate(prompts, start=1):
                task_id = str(uuid.uuid4())
                task_ids.append(task_id)
                
                tasks_to_insert.append({
                    "task_id": task_id,
                    "request_id": request_id,
                    # Report 关联
                    "report_id": request["report_id"],
                    "report_name": request["report_name"],
                    # Client 信息
                    "client_id": request["client_id"],
                    "client_name": request["client_name"],
                    "peers": request["peers"] or [],
                    "owned_domains": request["owned_domains"] or [],
                    # 请求参数
                    "batch_id": request["batch_id"],
                    "topic": request["topic"],
                    "product": request["product"],
                    "country": request["country"],
                    "platform": request["platform"],
                    "intent": request["intent"],
                    "target_user": request["target_user"],
                    "calls_per_prompt": request["calls_per_prompt"],
                    # Prompt 信息
                    "prompt_text": prompt_text,
                    "prompt_index": i,
                    "status": "PENDING"
                })
            
            if tasks_to_insert:
                await database.execute_many(insert(geo_tasks), tasks_to_insert)
                logger.info(f"[EXPAND-S4] geo_tasks 创建完成 | count={len(tasks_to_insert)} | request_id={request_id}")
            
            # [EXPAND-S5] Update status to EXPANDED
            logger.info(f"[EXPAND-S5] 更新 request 状态为 EXPANDED | request_id={request_id}")
            await database.execute(
                update(geo_requests)
                .where(geo_requests.c.request_id == request_id)
                .values(status="EXPANDED")
            )
            
            # [EXPAND-S6] Publish dispatch messages to Pub/Sub
            logger.info(f"[EXPAND-S6] 发布 dispatch 消息到 Pub/Sub | task_count={len(task_ids)} | request_id={request_id}")
            try:
                published = self.pubsub.publish_dispatch_batch(task_ids, request_id)
                logger.info(f"[EXPAND-S6] Pub/Sub 发布成功 | published={published} | request_id={request_id}")
            except Exception as e:
                logger.error(f"[EXPAND-S6] Pub/Sub 发布失败 | error={e} | request_id={request_id}")
                # Don't fail the whole operation - tasks are created and can be dispatched manually
            
            return len(tasks_to_insert)
            
        except Exception as e:
            logger.error(f"[EXPAND-ERR] Request 扩展失败 | error={e} | request_id={request_id}")
            # Update status to EXPAND_FAILED
            await database.execute(
                update(geo_requests)
                .where(geo_requests.c.request_id == request_id)
                .values(status="EXPAND_FAILED")
            )
            raise
    
    async def get_pending_requests(self, limit: int = 10) -> list:
        """Get pending requests to process"""
        query = (
            select(geo_requests)
            .where(geo_requests.c.status == "PENDING")
            .order_by(geo_requests.c.created_at.asc())
            .limit(limit)
        )
        return await database.fetch_all(query)


# Global service instance
_expander_service: Optional[PromptExpanderService] = None

def get_expander_service() -> PromptExpanderService:
    """Get Prompt Expander service singleton"""
    global _expander_service
    if _expander_service is None:
        _expander_service = PromptExpanderService()
    return _expander_service
