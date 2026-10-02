from __future__ import annotations

import csv
import io
import asyncio
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from geo_common.db import TenantIsolationError

from routers import prompt_import
from routers.prompt_import_service import (
    CSV_HEADERS,
    ImportValidationError,
    PromptImportService,
    PromptImportUndoLimiter,
)


CLIENT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TOPIC_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _raw(prompt: str = "Best robot vacuum?") -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(CSV_HEADERS)
    writer.writerow(["AnswerX", "Robot Vacuum", "S8", prompt, "chatgpt", "US", "en-US", "Solution Discovery"])
    return stream.getvalue().encode()


def _raw_rows(rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(CSV_HEADERS)
    writer.writerows(rows)
    return stream.getvalue().encode()


class Tx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.events.append("tx_enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.events.append("tx_rollback" if exc else "tx_commit")
        return False


class Acquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *args): return False


class Pool:
    def __init__(self, conn): self.conn = conn
    def acquire(self): return Acquire(self.conn)


class Conn:
    def __init__(
        self,
        *,
        existing=None,
        batch=None,
        client=None,
        topics=None,
        products=None,
        platforms=None,
        intents=None,
        languages=None,
    ):
        self.existing = existing or []
        self.batch = batch
        self.client = client or {
            "id": CLIENT_ID, "name": "AnswerX", "client_prompt_quota": 20,
            "config_platforms": ["chatgpt"], "config_countries": ["US"],
            "config_languages": ["en-US"],
        }
        self.topics = topics or [{"id": TOPIC_ID, "topic_name": "Robot Vacuum"}]
        self.products = products or [{"topic_id": TOPIC_ID, "product_name": "S8"}]
        self.platforms = platforms or [{
            "platform_id": "chatgpt", "display_name": "ChatGPT",
            "supported_countries": ["US"],
        }]
        self.intents = intents or [{"intent_name": "Solution Discovery"}]
        self.languages = languages or [{"language_code": "en-US", "language": "English"}]
        self.events = []
        self.fetch_queries = []
        self.audit_args = None
        self.lock_keys = []

    def transaction(self): return Tx(self)

    async def fetchrow(self, sql, *args):
        if "FROM geo_clients" in sql:
            return self.client
        if "FROM geo_prompt_import_batches" in sql:
            return self.batch
        if "INSERT INTO geo_prompt_import_batches" in sql:
            self.events.append("audit")
            self.audit_args = args
            return {"id": "dddddddd-dddd-dddd-dddd-dddddddddddd"}
        return None

    async def fetch(self, sql, *args):
        self.fetch_queries.append(sql)
        if "prompt_bulk_insert" in sql:
            self.events.append(f"bulk:{len(args[1])}")
            return [{"id": value} for value in args[1]]
        if "geo_client_topics" in sql:
            return self.topics
        if "geo_client_topic_products" in sql:
            return self.products
        if "geo_global_platforms" in sql:
            return self.platforms
        if "geo_global_intents" in sql:
            return self.intents
        if "geo_global_languages" in sql:
            return self.languages
        if "geo_client_prompts" in sql:
            return self.existing
        return []

    async def fetchval(self, sql, *args):
        if "SELECT EXISTS(SELECT 1 FROM geo_clients" in sql:
            return True
        if "pg_try_advisory_xact_lock_shared" in sql:
            self.events.append("lock")
            self.lock_keys.append(args[0])
            return True
        if "pg_advisory_xact_lock" in sql:
            self.events.append("lock")
            self.lock_keys.append(args[0])
            return None
        if "COUNT(*)" in sql and "geo_client_prompts" in sql:
            return len(args[1])
        return 0

    async def executemany(self, sql, records):
        records = list(records)
        self.events.append(f"bulk:{len(records)}")

    async def execute(self, sql, *args):
        if "UPDATE geo_prompt_import_batches" in sql:
            self.events.append("batch_status")
            return "UPDATE 1"
        return "DELETE 1"


@pytest.fixture
def anyio_backend(): return "asyncio"


@pytest.mark.anyio
async def test_preview_classifies_create_skip_and_conflict_tenant_scoped() -> None:
    existing = [{"id": UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"), "topic_id": UUID(TOPIC_ID),
                 "text": "Best robot vacuum?", "product": "S8", "intent": "Solution Discovery",
                 "platform": "chatgpt", "country": "US", "language": "en-US", "is_active": True}]
    service = PromptImportService(Pool(Conn(existing=existing)))
    preview = await service.preview(CLIENT_ID, _raw())
    assert preview.action_counts == {"create": 0, "skip": 1, "conflict": 0, "invalid": 0}
    assert preview.quota_before == 1
    assert preview.quota_after == 1
    assert preview.rows[0]["action"] == "skip"

    existing[0]["intent"] = "Specifics Inquiry"
    conflict = await PromptImportService(Pool(Conn(existing=existing))).preview(CLIENT_ID, _raw())
    assert conflict.action_counts["conflict"] == 1


@pytest.mark.anyio
async def test_allowed_values_labels_are_locale_aware_without_changing_canonical_values() -> None:
    service = PromptImportService(Pool(Conn()))

    english = await service.allowed_values(CLIENT_ID, locale="en-US")
    chinese = await service.allowed_values(CLIENT_ID, locale="zh-CN")

    en_language = next(row for row in english["rows"] if row["type"] == "Language")
    zh_language = next(row for row in chinese["rows"] if row["type"] == "Language")
    assert en_language["value"] == zh_language["value"] == "en-US"
    assert en_language["label"] == "English"
    assert zh_language["label"] == "en-US"

    en_platform = next(row for row in english["rows"] if row["type"] == "AI Platform")
    zh_platform = next(row for row in chinese["rows"] if row["type"] == "AI Platform")
    assert en_platform["value"] == zh_platform["value"] == "chatgpt"
    assert en_platform["label"] == zh_platform["label"] == "ChatGPT"

    chinese_label_service = PromptImportService(Pool(Conn(
        client={
            "id": CLIENT_ID, "name": "AnswerX", "client_prompt_quota": 20,
            "config_platforms": ["chatgpt"], "config_countries": ["US"],
            "config_languages": ["zh-CN"],
        },
        languages=[{"language_code": "zh-CN", "language": "中文"}],
    )))
    chinese_ui = await chinese_label_service.allowed_values(CLIENT_ID, locale="zh-CN")
    english_ui = await chinese_label_service.allowed_values(CLIENT_ID, locale="en-US")
    assert next(row for row in chinese_ui["rows"] if row["type"] == "Language")["label"] == "中文"
    assert next(row for row in english_ui["rows"] if row["type"] == "Language")["label"] == "zh-CN"


@pytest.mark.anyio
async def test_allowed_values_does_not_assume_topics_have_an_is_active_column() -> None:
    conn = Conn()
    await PromptImportService(Pool(conn)).allowed_values(CLIENT_ID)

    topic_query = next(sql for sql in conn.fetch_queries if "FROM geo_client_topics" in sql)
    assert "is_active" not in topic_query


@pytest.mark.anyio
async def test_allowed_values_json_and_csv_share_the_same_locale_resolver() -> None:
    pool = Pool(Conn())
    json_response = await prompt_import.get_allowed_values(UUID(CLIENT_ID), locale="zh-CN", response=prompt_import.Response(), pool=pool)
    csv_response = await prompt_import.download_allowed_values(UUID(CLIENT_ID), locale="zh-CN", pool=pool)
    decoded = bytes(csv_response.body).decode("utf-8-sig")

    language = next(row for row in json_response["rows"] if row["type"] == "Language")
    assert language["label"] == "en-US"
    assert "Language,en-US,en-US" in decoded


def _two_platform_conn(*, existing=None) -> Conn:
    return Conn(
        existing=existing,
        client={
            "id": CLIENT_ID,
            "name": "AnswerX",
            "client_prompt_quota": 20,
            "config_platforms": ["chatgpt", "gemini"],
            "config_countries": ["US"],
            "config_languages": ["en-US"],
        },
        platforms=[
            {"platform_id": "chatgpt", "display_name": "ChatGPT", "supported_countries": ["US"]},
            {"platform_id": "gemini", "display_name": "Gemini", "supported_countries": ["US"]},
        ],
        intents=[
            {"intent_name": "Solution Discovery"},
            {"intent_name": "Specifics Inquiry"},
        ],
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("existing", "expected_actions", "expected_counts"),
    [
        (
            [{
                "id": UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
                "topic_id": UUID(TOPIC_ID),
                "text": "Best robot vacuum?",
                "product": "S8",
                "intent": "Specifics Inquiry",
                "platform": "chatgpt",
                "country": "US",
                "language": "en-US",
                "is_active": True,
            }],
            ["conflict", "create"],
            {"create": 1, "skip": 0, "conflict": 1, "invalid": 0},
        ),
        (
            [
                {
                    "id": UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
                    "topic_id": UUID(TOPIC_ID),
                    "text": "Best robot vacuum?",
                    "product": "S8",
                    "intent": "Solution Discovery",
                    "platform": "chatgpt",
                    "country": "US",
                    "language": "en-US",
                    "is_active": True,
                },
                {
                    "id": UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
                    "topic_id": UUID(TOPIC_ID),
                    "text": "Best robot vacuum?",
                    "product": "S8",
                    "intent": "Specifics Inquiry",
                    "platform": "gemini",
                    "country": "US",
                    "language": "en-US",
                    "is_active": True,
                },
            ],
            ["skip", "conflict"],
            {"create": 0, "skip": 1, "conflict": 1, "invalid": 0},
        ),
    ],
)
async def test_mixed_row_preserves_physical_actions_and_summary_counts(
    existing, expected_actions, expected_counts
) -> None:
    preview = await PromptImportService(Pool(_two_platform_conn(existing=existing))).preview(
        CLIENT_ID,
        _raw_rows([[
            "AnswerX", "Robot Vacuum", "S8", "Best robot vacuum?",
            "chatgpt|gemini", "US", "en-US", "Solution Discovery",
        ]]),
    )

    assert preview.rows[0]["action"] == "conflict"
    assert [variant["action"] for variant in preview.rows[0]["variants"]] == expected_actions
    assert preview.action_counts == expected_counts


@pytest.mark.anyio
async def test_any_incompatible_database_duplicate_wins_over_compatible_match_and_changes_state() -> None:
    compatible = {
        "id": UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
        "topic_id": UUID(TOPIC_ID),
        "text": "Best robot vacuum?",
        "product": "S8",
        "intent": "Solution Discovery",
        "platform": "chatgpt",
        "country": "US",
        "language": "en-US",
        "is_active": True,
    }
    incompatible = {
        **compatible,
        "id": UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        "intent": "Specifics Inquiry",
    }
    conn = _two_platform_conn(existing=[compatible])
    service = PromptImportService(Pool(conn))
    original = await service.preview(CLIENT_ID, _raw())
    assert original.action_counts["skip"] == 1

    conn.existing.append(incompatible)
    refreshed = await service.preview(CLIENT_ID, _raw())

    assert refreshed.action_counts == {"create": 0, "skip": 0, "conflict": 1, "invalid": 0}
    assert refreshed.rows[0]["errors"][0]["code"] == "metadata_conflict"
    assert refreshed.preview_state_sha256 != original.preview_state_sha256


@pytest.mark.anyio
async def test_import_skips_compatible_inactive_variant_without_mutating_it() -> None:
    inactive_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")

    class InactiveConn(Conn):
        async def fetch(self, sql, *args):
            if "SELECT DISTINCT topic_id" in sql and "is_active = TRUE" in sql:
                return []
            return await super().fetch(sql, *args)

    conn = InactiveConn(existing=[{
        "id": inactive_id, "topic_id": UUID(TOPIC_ID),
        "text": "Best robot vacuum?", "product": "S8",
        "intent": "Solution Discovery", "platform": "chatgpt",
        "country": "US", "language": "en-US", "is_active": False,
    }])
    service = PromptImportService(Pool(conn))
    preview = await service.preview(CLIENT_ID, _raw())

    assert preview.action_counts == {"create": 0, "skip": 1, "conflict": 0, "invalid": 0}
    assert preview.rows[0]["warnings"][0]["code"] == "inactive_variant_remains_inactive"
    result = await service.commit(
        CLIENT_ID, USER_ID, "prompts.csv", _raw(),
        preview.normalized_manifest_sha256, preview.preview_state_sha256,
    )

    assert result["created"] == 0
    assert "reactivated" not in result
    assert conn.existing[0]["is_active"] is False
    assert not any(event.startswith("bulk:") for event in conn.events)


@pytest.mark.anyio
async def test_preview_returns_row_level_invalid_instead_of_rejecting_whole_file() -> None:
    preview = await PromptImportService(Pool(Conn())).preview(CLIENT_ID, _raw(prompt="[REPLACE WITH YOUR PROMPT]"))
    assert preview.input_row_count == 1
    assert preview.action_counts == {"create": 0, "skip": 0, "conflict": 0, "invalid": 1}
    row = preview.rows[0]
    assert row["row_number"] == 2
    assert row["expanded_count"] == 0
    assert row["variants"] == []
    assert row["errors"][0]["code"] == "prompt_placeholder"


@pytest.mark.anyio
async def test_preview_groups_expanded_variants_under_source_order_input_row() -> None:
    raw = _raw_rows([
        ["AnswerX", "Robot Vacuum", "S8", "Best robot vacuum?", "chatgpt", "US", "en-US", "Solution Discovery"],
        ["AnswerX", "Robot Vacuum", "S8", "Another prompt", "chatgpt", "US", "en-US", "Solution Discovery"],
    ])
    preview = await PromptImportService(Pool(Conn())).preview(CLIENT_ID, raw)
    assert [row["row_number"] for row in preview.rows] == [2, 3]
    assert preview.rows[0]["prompt"] == "Best robot vacuum?"
    assert preview.rows[0]["expanded_count"] == 1
    assert len(preview.rows[0]["variants"]) == 1
    assert preview.expanded_variant_count == 2
    assert preview.unique_physical_variant_count == 2


@pytest.mark.anyio
async def test_preview_invalidates_duplicate_declaration_and_reports_declared_vs_unique_counts() -> None:
    raw = _raw_rows([
        ["AnswerX", "Robot Vacuum", "S8", "Best robot vacuum?", "chatgpt", "US", "en-US", "Solution Discovery"],
        ["AnswerX", "Robot Vacuum", "S8", " Best   robot vacuum? ", "ChatGPT", "us", "en-us", "solution discovery"],
    ])
    preview = await PromptImportService(Pool(Conn())).preview(CLIENT_ID, raw)
    assert preview.expanded_variant_count == 2
    assert preview.unique_physical_variant_count == 1
    assert preview.rows[1]["action"] == "invalid"
    assert preview.rows[1]["errors"][0]["code"] == "file_duplicate"
    assert preview.rows[1]["errors"][0]["first_row_number"] == 2
    assert preview.can_commit is False


@pytest.mark.anyio
async def test_preview_invalidates_entire_partially_overlapping_row_without_losing_unique_count() -> None:
    conn = Conn(
        client={
            "id": CLIENT_ID,
            "name": "AnswerX",
            "client_prompt_quota": 20,
            "config_platforms": ["chatgpt", "gemini"],
            "config_countries": ["US"],
            "config_languages": ["en-US"],
        },
        platforms=[
            {"platform_id": "chatgpt", "display_name": "ChatGPT", "supported_countries": ["US"]},
            {"platform_id": "gemini", "display_name": "Gemini", "supported_countries": ["US"]},
        ],
    )
    raw = _raw_rows([
        ["AnswerX", "Robot Vacuum", "S8", "Best robot vacuum?", "chatgpt", "US", "en-US", "Solution Discovery"],
        ["AnswerX", "Robot Vacuum", "S8", "Best robot vacuum?", "chatgpt|gemini", "US", "en-US", "Solution Discovery"],
    ])

    preview = await PromptImportService(Pool(conn)).preview(CLIENT_ID, raw)

    assert preview.expanded_variant_count == 3
    assert preview.unique_physical_variant_count == 2
    assert preview.rows[1]["expanded_count"] == 2
    assert preview.rows[1]["action"] == "invalid"
    assert {variant["action"] for variant in preview.rows[1]["variants"]} == {"invalid"}
    assert preview.rows[1]["errors"][0]["code"] == "file_duplicate"
    assert preview.rows[1]["errors"][0]["first_row_number"] == 2
    assert preview.action_counts == {"create": 1, "skip": 0, "conflict": 0, "invalid": 2}
    assert preview.can_commit is False


@pytest.mark.anyio
async def test_preview_warns_when_normalized_prompt_exists_in_another_topic() -> None:
    existing = [{"id": UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
                 "topic_id": UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
                 "text": "Best robot vacuum?", "product": None, "intent": "Solution Discovery",
                 "platform": "chatgpt", "country": "US", "language": "en-US", "is_active": True}]
    preview = await PromptImportService(Pool(Conn(existing=existing))).preview(CLIENT_ID, _raw())
    assert preview.rows[0]["action"] == "create"
    assert preview.rows[0]["warnings"][0]["code"] == "prompt_exists_in_other_topic"


@pytest.mark.anyio
async def test_preview_blocks_overlapping_file_metadata_declarations_as_duplicate() -> None:
    class TwoIntentConn(Conn):
        async def fetch(self, sql, *args):
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}, {"intent_name": "Specifics Inquiry"}]
            return await super().fetch(sql, *args)

    raw = _raw_rows([
        ["AnswerX", "Robot Vacuum", "S8", "Best robot vacuum?", "chatgpt", "US", "en-US", "Solution Discovery"],
        ["AnswerX", "Robot Vacuum", "S8", "Best robot vacuum?", "chatgpt", "US", "en-US", "Specifics Inquiry"],
    ])
    preview = await PromptImportService(Pool(TwoIntentConn())).preview(CLIENT_ID, raw)
    assert preview.action_counts["create"] == 1
    assert preview.action_counts["invalid"] == 1
    assert preview.can_commit is False
    assert preview.rows[1]["errors"][0]["code"] == "file_duplicate"
    assert preview.rows[1]["errors"][0]["first_row_number"] == 2


