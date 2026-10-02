"""
Cross-Session Memory — per-message evaluation and LLM-managed CRUD.

Each user message is evaluated asynchronously by Gemini Flash to decide
whether it contains information worth remembering. The LLM sees existing
memories and can ADD, UPDATE, DELETE, MERGE, or SKIP.

Hard limit: 30 memory entries per user per client. When full, LLM must
evict or merge before adding new entries.

Memory lifecycle:
1. EVALUATE: After each user message, Flash decides if memory ops are needed.
2. EXECUTE: DB operations (INSERT/UPDATE/DELETE) based on Flash response.
3. INJECT: On conversation start, load all memories into system prompt.
"""
import logging
import json
from typing import Optional

from google.genai import types

from llm.client import get_genai_client, get_model_id, generate_content
from context.user_profile import (
    load_profile, save_profile, PROFILE_EVALUATE_ADDITION,
)

logger = logging.getLogger(__name__)

MEMORY_LIMIT = 30  # Max entries per user per client

EVALUATE_SYSTEM_PROMPT = """You are a memory manager for an AI assistant called Anthony,
which helps Chinese overseas brands with GEO (Generative Engine Optimization).

You will receive the user's latest message and a list of existing memories.
Your job: Decide if the message contains information worth remembering for FUTURE conversations.

## MUST REMEMBER (never skip these)
- **Preferences**: analysis style, report format, language, depth, chart types, response style
- **Preference changes**: "偏好...", "我想改成...", "以后用...", "不要太详细", "简洁一点"
- **Identity/role**: "我负责...", "我是...", "我的角色是...", team info, responsibilities
- **Brand/business facts**: positioning, products, target markets, competitors
- **Standing instructions**: "记住这个", "以后都这样做", "always do X"
- **Context**: upcoming launches, KPIs, organizational info, workflow habits

## SKIP (only these specific patterns)
- Pure data queries: "分析一下上周的 visibility", "帮我看看引用数据"
- Greetings and acknowledgments: "好的", "继续", "谢谢", "你好"
- Database-derivable data (metric values, platform lists)

## EXAMPLES (follow these exactly)

User: "我对 GEO 的分析偏好简洁、概要的风格"
→ {{"action": "add", "memory_type": "preference", "content": "用户偏好简洁概要的 GEO 分析风格，不需要详尽全面的分析"}}

User: "我主要负责整体策略的制定"
→ {{"action": "add", "memory_type": "fact", "content": "用户在团队中负责整体策略制定"}}

User: "以后报告都用中文，图表用折线图"
→ {{"action": "add", "memory_type": "preference", "content": "报告语言：中文；图表偏好：折线图"}}

User: "分析一下上周 Roborock 的可见度趋势"
→ {{"action": "skip"}}

User: "好的，谢谢"
→ {{"action": "skip"}}

If an existing memory covers the same topic but with different content, use UPDATE with the existing memory's ID.

## EXISTING MEMORIES
{existing_memories}

## RULES
- Current entry count: {memory_count}/{memory_limit}
- If adding would exceed {memory_limit}, you MUST delete or merge entries to make room.
- If new info contradicts an existing memory, UPDATE the existing one.
- If two existing memories are redundant, MERGE them.

## OUTPUT FORMAT (JSON only, no other text)

{{"action": "skip"}}

{{"action": "add", "memory_type": "preference|fact|context", "content": "..."}}

{{"action": "update", "memory_id": "<full-uuid>", "content": "updated content", "memory_type": "preference|fact|context"}}

{{"action": "delete", "memory_id": "<full-uuid>"}}

{{"action": "merge", "delete_ids": ["<id1>", "<id2>"], "memory_type": "preference|fact|context", "content": "merged content"}}

{{"action": "add_and_evict", "memory_type": "preference|fact|context", "content": "new content", "evict_id": "<id of least important memory>"}}

{{"action": "batch", "ops": [<op1>, <op2>, ...]}}

{profile_section}

Return ONLY the JSON object."""


# ── Public API ──────────────────────────────────────────────────────────


