"""
Supervisor Graph.

Top-level LangGraph graph that classifies user intent and routes to
the appropriate sub-graph: Analyze Agent, Action Agent, or General Chat.

Uses Gemini Flash for fast intent classification.
"""
import json
import logging
from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage, HumanMessage
from google.genai import types

from models.state import SupervisorState
from llm.client import get_genai_client, get_model_id, generate_content
from graphs.analyze import build_analyze_graph
from graphs.action import build_action_graph
from graphs.chat import build_chat_graph

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT = """Classify the user's LATEST message into exactly one category,
considering the recent conversation context below.

Categories:
- analyze: wants data, metrics, trends, comparisons, charts about brand visibility/citations/sentiment in AI search engines
- action: wants to generate content like FAQs, articles, recommendations, or content briefs
- chat: greeting, self-introduction, asking what you can do, discussing GEO/AnswerX platform capabilities, general GEO conversation, expressing preferences or style requests (e.g. "我偏好简洁的分析", "以后用概要风格"), sharing personal info (e.g. role, team, background), or any conversational message about how they want to interact
- off_topic: anything unrelated to GEO, brand optimization, or the AnswerX platform (e.g. coding help, math problems, recipes, weather, news, personal advice)
- system_command: user explicitly invokes a slash command or system operation (e.g. "/compress", "/model flash", "压缩对话", "切换模型", "清空对话"). Must be an explicit system control request, NOT a preference or style statement

Recent conversation:
{context}

Latest message: {message}

Reply with ONLY the category name (analyze, action, chat, off_topic, or system_command), nothing else.
Category:"""

OFF_TOPIC_RESPONSE = (
    "抱歉，我是 AnswerX GEO 平台的 AI 助手 Anthony，"
    "专注于帮助出海品牌优化在 AI 搜索引擎中的可见度和引用表现。\n\n"
    "我可以帮你：\n"
    "- 📊 **分析品牌表现** — 查看可见度、引用、情感趋势数据\n"
    "- ✍️ **生成优化内容** — 创建 FAQ、文章、内容策略\n"
    "- 💬 **解答 GEO 问题** — 了解平台功能和优化方法\n\n"
    "请问有什么 GEO 相关的问题我可以帮到你？"
)

# Map entry_point values to locked intents
_ENTRY_POINT_INTENT = {
    "content": "action",
    "analysis": "analyze",
}


