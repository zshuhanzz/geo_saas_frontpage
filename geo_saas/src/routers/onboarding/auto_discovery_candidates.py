"""
Auto-Discovery (candidate-writing variant) — Phase 6.4
======================================================

Unlike the ``auto_discovery.py`` endpoint (which returns suggestions for the
Onboarding Wizard to preview), this endpoint **writes** its findings to
``geo_settings_candidates`` so they show up in the per-tab Suggestions panel.

Workflow
--------
Given ``{client_id, target_url, target_type, target_entity_id?, instruction?,
topic_id?}``:

1. **Layer 1** — robots.txt → Sitemap directives
2. **Layer 2** — ``/sitemap.xml`` / ``/sitemap_index.xml``
3. **Layer 3** — homepage HTML nav/menu parsing
4. **Layer 4** — Gemini with web grounding as the catch-all

The URLs + anchor texts from layers 1-3 are fed into a Gemini call whose
system prompt includes the user ``instruction`` (e.g. "only include SKUs
containing HT-") for classification.

Each produced entry is UPSERTed into ``geo_settings_candidates`` with:

- ``candidate_type`` = one of:
    * ``own_product`` when ``target_type='own_domain'``
    * ``shadow_product`` when ``target_type='shadow_brand'``
    * ``peer_product`` when ``target_type='peer'``
    * ``tracked_url`` — for any grounding source URL captured
- ``source`` = ``'auto_discovery'``
- ``metadata`` = {grounding_sources, raw_llm_output, crawl_layer_used,
                  instruction, target_url}

Returns a summary(count per candidate_type + warnings). Persistence of chosen
candidates into `geo_client_topic_products` / `geo_product_tracked_urls` etc.
is a separate human-in-loop step via ``POST /settings/candidates/{id}/accept``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from functools import wraps
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from geo_common.llm import MODEL_REGION_OVERRIDES_KEY, resolve_model_region
from services.workspace_lifecycle import long_workspace_lifecycle_session

from db import database

logger = logging.getLogger("GeoSaaSAPI.AutoDiscoveryCandidates")

router = APIRouter(prefix="/api/onboarding")


# ---------------------------------------------------------------------------
# Constants — deliberately aligned with auto_discovery.py
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "X-AnswerX-Crawler": "AnswerX-GEO-Candidates/1.0 (+https://answer-x.ai)",
}
HTTP_TIMEOUT = 12.0
MAX_SITEMAP_URLS = 300
MAX_HTML_LINKS = 200
MAX_LLM_INPUT_URLS = 100
COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap_products.xml",
    "/sitemap_collections.xml",
    "/sitemaps/sitemap.xml",
]

_TARGET_TYPE_TO_CANDIDATE = {
    "own_domain": "own_product",
    "shadow_brand": "shadow_product",
    "peer": "peer_product",
}

FALLBACK_MODEL_ID = "gemini-2.0-flash"


# ---------------------------------------------------------------------------
# Request / response
# ---------------------------------------------------------------------------


class AutoDiscoveryCandidatesRequest(BaseModel):
    client_id: UUID
    target_url: str = Field(..., min_length=4, max_length=500)
    target_type: str = Field(..., pattern="^(own_domain|shadow_brand|peer)$")
    target_entity_id: Optional[UUID] = None  # brand_id / peer_id
    instruction: Optional[str] = Field(default=None, max_length=800)
    topic_id: Optional[UUID] = None


class AutoDiscoveryCandidatesResponse(BaseModel):
    client_id: UUID
    target_url: str
    target_type: str
    crawl_layer_used: str
    counts: Dict[str, int]  # candidate_type -> insert/update count
    warnings: List[str]
    tracked_urls_captured: int


# ---------------------------------------------------------------------------
# Layer 1-3 harvest (shared with auto_discovery.py patterns, slim re-impl)
# ---------------------------------------------------------------------------


def _normalize_base_url(url: str) -> str:
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    parsed = urlparse(u)
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid target_url")
    return f"{parsed.scheme}://{parsed.netloc}"


async def _http_get(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    try:
        resp = await client.get(url, follow_redirects=True, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200 and resp.text:
            return resp
        return None
    except Exception as exc:
        logger.debug("HTTP GET failed for %s: %s", url, exc)
        return None


def _parse_sitemap_xml(xml_text: str) -> Tuple[List[str], List[str]]:
    sub_sitemaps: List[str] = []
    page_urls: List[str] = []
    try:
        cleaned = re.sub(r'\sxmlns="[^"]+"', "", xml_text, count=1)
        root = ET.fromstring(cleaned)
    except Exception:
        return sub_sitemaps, page_urls
    tag = root.tag.lower()
    if tag.endswith("sitemapindex"):
        for sm in root.findall(".//sitemap/loc"):
            if sm.text:
                sub_sitemaps.append(sm.text.strip())
    elif tag.endswith("urlset"):
        for u in root.findall(".//url/loc"):
            if u.text:
                page_urls.append(u.text.strip())
    return sub_sitemaps, page_urls


async def _collect_sitemap(client: httpx.AsyncClient, urls: List[str]) -> List[str]:
    collected: List[str] = []
    seen: Set[str] = set()
    queue = list(urls)
    depth = 0
    while queue and depth < 3 and len(collected) < MAX_SITEMAP_URLS:
        nxt: List[str] = []
        for sm_url in queue:
            if sm_url in seen:
                continue
            seen.add(sm_url)
            resp = await _http_get(client, sm_url)
            if not resp:
                continue
            subs, pages = _parse_sitemap_xml(resp.text)
            collected.extend(pages)
            nxt.extend(subs)
            if len(collected) >= MAX_SITEMAP_URLS:
                break
        queue = nxt
        depth += 1
    return collected[:MAX_SITEMAP_URLS]


class _LinkHarvester(HTMLParser):
    """Minimal hrefs-with-text harvester — not scoped to <nav> on purpose.

    The Phase-6 endpoint accepts any URL (product list pages, SKU index pages)
    so harvesting every ``<a>`` gives the LLM the most evidence. The Onboarding
    auto_discovery.py is nav-scoped because it expects a homepage — this one
    expects anything.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.base_netloc = urlparse(base_url).netloc
        self.current_href: Optional[str] = None
        self.current_text: List[str] = []
        self.links: List[Dict[str, str]] = []
        self._seen: Set[str] = set()

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a" or len(self.links) >= MAX_HTML_LINKS:
            return
        d = dict(attrs)
        href = (d.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return
        self.current_href = href
        self.current_text = []

    def handle_data(self, data):
        if self.current_href is not None and data.strip():
            self.current_text.append(data.strip())

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self.current_href is None:
            return
        full = urljoin(self.base_url, self.current_href)
        try:
            parsed = urlparse(full)
        except Exception:
            self.current_href = None
            return
        if parsed.netloc == self.base_netloc and full not in self._seen:
            txt = " ".join(self.current_text)[:200]
            if txt:
                self._seen.add(full)
                self.links.append({"url": full, "text": txt})
        self.current_href = None
        self.current_text = []


async def _harvest_html_links(client: httpx.AsyncClient, page_url: str) -> List[Dict[str, str]]:
    resp = await _http_get(client, page_url)
    if not resp:
        return []
    h = _LinkHarvester(page_url)
    try:
        h.feed(resp.text)
        h.close()
    except Exception:
        pass
    return h.links


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------


async def _resolve_model_id() -> str:
    row = await database.fetch_one(
        """
        SELECT value FROM geo_global_settings
        WHERE key = 'topic_and_product_auto_discovery_model_id'
        """
    )
    if row and row["value"]:
        return row["value"]
    return FALLBACK_MODEL_ID


async def _resolve_model_region_overrides() -> Optional[str]:
    row = await database.fetch_one(
        """
        SELECT value FROM geo_global_settings
        WHERE key = :key
        """,
        {"key": MODEL_REGION_OVERRIDES_KEY},
    )
    return row["value"] if row and row["value"] else None


def _build_llm_prompt(
    target_url: str,
    target_type: str,
    signals: List[Dict[str, str]],
    instruction: Optional[str],
    configured_own_brands: List[str],
    configured_peers: List[str],
) -> str:
    sig_lines = []
    for s in signals[:MAX_LLM_INPUT_URLS]:
        line = f"- {s['url']}"
        if s.get("text"):
            line += f"  [{s['text']}]"
        sig_lines.append(line)
    signals_block = "\n".join(sig_lines) or "(no signals harvestable)"

    instruction_block = (
        f'"""\n{(instruction or "").strip()}\n"""'
        if instruction and instruction.strip()
        else "(no user instruction)"
    )

    return f"""You are an assistant helping a Generative Engine Optimization (GEO) SaaS tenant bootstrap their tracking configuration by crawling a third-party URL.

Target URL: {target_url}
Target type: {target_type}   # own_domain | shadow_brand | peer

Context — the client's already-configured Own Brands: {json.dumps(configured_own_brands, ensure_ascii=False)}
Context — the client's already-configured Peers: {json.dumps(configured_peers, ensure_ascii=False)}

User instruction (highest priority constraint): {instruction_block}

Signals harvested from the URL (anchor text + href):
{signals_block}

Task: Extract **product names / SKU codes** visible in the signals that belong at the target. Additionally, list **tracked_url** candidates — URLs worth monitoring for citation matching (product pages, SKU detail pages).

Rules:
- Classify every product as belonging to the target_type:
    own_domain    -> the client's own product on their own website
    shadow_brand  -> a product sold under a distributor / retail channel brand
    peer          -> a competitor's product
- For each product emit canonical ``name`` (and optional ``page_url`` if obviously tied to one).
- For each tracked_url emit the full URL (http/https) — favor product-detail-looking paths (/product/, /dp/, /p/, /sku/, etc.) over category pages.
- Deduplicate case-insensitively.
- Only include items you're reasonably confident about. Quality > quantity.

Return JSON — no prose, no markdown fences — matching:
{{
  "products": [
    {{"name": "<canonical product name / SKU>", "page_url": "<optional http(s) URL>", "reasoning": "<short sentence>"}}
  ],
  "tracked_urls": ["<url>", "<url>", ...]
}}
""".strip()


async def _call_llm(
    model_id: str,
    prompt: str,
    model_region_overrides: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        logger.warning("google-genai unavailable: %s", exc)
        return None

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    if not project_id:
        try:
            import google.auth
            _, project_id = google.auth.default()
        except Exception:
            pass
    if not project_id:
        logger.warning("GCP_PROJECT_ID not set; skipping LLM")
        return None

    region = resolve_model_region(
        model_id,
        overrides_value=model_region_overrides,
        default_region=os.environ.get("GCP_REGION", "us-central1"),
        global_region=os.environ.get("GCP_REGION_GLOBAL", "global"),
    )

    try:
        client = genai.Client(vertexai=True, project=project_id, location=region)
        gen_cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=4096,
        )
        resp = await client.aio.models.generate_content(
            model=model_id,
            contents=prompt,
            config=gen_cfg,
        )
        raw = (resp.text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON: %s", raw[:200])
            return None
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# UPSERT helper
# ---------------------------------------------------------------------------


async def _upsert_candidate(
    client_id: UUID,
    candidate_string: str,
    candidate_type: str,
    topic_id: Optional[UUID],
    target_entity_id: Optional[UUID],
    target_type: str,
    metadata: Dict[str, Any],
) -> str:
    """UPSERT a single candidate using raw SQL for composite ON CONFLICT handling.

    Uses ``:name`` placeholders interpreted by the asyncpg-backed ``database``
    adapter (Phase 2.5b — see ``db.py``). The asyncpg pool gets positional
    ``$N`` after the adapter's named-param rewrite shim runs.
    """
    # Figure out suggested target FKs based on target_type / entity_id
    suggested_brand_id = None
    suggested_peer_id = None
    if target_type == "shadow_brand":
        suggested_brand_id = target_entity_id
    elif target_type == "peer":
        suggested_peer_id = target_entity_id
    # own_domain carries no FK to a Shadow Brand / Peer by definition.

    # ``databases`` library expects positional or named params with `:` syntax
    # in SQLAlchemy Core style. We use SQLAlchemy Core ``insert`` + raw SQL
    # via ``database.execute(raw_sql, values={...})`` to get ON CONFLICT.
    sql = """
        INSERT INTO geo_settings_candidates (
            client_id, candidate_string, candidate_type,
            suggested_target_topic_id,
            suggested_target_brand_id,
            suggested_target_peer_id,
            source, frequency, first_seen, last_seen, status,
            sample_response_ids, metadata
        ) VALUES (
            :client_id, :candidate_string, :candidate_type,
            :topic_id, :brand_id, :peer_id,
            'auto_discovery', 1, NOW(), NOW(), 'pending',
            NULL, CAST(:meta AS JSONB)
        )
        ON CONFLICT (client_id, candidate_string, candidate_type) DO UPDATE SET
            frequency = geo_settings_candidates.frequency + 1,
            last_seen = NOW(),
            source = CASE
                WHEN geo_settings_candidates.source = EXCLUDED.source
                    THEN geo_settings_candidates.source
                WHEN position(EXCLUDED.source in geo_settings_candidates.source) > 0
                    THEN geo_settings_candidates.source
                ELSE geo_settings_candidates.source || '+' || EXCLUDED.source
            END,
            suggested_target_topic_id = COALESCE(geo_settings_candidates.suggested_target_topic_id, EXCLUDED.suggested_target_topic_id),
            suggested_target_brand_id = COALESCE(geo_settings_candidates.suggested_target_brand_id, EXCLUDED.suggested_target_brand_id),
            suggested_target_peer_id = COALESCE(geo_settings_candidates.suggested_target_peer_id, EXCLUDED.suggested_target_peer_id),
            metadata = COALESCE(geo_settings_candidates.metadata, '{}'::jsonb) || EXCLUDED.metadata
        RETURNING id, (xmax = 0) AS inserted
    """
    row = await database.fetch_one(
        sql,
        {
            "client_id": client_id,
            "candidate_string": candidate_string,
            "candidate_type": candidate_type,
            "topic_id": topic_id,
            "brand_id": suggested_brand_id,
            "peer_id": suggested_peer_id,
            "meta": json.dumps(metadata),
        },
    )
    if row is None:
        return "updated"
    # asyncpg.Record is dict-like but doesn't expose .get(); subscript access is
    # safe here because the SELECT always returns the ``inserted`` column.
    return "inserted" if row["inserted"] else "updated"


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------


async def _load_configured_names(client_id: UUID) -> Tuple[List[str], List[str]]:
    """Return (own_brand_names, peer_primary_names) for prompt context."""
    own_brands_rows = await database.fetch_all(
        """
        SELECT brand_name FROM geo_client_brands
        WHERE client_id = :client_id
          AND is_shadow = FALSE
          AND is_active = TRUE
        """,
        {"client_id": client_id},
    )
    peers_rows = await database.fetch_all(
        """
        SELECT primary_name FROM geo_client_peers
        WHERE client_id = :client_id
        """,
        {"client_id": client_id},
    )
    return (
        [r["brand_name"] for r in own_brands_rows if r["brand_name"]],
        [r["primary_name"] for r in peers_rows if r["primary_name"]],
    )


def _workspace_guarded_discovery(endpoint):
    @wraps(endpoint)
    async def guarded(data: AutoDiscoveryCandidatesRequest):
        async with long_workspace_lifecycle_session(database.pool(), str(data.client_id)):
            return await endpoint(data)

    return guarded


@router.post("/auto_discovery", response_model=AutoDiscoveryCandidatesResponse)
@_workspace_guarded_discovery
async def auto_discovery_candidates(data: AutoDiscoveryCandidatesRequest) -> AutoDiscoveryCandidatesResponse:
    """Run the 4-layer crawl + LLM classification and UPSERT candidates.

    This is the Phase 6.4 companion to the Onboarding Wizard's
    ``/auto-discover``: same crawling pipeline, but writes its findings to
    ``geo_settings_candidates`` instead of returning them for the wizard to
    preview. The per-tab Suggestions panel picks them up.
    """
    if data.target_type not in _TARGET_TYPE_TO_CANDIDATE:
        raise HTTPException(status_code=422, detail="target_type must be one of own_domain / shadow_brand / peer")
    candidate_type = _TARGET_TYPE_TO_CANDIDATE[data.target_type]

    base_url = _normalize_base_url(data.target_url)
    warnings: List[str] = []
    crawl_layer_used = "none"
    collected_urls: List[str] = []
    html_signals: List[Dict[str, str]] = []

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        # ---- Layer 1: robots.txt
        resp = await _http_get(client, urljoin(base_url, "/robots.txt"))
        sm_urls: List[str] = []
        if resp:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.lower().startswith("sitemap:"):
                    url = line.split(":", 1)[1].strip()
                    if url:
                        sm_urls.append(url)
        if sm_urls:
            collected_urls = await _collect_sitemap(client, sm_urls)
            if collected_urls:
                crawl_layer_used = "layer1_robots_sitemap"

        # ---- Layer 2: common sitemap paths
        if not collected_urls:
            for path in COMMON_SITEMAP_PATHS:
                urls = await _collect_sitemap(client, [urljoin(base_url, path)])
                if urls:
                    collected_urls = urls
                    crawl_layer_used = "layer2_common_sitemap"
                    break

        # ---- Layer 3: HTML parsing of target_url (not just homepage)
        #     If the user pointed at a product-list URL we harvest from there;
        #     otherwise from base.
        target_page = data.target_url
        if not target_page.startswith(("http://", "https://")):
            target_page = "https://" + target_page
        html_signals = await _harvest_html_links(client, target_page)
        if html_signals:
            if not collected_urls:
                collected_urls = [s["url"] for s in html_signals]
            if crawl_layer_used == "none":
                crawl_layer_used = "layer3_html"
        else:
            if crawl_layer_used == "none":
                warnings.append(f"Layer 3: no links harvested from {target_page}")

    if not collected_urls and not html_signals:
        warnings.append("All mechanical crawl layers yielded zero URLs; relying on LLM training knowledge only.")

    # ---- Layer 4: LLM classification
    model_id = await _resolve_model_id()
    model_region_overrides = await _resolve_model_region_overrides()
    own_names, peer_names = await _load_configured_names(data.client_id)

    signals_for_llm = html_signals if html_signals else [{"url": u, "text": ""} for u in collected_urls[:MAX_LLM_INPUT_URLS]]
    prompt = _build_llm_prompt(
        base_url,
        data.target_type,
        signals_for_llm,
        data.instruction,
        own_names,
        peer_names,
    )
    llm_out = await _call_llm(
        model_id,
        prompt,
        model_region_overrides=model_region_overrides,
    )
    if llm_out is None:
        warnings.append("Layer 4: LLM call failed or returned no JSON")
        llm_out = {"products": [], "tracked_urls": []}
    if crawl_layer_used == "none" and llm_out:
        crawl_layer_used = "layer4_llm_only"

    products = llm_out.get("products") or []
    tracked_urls = llm_out.get("tracked_urls") or []

    # ---- UPSERT products
    counts: Dict[str, int] = {candidate_type: 0, "tracked_url": 0}
    product_metadata_base = {
        "raw_llm_output_sample": products[:10],
        "crawl_layer_used": crawl_layer_used,
        "target_url": base_url,
        "target_type": data.target_type,
        "instruction": (data.instruction or "").strip() or None,
    }
    for p in products:
        if not isinstance(p, dict):
            continue
        name = (p.get("name") or "").strip()
        if not name:
            continue
        reasoning = (p.get("reasoning") or "")[:500]
        page_url = (p.get("page_url") or "").strip() or None
        try:
            await _upsert_candidate(
                client_id=data.client_id,
                candidate_string=name,
                candidate_type=candidate_type,
                topic_id=data.topic_id,
                target_entity_id=data.target_entity_id,
                target_type=data.target_type,
                metadata={
                    **product_metadata_base,
                    "reasoning": reasoning,
                    "page_url": page_url,
                    "grounding_sources": [s["url"] for s in signals_for_llm[:5]],
                },
            )
            counts[candidate_type] += 1
        except Exception as exc:
            logger.warning("Failed to upsert product candidate %s: %s", name, exc)

    # ---- UPSERT tracked_url candidates
    url_metadata_base = {
        "crawl_layer_used": crawl_layer_used,
        "target_url": base_url,
        "target_type": data.target_type,
    }
    seen_urls: Set[str] = set()
    for u in tracked_urls:
        if not isinstance(u, str):
            continue
        u_clean = u.strip()
        if not u_clean.startswith(("http://", "https://")):
            continue
        if u_clean in seen_urls:
            continue
        seen_urls.add(u_clean)
        try:
            await _upsert_candidate(
                client_id=data.client_id,
                candidate_string=u_clean,
                candidate_type="tracked_url",
                topic_id=data.topic_id,
                target_entity_id=data.target_entity_id,
                target_type=data.target_type,
                metadata=url_metadata_base,
            )
            counts["tracked_url"] += 1
        except Exception as exc:
            logger.warning("Failed to upsert tracked_url candidate %s: %s", u_clean, exc)

    return AutoDiscoveryCandidatesResponse(
        client_id=data.client_id,
        target_url=base_url,
        target_type=data.target_type,
        crawl_layer_used=crawl_layer_used,
        counts=counts,
        warnings=warnings,
        tracked_urls_captured=counts["tracked_url"],
    )
