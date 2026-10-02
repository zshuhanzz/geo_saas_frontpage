"""Selected-Workspace configuration context.

The router is mounted behind ``require_feature_access_if_present``. Every SQL
statement is also tenant-filtered for defense in depth: a caller cannot obtain
another Workspace's metadata even if a future handler is reused incorrectly.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from pool import get_pool

router = APIRouter()


class WorkspaceTopicOut(BaseModel):
    id: Any
    client_id: Any
    topic_name: str | None = None
    topic_type: str | None = None
    products: list[str] = Field(default_factory=list)
    created_at: Any = None


class WorkspaceContextOut(BaseModel):
    id: str
    name: str
    client_prompt_quota: int | None = None
    config_platforms: list[str] = Field(default_factory=list)
    config_countries: list[str] = Field(default_factory=list)
    config_languages: list[str] = Field(default_factory=list)
    topics: list[WorkspaceTopicOut] = Field(default_factory=list)


@router.get("/workspaces/{client_id}/context", response_model=WorkspaceContextOut)
async def get_workspace_context(
    client_id: UUID,
    pool=Depends(get_pool),
) -> WorkspaceContextOut:
    """Load configuration data only for the already-authorized Workspace."""
    workspace_id = str(client_id)
    workspace = await pool.fetchrow(
        """
        SELECT id, name, client_prompt_quota,
               config_platforms, config_countries, config_languages
        FROM geo_clients
        WHERE id = $1::uuid
        """,
        workspace_id,
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    topic_rows = await pool.fetch(
        """
        SELECT id, client_id, topic_name, topic_type, created_at
        FROM geo_client_topics
        WHERE client_id = $1::uuid
        ORDER BY created_at
        """,
        workspace_id,
    )
    product_rows = await pool.fetch(
        """
        SELECT topic_id, product_name
        FROM geo_client_topic_products
        WHERE client_id = $1::uuid
          AND product_role = 'own'
          AND is_active = true
        ORDER BY created_at
        """,
        workspace_id,
    )

    products_by_topic: dict[str, list[str]] = {}
    for row in product_rows:
        products_by_topic.setdefault(str(row["topic_id"]), []).append(
            str(row["product_name"])
        )

    topics = []
    for row in topic_rows:
        topic = dict(row)
        topic["products"] = products_by_topic.get(str(row["id"]), [])
        topics.append(WorkspaceTopicOut(**topic))

    return WorkspaceContextOut(
        id=workspace_id,
        name=str(workspace["name"]),
        client_prompt_quota=workspace["client_prompt_quota"],
        config_platforms=list(workspace["config_platforms"] or []),
        config_countries=list(workspace["config_countries"] or []),
        config_languages=list(workspace["config_languages"] or []),
        topics=topics,
    )
