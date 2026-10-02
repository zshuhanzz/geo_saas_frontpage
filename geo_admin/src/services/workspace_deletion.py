"""Workspace final-deletion cascade inventory and bounded residual cleanup.

``WORKSPACE_DELETE_MAX_CASCADE_ROWS`` controls the combined number of
low-volume configuration, report, agent-metadata, and child rows that one
final Workspace delete may remove. Prompt-owned facts are intentionally not
listed here: readiness requires those tables to be empty before final delete.

The inventory is a server-owned allowlist derived from the repository's
migrations. Runtime catalog discovery prevents optional tables from being
referenced. Every count and cleanup query remains explicitly tenant scoped.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Collection

logger = logging.getLogger(__name__)

CASCADE_FOOTPRINT_LIMIT_ENV = "WORKSPACE_DELETE_MAX_CASCADE_ROWS"
DEFAULT_CASCADE_FOOTPRINT_LIMIT = 5_000
MIN_CASCADE_FOOTPRINT_LIMIT = 100
MAX_CASCADE_FOOTPRINT_LIMIT = 100_000


def get_cascade_footprint_limit() -> int:
    """Read and clamp the configured combined final-delete row budget."""
    raw = os.environ.get(CASCADE_FOOTPRINT_LIMIT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_CASCADE_FOOTPRINT_LIMIT
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; using default %s",
            CASCADE_FOOTPRINT_LIMIT_ENV,
            raw,
            DEFAULT_CASCADE_FOOTPRINT_LIMIT,
        )
        return DEFAULT_CASCADE_FOOTPRINT_LIMIT
    return min(MAX_CASCADE_FOOTPRINT_LIMIT, max(MIN_CASCADE_FOOTPRINT_LIMIT, value))


def _direct_count(table: str) -> str:
    return f"SELECT COUNT(*) FROM {table} WHERE client_id = $1::uuid"


# Direct Workspace children and high-fanout children reached through those
# parents. geo_client_topics, geo_client_prompts, and all Prompt fact tables
# are excluded because they are independent zero-required readiness blockers.
WORKSPACE_CASCADE_COUNT_QUERIES: dict[str, str] = {
    "geo_client_brands": _direct_count("geo_client_brands"),
    "geo_client_peers": _direct_count("geo_client_peers"),
    "geo_client_domains": _direct_count("geo_client_domains"),
    "geo_client_personas": _direct_count("geo_client_personas"),
    "geo_client_topic_products": _direct_count("geo_client_topic_products"),
    "geo_product_sales_channels": _direct_count("geo_product_sales_channels"),
    "geo_product_tracked_urls": _direct_count("geo_product_tracked_urls"),
    "geo_settings_candidates": _direct_count("geo_settings_candidates"),
    "agent_sessions": _direct_count("agent_sessions"),
    "agent_messages": (
        "SELECT COUNT(*) FROM agent_messages child "
        "JOIN agent_sessions parent ON parent.thread_id = child.thread_id "
        "WHERE parent.client_id = $1::uuid"
    ),
    "geo_brand_profiles": _direct_count("geo_brand_profiles"),
    "agent_memories": _direct_count("agent_memories"),
    "agent_token_usage": _direct_count("agent_token_usage"),
    "agent_user_profiles": _direct_count("agent_user_profiles"),
    "geo_agent_tasks": _direct_count("geo_agent_tasks"),
    "geo_content_assets": _direct_count("geo_content_assets"),
    "geo_client_user_access": _direct_count("geo_client_user_access"),
    # ON DELETE SET NULL still touches every matching row and therefore belongs
    # in the bounded physical footprint even though the audit rows survive.
    "geo_user_audit_events": _direct_count("geo_user_audit_events"),
    "geo_static_reports": _direct_count("geo_static_reports"),
    "geo_static_report_list_rows": _direct_count("geo_static_report_list_rows"),
    "geo_published_urls": _direct_count("geo_published_urls"),
    "geo_published_url_topics": _direct_count("geo_published_url_topics"),
    "geo_prompt_import_batches": _direct_count("geo_prompt_import_batches"),
    "geo_report_templates": _direct_count("geo_report_templates"),
    "checkpoints": (
        "SELECT COUNT(*) FROM checkpoints child "
        "JOIN agent_sessions parent ON parent.thread_id = child.thread_id "
        "WHERE parent.client_id = $1::uuid"
    ),
    "checkpoint_blobs": (
        "SELECT COUNT(*) FROM checkpoint_blobs child "
        "JOIN agent_sessions parent ON parent.thread_id = child.thread_id "
        "WHERE parent.client_id = $1::uuid"
    ),
    "checkpoint_writes": (
        "SELECT COUNT(*) FROM checkpoint_writes child "
        "JOIN agent_sessions parent ON parent.thread_id = child.thread_id "
        "WHERE parent.client_id = $1::uuid"
    ),
}

_COUNT_DEPENDENCIES: dict[str, frozenset[str]] = {
    "agent_messages": frozenset({"agent_sessions"}),
    "checkpoints": frozenset({"agent_sessions"}),
    "checkpoint_blobs": frozenset({"agent_sessions"}),
    "checkpoint_writes": frozenset({"agent_sessions"}),
}


@dataclass(frozen=True)
class WorkspaceCascadeFootprint:
    by_table: dict[str, int]
    total_rows: int
    present_tables: frozenset[str]


WORKSPACE_ACTIVE_COUNT_QUERIES: dict[str, str] = {
    "geo_agent_tasks": (
        "SELECT COUNT(*) FROM geo_agent_tasks "
        "WHERE client_id = $1::uuid AND status = 'RUNNING'"
    ),
    "geo_static_reports": (
        "SELECT COUNT(*) FROM geo_static_reports "
        "WHERE client_id = $1::uuid AND status = 'MATERIALIZING'"
    ),
    "geo_prompt_import_batches": (
        "SELECT COUNT(*) FROM geo_prompt_import_batches "
        "WHERE client_id = $1::uuid AND status = 'REVERTING'"
    ),
}


@dataclass(frozen=True)
class WorkspaceActiveWork:
    by_table: dict[str, int]
    total_items: int


async def load_workspace_cascade_footprint(
    conn,
    client_id: str,
) -> WorkspaceCascadeFootprint:
    """Return exact row counts for existing allowlisted Workspace tables."""
    table_names = sorted(WORKSPACE_CASCADE_COUNT_QUERIES)
    rows = await conn.fetch(
        "SELECT tablename FROM pg_catalog.pg_tables "
        "WHERE schemaname = current_schema() AND tablename = ANY($1::text[])",
        table_names,
    )
    present = frozenset(str(row["tablename"]) for row in rows)
    counts: dict[str, int] = {}
    for table_name, sql in WORKSPACE_CASCADE_COUNT_QUERIES.items():
        if table_name not in present:
            continue
        if not _COUNT_DEPENDENCIES.get(table_name, frozenset()).issubset(present):
            continue
        counts[table_name] = int(await conn.fetchval(sql, str(client_id)) or 0)
    return WorkspaceCascadeFootprint(
        by_table=counts,
        total_rows=sum(counts.values()),
        present_tables=present,
    )


async def load_workspace_active_work(conn, client_id: str) -> WorkspaceActiveWork:
    """Return persisted in-progress jobs that make final deletion unsafe."""
    table_names = sorted(WORKSPACE_ACTIVE_COUNT_QUERIES)
    rows = await conn.fetch(
        "SELECT tablename FROM pg_catalog.pg_tables "
        "WHERE schemaname = current_schema() AND tablename = ANY($1::text[])",
        table_names,
    )
    present = frozenset(str(row["tablename"]) for row in rows)
    counts: dict[str, int] = {}
    for table_name, sql in WORKSPACE_ACTIVE_COUNT_QUERIES.items():
        if table_name in present:
            counts[table_name] = int(await conn.fetchval(sql, str(client_id)) or 0)
    return WorkspaceActiveWork(by_table=counts, total_items=sum(counts.values()))


NON_CASCADING_DELETE_ORDER = (
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
    "geo_agent_tasks",
    "geo_report_templates",
    "geo_settings_candidates",
)

NON_CASCADING_DELETE_QUERIES: dict[str, str] = {
    "checkpoint_writes": (
        "DELETE FROM checkpoint_writes child USING agent_sessions parent "
        "WHERE child.thread_id = parent.thread_id AND parent.client_id = $1::uuid"
    ),
    "checkpoint_blobs": (
        "DELETE FROM checkpoint_blobs child USING agent_sessions parent "
        "WHERE child.thread_id = parent.thread_id AND parent.client_id = $1::uuid"
    ),
    "checkpoints": (
        "DELETE FROM checkpoints child USING agent_sessions parent "
        "WHERE child.thread_id = parent.thread_id AND parent.client_id = $1::uuid"
    ),
    "geo_agent_tasks": (
        "DELETE FROM geo_agent_tasks WHERE client_id = $1::uuid"
    ),
    "geo_report_templates": (
        "DELETE FROM geo_report_templates WHERE client_id = $1::uuid"
    ),
    "geo_settings_candidates": (
        "DELETE FROM geo_settings_candidates WHERE client_id = $1::uuid"
    ),
}


async def delete_non_cascading_workspace_residuals(
    conn,
    client_id: str,
    present_tables: Collection[str],
) -> None:
    """Delete catalog-confirmed tenant rows that lack a geo_clients FK."""
    present = frozenset(present_tables)
    for table_name in NON_CASCADING_DELETE_ORDER:
        if table_name not in present:
            continue
        if not _COUNT_DEPENDENCIES.get(table_name, frozenset()).issubset(present):
            continue
        await conn.execute(
            NON_CASCADING_DELETE_QUERIES[table_name],
            str(client_id),
        )
