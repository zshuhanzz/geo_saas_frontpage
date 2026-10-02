"""
Message Pruning — Layer 1 of the Agent context management stack.

LangGraph's checkpointer stores the full conversation history so the UI can
re-render every turn. But sending that full history to the LLM on every call
makes token cost grow linearly with conversation length and lets stale turns
distract the model.

`prune_messages` returns a *truncated* view of the message list intended for
the LLM. It MUST NOT be written back into the checkpoint — pass the result as
a local variable to the model invocation only.

The `max_turns` budget is read from `geo_global_settings.agent_prune_max_turns`
via `get_prune_max_turns()` (60s cache). This mirrors compressor.py's pattern
so ops can tune the pruning window without a redeploy. `DEFAULT_MAX_TURNS` is
the in-process fallback used only when the DB read fails.

Layer 2 (sliding-window summary in `compressor.py`) and Layer 3 (Gemini
context caching) build on top of this.
"""
import logging
import time
from typing import List

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS = 10

_settings_cache: dict[str, int] = {}
_settings_cache_ts: float = 0.0
_SETTINGS_CACHE_TTL = 60


async def get_prune_max_turns() -> int:
    """Read ``agent_prune_max_turns`` from ``geo_global_settings`` (60s cache).

    Falls back to ``DEFAULT_MAX_TURNS`` if the row is missing or the DB read
    fails — the agent must keep serving traffic even if the settings table
    is briefly unavailable.
    """
    global _settings_cache, _settings_cache_ts

    now = time.time()
    if now - _settings_cache_ts < _SETTINGS_CACHE_TTL and _settings_cache:
        return _settings_cache.get("agent_prune_max_turns", DEFAULT_MAX_TURNS)

    try:
        from database import get_pool
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT key, value FROM geo_global_settings WHERE key = 'agent_prune_max_turns'",
        )
        for row in rows:
            try:
                _settings_cache[row["key"]] = int(row["value"])
            except (ValueError, TypeError):
                pass
        _settings_cache_ts = now
    except Exception as exc:
        logger.warning("[PRUNE] Failed to load agent_prune_max_turns, using default: %s", exc)

    return _settings_cache.get("agent_prune_max_turns", DEFAULT_MAX_TURNS)


def prune_messages(messages: List[BaseMessage], max_turns: int = DEFAULT_MAX_TURNS) -> List[BaseMessage]:
    """Return the tail of ``messages`` covering the last ``max_turns`` user turns.

    A "turn" is counted from the human side: one HumanMessage and the AI / tool
    messages that follow it count as one turn. SystemMessages are *always*
    preserved because they carry context (system prompts, compression
    summaries, brand profile injections), not history.

    The pruned list always preserves chronological order:

        [<all SystemMessages from the head>, ...<last N turns of dialogue>]

    Parameters
    ----------
    messages:
        The full message list from the LangGraph state. Not mutated.
    max_turns:
        Number of HumanMessage-led turns to retain. Must be >= 1. Values <= 0
        are clamped to 1 (the latest turn must always be sent — that's the
        actual user question we're responding to).

    Returns
    -------
    list[BaseMessage]
        A new list, suitable for passing directly to ``model.ainvoke`` /
        ``generate_content``. The original ``messages`` list is untouched.
    """
    if not messages:
        return []

    if max_turns < 1:
        max_turns = 1

    # Split system messages out — they're context, not history.
    system_messages: List[BaseMessage] = [m for m in messages if isinstance(m, SystemMessage)]
    dialogue: List[BaseMessage] = [m for m in messages if not isinstance(m, SystemMessage)]

    if not dialogue:
        return list(system_messages)

    # Walk backward through the dialogue, counting HumanMessages as turn markers.
    # Stop after we've collected `max_turns` of them; everything from that
    # boundary forward is kept (so we naturally include the AI / tool messages
    # that belong to those turns). If the loop never finds enough human
    # messages, boundary stays at 0 and we keep the whole dialogue.
    kept_turns = 0
    boundary = 0
    for i in range(len(dialogue) - 1, -1, -1):
        if isinstance(dialogue[i], HumanMessage):
            kept_turns += 1
            if kept_turns >= max_turns:
                boundary = i
                break

    pruned_dialogue = dialogue[boundary:]
    return system_messages + pruned_dialogue


__all__ = ["prune_messages", "get_prune_max_turns", "DEFAULT_MAX_TURNS"]
