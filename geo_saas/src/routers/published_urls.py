"""Published Pages management APIs.

Published Pages are customer-maintained URLs whose citation performance should
be tracked separately from the global "top cited pages" leaderboard.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from db import database
from geo_common.services import acquire_workspace_lifecycle_shared
from utils.url_normalization import UrlNormalizationError, normalize_url


router = APIRouter()

CSV_IMPORT_MAX_ROWS = 100
CSV_IMPORT_MAX_BYTES = 1_000_000
REVIEW_STATUS_VALUES = {
    "not_submitted",
    "in_review",
    "approved",
    "changes_requested",
    "rejected",
}
PUBLISH_STATUS_VALUES = {
    "draft",
    "scheduled",
    "published",
    "offline",
}
DEFAULT_REVIEW_STATUS = "approved"
DEFAULT_PUBLISH_STATUS = "published"
DEFAULT_IMPORT_DATE_TZ = ZoneInfo("Asia/Shanghai")
CSV_TEMPLATE_HEADERS = [
    "title",
    "published_url",
    "published_at",
    "topics",
    "channel",
    "review_status",
    "publish_status",
    "draft_doc_url",
    "owner_name",
    "notes",
]


class TopicRef(BaseModel):
    id: UUID
    topic_name: str


class PublishedUrlRow(BaseModel):
    id: UUID
    title: str
    published_url: str
    normalized_url: str
    published_at: date
    channel: str
    review_status: str = DEFAULT_REVIEW_STATUS
    publish_status: str = DEFAULT_PUBLISH_STATUS
    draft_doc_url: Optional[str] = None
    owner_name: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    topics: List[TopicRef] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PublishedUrlListOut(BaseModel):
    items: List[PublishedUrlRow]
    total: int
    limit: int
    offset: int


class PublishedUrlUpsertIn(BaseModel):
    client_id: UUID
    title: str
    published_url: str
    published_at: date
    channel: str
    topics: List[UUID] = Field(default_factory=list)
    review_status: Optional[str] = DEFAULT_REVIEW_STATUS
    publish_status: Optional[str] = DEFAULT_PUBLISH_STATUS
    draft_doc_url: Optional[str] = None
    owner_name: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class PublishedUrlImportPreviewIn(BaseModel):
    client_id: UUID
    csv_text: str


class PublishedUrlImportCommitIn(BaseModel):
    client_id: UUID
    csv_text: str


class PublishedUrlImportPreviewRow(BaseModel):
    row_number: int
    title: Optional[str] = None
    published_url: Optional[str] = None
    normalized_url: Optional[str] = None
    published_at: Optional[date] = None
    channel: Optional[str] = None
    review_status: Optional[str] = None
    publish_status: Optional[str] = None
    draft_doc_url: Optional[str] = None
    owner_name: Optional[str] = None
    notes: Optional[str] = None
    topics: List[TopicRef] = Field(default_factory=list)
    action: str
    errors: List[str] = Field(default_factory=list)


class PublishedUrlImportPreviewOut(BaseModel):
    total_rows: int
    valid_count: int
    invalid_count: int
    create_count: int
    update_count: int
    rows: List[PublishedUrlImportPreviewRow]


class PublishedUrlMutationOut(BaseModel):
    id: UUID
    normalized_url: str


class PublishedUrlCitationMatchIn(BaseModel):
    client_id: UUID
    source_url: str
    status: Literal["confirmed", "rejected"]


class PublishedUrlCitationMatchOut(BaseModel):
    published_url_id: UUID
    source_url: str
    match_key: str
    status: Literal["confirmed", "rejected"]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _default_import_date() -> date:
    return datetime.now(DEFAULT_IMPORT_DATE_TZ).date()


def _parse_date(value: str) -> Optional[date]:
    text = _clean(value)
    if not text:
        return _default_import_date()

    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    compact_date = text.split()[0].strip()
    normalized = compact_date.replace("/", "-").replace(".", "-")

    try:
        parts = normalized.split("-")
        if len(parts) == 3:
            year, month, day = (int(part) for part in parts)
            return date(year, month, day)
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _topic_key(value: str) -> str:
    return " ".join(_clean(value).lower().split())


def _split_topics(value: str) -> List[str]:
    text = _clean(value)
    if not text:
        return []
    normalized = text.replace("；", ";").replace("，", ";").replace(",", ";")
    return [part.strip() for part in normalized.split(";") if part.strip()]


def _normalize_enum_token(value: object) -> str:
    return _clean(value).lower().replace("-", "_").replace(" ", "_")


def _validate_enum(
    value: object,
    *,
    field_name: str,
    allowed: set[str],
    default: str,
    errors: Optional[List[str]] = None,
) -> str:
    normalized = _normalize_enum_token(value) or default
    if normalized not in allowed:
        message = f"{field_name} must be one of: {', '.join(sorted(allowed))}"
        if errors is not None:
            errors.append(message)
            return normalized
        raise HTTPException(status_code=400, detail=message)
    return normalized


async def _topic_map(client_id: UUID) -> Dict[str, TopicRef]:
    rows = await database.fetch_all(
        """
        SELECT id, topic_name
        FROM geo_client_topics
        WHERE client_id = :client_id
        ORDER BY topic_name
        """,
        {"client_id": client_id},
    )
    return {
        _topic_key(row["topic_name"]): TopicRef(id=row["id"], topic_name=row["topic_name"])
        for row in rows
    }


async def _validate_client_topic_ids(client_id: UUID, topic_ids: List[UUID]) -> None:
    """Ensure caller-provided topic ids belong to the current client.

    CSV imports resolve topics by name from the current client's topic list, but
    direct create/edit calls carry raw UUIDs. Validate them server-side so a
    client cannot attach another workspace's topic id to a Published URL.
    """
    unique_topic_ids = sorted(set(topic_ids), key=str)
    if not unique_topic_ids:
        return
    params = {"client_id": client_id}
    placeholders = []
    for idx, topic_id in enumerate(unique_topic_ids):
        key = f"topic_{idx}"
        placeholders.append(f":{key}")
        params[key] = topic_id
    rows = await database.fetch_all(
        f"""
        SELECT id
        FROM geo_client_topics
        WHERE client_id = :client_id
          AND id IN ({",".join(placeholders)})
        """,
        params,
    )
    found = {str(row["id"]) for row in rows}
    missing = [str(topic_id) for topic_id in unique_topic_ids if str(topic_id) not in found]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Topics do not belong to this client: {', '.join(missing)}",
        )


async def _existing_url_ids(client_id: UUID, normalized_urls: List[str]) -> Dict[str, UUID]:
    if not normalized_urls:
        return {}
    params = {"client_id": client_id}
    placeholders = []
    for idx, value in enumerate(sorted(set(normalized_urls))):
        key = f"url_{idx}"
        placeholders.append(f":{key}")
        params[key] = value
    rows = await database.fetch_all(
        f"""
        SELECT id, normalized_url
        FROM geo_published_urls
        WHERE client_id = :client_id
          AND normalized_url IN ({",".join(placeholders)})
        """,
        params,
    )
    return {row["normalized_url"]: row["id"] for row in rows}


def _parse_csv_rows(csv_text: str) -> List[dict]:
    if len(csv_text.encode("utf-8")) > CSV_IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"CSV import file must be smaller than {CSV_IMPORT_MAX_BYTES // 1_000_000}MB",
        )
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV header is required")
    rows = list(reader)
    if len(rows) > CSV_IMPORT_MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"CSV import supports at most {CSV_IMPORT_MAX_ROWS} rows per batch",
        )
    return rows


async def _build_preview(payload: PublishedUrlImportPreviewIn) -> PublishedUrlImportPreviewOut:
    raw_rows = _parse_csv_rows(payload.csv_text)
    topics_by_name = await _topic_map(payload.client_id)
    parsed_rows: List[PublishedUrlImportPreviewRow] = []
    normalized_urls: List[str] = []
    seen_in_file: Dict[str, int] = {}

    for idx, raw in enumerate(raw_rows, start=2):
        errors: List[str] = []
        title = _clean(raw.get("title"))
        published_url = _clean(raw.get("published_url"))
        published_at = _parse_date(_clean(raw.get("published_at")))
        channel = _clean(raw.get("channel"))
        review_status = _validate_enum(
            raw.get("review_status"),
            field_name="review_status",
            allowed=REVIEW_STATUS_VALUES,
            default=DEFAULT_REVIEW_STATUS,
            errors=errors,
        )
        publish_status = _validate_enum(
            raw.get("publish_status"),
            field_name="publish_status",
            allowed=PUBLISH_STATUS_VALUES,
            default=DEFAULT_PUBLISH_STATUS,
            errors=errors,
        )

        if not title:
            errors.append("title is required")
        if not published_url:
            errors.append("published_url is required")
        if not published_at:
            errors.append("published_at must be YYYY-MM-DD, YYYY/M/D, or empty")
        if not channel:
            errors.append("channel is required")

        normalized_url = None
        if published_url:
            try:
                normalized_url = normalize_url(published_url)
                normalized_urls.append(normalized_url)
                if normalized_url in seen_in_file:
                    errors.append(
                        f"Duplicate published_url in CSV; first seen at row {seen_in_file[normalized_url]}"
                    )
                else:
                    seen_in_file[normalized_url] = idx
            except UrlNormalizationError as exc:
                errors.append(str(exc))

        matched_topics: List[TopicRef] = []
        for topic_name in _split_topics(_clean(raw.get("topics"))):
            topic = topics_by_name.get(_topic_key(topic_name))
            if not topic:
                errors.append(f"Unmatched topic: {topic_name}")
            else:
                matched_topics.append(topic)

        parsed_rows.append(
            PublishedUrlImportPreviewRow(
                row_number=idx,
                title=title or None,
                published_url=published_url or None,
                normalized_url=normalized_url,
                published_at=published_at,
                channel=channel or None,
                review_status=review_status,
                publish_status=publish_status,
                draft_doc_url=_clean(raw.get("draft_doc_url")) or None,
                owner_name=_clean(raw.get("owner_name")) or None,
                notes=_clean(raw.get("notes")) or None,
                topics=matched_topics,
                action="invalid" if errors else "create",
                errors=errors,
            )
        )

    existing = await _existing_url_ids(payload.client_id, normalized_urls)
    create_count = 0
    update_count = 0
    for row in parsed_rows:
        if row.errors or not row.normalized_url:
            row.action = "invalid"
            continue
        if row.normalized_url in existing:
            row.action = "update"
            update_count += 1
        else:
            row.action = "create"
            create_count += 1

    invalid_count = sum(1 for row in parsed_rows if row.errors)
    return PublishedUrlImportPreviewOut(
        total_rows=len(parsed_rows),
        valid_count=len(parsed_rows) - invalid_count,
        invalid_count=invalid_count,
        create_count=create_count,
        update_count=update_count,
        rows=parsed_rows,
    )


async def _hydrate_topics(items: List[PublishedUrlRow], client_id: UUID) -> None:
    if not items:
        return
    params = {"client_id": client_id}
    placeholders = []
    for idx, item in enumerate(items):
        key = f"id_{idx}"
        placeholders.append(f":{key}")
        params[key] = item.id
    rows = await database.fetch_all(
        f"""
        SELECT put.published_url_id, ct.id, ct.topic_name
        FROM geo_published_url_topics put
        JOIN geo_client_topics ct
          ON ct.id = put.topic_id
         AND ct.client_id = put.client_id
        WHERE put.client_id = :client_id
          AND put.published_url_id IN ({",".join(placeholders)})
        ORDER BY ct.topic_name
        """,
        params,
    )
    by_id: Dict[UUID, List[TopicRef]] = {item.id: [] for item in items}
    for row in rows:
        by_id[row["published_url_id"]].append(TopicRef(id=row["id"], topic_name=row["topic_name"]))
    for item in items:
        item.topics = by_id.get(item.id, [])


async def _upsert_one(payload: PublishedUrlUpsertIn) -> PublishedUrlMutationOut:
    await _validate_client_topic_ids(payload.client_id, payload.topics)
    normalized_url = normalize_url(payload.published_url)
    review_status = _validate_enum(
        payload.review_status,
        field_name="review_status",
        allowed=REVIEW_STATUS_VALUES,
        default=DEFAULT_REVIEW_STATUS,
    )
    publish_status = _validate_enum(
        payload.publish_status,
        field_name="publish_status",
        allowed=PUBLISH_STATUS_VALUES,
        default=DEFAULT_PUBLISH_STATUS,
    )
    async with database.transaction() as conn:
        await acquire_workspace_lifecycle_shared(conn, str(payload.client_id))
        row = await conn.fetchrow(
            """
            INSERT INTO geo_published_urls (
                client_id, title, published_url, normalized_url, published_at,
                channel, review_status, publish_status, draft_doc_url,
                owner_name, notes, is_active, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9,
                $10, $11, $12, NOW()
            )
            ON CONFLICT (client_id, normalized_url)
            DO UPDATE SET
                title = EXCLUDED.title,
                published_url = EXCLUDED.published_url,
                published_at = EXCLUDED.published_at,
                channel = EXCLUDED.channel,
                review_status = EXCLUDED.review_status,
                publish_status = EXCLUDED.publish_status,
                draft_doc_url = EXCLUDED.draft_doc_url,
                owner_name = EXCLUDED.owner_name,
                notes = EXCLUDED.notes,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
            RETURNING id, normalized_url
            """,
            payload.client_id,
            payload.title.strip(),
            payload.published_url.strip(),
            normalized_url,
            payload.published_at,
            payload.channel.strip(),
            review_status,
            publish_status,
            payload.draft_doc_url.strip() if payload.draft_doc_url else None,
            payload.owner_name.strip() if payload.owner_name else None,
            payload.notes.strip() if payload.notes else None,
            payload.is_active,
        )
        published_url_id = row["id"]
        await conn.execute(
            "DELETE FROM geo_published_url_topics WHERE client_id = $1 AND published_url_id = $2",
            payload.client_id,
            published_url_id,
        )
        if payload.topics:
            await conn.executemany(
                """
                INSERT INTO geo_published_url_topics (client_id, published_url_id, topic_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                [(payload.client_id, published_url_id, topic_id) for topic_id in payload.topics],
            )
    return PublishedUrlMutationOut(id=published_url_id, normalized_url=normalized_url)


