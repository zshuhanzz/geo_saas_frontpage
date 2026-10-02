"""
Shared repository / data-access layer for GEO modules.

Phase 4 (2026-04-25): introduces the ``Repository`` pattern as the single
source of truth for cross-module DB access. Before Phase 4, ``geo_saas`` and
``geo_admin`` each owned independent SQL paths against the same Cloud SQL
tables — when a column was added (e.g. ``geo_client_brands.is_shadow``),
both modules had to be updated independently and drift was inevitable.

Repositories own SQL. Routers compose repositories. The ``@tenant_scoped``
decorator enforces the P0 multi-tenant isolation invariant on every
query path that takes ``client_id``.

Migration playbook for an existing query:
    1. Identify the SQL pattern in ``geo_saas`` or ``geo_admin``.
    2. Add a method to the relevant Repository (or create one).
    3. Replace the inline SQL in the router with a Repository call.
    4. Repeat for the same query in any sibling module.

Currently exported repositories:
    - ``BaseRepository``         — pool injection + helpers + the ``@tenant_scoped`` invariant
    - ``BrandRepository``        — ``geo_client_brands`` (Own + Shadow)
    - ``ClientRepository``       — ``geo_clients`` (admin-only, NOT tenant-scoped)
    - ``DomainRepository``       — ``geo_client_domains`` (brand/peer-attributed hosts)
    - ``PeerRepository``         — ``geo_client_peers`` (competitor brands)
    - ``PersonaRepository``      — ``geo_client_personas``
    - ``PromptRepository``       — ``geo_client_prompts`` (covers SaaS + Admin)
    - ``TopicRepository``        — ``geo_client_topics``
    - ``TopicProductRepository`` — ``geo_client_topic_products`` (Own / Shadow / Peer roles)
"""

from .base import BaseRepository
from .brand import BrandRepository
from .client import ClientRepository
from .domain import DomainRepository
from .peer import PeerRepository
from .persona import PersonaRepository
from .prompt import PromptRepository
from .prompt_deletion import (
    DEFAULT_PROMPT_CASCADE_BATCH_SIZE,
    MAX_PROMPT_CASCADE_BATCH_SIZE,
    PromptCascadeDeleteResult,
    PromptCascadeDeletionService,
)
from .prompt_write import PromptWriteCoordinator
from .prompt_keys import (
    canonical_prompt_logical_key,
    canonical_prompt_metadata,
    canonical_prompt_physical_key,
    canonical_prompt_text,
)
from .topic import TopicRepository
from .topic_product import TopicProductRepository
from .workspace_lifecycle import (
    WorkspaceLifecycleBusy,
    WorkspaceLifecycleMissing,
    WorkspaceLifecycleSessionLimiter,
    WorkspaceWriteCoordinator,
    acquire_workspace_lifecycle_exclusive,
    acquire_workspace_lifecycle_session_shared,
    acquire_workspace_lifecycle_shared,
    release_workspace_lifecycle_session_shared,
    try_acquire_workspace_lifecycle_exclusive,
    workspace_lifecycle_lock_key,
    workspace_lifecycle_session,
)

__all__ = [
    "BaseRepository",
    "BrandRepository",
    "ClientRepository",
    "DomainRepository",
    "DEFAULT_PROMPT_CASCADE_BATCH_SIZE",
    "MAX_PROMPT_CASCADE_BATCH_SIZE",
    "PeerRepository",
    "PersonaRepository",
    "PromptCascadeDeleteResult",
    "PromptCascadeDeletionService",
    "PromptRepository",
    "PromptWriteCoordinator",
    "canonical_prompt_logical_key",
    "canonical_prompt_metadata",
    "canonical_prompt_physical_key",
    "canonical_prompt_text",
    "TopicRepository",
    "TopicProductRepository",
    "WorkspaceLifecycleMissing",
    "WorkspaceLifecycleBusy",
    "WorkspaceLifecycleSessionLimiter",
    "WorkspaceWriteCoordinator",
    "acquire_workspace_lifecycle_exclusive",
    "acquire_workspace_lifecycle_session_shared",
    "acquire_workspace_lifecycle_shared",
    "release_workspace_lifecycle_session_shared",
    "try_acquire_workspace_lifecycle_exclusive",
    "workspace_lifecycle_lock_key",
    "workspace_lifecycle_session",
]
