"""
Domain Classifier — Uses Gemini to classify unknown domains into categories.

Checks geo_domain_categories mapping table first, then batch-classifies unknown
domains via Gemini and persists the results.

Categories (global, site-nature classification):
  - Earned Media   — independent reviews, news, blogs, forums
  - Agency         — service businesses selling done-for-you marketing,
                     SEO, consulting, creative, or advertising services
  - Social Media   — social / video / Q&A platforms
  - Owned Media    — official websites for a brand, product, SaaS tool,
                     API platform, publisher, or company
  - Channel        — retailers, distributors, marketplaces, e-commerce platforms
                     (amazon.com, ebay.com, jd.com, tmall.com, roughcountry.com).
                     Added in this iteration to let出海 clients track visibility
                     on distributor sites without conflating with Owned Media.
  - Other          — government, utility, or un-categorizable sites

Note: This classifier assigns categories at the **domain** level (global).
URL-level attribution for "this specific URL on a shared-host channel is
owned by a specific client" happens in ``citation_parser.parse_citations``
(v1.2), which populates ``citation_role`` + ``matched_*_id`` independently
of ``domain_category``. This module only short-circuits whole-domain Own
Brand entries to "Owned Media"; path-prefix entries continue to flow
through the LLM so the host gets its proper global category ("Channel"
in most marketplace cases).

Phase 2.5b: ``classify_domains`` and ``_gemini_classify`` are now async.
The Gemini call uses ``client.aio.models.generate_content`` so it does NOT
block the event loop. DB inserts use raw asyncpg with $-placeholders.
"""
import json
import logging
from typing import Dict, List, Optional, Set

from geo_common.llm import resolve_model_region

from .citation_parser import normalize_owned_entry

logger = logging.getLogger(__name__)

# Valid category enum values (global, site-nature classification)
DOMAIN_CATEGORIES = [
    "Earned Media",
    "Agency",
    "Social Media",
    "Owned Media",
    "Channel",
    "Other",
]


def _whole_domain_owned_hosts(owned_domains) -> Set[str]:
    """
    From the raw owned_domains input (which may be either a list of strings
    or a set of already-normalized hosts, depending on the caller), extract
    the subset that represents **whole-domain** ownership — entries without
    a path component.

    Path-prefix entries are intentionally excluded so their host (e.g.
    roughcountry.com) still gets its proper global Gemini classification
    (likely "Channel") instead of being short-circuited to "Owned Media".
    """
    result: Set[str] = set()
    if not owned_domains:
        return result

    for d in owned_domains:
        if not d:
            continue
        # Already-normalized bare host case (legacy callers pass a Set[str]
        # of plain hosts like "brand.com"). Anything with "/" should be
        # treated as a path-prefix entry and NOT short-circuited.
        if "/" not in d:
            result.add(d.lower().strip())
            continue
        # Raw entry with scheme/www/path — normalize and keep only whole-domain.
        try:
            host, prefix = normalize_owned_entry(d)
            if prefix is None:
                result.add(host)
        except ValueError:
            continue
    return result


