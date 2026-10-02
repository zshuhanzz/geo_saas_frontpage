import asyncio
from uuid import UUID

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from geo_common.auth import AuthenticatedUser

from dependencies import auth as auth_dependencies
from routers import prompts, sentiment
from routers.insights import citations, cited_domains, cited_pages
from routers.insights.target_filters import build_target_filter


CLIENT_ID = UUID("b0e10518-5f70-426f-b09e-dbe025984ba1")
PROMPT_A = "11111111-1111-1111-1111-111111111111"
PROMPT_B = "22222222-2222-2222-2222-222222222222"
USER_ID = "99999999-9999-9999-9999-999999999999"


class RecordingDatabase:
    def __init__(self):
        self.calls = []

    async def fetch_all(self, sql, params=None):
        self.calls.append(("fetch_all", sql, params or {}))
        if "geo_global_intents" in sql:
            return [{"intent_name": "Solution Discovery"}]
        if "geo_client_domains" in sql:
            return []
        return []

    async def fetch_one(self, sql, params=None):
        self.calls.append(("fetch_one", sql, params or {}))
        if "positive" in sql:
            return {
                "total": 0,
                "rated": 0,
                "positive": 0,
                "mixed_neutral": 0,
                "negative": 0,
                "insufficient_evidence": 0,
            }
        return {"total_citations": 0, "own_citation_count": 0, "own_rank": None, "total": 0}

    async def fetch_val(self, sql, params=None):
        self.calls.append(("fetch_val", sql, params or {}))
        return 0


def _assert_target_applied_to_metric_queries(db, prompt_param_prefix="target_prompt"):
    metric_calls = [
        call for call in db.calls
        if "geo_citations" in call[1] or "geo_sentiment_" in call[1]
    ]
    assert metric_calls
    for _method, sql, params in metric_calls:
        assert "cp.client_id" in sql or "client_id = :client_id" in sql
        if "geo_citations" in sql or "geo_sentiment_" in sql:
            assert "LOWER(TRIM(COALESCE(cp.product, ''))) IN" in sql
            assert "client_prompt_id IN" in sql
            assert any(key.startswith(prompt_param_prefix) for key in params)
            assert any(key.startswith("target_product") for key in params)


def test_target_filter_unions_prompt_inputs_and_normalizes_products():
    target = build_target_filter(
        products=" S8 MaxV ,s8 maxv, Q Revo ",
        prompt_id=PROMPT_A,
        prompt_ids=f"{PROMPT_B},{PROMPT_A}",
    )
    assert "LOWER(TRIM(COALESCE(cp.product, ''))) IN" in target.clause
    assert "c.client_prompt_id IN" in target.clause
    assert list(target.params.values()).count(PROMPT_A) == 1
    assert list(target.params.values()).count(PROMPT_B) == 1
    assert "s8 maxv" in target.params.values()
    assert "q revo" in target.params.values()


def test_target_filter_rejects_invalid_or_excess_prompt_ids():
    with pytest.raises(HTTPException) as invalid:
        build_target_filter(prompt_id="not-a-uuid")
    assert invalid.value.status_code == 422
    with pytest.raises(HTTPException) as excessive:
        build_target_filter(prompt_ids=",".join(str(UUID(int=i + 1)) for i in range(101)))
    assert excessive.value.status_code == 422
    with pytest.raises(HTTPException) as empty_products:
        build_target_filter(products=" , , ")
    assert empty_products.value.status_code == 422


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prompt_ids": "x" * 4097},
        {"prompt_ids": ",".join([PROMPT_A] * 101)},
        {"products": ",".join(f"product-{index}" for index in range(51))},
        {"products": "x" * 257},
        {"products": "x" * 8193},
    ],
)
def test_target_filter_rejects_raw_size_token_and_product_limits(kwargs):
    with pytest.raises(HTTPException) as exc_info:
        build_target_filter(**kwargs)
    assert exc_info.value.status_code == 422