@pytest.mark.anyio
async def test_preview_rejects_wrong_topic_product_and_workspace_allowlists() -> None:
    second_topic = "11111111-2222-3333-4444-555555555555"
    conn = Conn(
        topics=[
            {"id": TOPIC_ID, "topic_name": "Robot Vacuum"},
            {"id": second_topic, "topic_name": "Hair Dryer"},
        ],
        products=[{"topic_id": TOPIC_ID, "product_name": "S8"}],
        platforms=[
            {"platform_id": "chatgpt", "display_name": "ChatGPT", "supported_countries": ["US", "DE"]},
            {"platform_id": "gemini", "display_name": "Gemini", "supported_countries": ["US", "DE"]},
        ],
        languages=[
            {"language_code": "en-US", "language": "English"},
            {"language_code": "de-DE", "language": "German"},
        ],
    )
    service = PromptImportService(Pool(conn))

    wrong_product = await service.preview(
        CLIENT_ID,
        _raw_rows([["AnswerX", "Hair Dryer", "S8", "Prompt", "chatgpt", "US", "en-US", "Solution Discovery"]]),
    )
    assert wrong_product.rows[0]["errors"][0]["code"] == "product_not_allowed"

    platform = await service.preview(
        CLIENT_ID,
        _raw_rows([["AnswerX", "Robot Vacuum", "S8", "Prompt", "gemini", "US", "en-US", "Solution Discovery"]]),
    )
    assert platform.rows[0]["errors"][0]["code"] == "ai_platforms_not_allowed"

    conn.client["config_platforms"] = ["chatgpt", "ghost"]
    global_platform = await service.preview(
        CLIENT_ID,
        _raw_rows([["AnswerX", "Robot Vacuum", "S8", "Prompt", "ghost", "US", "en-US", "Solution Discovery"]]),
    )
    assert global_platform.rows[0]["errors"][0]["code"] == "ai_platforms_not_allowed"

    country = await service.preview(
        CLIENT_ID,
        _raw_rows([["AnswerX", "Robot Vacuum", "S8", "Prompt", "chatgpt", "DE", "en-US", "Solution Discovery"]]),
    )
    assert country.rows[0]["errors"][0]["code"] == "countries_not_allowed"

    language = await service.preview(
        CLIENT_ID,
        _raw_rows([["AnswerX", "Robot Vacuum", "S8", "Prompt", "chatgpt", "US", "de-DE", "Solution Discovery"]]),
    )
    assert language.rows[0]["errors"][0]["code"] == "language_not_allowed"


