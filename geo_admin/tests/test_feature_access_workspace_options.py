"""Lightweight Workspace option contracts for Feature Access."""

from __future__ import annotations

import pytest

from routers import feature_access


class WorkspaceOptionPool:
    def __init__(self) -> None:
        self.sql = ""

    async def fetch(self, sql: str):
        self.sql = sql
        return [
            {
                "id": "fd49b501-4c1b-499a-9b5f-193102f56f29",
                "name": "AnswerX",
            },
            {
                "id": "33af2049-af8e-42ab-adb9-4224f5369b18",
                "name": "AnswerX (Demo)",
            },
        ]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_feature_access_workspace_options_only_load_id_and_name() -> None:
    handler = getattr(feature_access, "list_workspace_options", None)
    assert handler is not None, "Feature Access needs a lightweight Workspace list"

    pool = WorkspaceOptionPool()
    result = await handler(pool)

    assert result == [
        {
            "id": "fd49b501-4c1b-499a-9b5f-193102f56f29",
            "name": "AnswerX",
        },
        {
            "id": "33af2049-af8e-42ab-adb9-4224f5369b18",
            "name": "AnswerX (Demo)",
        },
    ]
    normalized_sql = " ".join(pool.sql.split()).lower()
    assert "select id::text as id, name" in normalized_sql
    assert "from geo_clients" in normalized_sql
    assert "peer" not in normalized_sql
    assert "topic" not in normalized_sql
    assert "persona" not in normalized_sql

