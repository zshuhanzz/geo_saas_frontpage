"""Shared feature-entitlement and RBAC contracts."""

from .registry import (
    CAPABILITIES,
    FEATURE_REGISTRY,
    MODULES,
    ROLE_CAPABILITIES,
    FeatureDefinition,
    FeatureModule,
    RoutePolicy,
    capability_allowed,
    get_feature,
    registry_payload,
    resolve_backend_policies,
    resolve_frontend_feature,
)

__all__ = [
    "CAPABILITIES",
    "FEATURE_REGISTRY",
    "MODULES",
    "ROLE_CAPABILITIES",
    "FeatureDefinition",
    "FeatureModule",
    "RoutePolicy",
    "capability_allowed",
    "get_feature",
    "registry_payload",
    "resolve_backend_policies",
    "resolve_frontend_feature",
]
