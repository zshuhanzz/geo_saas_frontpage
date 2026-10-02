"""
Context Compressor — percentage-based compression for Agent conversations.

When context usage exceeds the configured percentage threshold (default 80%),
older messages are summarized into a single system message, keeping the most
recent N turns intact.

Configuration is read from geo_global_settings:
  - agent_compress_percentage  (default 80)  — triggers compression at this %
  - agent_compress_retain      (default 4)   — recent turns to keep uncompressed
"""
import time
import logging
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from google.genai import types

from llm.client import get_genai_client, get_model_id, generate_content

logger = logging.getLogger(__name__)

# Settings cache (read from DB, refreshed every 60 seconds)
_settings_cache: dict[str, int] = {}
_settings_cache_ts: float = 0
_SETTINGS_CACHE_TTL = 60

_DEFAULTS = {
    "agent_compress_percentage": 80,
    "agent_compress_retain": 4,
}

COMPRESS_SYSTEM_PROMPT = """You are a conversation summarizer for a GEO (Generative Engine Optimization) analytics platform.

Summarize the following conversation history into a concise summary that preserves:
1. Key data requests and results (metrics, SQL queries, chart types)
2. Important decisions and user preferences
3. Brand names, competitor names, and specific topics discussed
4. Any slot-filling progress (task configuration in progress)

Write the summary in the same language as the conversation. Keep it under 500 words.
Format as a coherent narrative, not bullet points.
Do NOT include greetings or meta-commentary. Just the facts."""


async def get_compress_settings() -> tuple[int, int]:
    """Read compression settings from geo_global_settings, with 60s cache.

    Returns (compress_percentage, retain_turns).
    """
    global _settings_cache, _settings_cache_ts

    now = time.time()
    if now - _settings_cache_ts < _SETTINGS_CACHE_TTL and _settings_cache:
        return (
            _settings_cache.get("agent_compress_percentage", _DEFAULTS["agent_compress_percentage"]),
            _settings_cache.get("agent_compress_retain", _DEFAULTS["agent_compress_retain"]),
        )

    try:
        from database import get_pool
        pool = await get_pool()

        rows = await pool.fetch(
            """SELECT key, value FROM geo_global_settings
               WHERE key IN ('agent_compress_percentage', 'agent_compress_retain')""",
        )
        for row in rows:
            try:
                _settings_cache[row["key"]] = int(row["value"])
            except (ValueError, TypeError):
                pass

        _settings_cache_ts = now
    except Exception as e:
        logger.warning(f"[COMPRESS] Failed to load settings, using defaults: {e}")

    return (
        _settings_cache.get("agent_compress_percentage", _DEFAULTS["agent_compress_percentage"]),
        _settings_cache.get("agent_compress_retain", _DEFAULTS["agent_compress_retain"]),
    )


def count_turns(messages: list) -> int:
    """Count the number of human turns in a message list."""
    return sum(1 for m in messages if isinstance(m, HumanMessage))


def estimate_tokens(messages: list) -> int:
    """Token estimate with CJK/Latin awareness.

    CJK characters: ~1.5 tokens/char (based on Gemini SentencePiece tokenizer)
    Latin characters: ~0.3 tokens/char (~0.75 tokens/word, ~4 chars/word)
    """
    total = 0
    for m in messages:
        text = m.content if hasattr(m, "content") else ""
        cjk = 0
        for c in text:
            cp = ord(c)
            # CJK Unified Ideographs + Extension A + Compatibility
            if (0x4E00 <= cp <= 0x9FFF
                    or 0x3400 <= cp <= 0x4DBF
                    or 0xF900 <= cp <= 0xFAFF
                    or 0x20000 <= cp <= 0x2A6DF):
                cjk += 1
        latin = len(text) - cjk
        total += int(cjk * 1.5 + latin * 0.3)
    return max(total, 1)


async def should_compress(messages: list) -> bool:
    """Check if context usage exceeds the compression percentage threshold."""
    pct_threshold, _ = await get_compress_settings()
    ctx = get_context_usage(messages)
    return ctx["percentage"] >= pct_threshold


async def compress_messages(messages: list) -> list:
    """Compress older messages into a summary, keeping recent turns.

    Returns a new message list: [SystemMessage(summary), ...recent_messages].
    If compression fails, returns the original messages unchanged.
    """
    _, retain = await get_compress_settings()

    # Find the split point: keep the last `retain` human turns (and their AI responses)
    kept_turns = 0
    split_idx = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            kept_turns += 1
            if kept_turns >= retain:
                split_idx = i
                break

    old_messages = messages[:split_idx]
    recent_messages = messages[split_idx:]

    if not old_messages:
        return messages

    # Check if there's already a compression summary at the start
    existing_summary = ""
    if old_messages and isinstance(old_messages[0], SystemMessage) and old_messages[0].content.startswith("[对话摘要]"):
        existing_summary = old_messages[0].content
        old_messages = old_messages[1:]

    # Build conversation text for summarization
    conv_parts = []
    if existing_summary:
        conv_parts.append(f"Previous summary:\n{existing_summary}\n")
    for msg in old_messages:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        text = msg.content if hasattr(msg, "content") else ""
        if text:
            conv_parts.append(f"{role}: {text[:500]}")

    conversation_text = "\n".join(conv_parts)

    try:
        model_id = await get_model_id("flash")
        client = await get_genai_client(model_id, role="flash")

        response = await generate_content(
            client, model_id,
            contents=f"Conversation to summarize:\n\n{conversation_text}",
            config=types.GenerateContentConfig(
                system_instruction=COMPRESS_SYSTEM_PROMPT,
                temperature=0.1,
                max_output_tokens=2048,
            ),
        )

        summary = (response.text or "").strip()
        if not summary:
            logger.warning("[COMPRESS] Empty summary returned, keeping original messages")
            return messages

        summary_msg = SystemMessage(content=f"[对话摘要] {summary}")
        compressed = [summary_msg] + recent_messages

        old_tokens = estimate_tokens(messages)
        new_tokens = estimate_tokens(compressed)
        logger.info(
            f"[COMPRESS] Compressed {len(old_messages)} messages → summary | "
            f"turns: {count_turns(messages)} → {count_turns(recent_messages)} | "
            f"tokens: ~{old_tokens} → ~{new_tokens} ({100 - new_tokens * 100 // max(old_tokens, 1)}% reduction)"
        )

        return compressed

    except Exception as e:
        logger.error(f"[COMPRESS] Compression failed, keeping original: {e}")
        return messages


def get_context_usage(messages: list, max_tokens: int = 100000) -> dict:
    """Calculate context usage metrics for SSE reporting.

    Returns:
        {
            "tokens_used": int,   — estimated tokens in current context
            "tokens_max": int,    — configured max before compression recommended
            "turns": int,         — number of human turns
            "compressed": bool,   — whether context has been compressed
            "percentage": int,    — usage percentage (0-100)
        }
    """
    tokens_used = estimate_tokens(messages)
    turns = count_turns(messages)
    compressed = any(
        isinstance(m, SystemMessage) and hasattr(m, "content") and m.content.startswith("[对话摘要]")
        for m in messages
    )

    return {
        "tokens_used": tokens_used,
        "tokens_max": max_tokens,
        "turns": turns,
        "compressed": compressed,
        "percentage": min(100, tokens_used * 100 // max(max_tokens, 1)),
    }
