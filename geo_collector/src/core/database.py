import sqlalchemy
from databases import Database
from sqlalchemy import (
    Column, 
    String, 
    Integer, 
    Text, 
    DateTime, 
    MetaData, 
    Table, 
    ForeignKey,
    Index,
    func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.core.config import get_settings

settings = get_settings()

# Database connection
# Limit pool size for Cloud Run / Local Dev to prevent connection exhaustion
database = Database(
    settings.DATABASE_URL, 
    min_size=1, 
    max_size=5
)
metadata = MetaData()

# ============================================================================
# 1. geo_requests - 业务输入层 (NEW)
# ============================================================================
geo_requests = Table(
    "geo_requests",
    metadata,
    Column("request_id", UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4()),
    Column("batch_id", String(50)),
    Column("client_name", String(100), nullable=False),
    Column("peers", String(500)),  # 竞对列表，逗号分隔
    Column("topic", String(100)),
    Column("product", String(100)),
    Column("country", String(10), nullable=False),
    Column("platform", String(50), nullable=False),
    Column("intent", String(50)),  # Enum: Solution Discovery, Competitive Evaluation, Specifics Inquiry
    Column("target_user", JSONB),
    
    # 扩展参数
    Column("prompts_per_request", Integer, server_default="20"),  # N: 每个 request 生成多少条 prompt
    Column("calls_per_prompt", Integer, server_default="100"),    # M: 每条 prompt 调用 Cloro 多少次
    
    # 状态管理
    Column("status", String(20), server_default="PENDING"),
    # PENDING → EXPANDING → EXPAND_FAILED → EXPANDED → COMPLETED → PARTIAL_COMPLETED
    
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

# ============================================================================
# 2. geo_tasks - 调用实例层 (REFACTORED)
# ============================================================================
geo_tasks = Table(
    "geo_tasks",
    metadata,
    Column("task_id", UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4()),
    Column("request_id", UUID(as_uuid=True), ForeignKey("geo_requests.request_id"), nullable=False),
    
    # 从 geo_requests 携带的业务字段
    Column("batch_id", String(50)),
    Column("client_name", String(100), nullable=False),
    Column("peers", String(500)),
    Column("topic", String(100)),
    Column("product", String(100)),
    Column("country", String(10), nullable=False),
    Column("platform", String(50), nullable=False),
    Column("intent", String(50)),
    Column("target_user", JSONB),
    Column("calls_per_prompt", Integer),  # M 值，从 request 携带
    
    # Gemini 生成的内容
    Column("prompt_text", Text, nullable=False),
    Column("prompt_index", Integer),  # 第几条 prompt (1~N)
    
    # 调度状态
    Column("dispatched_count", Integer, server_default="0"),  # 已发送的 Cloro 请求数
    Column("completed_count", Integer, server_default="0"),   # 已完成的回调数
    Column("status", String(20), server_default="PENDING"),
    # PENDING → DISPATCHING → DISPATCH_FAILED → COMPLETED
    
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

# ============================================================================
# 3. geo_results - 结果层 (REFACTORED)
# ============================================================================
geo_results = Table(
    "geo_results",
    metadata,
    Column("result_id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", UUID(as_uuid=True), ForeignKey("geo_tasks.task_id"), nullable=False),
    Column("cloro_task_id", String(100)),
    Column("call_index", Integer, nullable=False),  # 第几次调用 (1~M)
    
    # Cloro Response
    Column("cloro_response", JSONB, nullable=False),
    Column("http_status_code", Integer),
    Column("latency_ms", Integer),
    Column("ingested_at", DateTime(timezone=True), server_default=func.now()),

    # Unpacked Fields (Flat Columns)
    Column("text", Text),
    Column("html", Text),
    Column("markdown", Text),
    Column("sources", JSONB),
    Column("shopping_cards", JSONB),
    Column("places", JSONB),
    Column("entities", JSONB),
    Column("search_queries", JSONB),
    Column("citation_pills", JSONB),
    
    # Task Metadata (从 geo_tasks 冗余过来，便于查询)
    Column("platform", String(50)),
    Column("batch_id", String(50)),
    Column("client_name", String(100)),
    Column("peers", String(500)),
    Column("topic", String(100)),
    Column("product", String(100)),
    Column("country", String(10)),
    Column("intent", String(50)),
    Column("prompt_text", Text),
    Column("target_user", JSONB),
)

# 业务唯一约束 (幂等性): 每个 task + call_index 只有一条结果
Index("uq_task_call", geo_results.c.task_id, geo_results.c.call_index, unique=True)