@pytest.mark.anyio
async def test_unsupported_platform_country_invalidates_entire_source_row() -> None:
    client = {
        "id": CLIENT_ID, "name": "AnswerX", "client_prompt_quota": 20,
        "config_platforms": ["chatgpt", "gemini"],
        "config_countries": ["US", "DE"], "config_languages": ["en-US"],
    }
    conn = Conn(
        client=client,
        platforms=[
            {"platform_id": "chatgpt", "display_name": "ChatGPT", "supported_countries": ["US", "DE"]},
            {"platform_id": "gemini", "display_name": "Gemini", "supported_countries": ["US"]},
        ],
    )
    preview = await PromptImportService(Pool(conn)).preview(
        CLIENT_ID,
        _raw_rows([["AnswerX", "Robot Vacuum", "S8", "Prompt", "gemini", "US|DE", "en-US", "Solution Discovery"]]),
    )
    assert preview.rows[0]["action"] == "invalid"
    assert preview.rows[0]["expanded_count"] == 2
    assert {variant["action"] for variant in preview.rows[0]["variants"]} == {"invalid"}
    assert preview.action_counts["invalid"] == 2


@pytest.mark.anyio
async def test_quota_boundary_counts_one_logical_concept_across_physical_variants() -> None:
    client = {
        "id": CLIENT_ID, "name": "AnswerX", "client_prompt_quota": 1,
        "config_platforms": ["chatgpt", "gemini"],
        "config_countries": ["US"], "config_languages": ["en-US"],
    }
    conn = Conn(
        client=client,
        platforms=[
            {"platform_id": "chatgpt", "display_name": "ChatGPT", "supported_countries": ["US"]},
            {"platform_id": "gemini", "display_name": "Gemini", "supported_countries": ["US"]},
        ],
    )
    service = PromptImportService(Pool(conn))
    boundary = await service.preview(
        CLIENT_ID,
        _raw_rows([["AnswerX", "Robot Vacuum", "S8", "Prompt", "chatgpt|gemini", "US", "en-US", "Solution Discovery"]]),
    )
    assert boundary.quota_before == 0
    assert boundary.quota_after == 1
    assert boundary.action_counts["create"] == 2

    conn.client["client_prompt_quota"] = 0
    exceeded = await service.preview(
        CLIENT_ID,
        _raw_rows([["AnswerX", "Robot Vacuum", "S8", "Prompt", "chatgpt|gemini", "US", "en-US", "Solution Discovery"]]),
    )
    assert exceeded.rows[0]["action"] == "invalid"
    assert exceeded.action_counts["invalid"] == 2


