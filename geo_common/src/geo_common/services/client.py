"""
ClientRepository — DAL for ``geo_clients`` (the tenant table itself).

Unlike the other repositories in this package, ClientRepository operates
**above the tenant scope** — it manages the tenant rows themselves, so its
methods are NOT decorated with ``@tenant_scoped``. It is used exclusively
by the admin backend (``geo_admin``) where operators provision / list /
update / delete tenants.

Schema (post-v1.2):

    id UUID PK,
    name TEXT UNIQUE,
    client_prompt_quota INTEGER,
    aliases TEXT[],
    config_countries TEXT[],
    config_platforms TEXT[],
    config_languages TEXT[],
    cron_collector / cron_analyzer / cron_llm_discovery TEXT NULL,
    agent_daily_token_quota INTEGER default 500000,
    agent_rpm_limit INTEGER default 10,
    reuse_latest_final_prompt BOOLEAN NULL,
    country_localization_mode TEXT NULL,
    final_prompt_per_client_prompt INTEGER NULL,
    default_calls_per_prompt INTEGER NULL,
    onboarding_wizard_completed BOOLEAN default false,
    created_at / updated_at TIMESTAMP

Routers should use ``BrandRepository`` / ``TopicRepository`` / etc. for the
tenant-scoped tables; this repository is intentionally narrow to the
``geo_clients`` row itself.
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from .base import BaseRepository

_CLIENT_COLS = (
    "id, name, client_prompt_quota, aliases, "
    "config_countries, config_platforms, config_languages, "
    "cron_collector, cron_analyzer, cron_llm_discovery, "
    "agent_daily_token_quota, agent_rpm_limit, "
    "reuse_latest_final_prompt, country_localization_mode, "
    "final_prompt_per_client_prompt, default_calls_per_prompt, "
    "onboarding_wizard_completed, created_at, updated_at"
)


class ClientRepository(BaseRepository):
    """``geo_clients`` DAL — admin-only, NOT tenant-scoped."""

    async def list_all(
        self,
        *,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """List every client, optionally filtered by case-insensitive name
        substring."""
        if search:
            sql = (
                f"SELECT {_CLIENT_COLS} FROM geo_clients "
                "WHERE name ILIKE $1 ORDER BY name"
            )
            params: list[Any] = [f"%{search}%"]
        else:
            sql = f"SELECT {_CLIENT_COLS} FROM geo_clients ORDER BY name"
            params = []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return self._rows_to_dicts(rows)

    async def get_by_id(
        self, client_id: UUID | str
    ) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_CLIENT_COLS} FROM geo_clients WHERE id = $1",
                client_id,
            )
        return self._row_to_dict(row)

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_CLIENT_COLS} FROM geo_clients WHERE name = $1",
                name,
            )
        return self._row_to_dict(row)

    async def add(
        self,
        *,
        name: str,
        client_prompt_quota: int = 50,
        config_platforms: list[str] | None = None,
        config_countries: list[str] | None = None,
        config_languages: list[str] | None = None,
        cron_collector: str | None = None,
        cron_analyzer: str | None = None,
        cron_llm_discovery: str | None = None,
        conn: Any | None = None,
    ) -> dict[str, Any]:
        """INSERT a new client and return the persisted row."""
        async def _insert(connection: Any):
            return await connection.fetchrow(
                "INSERT INTO geo_clients "
                "(name, client_prompt_quota, "
                " config_platforms, config_countries, config_languages, "
                " cron_collector, cron_analyzer, cron_llm_discovery) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                f"RETURNING {_CLIENT_COLS}",
                name,
                client_prompt_quota,
                config_platforms or [],
                config_countries or [],
                config_languages or [],
                cron_collector,
                cron_analyzer,
                cron_llm_discovery,
            )
        if conn is not None:
            row = await _insert(conn)
        else:
            async with self._pool.acquire() as acquired:
                row = await _insert(acquired)
        return self._row_to_dict(row)

    async def update(
        self,
        client_id: UUID | str,
        *,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Whitelisted partial update. ``updated_at`` is bumped automatically
        (also handled by the ``updated_at`` trigger if installed, but we set
        it explicitly to keep behaviour identical across DB envs)."""
        allowed = {
            "name",
            "client_prompt_quota",
            "config_platforms",
            "config_countries",
            "config_languages",
            "cron_collector",
            "cron_analyzer",
            "cron_llm_discovery",
            "agent_daily_token_quota",
            "agent_rpm_limit",
            "reuse_latest_final_prompt",
            "country_localization_mode",
            "final_prompt_per_client_prompt",
            "default_calls_per_prompt",
            "onboarding_wizard_completed",
        }
        clean = self._whitelist_updates(updates, allowed)
        if not clean:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_CLIENT_COLS} FROM geo_clients WHERE id = $1",
                    client_id,
                )
            return self._row_to_dict(row)

        params: list[Any] = [client_id]
        set_parts: list[str] = []
        for col, val in clean.items():
            params.append(val)
            set_parts.append(f"{col} = ${len(params)}")
        set_parts.append("updated_at = NOW()")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE geo_clients "
                f"SET {', '.join(set_parts)} "
                "WHERE id = $1 "
                f"RETURNING {_CLIENT_COLS}",
                *params,
            )
        return self._row_to_dict(row)

    async def delete(self, client_id: UUID | str) -> bool:
        """Hard delete (CASCADE removes all tenant-scoped child rows).

        Returns True iff a row was actually removed.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM geo_clients WHERE id = $1",
                client_id,
            )
        return result.rsplit(" ", 1)[-1] != "0"

    async def fetch_related_collections(
        self,
        client_ids: Iterable[UUID | str],
    ) -> dict[str, dict[Any, list[dict[str, Any]]]]:
        """Batch-load the four "related" collections used by the admin list
        view: peers, domains, topics, personas — keyed by client_id.

        Used by ``geo_admin/src/routers/clients.py`` ``GET /clients`` so a
        list of N tenants becomes 1 + 4 queries instead of 1 + 4N.

        Returns a dict shaped::

            {
                "peers":    {client_id: [row, ...], ...},
                "domains":  {client_id: [row, ...], ...},
                "topics":   {client_id: [row, ...], ...},
                "personas": {client_id: [row, ...], ...},
            }

        Each row is a plain dict; columns match the underlying tables.
        """
        ids = list(client_ids)
        if not ids:
            return {"peers": {}, "domains": {}, "topics": {}, "personas": {}}

        async with self._pool.acquire() as conn:
            peers = await conn.fetch(
                "SELECT id, client_id, primary_name, aliases, created_at "
                "FROM geo_client_peers WHERE client_id = ANY($1::uuid[])",
                [str(i) for i in ids],
            )
            domains = await conn.fetch(
                "SELECT id, client_id, domain, is_primary, domain_scope, "
                "brand_id, peer_id, created_at "
                "FROM geo_client_domains WHERE client_id = ANY($1::uuid[])",
                [str(i) for i in ids],
            )
            topics = await conn.fetch(
                "SELECT id, client_id, topic_name, topic_type, created_at "
                "FROM geo_client_topics WHERE client_id = ANY($1::uuid[])",
                [str(i) for i in ids],
            )
            personas = await conn.fetch(
                "SELECT id, client_id, persona_name, persona_description, created_at "
                "FROM geo_client_personas WHERE client_id = ANY($1::uuid[])",
                [str(i) for i in ids],
            )

        out: dict[str, dict[Any, list[dict[str, Any]]]] = {
            "peers": {},
            "domains": {},
            "topics": {},
            "personas": {},
        }
        for src, key in (
            (peers, "peers"),
            (domains, "domains"),
            (topics, "topics"),
            (personas, "personas"),
        ):
            for r in src:
                out[key].setdefault(r["client_id"], []).append(dict(r))
        return out
