"""
LangGraph State schemas for geo_agent.

All agents share BaseAgentState. Each sub-graph extends it with
domain-specific fields.
"""
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class BaseAgentState(TypedDict):
    """Shared state across all agents.

    task_inputs and task_ready live here (not in sub-graph states) so they
    survive across turns.  Compiled sub-graphs only receive fields that exist
    in the parent state; keeping these in Base ensures the Supervisor can
    checkpoint them and pass them back on the next invocation.
    """
    messages: Annotated[list, add_messages]
    client_id: str                          # Injected from JWT, immutable
    thread_id: str
    client_name: str                        # Loaded from geo_clients at API boundary
    brand_profile: Optional[dict[str, Any]] # Loaded from geo_brand_profiles (may be None)
    widgets: list[dict[str, Any]]           # Interactive UI widgets emitted per turn
    # Slot-filling (shared so supervisor can checkpoint across subgraph turns)
    task_inputs: dict[str, Any]             # Accumulated slot-fill inputs
    task_ready: bool                        # True when all required inputs collected


class SupervisorState(BaseAgentState):
    """Supervisor routes to sub-graphs based on intent."""
    intent: str          # "analyze" | "action" | "chat"
    entry_point: str     # "content" | "analysis" | "chat" | "" — hard-constrains intent for dedicated entries


class AnalyzeState(BaseAgentState):
    """Analyze Agent state — NL2SQL: generates SQL, executes, charts, synthesizes.

    When invoked via chat, the slot-filler collects task_inputs first, then
    emits task_ready=True so the frontend can create a background task.
    When invoked via template form, the pipeline runs directly (no slot-filling).

    task_inputs and task_ready are inherited from BaseAgentState.
    """
    nl2sql_plan: dict[str, Any]        # LLM plan: {sql, chart_type, params, ...}
    query_results: list[dict[str, Any]]  # Raw query result rows
    query_sql: str                     # The executed SQL (for thinking panel)
    charts: list[dict[str, Any]]       # Generated chart configs (Recharts JSON)
    insights: str                      # Generated insights markdown
    # Internal routing
    _mode: str                         # "direct" | "guided" — set by intent_router


class ActionState(BaseAgentState):
    """Action Agent state — slot-filling for content generation tasks.

    The Action Agent collects inputs through conversation, then creates
    a background task via geo_agent_tasks. No inline HITL — the task
    runs asynchronously with status polling.

    task_inputs and task_ready are inherited from BaseAgentState.
    """
    content_type: str                  # "faq" | "article" | "recommendations" | "brief"
    action_topic: str                  # Topic/subject for content generation
    task_id: Optional[str]             # Created task ID (after user confirms)
