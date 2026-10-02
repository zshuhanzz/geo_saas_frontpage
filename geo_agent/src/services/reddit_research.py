from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from google.genai import types as genai_types

from llm.client import get_genai_client

logger = logging.getLogger(__name__)

ProviderName = Literal["web_grounded", "reddit_api"]
SubredditTargetingMode = Literal["ai_recommend", "manual", "reddit_api"]

_REDDIT_GROUNDING_MAX_RETRIES = 3
_REDDIT_GROUNDING_RETRY_BACKOFF_SECONDS = (5, 15)
_REDDIT_TARGETING_MAX_OUTPUT_TOKENS = 8192
_REDDIT_DISCOVERY_MAX_OUTPUT_TOKENS = 12288
_REDDIT_MAX_OUTPUT_TOKENS = 16384

_REDDIT_TARGETING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "candidates": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "url": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "public_description": {"type": "STRING"},
                    "relevance_reason": {"type": "STRING"},
                    "posting_risk": {"type": "STRING"},
                    "confidence": {"type": "NUMBER"},
                },
                "required": ["name", "url", "relevance_reason", "posting_risk", "confidence"],
            },
        }
    },
    "required": ["candidates"],
}

_REDDIT_POST_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "url": {"type": "STRING"},
        "score": {"type": "INTEGER"},
        "num_comments": {"type": "INTEGER"},
        "created_utc": {"type": "INTEGER"},
        "link_flair_text": {"type": "STRING"},
        "stickied": {"type": "BOOLEAN"},
        "locked": {"type": "BOOLEAN"},
        "upvote_ratio": {"type": "NUMBER"},
    },
    "required": ["title", "url"],
}

_REDDIT_DISCOVERY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "metadata": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "display_name": {"type": "STRING"},
                "title": {"type": "STRING"},
                "public_description": {"type": "STRING"},
                "subscribers": {"type": "INTEGER"},
                "active_user_count": {"type": "INTEGER"},
                "over18": {"type": "BOOLEAN"},
                "subreddit_type": {"type": "STRING"},
                "created_utc": {"type": "INTEGER"},
                "language": {"type": "STRING"},
                "submission_type": {"type": "STRING"},
                "subreddit_allowed_post_types": {
                    "type": "OBJECT",
                    "properties": {
                        "link": {"type": "BOOLEAN"},
                        "text": {"type": "BOOLEAN"},
                        "images": {"type": "BOOLEAN"},
                        "videos": {"type": "BOOLEAN"},
                        "polls": {"type": "BOOLEAN"},
                        "galleries": {"type": "BOOLEAN"},
                    },
                },
            },
            "required": ["name", "display_name"],
        },
        "rules": {
            "type": "OBJECT",
            "properties": {
                "rules_status": {"type": "STRING"},
                "rules_source_url": {"type": "STRING"},
                "rules": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "short_name": {"type": "STRING"},
                            "description": {"type": "STRING"},
                            "kind": {"type": "STRING"},
                            "priority": {"type": "INTEGER"},
                        },
                        "required": ["short_name"],
                    },
                },
            },
            "required": ["rules_status", "rules"],
        },
        "sidebar_summary": {"type": "STRING"},
        "posts": {
            "type": "OBJECT",
            "properties": {
                "search": {"type": "ARRAY", "items": _REDDIT_POST_RESPONSE_SCHEMA},
                "hot": {"type": "ARRAY", "items": _REDDIT_POST_RESPONSE_SCHEMA},
                "top": {"type": "ARRAY", "items": _REDDIT_POST_RESPONSE_SCHEMA},
                "new": {"type": "ARRAY", "items": _REDDIT_POST_RESPONSE_SCHEMA},
            },
        },
        "posting_capability": {"type": "OBJECT"},
        "risk_signals": {
            "type": "OBJECT",
            "properties": {
                "rules": {"type": "ARRAY", "items": {"type": "STRING"}},
                "sidebar": {"type": "ARRAY", "items": {"type": "STRING"}},
                "posts": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
        },
        "source_urls": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["metadata", "rules", "posts", "source_urls"],
}


class RedditResearchError(RuntimeError):
    pass


class RedditResearchConfigError(RedditResearchError):
    pass


@dataclass(frozen=True)
class RedditResearchConfig:
    provider: ProviderName
    web_fetch_enabled: bool
    grounding_model_id: str
    grounding_timeout_seconds: int
    fetch_user_agent: str
    request_timeout_seconds: int
    max_subreddit_candidates: int
    max_posts_per_subreddit: int
    api_enabled: bool
    api_commercial_access_approved: bool
    client_id: str
    client_secret: str
    api_user_agent: str

    @property
    def can_run(self) -> bool:
        if self.provider == "web_grounded":
            return (
                self.web_fetch_enabled
                and bool(self.grounding_model_id)
                and bool(self.fetch_user_agent)
            )
        return (
            self.api_enabled
            and self.api_commercial_access_approved
            and bool(self.client_id)
            and bool(self.client_secret)
            and bool(self.api_user_agent)
        )

    @property
    def block_reason(self) -> str:
        if self.can_run:
            return ""
        if self.provider == "web_grounded":
            missing = []
            if not self.web_fetch_enabled:
                missing.append("web fetch is disabled")
            if not self.grounding_model_id:
                missing.append("reddit_grounding_model_id is empty")
            if not self.fetch_user_agent:
                missing.append("reddit_research_fetch_user_agent is empty")
            return "Reddit web-grounded provider is not runnable: " + ", ".join(missing)
        if not self.api_commercial_access_approved:
            return "Reddit API commercial access is not approved"
        missing = []
        if not self.api_enabled:
            missing.append("reddit_api_enabled is false")
        if not self.client_id:
            missing.append("reddit_api_client_id is empty")
        if not self.client_secret:
            missing.append("reddit_api_client_secret is empty")
        if not self.api_user_agent:
            missing.append("reddit_api_user_agent is empty")
        return "Reddit API provider is not runnable: " + ", ".join(missing)


@dataclass(frozen=True)
class RedditTargetingContext:
    client_id: str
    template_id: str
    brand_context: dict[str, Any]
    topics: list[str]
    prompts: list[dict[str, Any]]
    citation_analysis_result: dict[str, Any] | None
    content_type: str
    keywords: str = ""


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else default
    except Exception:
        return default


