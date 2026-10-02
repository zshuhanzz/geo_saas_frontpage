"""Cascade deletion for Prompt-owned Collector and Analyzer facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from geo_common.db import tenant_scoped

from .base import BaseRepository


# Workspace Cleanup submits these physical-Prompt batches serially. The core
# service remains reusable by atomic import Undo, whose exact batch may be
# larger; the interactive route enforces the hard request limit.
DEFAULT_PROMPT_CASCADE_BATCH_SIZE = 25
MAX_PROMPT_CASCADE_BATCH_SIZE = 100


def _affected(status: str) -> int:
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (AttributeError, ValueError):
        return 0


@dataclass(frozen=True)
class PromptCascadeDeleteResult:
    requested_prompts: int
    matched_prompts: int
    deleted_sentiment_themes: int = 0
    deleted_sentiment_results: int = 0
    deleted_citations: int = 0
    deleted_product_mentions: int = 0
    deleted_brand_mentions: int = 0
    deleted_results: int = 0
    deleted_tasks: int = 0
    deleted_prompts: int = 0


class PromptCascadeDeletionService(BaseRepository):
    """Delete downstream facts before deleting prompt seed rows."""

    @tenant_scoped
    async def delete_one(
        self, client_id: str, prompt_id: str
    ) -> PromptCascadeDeleteResult:
        return await self.delete_many(client_id, [prompt_id])

    @tenant_scoped
    async def delete_many(
        self, client_id: str, prompt_ids: Iterable[str]
    ) -> PromptCascadeDeleteResult:
        requested = [str(pid) for pid in prompt_ids]
        if not requested:
            return PromptCascadeDeleteResult(requested_prompts=0, matched_prompts=0)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                return await self.delete_many_on_connection(client_id, conn, requested)

    @tenant_scoped
    async def delete_many_on_connection(
        self,
        client_id: str,
        conn,
        prompt_ids: Iterable[str],
    ) -> PromptCascadeDeleteResult:
        """Cascade-delete using a transaction and connection owned by caller."""
        requested = [str(pid) for pid in prompt_ids]
        if not requested:
            return PromptCascadeDeleteResult(requested_prompts=0, matched_prompts=0)
        rows = await conn.fetch(
            """
            SELECT id
            FROM geo_client_prompts
            WHERE client_id = $1::uuid
              AND id = ANY($2::uuid[])
            FOR UPDATE
            """,
            client_id,
            requested,
        )
        matched = [str(row["id"]) for row in rows]
        if not matched:
            return PromptCascadeDeleteResult(
                requested_prompts=len(requested),
                matched_prompts=0,
            )

        async def delete_from(table: str) -> int:
            id_column = "id" if table == "geo_client_prompts" else "client_prompt_id"
            return _affected(
                await conn.execute(
                    f"DELETE FROM {table} "
                    f"WHERE client_id = $2::uuid AND {id_column} = ANY($1::uuid[])",
                    matched,
                    client_id,
                )
            )

        deleted_sentiment_themes = await delete_from("geo_sentiment_themes")
        deleted_sentiment_results = await delete_from("geo_sentiment_results")
        deleted_citations = await delete_from("geo_citations")
        deleted_product_mentions = await delete_from("geo_product_mentions")
        deleted_brand_mentions = await delete_from("geo_brand_mentions")
        deleted_results = await delete_from("geo_results")
        deleted_tasks = await delete_from("geo_tasks")
        deleted_prompts = await delete_from("geo_client_prompts")

        return PromptCascadeDeleteResult(
            requested_prompts=len(requested),
            matched_prompts=len(matched),
            deleted_sentiment_themes=deleted_sentiment_themes,
            deleted_sentiment_results=deleted_sentiment_results,
            deleted_citations=deleted_citations,
            deleted_product_mentions=deleted_product_mentions,
            deleted_brand_mentions=deleted_brand_mentions,
            deleted_results=deleted_results,
            deleted_tasks=deleted_tasks,
            deleted_prompts=deleted_prompts,
        )
