"""
Fusion meta-prompt construction for FinalPromptBuilder.

Pure-function module: takes a base client_prompt + persona + platform context +
intent and produces the textual instruction sent to Gemini for query
diversification. Split out of `prompt_expander.py` in Phase 2.5a so the
orchestration stays focused on DB/Pub/Sub I/O while the prompt-engineering
content lives next to it but separately reviewable.

No imports from `src.core.database` or any I/O layer — this module is safe to
import in isolation (e.g. for prompt-engineering experiments).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional


def build_fusion_instruction(
    client_prompt_text: str,
    persona: Optional[str] = None,
    platform_instructions: Optional[str] = None,
    intent: Optional[str] = None,
    n: int = 1,
) -> str:
    """
    Build the meta-prompt that instructs Gemini to create N diverse search
    query variants of `client_prompt_text`.

    Intent gates which guidance block to inject (Solution Discovery vs
    Competitive Evaluation vs Specifics Inquiry). Persona, platform
    instructions, and intent are all optional; missing pieces simply omit
    their respective sections.
    """
    parts: list[str] = [
        "You are a search query diversifier for configured AI search engines.",
        "Your task is to create diverse NATURAL LANGUAGE QUESTION variants of a base query.",
        "The best Final Prompt is a LIGHTWEIGHT rewrite: stay close to the base query, preserve the original category, and avoid over-specializing the situation.",
        "The first priority is a stable baseline visibility probe, not maximum query diversity.",
        "",
        "Base query:",
        f'  "{client_prompt_text}"',
    ]
    persona_for_variants = persona if persona and n >= 2 else None
    if persona_for_variants:
        parts.append(f"User persona: {persona_for_variants}")
    if platform_instructions:
        parts.append(f"Platform context: {platform_instructions}")

    if intent:
        parts.extend(_intent_block(intent))

    if persona_for_variants:
        parts.extend(_persona_block(persona_for_variants, n))

    parts.extend(_strict_rules_block(n))
    return "\n".join(parts)


def simple_concat(
    client_prompt_text: str,
    persona: Optional[str] = None,
    platform_instructions: Optional[str] = None,
) -> str:
    """
    Fallback when LLM fusion is unavailable: prefix the platform's system
    instructions onto the raw client prompt. Persona is intentionally NOT
    inlined — the LLM-less path is meant to be a faithful passthrough, not a
    half-rewritten variant.
    """
    text = client_prompt_text.strip()
    if platform_instructions:
        text = platform_instructions.strip() + " " + text
    return text


# ---------------------------------------------------------------------------
# Intent-, persona- and rules-block helpers. Extracted as private functions so
# the public `build_fusion_instruction` reads as a flat assembly.
# ---------------------------------------------------------------------------


def _intent_block(intent: str) -> list[str]:
    intent_lower = intent.lower()
    if "solution" in intent_lower or "discovery" in intent_lower:
        return [
            "",
            f"Intent: {intent} — This is a RECOMMENDATION-SEEKING query.",
            "Each variant must keep the same recommendation/verdict intent using patterns like:",
            '  - "What\'s the best X for [situation]?"',
            '  - "What X do people/experts recommend for [need]?"',
            '  - "Top X for [use case]?"',
            "DO NOT include any brand names in the variants.",
            "Do not turn a broad query into a much narrower channel, industry, buyer type, or workflow unless the base query or persona clearly requires it.",
        ]
    if "compet" in intent_lower or "evaluat" in intent_lower:
        return [
            "",
            f"Intent: {intent} — This is a VERDICT-SEEKING COMPARISON query.",
            "Each variant must ask for a verdict between alternatives:",
            '  - "Is X or Y better for [specific situation]?"',
            '  - "Should I buy X or Y if I need [requirement]?"',
            "Comparisons must seek a verdict, NOT explain differences.",
            "You MUST keep the client brand/product name AND the competitor brand/product name from the base query.",
            "NEVER replace brand names with generic category names.",
        ]
    if "specific" in intent_lower or "inquiry" in intent_lower:
        return [
            "",
            f"Intent: {intent} — This is a FEATURE-SPECIFIC RECOMMENDATION query.",
            "Each variant must ask for a recommendation about a specific feature/spec:",
            '  - "Is the [product]\'s [feature] good enough for [situation]?"',
            '  - "Which features of [product] make it worth recommending for [use case]?"',
            "NEVER frame as 'how does X work' — always frame as a recommendation.",
            "You MUST keep the specific product name from the base query. DO NOT add competitor brand names.",
            "NEVER replace brand/product names with generic category names.",
        ]
    return []


def _persona_block(persona: str, n: int) -> list[str]:
    sequencing_rules = [
        "Persona sequencing:",
        "  - Variant 1 must be a baseline rewrite with no persona injection.",
        "  - Variant 2 may lightly reflect the persona only if it still preserves the original question.",
    ]
    if n >= 3:
        sequencing_rules.append(
            "  - Some variants should not use persona; keep at least one non-persona baseline-style variant."
        )
    return [
        "",
        "PERSONA INTEGRATION:",
        f"The user persona is: {persona}",
        "Reflect this persona's perspective lightly and naturally when it improves realism:",
        "  - Persona is more important than adding arbitrary use-case, location, budget, or year modifiers",
        "  - Use vocabulary relevant to this persona without changing the core category or recommendation target",
        "  - If persona details would distort the base query, keep the base query closer instead",
        *sequencing_rules,
    ]


def _strict_rules_block(n: int) -> list[str]:
    current_year = datetime.now().year
    return [
        "",
        "STRICT Rules:",
        f"1. Generate exactly {n} unique query variants as a JSON array of strings",
        "2. Each variant must use the same language as the base query. Do not translate Chinese queries into English or English queries into Chinese. This is independent of country, market, or platform.",
        "3. Each variant MUST be a complete, natural language QUESTION; aim for 12-40 words and avoid unnecessary length",
        "4. Do not make a short base query substantially longer; prefer similar or shorter length when the original query is already natural",
        "5. Write full conversational questions, NOT keyword phrases or fragments",
        "6. Each variant must be a light rephrase of the base query with different wording, angle, or emphasis",
        "7. Maintain the same core search intent — the user wants the same type of answer",
        "8. Do not add location, budget, or highly specific use cases unless the base query or persona naturally calls for them",
        f"9. If a year is genuinely needed, use the current year ({current_year}) or preserve the year already present in the base query",
        "10. Do not invent stale or past years, especially older years that would bias recommendations toward outdated tools",
        "",
        "Good examples (natural language questions):",
        '- "What\'s the best robot vacuum for homes with pets and hardwood floors?"',
        '- "Which robot vacuum do cleaning professionals recommend for reliable daily cleaning?"',
        '- "Is a hybrid mop-vacuum robot worth it for small apartments?"',
        "",
        "Bad examples (keyword phrases — do NOT generate these):",
        '- "best robot vacuum multi-floor 2026"',
        '- "robot vacuum pet hair comparison reviews"',
        '- "top rated vacuum mop combo apartments"',
        "",
        f"Output: Return a JSON array of exactly {n} strings.",
        f'Example: ["What\'s the best...", "Which X do..."]',
    ]