@pytest.mark.anyio
async def test_quota_150_logical_concepts_allows_600_physical_variants() -> None:
    client = {
        "id": CLIENT_ID,
        "name": "AnswerX",
        "client_prompt_quota": 150,
        "config_platforms": ["chatgpt", "gemini"],
        "config_countries": ["US", "DE"],
        "config_languages": ["en-US"],
    }
    platforms = [
        {
            "platform_id": "chatgpt",
            "display_name": "ChatGPT",
            "supported_countries": ["US", "DE"],
        },
        {
            "platform_id": "gemini",
            "display_name": "Gemini",
            "supported_countries": ["US", "DE"],
        },
    ]
    raw = _raw_rows([
        [
            "AnswerX",
            "Robot Vacuum",
            "S8",
            f"Prompt concept {number}",
            "chatgpt|gemini",
            "US|DE",
            "en-US",
            "Solution Discovery",
        ]
        for number in range(150)
    ])
    conn = Conn(client=client, platforms=platforms)
    service = PromptImportService(Pool(conn))

    preview = await service.preview(CLIENT_ID, raw)

    assert preview.input_row_count == 150
    assert preview.expanded_variant_count == 600
    assert preview.unique_physical_variant_count == 600
    assert preview.action_counts == {
        "create": 600,
        "skip": 0,
        "conflict": 0,
        "invalid": 0,
    }
    assert preview.quota_before == 0
    assert preview.quota_after == 150
    assert preview.quota_limit == 150
    assert preview.can_commit is True

    result = await service.commit(
        CLIENT_ID,
        USER_ID,
        "prompts.csv",
        raw,
        preview.normalized_manifest_sha256,
        preview.preview_state_sha256,
    )

    assert result["created"] == 600
    assert len(result["ids"]) == 600
    assert conn.events == [
        "tx_enter",
        "lock",
        "lock",
        "bulk:600",
        "audit",
        "tx_commit",
    ]
    assert conn.audit_args[5:11] == (150, 600, 600, 0, 0, 0)
    assert len(conn.audit_args[11]) == 600


