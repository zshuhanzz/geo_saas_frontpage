"""Citation Analysis service for AI-citable content generation.

This module is intentionally framework-light: it resolves template/user
configuration, selects tenant-scoped citation sources, performs deterministic
brand mention triage, optionally fetches source pages, and returns an aggregate
brief that can be injected into strategy/content/QA prompts.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import html
import ipaddress
import json
import logging
import re
import time
from typing import Any, Literal
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from google.genai import types as genai_types
from pydantic import BaseModel, Field, ValidationError

from llm.client import get_genai_client, get_model_id

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|svg)\b[^>]*>[\s\S]*?</\1>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title\b[^>]*>([\s\S]*?)</title>", re.IGNORECASE)
_BODY_RE = re.compile(r"<body\b[^>]*>([\s\S]*?)</body>", re.IGNORECASE)
_MAIN_BLOCK_RE = re.compile(r"<(article|main)\b[^>]*>([\s\S]*?)</\1>", re.IGNORECASE)
_TAG_WITH_ATTRS_RE = re.compile(r"<(meta|link)\b([^>]*)>", re.IGNORECASE)
_ATTR_RE = re.compile(r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"[^.!?。！？\n]{0,220}(?:[.!?。！？]|$)")
_PAGE_FETCH_CACHE_TTL_SECONDS = 60 * 60
_PAGE_FETCH_CACHE_MAX = 256
_PAGE_FETCH_CACHE: dict[str, tuple[float, str, str, dict[str, str]]] = {}
_NEGATIVE_HINTS = (
    "misleading",
    "wrong",
    "incorrect",
    "outdated",
    "broken",
    "doesn't",
    "does not",
    "can't",
    "cannot",
    "fails",
    "lack",
    "lacks",
    "expensive",
    "scam",
    "spam",
    "slop",
)
_COMPARISON_HINTS = (
    "alternative",
    "alternatives",
    "best",
    "compare",
    "comparison",
    "competitor",
    "competitors",
    "pricing",
    "pros and cons",
    "shortlist",
    "top ",
    "versus",
    " vs ",
)


@dataclass
class CitationAnalysisConfig:
    enabled: bool = False
    source_scope: str = "auto_by_template"
    brand_mention_policy: str = "triage_all"
    action_strategy: str = "auto"
    max_sources: int = 10
    fetch_full_pages: bool = True
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    query_override: str = ""
    llm_semantic_judgment: bool = True
    brief_rules: list[str] = field(default_factory=list)


@dataclass
class BrandMentionTriage:
    mention_state: str
    brand_mentioned: bool
    evidence: list[str] = field(default_factory=list)
    content_risk: str = "low"
    recommended_action: str = "new_content_gap"


@dataclass
class CitationSource:
    url: str
    domain: str
    citation_count: int
    domain_category: str | None = None
    prompt_examples: list[str] = field(default_factory=list)
    share_pct: float | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    page_text: str = ""
    page_title: str = ""
    meta_description: str = ""
    canonical_url: str = ""
    fetch_status: str = "not_fetched"
    triage: BrandMentionTriage | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "citation_count": self.citation_count,
            "domain_category": self.domain_category or "Other",
            "prompt_examples": self.prompt_examples[:3],
            "share_pct": self.share_pct,
            "page_title": self.page_title,
            "meta_description": self.meta_description,
            "canonical_url": self.canonical_url,
            "fetch_status": self.fetch_status,
            "triage": self.triage.__dict__ if self.triage else None,
        }


class LlmTriageItem(BaseModel):
    index: int
    brand_mentioned: bool
    mention_state: Literal["unmentioned", "positive_neutral", "negative_misleading", "ambiguous"]
    evidence: list[str] = Field(default_factory=list, max_length=3)
    content_risk: Literal["low", "medium", "high"] = "medium"
    recommended_action: Literal[
        "new_content_gap",
        "refresh_extractability",
        "clarification_rebuttal",
        "internal_linking",
        "third_party_nurture",
    ] = "new_content_gap"


class LlmTriageResponse(BaseModel):
    items: list[LlmTriageItem] = Field(default_factory=list)


def _coerce_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _split_domains(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = []
    out: list[str] = []
    for item in raw_items:
        domain = str(item or "").strip().lower()
        if domain and domain not in out:
            out.append(domain)
    return out


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = [value]
    else:
        raw_items = []
    out: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _coerce_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 20) -> int:
    try:
        num = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, num))


def resolve_citation_analysis_config(
    *,
    inputs: dict[str, Any],
    template_runtime_config: dict[str, Any],
) -> CitationAnalysisConfig:
    """Merge template-level citation config with submitted wizard fields."""
    top = _coerce_object(template_runtime_config.get("citation_analysis"))
    step = _coerce_object(template_runtime_config.get("citation_analysis_step"))
    submitted = _coerce_object(inputs.get("citation_analysis"))

    enabled_raw = submitted.get("enabled")
    if enabled_raw is None:
        enabled_raw = step.get("enabled")
    if enabled_raw is None:
        enabled_raw = top.get("enabled")

    return CitationAnalysisConfig(
        enabled=bool(enabled_raw),
        source_scope=str(
            submitted.get("citation_source_scope")
            or step.get("citation_source_scope")
            or top.get("source_selection", {}).get("source_scope")
            or "auto_by_template"
        ),
        brand_mention_policy=str(
            submitted.get("citation_brand_mention_policy")
            or step.get("citation_brand_mention_policy")
            or "triage_all"
        ),
        action_strategy=str(
            submitted.get("citation_action_strategy")
            or step.get("citation_action_strategy")
            or "auto"
        ),
        max_sources=_coerce_int(
            submitted.get("citation_max_sources", step.get("citation_max_sources")),
            _coerce_int(top.get("source_selection", {}).get("max_sources"), 10),
            maximum=30,
        ),
        fetch_full_pages=bool(
            submitted.get("citation_fetch_full_pages")
            if "citation_fetch_full_pages" in submitted
            else step.get(
                "citation_fetch_full_pages",
                top.get("source_selection", {}).get("fetch_full_pages", True),
            )
        ),
        include_domains=_split_domains(
            submitted.get("citation_include_domains", step.get("citation_include_domains"))
        ),
        exclude_domains=_split_domains(
            submitted.get("citation_exclude_domains", step.get("citation_exclude_domains"))
        ),
        query_override=str(
            submitted.get("citation_query_override")
            or step.get("citation_query_override")
            or ""
        ).strip(),
        llm_semantic_judgment=bool(
            top.get("brand_mention_triage", {}).get("layer_2_llm_semantic_judgment", True)
        ),
        brief_rules=_coerce_string_list(top.get("brief_rules")),
    )


def build_citation_analysis_fingerprint(
    *,
    inputs: dict[str, Any],
    template_runtime_config: dict[str, Any],
) -> str:
    """Return a stable fingerprint for Citation Analysis preflight reuse.

    The hash intentionally includes only fields that change citation source
    selection, not free-form strategy edits or final generation settings.
    """
    config = resolve_citation_analysis_config(
        inputs=inputs,
        template_runtime_config=template_runtime_config,
    )
    payload = {
        "config": {
            "enabled": config.enabled,
            "source_scope": resolve_effective_source_scope(config.source_scope, inputs),
            "brand_mention_policy": config.brand_mention_policy,
            "action_strategy": config.action_strategy,
            "max_sources": config.max_sources,
            "fetch_full_pages": config.fetch_full_pages,
            "include_domains": config.include_domains,
            "exclude_domains": config.exclude_domains,
            "query_override": config.query_override,
            "llm_semantic_judgment": config.llm_semantic_judgment,
            "brief_rules": config.brief_rules,
        },
        "inputs": {
            "content_type": inputs.get("content_type") or "",
            "publish_platform": inputs.get("publish_platform") or "",
            "target_prompt_ids": sorted(str(v) for v in (inputs.get("target_prompt_ids") or []) if str(v).strip()),
            "prompt_ids": sorted(str(v) for v in (inputs.get("prompt_ids") or []) if str(v).strip()),
            "topic_ids": sorted(str(v) for v in (inputs.get("topic_ids") or []) if str(v).strip()),
        },
        "template": {
            "platform_profile": template_runtime_config.get("platform_profile") or "",
            "template_group": template_runtime_config.get("template_group") or "",
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_brand_aliases(brand_context: dict[str, Any]) -> list[str]:
    aliases: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text.lower() not in {a.lower() for a in aliases}:
            aliases.append(text)

    add(brand_context.get("brand_name"))
    for brand in brand_context.get("own_brands") or []:
        if not isinstance(brand, dict):
            continue
        add(brand.get("brand_name"))
        for alias in brand.get("aliases") or []:
            add(alias)
    return aliases


def _find_evidence(text: str, aliases: list[str]) -> list[str]:
    if not text or not aliases:
        return []
    lowered = text.lower()
    evidence: list[str] = []
    for alias in aliases:
        needle = alias.lower()
        pos = lowered.find(needle)
        if pos < 0:
            continue
        start = max(0, pos - 120)
        end = min(len(text), pos + len(alias) + 160)
        snippet = _SPACE_RE.sub(" ", text[start:end]).strip()
        if snippet:
            evidence.append(snippet)
    return evidence[:3]


def _has_negative_context(text: str, evidence: list[str]) -> bool:
    window = " ".join(evidence) if evidence else text[:600]
    lowered = window.lower()
    return any(hint in lowered for hint in _NEGATIVE_HINTS)


def triage_citation_source(
    source: CitationSource,
    brand_aliases: list[str],
) -> BrandMentionTriage:
    haystack = "\n".join([
        source.url or "",
        source.domain or "",
        source.page_text or "",
    ])
    evidence = _find_evidence(haystack, brand_aliases)
    brand_mentioned = bool(evidence)
    if not brand_mentioned:
        return BrandMentionTriage(
            mention_state="unmentioned",
            brand_mentioned=False,
            evidence=[],
            content_risk="low",
            recommended_action="new_content_gap",
        )

    if _has_negative_context(haystack, evidence):
        return BrandMentionTriage(
            mention_state="negative_misleading",
            brand_mentioned=True,
            evidence=evidence,
            content_risk="high",
            recommended_action="clarification_rebuttal",
        )

    return BrandMentionTriage(
        mention_state="positive_neutral",
        brand_mentioned=True,
        evidence=evidence,
        content_risk="low",
        recommended_action="refresh_extractability",
    )


def resolve_effective_source_scope(source_scope: str, inputs: dict[str, Any]) -> str:
    """Resolve template/user source scope into the concrete citation query scope."""
    scope = (source_scope or "auto_by_template").lower()
    if scope != "auto_by_template":
        return scope

    platform = str(
        inputs.get("platform_profile")
        or inputs.get("publish_platform")
        or inputs.get("content_type")
        or ""
    ).lower()
    if "reddit" in platform:
        return "reddit_citations"
    if any(token in platform for token in ("official", "website", "site", "blog", "article")):
        return "official_article_citations"
    return "all_prompt_citations"


def apply_brand_mention_policy(
    sources: list[CitationSource],
    config: CitationAnalysisConfig,
) -> list[CitationSource]:
    """Order citation samples according to the configured brand triage policy."""
    policy = (config.brand_mention_policy or "triage_all").lower()
    priority_by_policy = {
        "prioritize_unmentioned": {
            "unmentioned": 0,
            "negative_misleading": 1,
            "ambiguous": 2,
            "positive_neutral": 3,
        },
        "amplify_positive_neutral": {
            "positive_neutral": 0,
            "unmentioned": 1,
            "ambiguous": 2,
            "negative_misleading": 3,
        },
        "clarify_negative_misleading": {
            "negative_misleading": 0,
            "ambiguous": 1,
            "positive_neutral": 2,
            "unmentioned": 3,
        },
    }
    priorities = priority_by_policy.get(policy)
    if not priorities:
        return sources[: config.max_sources]

    def sort_key(source: CitationSource) -> tuple[int, int]:
        state = source.triage.mention_state if source.triage else "ambiguous"
        return (priorities.get(state, 9), -int(source.citation_count or 0))

    return sorted(sources, key=sort_key)[: config.max_sources]


def _clean_extracted_text(value: str, max_chars: int = 8000) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", value or "")
    text = _HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text[:max_chars]


def _extract_tag_attrs(attrs_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(attrs_text or ""):
        attrs[match.group(1).lower()] = html.unescape(match.group(3)).strip()
    return attrs


def extract_page_content(
    raw_text: str,
    *,
    content_type: str = "",
    source_url: str = "",
    max_chars: int = 8000,
) -> dict[str, str]:
    """Extract readable page text plus lightweight metadata from fetched content."""
    raw_text = raw_text or ""
    is_html = "html" in (content_type or "").lower() or "<html" in raw_text[:800].lower()
    if not is_html:
        return {
            "text": _SPACE_RE.sub(" ", raw_text).strip()[:max_chars],
            "title": "",
            "meta_description": "",
            "canonical_url": source_url,
        }

    title = ""
    title_match = _TITLE_RE.search(raw_text)
    if title_match:
        title = _clean_extracted_text(title_match.group(1), max_chars=240)

    meta_description = ""
    canonical_url = source_url
    for tag_match in _TAG_WITH_ATTRS_RE.finditer(raw_text):
        tag = tag_match.group(1).lower()
        attrs = _extract_tag_attrs(tag_match.group(2))
        if tag == "meta" and not meta_description:
            meta_name = (attrs.get("name") or attrs.get("property") or "").lower()
            if meta_name in {"description", "og:description", "twitter:description"}:
                meta_description = attrs.get("content", "")[:500]
        elif tag == "link":
            rel = (attrs.get("rel") or "").lower()
            if "canonical" in rel and attrs.get("href"):
                canonical_url = urljoin(source_url, attrs["href"])

    main_blocks = [m.group(2) for m in _MAIN_BLOCK_RE.finditer(raw_text)]
    if main_blocks:
        content_html = max(main_blocks, key=len)
    else:
        body_match = _BODY_RE.search(raw_text)
        content_html = body_match.group(1) if body_match else raw_text

    return {
        "text": _clean_extracted_text(content_html, max_chars=max_chars),
        "title": title,
        "meta_description": meta_description,
        "canonical_url": canonical_url,
    }


def looks_like_reddit_verification_page(text: str) -> bool:
    """Detect Reddit anti-bot / verification shells that are useless as evidence."""
    lowered = (text or "").lower()
    return (
        "please wait for verification" in lowered
        or "your request has been blocked" in lowered
        or ("reddit" in lowered and "blocked by network security" in lowered)
    )


def build_reddit_fetch_candidates(url: str) -> list[str]:
    """Build public Reddit fallbacks for a comments URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "reddit.com" not in host:
        return []

    path = parsed.path or "/"
    if "/comments/" not in path:
        return []
    clean_path = "/" + path.strip("/")
    json_path = clean_path if clean_path.endswith(".json") else f"{clean_path}.json"
    return list(dict.fromkeys([
        f"https://www.reddit.com{json_path}?raw_json=1",
        f"https://api.reddit.com{clean_path}/?raw_json=1",
        f"https://old.reddit.com{clean_path}/",
    ]))


