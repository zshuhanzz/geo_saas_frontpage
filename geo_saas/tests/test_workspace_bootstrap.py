"""Lightweight Workspace bootstrap and tenant-scoped context contracts."""

from __future__ import annotations

from uuid import UUID

import pytest

from geo_common.auth import AuthenticatedUser
from routers.clients import list_accessible_clients
from routers.me import get_feature_catalog, list_accessible_workspaces
from routers.workspaces import get_workspace_context
from dependencies.auth import require_current_user, require_feature_access_if_present
from main import app


USER_ID = "77246f8b-84b8-4e3b-a085-7a79b7a1e825"
CLIENT_ID = "b0e10518-5f70-426f-b09e-dbe025984ba1"
OTHER_CLIENT_ID = "fdfbe155-a95d-461d-bf21-e37ad956027f"


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=USER_ID,
        email="viewer@example.com",
        google_sub="viewer-sub",
        name="Viewer",
        avatar_url=None,
        is_active=True,
    )


def _route_dependency_calls(path: str) -> set[object]:
    route = next(route for route in app.routes if getattr(route, "path", "") == path)
    return {
        dependency.call
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }


class BootstrapDb:
    def __init__(self):
        self.calls = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append(("fetchrow", sql, args))
        if "geo_admin_user_access" in sql:
            return None
        raise AssertionError(f"Unexpected fetchrow query: {sql}")

    async def fetch(self, sql: str, *args):
        self.calls.append(("fetch", sql, args))
        if "FROM geo_client_user_access" in sql:
            return [
                {
                    "id": CLIENT_ID,
                    "name": "AnswerX",
                    "grant_role": "viewer",
                }
            ]
        if "geo_workspace_feature_entitlements" in sql:
            assert args == ([CLIENT_ID],)
            return [
                {
                    "client_id": CLIENT_ID,
                    "feature_key": "analytics.overview",
                },
                {
                    "client_id": CLIENT_ID,
                    "feature_key": "actions.configuration",
                },
            ]
        raise AssertionError(f"Unexpected fetch query: {sql}")


class SuperAdminScopedDb(BootstrapDb):
    async def fetchrow(self, sql: str, *args):
        self.calls.append(("fetchrow", sql, args))
        if "geo_admin_user_access" in sql:
            return {
                "role": "super_admin",
                "support_all_clients": False,
                "is_active": True,
            }
        raise AssertionError(f"Unexpected fetchrow query: {sql}")


class FeatureCatalogDb:
    async def fetch(self, sql: str, *args):
        assert "FROM geo_feature_catalog" in sql
        assert "WHERE is_active = true" in sql
        return [
            {
                "feature_key": "actions.content",
                "module_key": "actions",
                "display_name_zh": "数据库内容生成",
                "display_name_en": "DB Content",
                "description_zh": "数据库介绍",
                "description_en": "Database description",
                "sort_order": 30,
            },
            {
                "feature_key": "database.only",
                "module_key": "actions",
                "display_name_zh": "非法功能",
                "display_name_en": "Unknown",
                "description_zh": "",
                "description_en": "",
                "sort_order": 999,
            },
        ]