@pytest.mark.anyio
async def test_same_file_cross_topic_prompt_gets_warning_on_both_rows() -> None:
    second_topic = "11111111-2222-3333-4444-555555555555"
    conn = Conn(
        topics=[
            {"id": TOPIC_ID, "topic_name": "Robot Vacuum"},
            {"id": second_topic, "topic_name": "Hair Dryer"},
        ],
        products=[
            {"topic_id": TOPIC_ID, "product_name": "S8"},
            {"topic_id": second_topic, "product_name": "S8"},
        ],
    )
    preview = await PromptImportService(Pool(conn)).preview(
        CLIENT_ID,
        _raw_rows([
            ["AnswerX", "Robot Vacuum", "S8", " Shared   Prompt ", "chatgpt", "US", "en-US", "Solution Discovery"],
            ["AnswerX", "Hair Dryer", "S8", "shared prompt", "chatgpt", "US", "en-US", "Solution Discovery"],
        ]),
    )
    assert [row["action"] for row in preview.rows] == ["create", "create"]
    assert all(
        any(warning["code"] == "prompt_exists_in_other_topic" for warning in row["warnings"])
        for row in preview.rows
    )


@pytest.mark.anyio
async def test_template_and_allowed_values_are_workspace_aware() -> None:
    service = PromptImportService(Pool(Conn()))
    template = (await service.template_csv(CLIENT_ID)).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(template)))
    assert tuple(rows[0]) == CSV_HEADERS
    assert len(rows) == 3
    assert rows[1][0] == "AnswerX"
    assert rows[1][3] == "[REPLACE WITH YOUR PROMPT]"

    allowed = await service.allowed_values(CLIENT_ID)
    product = next(row for row in allowed["rows"] if row["type"] == "Product")
    assert product["value"] == "S8"
    assert product["parent_type"] == "Topic"
    assert product["parent_value"] == "Robot Vacuum"


@pytest.mark.anyio
async def test_duplicate_normalized_topic_names_are_ambiguous_and_hide_their_products() -> None:
    duplicate_topic_id = "11111111-2222-3333-4444-555555555555"
    conn = Conn(
        topics=[
            {"id": TOPIC_ID, "topic_name": "Robot Vacuum"},
            {"id": duplicate_topic_id, "topic_name": " robot vacuum "},
        ],
        products=[
            {"topic_id": TOPIC_ID, "product_name": "S8"},
            {"topic_id": duplicate_topic_id, "product_name": "Q Revo"},
        ],
    )
    service = PromptImportService(Pool(conn))

    preview = await service.preview(CLIENT_ID, _raw())
    allowed = await service.allowed_values(CLIENT_ID)

    assert preview.rows[0]["action"] == "invalid"
    assert preview.rows[0]["errors"][0]["code"] == "topic_ambiguous"
    assert not any(row["type"] in {"Topic", "Product"} for row in allowed["rows"])


class _BoundedUpload:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.read_sizes: list[int] = []
        self.filename = "prompts.csv"

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.payload if size < 0 else self.payload[:size]


@pytest.mark.anyio
async def test_upload_reader_uses_max_plus_one_and_rejects_oversize_payload() -> None:
    assert hasattr(prompt_import, "_read_bounded_upload"), "bounded upload helper is required"
    upload = _BoundedUpload(b"x" * 7)
    with pytest.raises(prompt_import.ImportValidationError) as exc:
        await prompt_import._read_bounded_upload(upload, max_bytes=5)

    assert exc.value.code == "file_too_large"
    assert exc.value.actual == 6
    assert exc.value.allowed == 5
    assert upload.read_sizes == [6]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("manifest_hash", "state_hash"),
    [("invalid", "0" * 64), ("0" * 64, "")],
)
async def test_commit_rejects_invalid_hash_before_reading_upload(
    manifest_hash: str, state_hash: str
) -> None:
    upload = _BoundedUpload(_raw())
    with pytest.raises(HTTPException) as exc:
        await prompt_import.commit_import(
            client_id=UUID(CLIENT_ID),
            expected_manifest_sha256=manifest_hash,
            expected_preview_state_sha256=state_hash,
            file=upload,
            user=type("User", (), {"id": USER_ID})(),
            pool=object(),
        )

    assert exc.value.status_code == 422
    assert upload.read_sizes == []


@pytest.mark.anyio
async def test_preview_manifest_is_canonical_even_when_raw_csv_has_utf8_bom() -> None:
    service = PromptImportService(Pool(Conn()))
    plain = await service.preview(CLIENT_ID, _raw())
    bom = await service.preview(CLIENT_ID, b"\xef\xbb\xbf" + _raw())
    assert plain.raw_csv_sha256 != bom.raw_csv_sha256
    assert plain.normalized_manifest_sha256 == bom.normalized_manifest_sha256
    assert plain.preview_state_sha256 == bom.preview_state_sha256


@pytest.mark.anyio
async def test_commit_locks_repreviews_bulk_inserts_and_writes_audit_in_one_transaction() -> None:
    conn = Conn()
    service = PromptImportService(Pool(conn))
    preview = await service.preview(CLIENT_ID, _raw())
    result = await service.commit(
        CLIENT_ID, USER_ID, "prompts.csv", _raw(),
        preview.normalized_manifest_sha256, preview.preview_state_sha256,
    )

    assert result["created"] == 1
    assert conn.events == ["tx_enter", "lock", "lock", "bulk:1", "audit", "tx_commit"]
    assert conn.lock_keys == [
        f"workspace-lifecycle:{CLIENT_ID}",
        f"prompt-write:{CLIENT_ID}",
    ]
    assert conn.audit_args is not None
    assert "Best robot vacuum?" not in {str(value) for value in conn.audit_args}
    assert conn.audit_args[4] == preview.normalized_manifest_sha256
    assert preview.preview_state_sha256 not in {str(value) for value in conn.audit_args}


@pytest.mark.anyio
async def test_commit_audits_pre_dedup_declared_expansion_count() -> None:
    raw = _raw_rows([
        ["AnswerX", "Robot Vacuum", "S8", "First prompt", "chatgpt", "US", "en-US", "Solution Discovery"],
        ["AnswerX", "Robot Vacuum", "S8", "Second prompt", "chatgpt", "US", "en-US", "Solution Discovery"],
    ])
    conn = Conn()
    service = PromptImportService(Pool(conn))
    preview = await service.preview(CLIENT_ID, raw)
    result = await service.commit(
        CLIENT_ID, USER_ID, "prompts.csv", raw,
        preview.normalized_manifest_sha256, preview.preview_state_sha256,
    )
    assert preview.expanded_variant_count == 2
    assert preview.unique_physical_variant_count == 2
    assert result["created"] == 2
    assert conn.audit_args[6] == 2