async def evaluate_and_update_memory(
    user_message: str,
    client_id: str,
    user_identifier: str,
) -> dict:
    """Evaluate a single user message and update memories + profile if needed.

    This is called as a fire-and-forget background task after each user message.
    One Flash call handles both memory and profile evaluation (zero extra cost).
    Returns a summary dict for logging: {"action": "skip|add|update|...", "changed": int}
    """
    if not user_message or len(user_message.strip()) < 5:
        return {"action": "skip", "changed": 0}

    from database import get_pool
    pool = await get_pool()

    # Load existing memories for this user
    rows = await pool.fetch(
        """SELECT id, memory_type, content FROM agent_memories
           WHERE client_id = $1::uuid AND user_identifier = $2
           ORDER BY updated_at DESC LIMIT $3""",
        client_id, user_identifier, MEMORY_LIMIT + 10,
    )

    existing = [{"id": str(r["id"]), "type": r["memory_type"], "content": r["content"]} for r in rows]
    memory_count = len(existing)

    # Format existing memories for prompt (FULL UUID — needed for update/delete ops)
    if existing:
        mem_lines = [f'- [{m["id"]}] ({m["type"]}) {m["content"]}' for m in existing]
        existing_text = "\n".join(mem_lines)
    else:
        existing_text = "(no existing memories)"

    # Load current profile for combined evaluation
    current_profile = await load_profile(client_id, user_identifier)
    profile_section = PROFILE_EVALUATE_ADDITION.format(
        current_profile=current_profile or "(no profile yet)",
    )

    prompt = EVALUATE_SYSTEM_PROMPT.format(
        existing_memories=existing_text,
        memory_count=memory_count,
        memory_limit=MEMORY_LIMIT,
        profile_section=profile_section,
    )

    try:
        model_id = await get_model_id("flash")
        client = await get_genai_client(model_id, role="flash")

        response = await generate_content(
            client, model_id,
            contents=f"User message:\n{user_message[:1000]}",
            config=types.GenerateContentConfig(
                system_instruction=prompt,
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=1024,
                thinkingConfig=types.ThinkingConfig(thinkingBudget=0),
            ),
        )

        raw = (response.text or "").strip()
        # Strip markdown code fences if present (Flash sometimes wraps JSON)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]  # remove first line (```json)
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        logger.info(f"[MEMORY] Flash raw response ({len(raw)} chars): {raw[:500]}")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as je:
            logger.warning(f"[MEMORY] JSON parse failed: {je} | full raw: {raw!r}")
            return {"action": "skip", "changed": 0}

        if not isinstance(result, dict):
            logger.warning(f"[MEMORY] Flash returned non-dict: {type(result)}")
            return {"action": "skip", "changed": 0}

        action = result.get("action", "skip")

        # Handle profile update (piggybacks on same Flash call)
        profile_changed = False
        if result.get("profile_action") == "update" and result.get("profile_md"):
            new_md = result["profile_md"].strip()
            if new_md and new_md != (current_profile or ""):
                # Check if enough fields to mark as onboarded (at least 3 meaningful lines)
                meaningful_lines = [l for l in new_md.split("\n") if l.strip() and not l.strip().startswith("#")]
                onboarded = len(meaningful_lines) >= 3
                await save_profile(client_id, user_identifier, new_md, onboarded=onboarded)
                profile_changed = True
                logger.info(f"[PROFILE] Updated via memory eval | onboarded={onboarded}")

        if action == "skip":
            return {"action": "skip" if not profile_changed else "profile_only", "changed": 1 if profile_changed else 0}

        if action == "batch":
            ops = result.get("ops", [])
            changed = 0
            for op in ops[:3]:  # Max 3 ops per batch
                changed += await _execute_op(pool, op, client_id, user_identifier)
            logger.info(f"[MEMORY] Batch: {len(ops)} ops, {changed} changes")
            return {"action": "batch", "changed": changed + (1 if profile_changed else 0)}

        changed = await _execute_op(pool, result, client_id, user_identifier)
        logger.info(f"[MEMORY] {action} | changed={changed}")
        return {"action": action, "changed": changed + (1 if profile_changed else 0)}

    except Exception as e:
        logger.error(f"[MEMORY] Evaluation failed: {e}", exc_info=True)
        return {"action": "error", "changed": 0}