def build_reddit_research_config(values: dict[str, Any]) -> RedditResearchConfig:
    provider = str(values.get("provider") or values.get("reddit_research_provider") or "web_grounded").strip().lower()
    if provider not in {"web_grounded", "reddit_api"}:
        provider = "web_grounded"
    return RedditResearchConfig(
        provider=provider,  # type: ignore[arg-type]
        web_fetch_enabled=_as_bool(values.get("web_fetch_enabled", values.get("reddit_web_fetch_enabled")), True),
        grounding_model_id=str(values.get("grounding_model_id", values.get("reddit_grounding_model_id")) or "").strip(),
        grounding_timeout_seconds=_as_int(
            values.get("grounding_timeout_seconds", values.get("reddit_research_grounding_timeout_seconds")),
            180,
        ),
        fetch_user_agent=str(values.get("fetch_user_agent", values.get("reddit_research_fetch_user_agent")) or "AnswerX-GEO/1.0").strip(),
        request_timeout_seconds=_as_int(values.get("request_timeout_seconds", values.get("reddit_research_request_timeout_seconds")), 20),
        max_subreddit_candidates=_as_int(values.get("max_subreddit_candidates", values.get("reddit_research_max_subreddit_candidates")), 12),
        max_posts_per_subreddit=_as_int(values.get("max_posts_per_subreddit", values.get("reddit_research_max_posts_per_subreddit")), 10),
        api_enabled=_as_bool(values.get("api_enabled", values.get("reddit_api_enabled")), False),
        api_commercial_access_approved=_as_bool(
            values.get("api_commercial_access_approved", values.get("reddit_api_commercial_access_approved")),
            False,
        ),
        client_id=str(values.get("api_client_id", values.get("reddit_api_client_id")) or "").strip(),
        client_secret=str(values.get("api_client_secret", values.get("reddit_api_client_secret")) or "").strip(),
        api_user_agent=str(values.get("api_user_agent", values.get("reddit_api_user_agent")) or "").strip(),
    )


def _template_reddit_research_values(template_runtime_config: dict[str, Any] | None) -> dict[str, Any]:
    reddit_research = (template_runtime_config or {}).get("reddit_research")
    if not isinstance(reddit_research, dict):
        return {}
    provider = str(reddit_research.get("provider") or "web_grounded").strip().lower()
    provider_config = reddit_research.get("provider_config")
    provider_config = provider_config if isinstance(provider_config, dict) else {}
    active_provider_config = provider_config.get(provider)
    active_provider_config = active_provider_config if isinstance(active_provider_config, dict) else {}
    values: dict[str, Any] = {
        "provider": provider,
        **active_provider_config,
    }
    if provider == "reddit_api":
        values.update({
            "api_enabled": active_provider_config.get("enabled"),
            "api_commercial_access_approved": active_provider_config.get("commercial_access_approved"),
            "api_client_id": active_provider_config.get("client_id"),
            "api_client_secret": active_provider_config.get("client_secret"),
            "api_user_agent": active_provider_config.get("user_agent"),
        })
    return {key: value for key, value in values.items() if value is not None}


async def load_reddit_research_config(pool, template_runtime_config: dict[str, Any] | None = None) -> RedditResearchConfig:
    keys = [
        "reddit_research_provider",
        "reddit_web_fetch_enabled",
        "reddit_grounding_model_id",
        "reddit_research_grounding_model_id",
        "reddit_research_grounding_timeout_seconds",
        "reddit_research_request_timeout_seconds",
        "reddit_research_fetch_user_agent",
        "reddit_research_max_subreddit_candidates",
        "reddit_research_max_posts_per_subreddit",
        "reddit_api_enabled",
        "reddit_api_commercial_access_approved",
        "reddit_api_client_id",
        "reddit_api_client_secret",
        "reddit_api_user_agent",
    ]
    rows = await pool.fetch(
        "SELECT key, value FROM geo_global_settings WHERE key = ANY($1::text[])",
        keys,
    )
    global_values = {row["key"]: row["value"] for row in rows}
    values = dict(global_values)
    values.update(_template_reddit_research_values(template_runtime_config))

    # Migration 109 moved the grounding model and its timeout out of legacy
    # template runtime config. These two global settings therefore have higher
    # precedence than the template's old ``grounding_model_id`` and
    # ``request_timeout_seconds`` fields. Keep the latter mapping because old
    # templates used one timeout for both the grounded request and follow-up
    # provider fetches. A dedicated global provider timeout, when configured,
    # remains the most specific override for those follow-up fetches.
    global_grounding_model = global_values.get("reddit_research_grounding_model_id")
    if global_grounding_model:
        values["grounding_model_id"] = global_grounding_model

    global_grounding_timeout = global_values.get(
        "reddit_research_grounding_timeout_seconds"
    )
    if global_grounding_timeout:
        values["grounding_timeout_seconds"] = global_grounding_timeout
        values["request_timeout_seconds"] = global_grounding_timeout

    global_request_timeout = global_values.get(
        "reddit_research_request_timeout_seconds"
    )
    if global_request_timeout:
        values["request_timeout_seconds"] = global_request_timeout
    return build_reddit_research_config(values)


def normalize_subreddit_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    from_url = extract_subreddit_name_from_url(raw)
    if from_url:
        return from_url
    raw = raw.removeprefix("/").strip()
    if raw.lower().startswith("r/"):
        raw = raw[2:]
    return re.sub(r"[^A-Za-z0-9_]", "", raw)


def extract_subreddit_name_from_url(value: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(str(value).strip())
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if host not in {"reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com"}:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "r":
        return normalize_subreddit_name(parts[1])
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def build_reddit_research_fingerprint(value: Any) -> str:
    """Stable SHA-256 fingerprint used by Wizard stale detection.

    Keep this helper pure and data-shape agnostic so routes can fingerprint
    different preflight dependencies without adding template-specific logic.
    """
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _subreddit_url(name: str) -> str:
    normalized = normalize_subreddit_name(name)
    return f"https://www.reddit.com/r/{normalized}/"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).strip()))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).strip())
    except Exception:
        return default