@pytest.mark.anyio
async def test_commit_rejects_stale_preview_before_insert() -> None:
    conn = Conn()
    service = PromptImportService(Pool(conn))
    with pytest.raises(prompt_import.PreviewStaleError):
        await service.commit(
            CLIENT_ID, USER_ID, "prompts.csv", _raw(),
            "0" * 64, "0" * 64,
        )
    assert not any(event.startswith("bulk") for event in conn.events)
    assert conn.events[-1] == "tx_rollback"


@pytest.mark.anyio
async def test_commit_rejects_entire_file_when_any_source_row_is_invalid() -> None:
    raw = _raw_rows([
        ["AnswerX", "Robot Vacuum", "S8", "Valid prompt", "chatgpt", "US", "en-US", "Solution Discovery"],
        ["AnswerX", "Robot Vacuum", "S8", "[REPLACE WITH YOUR PROMPT]", "chatgpt", "US", "en-US", "Solution Discovery"],
    ])
    conn = Conn()
    service = PromptImportService(Pool(conn))
    preview = await service.preview(CLIENT_ID, raw)

    assert preview.action_counts == {
        "create": 1,
        "skip": 0,
        "conflict": 0,
        "invalid": 1,
    }
    assert preview.can_commit is False

    with pytest.raises(ImportValidationError) as exc:
        await service.commit(
            CLIENT_ID,
            USER_ID,
            "prompts.csv",
            raw,
            preview.normalized_manifest_sha256,
            preview.preview_state_sha256,
        )

    assert exc.value.code == "preview_not_committable"
    assert not any(event.startswith("bulk") for event in conn.events)
    assert "audit" not in conn.events
    assert conn.events[-1] == "tx_rollback"


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", ["config", "quota", "existing"])
async def test_preview_state_detects_config_quota_and_existing_data_staleness(mutation: str) -> None:
    conn = Conn()
    service = PromptImportService(Pool(conn))
    original = await service.preview(CLIENT_ID, _raw())

    if mutation == "config":
        conn.client["config_countries"] = ["US", "DE"]
    elif mutation == "quota":
        conn.client["client_prompt_quota"] = 21
    else:
        conn.existing.append({
            "id": UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
            "topic_id": UUID(TOPIC_ID), "text": "Best robot vacuum?",
            "product": "S8", "intent": "Solution Discovery",
            "platform": "chatgpt", "country": "US", "language": "en-US",
            "is_active": True,
        })

    refreshed = await service.preview(CLIENT_ID, _raw())
    assert refreshed.normalized_manifest_sha256 == original.normalized_manifest_sha256
    assert refreshed.preview_state_sha256 != original.preview_state_sha256
    with pytest.raises(prompt_import.PreviewStaleError):
        await service.commit(
            CLIENT_ID, USER_ID, "prompts.csv", _raw(),
            original.normalized_manifest_sha256, original.preview_state_sha256,
        )
    assert not any(event.startswith("bulk") for event in conn.events)


@pytest.mark.anyio
async def test_commit_rolls_back_when_bulk_insert_count_assertion_fails() -> None:
    class MismatchConn(Conn):
        async def fetch(self, sql, *args):
            if "/* prompt_bulk_insert */" in sql:
                return []
            return await super().fetch(sql, *args)

        async def fetchval(self, sql, *args):
            if "SELECT EXISTS(SELECT 1 FROM geo_clients" in sql:
                return True
            if "pg_try_advisory_xact_lock_shared" in sql:
                self.events.append("lock")
                return True
            if "pg_advisory_xact_lock" in sql:
                self.events.append("lock")
                return None
            if "COUNT(*)" in sql:
                return 0
            return 0

    conn = MismatchConn()
    service = PromptImportService(Pool(conn))
    preview = await service.preview(CLIENT_ID, _raw())
    with pytest.raises(RuntimeError, match="ID mismatch"):
        await service.commit(
            CLIENT_ID, USER_ID, "prompts.csv", _raw(),
            preview.normalized_manifest_sha256, preview.preview_state_sha256,
        )
    assert conn.events[-1] == "tx_rollback"
    assert "audit" not in conn.events


@pytest.mark.anyio
async def test_concurrent_commits_are_serialized_and_second_repreviews_as_stale() -> None:
    state = {"existing": [], "events": [], "lock": asyncio.Lock(), "batch": 0}

    class ConcurrentTx:
        def __init__(self, conn): self.conn = conn
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb):
            state["events"].append("rollback" if exc else "commit")
            if self.conn.lock_held:
                state["lock"].release()
                self.conn.lock_held = False
            return False

    class ConcurrentConn(Conn):
        def __init__(self):
            super().__init__(existing=[{"placeholder": True}])
            self.existing = state["existing"]
            self.lock_held = False

        def transaction(self): return ConcurrentTx(self)

        async def fetchval(self, sql, *args):
            if "SELECT EXISTS(SELECT 1 FROM geo_clients" in sql:
                return True
            if "pg_try_advisory_xact_lock_shared" in sql:
                state["events"].append("lock")
                return True
            if "pg_advisory_xact_lock" in sql:
                if str(args[0]).startswith("prompt-write:"):
                    await state["lock"].acquire()
                    self.lock_held = True
                state["events"].append("lock")
                return None
            if "COUNT(*)" in sql:
                return len(args[1])
            return 0

        async def fetch(self, sql, *args):
            if "prompt_bulk_insert" not in sql:
                return await super().fetch(sql, *args)
            state["events"].append("bulk")
            inserted = []
            for index, prompt_id in enumerate(args[1]):
                state["existing"].append({
                    "id": prompt_id, "topic_id": args[2][index], "text": args[3][index],
                    "intent": args[4][index], "product": args[5][index],
                    "platform": args[6][index], "country": args[7][index],
                    "language": args[8][index], "is_active": args[9][index],
                })
                inserted.append({"id": prompt_id})
            return inserted

        async def fetchrow(self, sql, *args):
            if "INSERT INTO geo_prompt_import_batches" in sql:
                state["batch"] += 1
                return {"id": f"dddddddd-dddd-dddd-dddd-{state['batch']:012d}"}
            return await super().fetchrow(sql, *args)

    class ConcurrentAcquire:
        async def __aenter__(self): return ConcurrentConn()
        async def __aexit__(self, *args): return False

    class ConcurrentPool:
        def acquire(self): return ConcurrentAcquire()

    service = PromptImportService(ConcurrentPool())
    preview = await service.preview(CLIENT_ID, _raw())
    results = await asyncio.gather(
        service.commit(
            CLIENT_ID, USER_ID, "first.csv", _raw(),
            preview.normalized_manifest_sha256, preview.preview_state_sha256,
        ),
        service.commit(
            CLIENT_ID, USER_ID, "second.csv", _raw(),
            preview.normalized_manifest_sha256, preview.preview_state_sha256,
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, prompt_import.PreviewStaleError) for result in results) == 1
    assert state["events"] == [
        "lock", "lock", "bulk", "commit",
        "lock", "lock", "rollback",
    ]
    assert len(state["existing"]) == 1