def test_invalid_prompt_uuid_error_does_not_echo_raw_input():
    raw = "secret-invalid-value"
    with pytest.raises(HTTPException) as exc_info:
        build_target_filter(prompt_id=raw)
    assert raw not in str(exc_info.value.detail)


def test_product_normalization_uses_lower_not_unicode_casefold():
    target = build_target_filter(products="Straße,STRASSE")
    assert target.params["target_product_0"] == "straße"
    assert target.params["target_product_1"] == "strasse"


@pytest.mark.parametrize("endpoint", [
    citations.get_citations,
    citations.get_citation_share_chart,
    citations.get_citation_ranking_chart,
    citations.get_citation_categories_chart,
])
def test_all_citation_dashboard_branches_apply_product_and_prompt_filters(monkeypatch, endpoint):
    db = RecordingDatabase()
    monkeypatch.setattr(citations, "database", db)
    result = asyncio.run(endpoint(
        client_id=CLIENT_ID,
        date_from="2026-05-01",
        date_to="2026-05-02",
        products="S8 MaxV,Q Revo",
        prompt_id=PROMPT_A,
        prompt_ids=PROMPT_B,
        interval="daily",
    ))
    assert result is not None
    _assert_target_applied_to_metric_queries(db)


def test_citation_target_filters_compose_with_existing_dimensions_using_and(monkeypatch):
    db = RecordingDatabase()
    monkeypatch.setattr(citations, "database", db)
    asyncio.run(citations.get_citations(
        client_id=CLIENT_ID,
        topic_id=PROMPT_B,
        platform="chatgpt",
        country="US",
        products="S8 MaxV",
        prompt_ids=PROMPT_A,
        date_from="2026-05-01",
        date_to="2026-05-02",
        interval="daily",
    ))
    metric_calls = [call for call in db.calls if "geo_citations" in call[1]]
    assert metric_calls
    for _method, sql, params in metric_calls:
        assert "cp.topic_id = :topic_id" in sql
        assert "cp.platform = :platform" in sql
        assert "cp.country IN (:country_0)" in sql
        assert "LOWER(TRIM(COALESCE(cp.product, ''))) IN" in sql
        assert "c.client_prompt_id IN" in sql
        assert params["topic_id"] == PROMPT_B
        assert params["platform"] == "chatgpt"
        assert params["country_0"] == "US"
        assert params["target_product_0"] == "s8 maxv"
        assert params["target_prompt_0"] == PROMPT_A


def test_citation_without_target_keeps_backward_compatible_unfiltered_queries(monkeypatch):
    db = RecordingDatabase()
    monkeypatch.setattr(citations, "database", db)
    asyncio.run(citations.get_citation_categories_chart(
        client_id=CLIENT_ID,
        date_from="2026-05-01",
        date_to="2026-05-02",
        interval="daily",
    ))
    metric_calls = [call for call in db.calls if "geo_citations" in call[1]]
    assert metric_calls
    for _method, sql, params in metric_calls:
        assert "target_product" not in sql
        assert "target_prompt" not in sql
        assert not any(key.startswith("target_") for key in params)


@pytest.mark.parametrize("module,endpoint", [
    (cited_domains, cited_domains.get_cited_domains),
    (cited_domains, cited_domains.get_cited_domains_count),
    (cited_pages, cited_pages.get_cited_pages),
    (cited_pages, cited_pages.get_cited_pages_count),
])
def test_cited_list_and_count_branches_apply_target_filters(monkeypatch, module, endpoint):
    db = RecordingDatabase()
    monkeypatch.setattr(module, "database", db)
    kwargs = dict(
        client_id=CLIENT_ID,
        date_from="2026-05-01",
        date_to="2026-05-02",
        products="S8 MaxV",
        prompt_ids=f"{PROMPT_A},{PROMPT_B}",
    )
    if endpoint in (cited_domains.get_cited_domains, cited_pages.get_cited_pages):
        kwargs.update(limit=20, offset=0)
    result = asyncio.run(endpoint(**kwargs))
    assert result is not None
    _assert_target_applied_to_metric_queries(db)


