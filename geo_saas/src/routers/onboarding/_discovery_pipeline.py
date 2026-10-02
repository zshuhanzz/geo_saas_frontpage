"""
Main 4-layer Auto-Discovery pipeline (async generator yielding progress events).

Phase 3A.5 refactor (2026-04-25): extracted from monolithic ``auto_discovery.py``.

Pipeline shape::

    Harvest phase (Layers 0-3.5)  →  Synthesis phase (LLM, always runs)

The harvest phase tries multiple strategies to get URL + anchor-text signals
from the site; the synthesis phase feeds whatever we got (possibly nothing)
to the configured Gemini model and asks it for semantic topics. Even with
zero harvested signals we still call the LLM — for known brands it can answer
from training knowledge, which is strictly better than returning empty.

Event shapes yielded by ``run_discovery_pipeline``::

    {"type": "stage",   "stage": "<stage_id>", "message": "..."}
    {"type": "progress","stage": "<stage_id>", "count": N, "message": "..."}
    {"type": "warn",    "stage": "<stage_id>", "message": "..."}
    {"type": "final",   "result": <AutoDiscoverResponse.model_dump()>}

Both the non-streaming POST endpoint and the SSE streaming endpoint consume
the same generator — one collects the final event, the other pipes every
event to the client. Keeping a single code path guarantees they can never
drift out of sync.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from ._discovery_fetchers import (
    COMMON_CONTENT_PATHS,
    COMMON_SITEMAP_PATHS,
    DEFAULT_HEADERS,
    HTTP_TIMEOUT,
    MAX_HTML_LINKS,
    NavLinkExtractor,
    collect_sitemap_urls,
    fetch_robots_sitemaps,
    http_get,
    normalize_base_url,
    parse_html_navigation,
)
from ._discovery_llm import heuristic_topics_from_urls, llm_extract_topics
from ._discovery_models import (
    AutoDiscoverResponse,
    DiscoveredTopic,
    SeedProduct,
)

logger = logging.getLogger("GeoSaaSAPI.AutoDiscovery")

__all__ = ["run_discovery_pipeline"]


async def run_discovery_pipeline(
    brand_name: str,
    website_url: str,
    instruction: Optional[str] = None,
    seed_urls: Optional[List[str]] = None,
):
    """
    End-to-end onboarding discovery pipeline.

    ``instruction`` is an optional user-supplied steering string. It bypasses
    the harvest phase entirely (which is purely mechanical) and is injected
    into the Gemini prompt during synthesis.
    """
    base_url = normalize_base_url(website_url.strip())
    notes: List[str] = []
    collected_urls: List[str] = []
    html_signals: List[Dict[str, str]] = []
    # Layer 0 seed signals are kept in a separate list so subsequent layers
    # (which reassign collected_urls / html_signals wholesale) don't clobber
    # them. They get prepended to the final `signals` list fed to Gemini.
    seed_persistent_signals: List[Dict[str, str]] = []
    source_layer = "failed"
    clean_instruction = (instruction or "").strip()

    yield {
        "type": "stage",
        "stage": "init",
        "message": f"Preparing to analyze {base_url}",
    }

    # Surface the user instruction up front so it appears above the harvest
    # stages in the live progress feed. Lets the user confirm their steering
    # was received before any crawling starts.
    if clean_instruction:
        preview = clean_instruction if len(clean_instruction) <= 160 else clean_instruction[:157] + "..."
        yield {
            "type": "stage",
            "stage": "instruction",
            "message": f"Applying user instruction: {preview}",
        }
        notes.append(f"User instruction applied: {clean_instruction}")

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:

        # ---------- Layer 0 (optional): user-supplied seed URLs ----------
        # When the user provides category / listing pages (e.g. a distributor
        # product-series page whose items are all OEM-manufactured by the
        # customer), we fetch those pages and scrape the real product-detail
        # links before crawling the full sitemap. The extracted URLs feed the
        # LLM as high-signal evidence so it doesn't hallucinate SKU paths.
        if seed_urls:
            yield {
                "type": "stage",
                "stage": "layer0_seed_urls",
                "message": f"Fetching {len(seed_urls)} user-supplied listing page(s)...",
            }
            seed_discovered_urls: List[str] = []
            seed_signals: List[Dict[str, str]] = []
            for seed_url in seed_urls:
                seed_url = seed_url.strip()
                if not seed_url or not (seed_url.startswith("http://") or seed_url.startswith("https://")):
                    continue
                try:
                    resp = await client.get(seed_url)
                    if resp.status_code != 200 or not resp.text:
                        notes.append(f"Layer 0: {seed_url} → HTTP {resp.status_code}")
                        continue
                    # Lightweight anchor extraction — pulls every <a href=...>
                    # from the page (not limited to nav like NavLinkExtractor)
                    # because list pages put product cards in main content.
                    #
                    # Pre-strip <style> and <script> blocks. Modern React /
                    # Emotion sites inline CSS-in-JS rules like
                    #   <style>.css-dos2rt{display:-webkit-box;...}</style>
                    # inside anchor tags. Just stripping HTML tags leaves the
                    # raw CSS-rule text behind and it bleeds into product
                    # names. Removing the entire <style>...</style> block
                    # (and <script>) kills that noise at the source.
                    style_block_re = re.compile(
                        r"<(style|script)\b[^>]*>.*?</\1>",
                        re.IGNORECASE | re.DOTALL,
                    )
                    clean_html = style_block_re.sub(" ", resp.text)
                    anchor_re = re.compile(
                        r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                        re.IGNORECASE | re.DOTALL,
                    )
                    tag_strip_re = re.compile(r"<[^>]+>")
                    seed_netloc = urlparse(seed_url).netloc
                    page_links: List[Dict[str, str]] = []
                    for href, inner in anchor_re.findall(clean_html):
                        href = href.strip()
                        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                            continue
                        # Resolve relative URLs.
                        abs_url = urljoin(seed_url, href)
                        parsed = urlparse(abs_url)
                        if parsed.netloc and parsed.netloc != seed_netloc:
                            continue
                        segs = [s for s in parsed.path.split("/") if s]
                        if len(segs) < 2:
                            continue
                        text_ = tag_strip_re.sub(" ", inner).strip()[:120]
                        page_links.append({"url": abs_url, "text": text_})
                    # Dedup
                    seen_set = set()
                    for pl in page_links:
                        if pl["url"] in seen_set:
                            continue
                        seen_set.add(pl["url"])
                        seed_discovered_urls.append(pl["url"])
                        seed_signals.append(pl)
                    notes.append(f"Layer 0: {seed_url} → {len(page_links)} product link(s)")
                    yield {
                        "type": "progress",
                        "stage": "layer0_seed_urls",
                        "count": len(page_links),
                        "message": f"{seed_url} → {len(page_links)} product link(s)",
                    }
                except Exception as exc:
                    notes.append(f"Layer 0: {seed_url} fetch error: {exc}")
            if seed_discovered_urls:
                # Seed URLs are highest-priority evidence. Persist them in
                # seed_persistent_signals so Layer 4 can prepend them to the
                # final `signals` list fed to Gemini regardless of what
                # Layers 1-3 do with collected_urls / html_signals.
                seed_persistent_signals = seed_signals
                source_layer = "layer0_seed_urls"

        # ---------- Layer 1: robots.txt → sitemap ----------
        yield {
            "type": "stage",
            "stage": "layer1_robots",
            "message": "Checking robots.txt for sitemap directives...",
        }
        sitemaps = await fetch_robots_sitemaps(client, base_url)
        if sitemaps:
            notes.append(f"Layer 1: robots.txt advertised {len(sitemaps)} sitemap(s)")
            yield {
                "type": "progress",
                "stage": "layer1_robots",
                "count": len(sitemaps),
                "message": f"Found {len(sitemaps)} sitemap URL(s) in robots.txt",
            }
            collected_urls = await collect_sitemap_urls(client, sitemaps)
            if collected_urls:
                source_layer = "layer1_sitemap"
                notes.append(f"Layer 1: collected {len(collected_urls)} URLs")
                yield {
                    "type": "progress",
                    "stage": "layer1_sitemap",
                    "count": len(collected_urls),
                    "message": f"Collected {len(collected_urls)} URLs from sitemap(s)",
                }
        else:
            notes.append("Layer 1: no robots.txt sitemap directives")
            yield {
                "type": "warn",
                "stage": "layer1_robots",
                "message": "No sitemap directives found in robots.txt",
            }

        # ---------- Layer 2: common sitemap paths ----------
        if not collected_urls:
            yield {
                "type": "stage",
                "stage": "layer2_common",
                "message": "Trying common sitemap paths...",
            }
            tried: List[str] = []
            for path in COMMON_SITEMAP_PATHS:
                sm_url = urljoin(base_url, path)
                tried.append(path)
                urls = await collect_sitemap_urls(client, [sm_url])
                if urls:
                    collected_urls = urls
                    source_layer = "layer2_common_paths"
                    notes.append(
                        f"Layer 2: hit on {path} → {len(urls)} URLs (after trying {tried})"
                    )
                    yield {
                        "type": "progress",
                        "stage": "layer2_common",
                        "count": len(urls),
                        "message": f"Hit {path} → {len(urls)} URLs",
                    }
                    break
            if not collected_urls:
                notes.append(f"Layer 2: no sitemap at common paths ({tried})")
                yield {
                    "type": "warn",
                    "stage": "layer2_common",
                    "message": f"No sitemap at common paths ({', '.join(tried)})",
                }

        # ---------- Layer 3: HTML nav parsing on homepage ----------
        if not collected_urls:
            yield {
                "type": "stage",
                "stage": "layer3_html",
                "message": "Fetching homepage HTML and parsing navigation...",
            }
            html_signals = await parse_html_navigation(client, base_url)
            if html_signals:
                collected_urls = [s["url"] for s in html_signals]
                source_layer = "layer3_html_nav"
                notes.append(f"Layer 3: parsed {len(html_signals)} nav links")
                yield {
                    "type": "progress",
                    "stage": "layer3_html",
                    "count": len(html_signals),
                    "message": f"Parsed {len(html_signals)} navigation links",
                }
            else:
                notes.append("Layer 3: no navigation anchors found")
                yield {
                    "type": "warn",
                    "stage": "layer3_html",
                    "message": "No navigation anchors found on homepage",
                }

        # ---------- Layer 3.5: common content paths (SPA fallback) ----------
        # Many SPA brand sites have empty-shell homepages but server-render
        # /products, /collections, /shop etc. Probe those and harvest any
        # anchors we find — good signal for the LLM even if the homepage is
        # completely blank.
        if not html_signals:
            yield {
                "type": "stage",
                "stage": "layer3_content_paths",
                "message": "Trying common product/collection paths for SPA sites...",
            }
            hits: List[Dict[str, str]] = []
            hit_paths: List[str] = []
            for path in COMMON_CONTENT_PATHS:
                page_url = urljoin(base_url, path)
                try:
                    resp = await http_get(client, page_url)
                except Exception:
                    resp = None
                if not resp:
                    continue
                # Reuse the nav extractor but force full-page mode — these
                # aren't homepages so they often have no <nav> at all.
                extractor = NavLinkExtractor(page_url)
                extractor._nav_stack = ["_sentinel_force_"]
                try:
                    extractor.feed(resp.text)
                    extractor.close()
                except Exception:
                    pass
                if extractor.links:
                    hits.extend(extractor.links)
                    hit_paths.append(path)
                    if len(hits) >= MAX_HTML_LINKS:
                        break
            if hits:
                # Dedupe by URL
                seen: set = set()
                deduped: List[Dict[str, str]] = []
                for h in hits:
                    if h["url"] not in seen:
                        seen.add(h["url"])
                        deduped.append(h)
                html_signals = deduped[:MAX_HTML_LINKS]
                collected_urls = [s["url"] for s in html_signals]
                source_layer = "layer3_content_paths"
                notes.append(
                    f"Layer 3.5: harvested {len(html_signals)} anchors from {hit_paths}"
                )
                yield {
                    "type": "progress",
                    "stage": "layer3_content_paths",
                    "count": len(html_signals),
                    "message": f"Found {len(html_signals)} anchors from {', '.join(hit_paths)}",
                }
            else:
                notes.append(f"Layer 3.5: no content at common paths ({COMMON_CONTENT_PATHS})")
                yield {
                    "type": "warn",
                    "stage": "layer3_content_paths",
                    "message": "No content at common product/collection paths either",
                }

    # ---------- Heuristic pass (used only as last-resort if LLM unavailable) ----------
    heuristic_topics, heuristic_products = heuristic_topics_from_urls(collected_urls)

    # ---------- LLM synthesis (ALWAYS runs — even with zero signals) ----------
    # This is the primary synthesizer. For known brands like Roborock, Gemini
    # can produce useful topics from just the brand name + URL even if the
    # harvest phase returned absolutely nothing. The "fallback" is the
    # path-segment heuristic, not the LLM.
    signals = html_signals if html_signals else [{"url": u, "text": ""} for u in collected_urls]
    # Prepend Layer 0 seed signals — these are the user-curated listing-page
    # anchors which must dominate the LLM's attention over generic sitemap
    # URLs. Dedup by URL in case Layer 1 also caught them.
    if seed_persistent_signals:
        seen_urls = {s.get("url") for s in seed_persistent_signals}
        signals = seed_persistent_signals + [s for s in signals if s.get("url") not in seen_urls]
    n_signals = len(signals)
    if n_signals == 0:
        yield {
            "type": "stage",
            "stage": "layer4_llm",
            "message": (
                "No signals harvested — asking Gemini to use its training knowledge "
                f"of '{brand_name}' to propose semantic topics..."
            ),
        }
    else:
        yield {
            "type": "stage",
            "stage": "layer4_llm",
            "message": f"Asking Gemini to synthesize semantic topics from {n_signals} signal(s)...",
        }

    llm_result = await llm_extract_topics(brand_name, base_url, signals, clean_instruction or None)

    topics: List[DiscoveredTopic] = []
    products: List[str] = []
    if llm_result and isinstance(llm_result.get("topics"), list):
        for t in llm_result["topics"]:
            if not isinstance(t, dict):
                continue
            name = (t.get("topic_name") or "").strip()
            if not name:
                continue
            prods = [
                p.strip()
                for p in (t.get("products") or [])
                if isinstance(p, str) and p.strip()
            ]
            topics.append(DiscoveredTopic(topic_name=name, products=prods))
        products = [
            p.strip()
            for p in (llm_result.get("products") or [])
            if isinstance(p, str) and p.strip()
        ]
        if topics:
            # Source layer should reflect "LLM synthesized from harvested signals"
            # vs "LLM synthesized from training knowledge alone".
            source_layer = "layer4_llm" if n_signals > 0 else "layer4_llm_zero_signal"
            note_msg = (
                f"Layer 4: LLM extracted {len(topics)} topics, {len(products)} products"
                + (" (from training knowledge only)" if n_signals == 0 else "")
            )
            notes.append(note_msg)
            yield {
                "type": "progress",
                "stage": "layer4_llm",
                "count": len(topics),
                "message": f"LLM synthesized {len(topics)} semantic topic(s)"
                + (" from training knowledge" if n_signals == 0 else ""),
            }
    else:
        notes.append("Layer 4: LLM unavailable or returned empty")
        yield {
            "type": "warn",
            "stage": "layer4_llm",
            "message": "LLM unavailable or returned empty; falling back to heuristic",
        }

    # If LLM failed but we have heuristic results, use them as last resort
    if not topics and heuristic_topics:
        topics = heuristic_topics
        products = heuristic_products
        if source_layer == "failed":
            source_layer = "layer1_sitemap" if collected_urls else "failed"
        notes.append(f"Using heuristic topics ({len(topics)})")
        yield {
            "type": "progress",
            "stage": "heuristic",
            "count": len(topics),
            "message": f"Heuristic pass produced {len(topics)} topic(s)",
        }

    # Priority order in raw_urls_sample: Layer 0 seed signals first (most
    # relevant to the user since they curated these) then whatever Layers
    # 1-3 collected. Dedup by URL.
    sample_urls: List[str] = []
    seen_sample = set()
    for s in seed_persistent_signals:
        u = s.get("url")
        if u and u not in seen_sample:
            seen_sample.add(u)
            sample_urls.append(u)
    for u in collected_urls:
        if u not in seen_sample:
            seen_sample.add(u)
            sample_urls.append(u)

    # Build seed_products from Layer 0 (anchor text + real URL) — these
    # bypass Gemini entirely so real URLs aren't lost to LLM hallucination
    # during the topic-synthesis pass.
    seed_products_out: List[SeedProduct] = []
    seen_seed_urls: set = set()
    for s in seed_persistent_signals:
        u = (s.get("url") or "").strip()
        t = (s.get("text") or "").strip()
        if not u or u in seen_seed_urls or not t:
            continue
        seen_seed_urls.add(u)
        # Light name sanitization — trim common listing-page UI noise
        # (reviews / price / "In stock"). Defensive: identical cleanup to
        # what the onboarding DB post-insert pass was doing manually.
        t = re.sub(r"\s+(Be first to review|\d+\s+reviews).*$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+(Starting at\s+)?\$[0-9,.]+.*$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+(In stock|Configurable|Out of stock).*$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        seed_products_out.append(SeedProduct(name=t[:250], url=u))

    final = AutoDiscoverResponse(
        brand_name=brand_name,
        website_url=base_url,
        source_layer=source_layer,
        topics=topics,
        products=products,
        seed_products=seed_products_out,
        raw_urls_sample=sample_urls[:60],
        notes=notes,
    )
    yield {"type": "final", "result": final.model_dump()}