@pytest.mark.anyio
async def test_undo_is_tenant_scoped_and_idempotent(monkeypatch) -> None:
    batch = {"id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "client_id": CLIENT_ID,
             "created_prompt_ids": [], "status": "REVERTED"}
    service = PromptImportService(Pool(Conn(batch=batch)))
    result = await service.undo(CLIENT_ID, USER_ID, batch["id"], confirmation=True)
    assert result["status"] == "REVERTED"
    assert result["already_reverted"] is True


@pytest.mark.anyio
async def test_undo_successfully_uses_cascade_service_for_exact_batch_ids() -> None:
    prompt_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    batch = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "client_id": CLIENT_ID,
        "created_prompt_ids": [prompt_id], "status": "COMMITTED",
    }
    existing = [{
        "id": prompt_id, "topic_id": UUID(TOPIC_ID), "text": "Prompt",
        "product": "S8", "intent": "Solution Discovery", "platform": "chatgpt",
        "country": "US", "language": "en-US", "is_active": True,
    }]
    class CaptureConn(Conn):
        def __init__(self):
            super().__init__(batch=batch, existing=existing)
            self.prompt_lookup_args = None

        async def fetch(self, sql, *args):
            if "FROM geo_client_prompts" in sql:
                self.prompt_lookup_args = args
            return await super().fetch(sql, *args)

    conn = CaptureConn()
    result = await PromptImportService(Pool(conn)).undo(
        CLIENT_ID, USER_ID, str(batch["id"]), confirmation=True,
    )
    assert result["status"] == "REVERTED"
    assert result["deleted"] == 1
    assert result["cascade"]["deleted_citations"] == 1
    assert conn.prompt_lookup_args == (CLIENT_ID, [str(prompt_id)])


@pytest.mark.anyio
async def test_undo_restores_pre_import_state_for_600_created_variants() -> None:
    prompt_ids = [UUID(int=value) for value in range(1, 601)]
    batch = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "client_id": CLIENT_ID,
        "created_prompt_ids": prompt_ids,
        "status": "COMMITTED",
    }

    class StatefulUndoConn(Conn):
        def __init__(self):
            super().__init__(
                batch=batch,
                existing=[{"id": prompt_id} for prompt_id in prompt_ids],
            )
            self.prompt_lookup_args = None

        async def fetch(self, sql, *args):
            if "FROM geo_client_prompts" in sql:
                self.prompt_lookup_args = args
            return await super().fetch(sql, *args)

        async def fetchval(self, sql, *args):
            if "prompt_undo_footprint" in sql:
                return len(self.existing)
            return await super().fetchval(sql, *args)

        async def execute(self, sql, *args):
            if "SET status = 'REVERTING'" in sql:
                self.batch["status"] = "REVERTING"
                return "UPDATE 1"
            if "SET status = 'REVERTED'" in sql:
                self.batch["status"] = "REVERTED"
                return "UPDATE 1"
            if sql.startswith("DELETE FROM geo_client_prompts"):
                deleted = len(self.existing)
                self.existing = []
                return f"DELETE {deleted}"
            if sql.startswith("DELETE"):
                return "DELETE 0"
            return await super().execute(sql, *args)

    conn = StatefulUndoConn()
    result = await PromptImportService(Pool(conn)).undo(
        CLIENT_ID,
        USER_ID,
        str(batch["id"]),
        confirmation=True,
    )

    assert result["status"] == "REVERTED"
    assert result["deleted"] == 600
    assert result["cascade"]["requested_prompts"] == 600
    assert result["cascade"]["matched_prompts"] == 600
    assert result["footprint"] == 600
    assert conn.batch["status"] == "REVERTED"
    assert conn.existing == []
    assert conn.prompt_lookup_args == (
        CLIENT_ID,
        [str(prompt_id) for prompt_id in prompt_ids],
    )


@pytest.mark.anyio
async def test_failed_undo_rolls_back_to_committed_and_is_retryable() -> None:
    prompt_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    batch = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "client_id": CLIENT_ID,
        "created_prompt_ids": [prompt_id], "status": "COMMITTED",
    }

    class UndoTx:
        def __init__(self, conn): self.conn = conn; self.before = None
        async def __aenter__(self):
            self.before = self.conn.batch["status"]
            return self
        async def __aexit__(self, exc_type, exc, tb):
            if exc:
                self.conn.batch["status"] = self.before
            return False

    class RetryUndoConn(Conn):
        def __init__(self):
            super().__init__(batch=batch, existing=[{"id": prompt_id}])
            self.fail_once = True

        def transaction(self): return UndoTx(self)

        async def execute(self, sql, *args):
            if "SET status = 'REVERTING'" in sql:
                self.batch["status"] = "REVERTING"
                return "UPDATE 1"
            if "SET status = 'REVERTED'" in sql:
                self.batch["status"] = "REVERTED"
                return "UPDATE 1"
            if "DELETE FROM geo_citations" in sql and self.fail_once:
                self.fail_once = False
                raise RuntimeError("simulated cascade failure")
            return "DELETE 1"

    conn = RetryUndoConn()
    service = PromptImportService(Pool(conn))
    with pytest.raises(RuntimeError, match="cascade failure"):
        await service.undo(CLIENT_ID, USER_ID, str(batch["id"]), confirmation=True)
    assert conn.batch["status"] == "COMMITTED"

    retried = await service.undo(
        CLIENT_ID, USER_ID, str(batch["id"]), confirmation=True,
    )
    assert retried["status"] == "REVERTED"
    assert conn.batch["status"] == "REVERTED"


