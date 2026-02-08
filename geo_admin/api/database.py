"""
Database connection and table definitions for geo_admin API.

Mirrors the geo_collector schema for read/write operations.
"""
import os
from databases import Database
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, MetaData, Table,
    ForeignKey, Boolean, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

# Database URL from environment
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://answer-x-geo-db-user:answer-x-geo-db-user-123@localhost:5432/answer-x-geo-db"
)

database = Database(DATABASE_URL, min_size=1, max_size=5)
metadata = MetaData()

# ============================================================================
# 1. geo_clients - 客户主表
# ============================================================================
geo_clients = Table(
    "geo_clients",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
)

# ============================================================================
# 2. geo_client_peers - 客户竞对关系表
# ============================================================================
geo_client_peers = Table(
    "geo_client_peers",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("client_id", UUID, ForeignKey("geo_clients.id"), nullable=False),
    Column("peer_name", Text, nullable=False),
    Column("created_at", DateTime, server_default=func.now()),
)

# ============================================================================
# 3. geo_client_domains - 客户域名表
# ============================================================================
geo_client_domains = Table(
    "geo_client_domains",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("client_id", UUID, ForeignKey("geo_clients.id"), nullable=False),
    Column("domain", Text, nullable=False),
    Column("is_primary", Boolean, server_default="false"),
    Column("created_at", DateTime, server_default=func.now()),
)

# ============================================================================
# 4. geo_reports - 分析报告表
# ============================================================================
geo_reports = Table(
    "geo_reports",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("name", Text, nullable=False),
    Column("client_id", UUID, ForeignKey("geo_clients.id")),
    Column("client_name", Text, nullable=False),
    Column("peers", ARRAY(Text)),
    Column("owned_domains", ARRAY(Text)),
    Column("status", Text, server_default="draft"),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
)

# ============================================================================
# 5. geo_requests - 请求表 (宽表)
# ============================================================================
geo_requests = Table(
    "geo_requests",
    metadata,
    Column("request_id", UUID, primary_key=True),
    
    # Report 关联
    Column("report_id", UUID, ForeignKey("geo_reports.id")),
    Column("report_name", Text),
    
    # Client 信息
    Column("client_id", UUID, ForeignKey("geo_clients.id")),
    Column("client_name", Text, nullable=False),
    Column("peers", ARRAY(Text)),
    Column("owned_domains", ARRAY(Text)),
    
    # 请求参数
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text, server_default="US"),
    Column("platform", Text, nullable=False),
    Column("intent", Text),
    Column("target_user", JSONB),
    
    Column("prompts_per_request", Integer, server_default="20"),
    Column("calls_per_prompt", Integer, server_default="100"),
    
    Column("status", Text, server_default="PENDING"),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
)

# ============================================================================
# 6. geo_tasks - 任务表 (宽表)
# ============================================================================
geo_tasks = Table(
    "geo_tasks",
    metadata,
    Column("task_id", UUID, primary_key=True),
    Column("request_id", UUID, ForeignKey("geo_requests.request_id")),
    
    # Report 关联
    Column("report_id", UUID),
    Column("report_name", Text),
    
    # Client 信息
    Column("client_id", UUID),
    Column("client_name", Text),
    Column("peers", ARRAY(Text)),
    Column("owned_domains", ARRAY(Text)),
    
    # 请求参数
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text),
    Column("platform", Text),
    Column("intent", Text),
    Column("target_user", JSONB),
    Column("calls_per_prompt", Integer),
    
    Column("prompt_text", Text, nullable=False),
    Column("prompt_index", Integer),
    
    Column("dispatched_count", Integer, server_default="0"),
    Column("completed_count", Integer, server_default="0"),
    Column("status", Text, server_default="PENDING"),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
)

# ============================================================================
# 7. geo_results - 结果表 (超宽表)
# ============================================================================
geo_results = Table(
    "geo_results",
    metadata,
    Column("result_id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", UUID, ForeignKey("geo_tasks.task_id")),
    Column("request_id", UUID),
    
    Column("cloro_task_id", Text),
    Column("call_index", Integer),
    Column("cloro_response", JSONB),
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
    
    # Report 关联
    Column("report_id", UUID),
    Column("report_name", Text),
    
    # Client 信息
    Column("client_id", UUID),
    Column("client_name", Text),
    Column("peers", ARRAY(Text)),
    Column("owned_domains", ARRAY(Text)),
    
    # 请求参数
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text),
    Column("platform", Text),
    Column("intent", Text),
    Column("prompt_text", Text),
    Column("target_user", JSONB),
    
    Column("ingested_at", DateTime, server_default=func.now()),
    Column("analyzed_at", DateTime),
)

# ============================================================================
# 8. geo_company_mentions - 公司提及表 (Analyzer output)
# ============================================================================
geo_company_mentions = Table(
    "geo_company_mentions",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("report_id", UUID),
    Column("request_id", UUID),
    Column("task_id", UUID),
    Column("result_id", Integer),
    Column("client_id", UUID),
    Column("company_name", Text),
    Column("mention_position", Integer),
    Column("is_client", Boolean),
    Column("is_peer", Boolean),
    Column("client_name", Text),
    Column("platform", Text),
    Column("intent", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text),
    Column("executed_at", DateTime),
    Column("created_at", DateTime, server_default=func.now()),
)

# ============================================================================
# 9. geo_citations - 引用来源表 (Analyzer output)
# ============================================================================
geo_citations = Table(
    "geo_citations",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("report_id", UUID),
    Column("request_id", UUID),
    Column("task_id", UUID),
    Column("result_id", Integer),
    Column("client_id", UUID),
    Column("source_url", Text),
    Column("source_domain", Text),
    Column("source_position", Integer),
    Column("source_label", Text),
    Column("domain_category", Text),
    Column("is_citation_pill", Boolean),
    Column("client_name", Text),
    Column("platform", Text),
    Column("intent", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text),
    Column("executed_at", DateTime),
    Column("created_at", DateTime, server_default=func.now()),
)