async def _execute_op(pool, op: dict, client_id: str, user_identifier: str) -> int:
    """Execute a single memory operation. Returns 1 if DB changed, 0 otherwise."""
    action = op.get("action", "skip")
    logger.info(f"[MEMORY] Executing op: {action} | {op}")

    if action == "skip":
        return 0

    elif action == "add":
        mtype = op.get("memory_type", "context")
        content = op.get("content", "").strip()
        if not content:
            return 0
        # Check count before adding
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM agent_memories WHERE client_id = $1::uuid AND user_identifier = $2",
            client_id, user_identifier,
        )
        if count >= MEMORY_LIMIT:
            logger.warning(f"[MEMORY] At limit ({MEMORY_LIMIT}), skipping add without eviction")
            return 0
        await pool.execute(
            """INSERT INTO agent_memories
               (id, client_id, user_identifier, memory_type, content, metadata, created_at, updated_at)
               VALUES (gen_random_uuid(), $1::uuid, $2, $3, $4, $5::jsonb, NOW(), NOW())""",
            client_id, user_identifier, mtype, content, "{}",
        )
        return 1

    elif action == "update":
        mid = op.get("memory_id", "")
        content = op.get("content", "").strip()
        if not mid or not content:
            return 0
        mtype = op.get("memory_type")
        if mtype:
            await pool.execute(
                """UPDATE agent_memories SET content = $1, memory_type = $2, updated_at = NOW()
                   WHERE id = $3::uuid AND client_id = $4::uuid AND user_identifier = $5""",
                content, mtype, mid, client_id, user_identifier,
            )
        else:
            await pool.execute(
                """UPDATE agent_memories SET content = $1, updated_at = NOW()
                   WHERE id = $2::uuid AND client_id = $3::uuid AND user_identifier = $4""",
                content, mid, client_id, user_identifier,
            )
        return 1

    elif action == "delete":
        mid = op.get("memory_id", "")
        if not mid:
            return 0
        await pool.execute(
            "DELETE FROM agent_memories WHERE id = $1::uuid AND client_id = $2::uuid AND user_identifier = $3",
            mid, client_id, user_identifier,
        )
        return 1

    elif action == "merge":
        delete_ids = op.get("delete_ids", [])
        content = op.get("content", "").strip()
        mtype = op.get("memory_type", "context")
        if not delete_ids or not content:
            return 0
        # Delete old entries
        for did in delete_ids:
            await pool.execute(
                "DELETE FROM agent_memories WHERE id = $1::uuid AND client_id = $2::uuid AND user_identifier = $3",
                did, client_id, user_identifier,
            )
        # Insert merged
        await pool.execute(
            """INSERT INTO agent_memories
               (id, client_id, user_identifier, memory_type, content, metadata, created_at, updated_at)
               VALUES (gen_random_uuid(), $1::uuid, $2, $3, $4, '{}'::jsonb, NOW(), NOW())""",
            client_id, user_identifier, mtype, content,
        )
        return 1 + len(delete_ids)

    elif action == "add_and_evict":
        evict_id = op.get("evict_id", "")
        content = op.get("content", "").strip()
        mtype = op.get("memory_type", "context")
        if not content:
            return 0
        if evict_id:
            await pool.execute(
                "DELETE FROM agent_memories WHERE id = $1::uuid AND client_id = $2::uuid AND user_identifier = $3",
                evict_id, client_id, user_identifier,
            )
        await pool.execute(
            """INSERT INTO agent_memories
               (id, client_id, user_identifier, memory_type, content, metadata, created_at, updated_at)
               VALUES (gen_random_uuid(), $1::uuid, $2, $3, $4, '{}'::jsonb, NOW(), NOW())""",
            client_id, user_identifier, mtype, content,
        )
        return 2 if evict_id else 1

    return 0


# ── Load & Inject ──────────────────────────────────────────────────────


async def load_memories(client_id: str, user_identifier: str, limit: int = 30) -> list[dict]:
    """Load memories for a user, including shared memories for the same client.

    Returns list of {id, memory_type, content} dicts, most recent first.
    """
    from database import get_pool
    pool = await get_pool()

    rows = await pool.fetch(
        """SELECT id, memory_type, content FROM agent_memories
           WHERE client_id = $1::uuid
             AND (user_identifier = $2 OR shared = true)
           ORDER BY updated_at DESC
           LIMIT $3""",
        client_id, user_identifier, limit,
    )

    return [{"id": str(r["id"]), "memory_type": r["memory_type"], "content": r["content"]} for r in rows]


async def get_memory_count(client_id: str, user_identifier: str) -> int:
    """Get count of memories for toolbar display."""
    from database import get_pool
    pool = await get_pool()
    return await pool.fetchval(
        """SELECT COUNT(*) FROM agent_memories
           WHERE client_id = $1::uuid AND (user_identifier = $2 OR shared = true)""",
        client_id, user_identifier,
    ) or 0


def build_memory_context(memories: list[dict]) -> str:
    """Format loaded memories into a context string for system prompt injection.

    Returns empty string if no memories.
    """
    if not memories:
        return ""

    parts = ["[用户记忆]"]
    for mem in memories:
        mtype = mem.get("memory_type", "")
        content = mem.get("content", "")
        if mtype == "preference":
            parts.append(f"- 偏好: {content}")
        elif mtype == "fact":
            parts.append(f"- 事实: {content}")
        elif mtype == "context":
            parts.append(f"- 背景: {content}")
        else:
            parts.append(f"- {content}")

    return "\n".join(parts)