@pytest.mark.parametrize("module,endpoint,kind", [
    (cited_domains, cited_domains.get_cited_domains, "domain"),
    (cited_pages, cited_pages.get_cited_pages, "page"),
])
@pytest.mark.parametrize("returned_count,expected_has_more", [(8, True), (7, False)])
def test_cited_pagination_sorts_in_sql_before_slicing_and_keeps_global_rank(
    monkeypatch, module, endpoint, kind, returned_count, expected_has_more
):
    class PaginationDatabase(RecordingDatabase):
        async def fetch_all(self, sql, params=None):
            self.calls.append(("fetch_all", sql, params or {}))
            if "geo_global_intents" in sql:
                return [{"intent_name": "Solution Discovery"}]
            if "FROM metrics" in sql and kind == "domain":
                return [
                    {
                        "rank": index,
                        "domain": f"domain-{index}.example",
                        "citation_count": 10 - index,
                        "share_pct": 10 - index,
                        "change_pct": None,
                        "domain_category": "Other",
                        "is_own": False,
                        "total_unique": returned_count,
                        "total_citations": 30,
                    }
                    for index in (6, 7)
                ]
            if "FROM metrics" in sql and kind == "page":
                return [
                    {
                        "rank": index,
                        "url": f"https://example.com/{index}",
                        "domain": "example.com",
                        "citation_count": 10 - index,
                        "share_pct": 10 - index,
                        "change_pct": None,
                        "domain_category": "Other",
                        "is_own": False,
                        "total_unique": returned_count,
                        "total_citations": 30,
                    }
                    for index in (6, 7)
                ]
            return []

        async def fetch_one(self, sql, params=None):
            self.calls.append(("fetch_one", sql, params or {}))
            return {
                "total_unique": returned_count,
                "total_citations": 30,
                "previous_total_citations": 20,
            }

    db = PaginationDatabase()
    monkeypatch.setattr(module, "database", db)
    result = asyncio.run(endpoint(
        client_id=CLIENT_ID,
        date_from="2026-05-01",
        date_to="2026-05-02",
        limit=2,
        offset=5,
    ))
    rows = result.domains if kind == "domain" else result.pages
    assert len(rows) == 2
    assert [row.rank for row in rows] == [6, 7]
    assert result.has_more is expected_has_more
    rank_call = next(
        call for call in db.calls
        if call[0] == "fetch_all"
        and (
            "FROM metrics" in call[1]
        )
    )
    assert "LIMIT :limit OFFSET :offset" in rank_call[1]
    assert rank_call[2]["limit"] == 2
    assert rank_call[2]["offset"] == 5
    assert "ORDER BY citation_count DESC NULLS LAST" in rank_call[1]


def test_sentiment_summary_series_themes_and_theme_results_share_target_filters(monkeypatch):
    db = RecordingDatabase()
    monkeypatch.setattr(sentiment, "database", db)
    asyncio.run(sentiment.get_sentiment(
        client_id=str(CLIENT_ID),
        date_from="2026-05-01",
        date_to="2026-05-02",
        products="S8 MaxV",
        prompt_id=PROMPT_A,
        prompt_ids=PROMPT_B,
        interval="daily",
    ))
    metric_calls = [call for call in db.calls if "geo_sentiment_" in call[1]]
    assert len(metric_calls) == 6
    for _method, sql, params in metric_calls:
        assert "cp.client_prompt_id" not in sql
        assert "client_prompt_id IN" in sql
        assert "LOWER(TRIM(COALESCE(cp.product, ''))) IN" in sql
        assert PROMPT_A in params.values() and PROMPT_B in params.values()

    db.calls.clear()
    asyncio.run(sentiment.get_theme_results(
        client_id=str(CLIENT_ID),
        theme_name="Easy To Use",
        date_from="2026-05-01",
        date_to="2026-05-02",
        products="S8 MaxV",
        prompt_ids=PROMPT_A,
    ))
    theme_calls = [call for call in db.calls if "geo_sentiment_themes" in call[1]]
    assert len(theme_calls) == 2
    for _method, sql, params in theme_calls:
        assert "st.client_prompt_id IN" in sql
        assert "LOWER(TRIM(COALESCE(cp.product, ''))) IN" in sql
        assert PROMPT_A in params.values()


