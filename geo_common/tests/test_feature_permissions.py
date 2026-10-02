"""Contract tests for the single code-owned feature registry."""

from __future__ import annotations

from geo_common.permissions import (
    FEATURE_REGISTRY,
    ROLE_CAPABILITIES,
    capability_allowed,
    resolve_backend_policies,
    resolve_frontend_feature,
)


def test_feature_keys_are_unique_and_use_declared_modules() -> None:
    keys = [feature.key for feature in FEATURE_REGISTRY]
    assert len(keys) == len(set(keys))
    assert set(keys) == {
        "analytics.overview",
        "analytics.visibility",
        "analytics.citations",
        "analytics.sentiment",
        "analytics.prompts",
        "analytics.reports",
        "actions.configuration",
        "actions.analysis",
        "actions.content",
        "actions.chat",
        "actions.training",
    }


def test_viewer_can_view_results_but_cannot_execute_actions() -> None:
    assert capability_allowed("viewer", "actions.analysis", "view")
    assert capability_allowed("viewer", "actions.content", "view")
    assert not capability_allowed("viewer", "actions.analysis", "execute")
    assert not capability_allowed("viewer", "actions.content", "execute")
    assert not capability_allowed("viewer", "actions.chat", "view")
    assert not capability_allowed("viewer", "actions.training", "view")


def test_admin_has_every_capability_on_every_feature() -> None:
    assert set(ROLE_CAPABILITIES["admin"]) == {
        feature.key for feature in FEATURE_REGISTRY
    }
    assert all(
        set(capabilities) == {"view", "execute", "manage"}
        for capabilities in ROLE_CAPABILITIES["admin"].values()
    )


def test_internal_workspace_roles_have_every_capability_on_every_feature() -> None:
    expected_features = {feature.key for feature in FEATURE_REGISTRY}
    for role in ("account_manager", "super_admin"):
        assert set(ROLE_CAPABILITIES[role]) == expected_features
        assert all(
            set(capabilities) == {"view", "execute", "manage"}
            for capabilities in ROLE_CAPABILITIES[role].values()
        )


def test_reports_materialize_is_registered_as_view() -> None:
    policies = resolve_backend_policies(
        "saas",
        "POST",
        "/api/static-reports/today/materialize",
    )
    assert [(feature.key, policy.capability) for feature, policy in policies] == [
        ("analytics.reports", "view")
    ]


def test_frontend_route_contract_preserves_sidebar_paths() -> None:
    assert resolve_frontend_feature("/overview").key == "analytics.overview"
    assert resolve_frontend_feature("/insights/prompts/topic/abc").key == "analytics.prompts"
    assert resolve_frontend_feature("/agents/tracking").key == "actions.configuration"
    assert resolve_frontend_feature("/agents/content").key == "actions.content"


def test_workspace_context_route_is_configuration_view() -> None:
    policies = resolve_backend_policies(
        "saas",
        "GET",
        "/api/workspaces/00000000-0000-0000-0000-000000000001/context",
    )
    assert [(feature.key, policy.capability) for feature, policy in policies] == [
        ("actions.configuration", "view")
    ]
