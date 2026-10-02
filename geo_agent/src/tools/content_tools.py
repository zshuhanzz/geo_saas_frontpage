"""
Tier 1 Atomic Content Tools for geo_agent — Action Agent.

Generates GEO-optimized content (FAQ, etc.) using the RAFT methodology:
  R — Readability: clear structure, machine-parseable, short sentences
  A — Answerability: directly answers user search intent, Q&A format
  F — (Trustworthiness): E-E-A-T aligned, authoritative, data-backed
  T — Timeliness: current data, dated references, freshness signals

All content generation uses Gemini Pro with brand profile injection.
"""
import json
import logging
from typing import Any, Optional
from langchain_core.tools import tool
from google.genai import types

from llm.client import get_genai_client, get_model_id

logger = logging.getLogger(__name__)

FAQ_SYSTEM_PROMPT = """You are an expert GEO (Generative Engine Optimization) content strategist.
Your task is to generate FAQ content that is optimized for being cited by AI search engines
(ChatGPT, Gemini, AI Mode).

You MUST follow the RAFT methodology for every piece of content:

## R — Readability
- Use clear, concise sentences (under 25 words each)
- Structure with proper headings and bullet points
- Each answer should be self-contained and independently understandable
- Use bold for key terms that AI engines should pick up

## A — Answerability
- Each FAQ must directly answer a real search intent
- The question should match how users actually phrase queries to AI engines
- The answer must start with a direct response in the first sentence
- Include specific details (numbers, names, comparisons) rather than vague statements

## F — Trustworthiness (E-E-A-T)
- Demonstrate expertise by including specific technical details or data points
- Reference authoritative sources where applicable
- Use professional, authoritative tone aligned with the brand's voice
- Include verifiable claims rather than subjective opinions

## T — Timeliness
- Include time-relevant context (e.g. "as of 2026", "latest generation")
- Reference recent developments, updates, or trends when applicable
- Avoid language that will age poorly (e.g. "recently" without context)

{brand_context}

## Output Format
Return a JSON object with this structure:
{{
  "topic": "The topic/category of this FAQ set",
  "faqs": [
    {{
      "question": "The FAQ question matching a real search intent",
      "answer": "The optimized answer (2-4 sentences, direct and specific)",
      "search_intent": "The AI search query this FAQ targets",
      "schema_type": "FAQPage"
    }}
  ],
  "raft_scores": {{
    "readability": {{"score": 1-5, "note": "brief assessment"}},
    "answerability": {{"score": 1-5, "note": "brief assessment"}},
    "trustworthiness": {{"score": 1-5, "note": "brief assessment"}},
    "timeliness": {{"score": 1-5, "note": "brief assessment"}},
    "overall": 1-5
  }},
  "improvement_suggestions": ["suggestion 1", "suggestion 2"]
}}

Generate {count} FAQ items for the given topic."""


def _build_brand_context(brand_profile: Optional[dict]) -> str:
    """Build brand context string for injection into content generation prompt."""
    if not brand_profile:
        return ""
    parts = ["## Brand Profile (match this voice in all content)"]
    if brand_profile.get("brand_name"):
        parts.append(f"- Brand: {brand_profile['brand_name']}")
    if brand_profile.get("tone_of_voice"):
        parts.append(f"- Tone: {brand_profile['tone_of_voice']}")
    if brand_profile.get("target_audience"):
        parts.append(f"- Target audience: {brand_profile['target_audience']}")
    if brand_profile.get("key_messages"):
        msgs = brand_profile["key_messages"]
        if isinstance(msgs, list):
            parts.append(f"- Key messages: {', '.join(msgs)}")
    if brand_profile.get("brand_values"):
        vals = brand_profile["brand_values"]
        if isinstance(vals, list):
            parts.append(f"- Brand values: {', '.join(vals)}")
    return "\n".join(parts)


@tool
async def faq_generator(
    topic: str,
    client_id: str,
    brand_profile: Optional[dict] = None,
    count: int = 5,
    language: str = "en",
    context_data: Optional[dict] = None,
) -> dict:
    """Generate GEO-optimized FAQ content for a given topic.

    Uses the RAFT methodology (Readability, Answerability, Trustworthiness,
    Timeliness) to produce FAQ content that AI search engines are more likely
    to cite.

    Args:
        topic: The topic or category to generate FAQs for (e.g. "robot vacuum pet hair").
        client_id: The tenant's client UUID.
        brand_profile: Brand profile dict with tone_of_voice, key_messages, etc.
        count: Number of FAQ items to generate (default 5, max 10).
        language: Output language (e.g. "en", "zh-CN").
        context_data: Optional real data from Analyze tools to inject timeliness signals.
    """
    count = min(count, 10)
    brand_context = _build_brand_context(brand_profile)

    system_prompt = FAQ_SYSTEM_PROMPT.format(
        brand_context=brand_context,
        count=count,
    )

    # Build user prompt with topic + optional data context
    user_parts = [f"Generate {count} FAQ items about: {topic}"]
    if language and language != "en":
        user_parts.append(f"Output language: {language}")
    if context_data:
        user_parts.append(
            f"Current brand data for timeliness (use these real numbers where relevant):\n"
            f"{json.dumps(context_data, ensure_ascii=False, default=str)}"
        )

    user_prompt = "\n\n".join(user_parts)

    model_id = await get_model_id("pro")
    client = await get_genai_client(model_id, role="pro")

    response = await client.aio.models.generate_content(
        model=model_id,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.4,
            max_output_tokens=4096,
        ),
    )

    try:
        result = json.loads(response.text)
    except (json.JSONDecodeError, TypeError):
        logger.error(f"[FAQ] Failed to parse response: {response.text[:200]}")
        result = {
            "topic": topic,
            "faqs": [],
            "raft_scores": {},
            "error": "Failed to generate valid FAQ content",
        }

    result["content_type"] = "faq"
    result["client_id"] = client_id
    logger.info(f"[FAQ] Generated {len(result.get('faqs', []))} FAQs for topic: {topic}")
    return result