class ContextDb:
    def __init__(self):
        self.calls = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append(("fetchrow", sql, args))
        assert "WHERE id = $1::uuid" in sql
        assert args == (CLIENT_ID,)
        return {
            "id": CLIENT_ID,
            "name": "AnswerX",
            "client_prompt_quota": 100,
            "config_platforms": ["chatgpt"],
            "config_countries": ["US"],
            "config_languages": ["en"],
        }

    async def fetch(self, sql: str, *args):
        self.calls.append(("fetch", sql, args))
        assert "client_id = $1::uuid" in sql
        assert args == (CLIENT_ID,)
        if "FROM geo_client_topics" in sql:
            return [
                {
                    "id": "topic-1",
                    "client_id": CLIENT_ID,
                    "topic_name": "Robot Vacuum",
                    "is_active": True,
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        if "FROM geo_client_topic_products" in sql:
            return [{"topic_id": "topic-1", "product_name": "S8 MaxV"}]
        raise AssertionError(f"Unexpected fetch query: {sql}")


class LegacyClientsDb(BootstrapDb):
    async def fetch(self, sql: str, *args):
        if "FROM geo_clients" in sql and "ANY($1::uuid[])" in sql:
            self.calls.append(("fetch", sql, args))
            assert args == ([UUID(CLIENT_ID)],)
            return [
                {
                    "id": CLIENT_ID,
                    "name": "AnswerX",
                    "client_prompt_quota": 100,
                    "config_platforms": ["chatgpt"],
                    "config_countries": ["US"],
                    "config_languages": ["en"],
                }
            ]
        if "FROM geo_client_topics" in sql:
            self.calls.append(("fetch", sql, args))
            assert args == ([UUID(CLIENT_ID)],)
            return [
                {
                    "id": "topic-1",
                    "client_id": CLIENT_ID,
                    "topic_name": "Robot Vacuum",
                    "created_at": None,
                }
            ]
        if "FROM geo_client_topic_products" in sql:
            self.calls.append(("fetch", sql, args))
            assert args == ([UUID(CLIENT_ID)],)
            return [{"topic_id": "topic-1", "product_name": "S8 MaxV"}]
        return await super().fetch(sql, *args)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_workspace_bootstrap_only_lists_active_grants_and_batches_entitlements() -> None:
    db = BootstrapDb()

    workspaces = await list_accessible_workspaces(current_user=_user(), pool=db)

    assert [workspace.id for workspace in workspaces] == [CLIENT_ID]
    assert workspaces[0].role == "viewer"
    assert set(workspaces[0].enabled_features) == {
        "analytics.overview",
        "actions.configuration",
    }
    list_sql = next(
        sql for method, sql, _args in db.calls
        if method == "fetch" and "FROM geo_client_user_access" in sql
    )
    assert "a.user_id = $1::uuid" in list_sql
    assert "a.is_active = true" in list_sql
    assert OTHER_CLIENT_ID not in str(workspaces)


@pytest.mark.anyio
async def test_super_admin_without_global_support_only_lists_explicit_grants() -> None:
    db = SuperAdminScopedDb()

    workspaces = await list_accessible_workspaces(current_user=_user(), pool=db)

    assert [workspace.id for workspace in workspaces] == [CLIENT_ID]
    assert workspaces[0].role == "super_admin"
    assert workspaces[0].entitlement_override is True
    assert not any(
        method == "fetch" and "geo_workspace_feature_entitlements" in sql
        for method, sql, _args in db.calls
    )


@pytest.mark.anyio
async def test_feature_catalog_uses_database_metadata_and_filters_unknown_keys() -> None:
    catalog = await get_feature_catalog(
        current_user=_user(),
        pool=FeatureCatalogDb(),
    )

    assert len(catalog) == 1
    assert catalog[0].feature_key == "actions.content"
    assert catalog[0].display_name_zh == "数据库内容生成"
    assert catalog[0].description_zh == "数据库介绍"


@pytest.mark.anyio
async def test_workspace_context_queries_every_table_with_client_scope() -> None:
    db = ContextDb()

    context = await get_workspace_context(client_id=CLIENT_ID, pool=db)

    assert context.id == CLIENT_ID
    assert context.topics[0].products == ["S8 MaxV"]
    assert len(db.calls) == 3
    assert all(args == (CLIENT_ID,) for _method, _sql, args in db.calls)


@pytest.mark.anyio
async def test_legacy_clients_endpoint_batches_authorized_workspace_details() -> None:
    db = LegacyClientsDb()

    clients = await list_accessible_clients(user=_user(), pool=db)

    assert [client.id for client in clients] == [CLIENT_ID]
    assert clients[0].topics[0].products == ["S8 MaxV"]
    detail_queries = [
        sql for method, sql, _args in db.calls
        if method == "fetch"
        and (
            "FROM geo_clients" in sql
            or "FROM geo_client_topics" in sql
            or "FROM geo_client_topic_products" in sql
        )
    ]
    assert len(detail_queries) == 3
    assert all("ANY($1::uuid[])" in sql for sql in detail_queries)


def test_new_workspace_apis_have_explicit_authorization_boundaries() -> None:
    assert require_feature_access_if_present in _route_dependency_calls(
        "/api/workspaces/{client_id}/context"
    )
    assert require_current_user in _route_dependency_calls("/api/me/workspaces")
    assert require_current_user in _route_dependency_calls("/api/me/feature-catalog")
