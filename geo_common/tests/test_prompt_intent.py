"""Database-backed Prompt Intent facets and write validation."""

from __future__ import annotations

from typing import Any

import pytest

from geo_common.services.prompt_intent import (
    PromptIntentService,
    PromptIntentValidationError,
    canonicalize_configured_values,
    normalize_case_insensitive,
)

CLIENT_A = "11111111-1111-1111-1111-111111111111"
CLIENT_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class IntentConn:
    def __init__(
        self,
        *,
        active: list[str],
        history_by_client: dict[str, list[str | None]],
        fail_active: bool = False,
    ) -> None:
        self.active = active
        self.history_by_client = history_by_client
        self.fail_active = fail_active
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append((sql, args))
        if "geo_global_intents" in sql:
            if self.fail_active:
                raise RuntimeError("global config unavailable")
            return [{"intent_name": value} for value in self.active]
        if "geo_client_prompts" in sql:
            assert args, "tenant history query must bind client_id"
            return [
                {"intent": value}
                for value in self.history_by_client.get(str(args[0]), [])
            ]
        raise AssertionError(f"Unexpected SQL: {sql}")


class Pool:
    def __init__(self, conn: IntentConn) -> None:
        self.conn = conn

    def acquire(self):
        return Acquire(self.conn)


class Acquire:
    def __init__(self, conn: IntentConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> IntentConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def make_service(
    *,
    active: list[str] | None = None,
    history_by_client: dict[str, list[str | None]] | None = None,
    fail_active: bool = False,
) -> tuple[PromptIntentService, IntentConn]:
    conn = IntentConn(
        active=(
            active
            if active is not None
            else [
                "Specifics Inquiry",
                "Solution Discovery",
                "Competitive Evaluation",
            ]
        ),
        history_by_client=history_by_client or {},
        fail_active=fail_active,
    )
    return PromptIntentService(Pool(conn)), conn


@pytest.mark.anyio
async def test_facets_separate_active_and_tenant_history() -> None:
    service, conn = make_service(
        history_by_client={CLIENT_A: ["general", "Solution Discovery"]}
    )

    facets = await service.facets(CLIENT_A)

    assert facets.active == [
        "Competitive Evaluation",
        "Solution Discovery",
        "Specifics Inquiry",
    ]
    assert facets.unconfigured == ["general"]
    assert facets.has_unconfigured_blank is False
    history_sql, history_args = next(
        call for call in conn.calls if "geo_client_prompts" in call[0]
    )
    assert "client_id = $1" in history_sql
    assert history_args == (CLIENT_A,)


@pytest.mark.anyio
async def test_facets_normalize_null_blank_and_case_insensitive_history() -> None:
    service, _ = make_service(
        history_by_client={
            CLIENT_A: [
                None,
                "",
                "   ",
                " GENERAL ",
                "general",
                " solution discovery ",
            ]
        }
    )

    facets = await service.facets(CLIENT_A)

    assert facets.unconfigured == ["GENERAL"]
    assert facets.has_unconfigured_blank is True


@pytest.mark.anyio
async def test_facets_do_not_leak_other_tenant_history() -> None:
    service, conn = make_service(
        history_by_client={CLIENT_A: ["legacy-a"], CLIENT_B: ["legacy-b"]}
    )

    facets_a = await service.facets(CLIENT_A)
    facets_b = await service.facets(CLIENT_B)

    assert facets_a.unconfigured == ["legacy-a"]
    assert facets_b.unconfigured == ["legacy-b"]
    assert facets_a.has_unconfigured_blank is False
    assert facets_b.has_unconfigured_blank is False
    history_calls = [call for call in conn.calls if "geo_client_prompts" in call[0]]
    assert [call[1] for call in history_calls] == [(CLIENT_A,), (CLIENT_B,)]


@pytest.mark.anyio
async def test_require_active_returns_database_canonical_name_case_insensitively() -> None:
    service, _ = make_service()

    assert await service.require_active("  solution DISCOVERY ") == "Solution Discovery"


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, "", "   "])
async def test_require_active_rejects_empty_values(value: str | None) -> None:
    service, _ = make_service()

    with pytest.raises(PromptIntentValidationError) as exc:
        await service.require_active(value)

    assert exc.value.code == "intent_required"


@pytest.mark.anyio
async def test_require_active_rejects_disabled_or_historical_value() -> None:
    service, _ = make_service(history_by_client={CLIENT_A: ["general"]})

    with pytest.raises(PromptIntentValidationError) as exc:
        await service.require_active("general")

    assert exc.value.code == "intent_not_active"


@pytest.mark.anyio
async def test_global_config_error_does_not_use_hardcoded_fallback() -> None:
    service, _ = make_service(fail_active=True)

    with pytest.raises(RuntimeError, match="global config unavailable"):
        await service.require_active("Solution Discovery")


@pytest.mark.anyio
async def test_empty_active_config_stays_empty_and_rejects_every_write() -> None:
    service, _ = make_service(
        active=[],
        history_by_client={CLIENT_A: ["Solution Discovery"]},
    )

    facets = await service.facets(CLIENT_A)

    assert facets.active == []
    assert facets.unconfigured == ["Solution Discovery"]
    assert facets.has_unconfigured_blank is False
    with pytest.raises(PromptIntentValidationError) as exc:
        await service.require_active("Solution Discovery")
    assert exc.value.code == "intent_not_active"


def test_normalization_matches_postgresql_lower_instead_of_casefold() -> None:
    assert normalize_case_insensitive(" Straße ") == "straße"
    assert normalize_case_insensitive("STRASSE") == "strasse"
    assert normalize_case_insensitive("Straße") != normalize_case_insensitive("STRASSE")


def test_configured_value_dedupe_is_deterministic_for_case_duplicates() -> None:
    values = ["solution discovery", "Solution Discovery", "SOLUTION DISCOVERY"]
    expected = ["SOLUTION DISCOVERY"]
    assert canonicalize_configured_values(values) == expected
    assert canonicalize_configured_values(reversed(values)) == expected


@pytest.mark.anyio
async def test_service_uses_same_deterministic_canonical_for_case_duplicates() -> None:
    service, _ = make_service(
        active=["solution discovery", "Solution Discovery", "SOLUTION DISCOVERY"]
    )
    assert await service.require_active("solution discovery") == "SOLUTION DISCOVERY"
