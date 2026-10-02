"""Unit tests for Admin Access Control safety helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from routers.access_control import _build_user_audit_filters, _ensure_not_last_active_super_admin


class SequencedDb:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append(("fetchrow", sql, args))
        if not self.rows:
            return None
        return self.rows.pop(0)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_ensure_not_last_active_super_admin_blocks_last_active_admin() -> None:
    db = SequencedDb(
        [
            {"role": "super_admin", "is_active": True},
            {"count": 1},
        ]
    )

    with pytest.raises(HTTPException) as exc:
        await _ensure_not_last_active_super_admin(
            db,
            "8f422899-c4a0-494f-b868-b94fcd5f79d2",
        )

    assert exc.value.status_code == 400
    assert "last active Super Admin" in exc.value.detail


@pytest.mark.anyio
async def test_ensure_not_last_active_super_admin_allows_when_another_admin_exists() -> None:
    db = SequencedDb(
        [
            {"role": "super_admin", "is_active": True},
            {"count": 2},
        ]
    )

    await _ensure_not_last_active_super_admin(
        db,
        "8f422899-c4a0-494f-b868-b94fcd5f79d2",
    )


def test_build_user_audit_filters_supports_client_and_user_filters_with_pagination() -> None:
    where_sql, params, limit, offset = _build_user_audit_filters(
        client_search="dream",
        user_search="lancelot",
        page=3,
        page_size=25,
    )

    assert "c.name ILIKE $1" in where_sql
    assert "(u.email ILIKE $2 OR u.name ILIKE $2)" in where_sql
    assert params == ["%dream%", "%lancelot%"]
    assert limit == 25
    assert offset == 50


def test_build_user_audit_filters_caps_page_size_at_100() -> None:
    where_sql, params, limit, offset = _build_user_audit_filters(
        client_search=None,
        user_search=None,
        page=1,
        page_size=500,
    )

    assert where_sql == ""
    assert params == []
    assert limit == 100
    assert offset == 0
