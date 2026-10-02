"""
Brainstorming Router (V2.5 SaaS) - SSE streaming endpoint for AI-generated prompt suggestions.

Redesigned to support:
- Multi-select Topics & Products
- Multi-select Countries & Languages  
- Parallel Gemini calls per (topic, product, country, language) combination
- prompts_per_product evenly distributed across country × language combos
"""
import asyncio
import json
import logging
import math
from typing import Optional, List, Dict
from uuid import UUID
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from geo_common.llm import MODEL_REGION_OVERRIDES_KEY, resolve_model_region

from db import database

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request Model
# ---------------------------------------------------------------------------

class TopicSelection(BaseModel):
    topic_id: UUID
    product_names: List[str] = []  # selected products within this topic

class BrainstormRequest(BaseModel):
    client_id: UUID
    topics: List[TopicSelection]
    prompts_per_product: Optional[int] = 10
    countries: List[str] = ["US"]
    language: str = "en-US"  # Single-select (different languages = different text)
    platforms: List[str] = []
    # v1.2 (Spec §8 / Plan Phase 3.5): when False the brainstorm prompts are
    # generated at topic granularity only — no product names are referenced
    # in the LLM prompt and ``client_prompts.product`` is written NULL.
    include_products: bool = True


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

# Streaming response — response_model= incompatible with StreamingResponse
@router.post("/generate")
async def generate_brainstorm_prompts(data: BrainstormRequest):
    """
    Generate candidate prompts via SSE streaming with parallel Gemini calls.

    Streams JSON events:
    - {"type": "prompt", "index": N, "text": "...", "intent": "...",
       "topic_id": "...", "topic_name": "...", "product": "...",
       "country": "...", "language": "..."}
    - {"type": "done", "total": N}
    - {"type": "error", "message": "..."}
    """
    # ------ Load client ------
    client = await database.fetch_one(
        "SELECT id, name FROM geo_clients WHERE id = :client_id",
        {"client_id": data.client_id},
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # ------ Load all selected topics ------
    topic_map: Dict[str, dict] = {}
    for ts in data.topics:
        topic = await database.fetch_one(
            """
            SELECT id, topic_name
            FROM geo_client_topics
            WHERE id = :topic_id AND client_id = :client_id
            """,
            {"topic_id": ts.topic_id, "client_id": data.client_id},
        )
        if not topic:
            raise HTTPException(status_code=404, detail=f"Topic {ts.topic_id} not found")

        # v1.2: Products moved out of geo_client_topics.products TEXT[] into
        # the structured geo_client_topic_products table. Read the Own
        # products (product_role='own') for this topic.
        own_product_rows = await database.fetch_all(
            """
            SELECT product_name
            FROM geo_client_topic_products
            WHERE topic_id = :topic_id
              AND client_id = :client_id
              AND product_role = 'own'
              AND is_active = TRUE
            """,
            {"topic_id": ts.topic_id, "client_id": data.client_id},
        )
        default_products = [r["product_name"] for r in own_product_rows]

        topic_map[str(ts.topic_id)] = {
            "topic_name": topic["topic_name"],
            "products": ts.product_names or default_products,
        }

    # ------ Load peers ------
    peers_rows = await database.fetch_all(
        """
        SELECT primary_name
        FROM geo_client_peers
        WHERE client_id = :client_id
        """,
        {"client_id": data.client_id},
    )
    peers = [p["primary_name"] for p in peers_rows]

    # ------ Load model ID ------
    model_row = await database.fetch_one(
        """
        SELECT value
        FROM geo_global_settings
        WHERE key = 'brainstorming_model_id'
        """
    )
    model_id = model_row["value"] if model_row else "gemini-3-flash-preview"
    model_region_row = await database.fetch_one(
        """
        SELECT value
        FROM geo_global_settings
        WHERE key = :key
        """,
        {"key": MODEL_REGION_OVERRIDES_KEY},
    )
    model_region_overrides = model_region_row["value"] if model_region_row else None

    # ------ Load intent allocations ------
    intents_rows = await database.fetch_all(
        """
        SELECT intent_name, allocation_ratio
        FROM geo_global_intents
        WHERE is_active = TRUE
        """
    )

    # ------ Build call plan ------
    # Generate prompts_per_product prompts per (topic, product, language).
    # Platform and country are multi-select: the same text is saved for each combo.
    per_product_total = data.prompts_per_product or 10
    language = data.language or "en-US"

    call_plan = []  # List of dicts describing each Gemini call
    for ts in data.topics:
        tid = str(ts.topic_id)
        topic_info = topic_map[tid]

        # v1.2: when include_products=False, collapse to one call per topic
        # with the empty product placeholder. The LLM template sees topic-only
        # prompts and the saved prompts carry product=NULL (downstream
        # client_prompts.product write site must respect this).
        if not data.include_products:
            products = [""]
        else:
            products = topic_info["products"] if topic_info["products"] else [""]

        for product in products:
            intent_alloc = _compute_intent_allocations(intents_rows, per_product_total)
            call_plan.append({
                "topic_id": tid,
                "topic_name": topic_info["topic_name"],
                "product": product,
                "country": data.countries[0] if data.countries else "US",  # hint for AI context
                "language": language,
                "count": per_product_total,
                "intent_allocations": intent_alloc,
                "platforms": data.platforms,
                "countries": data.countries,
                # Surfaced to the SSE client so a save-to-DB layer knows to
                # write NULL into client_prompts.product.
                "include_products": data.include_products,
            })

    # ------ SSE streaming with parallel Gemini calls ------
    async def event_stream():
        try:
            from google import genai
            from google.genai import types
            import os
            import google.auth

            project_id = os.getenv("GCP_PROJECT_ID")
            region = resolve_model_region(
                model_id,
                overrides_value=model_region_overrides,
                default_region=os.getenv("GCP_REGION", "us-central1"),
                global_region=os.getenv("GCP_REGION_GLOBAL", "global"),
            )
            if not project_id:
                try:
                    _, project_id = google.auth.default()
                except Exception:
                    pass
            if not project_id:
                raise RuntimeError("GCP_PROJECT_ID is not set.")

            genai_client = genai.Client(vertexai=True, project=project_id, location=region)
            gen_config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.9,
                max_output_tokens=8192,
            )

            # Queue for collecting results from parallel tasks
            result_queue: asyncio.Queue = asyncio.Queue()

            async def call_gemini(call_info: dict):
                """Single Gemini call for one (topic, product, country, language) combo."""
                try:
                    prompt_text = _build_brainstorm_prompt(
                        client_name=str(client["name"]),
                        peers=peers,
                        topic=call_info["topic_name"],
                        # When include_products=False, pass an empty product
                        # so the LLM template falls back to topic-only
                        # generation (no SKU-level references).
                        product=call_info["product"] if call_info.get("include_products", True) else "",
                        country=call_info["country"],
                        language=call_info["language"],
                        intent_allocations=call_info["intent_allocations"],
                        n=call_info["count"],
                    )

                    response = await genai_client.aio.models.generate_content_stream(
                        model=model_id,
                        contents=prompt_text,
                        config=gen_config,
                    )
                    accumulated = ""
                    async for chunk in response:
                        if chunk.text:
                            accumulated += chunk.text

                    result = json.loads(accumulated)
                    prompts = result if isinstance(result, list) else result.get("prompts", [])

                    for p in prompts:
                        text = p.get("text", "") if isinstance(p, dict) else str(p)
                        intent = p.get("intent", "General") if isinstance(p, dict) else "General"
                        # include_products=False ⇒ explicit null so the saver
                        # writes NULL into geo_client_prompts.product.
                        product_value = call_info["product"] if call_info.get("include_products", True) else None
                        await result_queue.put({
                            "type": "prompt",
                            "text": text,
                            "intent": intent,
                            "topic_id": call_info["topic_id"],
                            "topic_name": call_info["topic_name"],
                            "product": product_value,
                            "platforms": call_info.get("platforms", []),
                            "countries": call_info.get("countries", []),
                            "language": call_info["language"],
                        })
                except Exception as e:
                    logger.error(f"[BRAINSTORM] Gemini call failed for {call_info}: {e}")
                    await result_queue.put({
                        "type": "error",
                        "message": f"Failed for {call_info['topic_name']}/{call_info['product']}: {str(e)}"
                    })

            # Launch all calls in parallel
            tasks = [asyncio.create_task(call_gemini(cp)) for cp in call_plan]

            # Sentinel: when all tasks complete, put None
            async def sentinel():
                await asyncio.gather(*tasks)
                await result_queue.put(None)
            asyncio.create_task(sentinel())

            total = 0
            while True:
                item = await result_queue.get()
                if item is None:
                    break
                if item["type"] == "prompt":
                    total += 1
                    item["index"] = total
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'total': total})}\n\n"

        except Exception as e:
            logger.error(f"[BRAINSTORM] Generation failed: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_intent_allocations(intents_rows, count: int) -> dict:
    """Compute intent allocations for a given prompt count."""
    if not intents_rows:
        return {"General": count}
    
    total_ratio = sum(r["allocation_ratio"] for r in intents_rows)
    result = {}
    remaining = count
    sorted_intents = sorted(intents_rows, key=lambda x: x["allocation_ratio"], reverse=True)
    
    for row in sorted_intents:
        if total_ratio > 0:
            assigned = int(round(count * row["allocation_ratio"] / total_ratio))
            assigned = min(assigned, remaining)
        else:
            assigned = 0
        result[row["intent_name"]] = assigned
        remaining -= assigned
    
    if remaining > 0 and sorted_intents:
        result[sorted_intents[0]["intent_name"]] += remaining
    
    return result


def _build_brainstorm_prompt(
    client_name: str,
    peers: List[str],
    topic: str,
    product: str,
    country: str,
    language: str,
    intent_allocations: dict,
    n: int = 10,
) -> str:
    """Build the Gemini prompt for brainstorming candidate questions."""
    peers_str = ", ".join(peers) if peers else "competitors"

    # Intent-specific sentence patterns and rules
    intent_instructions = []
    for intent_name, count in intent_allocations.items():
        if count <= 0:
            continue
        if "solution" in intent_name.lower() or "discovery" in intent_name.lower():
            intent_instructions.append(
                f"- {count} queries for intent '{intent_name}': "
                f"Use patterns like 'best X for [situation]', 'what X do people recommend for...', "
                f"'top X for [persona/use-case]'. "
                f"Vary across dimensions: Use Case, Constraint (price/requirements), Authority (expert recommendations), Specificity (broad to narrow). "
                f"DO NOT include any brand names."
            )
        elif "compet" in intent_name.lower() or "evaluat" in intent_name.lower():
            if product:
                comp_rule = (
                    f"One side of every comparison MUST be the client's brand '{client_name}' or product '{product}'. "
                    f"The other side MUST be a specific competitor brand or product from this list: [{peers_str}]. "
                    f"Allow natural flexibility: sometimes use brand name (e.g., '{client_name}'), "
                    f"sometimes use specific product SKU (e.g., '{product}'), same for competitors. "
                    f"NEVER use generic category names (like '{topic}') as a substitute for a brand/product name."
                )
            else:
                comp_rule = (
                    f"One side of every comparison MUST be the client brand '{client_name}'. "
                    f"The other side MUST be a specific competitor from this list: [{peers_str}]. "
                    f"Allow natural flexibility: sometimes use brand name, sometimes specific product SKU. "
                    f"NEVER use generic category names as a substitute for a brand/product name."
                )
            intent_instructions.append(
                f"- {count} queries for intent '{intent_name}': "
                f"Use VERDICT-SEEKING comparison patterns like 'Is X or Y better for [situation]?', "
                f"'Should I buy X or Y if I need [requirement]?'. "
                f"The comparison MUST seek a verdict/recommendation, NOT an explanation of differences. "
                f"{comp_rule} "
                f"Vary across dimensions: Comparison, Constraint (budget/requirements), Authority."
            )
        elif "specific" in intent_name.lower() or "inquiry" in intent_name.lower():
            if product:
                product_rule = (
                    f"You MUST mention the client's brand '{client_name}' or product '{product}' by name. "
                    f"Allow natural flexibility: sometimes use brand name, sometimes specific product SKU. "
                    f"NEVER use generic category names (like '{topic}') as a substitute for the brand/product name. "
                    f"DO NOT mention any competitor brand names."
                )
            else:
                product_rule = (
                    f"You MUST mention the client brand '{client_name}' by name. "
                    f"NEVER use generic category names as a substitute. "
                    f"DO NOT mention any competitor brand names."
                )
            intent_instructions.append(
                f"- {count} queries for intent '{intent_name}': "
                f"Use patterns like 'Is the [product]'s [feature] good enough for [situation]?', "
                f"'Which features of [product] make it worth recommending for [use case]?'. "
                f"Focus on specific product features/specs, but ALWAYS frame as a recommendation/verdict, "
                f"NEVER as 'how does X work' or 'what should I look for'. "
                f"{product_rule} "
                f"Vary across dimensions: Specificity (feature-focused), Use Case, Constraint."
            )
        else:
            intent_instructions.append(
                f"- {count} queries for intent '{intent_name}': "
                f"Generate natural recommendation-seeking queries."
            )
    distribution_str = "\n".join(intent_instructions)

    # Language instruction
    lang_code = language.split("-")[0] if "-" in language else language
    if lang_code != "en":
        lang_instruction = f"\n7. Generate all queries in the language indicated by code '{language}' (not in English)."
    else:
        lang_instruction = "\n7. Generate all queries in English."

    # Product context
    product_context = ""
    if product:
        product_context = f"\n- Specific Product Focus: {product}"

    parts = [
        "You are a GEO (Generative Engine Optimization) strategist specializing in AI search engine visibility.",
        f"Generate {n} unique search queries that real users in {country} would type into AI search engines (ChatGPT, Gemini, AI Mode).",
        "",
        "Business Context:",
        f"- Client/Brand: {client_name}",
        f"- Competitors: {peers_str}",
        f"- Topic/Category: {topic}",
        product_context,
        f"- Target Country: {country}",
        f"- Target Language: {language}",
        "",
        "═══ COMMERCIAL INTENT ONLY (CRITICAL) ═══",
        "",
        "Every query MUST ask for a buying recommendation or verdict — NOT an explanation or education.",
        "",
        "✅ ALLOWED patterns:",
        '- "What\'s the best X for [situation]?"',
        '- "Which X do experts/people recommend for [need]?"',
        '- "Is X or Y better for [specific situation]?" (verdict-seeking comparison)',
        '- "Best X under $[price] for [use case]?"',
        '- "Top X for [persona/situation]?"',
        "",
        "❌ FORBIDDEN patterns (never use these):",
        '- "What\'s the difference between X and Y?" (informational)',
        '- "How does X work?" (educational)',
        '- "What should I look for in X?" (educational)',
        '- "What are the pros and cons of X?" (informational)',
        '- "Can you explain X?" (educational)',
        '- "Why is X better than Y?" (asks for reasoning, not a recommendation)',
        "",
        "═══ INTENT DISTRIBUTION & PATTERNS ═══",
        "",
        f"Generate exactly {n} queries with the following intent distribution and sentence patterns:",
        distribution_str,
        "",
        "═══ DIVERSITY DIMENSIONS ═══",
        "",
        "Within each intent category, systematically vary queries across these angles:",
        "- USE CASE: different scenarios/situations triggering the search",
        "- CONSTRAINT: different price points, requirements, or limitations",
        "- COMPARISON: category vs category (verdict-seeking only, for Competitive Evaluation)",
        "- AUTHORITY: expert/professional/social proof framing",
        "- SPECIFICITY: broad recommendations → 2-modifier → 3-modifier compound queries",
        "",
        "═══ RULES ═══",
        "",
        "1. Every query MUST seek a recommendation/verdict — zero informational queries",
        "2. Queries should be 10-30 words, natural conversational language (not SEO keyword phrases)",
        "3. Use complete questions, not keyword fragments",
        f"4. Generate exactly {n} queries matching the exact intent counts above",
        "5. Brand name rules: follow the brand name instructions in each intent section above",
        "6. DO NOT generate duplicate or near-duplicate queries",
        lang_instruction,
        "",
        "═══ AUDIT STEP ═══",
        "",
        "Before outputting, review each query and ask: 'Is this person asking for a buying recommendation, or just trying to learn?'",
        "If learning → rewrite as a recommendation-seeking query or replace entirely.",
        "",
        f"Output: Return a JSON array of exactly {n} objects, matching the intent counts above.",
        'Format: [{"text": "query text here", "intent": "Intent Name"}, ...]',
    ]

    return "\n".join(parts)