@pytest.mark.anyio
async def test_undo_applies_transaction_local_timeouts_before_footprint_and_delete() -> None:
    prompt_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    batch = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "client_id": CLIENT_ID,
        "created_prompt_ids": [prompt_id],
        "status": "COMMITTED",
    }

    class TimeoutCaptureConn(Conn):
        async def execute(self, sql, *args):
            if "SET LOCAL" in sql:
                self.events.append(sql.strip())
            return await super().execute(sql, *args)

        async def fetchval(self, sql, *args):
            if "prompt_undo_footprint" in sql:
                self.events.append("footprint")
                assert args == (CLIENT_ID, [str(prompt_id)])
                return 1
            return await super().fetchval(sql, *args)

    conn = TimeoutCaptureConn(batch=batch, existing=[{"id": prompt_id}])
    await PromptImportService(Pool(conn)).undo(
        CLIENT_ID, USER_ID, str(batch["id"]), confirmation=True,
    )

    lock_index = next(index for index, event in enumerate(conn.events) if "lock_timeout" in event)
    statement_index = next(index for index, event in enumerate(conn.events) if "statement_timeout" in event)
    first_advisory_lock_index = conn.events.index("lock")
    footprint_index = conn.events.index("footprint")
    assert lock_index < first_advisory_lock_index < footprint_index
    assert statement_index < first_advisory_lock_index < footprint_index


@pytest.mark.anyio
async def test_undo_large_tenant_scoped_footprint_warns_but_remains_revertible() -> None:
    prompt_ids = [
        UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee1"),
        UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee2"),
    ]
    batch = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "client_id": CLIENT_ID,
        "created_prompt_ids": prompt_ids,
        "status": "COMMITTED",
    }

    class LargeFootprintConn(Conn):
        async def fetchval(self, sql, *args):
            if "prompt_undo_footprint" in sql:
                self.events.append("footprint")
                assert "client_id = $1::uuid" in sql
                assert "client_prompt_id = ANY($2::uuid[])" in sql
                assert "id = ANY($2::uuid[])" in sql
                assert args == (CLIENT_ID, [str(value) for value in prompt_ids])
                return 6
            return await super().fetchval(sql, *args)

        async def execute(self, sql, *args):
            if sql.lstrip().startswith("DELETE") or "SET status" in sql:
                self.events.append("undo_mutation")
            return await super().execute(sql, *args)

    conn = LargeFootprintConn(
        batch=batch,
        existing=[{"id": value} for value in prompt_ids],
    )
    service = PromptImportService(Pool(conn), undo_max_footprint=5)
    result = await service.undo(
        CLIENT_ID,
        USER_ID,
        str(batch["id"]),
        confirmation=True,
    )

    assert result["status"] == "REVERTED"
    assert result["already_reverted"] is False
    assert result["footprint"] == 6
    assert result["large_footprint_warning"] is True
    assert "footprint" in conn.events
    assert "undo_mutation" in conn.events


@pytest.mark.anyio
async def test_undo_limiter_bounds_pool_acquisition_before_connection_checkout() -> None:
    state = {"active": 0, "max_active": 0, "acquires": 0}
    release_first = asyncio.Event()
    first_entered = asyncio.Event()
    batch = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "client_id": CLIENT_ID,
        "created_prompt_ids": [],
        "status": "REVERTED",
    }

    class SlowRevertedConn(Conn):
        async def fetchrow(self, sql, *args):
            if "FROM geo_prompt_import_batches" in sql and not first_entered.is_set():
                first_entered.set()
                await release_first.wait()
            return await super().fetchrow(sql, *args)

    class LimitedAcquire:
        async def __aenter__(self):
            state["acquires"] += 1
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            return SlowRevertedConn(batch=batch)

        async def __aexit__(self, *args):
            state["active"] -= 1
            return False

    class ConstrainedPool:
        def acquire(self):
            return LimitedAcquire()

    service = PromptImportService(
        ConstrainedPool(),
        undo_limiter=PromptImportUndoLimiter(limit=1),
    )
    first = asyncio.create_task(service.undo(CLIENT_ID, USER_ID, batch["id"], confirmation=True))
    await first_entered.wait()
    second = asyncio.create_task(service.undo(CLIENT_ID, USER_ID, batch["id"], confirmation=True))
    await asyncio.sleep(0)
    assert state["acquires"] == 1
    release_first.set()
    results = await asyncio.gather(first, second)

    assert [result["already_reverted"] for result in results] == [True, True]
    assert state["acquires"] == 2
    assert state["max_active"] == 1


@pytest.mark.anyio
async def test_undo_timeout_failure_rolls_back_without_status_or_delete() -> None:
    batch = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "client_id": CLIENT_ID,
        "created_prompt_ids": [],
        "status": "COMMITTED",
    }

    class TimeoutConn(Conn):
        async def execute(self, sql, *args):
            if "statement_timeout" in sql:
                raise TimeoutError("statement timeout setup failed")
            if sql.lstrip().startswith("DELETE") or "SET status" in sql:
                self.events.append("forbidden_mutation")
            return await super().execute(sql, *args)

    conn = TimeoutConn(batch=batch)
    with pytest.raises(TimeoutError, match="statement timeout"):
        await PromptImportService(Pool(conn)).undo(
            CLIENT_ID, USER_ID, str(batch["id"]), confirmation=True,
        )
    assert conn.events[-1] == "tx_rollback"
    assert "forbidden_mutation" not in conn.events


def test_router_exposes_every_import_endpoint() -> None:
    paths = {(route.path, next(iter(route.methods))) for route in prompt_import.router.routes}
    assert ("/import/template.csv", "GET") in paths
    assert ("/import/allowed-values", "GET") in paths
    assert ("/import/allowed-values.csv", "GET") in paths
    assert ("/import/preview", "POST") in paths
    assert ("/import/commit", "POST") in paths
    assert ("/import/{batch_id}/undo", "POST") in paths


def test_preview_and_commit_publish_multipart_openapi_contract() -> None:
    app = FastAPI()
    app.include_router(prompt_import.router)
    schema = app.openapi()
    paths = schema["paths"]
    assert "multipart/form-data" in paths["/import/preview"]["post"]["requestBody"]["content"]
    assert "multipart/form-data" in paths["/import/commit"]["post"]["requestBody"]["content"]
    commit_schema = paths["/import/commit"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    component_name = commit_schema["$ref"].rsplit("/", 1)[-1]
    required = set(schema["components"]["schemas"][component_name]["required"])
    assert {"file", "expected_manifest_sha256", "expected_preview_state_sha256"} <= required

    for path in ("/import/allowed-values", "/import/allowed-values.csv"):
        locale_parameter = next(
            parameter for parameter in paths[path]["get"]["parameters"]
            if parameter["name"] == "locale"
        )
        assert locale_parameter["in"] == "query"
        assert locale_parameter["schema"]["enum"] == ["zh-CN", "en-US"]


@pytest.mark.anyio
async def test_import_service_refuses_missing_tenant_id_before_database_access() -> None:
    with pytest.raises(TenantIsolationError):
        await PromptImportService(Pool(Conn())).preview("", _raw())
