import asyncio
from datetime import date
from uuid import UUID

import pytest

from routers import published_urls


CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_CLIENT_ID = UUID("22222222-2222-2222-2222-222222222222")
PUBLISHED_URL_ID = UUID("33333333-3333-3333-3333-333333333333")


def test_published_url_citation_match_mutation_exists():
    assert hasattr(published_urls, "set_published_url_citation_match")


class FakeCitationMatchConnection:
    def __init__(self, *, conflict=False):
        self.conflict = conflict
        self.fetchrow_calls = []

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        if "SELECT id" in sql and "FROM geo_published_urls" in sql:
            return {"id": PUBLISHED_URL_ID}
        if "SELECT published_url_id" in sql:
            return {"published_url_id": OTHER_CLIENT_ID} if self.conflict else None
        if "INSERT INTO geo_published_url_citation_matches" in sql:
            return {
                "published_url_id": args[1],
                "citation_url": args[2],
                "citation_match_key": args[3],
                "status": args[4],
            }
        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeTransactionContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeCitationMatchDatabase:
    def __init__(self, connection):
        self.connection = connection

    def transaction(self):
        return FakeTransactionContext(self.connection)


async def _no_workspace_lock(*_args, **_kwargs):
    return None


def test_confirm_match_keeps_raw_url_and_stores_conservative_match_key(monkeypatch):
    connection = FakeCitationMatchConnection()
    monkeypatch.setattr(
        published_urls, "database", FakeCitationMatchDatabase(connection)
    )
    monkeypatch.setattr(
        published_urls, "acquire_workspace_lifecycle_shared", _no_workspace_lock
    )
    raw_url = "https://Example.com/article?variant=red&utm_source=chatgpt.com"

    result = asyncio.run(
        published_urls.set_published_url_citation_match(
            PUBLISHED_URL_ID,
            published_urls.PublishedUrlCitationMatchIn(
                client_id=CLIENT_ID,
                source_url=raw_url,
                status="confirmed",
            ),
        )
    )

    assert result.source_url == raw_url
    assert result.match_key == "https://example.com/article?variant=red"
    all_sql = "\n".join(sql for sql, _ in connection.fetchrow_calls)
    assert "geo_citations" not in all_sql


def test_confirm_match_rejects_cross_page_match_key_conflict(monkeypatch):
    connection = FakeCitationMatchConnection(conflict=True)
    monkeypatch.setattr(
        published_urls, "database", FakeCitationMatchDatabase(connection)
    )
    monkeypatch.setattr(
        published_urls, "acquire_workspace_lifecycle_shared", _no_workspace_lock
    )

    with pytest.raises(published_urls.HTTPException) as exc_info:
        asyncio.run(
            published_urls.set_published_url_citation_match(
                PUBLISHED_URL_ID,
                published_urls.PublishedUrlCitationMatchIn(
                    client_id=CLIENT_ID,
                    source_url="https://example.com/article?variant=red",
                    status="confirmed",
                ),
            )
        )

    assert exc_info.value.status_code == 409


def test_citation_match_rejects_invalid_url_as_validation_error(monkeypatch):
    connection = FakeCitationMatchConnection()
    monkeypatch.setattr(
        published_urls, "database", FakeCitationMatchDatabase(connection)
    )

    with pytest.raises(published_urls.HTTPException) as exc_info:
        asyncio.run(
            published_urls.set_published_url_citation_match(
                PUBLISHED_URL_ID,
                published_urls.PublishedUrlCitationMatchIn(
                    client_id=CLIENT_ID,
                    source_url="",
                    status="confirmed",
                ),
            )
        )

    assert exc_info.value.status_code == 422
    assert connection.fetchrow_calls == []


class FakePublishedUrlsDatabase:
    def __init__(self):
        self.fetch_all_calls = []
        self.fetch_one_calls = []
        self.fetch_val_calls = []
        self.execute_calls = []
        self.rows = []
        self.topic_rows = [
            {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "topic_name": "AI Video"},
            {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "topic_name": "AI Image"},
        ]

    async def fetch_all(self, sql, params=None):
        self.fetch_all_calls.append((sql, params or {}))
        if "FROM geo_client_topics" in sql:
            if "id IN" in sql:
                requested = {str(value) for key, value in (params or {}).items() if key.startswith("topic_")}
                return [row for row in self.topic_rows if str(row["id"]) in requested]
            return self.topic_rows
        if "SELECT DISTINCT channel" in sql:
            return [{"channel": "Reddit"}, {"channel": "Official Website"}]
        if "FROM geo_published_urls pu" in sql:
            return self.rows
        return []

    async def fetch_one(self, sql, params=None):
        self.fetch_one_calls.append((sql, params or {}))
        return None

    async def fetch_val(self, sql, params=None):
        self.fetch_val_calls.append((sql, params or {}))
        if "COUNT" in sql:
            return len(self.rows)
        return None

    async def execute(self, sql, params=None):
        self.execute_calls.append((sql, params or {}))
        return "EXECUTE 1"


