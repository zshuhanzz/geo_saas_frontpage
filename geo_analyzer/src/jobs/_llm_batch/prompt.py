"""
Bilingual extraction prompt for the LLM Batch Candidate Discovery job.

The prompt is bilingual (zh + en) because customer AI-search responses can
arrive in either language. The instruction set tells Gemini Flash to:

1. Skip anything already in the configured tracking lists.
2. Classify each candidate into one of 6 ``candidate_type`` enum values.
3. Emit ONLY the JSON object — no prose, no markdown fences.
"""
from __future__ import annotations

import json
from typing import Dict, List


# Truncate the "already configured" lists in the prompt so a client with
# 5000 historical SKUs doesn't blow the prompt budget. Anything beyond cap
# becomes a "+N more" marker so Gemini knows the list is non-exhaustive.
MAX_KNOWN_ITEMS_PER_LIST = 200


def _truncate_list(items: List[str], cap: int = MAX_KNOWN_ITEMS_PER_LIST) -> List[str]:
    if len(items) <= cap:
        return items
    return items[:cap] + [f"... (+{len(items) - cap} more)"]


def build_prompt(config: Dict[str, List[str]], samples: List[Dict]) -> str:
    """Build the full bilingual extraction prompt.

    ``config`` shape: ``{own_brands, shadow_brands, peers, product_variants}``
        — each list is plain strings.
    ``samples`` shape: ``[{result_id, text}, ...]``.
    """
    own_brands = _truncate_list(config["own_brands"])
    shadow_brands = _truncate_list(config["shadow_brands"])
    peers = _truncate_list(config["peers"])
    variants = _truncate_list(config["product_variants"])

    samples_blob = "\n\n---\n\n".join(
        f"[response_id={s['result_id']}]\n{s['text']}"
        for s in samples
    )

    return f"""You are an analyst helping a Generative Engine Optimization (GEO) SaaS tenant discover **new** brand / product / SKU mentions that are NOT yet in their configured tracking lists.

你是一个 GEO SaaS 租户的分析助手。请从下列 AI 搜索引擎回答中,找出**尚未配置**的品牌 / 产品型号 / SKU 候选。

## Already configured (do NOT re-emit these)

**Own brands (我的品牌):**
{json.dumps(own_brands, ensure_ascii=False)}

**Shadow brands — resale / distribution channel brands (经销渠道品牌):**
{json.dumps(shadow_brands, ensure_ascii=False)}

**Peers — independent competitors (独立竞品):**
{json.dumps(peers, ensure_ascii=False)}

**Product variants (已配置的产品匹配变体):**
{json.dumps(variants, ensure_ascii=False)}

## Responses to mine

{samples_blob}

## Task

Scan the responses and propose candidates that are clearly brand names, product model numbers, or SKU identifiers AND are NOT in the lists above (case-insensitive).

For each candidate, choose ONE ``type`` from:
- ``brand``          — a standalone brand name that looks like a Own/competitor brand candidate
- ``shadow_brand``   — clearly a retail / distributor channel brand (e.g. Amazon Basics, Walmart, RC, Target)
- ``peer``           — a rival product brand not yet listed as a peer
- ``own_product``    — a product/SKU code that looks like it belongs to one of the Own brands
- ``shadow_product`` — a product/SKU that lives on a Shadow Brand channel
- ``peer_product``   — a SKU of a listed or suspected peer

Rules:
- Only include candidates you are reasonably confident are real entities (>= 70%% confidence).
- Do NOT emit generic words, categories, feature names, or marketing phrases.
- Deduplicate case-insensitively within your output. Prefer the most canonical form (usually the form that appears in the response).
- If unsure between ``brand`` and ``shadow_brand``, prefer ``brand``.
- If the response text is in Chinese, Chinese candidate strings are fine — do not translate.

Return ONLY a JSON object — no prose, no markdown fences — matching:
{{
  "candidates": [
    {{
      "string": "<candidate as it should be stored>",
      "type": "brand|shadow_brand|peer|own_product|shadow_product|peer_product",
      "reasoning": "<one short sentence justifying the classification>"
    }}
  ]
}}
""".strip()