def test_sentiment_result_detail_enforces_product_and_prompt_context(monkeypatch):
    class DetailDatabase(RecordingDatabase):
        async def fetch_one(self, sql, params=None):
            self.calls.append(("fetch_one", sql, params or {}))
            return {
                "result_id": 42,
                "client_prompt": "Prompt",
                "final_prompt": "Final",
                "platform": "chatgpt",
                "country": "US",
                "language": "en-US",
                "executed_at": None,
                "response_text": "Response",
                "search_queries": None,
                "search_queries_requested": True,
                "topic_name": "Robot Vacuums",
                "product": "S8 MaxV",
                "intent": "Solution Discovery",
            }

    db = DetailDatabase()
    monkeypatch.setattr(sentiment, "database", db)
    result = asyncio.run(sentiment.get_result_detail(
        client_id=str(CLIENT_ID),
        result_id=42,
        products="S8 MaxV",
        prompt_ids=PROMPT_A,
    ))
    assert result.result_id == 42
    assert result.search_queries == []
    assert result.search_queries_status == "upstream_not_provided"
    result_sql, params = db.calls[0][1], db.calls[0][2]
    assert "JOIN geo_client_prompts cp" in result_sql
    assert "AS search_queries_requested" in result_sql
    assert "gr.cloro_response," not in result_sql
    citations_sql = db.calls[1][1]
    assert "ORDER BY source_position NULLS LAST" in citations_sql
    assert "LIMIT 100" in citations_sql
    assert "LOWER(TRIM(COALESCE(cp.product, ''))) IN" in result_sql
    assert "gr.client_prompt_id IN" in result_sql
    assert PROMPT_A in params.values()


@pytest.mark.parametrize(
    "platform,queries,cloro_response,expected_queries,expected_status",
    [
        (
            "chatgpt",
            ["best backup", {"query": "backup comparison"}, None, 42],
            None,
            ["best backup", {"query": "backup comparison"}],
            "available",
        ),
        (
            "chatgpt",
            '["best backup", {"query": "backup comparison"}, null, 42]',
            None,
            ["best backup", {"query": "backup comparison"}],
            "available",
        ),
        ("chatgpt", "not-json", None, [], "upstream_not_provided"),
        ("chatgpt", '{"query": "wrong container"}', None, [], "upstream_not_provided"),
        ("ChatGPT", None, None, [], "upstream_not_provided"),
        (
            "chatgpt",
            [],
            {"request": {"include": {"searchQueries": False}}},
            [],
            "not_requested",
        ),
        ("gemini", ["ignored"], None, [], "not_applicable"),
    ],
)
def test_result_detail_search_query_availability_states(
    platform,
    queries,
    cloro_response,
    expected_queries,
    expected_status,
):
    normalized, status = sentiment._resolve_search_queries_state(
        platform=platform,
        search_queries=queries,
        cloro_response=cloro_response,
    )
    assert normalized == expected_queries
    assert status == expected_status