def extract_reddit_json_content(
    raw_json: str,
    *,
    source_url: str,
    max_chars: int = 8000,
) -> dict[str, str]:
    """Extract readable post + top-comment excerpts from Reddit listing JSON."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return {"text": "", "title": "", "meta_description": "", "canonical_url": source_url}

    if not isinstance(data, list) or not data:
        return {"text": "", "title": "", "meta_description": "", "canonical_url": source_url}

    post_data: dict[str, Any] = {}
    try:
        post_children = data[0]["data"]["children"]
        if post_children:
            post_data = post_children[0]["data"]
    except (KeyError, TypeError, IndexError):
        post_data = {}

    title = str(post_data.get("title") or "").strip()
    selftext = str(post_data.get("selftext") or "").strip()
    subreddit = str(post_data.get("subreddit") or "").strip()
    permalink = str(post_data.get("permalink") or "").strip()
    canonical_url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else source_url

    lines: list[str] = []
    if title:
        lines.append(f"Title: {title}")
    if subreddit:
        lines.append(f"Subreddit: r/{subreddit}")
    if post_data.get("score") is not None:
        lines.append(f"Score: {post_data.get('score')}")
    if post_data.get("num_comments") is not None:
        lines.append(f"Comments: {post_data.get('num_comments')}")
    if selftext:
        lines.extend(["", selftext])

    comment_lines: list[str] = []
    try:
        comment_children = data[1]["data"]["children"]
    except (KeyError, TypeError, IndexError):
        comment_children = []
    for child in comment_children[:8]:
        body = str(((child or {}).get("data") or {}).get("body") or "").strip()
        if not body or body in {"[deleted]", "[removed]"}:
            continue
        score = ((child or {}).get("data") or {}).get("score")
        prefix = f"- Comment ({score}): " if score is not None else "- Comment: "
        comment_lines.append(prefix + _SPACE_RE.sub(" ", body)[:700])
    if comment_lines:
        lines.extend(["", "Top comments:", *comment_lines])

    text = _SPACE_RE.sub(" ", "\n".join(lines)).strip()
    return {
        "text": text[:max_chars],
        "title": title,
        "meta_description": f"Reddit discussion in r/{subreddit}" if subreddit else "Reddit discussion",
        "canonical_url": canonical_url,
    }


def _download_url(url: str, *, timeout: float) -> tuple[str, str]:
    req = Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (compatible; AnswerX-GEO-CitationAnalysis/1.0; "
            "+https://answerx.ai)"
        ),
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    })
    with urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("content-type", "")
        raw = resp.read(800_000)
    return raw.decode("utf-8", errors="ignore"), ctype


def _extract_url_content(
    url: str,
    raw_text: str,
    content_type: str,
    *,
    max_chars: int,
) -> tuple[str, str, dict[str, str]]:
    host = (urlparse(url).hostname or "").lower()
    if "reddit.com" in host and ("json" in content_type.lower() or url.endswith(".json?raw_json=1") or "api.reddit.com" in url):
        extracted = extract_reddit_json_content(raw_text, source_url=url, max_chars=max_chars)
    else:
        extracted = extract_page_content(
            raw_text,
            content_type=content_type,
            source_url=url,
            max_chars=max_chars,
        )
    page_text = extracted.get("text", "")
    metadata = {
        "title": extracted.get("title", ""),
        "meta_description": extracted.get("meta_description", ""),
        "canonical_url": extracted.get("canonical_url", url),
    }
    status = "fetched" if page_text else "empty"
    if looks_like_reddit_verification_page(page_text):
        status = "reddit_verification_page"
    return page_text, status, metadata


def _append_where(
    parts: list[str],
    params: list[Any],
    clause: str,
    value: Any,
) -> None:
    params.append(value)
    parts.append(clause.format(idx=len(params)))


def build_citation_source_query(
    *,
    client_id: str,
    inputs: dict[str, Any],
    config: CitationAnalysisConfig,
) -> tuple[str, list[Any]]:
    """Build tenant-scoped SQL and positional params for citation source selection."""
    params: list[Any] = [client_id]
    where = [
        "c.client_id = $1::uuid",
        "cp.client_id = c.client_id",
        "c.source_url IS NOT NULL",
        "c.source_url <> ''",
    ]

    prompt_ids = [str(v) for v in inputs.get("target_prompt_ids") or [] if str(v).strip()]
    if prompt_ids:
        _append_where(where, params, "c.client_prompt_id = ANY(${idx}::uuid[])", prompt_ids)

    topic_ids = [str(v) for v in inputs.get("topic_ids") or [] if str(v).strip()]
    if topic_ids:
        _append_where(where, params, "cp.topic_id = ANY(${idx}::uuid[])", topic_ids)

    scope = resolve_effective_source_scope(config.source_scope, inputs)
    if scope == "reddit_citations":
        where.append("LOWER(c.source_domain) LIKE '%reddit.com'")
    elif scope == "official_article_citations":
        where.append(
            "LOWER(COALESCE(c.source_domain, '')) NOT LIKE '%reddit.com' "
            "AND LOWER(COALESCE(c.source_domain, '')) NOT LIKE '%youtube.com' "
            "AND LOWER(COALESCE(c.source_domain, '')) NOT LIKE '%instagram.com' "
            "AND LOWER(COALESCE(c.source_domain, '')) NOT LIKE '%tiktok.com'"
        )

    for domain in config.include_domains:
        _append_where(where, params, "LOWER(c.source_domain) LIKE '%' || ${idx} || '%'", domain)
    for domain in config.exclude_domains:
        _append_where(where, params, "LOWER(c.source_domain) NOT LIKE '%' || ${idx} || '%'", domain)

    if config.query_override:
        params.append(f"%{config.query_override}%")
        idx = len(params)
        where.append(
            f"(cp.text ILIKE ${idx} OR c.source_url ILIKE ${idx} OR c.source_domain ILIKE ${idx})"
        )

    params.append(config.max_sources)
    limit_idx = len(params)
    sql = f"""
        SELECT
            c.source_url,
            c.source_domain,
            COUNT(*)::int AS citation_count,
            MIN(c.domain_category) AS domain_category,
            (ARRAY_REMOVE(ARRAY_AGG(DISTINCT cp.text), NULL))[1:3] AS prompt_examples,
            MIN(c.executed_at)::text AS first_seen,
            MAX(c.executed_at)::text AS last_seen
        FROM geo_citations c
        JOIN geo_client_prompts cp
          ON cp.id = c.client_prompt_id
         AND cp.client_id = c.client_id
        WHERE {' AND '.join(where)}
        GROUP BY c.source_url, c.source_domain
        ORDER BY COUNT(*) DESC, c.source_url ASC
        LIMIT ${limit_idx}
    """
    return sql, params


async def fetch_citation_sources(
    pool,
    *,
    client_id: str,
    inputs: dict[str, Any],
    config: CitationAnalysisConfig,
) -> list[CitationSource]:
    sql, params = build_citation_source_query(client_id=client_id, inputs=inputs, config=config)
    rows = await pool.fetch(sql, *params)
    total = sum(int(r["citation_count"] or 0) for r in rows) or 0
    sources: list[CitationSource] = []
    for row in rows:
        count = int(row["citation_count"] or 0)
        sources.append(CitationSource(
            url=row["source_url"] or "",
            domain=row["source_domain"] or "",
            citation_count=count,
            domain_category=row["domain_category"] or "Other",
            prompt_examples=list(row["prompt_examples"] or []),
            share_pct=round(count / total * 100, 2) if total else None,
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
        ))
    return sources


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return True


def _fetch_url_text_sync(url: str, timeout: float = 5.0, max_chars: int = 8000) -> tuple[str, str, dict[str, str]]:
    if not _is_public_http_url(url):
        return "", "skipped_non_public_url", {"canonical_url": url}
    cached = _PAGE_FETCH_CACHE.get(url)
    now = time.monotonic()
    if cached and (now - cached[0]) < _PAGE_FETCH_CACHE_TTL_SECONDS:
        return cached[1], cached[2], dict(cached[3])
    try:
        text, ctype = _download_url(url, timeout=timeout)
        page_text, status, metadata = _extract_url_content(
            url,
            text,
            ctype,
            max_chars=max_chars,
        )
        if status in {"empty", "reddit_verification_page"}:
            for fallback_url in build_reddit_fetch_candidates(url):
                try:
                    fallback_text, fallback_ctype = _download_url(fallback_url, timeout=timeout)
                    fallback_page_text, fallback_status, fallback_metadata = _extract_url_content(
                        fallback_url,
                        fallback_text,
                        fallback_ctype,
                        max_chars=max_chars,
                    )
                    if fallback_status == "fetched" and fallback_page_text:
                        page_text = fallback_page_text
                        status = "reddit_json_fetched" if "json" in fallback_url else "reddit_fallback_fetched"
                        metadata = fallback_metadata
                        break
                except Exception as fallback_exc:
                    logger.info(
                        "[CITATION] reddit fallback fetch failed url=%s error=%s",
                        fallback_url,
                        fallback_exc,
                    )
        if len(_PAGE_FETCH_CACHE) >= _PAGE_FETCH_CACHE_MAX:
            oldest_key = min(_PAGE_FETCH_CACHE, key=lambda k: _PAGE_FETCH_CACHE[k][0])
            _PAGE_FETCH_CACHE.pop(oldest_key, None)
        _PAGE_FETCH_CACHE[url] = (now, page_text, status, metadata)
        return page_text, status, metadata
    except Exception as exc:
        logger.info("[CITATION] page fetch failed url=%s error=%s", url, exc)
        return "", "fetch_failed", {"canonical_url": url}


async def fetch_page_text(url: str) -> tuple[str, str, dict[str, str]]:
    return await asyncio.to_thread(_fetch_url_text_sync, url)


async def hydrate_source_pages(
    sources: list[CitationSource],
    *,
    enabled: bool,
    max_concurrency: int = 4,
) -> None:
    if not enabled or not sources:
        return
    sem = asyncio.Semaphore(max_concurrency)

    async def hydrate(source: CitationSource) -> None:
        async with sem:
            source.page_text, source.fetch_status, metadata = await fetch_page_text(source.url)
            source.page_title = metadata.get("title", "")
            source.meta_description = metadata.get("meta_description", "")
            source.canonical_url = metadata.get("canonical_url", source.url)

    await asyncio.gather(*(hydrate(source) for source in sources))


def needs_llm_triage(source: CitationSource, triage: BrandMentionTriage) -> bool:
    if not source.page_text:
        return False
    if triage.mention_state in {"positive_neutral", "negative_misleading", "ambiguous"}:
        return True
    if triage.mention_state == "unmentioned":
        lowered = source.page_text[:4000].lower()
        return any(hint in lowered for hint in _COMPARISON_HINTS)
    return False


def parse_llm_triage_response(data: Any) -> LlmTriageResponse:
    """Validate and normalize Gemini triage JSON; invalid items are dropped."""
    if not isinstance(data, dict):
        return LlmTriageResponse()
    valid_items: list[LlmTriageItem] = []
    for raw_item in data.get("items") or []:
        try:
            valid_items.append(LlmTriageItem.model_validate(raw_item))
        except ValidationError as exc:
            logger.info("[CITATION] Dropping invalid LLM triage item: %s", exc)
    return LlmTriageResponse(items=valid_items)


async def apply_llm_semantic_triage(
    sources: list[CitationSource],
    *,
    brand_aliases: list[str],
    enabled: bool,
    max_pages: int = 5,
) -> None:
    """Use Flash for ambiguous/brand-mentioned pages and keep rule fallback on failure."""
    if not enabled or not brand_aliases:
        return
    candidates = [
        source for source in sources
        if source.triage and needs_llm_triage(source, source.triage)
    ][:max_pages]
    if not candidates:
        return

    payload = [{
        "index": i,
        "url": s.url,
        "domain": s.domain,
        "current_rule_triage": s.triage.__dict__ if s.triage else None,
        "page_excerpt": s.page_text[:2500],
    } for i, s in enumerate(candidates)]

    prompt = f"""You are doing Brand Mention Triage for GEO citation analysis.

