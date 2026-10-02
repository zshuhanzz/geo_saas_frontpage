"""Three-tier data model: drop and recreate tables

Revision ID: three_tier_model
Revises: add_task_metadata_columns
Create Date: 2026-02-07

This migration:
1. Drops existing geo_results and geo_tasks tables
2. Creates new geo_requests table
3. Recreates geo_tasks with new schema (references geo_requests)
4. Recreates geo_results with new schema (call_index, unique constraint)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'three_tier_model'
down_revision = 'add_task_metadata_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop existing tables (CASCADE to handle foreign keys)
    op.execute("DROP TABLE IF EXISTS geo_results CASCADE")
    op.execute("DROP TABLE IF EXISTS geo_tasks CASCADE")
    
    # 2. Create geo_requests (业务输入层)
    op.create_table(
        'geo_requests',
        sa.Column('request_id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('batch_id', sa.String(50)),
        sa.Column('client_name', sa.String(100), nullable=False),
        sa.Column('peers', sa.String(500)),
        sa.Column('topic', sa.String(100)),
        sa.Column('product', sa.String(100)),
        sa.Column('country', sa.String(10), nullable=False),
        sa.Column('platform', sa.String(50), nullable=False),
        sa.Column('intent', sa.String(50)),
        sa.Column('target_user', postgresql.JSONB()),
        sa.Column('prompts_per_request', sa.Integer(), server_default='20'),
        sa.Column('calls_per_prompt', sa.Integer(), server_default='100'),
        sa.Column('status', sa.String(20), server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    
    # 3. Create geo_tasks (调用实例层)
    op.create_table(
        'geo_tasks',
        sa.Column('task_id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('request_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('geo_requests.request_id'), nullable=False),
        sa.Column('batch_id', sa.String(50)),
        sa.Column('client_name', sa.String(100), nullable=False),
        sa.Column('peers', sa.String(500)),
        sa.Column('topic', sa.String(100)),
        sa.Column('product', sa.String(100)),
        sa.Column('country', sa.String(10), nullable=False),
        sa.Column('platform', sa.String(50), nullable=False),
        sa.Column('intent', sa.String(50)),
        sa.Column('target_user', postgresql.JSONB()),
        sa.Column('calls_per_prompt', sa.Integer()),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('prompt_index', sa.Integer()),
        sa.Column('dispatched_count', sa.Integer(), server_default='0'),
        sa.Column('completed_count', sa.Integer(), server_default='0'),
        sa.Column('status', sa.String(20), server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    
    # 4. Create geo_results (结果层)
    op.create_table(
        'geo_results',
        sa.Column('result_id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('geo_tasks.task_id'), nullable=False),
        sa.Column('cloro_task_id', sa.String(100)),
        sa.Column('call_index', sa.Integer(), nullable=False),
        sa.Column('cloro_response', postgresql.JSONB(), nullable=False),
        sa.Column('http_status_code', sa.Integer()),
        sa.Column('latency_ms', sa.Integer()),
        sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('text', sa.Text()),
        sa.Column('html', sa.Text()),
        sa.Column('markdown', sa.Text()),
        sa.Column('sources', postgresql.JSONB()),
        sa.Column('shopping_cards', postgresql.JSONB()),
        sa.Column('places', postgresql.JSONB()),
        sa.Column('entities', postgresql.JSONB()),
        sa.Column('search_queries', postgresql.JSONB()),
        sa.Column('citation_pills', postgresql.JSONB()),
        sa.Column('platform', sa.String(50)),
        sa.Column('batch_id', sa.String(50)),
        sa.Column('client_name', sa.String(100)),
        sa.Column('peers', sa.String(500)),
        sa.Column('topic', sa.String(100)),
        sa.Column('product', sa.String(100)),
        sa.Column('country', sa.String(10)),
        sa.Column('intent', sa.String(50)),
        sa.Column('prompt_text', sa.Text()),
        sa.Column('target_user', postgresql.JSONB()),
    )
    
    # 5. Create unique constraint for idempotency
    op.create_index('uq_task_call', 'geo_results', ['task_id', 'call_index'], unique=True)


def downgrade() -> None:
    # Drop new tables
    op.execute("DROP TABLE IF EXISTS geo_results CASCADE")
    op.execute("DROP TABLE IF EXISTS geo_tasks CASCADE")
    op.execute("DROP TABLE IF EXISTS geo_requests CASCADE")
    
    # Note: This downgrade does NOT restore the old schema.
    # A full rollback would require running the previous migrations again.