async def _update_one(
    published_url_id: UUID,
    payload: PublishedUrlUpsertIn,
) -> PublishedUrlMutationOut:
    await _validate_client_topic_ids(payload.client_id, payload.topics)
    normalized_url = normalize_url(payload.published_url)
    review_status = _validate_enum(
        payload.review_status,
        field_name="review_status",
        allowed=REVIEW_STATUS_VALUES,
        default=DEFAULT_REVIEW_STATUS,
    )
    publish_status = _validate_enum(
        payload.publish_status,
        field_name="publish_status",
        allowed=PUBLISH_STATUS_VALUES,
        default=DEFAULT_PUBLISH_STATUS,
    )
    async with database.transaction() as conn:
        await acquire_workspace_lifecycle_shared(conn, str(payload.client_id))
        conflict = await conn.fetchrow(
            """
            SELECT id
            FROM geo_published_urls
            WHERE client_id = $1
              AND normalized_url = $2
              AND id <> $3
            """,
            payload.client_id,
            normalized_url,
            published_url_id,
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail="Another Published URL with the same normalized URL already exists",
            )
        row = await conn.fetchrow(
            """
            UPDATE geo_published_urls
            SET title = $3,
                published_url = $4,
                normalized_url = $5,
                published_at = $6,
                channel = $7,
                review_status = $8,
                publish_status = $9,
                draft_doc_url = $10,
                owner_name = $11,
                notes = $12,
                is_active = $13,
                updated_at = NOW()
            WHERE client_id = $1
              AND id = $2
            RETURNING id, normalized_url
            """,
            payload.client_id,
            published_url_id,
            payload.title.strip(),
            payload.published_url.strip(),
            normalized_url,
            payload.published_at,
            payload.channel.strip(),
            review_status,
            publish_status,
            payload.draft_doc_url.strip() if payload.draft_doc_url else None,
            payload.owner_name.strip() if payload.owner_name else None,
            payload.notes.strip() if payload.notes else None,
            payload.is_active,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Published URL not found")
        await conn.execute(
            "DELETE FROM geo_published_url_topics WHERE client_id = $1 AND published_url_id = $2",
            payload.client_id,
            published_url_id,
        )
        if payload.topics:
            await conn.executemany(
                """
                INSERT INTO geo_published_url_topics (client_id, published_url_id, topic_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                [(payload.client_id, published_url_id, topic_id) for topic_id in payload.topics],
            )
    return PublishedUrlMutationOut(id=row["id"], normalized_url=row["normalized_url"])


@router.get("", response_model=PublishedUrlListOut)
async def list_published_urls(
    client_id: UUID,
    search: Optional[str] = None,
    status: Optional[str] = None,
    publish_status: Optional[str] = None,
    channel: Optional[str] = None,
    topic_id: Optional[UUID] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PublishedUrlListOut:
    limit = int(limit) if isinstance(limit, int) else 20
    offset = int(offset) if isinstance(offset, int) else 0
    where_parts = ["pu.client_id = :client_id"]
    params = {"client_id": client_id, "limit": limit, "offset": offset}
    if search:
        where_parts.append(
            """
            (
                pu.published_url ILIKE :search
                OR pu.title ILIKE :search
                OR pu.channel ILIKE :search
                OR EXISTS (
                    SELECT 1
                    FROM geo_published_url_topics put_search
                    JOIN geo_client_topics ct_search
                      ON ct_search.id = put_search.topic_id
                     AND ct_search.client_id = put_search.client_id
                    WHERE put_search.client_id = pu.client_id
                      AND put_search.published_url_id = pu.id
                      AND ct_search.topic_name ILIKE :search
                )
            )
            """
        )
        params["search"] = f"%{search}%"
    effective_publish_status = publish_status or status
    if effective_publish_status:
        normalized_publish_status = _validate_enum(
            effective_publish_status,
            field_name="publish_status",
            allowed=PUBLISH_STATUS_VALUES,
            default=DEFAULT_PUBLISH_STATUS,
        )
        where_parts.append("pu.publish_status = :publish_status")
        params["publish_status"] = normalized_publish_status
    if channel:
        where_parts.append("pu.channel = :channel")
        params["channel"] = channel
    if topic_id:
        where_parts.append(
            """
            EXISTS (
                SELECT 1 FROM geo_published_url_topics put
                WHERE put.client_id = pu.client_id
                  AND put.published_url_id = pu.id
                  AND put.topic_id = :topic_id
            )
            """
        )
        params["topic_id"] = topic_id

    where_sql = " AND ".join(where_parts)
    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM geo_published_urls pu WHERE {where_sql}",
        params,
    ) or 0
    rows = await database.fetch_all(
        f"""
        SELECT
            pu.id, pu.title, pu.published_url, pu.normalized_url,
            pu.published_at, pu.channel, pu.review_status, pu.publish_status,
            pu.draft_doc_url, pu.owner_name, pu.notes,
            pu.is_active, pu.created_at, pu.updated_at
        FROM geo_published_urls pu
        WHERE {where_sql}
        ORDER BY pu.published_at DESC, pu.updated_at DESC
        OFFSET :offset
        LIMIT :limit
        """,
        params,
    )
    items = []
    should_hydrate = False
    for row in rows:
        payload = dict(row)
        raw_topics = payload.pop("topics", None)
        topic_refs = [
            topic if isinstance(topic, TopicRef) else TopicRef(**topic)
            for topic in (raw_topics or [])
        ]
        if raw_topics is None:
            should_hydrate = True
        items.append(PublishedUrlRow(**payload, topics=topic_refs))
    if should_hydrate:
        await _hydrate_topics(items, client_id)
    return PublishedUrlListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/channels", response_model=List[str])
async def list_published_url_channels(client_id: UUID) -> List[str]:
    rows = await database.fetch_all(
        """
        SELECT DISTINCT channel
        FROM geo_published_urls
        WHERE client_id = :client_id
          AND channel IS NOT NULL
          AND channel <> ''
        ORDER BY channel
        """,
        {"client_id": client_id},
    )
    return [row["channel"] for row in rows]


@router.get("/csv-template", response_class=PlainTextResponse)
async def download_published_url_csv_template() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_TEMPLATE_HEADERS)
    writer.writerows([
        [
            "Published launch page",
            "https://example.com/blog/launch?utm_source=newsletter",
            "2026-06-10",
            "AI Video;AI Image",
            "Official Website",
            "approved",
            "published",
            "https://example.feishu.cn/docx/xxx",
            "Anthony",
            "review_status=approved; publish_status=published",
        ],
        [
            "Draft Reddit post",
            "https://www.reddit.com/r/example/comments/abc/example_post/",
            "2026/6/11",
            "AI Video",
            "Reddit",
            "in_review",
            "draft",
            "https://example.feishu.cn/docx/draft",
            "Anthony",
            "review_status=in_review; publish_status=draft",
        ],
        [
            "Scheduled Medium article",
            "https://medium.com/@example/scheduled-article",
            "",
            "AI Image",
            "Medium",
            "not_submitted",
            "scheduled",
            "",
            "Anthony",
            "published_at empty defaults to today; review_status=not_submitted; publish_status=scheduled",
        ],
        [
            "Revision needed page",
            "https://example.com/blog/revision-needed",
            "2026-06-13",
            "AI Design",
            "Official Website",
            "changes_requested",
            "draft",
            "https://example.feishu.cn/docx/revision",
            "Anthony",
            "review_status=changes_requested; publish_status=draft",
        ],
        [
            "Offline rejected sample",
            "https://example.com/blog/offline-page",
            "2026-06-14",
            "AI Video",
            "Agency",
            "rejected",
            "offline",
            "",
            "Anthony",
            "review_status=rejected; publish_status=offline",
        ],
    ])
    return "\ufeff" + output.getvalue()


@router.post("", response_model=PublishedUrlMutationOut)
async def upsert_published_url(payload: PublishedUrlUpsertIn) -> PublishedUrlMutationOut:
    return await _upsert_one(payload)


@router.patch("/{published_url_id}", response_model=PublishedUrlMutationOut)
async def update_published_url(
    published_url_id: UUID,
    payload: PublishedUrlUpsertIn,
) -> PublishedUrlMutationOut:
    return await _update_one(published_url_id, payload)


@router.put(
    "/{published_url_id}/citation-match",
    response_model=PublishedUrlCitationMatchOut,
)
async def set_published_url_citation_match(
    published_url_id: UUID,
    payload: PublishedUrlCitationMatchIn,
) -> PublishedUrlCitationMatchOut:
    source_url = payload.source_url.strip()
    try:
        match_key = normalize_url(source_url)
    except UrlNormalizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    async with database.transaction() as conn:
        await acquire_workspace_lifecycle_shared(conn, str(payload.client_id))
        published = await conn.fetchrow(
            """
            SELECT id
            FROM geo_published_urls
            WHERE client_id = $1
              AND id = $2
            """,
            payload.client_id,
            published_url_id,
        )
        if not published:
            raise HTTPException(status_code=404, detail="Published URL not found")
        if payload.status == "confirmed":
            conflict = await conn.fetchrow(
                """
                SELECT published_url_id
                FROM geo_published_url_citation_matches
                WHERE client_id = $1
                  AND citation_match_key = $2
                  AND status = 'confirmed'
                  AND published_url_id <> $3
                """,
                payload.client_id,
                match_key,
                published_url_id,
            )
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail="This Citation URL is already tracked by another Published URL",
                )
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO geo_published_url_citation_matches (
                    client_id,
                    published_url_id,
                    citation_url,
                    citation_match_key,
                    status,
                    updated_at
                )
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (client_id, published_url_id, citation_match_key)
                DO UPDATE SET
                    citation_url = EXCLUDED.citation_url,
                    status = EXCLUDED.status,
                    updated_at = NOW()
                RETURNING published_url_id, citation_url, citation_match_key, status
                """,
                payload.client_id,
                published_url_id,
                source_url,
                match_key,
                payload.status,
            )
        except asyncpg.UniqueViolationError as exc:
            # The partial unique index is the final guard against two concurrent
            # confirmations assigning one Match Key to different Published URLs.
            raise HTTPException(
                status_code=409,
                detail="This Citation URL is already tracked by another Published URL",
            ) from exc
    return PublishedUrlCitationMatchOut(
        published_url_id=row["published_url_id"],
        source_url=row["citation_url"],
        match_key=row["citation_match_key"],
        status=row["status"],
    )


@router.post("/import/preview", response_model=PublishedUrlImportPreviewOut)
async def preview_published_urls_import(
    payload: PublishedUrlImportPreviewIn,
) -> PublishedUrlImportPreviewOut:
    return await _build_preview(payload)


@router.post("/import/commit", response_model=PublishedUrlImportPreviewOut)
async def commit_published_urls_import(
    payload: PublishedUrlImportCommitIn,
) -> PublishedUrlImportPreviewOut:
    preview = await _build_preview(PublishedUrlImportPreviewIn(**payload.model_dump()))
    if preview.invalid_count:
        raise HTTPException(status_code=400, detail="CSV contains invalid rows")
    for row in preview.rows:
        await _upsert_one(
            PublishedUrlUpsertIn(
                client_id=payload.client_id,
                title=row.title or "",
                published_url=row.published_url or "",
                published_at=row.published_at or date.today(),
                channel=row.channel or "",
                topics=[topic.id for topic in row.topics],
                review_status=row.review_status,
                publish_status=row.publish_status,
                draft_doc_url=row.draft_doc_url,
                owner_name=row.owner_name,
                notes=row.notes,
                is_active=True,
            )
        )
    return preview


@router.patch("/{published_url_id}/disable", response_model=PublishedUrlMutationOut)
async def disable_published_url(client_id: UUID, published_url_id: UUID) -> PublishedUrlMutationOut:
    async with database.transaction() as conn:
        await acquire_workspace_lifecycle_shared(conn, str(client_id))
        row = await conn.fetchrow(
            """
            UPDATE geo_published_urls
            SET is_active = FALSE, publish_status = 'offline', updated_at = NOW()
            WHERE client_id = $1
              AND id = $2
            RETURNING id, normalized_url
            """,
            client_id,
            published_url_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Published URL not found")
    return PublishedUrlMutationOut(id=row["id"], normalized_url=row["normalized_url"])


@router.delete("/{published_url_id}", response_model=PublishedUrlMutationOut)
async def delete_published_url(client_id: UUID, published_url_id: UUID) -> PublishedUrlMutationOut:
    async with database.transaction() as conn:
        await acquire_workspace_lifecycle_shared(conn, str(client_id))
        row = await conn.fetchrow(
            """
            SELECT id, normalized_url
            FROM geo_published_urls
            WHERE client_id = $1
              AND id = $2
            """,
            client_id,
            published_url_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Published URL not found")
        await conn.execute(
            "DELETE FROM geo_published_url_topics WHERE client_id = $1 AND published_url_id = $2",
            client_id,
            published_url_id,
        )
        await conn.execute(
            "DELETE FROM geo_published_urls WHERE client_id = $1 AND id = $2",
            client_id,
            published_url_id,
        )
    return PublishedUrlMutationOut(id=row["id"], normalized_url=row["normalized_url"])