async def classify_domains(
    conn,
    domains: Set[str],
    owned_domains,
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> Dict[str, str]:
    """
    Classify a set of domains into categories.

    1. Mark **whole-domain** owned entries as "Owned Media" (path-prefix entries
       flow through so their host gets a proper global category).
    2. Look up existing classifications in geo_domain_categories.
    3. For remaining unknown domains, batch-query Gemini.
    4. Persist new classifications to geo_domain_categories.

    Args:
        owned_domains: Either a list of raw strings from `geo_client_domains.domain`
            (may include scheme/www/path), or a Set[str] of already-normalized
            bare hosts. Both are accepted for backward compatibility.
        model_id: Optional Gemini model to use (from global settings). Falls back to env var.
        model_region_overrides: Optional model-id -> Vertex location override JSON.

    Returns: dict mapping domain -> category
    """
    if not domains:
        return {}

    result_map: Dict[str, str] = {}
    whole_owned = _whole_domain_owned_hosts(owned_domains)

    # Step 1: Whole-domain owned short-circuit
    for d in domains:
        if d.lower() in whole_owned:
            result_map[d.lower()] = "Owned Media"

    # Step 2: Check mapping table
    remaining = {d.lower() for d in domains if d.lower() not in result_map}
    if remaining:
        rows = await conn.fetch(
            """
            SELECT domain, category FROM geo_domain_categories
            WHERE domain = ANY($1::text[])
            """,
            list(remaining),
        )
        for r in rows:
            result_map[r["domain"]] = r["category"]
            remaining.discard(r["domain"])

    # Step 3: Classify remaining via Gemini
    cached_count = len(domains) - len(remaining)
    if remaining:
        logger.info(
            f"[CLASSIFIER] Domain stats: {len(domains)} total, "
            f"{cached_count} cached, {len(remaining)} need Gemini"
        )
        new_classifications = await _gemini_classify(
            list(remaining),
            model_id=model_id,
            model_region_overrides=model_region_overrides,
        )
        result_map.update(new_classifications)

        # Step 4: Persist to mapping table (the enclosing pipeline transaction
        # commits per-batch; if there's no enclosing transaction, each
        # statement auto-commits which is fine for an idempotent UPSERT).
        if new_classifications:
            for domain, category in new_classifications.items():
                try:
                    await conn.execute(
                        """
                        INSERT INTO geo_domain_categories (id, domain, category, classified_by)
                        VALUES (gen_random_uuid(), $1, $2, 'gemini')
                        ON CONFLICT (domain) DO NOTHING
                        """,
                        domain,
                        category,
                    )
                except Exception as e:
                    logger.warning(
                        f"[CLASSIFIER] Failed to persist classification for {domain}: {e}"
                    )
            logger.info(
                f"[CLASSIFIER] Wrote {len(new_classifications)} new classifications to geo_domain_categories"
            )
    else:
        logger.info(
            f"[CLASSIFIER] All {len(domains)} domains resolved from cache/owned, no Gemini call needed"
        )

    # Default any still-unclassified to "Other"
    for d in domains:
        if d.lower() not in result_map:
            result_map[d.lower()] = "Other"

    return result_map


# Module-level cache for genai clients to avoid re-initializing on every call
_gemini_client_cache = {}


async def _gemini_classify(
    domains: List[str],
    model_id: Optional[str] = None,
    model_region_overrides: Optional[str] = None,
) -> Dict[str, str]:
    """
    Call Gemini to classify a batch of domains.
    Falls back to "Other" for any domain that can't be classified.

    Args:
        model_id: Optional model override from global settings.
    """
    try:
        from google import genai
        from google.genai import types
        import os

        project_id = os.environ.get("GCP_PROJECT_ID", "")
        effective_model = model_id or os.environ.get("GEMINI_MODEL_ID", "gemini-2.0-flash")
        region = resolve_model_region(
            effective_model,
            overrides_value=model_region_overrides,
            default_region=os.environ.get("GCP_REGION", "us-central1"),
            global_region=os.environ.get("GCP_REGION_GLOBAL", "global"),
        )

        if not project_id:
            logger.warning("[CLASSIFIER] GCP_PROJECT_ID not set, defaulting all to 'Other'")
            return {d: "Other" for d in domains}

        # Cache genai client to avoid re-initializing on every batch
        cache_key = f"{project_id}:{region}"
        if cache_key not in _gemini_client_cache:
            _gemini_client_cache[cache_key] = genai.Client(
                vertexai=True, project=project_id, location=region
            )
            logger.info(f"[CLASSIFIER] Initialized GenAI client: {effective_model} (region: {region})")
        else:
            logger.info(f"[CLASSIFIER] Reusing cached GenAI client: {effective_model}")
        client = _gemini_client_cache[cache_key]

        # Batch classify (max ~50 domains at a time)
        all_results: Dict[str, str] = {}
        batch_size = 50
        total_batches = (len(domains) + batch_size - 1) // batch_size
        for batch_idx, i in enumerate(range(0, len(domains), batch_size)):
            batch = domains[i:i + batch_size]
            logger.info(
                f"[CLASSIFIER] Processing batch {batch_idx + 1}/{total_batches} "
                f"({len(batch)} domains)..."
            )

            try:
                prompt = _build_prompt(batch)
                response = await client.aio.models.generate_content(
                    model=effective_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
            except Exception as e:
                logger.warning(f"[CLASSIFIER] Gemini call failed for batch {batch_idx + 1}: {e}")
                for d in batch:
                    all_results[d.lower()] = "Other"
                continue

            try:
                text_content = (response.text or "").strip()
                if not text_content:
                    raise ValueError("empty Gemini response")
                # Remove markdown code fences if present
                if text_content.startswith("```"):
                    text_content = text_content.split("\n", 1)[1]
                    text_content = text_content.rsplit("```", 1)[0].strip()

                parsed = json.loads(text_content)
                if isinstance(parsed, dict):
                    for domain, category in parsed.items():
                        if category in DOMAIN_CATEGORIES:
                            all_results[domain.lower()] = category
                        else:
                            all_results[domain.lower()] = "Other"
                elif isinstance(parsed, list):
                    for item in parsed:
                        domain = item.get("domain", "").lower()
                        category = item.get("category", "Other")
                        if category not in DOMAIN_CATEGORIES:
                            category = "Other"
                        if domain:
                            all_results[domain] = category
                logger.info(
                    f"[CLASSIFIER] Batch {batch_idx + 1}/{total_batches} done, "
                    f"{len(all_results)} domains classified so far"
                )
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(
                    f"[CLASSIFIER] Failed to parse Gemini response for batch {batch_idx + 1}: {e}"
                )
                for d in batch:
                    all_results[d.lower()] = "Other"

        # Default any remaining
        for d in domains:
            if d.lower() not in all_results:
                all_results[d.lower()] = "Other"

        return all_results

    except ImportError:
        logger.warning("[CLASSIFIER] google-genai not installed, defaulting all to 'Other'")
        return {d: "Other" for d in domains}
    except Exception as e:
        logger.error(f"[CLASSIFIER] Gemini classification failed: {e}")
        return {d: "Other" for d in domains}


def _build_prompt(domains: List[str]) -> str:
    """Build Gemini prompt for domain classification."""
    domain_list = "\n".join(f"- {d}" for d in domains)
    return f"""Classify each of the following website domains into one of these categories:

Important decision rules:
- Classify the domain's global site nature. Do not classify based on the current customer.
- "Owned Media" means an official first-party website for a single brand, product, software tool, SaaS company, API platform, creator tool, media property, or publisher. This includes AI tools, ad-tech tools, creative software, image/video generation tools, and .ai product websites.
- "Agency" means a service provider primarily selling done-for-you human services: marketing agency, SEO agency, creative agency/studio, consulting firm, or advertising services firm.
- Do NOT classify a domain as "Agency" merely because its product serves marketers, advertisers, creators, or business users.
- If the domain is the official website of a self-serve software/API/SaaS/tool product, prefer "Owned Media" over "Agency".
- If the domain is a marketplace, retailer, reseller, directory, or platform where many brands are listed or sold side-by-side, classify it as "Channel".
- If the domain is a third-party news/review/blog/forum/social site, classify it as "Earned Media" or "Social Media" as appropriate.
- When uncertain between "Agency" and "Owned Media", choose "Owned Media" only if the site is primarily a product/tool/platform; choose "Agency" only if it primarily sells services/consulting.

Categories:
1. "Earned Media" — Independent review sites, news outlets, blogs, forums, expert review websites (e.g. tomsguide.com, reddit.com, techradar.com, nytimes.com, wirecutter.com)
2. "Agency" — Marketing agencies, SEO firms, consulting companies, creative agencies/studios, and advertising services firms (e.g. wpromote.com, flatlineagency.com, motiontheagency.com, theinfluencermarketingfactory.com)
3. "Social Media" — Social networking platforms, video platforms, Q&A platforms (e.g. youtube.com, twitter.com, facebook.com, quora.com, tiktok.com)
4. "Owned Media" — Official websites for a brand, product, SaaS tool, API platform, AI tool, software company, publisher, or media property (e.g. getmaxim.ai, reelmind.ai, adstellar.ai, aimlapi.com, claid.ai, getimg.ai, photoroom.com, lumalabs.ai, vizard.ai, pictory.ai, lumen5.com, piktochart.com, venngage.com, quickads.ai)
5. "Channel" — Retailers, distributors, marketplaces, and e-commerce platforms where multiple brands' products are sold side-by-side (e.g. amazon.com, ebay.com, walmart.com, jd.com, tmall.com, alibaba.com, bestbuy.com, homedepot.com, roughcountry.com). Distinguish from "Owned Media": a Channel site sells many brands; an Owned Media site is one brand's official web presence.
6. "Other" — Government sites, utility sites, or domains that don't fit other categories

Domains to classify:
{domain_list}

Return a JSON object where keys are the domain strings and values are the category strings. Example:
{{"tomsguide.com": "Earned Media", "youtube.com": "Social Media", "amazon.com": "Channel"}}
"""