def test_csv_preview_maps_topics_case_insensitively(monkeypatch):
    fake_db = FakePublishedUrlsDatabase()
    monkeypatch.setattr(published_urls, "database", fake_db)

    csv_text = (
        "title,published_url,published_at,topics,channel,review_status,publish_status\n"
        "Page,https://Example.com/a?utm_source=x,2026-06-10,ai video; AI IMAGE,Reddit,approved,published\n"
    )

    result = asyncio.run(
        published_urls.preview_published_urls_import(
            published_urls.PublishedUrlImportPreviewIn(
                client_id=CLIENT_ID,
                csv_text=csv_text,
            )
        )
    )

    assert result.valid_count == 1
    assert result.invalid_count == 0
    assert result.rows[0].normalized_url == "https://example.com/a"
    assert [topic.topic_name for topic in result.rows[0].topics] == ["AI Video", "AI Image"]


def test_csv_preview_rejects_unmatched_topics(monkeypatch):
    fake_db = FakePublishedUrlsDatabase()
    monkeypatch.setattr(published_urls, "database", fake_db)

    csv_text = (
        "title,published_url,published_at,topics,channel,review_status,publish_status\n"
        "Page,https://example.com/a,2026-06-10,Unknown Topic,Reddit,approved,published\n"
    )

    result = asyncio.run(
        published_urls.preview_published_urls_import(
            published_urls.PublishedUrlImportPreviewIn(
                client_id=CLIENT_ID,
                csv_text=csv_text,
            )
        )
    )

    assert result.valid_count == 0
    assert result.invalid_count == 1
    assert "Unmatched topic" in result.rows[0].errors[0]


def test_csv_preview_rejects_duplicate_urls_in_same_file(monkeypatch):
    fake_db = FakePublishedUrlsDatabase()
    monkeypatch.setattr(published_urls, "database", fake_db)

    csv_text = (
        "title,published_url,published_at,topics,channel,review_status,publish_status\n"
        "Page A,https://example.com/a?utm_source=x,2026-06-10,AI Video,Reddit,approved,published\n"
        "Page B,https://example.com/a,2026-06-11,AI Image,Reddit,approved,published\n"
    )

    result = asyncio.run(
        published_urls.preview_published_urls_import(
            published_urls.PublishedUrlImportPreviewIn(
                client_id=CLIENT_ID,
                csv_text=csv_text,
            )
        )
    )

    assert result.valid_count == 1
    assert result.invalid_count == 1
    assert "Duplicate published_url" in result.rows[1].errors[0]


def test_csv_preview_rejects_invalid_publish_status(monkeypatch):
    fake_db = FakePublishedUrlsDatabase()
    monkeypatch.setattr(published_urls, "database", fake_db)

    csv_text = (
        "title,published_url,published_at,topics,channel,review_status,publish_status\n"
        "Page,https://example.com/a,2026-06-10,AI Video,Reddit,approved,live\n"
    )

    result = asyncio.run(
        published_urls.preview_published_urls_import(
            published_urls.PublishedUrlImportPreviewIn(
                client_id=CLIENT_ID,
                csv_text=csv_text,
            )
        )
    )

    assert result.valid_count == 0
    assert result.invalid_count == 1
    assert "publish_status must be one of" in result.rows[0].errors[0]


def test_list_query_is_client_scoped(monkeypatch):
    fake_db = FakePublishedUrlsDatabase()
    fake_db.rows = [
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "client_id": str(CLIENT_ID),
            "title": "Page",
            "published_url": "https://example.com/a",
            "normalized_url": "https://example.com/a",
            "published_at": date(2026, 6, 10),
            "channel": "Reddit",
            "review_status": "approved",
            "publish_status": "published",
            "draft_doc_url": None,
            "owner_name": None,
            "notes": None,
            "is_active": True,
            "created_at": None,
            "updated_at": None,
            "topics": [],
        }
    ]
    monkeypatch.setattr(published_urls, "database", fake_db)

    result = asyncio.run(published_urls.list_published_urls(client_id=CLIENT_ID))

    assert result.total == 1
    assert "pu.client_id = :client_id" in fake_db.fetch_all_calls[-1][0]
    assert fake_db.fetch_all_calls[-1][1]["client_id"] == CLIENT_ID


def test_list_search_includes_client_scoped_topics(monkeypatch):
    fake_db = FakePublishedUrlsDatabase()
    monkeypatch.setattr(published_urls, "database", fake_db)

    asyncio.run(published_urls.list_published_urls(client_id=CLIENT_ID, search="AI Video"))

    sql = fake_db.fetch_all_calls[-1][0]
    assert "geo_published_url_topics put_search" in sql
    assert "ct_search.client_id = put_search.client_id" in sql
    assert "put_search.client_id = pu.client_id" in sql


def test_direct_topic_ids_must_belong_to_client(monkeypatch):
    fake_db = FakePublishedUrlsDatabase()
    monkeypatch.setattr(published_urls, "database", fake_db)

    with pytest.raises(published_urls.HTTPException) as exc_info:
        asyncio.run(
            published_urls._validate_client_topic_ids(
                CLIENT_ID,
                [UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")],
            )
        )

    assert exc_info.value.status_code == 400
    assert "do not belong to this client" in exc_info.value.detail
