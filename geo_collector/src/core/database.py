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
    Boolean,
    func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from src.core.config import get_settings

settings = get_settings()

# Database connection
database = Database(
    settings.DATABASE_URL, 
    min_size=1, 
    max_size=5
)
metadata = MetaData()

# ============================================================================
# 1. geo_clients - 客户主表
# ============================================================================
geo_clients = Table(
    "geo_clients",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4()),
    Column("name", Text, nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

# ============================================================================
# 2. geo_client_peers - 客户竞对关系表
# ============================================================================
geo_client_peers = Table(
    "geo_client_peers",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4()),
    Column("client_id", UUID(as_uuid=True), ForeignKey("geo_clients.id", ondelete="CASCADE"), nullable=False),
    Column("peer_name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

# ============================================================================
# 3. geo_client_domains - 客户域名表
# ============================================================================
geo_client_domains = Table(
    "geo_client_domains",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4()),
    Column("client_id", UUID(as_uuid=True), ForeignKey("geo_clients.id", ondelete="CASCADE"), nullable=False),
    Column("domain", Text, nullable=False),
    Column("is_primary", Boolean, server_default="false"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

# ============================================================================
# 4. geo_reports - 分析报告表
# ============================================================================
geo_reports = Table(
    "geo_reports",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4()),
    Column("name", Text, nullable=False),
    
    # Client 完整信息 (冗余快照)
    Column("client_id", UUID(as_uuid=True), ForeignKey("geo_clients.id")),
    Column("client_name", Text, nullable=False),
    Column("peers", ARRAY(Text), server_default="{}"),
    Column("owned_domains", ARRAY(Text), server_default="{}"),
    
    Column("status", Text, server_default="draft"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

# ============================================================================
# 5. geo_requests - 请求表 (宽表)
# ============================================================================
geo_requests = Table(
    "geo_requests",
    metadata,
    Column("request_id", UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4()),
    
    # Report 关联 (可选)
    Column("report_id", UUID(as_uuid=True), ForeignKey("geo_reports.id")),
    Column("report_name", Text),
    
    # Client 完整信息 (冗余)
    Column("client_id", UUID(as_uuid=True), ForeignKey("geo_clients.id")),
    Column("client_name", Text, nullable=False),
    Column("peers", ARRAY(Text), server_default="{}"),
    Column("owned_domains", ARRAY(Text), server_default="{}"),
    
    # 请求参数
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text, nullable=False, server_default="US"),
    Column("platform", Text, nullable=False),
    Column("intent", Text),
    Column("target_user", JSONB),
    
    # 扩展参数
    Column("prompts_per_request", Integer, server_default="20"),
    Column("calls_per_prompt", Integer, server_default="100"),
    
    # 状态管理
    Column("status", Text, server_default="PENDING"),
    
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

# ============================================================================
# 6. geo_tasks - 任务表 (宽表)
# ============================================================================
geo_tasks = Table(
    "geo_tasks",
    metadata,
    Column("task_id", UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4()),
    Column("request_id", UUID(as_uuid=True), ForeignKey("geo_requests.request_id"), nullable=False),
    
    # Report 关联 (冗余)
    Column("report_id", UUID(as_uuid=True)),
    Column("report_name", Text),
    
    # Client 完整信息 (冗余)
    Column("client_id", UUID(as_uuid=True)),
    Column("client_name", Text, nullable=False),
    Column("peers", ARRAY(Text), server_default="{}"),
    Column("owned_domains", ARRAY(Text), server_default="{}"),
    
    # 请求参数 (冗余)
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text, nullable=False),
    Column("platform", Text, nullable=False),
    Column("intent", Text),
    Column("target_user", JSONB),
    Column("calls_per_prompt", Integer),
    
    # Gemini 生成的内容
    Column("prompt_text", Text, nullable=False),
    Column("prompt_index", Integer),
    
    # 调度状态
    Column("dispatched_count", Integer, server_default="0"),
    Column("completed_count", Integer, server_default="0"),
    Column("status", Text, server_default="PENDING"),
    
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

# ============================================================================
# 7. geo_results - 结果表 (超宽表，Analyzer 主输入)
# ============================================================================
geo_results = Table(
    "geo_results",
    metadata,
    Column("result_id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", UUID(as_uuid=True), ForeignKey("geo_tasks.task_id"), nullable=False),
    Column("request_id", UUID(as_uuid=True), nullable=False),
    
    # Cloro 响应
    Column("cloro_task_id", Text),
    Column("call_index", Integer, nullable=False),
    Column("cloro_response", JSONB, nullable=False),
    Column("http_status_code", Integer),
    Column("latency_ms", Integer),
    
    # Unpacked Fields
    Column("text", Text),
    Column("html", Text),
    Column("markdown", Text),
    Column("sources", JSONB),
    Column("shopping_cards", JSONB),
    Column("places", JSONB),
    Column("entities", JSONB),
    Column("search_queries", JSONB),
    Column("citation_pills", JSONB),
    
    # Report 关联 (冗余)
    Column("report_id", UUID(as_uuid=True)),
    Column("report_name", Text),
    
    # Client 完整信息 (冗余)
    Column("client_id", UUID(as_uuid=True)),
    Column("client_name", Text),
    Column("peers", ARRAY(Text), server_default="{}"),
    Column("owned_domains", ARRAY(Text), server_default="{}"),
    
    # 请求参数 (冗余)
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text),
    Column("platform", Text),
    Column("intent", Text),
    Column("prompt_text", Text),
    Column("target_user", JSONB),
    
    Column("ingested_at", DateTime(timezone=True), server_default=func.now()),
)

# 业务唯一约束 (幂等性)
Index("uq_task_call", geo_results.c.task_id, geo_results.c.call_index, unique=True)