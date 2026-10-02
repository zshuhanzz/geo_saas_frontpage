"""Pure URL-variant matching helpers for Published URL tracking.

Citation rows keep their original ``source_url``.  These helpers only derive
request-time comparison keys and therefore never mutate or backfill citation
data.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit

from utils.url_normalization import UrlNormalizationError, normalize_url


VariantStatus = Literal["exact", "automatic", "confirmed", "pending", "rejected"]


@dataclass(frozen=True)
class PublishedUrlVariantMatch:
    source_url: str
    match_key: str
    status: VariantStatus
    citation_count: int


@dataclass
class PublishedUrlVariantResolution:
    matched_source_urls_by_published_id: dict[str, set[str]]
    published_ids_by_source_url: dict[str, set[str]]
    variants_by_published_id: dict[str, list[PublishedUrlVariantMatch]]
    pending_count_by_published_id: dict[str, int]


def _row_value(row: Mapping, key: str, default=None):
    try:
        value = row[key]
    except (KeyError, TypeError):
        value = default
    return default if value is None else value


def url_origin_path(value: str) -> str:
    """Return normalized ``scheme://host/path`` without query or fragment."""

    normalized = normalize_url(value)
    parts = urlsplit(normalized)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_candidate_url_predicate(
    *,
    published_rows: Iterable[Mapping],
    mapping_rows: Iterable[Mapping],
    prefix: str,
    url_column: str = "c.source_url",
) -> tuple[str, dict[str, str]]:
    """Build an indexed, boundary-aware SQL prefilter for URL candidates.

    ``LIKE`` is deliberately limited to ``?`` and ``#`` boundaries.  Semantic
    matching remains in Python after PostgreSQL has grouped the small candidate
    URL set.
    """

    origins: set[str] = set()

    def add_origin_variants(value: str) -> None:
        origin = url_origin_path(value)
        origins.add(origin)
        parts = urlsplit(origin)
        if parts.path == "/":
            origins.add(urlunsplit((parts.scheme, parts.netloc, "", "", "")))
        else:
            origins.add(f"{origin}/")

    for row in published_rows:
        for key in ("published_url", "normalized_url"):
            value = str(_row_value(row, key, "")).strip()
            if not value:
                continue
            try:
                add_origin_variants(value)
            except UrlNormalizationError:
                continue
    for row in mapping_rows:
        value = str(_row_value(row, "citation_url", "")).strip()
        if not value:
            continue
        try:
            add_origin_variants(value)
        except UrlNormalizationError:
            continue

    if not origins:
        return "FALSE", {}

    clauses: list[str] = []
    params: dict[str, str] = {}
    for index, origin in enumerate(sorted(origins)):
        exact_key = f"{prefix}_exact_{index}"
        query_key = f"{prefix}_query_{index}"
        fragment_key = f"{prefix}_fragment_{index}"
        escaped = _escape_like(origin)
        params[exact_key] = origin
        params[query_key] = f"{escaped}?%"
        params[fragment_key] = f"{escaped}#%"
        clauses.append(
            f"({url_column} = :{exact_key} "
            f"OR {url_column} LIKE :{query_key} ESCAPE '\\' "
            f"OR {url_column} LIKE :{fragment_key} ESCAPE '\\')"
        )
    return f"({' OR '.join(clauses)})", params


