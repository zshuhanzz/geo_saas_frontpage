"""
User Profile — one Markdown document per user per client workspace.

Stores free-form user info (role, preferences, KPIs, language, response style).
On cold-start (no profile yet), the Supervisor is instructed to gently interview
the user to gather basic preferences.

Profile updates happen inside the same Flash call that evaluates memories,
so there is zero extra LLM cost for profile management.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def load_profile(client_id: str, user_identifier: str) -> Optional[str]:
    """Load the user's Markdown profile. Returns None if no profile exists."""
    from database import get_pool
    pool = await get_pool()

    row = await pool.fetchrow(
        """SELECT profile_md, onboarded FROM agent_user_profiles
           WHERE client_id = $1::uuid AND user_identifier = $2""",
        client_id, user_identifier,
    )
    if row and row["profile_md"]:
        return row["profile_md"]
    return None


async def is_onboarded(client_id: str, user_identifier: str) -> bool:
    """Check if user has completed cold-start interview."""
    from database import get_pool
    pool = await get_pool()

    val = await pool.fetchval(
        """SELECT onboarded FROM agent_user_profiles
           WHERE client_id = $1::uuid AND user_identifier = $2""",
        client_id, user_identifier,
    )
    return bool(val)


async def save_profile(client_id: str, user_identifier: str, profile_md: str, onboarded: Optional[bool] = None):
    """Upsert the user profile Markdown document."""
    from database import get_pool
    pool = await get_pool()

    if onboarded is not None:
        await pool.execute(
            """INSERT INTO agent_user_profiles (id, client_id, user_identifier, profile_md, onboarded, created_at, updated_at)
               VALUES (gen_random_uuid(), $1::uuid, $2, $3, $4, NOW(), NOW())
               ON CONFLICT (client_id, user_identifier) DO UPDATE
               SET profile_md = $3, onboarded = $4, updated_at = NOW()""",
            client_id, user_identifier, profile_md, onboarded,
        )
    else:
        await pool.execute(
            """INSERT INTO agent_user_profiles (id, client_id, user_identifier, profile_md, created_at, updated_at)
               VALUES (gen_random_uuid(), $1::uuid, $2, $3, NOW(), NOW())
               ON CONFLICT (client_id, user_identifier) DO UPDATE
               SET profile_md = $3, updated_at = NOW()""",
            client_id, user_identifier, profile_md,
        )

    logger.info(f"[PROFILE] Saved profile for {user_identifier[:20]}... | onboarded={onboarded}")


def build_profile_context(profile_md: Optional[str]) -> str:
    """Format user profile for system prompt injection."""
    if not profile_md:
        return ""
    return f"[用户档案]\n{profile_md}"


# ── Cold-Start Interview System Prompt Addition ────────────────────────

COLD_START_INSTRUCTION = """
[新用户引导]
当前用户尚未建立个人档案。请在回答用户问题的同时，自然地引导用户分享以下信息。
不要像问卷一样连续提问。如果用户直接提出了分析请求，先回答请求，然后在对话间隙自然地引导 1-2 个问题。

必问（温和引导）：
- 你希望 Agent 用什么语言回复？（中文/英文/自动匹配）
- 你在 GEO 优化中最关注哪些方面？（可见度/引用/情感/内容策略/全部）
- 你希望分析结果的详细程度？（简洁概要 / 详细分析 / 适中）

选问（如果用户主动提及或时机合适）：
- 你的角色或职责是什么（不要主动追问全名）
- 你当前最重要的 KPI 或 OKR 是什么
- 你对 AI 搜索引擎优化最关心的核心问题
- 你希望 Agent 的回复风格（简洁直接 / 详尽全面 / 适中）

注意事项：
- 保持温和、专业、不要过于探询个人信息
- 用户的公司信息已知（可通过系统获取），无需询问
- 收集到的信息会自动保存到用户档案中，用于个性化后续对话
- 当累积了足够信息后，会自动完成引导流程
""".strip()


# ── Evaluate profile update (called alongside memory evaluation) ───────

PROFILE_EVALUATE_ADDITION = """
Additionally, evaluate if the user's message contains USER PROFILE information
(identity, role, language preference, response style preference, GEO focus areas, KPIs).

If profile update is needed, add to your response:
"profile_action": "update",
"profile_md": "<complete updated Markdown profile document>"

The current user profile is:
{current_profile}

If updating, output the COMPLETE profile document (not just the diff).
Use Markdown format with sections like:
## 基本信息
- 语言偏好: 中文
- 回复风格: 详细

## GEO 关注点
- 核心关注: 可见度、引用
- KPI: ...

## 偏好设置
- 分析深度: 详细
- 图表偏好: ...

If no profile update needed, omit profile_action entirely.
""".strip()
