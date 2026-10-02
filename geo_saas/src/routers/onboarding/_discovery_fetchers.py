"""
HTTP / sitemap / HTML navigation helpers for Auto-Discovery (Layers 1-3).

Phase 3A.5 refactor (2026-04-25): extracted from monolithic ``auto_discovery.py``.

Layered approach:
    - **Layer 1**: ``robots.txt`` → ``Sitemap:`` directives → walk sitemap tree.
    - **Layer 2**: try common sitemap paths (``/sitemap.xml`` etc) for sites
      that serve sitemaps but omit the ``robots.txt`` hint.
    - **Layer 3**: fetch homepage, extract ``<a>`` anchors from ``<nav>`` /
      ``<header>`` / role=navigation containers using a stdlib HTMLParser
      (no BeautifulSoup dependency).

Constants exposed at module level: ``USER_AGENT``, ``DEFAULT_HEADERS``,
``HTTP_TIMEOUT``, ``MAX_SITEMAP_URLS``, ``MAX_HTML_LINKS``, ``MAX_LLM_INPUT_URLS``,
``COMMON_SITEMAP_PATHS``, ``COMMON_CONTENT_PATHS``.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException

logger = logging.getLogger("GeoSaaSAPI.AutoDiscovery")

__all__ = [
    "USER_AGENT",
    "DEFAULT_HEADERS",
    "HTTP_TIMEOUT",
    "MAX_SITEMAP_URLS",
    "MAX_HTML_LINKS",
    "MAX_LLM_INPUT_URLS",
    "COMMON_SITEMAP_PATHS",
    "COMMON_CONTENT_PATHS",
    "normalize_base_url",
    "http_get",
    "fetch_robots_sitemaps",
    "parse_sitemap_xml",
    "collect_sitemap_urls",
    "NavLinkExtractor",
    "parse_html_navigation",
]


# Many brand sites (Cloudflare / Akamai / custom WAF) return 403 or silently drop
# requests whose User-Agent advertises a bot. We therefore impersonate a recent
# Chrome. This is standard practice for onboarding-time crawls and matches what
# Screaming Frog / Sitebulb do by default. The original bot UA is preserved in
# X-AnswerX-Crawler for any site owner auditing their logs.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "X-AnswerX-Crawler": "AnswerX-GEO/1.0 (+https://answer-x.ai)",
}
HTTP_TIMEOUT = 12.0
MAX_SITEMAP_URLS = 500
MAX_HTML_LINKS = 300
MAX_LLM_INPUT_URLS = 120
COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap_products.xml",
    "/sitemap_collections.xml",
    "/sitemaps/sitemap.xml",
]

# Layer 2.5: SPA sites frequently ship empty-shell homepages but still
# server-render product / collection index pages. Treat these as additional
# HTML signal sources so the LLM still gets real anchor text even when both
# the homepage and sitemaps are empty.
COMMON_CONTENT_PATHS = [
    "/products",
    "/collections",
    "/shop",
    "/store",
    "/category",
    "/categories",
    "/en-us/products",
    "/en/products",
    "/us/products",
]


# ─────────────────────────────────────────────────────────
# URL normalization + HTTP fetch
# ─────────────────────────────────────────────────────────

def normalize_base_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid website_url")
    return f"{parsed.scheme}://{parsed.netloc}"


async def http_get(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    try:
        resp = await client.get(url, follow_redirects=True, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200 and resp.text:
            return resp
        return None
    except Exception as exc:
        logger.debug("HTTP GET failed for %s: %s", url, exc)
        return None


# ─────────────────────────────────────────────────────────
# Layer 1 / 2 — Sitemap discovery
# ─────────────────────────────────────────────────────────

async def fetch_robots_sitemaps(
    client: httpx.AsyncClient, base_url: str,
) -> List[str]:
    resp = await http_get(client, urljoin(base_url, "/robots.txt"))
    if not resp:
        return []
    sitemaps = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            url = line.split(":", 1)[1].strip()
            if url:
                sitemaps.append(url)
    return sitemaps


def parse_sitemap_xml(xml_text: str) -> Tuple[List[str], List[str]]:
    """
    Parse a sitemap (or sitemap index) and return ``(sub_sitemap_urls, page_urls)``.
    """
    sub_sitemaps: List[str] = []
    page_urls: List[str] = []
    try:
        # Strip XML namespace to simplify parsing
        xml_text_clean = re.sub(r'\sxmlns="[^"]+"', "", xml_text, count=1)
        root = ET.fromstring(xml_text_clean)
    except Exception as exc:
        logger.debug("Sitemap parse failed: %s", exc)
        return sub_sitemaps, page_urls

    tag = root.tag.lower()
    if tag.endswith("sitemapindex"):
        for sm in root.findall(".//sitemap/loc"):
            if sm.text:
                sub_sitemaps.append(sm.text.strip())
    elif tag.endswith("urlset"):
        for url in root.findall(".//url/loc"):
            if url.text:
                page_urls.append(url.text.strip())
    return sub_sitemaps, page_urls


async def collect_sitemap_urls(
    client: httpx.AsyncClient, sitemap_urls: List[str],
) -> List[str]:
    """Walk sitemap (and sitemap index) trees, collecting all page URLs."""
    collected: List[str] = []
    seen: set = set()
    queue: List[str] = list(sitemap_urls)
    max_depth = 3
    depth = 0

    while queue and depth < max_depth and len(collected) < MAX_SITEMAP_URLS:
        next_queue: List[str] = []
        for sm_url in queue:
            if sm_url in seen:
                continue
            seen.add(sm_url)
            resp = await http_get(client, sm_url)
            if not resp:
                continue
            subs, pages = parse_sitemap_xml(resp.text)
            collected.extend(pages)
            next_queue.extend(subs)
            if len(collected) >= MAX_SITEMAP_URLS:
                break
        queue = next_queue
        depth += 1

    return collected[:MAX_SITEMAP_URLS]


# ─────────────────────────────────────────────────────────
# Layer 3 — HTML navigation parsing
# ─────────────────────────────────────────────────────────

class NavLinkExtractor(HTMLParser):
    """
    Stdlib-only HTML parser that extracts anchor links from navigation-like
    containers. Tracks ``<nav>``/``<header>``/``role=navigation`` nesting depth;
    any ``<a>`` encountered inside such a container (or inside an element whose
    class matches a menu-ish pattern) is recorded.

    Why stdlib instead of BeautifulSoup: zero extra deps, zero cold-start
    penalty on Cloud Run, and the navigation-extraction task is simple enough
    that a hand-rolled state machine is clearer than pulling in lxml.
    """

    _MENU_CLASS_RE = re.compile(
        r"\b(menu|nav(igation)?|main-menu|site-nav|primary-menu|header-nav)\b",
        re.IGNORECASE,
    )

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.base_netloc = urlparse(base_url).netloc
        # Stack of tag names that contributed a "+1" to nav depth. Popping
        # on matching close tags keeps the depth correct across arbitrary
        # nesting of nav/header/role-nav containers.
        self._nav_stack: List[str] = []
        self._current_href: Optional[str] = None
        self._current_text_parts: List[str] = []
        self._in_anchor = False
        self.links: List[Dict[str, str]] = []
        self._seen: set = set()
        self._saw_any_nav = False

    @property
    def _nav_depth(self) -> int:
        return len(self._nav_stack)

    def _is_menu_container(self, attrs_dict: Dict[str, str]) -> bool:
        role = (attrs_dict.get("role") or "").lower()
        if role == "navigation":
            return True
        cls = attrs_dict.get("class") or ""
        ident = attrs_dict.get("id") or ""
        combined = f"{cls} {ident}"
        return bool(self._MENU_CLASS_RE.search(combined))

    def handle_starttag(self, tag: str, attrs) -> None:
        if len(self.links) >= MAX_HTML_LINKS:
            return
        attrs_dict = {k: (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        if tag_lower in ("nav", "header") or self._is_menu_container(attrs_dict):
            self._nav_stack.append(tag_lower)
            self._saw_any_nav = True

        if tag_lower == "a" and self._nav_depth > 0:
            href = (attrs_dict.get("href") or "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                self._current_href = href
                self._current_text_parts = []
            self._in_anchor = True

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower == "a" and self._in_anchor:
            self._in_anchor = False
            if self._current_href is not None:
                full = urljoin(self.base_url, self._current_href)
                parsed = urlparse(full)
                # Same-origin only — we want internal nav, not social links
                if parsed.netloc == self.base_netloc and full not in self._seen:
                    text = " ".join(
                        t.strip() for t in self._current_text_parts if t.strip()
                    )[:200]
                    if text:
                        self._seen.add(full)
                        self.links.append({"url": full, "text": text})
            self._current_href = None
            self._current_text_parts = []

        # Pop nav stack on matching close tag. We pop the most recent entry
        # with the same tag name — this is robust against unbalanced tag
        # nesting (which real HTML frequently has) because we only pop when
        # we actually see the matching close.
        if self._nav_stack and tag_lower == self._nav_stack[-1]:
            self._nav_stack.pop()
        elif tag_lower in ("nav", "header", "div", "ul", "section") and self._nav_stack:
            # Fallback: if the top doesn't match but this is a container-ish
            # close tag and our stack's top is also container-ish, pop anyway
            # to avoid runaway depth on malformed markup.
            if self._nav_stack[-1] in ("nav", "header", "div", "ul", "section"):
                self._nav_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._current_href is not None and data.strip():
            self._current_text_parts.append(data)


async def parse_html_navigation(
    client: httpx.AsyncClient, base_url: str,
) -> List[Dict[str, str]]:
    """
    Fetch the homepage and pull ``<a>`` tags from ``<nav>`` / ``<header>`` and
    menu-like containers. Returns a list of ``{url, text}`` dicts.

    Uses stdlib ``html.parser.HTMLParser`` via ``NavLinkExtractor`` — no BS4 / lxml
    dependency so the Cloud Run image stays lean.
    """
    resp = await http_get(client, base_url)
    if not resp:
        return []

    extractor = NavLinkExtractor(base_url)
    try:
        extractor.feed(resp.text)
        extractor.close()
    except Exception as exc:
        logger.debug("HTML parse raised (continuing with whatever was captured): %s", exc)

    # Fallback: either (a) no nav/header element was ever encountered, or (b)
    # nav elements existed but yielded zero usable anchors (common with SPA
    # shells where the <nav> is there but its contents are rendered by JS).
    # Re-run treating the entire document as the navigation container so we
    # still get something useful for the LLM stage.
    if not extractor._saw_any_nav or not extractor.links:
        fallback = NavLinkExtractor(base_url)
        # Force "always in nav" mode by seeding the stack with a sentinel.
        # The matching close-tag logic will never pop this sentinel, so all
        # anchors in the document are candidates.
        fallback._nav_stack = ["_sentinel_force_"]
        try:
            fallback.feed(resp.text)
            fallback.close()
        except Exception:
            pass
        return fallback.links[:MAX_HTML_LINKS]

    return extractor.links[:MAX_HTML_LINKS]
