"""Add task metadata columns to geo_results

Revision ID: add_task_metadata_columns
Revises: bb915c6eb8a9
Create Date: 2026-02-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'add_task_metadata_columns'
down_revision = 'bb915c6eb8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('geo_results', sa.Column('platform', sa.String(50), nullable=True))
    op.add_column('geo_results', sa.Column('cloro_task_id', sa.String(100), nullable=True))
    op.add_column('geo_results', sa.Column('batch_id', sa.String(50), nullable=True))
    op.add_column('geo_results', sa.Column('client_name', sa.String(100), nullable=True))
    op.add_column('geo_results', sa.Column('topic', sa.String(100), nullable=True))
    op.add_column('geo_results', sa.Column('product', sa.String(100), nullable=True))
    op.add_column('geo_results', sa.Column('country', sa.String(10), nullable=True))
    op.add_column('geo_results', sa.Column('intent', sa.String(50), nullable=True))
    op.add_column('geo_results', sa.Column('prompt_text', sa.Text(), nullable=True))
    op.add_column('geo_results', sa.Column('target_user', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('geo_results', 'target_user')
    op.drop_column('geo_results', 'prompt_text')
    op.drop_column('geo_results', 'intent')
    op.drop_column('geo_results', 'country')
    op.drop_column('geo_results', 'product')
    op.drop_column('geo_results', 'topic')
    op.drop_column('geo_results', 'client_name')
    op.drop_column('geo_results', 'batch_id')
    op.drop_column('geo_results', 'cloro_task_id')
    op.drop_column('geo_results', 'platform')