def _short_text(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _normalize_posting_capability(value: Any) -> dict[str, bool]:
    raw = value if isinstance(value, dict) else {}
    return {
        "link": bool(raw.get("link") or False),
        "text": bool(raw.get("text") or False),
        "images": bool(raw.get("images") or False),
        "videos": bool(raw.get("videos") or False),
        "polls": bool(raw.get("polls") or False),
        "galleries": bool(raw.get("galleries") or False),
    }


def normalize_subreddit_candidate(
    item: dict[str, Any],
    *,
    source: str,
    mode: str,
    default_relevance_reason: str = "",
    default_posting_risk: str = "",
    default_confidence: float = 0.0,
    grounding_source_urls: list[str] | None = None,
    verification_status: str | None = None,
) -> dict[str, Any] | None:
    name = (
        normalize_subreddit_name(str(item.get("name") or item.get("display_name") or ""))
        or extract_subreddit_name_from_url(str(item.get("url") or "")) or ""
    )
    if not name:
        return None
    fallback = _fallback_about_from_name(name, source=source)
    candidate = {
        "name": f"r/{name}",
        "display_name": name,
        "url": str(item.get("url") or fallback.get("url") or _subreddit_url(name)).strip(),
        "title": _short_text(item.get("title") or fallback.get("title") or name, 180),
        "public_description": _short_text(item.get("public_description") or item.get("description") or fallback.get("public_description") or "", 320),
        "subscribers": _safe_int(item.get("subscribers")),
        "active_user_count": _safe_int(item.get("active_user_count")),
        "over18": bool(item.get("over18") or False),
        "subreddit_type": str(item.get("subreddit_type") or fallback.get("subreddit_type") or "unknown"),
        "created_utc": item.get("created_utc"),
        "language": str(item.get("language") or "").strip(),
        "submission_type": str(item.get("submission_type") or "").strip(),
        "subreddit_allowed_post_types": _normalize_posting_capability(item.get("subreddit_allowed_post_types")),
        "relevance_reason": _short_text(item.get("relevance_reason") or item.get("reason") or default_relevance_reason, 220),
        "posting_risk": _short_text(item.get("posting_risk") or item.get("risk") or default_posting_risk, 220),
        "confidence": max(0.0, min(1.0, _safe_float(item.get("confidence"), default_confidence))),
        "source": source,
        "targeting_mode": mode,
        "metadata_status": str(item.get("metadata_status") or fallback.get("metadata_status") or "unverified"),
        "verification_status": str(verification_status or item.get("verification_status") or "unverified"),
    }
    if grounding_source_urls:
        candidate["grounding_source_urls"] = list(dict.fromkeys(grounding_source_urls))
    return candidate


def _candidate_from_mapping(item: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    return normalize_subreddit_candidate(item, source=source, mode=source)


def _recover_subreddit_candidates_payload(text: str, *, limit: int = 12) -> dict[str, Any]:
    names: list[str] = []
    seen: set[str] = set()
    patterns = [
        r'"name"\s*:\s*"r/([A-Za-z0-9_]+)"',
        r"https?://(?:www\.|old\.|new\.)?reddit\.com/r/([A-Za-z0-9_]+)/?",
        r"\br/([A-Za-z0-9_]+)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", flags=re.I):
            name = normalize_subreddit_name(match.group(1))
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                names.append(name)
            if len(names) >= limit:
                break
        if len(names) >= limit:
            break
    return {
        "candidates": [
            {
                "name": f"r/{name}",
                "url": _subreddit_url(name),
                "title": name,
                "public_description": "",
                "relevance_reason": "Recovered from grounded Reddit recommendation output.",
                "posting_risk": "Review subreddit rules before posting.",
                "confidence": 0.5,
            }
            for name in names[:limit]
        ]
    }


def parse_reddit_about_json(raw_text: str, *, source: str) -> dict[str, Any]:
    payload = json.loads(raw_text or "{}")
    data = payload.get("data") if isinstance(payload, dict) else {}
    data = data if isinstance(data, dict) else {}
    name = normalize_subreddit_name(str(data.get("display_name") or data.get("display_name_prefixed") or ""))
    return {
        "name": f"r/{name}" if name else "",
        "display_name": name,
        "title": str(data.get("title") or name).strip(),
        "public_description": str(data.get("public_description") or data.get("description") or "").strip(),
        "subscribers": int(data.get("subscribers") or 0),
        "active_user_count": int(data.get("active_user_count") or 0),
        "over18": bool(data.get("over18") or False),
        "subreddit_type": str(data.get("subreddit_type") or "unknown"),
        "created_utc": data.get("created_utc"),
        "language": str(data.get("lang") or "").strip(),
        "submission_type": str(data.get("submission_type") or "").strip(),
        "subreddit_allowed_post_types": {
            "link": bool(data.get("allow_links") if data.get("allow_links") is not None else data.get("link_type") != "self"),
            "text": bool(data.get("allow_self_posts") if data.get("allow_self_posts") is not None else data.get("submission_type") in {"self", "any"}),
            "images": bool(data.get("allow_images") or False),
            "videos": bool(data.get("allow_videos") or False),
            "polls": bool(data.get("allow_polls") or False),
            "galleries": bool(data.get("allow_galleries") or False),
            "prediction_contributors": bool(data.get("allow_predictions") or False),
        },
        "url": _subreddit_url(name) if name else "",
        "source": source,
    }


def parse_reddit_rules_json(raw_text: str, *, subreddit: str, source_url: str) -> dict[str, Any]:
    payload = json.loads(raw_text or "{}")
    raw_rules = payload.get("rules") if isinstance(payload, dict) else []
    rules = []
    for idx, item in enumerate(raw_rules if isinstance(raw_rules, list) else []):
        if not isinstance(item, dict):
            continue
        short_name = str(item.get("short_name") or item.get("violation_reason") or "").strip()
        description = str(item.get("description") or "").strip()
        if not short_name and not description:
            continue
        rules.append({
            "short_name": short_name or f"Rule {idx + 1}",
            "description": description,
            "kind": str(item.get("kind") or "").strip(),
            "priority": item.get("priority", idx),
        })
    return {
        "name": f"r/{normalize_subreddit_name(subreddit)}",
        "rules_status": "verified" if rules else "unavailable",
        "rules_source_url": source_url if rules else "",
        "rules": rules,
    }


def parse_reddit_rules_text(raw_text: str, *, subreddit: str, source_url: str) -> dict[str, Any]:
    """Extract rule-like lines from deterministic Reddit text/HTML evidence.

    This is intentionally conservative: it only accepts explicit numbered or
    bulleted rule lines and never asks an LLM to infer missing rules.
    """
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_text or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;?", "&", text)
    text = re.sub(r"&lt;?", "<", text)
    text = re.sub(r"&gt;?", ">", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in lines:
        if not line:
            continue
        match = re.match(r"^(?:rule\s*)?(\d+)[\).\-\s:]+(.+)$", line, flags=re.I)
        bullet = re.match(r"^[\-*•]\s+(.+)$", line)
        body = match.group(2).strip() if match else bullet.group(1).strip() if bullet else ""
        if not body:
            continue
        body = re.sub(r"\s+", " ", body)
        if len(body) < 4 or len(body) > 220:
            continue
        lowered = body.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        rules.append({
            "short_name": body,
            "description": "",
            "kind": "all",
            "priority": len(rules),
        })
        if len(rules) >= 20:
            break
    return {
        "name": f"r/{normalize_subreddit_name(subreddit)}",
        "rules_status": "verified" if rules else "unavailable",
        "rules_source_url": source_url if rules else "",
        "rules": rules,
    }


def _parse_json_response(text: str) -> Any:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return json.loads(stripped or "{}")


def _json_error_looks_truncated(error: Exception, text: str) -> bool:
    if not isinstance(error, json.JSONDecodeError):
        return False
    message = str(error).lower()
    if "unterminated string" in message:
        return True
    if "expecting value" in message or "expecting ',' delimiter" in message or "expecting property name" in message:
        return bool(text) and error.pos >= max(len(text) - 80, 0)
    return False


def _grounded_source_urls(response: Any) -> list[str]:
    urls: list[str] = []
    metadata = getattr(response, "grounding_metadata", None)
    chunks = getattr(metadata, "grounding_chunks", None) if metadata else None
    for chunk in chunks or []:
        web = getattr(chunk, "web", None)
        uri = getattr(web, "uri", None) if web else None
        if uri:
            urls.append(str(uri))
    return urls


def _is_retryable_grounding_error(exc: Exception) -> bool:
    text = str(exc).upper()
    return (
        "DEADLINE" in text
        or "504" in text
        or "TIMEOUT" in text
        or "READTIMEOUT" in text
        or "UNAVAILABLE" in text
        or "RESOURCE_EXHAUSTED" in text
    )


async def _sleep_before_grounding_retry(attempt: int) -> None:
    index = min(max(attempt - 1, 0), len(_REDDIT_GROUNDING_RETRY_BACKOFF_SECONDS) - 1)
    await asyncio.sleep(_REDDIT_GROUNDING_RETRY_BACKOFF_SECONDS[index])


_OBJECTION_RE = re.compile(
    r"\b(avoid|problem|issue|spam|sponsored|fake|scam|annoying|concern|warning|bad|broken|frustrat)",
    re.I,
)
_RISK_RE = re.compile(
    r"\b(no affiliate|affiliate|self[-\s]?promotion|promo|spam|ban|removed|rule|moderator|mod\b|flair|required)",
    re.I,
)


def extract_reddit_discovery_insights(*, sidebar: str, posts: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Derive compact community evidence without inventing anything.

    These fields feed Artifact Preparation as writing-context material. They
    are deterministic extractions from fetched sidebar/post titles, not facts
    synthesized by a model.
    """
    questions: list[str] = []
    objections: list[str] = []
    content_angles: list[str] = []
    risks: list[str] = []
    seen: set[str] = set()

    def add(bucket: list[str], text: str, *, limit: int = 8) -> None:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        if len(bucket) < limit:
            bucket.append(cleaned)

    for post in posts or []:
        title = str(post.get("title") or "").strip()
        if not title:
            continue
        if "?" in title:
            add(questions, title)
        if _OBJECTION_RE.search(title):
            add(objections, title)
        add(content_angles, title, limit=10)

    for sentence in re.split(r"(?<=[.!?])\s+|\n+", sidebar or ""):
        if _RISK_RE.search(sentence):
            add(risks, sentence, limit=8)

    return {
        "community_questions": questions,
        "objections": objections,
        "competitor_signals": [],
        "content_angles": content_angles,
        "risks": risks,
    }


class RedditResearchProvider:
    async def recommend_subreddits(self, context: RedditTargetingContext, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def resolve_subreddit(self, name: str) -> dict[str, Any]:
        raise NotImplementedError

    async def fetch_rules(self, name: str) -> dict[str, Any]:
        raise NotImplementedError

    async def fetch_sidebar(self, name: str) -> str:
        raise NotImplementedError

    async def search_posts(self, name: str, query: str, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def fetch_listing_posts(self, name: str, listing: str, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def discover_subreddit(self, name: str, *, query: str, limit: int) -> dict[str, Any] | None:
        return None


def _fallback_about_from_name(name: str, *, source: str) -> dict[str, Any]:
    normalized = normalize_subreddit_name(name)
    return {
        "name": f"r/{normalized}",
        "display_name": normalized,
        "title": normalized,
        "public_description": "",
        "subscribers": 0,
        "active_user_count": 0,
        "over18": False,
        "subreddit_type": "unknown",
        "created_utc": None,
        "language": "",
        "submission_type": "unknown",
        "subreddit_allowed_post_types": {},
        "url": _subreddit_url(normalized),
        "source": source,
        "metadata_status": "unverified",
    }


class WebGroundedRedditResearchProvider(RedditResearchProvider):
    def __init__(self, config: RedditResearchConfig):
        if not config.can_run:
            raise RedditResearchConfigError(config.block_reason)
        self.config = config

    async def recommend_subreddits(self, context: RedditTargetingContext, limit: int) -> list[dict[str, Any]]:
        prompt = f"""You recommend Reddit communities for a content generation task.

Use Google Search grounding to find real subreddit candidates. Return JSON only, matching the configured response schema exactly.

Brand context:
{json.dumps(context.brand_context, ensure_ascii=False, indent=2, default=str)}

Selected topics:
{json.dumps(context.topics, ensure_ascii=False, indent=2, default=str)}

Selected prompts:
{json.dumps(context.prompts, ensure_ascii=False, indent=2, default=str)}

Citation analysis summary:
{json.dumps(context.citation_analysis_result or {}, ensure_ascii=False, indent=2, default=str)[:6000]}

Content type: {context.content_type}
User keywords: {context.keywords or "(none)"}

Rules:
- Candidate names and URLs must be real Reddit subreddit URLs.
- Do not invent subscriber counts, rules, comments, vote counts, or posts.
- Keep to at most {limit} candidates.
- Keep public_description, relevance_reason, and posting_risk concise: each must be under 180 characters.
"""
        payload, response = await self._generate_grounded_json(
            prompt,
            context_label="subreddit recommendation",
            response_schema=_REDDIT_TARGETING_RESPONSE_SCHEMA,
            max_output_tokens=_REDDIT_TARGETING_MAX_OUTPUT_TOKENS,
            fallback_parser=lambda raw: _recover_subreddit_candidates_payload(raw, limit=limit),
        )
        source_urls = _grounded_source_urls(response)
        candidates = payload.get("candidates") if isinstance(payload, dict) else []
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates if isinstance(candidates, list) else []:
            if not isinstance(item, dict):
                continue
            suggested = _candidate_from_mapping(item, source="web_grounded")
            if not suggested:
                continue
            display = str(suggested.get("display_name") or "").lower()
            if not display or display in seen:
                continue
            candidate = normalize_subreddit_candidate(
                suggested,
                source="ai_recommend",
                mode="ai_recommend",
                grounding_source_urls=source_urls,
                verification_status="grounded_unverified",
            )
            if not candidate:
                continue
            seen.add(display)
            normalized.append(candidate)
            if len(normalized) >= limit:
                break
        return normalized

    async def _generate_grounded_json(
        self,
        prompt: str,
        *,
        context_label: str,
        response_schema: dict[str, Any] | None = None,
        max_output_tokens: int = _REDDIT_TARGETING_MAX_OUTPUT_TOKENS,
        fallback_parser: Callable[[str], Any] | None = None,
    ) -> tuple[Any, Any]:
        current_prompt = prompt
        last_err: Exception | None = None
        last_text = ""
        last_response: Any = None
        current_max_output_tokens = max_output_tokens
        for attempt in range(1, _REDDIT_GROUNDING_MAX_RETRIES + 1):
            response = await self._generate_grounded_candidates(
                current_prompt,
                response_schema=response_schema,
                max_output_tokens=current_max_output_tokens,
            )
            last_response = response
            text = response.text or "{}"
            last_text = text
            try:
                return _parse_json_response(text), response
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "[REDDIT-RESEARCH] Failed to parse grounded %s JSON attempt %s/%s error=%s raw_prefix=%s",
                    context_label,
                    attempt,
                    _REDDIT_GROUNDING_MAX_RETRIES,
                    exc,
                    text[:500].replace("\n", "\\n"),
                )
                if attempt >= _REDDIT_GROUNDING_MAX_RETRIES:
                    break
                await _sleep_before_grounding_retry(attempt)
                if _json_error_looks_truncated(exc, text):
                    current_max_output_tokens = min(
                        max(current_max_output_tokens * 2, current_max_output_tokens + 2048),
                        _REDDIT_MAX_OUTPUT_TOKENS,
                    )
                    logger.info(
                        "[REDDIT-RESEARCH] Grounded %s JSON looked truncated; retrying with max_output_tokens=%s",
                        context_label,
                        current_max_output_tokens,
                    )
                current_prompt = (
                    prompt
                    + "\n\nThe previous response was not valid JSON. Retry now and return one strict JSON object only: "
                    "no Markdown fences, no comments, no trailing commas, no unescaped quotes inside strings. "
                    "Keep every string concise."
                )
        if fallback_parser:
            fallback_payload = fallback_parser(last_text)
            if (
                isinstance(fallback_payload, dict)
                and (
                    (isinstance(fallback_payload.get("candidates"), list) and bool(fallback_payload.get("candidates")))
                    or any(key != "candidates" for key in fallback_payload)
                )
            ):
                logger.warning(
                    "[REDDIT-RESEARCH] Recovered grounded %s payload after JSON parse retries failed",
                    context_label,
                )
                return fallback_payload, last_response
        raise RedditResearchError(f"Failed to parse grounded {context_label} JSON after retries: {last_err}") from last_err

    async def _generate_grounded_candidates(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        max_output_tokens: int = _REDDIT_TARGETING_MAX_OUTPUT_TOKENS,
    ) -> Any:
        client = await get_genai_client(
            self.config.grounding_model_id,
            role="flash",
            timeout_seconds=self.config.grounding_timeout_seconds,
        )
        last_err: Exception | None = None
        for attempt in range(1, _REDDIT_GROUNDING_MAX_RETRIES + 1):
            try:
                logger.info(
                    "[REDDIT-RESEARCH] Grounded subreddit recommendation attempt %s/%s model=%s timeout=%ss",
                    attempt,
                    _REDDIT_GROUNDING_MAX_RETRIES,
                    self.config.grounding_model_id,
                    self.config.grounding_timeout_seconds,
                )
                config_kwargs: dict[str, Any] = {
                    "temperature": 0.2,
                    "max_output_tokens": max_output_tokens,
                    "response_mime_type": "application/json",
                    "tools": [genai_types.Tool(google_search=genai_types.GoogleSearch())],
                }
                if response_schema:
                    config_kwargs["response_schema"] = response_schema
                return await client.aio.models.generate_content(
                    model=self.config.grounding_model_id,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(**config_kwargs),
                )
            except Exception as exc:
                last_err = exc
                retryable = _is_retryable_grounding_error(exc)
                logger.warning(
                    "[REDDIT-RESEARCH] Grounded subreddit recommendation failed attempt %s/%s retryable=%s error=%s",
                    attempt,
                    _REDDIT_GROUNDING_MAX_RETRIES,
                    retryable,
                    exc,
                )
                if attempt >= _REDDIT_GROUNDING_MAX_RETRIES or not retryable:
                    break
                await _sleep_before_grounding_retry(attempt)
        raise RedditResearchError(f"Grounded subreddit recommendation failed after {_REDDIT_GROUNDING_MAX_RETRIES} attempts: {last_err}") from last_err

    async def resolve_subreddit(self, name: str) -> dict[str, Any]:
        normalized = normalize_subreddit_name(name)
        if not normalized:
            raise RedditResearchError("Subreddit name is empty")
        about_url = f"https://www.reddit.com/r/{normalized}/about.json"
        try:
            text = await self._fetch_text(about_url)
            candidate = parse_reddit_about_json(text, source="web_grounded")
            normalized_candidate = normalize_subreddit_candidate(
                candidate,
                source="web_grounded",
                mode="manual",
                default_relevance_reason="Confirmed from public Reddit metadata.",
                default_posting_risk="Review subreddit rules before posting.",
                default_confidence=1.0,
                verification_status="web_metadata",
            )
            if normalized_candidate and normalized_candidate.get("name"):
                return normalized_candidate
        except Exception as exc:
            logger.warning("[REDDIT-RESEARCH] about.json fetch failed for %s: %s", normalized, exc)
        return normalize_subreddit_candidate(
            _fallback_about_from_name(normalized, source="web_grounded"),
            source="web_grounded",
            mode="manual",
            default_relevance_reason="Accepted from manual subreddit input.",
            default_posting_risk="Rules unavailable until Reddit Discovery succeeds.",
            default_confidence=0.5,
            verification_status="metadata_unavailable",
        ) or _fallback_about_from_name(normalized, source="web_grounded")

    async def fetch_rules(self, name: str) -> dict[str, Any]:
        normalized = normalize_subreddit_name(name)
        rules_url = f"https://www.reddit.com/r/{normalized}/about/rules.json"
        try:
            text = await self._fetch_text(rules_url)
            parsed = parse_reddit_rules_json(text, subreddit=normalized, source_url=rules_url)
            if parsed.get("rules_status") == "verified":
                return parsed
        except Exception as exc:
            logger.warning("[REDDIT-RESEARCH] rules.json fetch failed for %s: %s", normalized, exc)
        about_url = f"https://www.reddit.com/r/{normalized}/about.json"
        try:
            text = await self._fetch_text(about_url)
            payload = json.loads(text or "{}")
            data = payload.get("data") if isinstance(payload, dict) else {}
            if isinstance(data, dict):
                about_text = "\n".join(
                    str(data.get(key) or "")
                    for key in ("rules", "submit_text", "description", "public_description")
                    if data.get(key)
                )
                parsed = parse_reddit_rules_text(about_text, subreddit=normalized, source_url=about_url)
                if parsed.get("rules_status") == "verified":
                    return parsed
        except Exception as exc:
            logger.warning("[REDDIT-RESEARCH] about.json rules fallback failed for %s: %s", normalized, exc)
        public_about_url = f"https://www.reddit.com/r/{normalized}/about/"
        try:
            text = await self._fetch_text(public_about_url)
            parsed = parse_reddit_rules_text(text, subreddit=normalized, source_url=public_about_url)
            if parsed.get("rules_status") == "verified":
                return parsed
        except Exception as exc:
            logger.warning("[REDDIT-RESEARCH] public about rules fallback failed for %s: %s", normalized, exc)
        return {
            "name": f"r/{normalized}",
            "rules_status": "unavailable",
            "rules_source_url": "",
            "rules": [],
        }

    async def fetch_sidebar(self, name: str) -> str:
        normalized = normalize_subreddit_name(name)
        about_url = f"https://www.reddit.com/r/{normalized}/about.json"
        try:
            text = await self._fetch_text(about_url)
            payload = json.loads(text or "{}")
            data = payload.get("data") if isinstance(payload, dict) else {}
            if isinstance(data, dict):
                return str(data.get("description") or data.get("public_description") or "").strip()
        except Exception as exc:
            logger.warning("[REDDIT-RESEARCH] sidebar fetch failed for %s: %s", normalized, exc)
        return ""

    async def search_posts(self, name: str, query: str, limit: int) -> list[dict[str, Any]]:
        normalized = normalize_subreddit_name(name)
        search_url = (
            f"https://www.reddit.com/r/{normalized}/search.json?"
            + urllib.parse.urlencode({"q": query, "restrict_sr": "1", "sort": "relevance", "limit": str(limit)})
        )
        try:
            text = await self._fetch_text(search_url)
            payload = json.loads(text or "{}")
            children = (((payload or {}).get("data") or {}).get("children") or [])
            posts = []
            for child in children[:limit]:
                data = child.get("data") if isinstance(child, dict) else {}
                if not isinstance(data, dict):
                    continue
                permalink = str(data.get("permalink") or "")
                posts.append({
                    "title": str(data.get("title") or "").strip(),
                    "url": f"https://www.reddit.com{permalink}" if permalink.startswith("/") else str(data.get("url") or ""),
                    "score": data.get("score"),
                    "num_comments": data.get("num_comments"),
                    "subreddit": f"r/{normalized}",
                    "source": "web_grounded",
                })
            return posts
        except Exception as exc:
            logger.warning("[REDDIT-RESEARCH] post search failed for %s: %s", normalized, exc)
            return []

    async def fetch_listing_posts(self, name: str, listing: str, limit: int) -> list[dict[str, Any]]:
        normalized = normalize_subreddit_name(name)
        listing = listing if listing in {"hot", "new", "top"} else "hot"
        listing_url = f"https://www.reddit.com/r/{normalized}/{listing}.json?{urllib.parse.urlencode({'limit': str(limit)})}"
        try:
            text = await self._fetch_text(listing_url)
            payload = json.loads(text or "{}")
            posts = _parse_reddit_listing_posts(payload, normalized, source="web_grounded", limit=limit)
            for post in posts:
                post["listing"] = listing
            return posts
        except Exception as exc:
            logger.warning("[REDDIT-RESEARCH] %s listing failed for %s: %s", listing, normalized, exc)
            return []

    async def discover_subreddit(self, name: str, *, query: str, limit: int) -> dict[str, Any]:
        normalized = normalize_subreddit_name(name)
        prompt = f"""You are producing a Reddit Discovery contract for a content research workflow.

Use Google Search grounding to inspect public Reddit pages for r/{normalized}. Focus on:
- https://www.reddit.com/r/{normalized}/about.json
- https://www.reddit.com/r/{normalized}/about/rules.json
- public search, hot, top, and new posts relevant to: {query or "(general subreddit context)"}

Return JSON only, matching the configured response schema exactly. Do not invent numeric metrics, rule text, votes, comments, or posts. If a field cannot be verified from grounding, use empty strings, empty arrays, 0, false, or "unavailable".
"""
        payload, response = await self._generate_grounded_json(
            prompt,
            context_label=f"Reddit Discovery for r/{normalized}",
            response_schema=_REDDIT_DISCOVERY_RESPONSE_SCHEMA,
            max_output_tokens=_REDDIT_DISCOVERY_MAX_OUTPUT_TOKENS,
        )
        payload = payload if isinstance(payload, dict) else {}
        source_urls = _grounded_source_urls(response)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata = {**_fallback_about_from_name(normalized, source="ai_recommend"), **metadata, "source": "ai_recommend"}
        rules = payload.get("rules") if isinstance(payload.get("rules"), dict) else {}
        parsed_rules = {
            "name": f"r/{normalized}",
            "rules_status": rules.get("rules_status") or "unavailable",
            "rules_source_url": rules.get("rules_source_url") or "",
            "rules": rules.get("rules") if isinstance(rules.get("rules"), list) else [],
        }
        posts = payload.get("posts") if isinstance(payload.get("posts"), dict) else {}
        normalized_posts = {
            key: posts.get(key) if isinstance(posts.get(key), list) else []
            for key in ("search", "hot", "top", "new")
        }
        all_posts = normalized_posts["search"] + normalized_posts["hot"] + normalized_posts["top"] + normalized_posts["new"]
        insights = extract_reddit_discovery_insights(
            sidebar=str(payload.get("sidebar_summary") or metadata.get("public_description") or ""),
            posts=all_posts,
        )
        return {
            "name": f"r/{normalized}",
            "metadata": metadata,
            "rules_status": parsed_rules["rules_status"],
            "rules_source_url": parsed_rules["rules_source_url"],
            "rules": parsed_rules["rules"],
            "sidebar_summary": str(payload.get("sidebar_summary") or metadata.get("public_description") or ""),
            "posting_capability": payload.get("posting_capability") if isinstance(payload.get("posting_capability"), dict) else metadata.get("subreddit_allowed_post_types") or {},
            "submission_type": metadata.get("submission_type") or "",
            "community_questions": insights["community_questions"],
            "objections": insights["objections"],
            "competitor_signals": insights["competitor_signals"],
            "content_angles": insights["content_angles"],
            "risks": insights["risks"],
            "risk_signals": payload.get("risk_signals") if isinstance(payload.get("risk_signals"), dict) else {
                "rules": [r for r in parsed_rules["rules"] if _RISK_RE.search(_stable_json(r))],
                "sidebar": insights["risks"],
                "posts": insights["objections"],
            },
            "source_urls": list(dict.fromkeys((payload.get("source_urls") if isinstance(payload.get("source_urls"), list) else []) + source_urls)),
            "posts": normalized_posts,
            "discovery_source": "ai_recommend_grounding",
        }

    async def _fetch_text(self, url: str) -> str:
        if not self.config.web_fetch_enabled:
            raise RedditResearchConfigError(self.config.block_reason)
        return await asyncio.to_thread(
            _fetch_text_sync,
            url,
            self.config.fetch_user_agent,
            self.config.request_timeout_seconds,
        )


class RedditApiResearchProvider(RedditResearchProvider):
    def __init__(self, config: RedditResearchConfig):
        if not config.can_run:
            raise RedditResearchConfigError(config.block_reason)
        self.config = config
        self._access_token = ""
        self._access_token_expires_at = 0.0

    async def recommend_subreddits(self, context: RedditTargetingContext, limit: int) -> list[dict[str, Any]]:
        query_parts = context.topics + [str(p.get("text") or "") for p in context.prompts]
        query = " ".join([p for p in query_parts if p]).strip() or context.keywords
        if not query:
            return []
        payload = await self._api_json("/subreddits/search", params={"q": query, "limit": str(limit)})
        children = (((payload or {}).get("data") or {}).get("children") or [])
        candidates = []
        for child in children[:limit]:
            data = child.get("data") if isinstance(child, dict) else {}
            if isinstance(data, dict):
                parsed = parse_reddit_about_json(json.dumps({"data": data}), source="reddit_api")
                normalized = normalize_subreddit_candidate(
                    parsed,
                    source="reddit_api",
                    mode="reddit_api",
                    default_relevance_reason="Matched by Reddit subreddit search for the selected topics and prompts.",
                    default_posting_risk="Review subreddit rules before posting.",
                    default_confidence=0.75,
                    verification_status="reddit_api_metadata",
                )
                if normalized:
                    candidates.append(normalized)
        return candidates

    async def resolve_subreddit(self, name: str) -> dict[str, Any]:
        normalized = normalize_subreddit_name(name)
        payload = await self._api_json(f"/r/{normalized}/about")
        parsed = parse_reddit_about_json(json.dumps(payload), source="reddit_api")
        return normalize_subreddit_candidate(
            parsed,
            source="reddit_api",
            mode="reddit_api",
            default_relevance_reason="Confirmed by Reddit API metadata.",
            default_posting_risk="Review subreddit rules before posting.",
            default_confidence=1.0,
            verification_status="reddit_api_metadata",
        ) or parsed

    async def fetch_rules(self, name: str) -> dict[str, Any]:
        normalized = normalize_subreddit_name(name)
        source_url = f"https://oauth.reddit.com/r/{normalized}/about/rules"
        payload = await self._api_json(f"/r/{normalized}/about/rules")
        return parse_reddit_rules_json(json.dumps(payload), subreddit=normalized, source_url=source_url)

    async def fetch_sidebar(self, name: str) -> str:
        data = await self.resolve_subreddit(name)
        return str(data.get("public_description") or "")

    async def search_posts(self, name: str, query: str, limit: int) -> list[dict[str, Any]]:
        normalized = normalize_subreddit_name(name)
        payload = await self._api_json(
            f"/r/{normalized}/search",
            params={"q": query, "restrict_sr": "1", "sort": "relevance", "limit": str(limit)},
        )
        return _parse_reddit_listing_posts(payload, normalized, source="reddit_api", limit=limit)

    async def fetch_listing_posts(self, name: str, listing: str, limit: int) -> list[dict[str, Any]]:
        normalized = normalize_subreddit_name(name)
        listing = listing if listing in {"hot", "new", "top"} else "hot"
        payload = await self._api_json(f"/r/{normalized}/{listing}", params={"limit": str(limit)})
        posts = _parse_reddit_listing_posts(payload, normalized, source="reddit_api", limit=limit)
        for post in posts:
            post["listing"] = listing
        return posts

    async def _api_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        token = await self._get_access_token()
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"https://oauth.reddit.com{path}{query}"
        return await asyncio.to_thread(
            _fetch_json_sync,
            url,
            {
                "Authorization": f"Bearer {token}",
                "User-Agent": self.config.api_user_agent,
                "Accept": "application/json",
            },
            self.config.request_timeout_seconds,
        )

    async def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._access_token_expires_at - 60:
            return self._access_token
        payload = await asyncio.to_thread(
            _fetch_reddit_app_only_token_sync,
            self.config.client_id,
            self.config.client_secret,
            self.config.api_user_agent,
            self.config.request_timeout_seconds,
        )
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RedditResearchError("Reddit OAuth token response did not include access_token")
        expires_in = _as_int(payload.get("expires_in"), 3600)
        self._access_token = token
        self._access_token_expires_at = now + expires_in
        return token


def _parse_reddit_listing_posts(payload: dict[str, Any], normalized: str, *, source: str, limit: int) -> list[dict[str, Any]]:
    children = (((payload or {}).get("data") or {}).get("children") or [])
    posts = []
    for child in children[:limit]:
        data = child.get("data") if isinstance(child, dict) else {}
        if not isinstance(data, dict):
            continue
        permalink = str(data.get("permalink") or "")
        posts.append({
            "title": str(data.get("title") or "").strip(),
            "url": f"https://www.reddit.com{permalink}" if permalink.startswith("/") else str(data.get("url") or ""),
            "score": data.get("score"),
            "num_comments": data.get("num_comments"),
            "created_utc": data.get("created_utc"),
            "link_flair_text": data.get("link_flair_text"),
            "stickied": bool(data.get("stickied") or False),
            "locked": bool(data.get("locked") or False),
            "upvote_ratio": data.get("upvote_ratio"),
            "subreddit": f"r/{normalized}",
            "source": source,
        })
    return posts


def _fetch_text_sync(url: str, user_agent: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RedditResearchError(f"HTTP {exc.code} for {url}") from exc


def _fetch_json_sync(url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            payload = json.loads(text or "{}")
            return payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RedditResearchError(f"HTTP {exc.code} for {url}: {body}") from exc


def _fetch_reddit_app_only_token_sync(client_id: str, client_secret: str, user_agent: str, timeout: int) -> dict[str, Any]:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    request = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "User-Agent": user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            payload = json.loads(text or "{}")
            return payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RedditResearchError(f"Reddit OAuth token request failed: HTTP {exc.code}: {body_text}") from exc


def get_reddit_research_provider(config: RedditResearchConfig) -> RedditResearchProvider:
    if config.provider == "reddit_api":
        return RedditApiResearchProvider(config)
    return WebGroundedRedditResearchProvider(config)


def get_reddit_research_provider_for_mode(config: RedditResearchConfig, mode: str) -> RedditResearchProvider:
    if mode == "reddit_api":
        return RedditApiResearchProvider(replace(config, provider="reddit_api"))
    return WebGroundedRedditResearchProvider(replace(config, provider="web_grounded"))


async def recommend_subreddits(
    *,
    pool,
    context: RedditTargetingContext,
    template_runtime_config: dict[str, Any] | None = None,
    limit: int | None = None,
    mode: SubredditTargetingMode = "ai_recommend",
) -> dict[str, Any]:
    config = await load_reddit_research_config(pool, template_runtime_config)
    provider = get_reddit_research_provider_for_mode(config, mode)
    max_count = limit or config.max_subreddit_candidates
    candidates = await provider.recommend_subreddits(context, max_count)
    fingerprint = build_reddit_research_fingerprint({
        "step": "subreddit_targeting",
        "mode": mode,
        "provider": config.provider,
        "client_id": context.client_id,
        "template_id": context.template_id,
        "topics": context.topics,
        "prompts": context.prompts,
        "citation_analysis_fingerprint": (context.citation_analysis_result or {}).get("fingerprint"),
        "content_type": context.content_type,
        "keywords": context.keywords,
        "selected_subreddits": [
            item.get("display_name") or item.get("name")
            for item in candidates[:max_count]
            if isinstance(item, dict)
        ],
    })
    return {
        "status": "ready" if candidates[:max_count] else "error",
        "mode": mode,
        "provider": config.provider,
        "selected_subreddits": candidates[:max_count],
        "candidate_subreddits": candidates[:max_count],
        "generated_at": _now_iso(),
        "fingerprint": fingerprint,
        "input_fingerprint": fingerprint,
    }


async def resolve_manual_subreddits(
    *,
    pool,
    names: list[str],
    template_runtime_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = await load_reddit_research_config(pool, template_runtime_config)
    provider = get_reddit_research_provider(config)
    selected = []
    errors = []
    for raw in names:
        name = normalize_subreddit_name(raw)
        if not name:
            continue
        try:
            resolved = await provider.resolve_subreddit(name)
            selected_candidate = normalize_subreddit_candidate(
                resolved,
                source=str(resolved.get("source") or config.provider),
                mode="manual",
                default_relevance_reason="Accepted from manual subreddit input.",
                default_posting_risk="Review subreddit rules before posting.",
                default_confidence=1.0 if resolved.get("metadata_status") != "unavailable" else 0.5,
                verification_status=str(resolved.get("verification_status") or resolved.get("metadata_status") or "manual_input"),
            )
            if selected_candidate:
                selected.append(selected_candidate)
        except Exception as exc:
            errors.append({"name": raw, "error": str(exc)})
    fingerprint = build_reddit_research_fingerprint({
        "step": "subreddit_targeting",
        "mode": "manual",
        "provider": config.provider,
        "manual_names": [normalize_subreddit_name(n) for n in names],
        "selected_subreddits": [
            item.get("display_name") or item.get("name")
            for item in selected
            if isinstance(item, dict)
        ],
    })
    return {
        "status": "ready" if selected else "error",
        "mode": "manual",
        "provider": config.provider,
        "selected_subreddits": selected,
        "candidate_subreddits": selected,
        "errors": errors,
        "generated_at": _now_iso(),
        "fingerprint": fingerprint,
        "input_fingerprint": fingerprint,
    }


async def discover_reddit_context(
    *,
    pool,
    subreddit_targeting: dict[str, Any],
    query: str,
    template_runtime_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = await load_reddit_research_config(pool, template_runtime_config)
    mode = str(subreddit_targeting.get("mode") or "ai_recommend")
    provider = get_reddit_research_provider_for_mode(config, mode)
    selected = subreddit_targeting.get("selected_subreddits")
    if not isinstance(selected, list) or not selected:
        raise RedditResearchError("Confirmed subreddit targets are required")
    subreddits = []
    for candidate in selected:
        raw_name = candidate.get("display_name") or candidate.get("name") if isinstance(candidate, dict) else ""
        name = normalize_subreddit_name(str(raw_name or ""))
        if not name:
            continue
        if hasattr(provider, "discover_subreddit"):
            discovered = await provider.discover_subreddit(name, query=query, limit=config.max_posts_per_subreddit)
            if discovered:
                subreddits.append(discovered)
                continue
        candidate_data = candidate if isinstance(candidate, dict) else {}
        try:
            metadata = await provider.resolve_subreddit(name)
        except Exception as exc:
            logger.warning("[REDDIT-RESEARCH] metadata fetch failed for %s: %s", name, exc)
            metadata = {}
        rules = await provider.fetch_rules(name)
        sidebar = await provider.fetch_sidebar(name)
        search_posts = await provider.search_posts(name, query, config.max_posts_per_subreddit) if query else []
        hot_posts = await provider.fetch_listing_posts(name, "hot", config.max_posts_per_subreddit)
        top_posts = await provider.fetch_listing_posts(name, "top", config.max_posts_per_subreddit)
        new_posts = await provider.fetch_listing_posts(name, "new", config.max_posts_per_subreddit)
        all_posts = search_posts + hot_posts + top_posts + new_posts
        insights = extract_reddit_discovery_insights(sidebar=sidebar, posts=all_posts)
        subreddit_metadata = {**candidate_data, **metadata}
        subreddits.append({
            "name": f"r/{name}",
            "metadata": subreddit_metadata,
            "rules_status": rules.get("rules_status"),
            "rules_source_url": rules.get("rules_source_url"),
            "rules": rules.get("rules") or [],
            "sidebar_summary": sidebar,
            "posting_capability": subreddit_metadata.get("subreddit_allowed_post_types") or {},
            "submission_type": subreddit_metadata.get("submission_type") or "",
            "community_questions": insights["community_questions"],
            "objections": insights["objections"],
            "competitor_signals": insights["competitor_signals"],
            "content_angles": insights["content_angles"],
            "risks": insights["risks"],
            "risk_signals": {
                "rules": [r for r in (rules.get("rules") or []) if _RISK_RE.search(_stable_json(r))],
                "sidebar": insights["risks"],
                "posts": insights["objections"],
            },
            "source_urls": [p.get("url") for p in all_posts if p.get("url")],
            "posts": {
                "search": search_posts,
                "hot": hot_posts,
                "top": top_posts,
                "new": new_posts,
            },
        })
    fingerprint = build_reddit_research_fingerprint({
        "step": "reddit_discovery",
        "mode": mode,
        "provider": "reddit_api" if mode == "reddit_api" else "web_grounded",
        "subreddit_targeting_fingerprint": subreddit_targeting.get("fingerprint"),
        "selected_subreddits": [
            item.get("display_name") or item.get("name")
            for item in selected
            if isinstance(item, dict)
        ],
        "query": query,
        "rules_status": [
            item.get("rules_status")
            for item in subreddits
            if isinstance(item, dict)
        ],
    })
    return {
        "status": "ready" if subreddits else "error",
        "mode": mode,
        "provider": "reddit_api" if mode == "reddit_api" else "web_grounded",
        "subreddits": subreddits,
        "generated_at": _now_iso(),
        "fingerprint": fingerprint,
        "input_fingerprint": fingerprint,
    }
