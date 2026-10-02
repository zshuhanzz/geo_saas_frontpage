"""Shared DB primitives — asyncpg pool creator and multi-tenant decorator."""

from .pool import create_asyncpg_pool
from .tenant import TenantIsolationError, tenant_scoped

__all__ = [
    "create_asyncpg_pool",
    "tenant_scoped",
    "TenantIsolationError",
]
