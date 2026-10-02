from routers.insights import published_url_tracking


PAGE_ID = "11111111-1111-1111-1111-111111111111"
OTHER_PAGE_ID = "22222222-2222-2222-2222-222222222222"
BASE_URL = "https://example.com/article"


def test_variant_resolver_api_exists():
    assert hasattr(published_url_tracking, "resolve_published_url_variants")


def _published(page_id=PAGE_ID, url=BASE_URL):
    return {
        "id": page_id,
        "published_url": url,
        "normalized_url": url,
    }


def _citation(url, count=1):
    return {"source_url": url, "citation_count": count}


def test_conservative_match_key_auto_matches_tracking_params_but_not_content_params():
    resolution = published_url_tracking.resolve_published_url_variants(
        published_rows=[_published()],
        citation_rows=[
            _citation(BASE_URL, 2),
            _citation(f"{BASE_URL}?utm_source=chatgpt.com", 5),
            _citation(f"{BASE_URL}#:~:text=quote", 1),
            _citation(f"{BASE_URL}?variant=red", 3),
        ],
        mapping_rows=[],
    )

    assert resolution.matched_source_urls_by_published_id[PAGE_ID] == {
        BASE_URL,
        f"{BASE_URL}?utm_source=chatgpt.com",
        f"{BASE_URL}#:~:text=quote",
    }
    statuses = {item.source_url: item.status for item in resolution.variants_by_published_id[PAGE_ID]}
    assert statuses[f"{BASE_URL}?utm_source=chatgpt.com"] == "automatic"
    assert statuses[f"{BASE_URL}?variant=red"] == "pending"
    assert resolution.pending_count_by_published_id[PAGE_ID] == 1


def test_confirmed_match_key_includes_future_tracking_variants_without_changing_citations():
    confirmed_url = f"{BASE_URL}?variant=red"
    future_url = f"{BASE_URL}?utm_campaign=x&variant=red"
    resolution = published_url_tracking.resolve_published_url_variants(
        published_rows=[_published()],
        citation_rows=[_citation(confirmed_url, 3), _citation(future_url, 4)],
        mapping_rows=[{
            "published_url_id": PAGE_ID,
            "citation_url": confirmed_url,
            "citation_match_key": confirmed_url,
            "status": "confirmed",
        }],
    )

    assert resolution.matched_source_urls_by_published_id[PAGE_ID] == {confirmed_url, future_url}
    assert {
        item.status for item in resolution.variants_by_published_id[PAGE_ID]
    } == {"confirmed"}


def test_rejected_variant_is_not_counted_or_returned_as_pending():
    rejected_url = f"{BASE_URL}?variant=red"
    resolution = published_url_tracking.resolve_published_url_variants(
        published_rows=[_published()],
        citation_rows=[_citation(rejected_url, 3)],
        mapping_rows=[{
            "published_url_id": PAGE_ID,
            "citation_url": rejected_url,
            "citation_match_key": rejected_url,
            "status": "rejected",
        }],
    )

    assert resolution.matched_source_urls_by_published_id[PAGE_ID] == set()
    assert resolution.variants_by_published_id[PAGE_ID][0].status == "rejected"
    assert resolution.pending_count_by_published_id[PAGE_ID] == 0


def test_same_raw_url_grouped_by_category_is_one_candidate_with_summed_count():
    candidate_url = f"{BASE_URL}?variant=red"
    resolution = published_url_tracking.resolve_published_url_variants(
        published_rows=[_published()],
        citation_rows=[
            _citation(candidate_url, 2),
            _citation(candidate_url, 3),
        ],
        mapping_rows=[],
    )

    variants = resolution.variants_by_published_id[PAGE_ID]
    assert len(variants) == 1
    assert variants[0].source_url == candidate_url
    assert variants[0].citation_count == 5
    assert resolution.pending_count_by_published_id[PAGE_ID] == 1


def test_ambiguous_automatic_match_never_counts_one_citation_twice():
    citation_url = f"{BASE_URL}?utm_source=x"
    resolution = published_url_tracking.resolve_published_url_variants(
        published_rows=[_published(), _published(OTHER_PAGE_ID, f"{BASE_URL}?utm_source=other")],
        citation_rows=[_citation(citation_url, 2)],
        mapping_rows=[],
    )

    assert resolution.matched_source_urls_by_published_id[PAGE_ID] == set()
    assert resolution.matched_source_urls_by_published_id[OTHER_PAGE_ID] == set()
    assert resolution.pending_count_by_published_id[PAGE_ID] == 1
    assert resolution.pending_count_by_published_id[OTHER_PAGE_ID] == 1


def test_candidate_sql_uses_query_and_fragment_boundaries_not_broad_prefixes():
    assert hasattr(published_url_tracking, "build_candidate_url_predicate")
    sql, params = published_url_tracking.build_candidate_url_predicate(
        published_rows=[_published(url="https://example.com/a_percent%/item_name_")],
        mapping_rows=[],
        prefix="candidate",
    )

    assert "c.source_url = :candidate_exact_0" in sql
    assert "c.source_url LIKE :candidate_query_0 ESCAPE '\\'" in sql
    assert "c.source_url LIKE :candidate_fragment_0 ESCAPE '\\'" in sql
    assert params["candidate_exact_0"] == "https://example.com/a_percent%/item_name_"
    assert params["candidate_query_0"] == "https://example.com/a\\_percent\\%/item\\_name\\_?%"
    assert params["candidate_fragment_0"] == "https://example.com/a\\_percent\\%/item\\_name\\_#%"


def test_candidate_sql_covers_trailing_slash_variant_of_same_match_key():
    sql, params = published_url_tracking.build_candidate_url_predicate(
        published_rows=[_published()],
        mapping_rows=[],
        prefix="candidate",
    )

    assert "https://example.com/article" in params.values()
    assert "https://example.com/article/" in params.values()
    assert sql.count("c.source_url =") == 2


def test_candidate_sql_includes_confirmed_alias_origin_path():
    alias_url = "https://cdn.example.com/render?id=123"
    sql, params = published_url_tracking.build_candidate_url_predicate(
        published_rows=[_published()],
        mapping_rows=[{
            "published_url_id": PAGE_ID,
            "citation_url": alias_url,
            "citation_match_key": alias_url,
            "status": "confirmed",
        }],
        prefix="variant",
    )

    assert "https://cdn.example.com/render" in params.values()
    assert sql.count("c.source_url =") == 4


def test_variant_discovery_endpoint_exists():
    assert hasattr(published_url_tracking, "get_published_url_tracking_variants")