@pytest.mark.anyio
async def test_theme_results_pagination_query_validation_and_defaults(monkeypatch):
    db = RecordingDatabase()
    monkeypatch.setattr(sentiment, "database", db)
    app = FastAPI()
    app.include_router(sentiment.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        invalid_page = await client.get(
            "/api/sentiment/theme-results",
            params={"client_id": str(CLIENT_ID), "theme_name": "Easy", "page": 0},
        )
        assert db.calls == []
        oversized = await client.get(
            "/api/sentiment/theme-results",
            params={
                "client_id": str(CLIENT_ID),
                "theme_name": "Easy",
                "page_size": 101,
            },
        )
        assert db.calls == []
        valid_default = await client.get(
            "/api/sentiment/theme-results",
            params={"client_id": str(CLIENT_ID), "theme_name": "Easy"},
        )
    assert invalid_page.status_code == 422
    assert oversized.status_code == 422
    assert valid_default.status_code == 200
    body = valid_default.json()
    assert body["page"] == 1
    assert body["pages"] == 1


@pytest.mark.parametrize("module,endpoint", [
    (citations, citations.get_citations),
    (cited_domains, cited_domains.get_cited_domains_count),
    (cited_pages, cited_pages.get_cited_pages_count),
    (sentiment, sentiment.get_sentiment),
])
def test_invalid_prompt_uuid_is_rejected_before_database_access(monkeypatch, module, endpoint):
    db = RecordingDatabase()
    monkeypatch.setattr(module, "database", db)
    kwargs = {"client_id": str(CLIENT_ID), "prompt_id": "invalid"}
    if module is not sentiment:
        kwargs["client_id"] = CLIENT_ID
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(endpoint(**kwargs))
    assert exc_info.value.status_code == 422
    assert db.calls == []


def test_prompt_concept_endpoint_returns_tenant_scoped_variants(monkeypatch):
    class FakeRepo:
        def __init__(self, pool):
            self.pool = pool

        async def resolve_concept_by_prompt_id(self, client_id, prompt_id):
            assert client_id == str(CLIENT_ID)
            assert prompt_id == PROMPT_A
            return {
                "representative": {
                    "id": PROMPT_A,
                    "client_id": str(CLIENT_ID),
                    "topic_id": PROMPT_B,
                    "text": "Best robot vacuum",
                    "intent": "Solution Discovery",
                    "product": "S8 MaxV",
                    "language": "en-US",
                },
                "prompt_ids": [PROMPT_A, PROMPT_B],
            }

    monkeypatch.setattr(prompts, "PromptRepository", FakeRepo)
    result = asyncio.run(prompts.get_prompt_concept(
        client_id=CLIENT_ID,
        prompt_id=UUID(PROMPT_A),
        pool=object(),
    ))
    assert result.prompt_ids == [PROMPT_A, PROMPT_B]
    assert result.representative.intent == "Solution Discovery"


def test_prompt_concept_endpoint_hides_missing_or_other_tenant_prompt(monkeypatch):
    class FakeRepo:
        def __init__(self, pool):
            pass

        async def resolve_concept_by_prompt_id(self, client_id, prompt_id):
            return None

    monkeypatch.setattr(prompts, "PromptRepository", FakeRepo)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(prompts.get_prompt_concept(
            client_id=CLIENT_ID,
            prompt_id=UUID(PROMPT_A),
            pool=object(),
        ))
    assert exc_info.value.status_code == 404


def test_prompt_concept_list_returns_active_logical_rows(monkeypatch):
    class FakeRepo:
        def __init__(self, pool):
            self.pool = pool

        async def list_concepts_for_client(self, client_id, *, is_active):
            assert client_id == str(CLIENT_ID)
            assert is_active is True
            return [{
                "client_id": str(CLIENT_ID),
                "topic_id": PROMPT_B,
                "text": "Best robot vacuum",
                "intent": "Solution Discovery",
                "product": "S8 MaxV",
                "language": "en-US",
                "prompt_ids": [UUID(PROMPT_A), UUID(PROMPT_B)],
                "variant_platforms": ["chatgpt", "gemini"],
                "variant_countries": ["US", "DE"],
                "countries": ["DE", "US"],
                "platforms": ["chatgpt", "gemini"],
                "active_final_prompt_count": 2,
                "created_at": None,
                "updated_at": None,
            }]

    monkeypatch.setattr(prompts, "PromptRepository", FakeRepo)
    result = asyncio.run(prompts.list_prompt_concepts(
        client_id=CLIENT_ID,
        is_active=True,
        pool=object(),
    ))
    assert len(result) == 1
    assert result[0].id == PROMPT_A
    assert result[0].prompt_ids == [PROMPT_A, PROMPT_B]
    assert result[0].platforms == ["chatgpt", "gemini"]
    assert result[0].countries == ["DE", "US"]
    assert [variant.model_dump() for variant in result[0].variants] == [
        {"id": PROMPT_A, "platform": "chatgpt", "country": "US"},
        {"id": PROMPT_B, "platform": "gemini", "country": "DE"},
    ]
    assert result[0].is_active is True


def _concept_test_app(monkeypatch, repo_class, *, allowed: bool) -> FastAPI:
    async def current_user_override() -> AuthenticatedUser:
        return AuthenticatedUser(
            id=USER_ID,
            email="tester@example.com",
            google_sub="google-sub",
            name="Tester",
            avatar_url=None,
            is_active=True,
        )

    async def client_access(pool, user_id: str, client_id: str) -> bool:
        assert user_id == USER_ID
        assert client_id == str(CLIENT_ID)
        return allowed

    monkeypatch.setattr(auth_dependencies, "has_client_access", client_access)
    monkeypatch.setattr(prompts, "PromptRepository", repo_class)
    app = FastAPI()
    app.include_router(
        prompts.router,
        prefix="/api/prompts",
        dependencies=[Depends(auth_dependencies.require_client_access_if_present)],
    )
    app.dependency_overrides[auth_dependencies.require_current_user] = current_user_override
    app.dependency_overrides[prompts.get_pool] = lambda: object()
    return app


@pytest.mark.anyio
async def test_prompt_concept_asgi_denies_other_workspace_before_repository(monkeypatch):
    class NeverCalledRepo:
        calls = []

        def __init__(self, pool):
            self.pool = pool

        async def resolve_concept_by_prompt_id(self, client_id, prompt_id):
            self.calls.append((client_id, prompt_id))
            return None

    app = _concept_test_app(monkeypatch, NeverCalledRepo, allowed=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/api/prompts/{PROMPT_A}/concept",
            params={"client_id": str(CLIENT_ID)},
        )
    assert response.status_code == 403
    assert NeverCalledRepo.calls == []


@pytest.mark.anyio
async def test_prompt_concept_asgi_authorized_but_foreign_representative_is_safe_404(monkeypatch):
    class TenantScopedRepo:
        calls = []

        def __init__(self, pool):
            self.pool = pool

        async def resolve_concept_by_prompt_id(self, client_id, prompt_id):
            self.calls.append((client_id, prompt_id))
            return None

    app = _concept_test_app(monkeypatch, TenantScopedRepo, allowed=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/api/prompts/{PROMPT_A}/concept",
            params={"client_id": str(CLIENT_ID)},
        )
    assert response.status_code == 404
    assert response.json() == {"detail": "Prompt not found"}
    assert TenantScopedRepo.calls == [(str(CLIENT_ID), PROMPT_A)]
    assert "prompt_ids" not in response.json()


@pytest.mark.anyio
async def test_prompt_concept_asgi_authorized_returns_only_current_tenant_variants(monkeypatch):
    class TenantScopedRepo:
        def __init__(self, pool):
            self.pool = pool

        async def resolve_concept_by_prompt_id(self, client_id, prompt_id):
            assert client_id == str(CLIENT_ID)
            return {
                "representative": {
                    "id": prompt_id,
                    "client_id": client_id,
                    "topic_id": PROMPT_B,
                    "text": "Best robot vacuum",
                    "intent": "Solution Discovery",
                    "product": "S8 MaxV",
                    "language": "en-US",
                },
                "prompt_ids": [PROMPT_A, PROMPT_B],
            }

    app = _concept_test_app(monkeypatch, TenantScopedRepo, allowed=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/api/prompts/{PROMPT_A}/concept",
            params={"client_id": str(CLIENT_ID)},
        )
    assert response.status_code == 200
    assert response.json()["representative"]["client_id"] == str(CLIENT_ID)
    assert response.json()["prompt_ids"] == [PROMPT_A, PROMPT_B]
