import httpx
import logging
import json
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# --- Strategy Interface ---

class CloroPlatformStrategy(ABC):
    """
    策略模式基类：定义不同 AI 平台（ChatGPT, Gemini 等）的差异化行为。
    同时支持同步（Monitor API）和异步（Async Task API）两种模式的配置。
    """
    
    @abstractmethod
    def get_platform_key(self) -> str:
        """返回平台标识符，如 'chatgpt' (用于策略注册)。"""
        pass

    @abstractmethod
    def get_sync_endpoint_suffix(self) -> str:
        """[同步模式] 返回 API 路径后缀，如 '/v1/monitor/chatgpt'。"""
        pass
        
    @abstractmethod
    def get_async_task_type(self) -> str:
        """[异步模式] 返回 taskType 枚举值，如 'CHATGPT'。"""
        pass

    @abstractmethod
    def get_default_include_options(self) -> Dict[str, Any]:
        """返回该平台默认的 'include' 参数配置。"""
        pass

    def build_payload(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Build the provider-specific Cloro request payload."""
        return {
            "prompt": task["final_prompt"],
            "country": task.get("country", "US"),
            "include": self.get_default_include_options()
        }

# --- Concrete Strategies ---

class ChatGPTStrategy(CloroPlatformStrategy):
    def get_platform_key(self) -> str:
        return "chatgpt"

    def get_sync_endpoint_suffix(self) -> str:
        return "/v1/monitor/chatgpt"
        
    def get_async_task_type(self) -> str:
        return "CHATGPT"

    def get_default_include_options(self) -> Dict[str, Any]:
        return {
            "markdown": False,
            "rawResponse": False,
            "searchQueries": True # 对 SEO 分析很有用
        }

class GeminiStrategy(CloroPlatformStrategy):
    def get_platform_key(self) -> str:
        return "gemini"

    def get_sync_endpoint_suffix(self) -> str:
        return "/v1/monitor/gemini"
        
    def get_async_task_type(self) -> str:
        return "GEMINI"

    def get_default_include_options(self) -> Dict[str, Any]:
        return {
            "markdown": False,
            "html": False
        }

class GoogleAiModeStrategy(CloroPlatformStrategy):
    def get_platform_key(self) -> str:
        return "aimode"

    def get_sync_endpoint_suffix(self) -> str:
        return "/v1/monitor/aimode"

    def get_async_task_type(self) -> str:
        return "AIMODE"

    def get_default_include_options(self) -> Dict[str, Any]:
        return {
            "markdown": False
        }

class PerplexityStrategy(CloroPlatformStrategy):
    def get_platform_key(self) -> str:
        return "perplexity"

    def get_sync_endpoint_suffix(self) -> str:
        return "/v1/monitor/perplexity"
        
    def get_async_task_type(self) -> str:
        return "PERPLEXITY"

    def get_default_include_options(self) -> Dict[str, Any]:
        return {
            "html": False,
            "markdown": False,
            "rawResponse": False,
        }

class GoogleAIOverviewStrategy(CloroPlatformStrategy):
    def get_platform_key(self) -> str:
        return "aioverview"

    def get_sync_endpoint_suffix(self) -> str:
        return "/v1/monitor/google"

    def get_async_task_type(self) -> str:
        return "GOOGLE"

    def get_default_include_options(self) -> Dict[str, Any]:
        return {
            "aioverview": {
                "markdown": True
            }
        }

    def build_payload(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "query": task["final_prompt"],
            "country": task.get("country", "US"),
            "include": self.get_default_include_options()
        }

# --- Context / Service ---

class CloroService:
    """
    Cloro API 客户端服务。
    支持两种模式：
    1. 同步模式 (dispatch_task_sync): 使用 /v1/monitor/* 接口，适合本地调试。
    2. 异步模式 (dispatch_task_async): 使用 /v1/async/task 接口，适合生产环境高并发。
    """
    def __init__(self):
        self.base_url = settings.CLORO_BASE_URL
        self.api_key = settings.CLORO_API_KEY
        self.webhook_base = settings.WEBHOOK_PUBLIC_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 注册所有支持的策略
        self._strategies: Dict[str, CloroPlatformStrategy] = {}
        self._register_strategy(ChatGPTStrategy())
        self._register_strategy(GeminiStrategy())
        self._register_strategy(GoogleAiModeStrategy())
        self._register_strategy(PerplexityStrategy())
        self._register_strategy(GoogleAIOverviewStrategy())
        self._register_strategy_alias("ai_overview", "aioverview")
        self._register_strategy_alias("google_ai_overview", "aioverview")

    def _register_strategy(self, strategy: CloroPlatformStrategy):
        self._strategies[strategy.get_platform_key()] = strategy

    def _register_strategy_alias(self, alias: str, platform_key: str):
        self._strategies[alias] = self._strategies[platform_key]

    def _get_strategy(self, platform: str) -> CloroPlatformStrategy:
        """根据平台名称获取对应的策略对象。"""
        key = platform.lower().replace(" ", "_").replace("-", "_")
        strategy = self._strategies.get(key)
        if not strategy:
            logger.warning(f"[CLORO] 未知平台 '{platform}'，使用 ChatGPT 策略")
            return self._strategies["chatgpt"]
        return strategy

    def _construct_webhook_url(self, task_id: str, call_index: int = 1) -> str:
        """构造带有 task_id 和 call_index 参数的回调 URL。"""
        return f"{self.webhook_base}/callback/cloro?task_id={task_id}&call_index={call_index}"

    async def dispatch_task_async(self, client: httpx.AsyncClient, task: Dict[str, Any], call_index: int = 1) -> Optional[str]:
        """
        [生产环境/异步模式]
        使用 /v1/async/task 接口发送任务。
        
        Args:
            client: httpx AsyncClient
            task: 任务数据 (包含 task_id, platform, final_prompt 等)
            call_index: 第几次调用 (1 ~ M)，用于区分同一 task 的多次调用
        
        Payload 结构 (符合官方文档):
        {
            "taskType": "CHATGPT",
            "idempotencyKey": "uuid...",
            "webhook": { "url": "..." },
            "payload": {
                "prompt": "...",
                "country": "...",
                "include": {...}
            }
        }
        
        Returns:
            str: Cloro 返回的 Task ID (cloro_task_id)。
            None: 如果请求失败。
        """
        start_time = time.time()
        platform = task["platform"]
        task_id = str(task["task_id"])
        
        strategy = self._get_strategy(platform)
        
        # 1. 构建 URL (固定为异步任务接口)
        url = f"{self.base_url}/v1/async/task"
        
        # 2. 构建 Payload (嵌套结构)
        # idempotencyKey 需要包含 call_index 以区分同一 task 的不同调用
        idempotency_key = f"{task_id}-{call_index}"
        
        payload = {
            "taskType": strategy.get_async_task_type(),
            "idempotencyKey": idempotency_key,
            "webhook": {
                "url": self._construct_webhook_url(task_id, call_index)
            },
            "payload": {
                **strategy.build_payload(task)
            }
        }
        
        # 日志：记录关键信息和 Payload 预览
        prompt_preview = (task['final_prompt'][:50] + '...') if len(task['final_prompt']) > 50 else task['final_prompt']
        logger.info(f"[CLORO-S1] 发送异步任务 | task_id={task_id} | call={call_index} | platform={platform} | prompt={prompt_preview}")
        logger.debug(f"[CLORO-S1] Full Payload for {task_id}:\n{json.dumps(payload, indent=2)}")

        try:
            response = await client.post(url, json=payload, headers=self.headers)
            duration = (time.time() - start_time) * 1000
            
            if response.is_success:
                resp_data = response.json()
                # Extract Cloro's internal task ID from: {"task": {"id": "..."}}
                cloro_task_id = resp_data.get("task", {}).get("id")
                logger.info(f"[CLORO-S2] 发送成功 | task_id={task_id} | call={call_index} | cloro_id={cloro_task_id} | status={response.status_code} | time={duration:.2f}ms")
                return cloro_task_id
            else:
                logger.error(f"[CLORO-S2] 发送失败 | task_id={task_id} | call={call_index} | status={response.status_code} | resp={response.text}")
                return None
                
        except httpx.HTTPStatusError as e:
            logger.error(f"[CLORO-ERR] HTTP 错误 | task_id={task_id} | call={call_index} | error={e.response.text}")
            return None
        except Exception as e:
            logger.error(f"[CLORO-ERR] 异常 | task_id={task_id} | call={call_index} | error={str(e)}")
            return None

    async def dispatch_task_sync(self, client: httpx.AsyncClient, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        [调试/本地模式]
        使用 /v1/monitor/{platform} 接口发送任务。
        不带 Webhook，阻塞等待结果。
        
        Payload 结构 (扁平结构):
        {
            "prompt": "...",
            "country": "...",
            "include": {...}
        }
        """
        platform = task["platform"]
        task_id = str(task["task_id"])
        
        strategy = self._get_strategy(platform)
        
        # 1. 构建 URL (使用旧的 Monitor 接口)
        url = f"{self.base_url}{strategy.get_sync_endpoint_suffix()}"
        
        # 2. 构建 Payload (扁平结构)
        payload = {
            **strategy.build_payload(task)
        }

        logger.info(f"[CLORO-SYNC-S1] 发送同步任务 | task_id={task_id} | platform={platform}")
        logger.debug(f"[CLORO-SYNC-S1] Request Payload:\n{json.dumps(payload, indent=2)}")
        
        try:
            # 增加超时时间，因为 AI 生成通常较慢
            response = await client.post(url, json=payload, headers=self.headers, timeout=60.0)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"[CLORO-SYNC-S2] 同步任务完成 | task_id={task_id} | resp_size={len(str(data))} bytes")
            return data
            
        except httpx.TimeoutException:
            logger.error(f"[CLORO-SYNC-ERR] 超时 | task_id={task_id}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"[CLORO-SYNC-ERR] HTTP 错误 | task_id={task_id} | error={e.response.text}")
            return None
        except Exception as e:
            logger.error(f"[CLORO-SYNC-ERR] 异常 | task_id={task_id} | error={str(e)}")
            return None