def resolve_published_url_variants(
    *,
    published_rows: Iterable[Mapping],
    citation_rows: Iterable[Mapping],
    mapping_rows: Iterable[Mapping],
) -> PublishedUrlVariantResolution:
    """Resolve raw citation URLs to at most one Published URL.

    Resolution priority is exact raw URL, confirmed per-page mapping, then a
    conservative automatic match key.  Same-path URLs with meaningful or
    unknown query parameters remain pending until explicitly confirmed.
    """

    pages = [row for row in published_rows]
    page_ids = [str(_row_value(row, "id")) for row in pages]
    matched_by_page: dict[str, set[str]] = {page_id: set() for page_id in page_ids}
    ids_by_source: dict[str, set[str]] = defaultdict(set)
    variants_by_page: dict[str, list[PublishedUrlVariantMatch]] = {
        page_id: [] for page_id in page_ids
    }

    exact_page_ids: dict[str, set[str]] = defaultdict(set)
    primary_page_ids: dict[str, set[str]] = defaultdict(set)
    origin_page_ids: dict[str, set[str]] = defaultdict(set)
    for row in pages:
        page_id = str(_row_value(row, "id"))
        raw_urls = {
            str(_row_value(row, "published_url", "")).strip(),
            str(_row_value(row, "normalized_url", "")).strip(),
        } - {""}
        for raw_url in raw_urls:
            exact_page_ids[raw_url].add(page_id)
        primary_url = str(_row_value(row, "published_url", "")).strip()
        try:
            primary_page_ids[normalize_url(primary_url)].add(page_id)
            origin_page_ids[url_origin_path(primary_url)].add(page_id)
        except UrlNormalizationError:
            continue

    confirmed_page_ids: dict[str, set[str]] = defaultdict(set)
    rejected_by_page: dict[str, set[str]] = defaultdict(set)
    for row in mapping_rows:
        page_id = str(_row_value(row, "published_url_id"))
        if page_id not in matched_by_page:
            continue
        raw_url = str(_row_value(row, "citation_url", "")).strip()
        stored_key = str(_row_value(row, "citation_match_key", "")).strip()
        try:
            match_key = normalize_url(raw_url or stored_key)
        except UrlNormalizationError:
            match_key = stored_key
        if not match_key:
            continue
        status = str(_row_value(row, "status", ""))
        if status == "confirmed":
            confirmed_page_ids[match_key].add(page_id)
        elif status == "rejected":
            rejected_by_page[page_id].add(match_key)

    citation_counts_by_source: dict[str, int] = defaultdict(int)
    for row in citation_rows:
        source_url = str(_row_value(row, "source_url", "")).strip()
        if not source_url:
            continue
        citation_counts_by_source[source_url] += int(
            _row_value(row, "citation_count", 0) or 0
        )

    for source_url, citation_count in citation_counts_by_source.items():
        try:
            match_key = normalize_url(source_url)
            origin_path = url_origin_path(source_url)
        except UrlNormalizationError:
            continue

        exact_ids = exact_page_ids.get(source_url, set())
        confirmed_ids = confirmed_page_ids.get(match_key, set())
        automatic_ids = primary_page_ids.get(match_key, set())
        matched_ids: set[str] = set()
        matched_status: VariantStatus | None = None
        if len(exact_ids) == 1:
            matched_ids = set(exact_ids)
            matched_status = "exact"
        elif len(confirmed_ids) == 1:
            matched_ids = set(confirmed_ids)
            matched_status = "confirmed"
        elif len(automatic_ids) == 1:
            matched_ids = set(automatic_ids)
            matched_status = "automatic"

        if matched_ids and matched_status:
            page_id = next(iter(matched_ids))
            matched_by_page[page_id].add(source_url)
            ids_by_source[source_url].add(page_id)
            variants_by_page[page_id].append(PublishedUrlVariantMatch(
                source_url=source_url,
                match_key=match_key,
                status=matched_status,
                citation_count=citation_count,
            ))
            continue

        candidate_ids = origin_page_ids.get(origin_path, set())
        for page_id in sorted(candidate_ids):
            status: VariantStatus = (
                "rejected" if match_key in rejected_by_page.get(page_id, set()) else "pending"
            )
            variants_by_page[page_id].append(PublishedUrlVariantMatch(
                source_url=source_url,
                match_key=match_key,
                status=status,
                citation_count=citation_count,
            ))

    pending_counts = {
        page_id: sum(1 for item in variants if item.status == "pending")
        for page_id, variants in variants_by_page.items()
    }
    return PublishedUrlVariantResolution(
        matched_source_urls_by_published_id=matched_by_page,
        published_ids_by_source_url=dict(ids_by_source),
        variants_by_published_id=variants_by_page,
        pending_count_by_published_id=pending_counts,
    )
