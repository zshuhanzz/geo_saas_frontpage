"""Admin-wide bounded guard for long Workspace workflows."""

from geo_common.services import WorkspaceLifecycleSessionLimiter


_limiter = WorkspaceLifecycleSessionLimiter(
    "ADMIN_WORKSPACE_LIFECYCLE_MAX_CONCURRENCY",
    default=4,
    pool_capacity=10,
)


def long_workspace_lifecycle_session(pool, client_id: str):
    return _limiter.session(pool, str(client_id))


def long_workspace_lifecycle_slot():
    """Bound long maintenance work before it consumes a pool connection."""
    return _limiter.slot()
