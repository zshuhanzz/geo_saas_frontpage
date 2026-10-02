"""
[Compatibility shim] — re-exports from ``geo_common.db.tenant``.

Phase 2 (2026-04-25): The ``@tenant_scoped`` decorator was lifted into the
shared ``geo_common`` package so all 5 GEO modules can enforce multi-tenant
isolation from a single primitive. This file stays as a thin alias so existing
``from middleware.tenant import tenant_scoped`` imports across ``geo_agent``
keep working without bulk-editing every callsite.

**New code should prefer** ::

    from geo_common.db import tenant_scoped, TenantIsolationError
"""

from geo_common.db.tenant import TenantIsolationError, tenant_scoped

__all__ = ["tenant_scoped", "TenantIsolationError"]
