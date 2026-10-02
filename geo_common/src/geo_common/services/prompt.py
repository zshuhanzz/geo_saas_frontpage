"""
PromptRepository — DAL for ``geo_client_prompts``.

A Client Prompt is the user-authored seed prompt that the collector expands
into platform/country variants. Schema:

    id UUID PK,
    client_id UUID FK,
    topic_id UUID FK,
    text TEXT,
    intent TEXT NULL,
    product TEXT NULL,
    platform TEXT,
    country TEXT,
    language TEXT,
    is_active BOOLEAN default true,
    created_at TIMESTAMP,
    updated_at TIMESTAMP

Used by both ``geo_saas/src/routers/prompts.py`` (tenant-facing CRUD) and
``geo_admin/src/routers/prompts.py`` (admin-facing list/edit). The two callers
have slightly different read shapes (admin needs a join to ``geo_client_topics``
for ``topic_name``); both are covered here.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

from geo_common.db import tenant_scoped

from .base import BaseRepository
from .prompt_intent import (
    canonicalize_configured_values,
    normalize_case_insensitive,
)
from .prompt_keys import canonical_prompt_logical_key

_PROMPT_COLS = (
    "id, client_id, topic_id, text, intent, product, "
    "platform, country, language, is_active, created_at, updated_at"
)


class PromptRepository(BaseRepository):
    """``geo_client_prompts`` DAL — covers both SaaS and Admin call sites."""

    @staticmethod
    def _concept_filter_sql(
        client_id: str,
        *,
        topic_id: UUID | str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        product: str | None = None,
        platform: str | None = None,
        country: str | None = None,
        language: str | None = None,
    ) -> tuple[list[str], list[Any]]:
        clauses = ["p.client_id = $1"]
        params: list[Any] = [client_id]
        if topic_id is not None:
            clauses.append(f"p.topic_id = ${len(params) + 1}")
            params.append(topic_id)
        if is_active is not None:
            clauses.append(f"p.is_active = ${len(params) + 1}")
            params.append(is_active)
        if search:
            clauses.append(f"p.text ILIKE ${len(params) + 1}")
            params.append(f"%{search}%")
        if product:
            clauses.append(f"COALESCE(p.product, '') = ${len(params) + 1}")
            params.append(product)
        if platform:
            clauses.append(f"p.platform = ${len(params) + 1}")
            params.append(platform)
        if country:
            clauses.append(f"p.country = ${len(params) + 1}")
            params.append(country)
        if language:
            clauses.append(f"UPPER(COALESCE(p.language, '')) = ${len(params) + 1}")
            params.append(language.upper())
        return clauses, params

    @tenant_scoped
    async def list_concepts_for_client(
        self,
        client_id: str,
        *,
        topic_id: UUID | str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        product: str | None = None,
        platform: str | None = None,
        country: str | None = None,
        language: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        with_topic_name: bool = False,
    ) -> list[dict[str, Any]]:
        """List user-authored prompt concepts for a client.

        ``geo_client_prompts`` stores one physical row per country/platform
        variant. Admin pagination should not slice through those variants, so
        this groups physical rows into one logical prompt concept before
        applying ``LIMIT/OFFSET``.
        """
        clauses, params = self._concept_filter_sql(
            client_id,
            topic_id=topic_id,
            is_active=is_active,
            search=search,
            product=product,
            platform=platform,
            country=country,
            language=language,
        )
        topic_select = ", t.topic_name" if with_topic_name else ""
        topic_join = (
            "JOIN geo_client_topics t ON grouped.topic_id = t.id"
            if with_topic_name
            else ""
        )
        sql = (
            "WITH grouped AS ("
            "SELECT "
            "p.client_id, "
            "p.topic_id, "
            "p.text, "
            "COALESCE(p.intent, '') AS intent, "
            "COALESCE(p.product, '') AS product, "
            "COALESCE(p.language, '') AS language, "
            "ARRAY_AGG(p.id ORDER BY p.created_at DESC, p.id) AS prompt_ids, "
            "ARRAY_AGG(p.platform ORDER BY p.created_at DESC, p.id) AS variant_platforms, "
            "ARRAY_AGG(p.country ORDER BY p.created_at DESC, p.id) AS variant_countries, "
            "ARRAY_AGG(DISTINCT p.country) FILTER (WHERE p.country IS NOT NULL AND p.country <> '') AS countries, "
            "ARRAY_AGG(DISTINCT p.platform) FILTER (WHERE p.platform IS NOT NULL AND p.platform <> '') AS platforms, "
            "COUNT(*) AS final_prompt_count, "
            "COUNT(*) FILTER (WHERE p.is_active = true) AS active_final_prompt_count, "
            "COUNT(*) FILTER (WHERE p.is_active = false) AS inactive_final_prompt_count, "
            "MIN(p.created_at) AS created_at, "
            "MAX(p.updated_at) AS updated_at "
            "FROM geo_client_prompts p "
            f"WHERE {' AND '.join(clauses)} "
            "GROUP BY p.client_id, p.topic_id, p.text, COALESCE(p.intent, ''), COALESCE(p.product, ''), COALESCE(p.language, '')"
            ") "
            f"SELECT grouped.*{topic_select} "
            f"FROM grouped {topic_join} "
            "ORDER BY grouped.updated_at DESC NULLS LAST, grouped.created_at DESC NULLS LAST, grouped.text ASC"
        )
        if limit is not None:
            params.append(limit)
            sql += f" LIMIT ${len(params)}"
            if offset:
                params.append(offset)
                sql += f" OFFSET ${len(params)}"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def count_concepts_for_client(
        self,
        client_id: str,
        *,
        topic_id: UUID | str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        product: str | None = None,
        platform: str | None = None,
        country: str | None = None,
        language: str | None = None,
    ) -> int:
        """Count logical prompt concepts for the same filters as
        ``list_concepts_for_client``."""
        clauses, params = self._concept_filter_sql(
            client_id,
            topic_id=topic_id,
            is_active=is_active,
            search=search,
            product=product,
            platform=platform,
            country=country,
            language=language,
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM ("
                "SELECT 1 FROM geo_client_prompts p "
                f"WHERE {' AND '.join(clauses)} "
                "GROUP BY p.client_id, p.topic_id, p.text, COALESCE(p.intent, ''), COALESCE(p.product, ''), COALESCE(p.language, '')"
                ") grouped",
                *params,
            )
        return int(row["n"]) if row else 0

    @tenant_scoped
    async def list_for_client(
        self,
        client_id: str,
        *,
        topic_id: UUID | str | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
        with_topic_name: bool = False,
    ) -> list[dict[str, Any]]:
        """List prompts for a client.

        Args:
            topic_id: optional topic filter.
            is_active: optional active-only filter (True returns only active,
                False returns only inactive, None returns both).
            limit / offset: pagination. Pass ``limit=None`` for unbounded.
            with_topic_name: when True, joins ``geo_client_topics`` and adds a
                ``topic_name`` column to each row (used by the admin list view).
        """
        clauses = ["p.client_id = $1"]
        params: list[Any] = [client_id]
        if topic_id is not None:
            clauses.append(f"p.topic_id = ${len(params) + 1}")
            params.append(topic_id)
        if is_active is not None:
            clauses.append(f"p.is_active = ${len(params) + 1}")
            params.append(is_active)

        select_cols = ", ".join(f"p.{c.strip()}" for c in _PROMPT_COLS.split(","))
        if with_topic_name:
            select_cols += ", t.topic_name"
            join_sql = (
                "FROM geo_client_prompts p "
                "JOIN geo_client_topics t ON p.topic_id = t.id"
            )
        else:
            join_sql = "FROM geo_client_prompts p"

        sql = (
            f"SELECT {select_cols} {join_sql} "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY p.created_at DESC"
        )
        if limit is not None:
            params.append(limit)
            sql += f" LIMIT ${len(params)}"
            if offset:
                params.append(offset)
                sql += f" OFFSET ${len(params)}"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def count_for_client(
        self,
        client_id: str,
        *,
        topic_id: UUID | str | None = None,
        is_active: bool | None = None,
    ) -> int:
        """Total row count for the same filters as ``list_for_client``.

        Used by the admin paginated list view.
        """
        clauses = ["client_id = $1"]
        params: list[Any] = [client_id]
        if topic_id is not None:
            clauses.append(f"topic_id = ${len(params) + 1}")
            params.append(topic_id)
        if is_active is not None:
            clauses.append(f"is_active = ${len(params) + 1}")
            params.append(is_active)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM geo_client_prompts "
                f"WHERE {' AND '.join(clauses)}",
                *params,
            )
        return int(row["n"]) if row else 0

    @tenant_scoped
    async def count_active_for_client(self, client_id: str) -> int:
        """Convenience helper used by quota checks."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM geo_client_prompts "
                "WHERE client_id = $1 AND is_active = true",
                client_id,
            )
        return int(row["n"]) if row else 0

    @tenant_scoped
    async def count_active_unique_for_client(self, client_id: str) -> int:
        """Count active unique prompt concepts by ``text + topic_id``.

        A single user-authored prompt can be expanded into multiple
        platform/country rows. Product quota is based on the unique prompt
        concept, matching the SaaS editor's displayed usage.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM ("
                "SELECT DISTINCT text, topic_id FROM geo_client_prompts "
                "WHERE client_id = $1 AND is_active = true"
                ") unique_prompts",
                client_id,
            )
        return int(row["n"]) if row else 0

    @tenant_scoped
    async def active_prompt_keys_for_client(self, client_id: str) -> set[tuple[str, str]]:
        """Return active unique prompt keys as ``(text, topic_id)`` pairs."""
        async with self._pool.acquire() as conn:
            return await self.active_prompt_keys_on_connection(client_id, conn)

    @tenant_scoped
    async def active_prompt_keys_on_connection(
        self,
        client_id: str,
        conn,
        *,
        exclude_prompt_ids: list[UUID | str] | None = None,
    ) -> set[tuple[str, str]]:
        """Read quota keys on a caller-owned locked transaction."""
        params: list[Any] = [client_id]
        excluded_clause = ""
        if exclude_prompt_ids:
            params.append([UUID(str(value)) for value in exclude_prompt_ids])
            excluded_clause = " AND NOT (id = ANY($2::uuid[]))"
        rows = await conn.fetch(
            "SELECT DISTINCT text, topic_id FROM geo_client_prompts "
            "WHERE client_id = $1 AND is_active = true"
            + excluded_clause,
            *params,
        )
        return {
            canonical_prompt_logical_key(str(r["text"]), r["topic_id"])
            for r in rows
        }

    @tenant_scoped
    async def owned_topic_ids_on_connection(
        self, client_id: str, conn, topic_ids: list[UUID | str]
    ) -> set[str]:
        """Return Topic IDs owned by this tenant.

        ``geo_client_topics`` has no activation flag. Prompt activation is
        stored on ``geo_client_prompts`` and must not leak into this ownership
        check, which is shared by interactive and batch prompt creation.
        """
        if not topic_ids:
            return set()
        rows = await conn.fetch(
            "SELECT id FROM geo_client_topics "
            "WHERE client_id = $1::uuid AND id = ANY($2::uuid[])",
            client_id,
            [UUID(str(value)) for value in topic_ids],
        )
        return {str(row["id"]) for row in rows}

    @tenant_scoped
    async def physical_candidates_on_connection(
        self,
        client_id: str,
        conn,
        *,
        topic_ids: list[UUID | str],
        normalized_texts: list[str],
    ) -> list[dict[str, Any]]:
        """Load possible physical duplicates within the locked transaction."""
        if not topic_ids or not normalized_texts:
            return []
        rows = await conn.fetch(
            f"SELECT {_PROMPT_COLS} FROM geo_client_prompts "
            "WHERE client_id = $1::uuid "
            "AND topic_id = ANY($2::uuid[]) "
            "AND LOWER(REGEXP_REPLACE(TRIM(text), '\\s+', ' ', 'g')) = ANY($3::text[]) "
            "ORDER BY id",
            client_id,
            [UUID(str(value)) for value in topic_ids],
            normalized_texts,
        )
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def get_by_id(
        self, client_id: str, prompt_id: UUID | str
    ) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            return await self.get_by_id_on_connection(client_id, conn, prompt_id)

    @tenant_scoped
    async def get_by_id_on_connection(
        self, client_id: str, conn, prompt_id: UUID | str, *, for_update: bool = False
    ) -> dict[str, Any] | None:
        lock_clause = " FOR UPDATE" if for_update else ""
        row = await conn.fetchrow(
            f"SELECT {_PROMPT_COLS} FROM geo_client_prompts "
            f"WHERE client_id = $1 AND id = $2{lock_clause}",
            client_id, prompt_id,
        )
        return self._row_to_dict(row)

    @tenant_scoped
    async def get_many_on_connection(
        self, client_id: str, conn, prompt_ids: list[UUID | str], *, for_update: bool = False
    ) -> list[dict[str, Any]]:
        if not prompt_ids:
            return []
        lock_clause = " FOR UPDATE" if for_update else ""
        rows = await conn.fetch(
            f"SELECT {_PROMPT_COLS} FROM geo_client_prompts "
            f"WHERE client_id = $1 AND id = ANY($2::uuid[]){lock_clause}",
            client_id, [UUID(str(value)) for value in prompt_ids],
        )
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def resolve_concept_by_prompt_id(
        self,
        client_id: str,
        prompt_id: UUID | str,
    ) -> dict[str, Any] | None:
        """Resolve one physical prompt row to its complete logical concept.

        Platform and country are expansion dimensions and therefore do not
        participate in the logical key. All lookups remain tenant scoped,
        including the second query that discovers sibling variants.
        """
        async with self._pool.acquire() as conn:
            representative_row = await conn.fetchrow(
                f"SELECT {_PROMPT_COLS} FROM geo_client_prompts "
                "WHERE client_id = $1 AND id = $2",
                client_id,
                prompt_id,
            )
            representative = self._row_to_dict(representative_row)
            if not representative:
                return None

            client_row = await conn.fetchrow(
                "SELECT config_languages FROM geo_clients WHERE id = $1",
                client_id,
            )
            configured_languages = (
                list(client_row.get("config_languages") or []) if client_row else []
            )
            active_intent_rows = await conn.fetch(
                "SELECT intent_name FROM geo_global_intents "
                "WHERE is_active = TRUE ORDER BY intent_name"
            )
            canonical_intents = canonicalize_configured_values(
                str(row["intent_name"])
                for row in active_intent_rows
                if row.get("intent_name")
            )
            active_intents = {
                normalize_case_insensitive(value): value for value in canonical_intents
            }

            intent_value = str(representative.get("intent") or "").strip()
            canonical_intent = active_intents.get(normalize_case_insensitive(intent_value))
            normalized_text = re.sub(
                r"\s+", " ", str(representative.get("text") or "").strip()
            ).lower()
            normalized_product = str(representative.get("product") or "").strip().lower()
            language_value = str(representative.get("language") or "").strip()
            canonical_language = next(
                (
                    str(configured).strip()
                    for configured in configured_languages
                    if normalize_case_insensitive(str(configured))
                    == normalize_case_insensitive(language_value)
                ),
                None,
            )
            language_key = canonical_language.lower() if canonical_language else language_value

            params: list[Any] = [
                client_id,
                representative["topic_id"],
                normalized_text,
                normalized_product,
                language_key,
            ]
            if canonical_intent is not None:
                params.append(canonical_intent.lower())
                intent_clause = "LOWER(TRIM(COALESCE(p.intent, ''))) = $6"
            else:
                params.append(intent_value)
                intent_clause = "TRIM(COALESCE(p.intent, '')) = $6"

            language_clause = (
                "LOWER(TRIM(COALESCE(p.language, ''))) = $5"
                if canonical_language is not None
                else "TRIM(COALESCE(p.language, '')) = $5"
            )
            active_clause = (
                "p.is_active = FALSE"
                if representative.get("is_active") is False
                else "p.is_active = TRUE"
            )
            variant_rows = await conn.fetch(
                "SELECT p.id FROM geo_client_prompts p "
                "WHERE p.client_id = $1 "
                "AND p.topic_id = $2 "
                "AND LOWER(REGEXP_REPLACE(TRIM(p.text), '\\s+', ' ', 'g')) = $3 "
                "AND LOWER(TRIM(COALESCE(p.product, ''))) = $4 "
                f"AND {language_clause} "
                f"AND {intent_clause} "
                f"AND {active_clause} "
                "ORDER BY p.created_at ASC NULLS LAST, p.id ASC",
                *params,
            )

        representative["text"] = re.sub(
            r"\s+", " ", str(representative.get("text") or "").strip()
        )
        representative["product"] = str(representative.get("product") or "").strip() or None
        representative["language"] = canonical_language or language_value
        representative["intent"] = canonical_intent if canonical_intent is not None else intent_value
        return {
            "representative": representative,
            "prompt_ids": [str(row["id"]) for row in variant_rows],
        }

    @tenant_scoped
    async def add(
        self,
        client_id: str,
        *,
        topic_id: UUID | str,
        text: str,
        platform: str,
        country: str,
        language: str,
        intent: str | None = None,
        product: str | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """INSERT a single prompt and return the persisted row."""
        async with self._pool.acquire() as conn:
            return await self.add_on_connection(
                client_id,
                conn,
                topic_id=topic_id,
                text=text,
                platform=platform,
                country=country,
                language=language,
                intent=intent,
                product=product,
                is_active=is_active,
            )

    @tenant_scoped
    async def add_on_connection(
        self,
        client_id: str,
        conn,
        *,
        topic_id: UUID | str,
        text: str,
        platform: str,
        country: str,
        language: str,
        intent: str | None = None,
        product: str | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """Insert one Prompt using the caller-owned write transaction."""
        row = await conn.fetchrow(
            "INSERT INTO geo_client_prompts "
            "(id, client_id, topic_id, text, intent, product, "
            " platform, country, language, is_active) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
            f"RETURNING {_PROMPT_COLS}",
            uuid4(),
            client_id,
            topic_id,
            text,
            intent,
            product,
            platform,
            country,
            language,
            is_active,
        )
        return self._row_to_dict(row)

    @tenant_scoped
    async def add_many(
        self,
        client_id: str,
        rows: list[dict[str, Any]],
    ) -> list[str]:
        """Bulk insert. Each row dict must carry topic_id, text, platform,
        country, language; intent/product/is_active are optional. Returns the
        new ids in insert order.

        Used by the SaaS ``/prompts/batch`` endpoint when the brainstorm flow
        saves many prompts at once.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                return await self.add_many_on_connection(client_id, conn, rows)

    @tenant_scoped
    async def add_many_on_connection(
        self,
        client_id: str,
        conn,
        rows: list[dict[str, Any]],
    ) -> list[str]:
        """Bulk insert Prompt rows in a caller-owned write transaction."""
        ids = [str(uuid4()) for _ in rows]
        return await self.bulk_insert_on_connection(
            client_id,
            conn,
            rows,
            prompt_ids=ids,
        )

    @tenant_scoped
    async def reactivate_on_connection(
        self,
        client_id: str,
        conn,
        prompt_ids: list[UUID | str],
    ) -> list[dict[str, Any]]:
        """Reactivate compatible inactive variants inside the write lock."""
        if not prompt_ids:
            return []
        rows = await conn.fetch(
            "UPDATE geo_client_prompts SET is_active = TRUE, updated_at = NOW() "
            "WHERE client_id = $1::uuid AND id = ANY($2::uuid[]) "
            "AND is_active IS DISTINCT FROM TRUE "
            f"RETURNING {_PROMPT_COLS}",
            client_id,
            [UUID(str(value)) for value in prompt_ids],
        )
        return self._rows_to_dicts(rows)

    @tenant_scoped
    async def bulk_insert_on_connection(
        self,
        client_id: str,
        conn: Any,
        rows: list[dict[str, Any]],
        *,
        prompt_ids: list[UUID | str],
    ) -> list[str]:
        """Insert ordered Prompt variants on a caller-owned transaction.

        The caller owns connection acquisition, locking, transaction commit,
        and rollback.  This method intentionally performs one bulk operation
        and then verifies that every caller-generated UUID is present for the
        same tenant before returning.
        """
        if len(rows) != len(prompt_ids):
            raise ValueError("Prompt row and ID counts must match")
        if not rows:
            return []
        ids = [UUID(str(value)) for value in prompt_ids]
        inserted_rows = await conn.fetch(
            """
            /* prompt_bulk_insert */
            WITH input_rows AS MATERIALIZED (
                SELECT *
                FROM UNNEST(
                    $2::uuid[], $3::uuid[], $4::text[], $5::text[],
                    $6::text[], $7::text[], $8::text[], $9::text[],
                    $10::boolean[]
                ) WITH ORDINALITY AS input(
                    id, topic_id, text, intent, product, platform,
                    country, language, is_active, input_order
                )
            )
            INSERT INTO geo_client_prompts (
                id, client_id, topic_id, text, intent, product,
                platform, country, language, is_active
            )
            SELECT
                id, $1::uuid, topic_id, text, intent, product,
                platform, country, language, is_active
            FROM input_rows
            ORDER BY input_order
            RETURNING id::text AS id
            """,
            client_id,
            ids,
            [UUID(str(row["topic_id"])) for row in rows],
            [row["text"] for row in rows],
            [row.get("intent") for row in rows],
            [row.get("product") for row in rows],
            [row["platform"] for row in rows],
            [row["country"] for row in rows],
            [row["language"] for row in rows],
            [row.get("is_active", True) for row in rows],
        )
        returned_ids = {str(row["id"]) for row in inserted_rows}
        expected_ids = {str(value) for value in ids}
        if returned_ids != expected_ids:
            raise RuntimeError(
                f"Prompt bulk insert ID mismatch: expected {len(ids)}, got {len(returned_ids)}"
            )
        return [str(value) for value in ids]

    @tenant_scoped
    async def update(
        self,
        client_id: str,
        prompt_id: UUID | str,
        *,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Whitelisted partial update. Returns the updated row, or None.

        ``updated_at`` is bumped automatically.
        """
        allowed = {
            "text",
            "intent",
            "product",
            "platform",
            "country",
            "language",
            "is_active",
            "topic_id",
        }
        clean = self._whitelist_updates(updates, allowed)
        if not clean:
            # Match BrandRepository.update_aliases semantics: a no-op patch
            # returns the existing row. Callers that want "must update something"
            # should reject empty patches at the router layer.
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_PROMPT_COLS} FROM geo_client_prompts "
                    "WHERE client_id = $1 AND id = $2",
                    client_id,
                    prompt_id,
                )
            return self._row_to_dict(row)

        async with self._pool.acquire() as conn:
            return await self.update_on_connection(
                client_id, conn, prompt_id, updates=clean
            )

    @tenant_scoped
    async def update_on_connection(
        self,
        client_id: str,
        conn,
        prompt_id: UUID | str,
        *,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        allowed = {"text", "intent", "product", "platform", "country", "language", "is_active", "topic_id"}
        clean = self._whitelist_updates(updates, allowed)
        if not clean:
            row = await conn.fetchrow(
                f"SELECT {_PROMPT_COLS} FROM geo_client_prompts WHERE client_id = $1 AND id = $2",
                client_id, prompt_id,
            )
            return self._row_to_dict(row)
        params: list[Any] = [client_id, prompt_id]
        set_parts: list[str] = []
        for col, val in clean.items():
            params.append(val)
            set_parts.append(f"{col} = ${len(params)}")
        set_parts.append("updated_at = NOW()")
        row = await conn.fetchrow(
            "UPDATE geo_client_prompts "
            f"SET {', '.join(set_parts)} "
            "WHERE client_id = $1 AND id = $2 "
            f"RETURNING {_PROMPT_COLS}",
            *params,
        )
        return self._row_to_dict(row)

    @tenant_scoped
    async def update_many(
        self,
        client_id: str,
        prompt_ids: list[UUID | str],
        *,
        updates: dict[str, Any],
    ) -> int:
        """Whitelisted batch update for prompt variants.

        Returns the number of rows updated. This is used by the Prompt Editor
        where one logical prompt can represent many country/platform rows.
        """
        if not prompt_ids:
            return 0

        allowed = {
            "text",
            "intent",
            "product",
            "platform",
            "country",
            "language",
            "is_active",
            "topic_id",
        }
        clean = self._whitelist_updates(updates, allowed)
        if not clean:
            return 0

        async with self._pool.acquire() as conn:
            return await self.update_many_on_connection(
                client_id, conn, prompt_ids, updates=clean
            )

    @tenant_scoped
    async def update_many_on_connection(
        self,
        client_id: str,
        conn,
        prompt_ids: list[UUID | str],
        *,
        updates: dict[str, Any],
    ) -> int:
        if not prompt_ids:
            return 0
        allowed = {"text", "intent", "product", "platform", "country", "language", "is_active", "topic_id"}
        clean = self._whitelist_updates(updates, allowed)
        if not clean:
            return 0
        params: list[Any] = [client_id, [str(pid) for pid in prompt_ids]]
        set_parts: list[str] = []
        for col, val in clean.items():
            params.append(val)
            set_parts.append(f"{col} = ${len(params)}")
        set_parts.append("updated_at = NOW()")
        result = await conn.execute(
            "UPDATE geo_client_prompts "
            f"SET {', '.join(set_parts)} "
            "WHERE client_id = $1 AND id = ANY($2::uuid[])",
            *params,
        )
        try:
            return int(result.rsplit(" ", 1)[-1])
        except ValueError:
            return 0

    @tenant_scoped
    async def delete(self, client_id: str, prompt_id: UUID | str) -> bool:
        async with self._pool.acquire() as conn:
            return await self.delete_on_connection(client_id, conn, prompt_id)

    @tenant_scoped
    async def delete_on_connection(self, client_id: str, conn, prompt_id: UUID | str) -> bool:
        result = await conn.execute(
            "DELETE FROM geo_client_prompts WHERE client_id = $1 AND id = $2",
            client_id, prompt_id,
        )
        return result.rsplit(" ", 1)[-1] != "0"

    @tenant_scoped
    async def delete_many(
        self, client_id: str, prompt_ids: list[UUID | str]
    ) -> int:
        """Delete a batch of prompts by id. Returns the number actually
        removed."""
        if not prompt_ids:
            return 0
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM geo_client_prompts "
                "WHERE client_id = $1 AND id = ANY($2::uuid[])",
                client_id,
                [str(pid) for pid in prompt_ids],
            )
        try:
            return int(result.rsplit(" ", 1)[-1])
        except ValueError:
            return 0
