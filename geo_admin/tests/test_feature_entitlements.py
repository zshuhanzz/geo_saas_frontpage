"""Feature entitlement write contracts."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.feature_entitlements import (
    validate_feature_keys,
    validate_package_feature_keys,
)


def test_validate_feature_keys_accepts_code_registry_keys() -> None:
    assert validate_feature_keys(
        ["actions.content", "analytics.overview", "actions.content"]
    ) == ["actions.content", "analytics.overview"]


def test_validate_feature_keys_rejects_database_only_key() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_feature_keys(["actions.not_declared"])
    assert exc.value.status_code == 400
    assert "actions.not_declared" in str(exc.value.detail)


def test_standard_packages_must_keep_configuration_access() -> None:
    for package_key in ("analytics", "full_platform"):
        with pytest.raises(HTTPException) as exc:
            validate_package_feature_keys(
                package_key,
                ["analytics.overview"],
            )
        assert exc.value.status_code == 400
        assert "actions.configuration" in str(exc.value.detail)


def test_custom_packages_may_omit_configuration_access() -> None:
    assert validate_package_feature_keys(
        "customer_custom",
        ["analytics.overview"],
    ) == ["analytics.overview"]
