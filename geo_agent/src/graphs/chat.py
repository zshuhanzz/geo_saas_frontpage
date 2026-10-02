"""
General Chat Sub-graph.

Simple conversational agent using Gemini Flash. No tools —
just friendly conversation with GEO domain knowledge.
Injects client name and brand profile into the system prompt.
"""
import json
import logging
from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage, HumanMessage
from google.genai import types

from models.state import BaseAgentState
from llm.client import get_genai_client, get_model_id, generate_content
from context.pruner import get_prune_max_turns, prune_messages

logger = logging.getLogger(__name__)

CHAT_SYSTEM_TEMPLATE = """You are Anthony, the AI assistant for AnswerX GEO (Generative Engine Optimization) platform.
You help Chinese overseas brands (出海品牌) understand and improve their visibility across AI search engines
like ChatGPT, Gemini, and AI Mode.

## What you CAN do
- Greet users warmly and introduce yourself
- Explain what you can do: analyze brand performance data, generate optimized content, answer GEO questions
- Discuss GEO concepts (Share of Voice, citations, sentiment, AI search engines)
- Explain brand visibility optimization strategies
- Describe the AnswerX platform's features and capabilities
- Guide users on how to use the platform's Analyze and Content features

## What you MUST NOT do
- Answer questions unrelated to GEO, brand optimization, or the AnswerX platform
- Provide coding help, math solutions, recipes, travel advice, or any non-GEO topic
- If a user asks something off-topic, politely redirect them:
  "这个问题超出了我的专业范围。我专注于帮助品牌优化在 AI 搜索引擎中的表现，有什么 GEO 相关的问题我可以帮到你吗？"

## Response style
- When users ask questions that require data analysis (visibility, citations, sentiment),
  suggest they use the Analyze feature (分析功能) for detailed data insights.
- When users want to create content, suggest they use the Content feature (内容创作).
- Respond in the same language as the user's message.

{brand_context}"""


def _build_system_prompt(state: BaseAgentState) -> str:
    """Build system prompt with optional brand context injection."""
    parts = []
    client_name = state.get("client_name", "")
    if client_name:
        parts.append(f"Current client: {client_name}")

    bp = state.get("brand_profile")
    if bp:
        if bp.get("brand_name"):
            parts.append(f"Brand: {bp['brand_name']}")
        if bp.get("tone_of_voice"):
            parts.append(f"Brand tone: {bp['tone_of_voice']}")
        if bp.get("target_audience"):
            parts.append(f"Target audience: {bp['target_audience']}")
        if bp.get("key_messages"):
            msgs = bp["key_messages"]
            if isinstance(msgs, list):
                parts.append(f"Key messages: {', '.join(msgs)}")

    # Inject cross-session memory if available
    if bp and bp.get("_memory_context"):
        parts.append(f"\n{bp['_memory_context']}")

    brand_context = "\n".join(parts) if parts else ""
    return CHAT_SYSTEM_TEMPLATE.format(brand_context=brand_context)


async def chat_node(state: BaseAgentState) -> dict:
    """Generate a conversational response using Gemini Flash."""
    model_id = await get_model_id("flash")
    client = await get_genai_client(model_id, role="flash")

    system_prompt = _build_system_prompt(state)

    # Build conversation history. Prune to the last N turns before sending to
    # the LLM — checkpoint state still holds the full history for UI replay.
    pruned = prune_messages(state["messages"], max_turns=await get_prune_max_turns())
    contents = []
    for msg in pruned:
        if isinstance(msg, HumanMessage):
            contents.append(types.Content(role="user", parts=[types.Part(text=msg.content)]))
        elif isinstance(msg, AIMessage):
            contents.append(types.Content(role="model", parts=[types.Part(text=msg.content)]))

    response = await generate_content(
        client, model_id,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )

    reply = response.text or ""
    return {"messages": [AIMessage(content=reply)]}


def build_chat_graph() -> StateGraph:
    """Build and return the General Chat sub-graph (uncompiled)."""
    graph = StateGraph(BaseAgentState)

    graph.add_node("chat", chat_node)
    graph.set_entry_point("chat")
    graph.add_edge("chat", END)

    return graph
