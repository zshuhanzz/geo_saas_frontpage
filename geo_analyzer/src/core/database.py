"""
GEO Analyzer - Database Connection and Table Definitions
Synced with actual Cloud SQL database schema.
"""
from contextlib import contextmanager
from sqlalchemy import (
    create_engine, MetaData, Table, Column, 
    String, Integer, Boolean, DateTime, Text,
    ForeignKey, func
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from src.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
metadata = MetaData()


# ============================================================================
# Source Tables (READ) - From geo_collector
# ============================================================================

geo_clients = Table(
    "geo_clients",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", Text, nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

geo_reports = Table(
    "geo_reports",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", Text, nullable=False),
    Column("client_id", UUID(as_uuid=True)),
    Column("client_name", Text, nullable=False),
    Column("peers", ARRAY(Text)),
    Column("owned_domains", ARRAY(Text)),
    Column("status", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

geo_requests = Table(
    "geo_requests",
    metadata,
    Column("request_id", UUID(as_uuid=True), primary_key=True),
    Column("report_id", UUID(as_uuid=True)),
    Column("report_name", Text),
    Column("client_id", UUID(as_uuid=True)),
    Column("client_name", Text, nullable=False),
    Column("peers", ARRAY(Text)),
    Column("owned_domains", ARRAY(Text)),
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text, nullable=False),
    Column("platform", Text, nullable=False),
    Column("intent", Text),
    Column("target_user", JSONB),
    Column("status", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

geo_tasks = Table(
    "geo_tasks",
    metadata,
    Column("task_id", UUID(as_uuid=True), primary_key=True),
    Column("request_id", UUID(as_uuid=True)),
    Column("report_id", UUID(as_uuid=True)),
    Column("report_name", Text),
    Column("client_id", UUID(as_uuid=True)),
    Column("client_name", Text, nullable=False),
    Column("peers", ARRAY(Text)),
    Column("owned_domains", ARRAY(Text)),
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text, nullable=False),
    Column("platform", Text, nullable=False),
    Column("intent", Text),
    Column("target_user", JSONB),
    Column("prompt_text", Text, nullable=False),
    Column("prompt_index", Integer),
    Column("status", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

# geo_results - Analyzer主输入表
geo_results = Table(
    "geo_results",
    metadata,
    Column("result_id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", UUID(as_uuid=True)),
    Column("request_id", UUID(as_uuid=True)),
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
    # Report/Client info
    Column("report_id", UUID(as_uuid=True)),
    Column("report_name", Text),
    Column("client_id", UUID(as_uuid=True)),
    Column("client_name", Text),
    Column("peers", ARRAY(Text)),
    Column("owned_domains", ARRAY(Text)),
    # Request params
    Column("batch_id", Text),
    Column("topic", Text),
    Column("product", Text),
    Column("country", Text),
    Column("platform", Text),
    Column("intent", Text),
    Column("prompt_text", Text),
    Column("target_user", JSONB),
    Column("ingested_at", DateTime(timezone=True)),
    Column("analyzed_at", DateTime(timezone=True)),
)


# ============================================================================
# Analyzer Output Tables (WRITE) - Actual DB schema
# ============================================================================

geo_company_mentions = Table(
    "geo_company_mentions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("report_id", UUID(as_uuid=True)),
    Column("request_id", UUID(as_uuid=True)),
    Column("task_id", UUID(as_uuid=True)),
    Column("result_id", Integer, nullable=False),
    Column("client_id", UUID(as_uuid=True)),
    Column("company_name", String(255), nullable=False),
    Column("mention_position", Integer),
    Column("is_client", Boolean, server_default="false"),
    Column("is_peer", Boolean, server_default="false"),
    Column("client_name", Text),
    Column("platform", String(50)),
    Column("intent", String(100)),
    Column("topic", Text),
    Column("product", Text),
    Column("country", String(10)),
    Column("executed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

geo_citations = Table(
    "geo_citations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("report_id", UUID(as_uuid=True)),
    Column("request_id", UUID(as_uuid=True)),
    Column("task_id", UUID(as_uuid=True)),
    Column("result_id", Integer, nullable=False),
    Column("client_id", UUID(as_uuid=True)),
    Column("source_url", Text),
    Column("source_domain", String(255)),
    Column("source_position", Integer),
    Column("source_label", Text),
    Column("domain_category", String(50)),
    Column("is_citation_pill", Boolean, server_default="false"),
    Column("client_name", Text),
    Column("platform", String(50)),
    Column("intent", String(100)),
    Column("topic", Text),
    Column("product", Text),
    Column("country", String(10)),
    Column("executed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


# ============================================================================
# Database Connection
# ============================================================================

@contextmanager
def get_db_connection():
    """Context manager for database session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine():
    """Get raw SQLAlchemy engine for direct operations."""
    return engine
