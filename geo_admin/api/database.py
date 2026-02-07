"""
Database connection and table definitions.

Reuses the same schema as geo_collector but with a read-focused connection.
"""
import os
from databases import Database
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, MetaData, Table,
    ForeignKey, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

# Database URL from environment
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://answer-x-geo-db-user:answer-x-geo-db-user-123@localhost:5432/answer-x-geo-db"
)

database = Database(DATABASE_URL, min_size=1, max_size=5)
metadata = MetaData()

# --- Table Definitions (mirror geo_collector schema) ---

geo_requests = Table(
    "geo_requests",
    metadata,
    Column("request_id", UUID, primary_key=True),
    Column("batch_id", String(100)),
    Column("client_name", String(255), nullable=False),
    Column("peers", Text),
    Column("topic", String(255)),
    Column("product", String(255)),
    Column("country", String(10), default="US"),
    Column("platform", String(50), default="chatgpt"),
    Column("intent", String(100)),
    Column("target_user", JSONB),
    Column("prompts_per_request", Integer, default=20),
    Column("calls_per_prompt", Integer, default=3),
    Column("status", String(50), default="PENDING"),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now(), onupdate=func.now()),
)

geo_tasks = Table(
    "geo_tasks",
    metadata,
    Column("task_id", UUID, primary_key=True),
    Column("request_id", UUID, ForeignKey("geo_requests.request_id")),
    Column("batch_id", String(100)),
    Column("client_name", String(255)),
    Column("peers", Text),
    Column("topic", String(255)),
    Column("product", String(255)),
    Column("country", String(10)),
    Column("platform", String(50)),
    Column("intent", String(100)),
    Column("target_user", JSONB),
    Column("prompt_text", Text, nullable=False),
    Column("prompt_index", Integer),
    Column("calls_per_prompt", Integer, default=3),
    Column("dispatched_count", Integer, default=0),
    Column("completed_count", Integer, default=0),
    Column("status", String(50), default="PENDING"),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now(), onupdate=func.now()),
)

geo_results = Table(
    "geo_results",
    metadata,
    Column("result_id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", UUID, ForeignKey("geo_tasks.task_id")),
    Column("cloro_task_id", String(100)),
    Column("call_index", Integer, default=1),
    Column("platform", String(50)),
    Column("batch_id", String(100)),
    Column("client_name", String(255)),
    Column("peers", Text),
    Column("topic", String(255)),
    Column("product", String(255)),
    Column("country", String(10)),
    Column("intent", String(100)),
    Column("prompt_text", Text),
    Column("target_user", JSONB),
    Column("cloro_response", JSONB),
    Column("http_status_code", Integer),
    Column("latency_ms", Integer),
    Column("text", Text),
    Column("html", Text),
    Column("markdown", Text),
    Column("sources", JSONB),
    Column("shopping_cards", JSONB),
    Column("places", JSONB),
    Column("entities", JSONB),
    Column("search_queries", JSONB),
    Column("citation_pills", JSONB),
    Column("ingested_at", DateTime, server_default=func.now()),
)
