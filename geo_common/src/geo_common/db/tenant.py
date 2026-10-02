"""
Multi-tenant isolation decorator.

P0 security: every data query tool that accepts `client_id` MUST be decorated
with `@tenant_scoped`. The decorator enforces `client_id` is present and looks
like a reasonable UUID-ish string (non-empty, length >= 8).

Originally lived at `geo_agent/src/middleware/tenant.py`; moved to `geo_common`
in Phase 2 (2026-04-25) so all modules share a single enforcement primitive.
The old location now re-exports from here for backward compatibility.
"""

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TenantIsolationError(Exception):
    """Raised when `client_id` is missing or invalid on a `@tenant_scoped` call."""


def tenant_scoped(fn: Callable) -> Callable:
    """
    Decorator that enforces `client_id` presence on every tool invocation.

    The decorated function MUST accept `client_id: str` as its first argument
    (positional or kwarg). If `client_id` is missing, empty, non-string, or
    shorter than 8 chars, the tool refuses to execute.

    Usage::

        @tenant_scoped
        async def visibility_query(client_id: str, time_range: str, ...) -> dict:
            ...
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Pull `client_id` from kwargs, else from the first positional arg.
        # When ``fn`` is an instance method, ``args[0]`` is ``self`` — detect
        # that and look at ``args[1]`` instead. We use ``BaseRepository``
        # (lazy-imported to avoid an import cycle) as the marker class for
        # "this is a method, skip self". A module-level @tool function never
        # passes a Repository as its first arg, so this is unambiguous.
        if "client_id" in kwargs:
            client_id = kwargs["client_id"]
        elif args:
            from geo_common.services.base import BaseRepository  # noqa: WPS433
            if isinstance(args[0], BaseRepository) and len(args) >= 2:
                client_id = args[1]
            else:
                client_id = args[0]
        else:
            client_id = None

        if (
            not client_id
            or not isinstance(client_id, str)
            or len(client_id) < 8
        ):
            raise TenantIsolationError(
                f"Tool '{fn.__name__}' requires a valid client_id. "
                f"Got: {client_id!r}"
            )

        logger.debug(f"[TENANT] {fn.__name__} executing for client_id={client_id}")
        return await fn(*args, **kwargs)

    return wrapper
