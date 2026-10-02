"""Account Manager role API and migration contracts."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from routers.access_control import ClientRole


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_admin_api_accepts_account_manager_workspace_role() -> None:
    assert set(get_args(ClientRole)) == {"admin", "viewer", "account_manager"}


def test_migration_134_expands_role_and_adds_configuration_to_analytics() -> None:
    sql = (
        REPO_ROOT / "migrations" / "134_account_manager_and_analytics_configuration.sql"
    ).read_text(encoding="utf-8")

    assert "'account_manager'" in sql
    assert "geo_client_user_access_role_check" in sql
    assert "'analytics', 'actions.configuration'" in sql
    assert "geo_workspace_feature_entitlements" in sql
    assert "is_custom = false" in sql