Brand aliases:
{json.dumps(brand_aliases, ensure_ascii=False)}

For each page, classify whether the brand is unmentioned, positive/neutral,
negative/misleading, or ambiguous. Use only the excerpt. Return JSON:
{{"items":[{{"index":0,"brand_mentioned":true,"mention_state":"positive_neutral|negative_misleading|unmentioned|ambiguous","evidence":["short evidence"],"content_risk":"low|medium|high","recommended_action":"new_content_gap|refresh_extractability|clarification_rebuttal|internal_linking|third_party_nurture"}}]}}

Pages:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""
    try:
        model_id = await get_model_id("flash")
        client = await get_genai_client(model_id, role="flash")
        resp = await client.aio.models.generate_content(
            model=model_id,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(resp.text or "{}")
        parsed = parse_llm_triage_response(data)
    except Exception as exc:
        logger.warning("[CITATION] LLM semantic triage failed; keeping rule triage: %s", exc)
        return

    for item in parsed.items:
        try:
            source = candidates[int(item.index)]
        except Exception:
            continue
        source.triage = BrandMentionTriage(
            mention_state=item.mention_state,
            brand_mentioned=item.brand_mentioned,
            evidence=[str(v) for v in item.evidence][:3],
            content_risk=item.content_risk,
            recommended_action=item.recommended_action,
        )


def decide_primary_action(summary: dict[str, int], config: CitationAnalysisConfig) -> tuple[str, str]:
    if config.action_strategy and config.action_strategy != "auto":
        return config.action_strategy, "User/template selected a fixed Citation content action."
    policy = (config.brand_mention_policy or "triage_all").lower()
    if policy == "prioritize_unmentioned" and summary.get("unmentioned", 0) > 0:
        return (
            "new_content_gap",
            "Brand Mention Triage policy prioritizes high-citation pages that do not yet mention the customer brand.",
        )
    if policy == "amplify_positive_neutral" and summary.get("positive_neutral", 0) > 0:
        return (
            "refresh_extractability",
            "Brand Mention Triage policy prioritizes existing positive/neutral citation assets for refresh, extractability, and adjacent coverage.",
        )
    if policy == "clarify_negative_misleading" and summary.get("negative_misleading", 0) > 0:
        return (
            "clarification_rebuttal",
            "Brand Mention Triage policy prioritizes negative, outdated, incomplete, or potentially misleading brand mentions.",
        )
    if summary.get("negative_misleading", 0) > 0:
        return (
            "clarification_rebuttal",
            "At least one cited source appears to contain negative, outdated, incomplete, or potentially misleading brand information.",
        )
    if summary.get("unmentioned", 0) >= max(summary.get("positive_neutral", 0), 1):
        return (
            "new_content_gap",
            "Most useful citation examples do not mention the customer brand, so the best opportunity is a new brand-relevant content gap.",
        )
    if summary.get("positive_neutral", 0) > 0:
        return (
            "refresh_extractability",
            "The brand already appears in citation assets, so improve extractability, adjacent coverage, and internal linking instead of duplicating the same angle.",
        )
    return "new_content_gap", "No strong brand citation asset was found; create a prompt-first content asset."


def _source_pattern_text(source: CitationSource) -> str:
    return " ".join([
        source.page_title or "",
        source.meta_description or "",
        source.page_text[:2500] if source.page_text else "",
        " ".join(source.prompt_examples or []),
    ]).lower()


def _learnable_strengths_for_source(source: CitationSource) -> list[str]:
    """Infer why a cited page is likely useful to AI answers.

    This is intentionally lightweight and deterministic. Citation Analysis is
    not trying to copy cited pages; it extracts reusable structural advantages
    that later prompts can combine with the customer brand gap.
    """
    text = _source_pattern_text(source)
    domain = (source.domain or "").lower()
    strengths: list[str] = []

    def add(label: str) -> None:
        if label not in strengths:
            strengths.append(label)

    if "reddit.com" in domain:
        add("community-native discussion format")
        if any(token in text for token in ("i tested", "i tried", "my workflow", "my stack", "field notes")):
            add("first-person or field-tested framing")
        if any(token in text for token in ("comment", "comments", "what actually", "anyone", "worth it")):
            add("practical tradeoffs and peer validation")

    if any(token in text for token in ("best ", "top ", "ranked", "shortlist", "compare", "comparison", " vs ")):
        add("direct-answer comparison structure")
    if any(token in text for token in ("workflow", "step-by-step", "how to", "guide", "checklist")):
        add("workflow or checklist structure")
    if any(token in text for token in ("pros and cons", "tradeoff", "limitations", "pricing", "cost", "subscription")):
        add("explicit tradeoff or limitation framing")
    if any(token in text for token in ("faq", "question", "answer", "what is", "how do")):
        add("FAQ-friendly answer blocks")
    if any(token in text for token in ("2026", "may 2026", "updated", "current")):
        add("freshness signal")
    if source.citation_count >= 5:
        add("high citation frequency signal")
    if source.fetch_status in {"fetch_failed", "empty", "reddit_verification_page"}:
        add("limited readable evidence; use only URL/title-level pattern")

    return strengths[:5]


def _visibility_gaps_for_source(source: CitationSource) -> list[str]:
    triage = source.triage
    if not triage:
        return ["brand mention state is unknown; keep claims conservative"]
    if triage.mention_state == "unmentioned":
        return [
            "customer brand is missing from an already-cited source pattern",
            "new content should reuse the useful structure while adding a conservative brand-fit angle",
        ]
    if triage.mention_state == "positive_neutral":
        return [
            "customer brand already appears; improve extractability, adjacent coverage, or internal linking instead of duplicating the same angle",
        ]
    if triage.mention_state == "negative_misleading":
        return [
            "customer brand appears in a negative, outdated, incomplete, or potentially misleading context",
            "new content should clarify, correct, compare, or troubleshoot rather than imitate the cited page",
        ]
    return ["brand mention is ambiguous; avoid overstating brand relationship and use cautious evidence language"]


def analyze_citation_source_patterns(sources: list[CitationSource]) -> dict[str, Any]:
    learnable_strengths: list[str] = []
    visibility_gaps: list[str] = []
    source_summaries: list[dict[str, Any]] = []

    def add_unique(target: list[str], values: list[str]) -> None:
        for value in values:
            if value and value not in target:
                target.append(value)

    for source in sorted(sources, key=lambda s: s.citation_count, reverse=True)[:8]:
        strengths = _learnable_strengths_for_source(source)
        gaps = _visibility_gaps_for_source(source)
        add_unique(learnable_strengths, strengths)
        add_unique(visibility_gaps, gaps)
        source_summaries.append({
            "url": source.url,
            "domain": source.domain,
            "citation_count": source.citation_count,
            "mention_state": source.triage.mention_state if source.triage else "unknown",
            "fetch_status": source.fetch_status,
            "learnable_strengths": strengths,
            "visibility_gaps": gaps,
        })

    return {
        "learnable_strengths": learnable_strengths[:8],
        "visibility_gaps": visibility_gaps[:8],
        "source_summaries": source_summaries,
    }


def build_citation_grounded_brief(
    *,
    config: CitationAnalysisConfig,
    sources: list[CitationSource],
    summary: dict[str, int],
    primary_action: str,
    rationale: str,
    platform_profile: str,
    source_patterns: dict[str, Any] | None = None,
) -> str:
    top_sources = sorted(sources, key=lambda s: s.citation_count, reverse=True)[:5]
    source_lines = [
        f"- {s.domain} — {s.citation_count} citations; state={s.triage.mention_state if s.triage else 'unknown'}; url={s.url}"
        for s in top_sources
    ]
    if not source_lines:
        source_lines = ["- No matching citation pages were found for the selected prompt/topic scope."]

    rules = config.brief_rules or [
        "Citation data is a source of truth for structure, extractability patterns, and content gaps; do not copy cited pages.",
        "If sources are unmentioned: learn the structure and add a relevant, evidence-conservative brand angle.",
        "If sources are positive/neutral: treat them as citation assets; prefer adjacent prompts, refresh, internal linking, or support pages.",
        "If sources are negative/misleading: Do not imitate; write clarification, comparison, rebuttal, troubleshooting, or evidence-correcting content.",
    ]

    source_patterns = source_patterns if isinstance(source_patterns, dict) else {}
    learnable_strengths = source_patterns.get("learnable_strengths") or []
    visibility_gaps = source_patterns.get("visibility_gaps") or []
    if not learnable_strengths:
        learnable_strengths = ["No strong reusable source pattern was detected; keep the article prompt-first and evidence-conservative."]
    if not visibility_gaps:
        visibility_gaps = ["No explicit customer visibility gap was detected; keep brand claims conservative and improve extractability."]

    return "\n".join([
        "## Citation Analysis Summary（硬约束）",
        f"- Source scope: {config.source_scope}",
        f"- Brand mention summary: {json.dumps(summary, ensure_ascii=False)}",
        f"- Primary content action: {primary_action}",
        f"- Rationale: {rationale}",
        "",
        "### Top cited source patterns",
        "\n".join(source_lines),
        "",
        "### Why AI likely cites these sources (patterns to learn)",
        "\n".join(f"- {item}" for item in learnable_strengths),
        "",
        "### Gaps to fill for customer GEO visibility",
        "\n".join(f"- {item}" for item in visibility_gaps),
        "",
        "### Writing constraints from Citation Analysis",
        "\n".join(f"- {rule}" for rule in rules),
        "",
    ])


def build_citation_analysis_result(
    *,
    config: CitationAnalysisConfig,
    sources: list[CitationSource],
    brand_aliases: list[str],
    platform_profile: str,
) -> dict[str, Any]:
    summary = {
        "unmentioned": 0,
        "positive_neutral": 0,
        "negative_misleading": 0,
        "ambiguous": 0,
    }
    for source in sources:
        if not source.triage:
            source.triage = triage_citation_source(source, brand_aliases)
        if source.triage.mention_state in summary:
            summary[source.triage.mention_state] += 1
        else:
            summary["ambiguous"] += 1

    primary_action, rationale = decide_primary_action(summary, config)
    source_patterns = analyze_citation_source_patterns(sources)
    brief = build_citation_grounded_brief(
        config=config,
        sources=sources,
        summary=summary,
        primary_action=primary_action,
        rationale=rationale,
        platform_profile=platform_profile,
        source_patterns=source_patterns,
    )
    return {
        "enabled": True,
        "fingerprint": build_citation_analysis_fingerprint(
            inputs={"citation_analysis": {
                "enabled": config.enabled,
                "citation_source_scope": config.source_scope,
                "citation_brand_mention_policy": config.brand_mention_policy,
                "citation_action_strategy": config.action_strategy,
                "citation_max_sources": config.max_sources,
                "citation_fetch_full_pages": config.fetch_full_pages,
                "citation_include_domains": ",".join(config.include_domains),
                "citation_exclude_domains": ",".join(config.exclude_domains),
                "citation_query_override": config.query_override,
            }},
            template_runtime_config={
                "citation_analysis": {"enabled": config.enabled},
                "platform_profile": platform_profile,
            },
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(sources),
        "brand_aliases": brand_aliases,
        "brand_mention_summary": summary,
        "content_action_decision": {
            "primary_action": primary_action,
            "rationale": rationale,
        },
        "citation_source_patterns": source_patterns,
        "citation_sources": [s.public_dict() for s in sources[: config.max_sources]],
        "citation_grounded_brief": brief,
    }


async def run_citation_analysis(
    *,
    pool,
    client_id: str,
    inputs: dict[str, Any],
    brand_context: dict[str, Any],
    template_runtime_config: dict[str, Any],
) -> dict[str, Any]:
    config = resolve_citation_analysis_config(
        inputs=inputs,
        template_runtime_config=template_runtime_config,
    )
    if not config.enabled:
        return {"enabled": False, "reason": "citation_analysis_disabled"}

    brand_aliases = extract_brand_aliases(brand_context)
    sources = await fetch_citation_sources(
        pool,
        client_id=client_id,
        inputs=inputs,
        config=config,
    )
    await hydrate_source_pages(sources, enabled=config.fetch_full_pages)
    for source in sources:
        source.triage = triage_citation_source(source, brand_aliases)
    await apply_llm_semantic_triage(
        sources,
        brand_aliases=brand_aliases,
        enabled=config.llm_semantic_judgment,
    )
    sources = apply_brand_mention_policy(sources, config)
    platform_profile = str(template_runtime_config.get("platform_profile") or inputs.get("publish_platform") or "")
    return build_citation_analysis_result(
        config=config,
        sources=sources,
        brand_aliases=brand_aliases,
        platform_profile=platform_profile,
    ) | {
        "fingerprint": build_citation_analysis_fingerprint(
            inputs=inputs,
            template_runtime_config=template_runtime_config,
        ),
    }
