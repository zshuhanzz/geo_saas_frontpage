"""
Tests for ``context.pruner.prune_messages``.

These tests verify the contract laid out in ``geo_agent/src/context/pruner.py``:
SystemMessages always survive, the last ``max_turns`` HumanMessage-led turns
survive (with their AI / tool replies), and the input list is never mutated.
"""
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from context.pruner import DEFAULT_MAX_TURNS, prune_messages


def _h(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _a(text: str) -> AIMessage:
    return AIMessage(content=text)


def _s(text: str) -> SystemMessage:
    return SystemMessage(content=text)


def _conversation(n_turns: int) -> list[BaseMessage]:
    """Build n alternating Human/AI turns: H1, A1, H2, A2, ..."""
    msgs: list[BaseMessage] = []
    for i in range(1, n_turns + 1):
        msgs.append(_h(f"q{i}"))
        msgs.append(_a(f"r{i}"))
    return msgs


def test_empty_input_returns_empty():
    assert prune_messages([]) == []


def test_short_history_passes_through_unchanged():
    msgs = _conversation(3)
    assert prune_messages(msgs, max_turns=10) == msgs


def test_truncates_to_last_n_turns():
    msgs = _conversation(15)
    pruned = prune_messages(msgs, max_turns=5)
    # 5 turns × 2 messages = 10 messages
    assert len(pruned) == 10
    # First kept turn should be turn 11 (q11/r11)
    assert pruned[0] == _h("q11")
    assert pruned[-1] == _a("r15")


def test_preserves_system_messages_at_head():
    sys1 = _s("you are anthony")
    sys2 = _s("[对话摘要] earlier topic was SOV trends")
    dialogue = _conversation(15)
    full = [sys1] + dialogue[:4] + [sys2] + dialogue[4:]

    pruned = prune_messages(full, max_turns=3)
    # Both system messages must come first
    assert pruned[0] is sys1
    assert pruned[1] is sys2
    # Then the last 3 turns of dialogue
    assert pruned[2:] == dialogue[-6:]


def test_does_not_mutate_input():
    msgs = _conversation(20)
    snapshot = list(msgs)
    _ = prune_messages(msgs, max_turns=5)
    assert msgs == snapshot
    # Returned list should not be the same object
    pruned = prune_messages(msgs, max_turns=5)
    pruned.clear()
    assert msgs == snapshot


def test_default_max_turns_constant():
    assert DEFAULT_MAX_TURNS == 10
    msgs = _conversation(15)
    # No max_turns argument — should use the default
    pruned = prune_messages(msgs)
    assert len(pruned) == 20  # 10 turns × 2


def test_keeps_tool_messages_within_kept_turns():
    """Tool messages between Human and AI replies stay attached to the turn."""
    msgs: list[BaseMessage] = [
        _h("q1"), _a("r1"),
        _h("q2"),
        ToolMessage(content="tool result", tool_call_id="t1"),
        _a("r2"),
        _h("q3"), _a("r3"),
    ]
    pruned = prune_messages(msgs, max_turns=2)
    # Last 2 turns = q2 onward
    assert pruned[0] == _h("q2")
    assert isinstance(pruned[1], ToolMessage)
    assert pruned[2] == _a("r2")
    assert pruned[3] == _h("q3")
    assert pruned[4] == _a("r3")


def test_max_turns_zero_clamped_to_one():
    msgs = _conversation(5)
    pruned = prune_messages(msgs, max_turns=0)
    # Last 1 turn only
    assert pruned == [_h("q5"), _a("r5")]


def test_max_turns_negative_clamped_to_one():
    msgs = _conversation(5)
    pruned = prune_messages(msgs, max_turns=-3)
    assert pruned == [_h("q5"), _a("r5")]


def test_only_system_messages_returns_them_all():
    sys_msgs = [_s("a"), _s("b")]
    pruned = prune_messages(sys_msgs, max_turns=5)
    assert pruned == sys_msgs


def test_dialogue_with_no_human_messages_keeps_everything():
    """Edge case: AI-only stream (e.g. seeded greeting) — keep as-is."""
    msgs: list[BaseMessage] = [_a("hi 1"), _a("hi 2")]
    pruned = prune_messages(msgs, max_turns=3)
    assert pruned == msgs


def test_exactly_max_turns_keeps_everything():
    msgs = _conversation(10)
    pruned = prune_messages(msgs, max_turns=10)
    assert pruned == msgs


def test_one_more_than_max_turns_drops_oldest():
    msgs = _conversation(11)
    pruned = prune_messages(msgs, max_turns=10)
    assert len(pruned) == 20
    assert pruned[0] == _h("q2")
    assert pruned[-1] == _a("r11")
