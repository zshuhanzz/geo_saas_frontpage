"""
Phase 1 — Per-result, in-memory parse.

For each ``geo_results`` row in the current batch, run brand / product /
citation parsers. Outputs are accumulated in a ``BatchParseResult`` so Phase
2a, 2b, and 3 can consume them without touching the source rows again.

This phase does **no** database writes — it only reads from the rows in
memory. The DB rows themselves were loaded by ``main.py``'s batch query.

Phase 2.5b note: ``results`` is now a list of ``asyncpg.Record`` objects.
``Record`` supports dict-style access only (``r["text"]``), not attribute
access — earlier sync-SQLAlchemy ``.text`` calls have been ported.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from src.parsers.brand_parser import parse_brand_mentions
from src.parsers.citation_parser import parse_citations
from src.parsers.product_parser import parse_product_mentions
from src.parsers.sentiment_parser import strip_entity_citation_markers
from src.pipeline.phase0_load_config import ClientConfig

logger = logging.getLogger("GeoAnalyzer.phase1")

# Sentiment input is fed into Gemini per sub-batch later. We collect tuples
# rather than dicts to keep Phase 2b's signature stable with the existing
# ``parse_sentiment_batch`` helper.
SentimentTargetEntities = Dict[str, List[str]]
SentimentInput = Tuple[int, str, Any, Any, Any, Any, SentimentTargetEntities]
# (result_id, text, client_id, client_prompt_id, task_id, executed_at, target_entities)


@dataclass
class BatchParseResult:
    # Per-result parse outputs, ordered to match the source rows.
    # Each entry: (result_row, brand_mentions, product_mentions, citations)
    per_result: List[Tuple[Any, list, list, list]] = field(default_factory=list)
    # Lowercase domain set for Phase 2a classifier.
    all_domains: Set[str] = field(default_factory=set)
    # Subset of results worth running through sentiment (text > 100 chars).
    sentiment_inputs: List[SentimentInput] = field(default_factory=list)


def _entity_label(name: str, aliases: List[str]) -> str:
    """Render an entity with aliases so LLM attribution sees equivalent names."""
    clean_aliases = []
    seen = {name.lower()}
    for alias in aliases or []:
        alias = (alias or "").strip()
        if not alias:
            continue
        key = alias.lower()
        if key in seen:
            continue
        clean_aliases.append(alias)
        seen.add(key)
    if clean_aliases:
        return f"{name} (aliases: {', '.join(clean_aliases)})"
    return name


def _brand_alias_map(config: ClientConfig) -> Dict[str, List[str]]:
    return {
        (b.get("brand_name") or "").strip(): list(b.get("aliases") or [])
        for b in config.brands
        if (b.get("brand_name") or "").strip()
    }


def _product_alias_map(config: ClientConfig) -> Dict[str, List[str]]:
    return {
        (p.get("product_name") or "").strip(): list(p.get("match_variants") or [])
        for p in config.tracked_products
        if (p.get("product_name") or "").strip()
    }


def _configured_entity_terms(config: ClientConfig) -> List[str]:
    """Names whose ``Name+N`` citation markers must not trigger sentiment."""
    terms: List[str] = []
    for brand in config.brands:
        terms.append((brand.get("brand_name") or "").strip())
        terms.extend(brand.get("aliases") or [])
    for product in config.tracked_products:
        terms.append((product.get("product_name") or "").strip())
        terms.extend(product.get("match_variants") or [])
    return [term for term in terms if term]


def _sentiment_target_entities(
    brand_mentions: list,
    product_mentions: list,
    config: ClientConfig,
) -> SentimentTargetEntities:
    """Return customer-owned entities that sentiment may be attributed to."""
    brand_aliases = _brand_alias_map(config)
    product_aliases = _product_alias_map(config)
    brands = sorted({
        _entity_label(m["brand_name"], brand_aliases.get(m["brand_name"], []))
        for m in brand_mentions
        if m.get("brand_role") in ("own", "shadow") and m.get("brand_name")
    })
    own_brand_ids = {
        str(brand.get("id"))
        for brand in config.brands
        if brand.get("id") is not None and not brand.get("is_shadow")
    }
    shadow_brand_ids = {
        str(brand.get("id"))
        for brand in config.brands
        if brand.get("id") is not None and brand.get("is_shadow")
    }
    products = sorted({
        _entity_label(m["product_name"], product_aliases.get(m["product_name"], []))
        for m in product_mentions
        if m.get("product_name")
        and m.get("owner_brand_id") is not None
        and (
            (
                m.get("product_role") == "own"
                and str(m.get("owner_brand_id")) in own_brand_ids
            )
            or (
                m.get("product_role") == "shadow_brand_product"
                and str(m.get("owner_brand_id")) in shadow_brand_ids
            )
        )
    })
    return {"brands": brands, "products": products}


def parse_batch(results, config: ClientConfig) -> BatchParseResult:
    """Parse one DB batch of ``geo_results`` rows into structured outputs."""
    out = BatchParseResult()
    for result in results:
        text_blob = result["text"] or ""
        sentiment_text_blob = strip_entity_citation_markers(
            text_blob,
            _configured_entity_terms(config),
        )

        # --- Brand mentions (own / shadow / peer dedupe in parser) ---
        brand_mentions = parse_brand_mentions(
            text_blob,
            brands=config.brands,
            peers=config.peers,
        )

        # --- Product mentions (variants + denormalized owner fields) ---
        product_mentions = parse_product_mentions(
            text_blob,
            tracked_products=config.tracked_products,
        )

        sentiment_brand_mentions = parse_brand_mentions(
            sentiment_text_blob,
            brands=config.brands,
            peers=config.peers,
        )
        sentiment_product_mentions = parse_product_mentions(
            sentiment_text_blob,
            tracked_products=config.tracked_products,
        )

        # --- Citations (two-stage: tracked URL → domain → fallback) ---
        citations = parse_citations(
            result["sources"] or [],
            result["citation_pills"] or [],
            tracked_urls=config.tracked_urls,
            domains=config.domains,
            include_pill_only=(result["platform"] or "").strip().lower() == "chatgpt",
        )

        # Collect unique domains for Phase 2a.
        for c in citations:
            d = c.get("source_domain", "")
            if d:
                out.all_domains.add(d.lower())

        # Sentiment is only meaningful when the response mentions a customer
        # entity. Peer-only pros/cons belong to competitor analysis, not the
        # customer's sentiment dashboard.
        target_entities = _sentiment_target_entities(
            sentiment_brand_mentions,
            sentiment_product_mentions,
            config,
        )
        has_target_entity = bool(target_entities["brands"] or target_entities["products"])
        if result["text"] and len(result["text"].strip()) > 100 and has_target_entity:
            out.sentiment_inputs.append((
                result["result_id"],
                sentiment_text_blob,
                result["client_id"],
                result["client_prompt_id"],
                result["task_id"],
                result["ingested_at"],
                target_entities,
            ))

        out.per_result.append(
            (result, brand_mentions, product_mentions, citations)
        )

    return out