async def classify_intent(state: SupervisorState) -> dict:
    """Classify the user's latest message intent using Gemini Flash.

    Three layers of short-circuiting before LLM classification:
    1. entry_point hard constraint — Content/Analysis entries lock intent
    2. Widget response — reuse existing intent (JSON payloads misroute)
    3. Slot-filling in progress — reuse existing intent (user is answering
       questions, not expressing a new intent)

    When LLM classification is needed (free chat), the prompt includes the
    last 3 turns of conversation for context-aware routing.
    """
    # ── Layer 1: entry_point hard constraint ──────────────────
    entry_point = state.get("entry_point", "")
    locked_intent = _ENTRY_POINT_INTENT.get(entry_point)
    if locked_intent:
        logger.info(f"[SUPERVISOR] entry_point={entry_point} → locked intent: {locked_intent}")
        return {"intent": locked_intent}

    # ── Extract latest user message ───────────────────────────
    user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    # ── Layer 2: Widget response → reuse intent ───────────────
    try:
        parsed = json.loads(user_message)
        if parsed.get("type") == "widget_response":
            existing_intent = state.get("intent", "")
            if existing_intent:
                logger.info(f"[SUPERVISOR] Widget response — reusing intent: {existing_intent}")
                return {"intent": existing_intent}
    except (json.JSONDecodeError, TypeError):
        pass

    # ── Layer 3: Slot-filling in progress → reuse intent ──────
    existing_intent = state.get("intent", "")
    task_inputs = state.get("task_inputs") or {}
    task_ready = state.get("task_ready", False)
    if task_inputs and not task_ready and existing_intent in ("analyze", "action"):
        logger.info(f"[SUPERVISOR] Slot-filling active (task_inputs={list(task_inputs.keys())}) — reusing intent: {existing_intent}")
        return {"intent": existing_intent}

    # ── Layer 4: LLM classification with recent context ───────
    # Build context from last 3 turns (6 messages: human+ai pairs)
    recent_msgs = state["messages"][-6:] if len(state["messages"]) > 6 else state["messages"]
    context_lines = []
    for msg in recent_msgs:
        role = "User" if isinstance(msg, HumanMessage) else "Agent"
        text = (msg.content or "")[:200] if hasattr(msg, "content") else ""
        if text:
            context_lines.append(f"{role}: {text}")
    context = "\n".join(context_lines) if context_lines else "(new conversation)"

    model_id = await get_model_id("flash")
    client = await get_genai_client(model_id, role="flash")

    prompt = CLASSIFIER_PROMPT.format(context=context, message=user_message)

    response = await generate_content(
        client, model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=256,
        ),
    )

    raw = (response.text or "").strip().lower()
    if raw in ("analyze", "action", "chat", "off_topic", "system_command"):
        intent = raw
    elif "analyze" in raw:
        intent = "analyze"
    elif "action" in raw:
        intent = "action"
    elif "off_topic" in raw:
        intent = "off_topic"
    elif "system_command" in raw:
        intent = "system_command"
    else:
        intent = "chat"

    logger.info(f"[SUPERVISOR] Intent classified: {intent} (context_turns={len(context_lines)}, message: {user_message[:60]})")

    # ── Clear stale slot-filling state when intent changes ────
    # If the user switches from analyze to action (or vice versa),
    # old task_inputs would pollute the new flow.
    result = {"intent": intent}
    if existing_intent and existing_intent != intent and existing_intent in ("analyze", "action"):
        logger.info(f"[SUPERVISOR] Intent changed {existing_intent} → {intent}, clearing stale task_inputs")
        result["task_inputs"] = {}
        result["task_ready"] = False

    return result


def route_by_intent(state: SupervisorState) -> str:
    """Route to the appropriate sub-graph based on classified intent."""
    intent = state.get("intent", "chat")
    if intent == "analyze":
        return "analyze"
    if intent == "action":
        return "action"
    if intent == "off_topic":
        return "off_topic"
    if intent == "system_command":
        return "system_command"
    return "chat"


async def off_topic_node(state: SupervisorState) -> dict:
    """Return a hardcoded off-topic response without calling any LLM."""
    return {"messages": [AIMessage(content=OFF_TOPIC_RESPONSE)]}


SYSTEM_COMMAND_RESPONSE = (
    "好的，我理解你想执行一个系统操作。你可以使用以下快捷命令：\n\n"
    "- `/compress` — 压缩当前对话上下文\n"
    "- `/model flash` 或 `/model pro` — 切换 AI 模型\n"
    "- `/status` — 查看当前会话状态\n"
    "- `/memories` — 查看已保存的记忆\n\n"
    "你也可以直接点击对话框上方工具栏中的对应按钮来操作。"
)


async def system_command_node(state: SupervisorState) -> dict:
    """Guide user to use slash commands or toolbar buttons for system operations."""
    return {"messages": [AIMessage(content=SYSTEM_COMMAND_RESPONSE)]}


def build_supervisor_graph() -> StateGraph:
    """Build the top-level Supervisor graph with sub-graph routing."""
    analyze_graph = build_analyze_graph().compile()
    action_graph = build_action_graph().compile()
    chat_graph = build_chat_graph().compile()

    graph = StateGraph(SupervisorState)

    graph.add_node("classify", classify_intent)
    graph.add_node("analyze", analyze_graph)
    graph.add_node("action", action_graph)
    graph.add_node("chat", chat_graph)
    graph.add_node("off_topic", off_topic_node)
    graph.add_node("system_command", system_command_node)

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        route_by_intent,
        {"analyze": "analyze", "action": "action", "chat": "chat", "off_topic": "off_topic", "system_command": "system_command"},
    )
    graph.add_edge("analyze", END)
    graph.add_edge("action", END)
    graph.add_edge("chat", END)
    graph.add_edge("off_topic", END)
    graph.add_edge("system_command", END)

    return graph
