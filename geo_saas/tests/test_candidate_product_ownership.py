import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from routers.settings import candidates


CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
TOPIC_ID = UUID("22222222-2222-2222-2222-222222222222")
BRAND_ID = UUID("33333333-3333-3333-3333-333333333333")
PEER_ID = UUID("44444444-4444-4444-4444-444444444444")
CANDIDATE_ID = UUID("66666666-6666-6666-6666-666666666666")


class FakeDatabase:
    def __init__(self, *, topic=None, brand=None, peer=None):
        self.topic = topic
        self.brand = brand
        self.peer = peer
        self.calls = []

    async def fetch_one(self, sql, params):
        self.calls.append((sql, params))
        if "FROM geo_client_topics" in sql:
            return self.topic
        if "FROM geo_client_brands" in sql:
            return self.brand
        if "FROM geo_client_peers" in sql:
            return self.peer
        if "INSERT INTO geo_client_topic_products" in sql:
            return {
                "id": UUID("55555555-5555-5555-5555-555555555555"),
                "client_id": CLIENT_ID,
                "topic_id": TOPIC_ID,
                "product_name": "Studio Pro",
                "match_variants": ["Studio Pro"],
                "product_role": params["product_role"],
                "shadow_sub_role": None,
                "owner_brand_id": params["owner_brand_id"],
                "owner_peer_id": params["owner_peer_id"],
                "is_active": True,
            }
        raise AssertionError(f"Unexpected SQL: {sql}")


def _accept(monkeypatch, fake_db, *, role, brand_id=None, peer_id=None):
    monkeypatch.setattr(candidates, "database", fake_db)
    return asyncio.run(candidates._accept_product(
        CLIENT_ID,
        "Studio Pro",
        TOPIC_ID,
        role,
        brand_id,
        peer_id,
    ))


def test_candidate_product_rejects_topic_outside_workspace(monkeypatch):
    fake_db = FakeDatabase(
        topic=None,
        brand={"id": BRAND_ID, "is_shadow": False, "is_active": True},
    )

    with pytest.raises(HTTPException) as error:
        _accept(monkeypatch, fake_db, role="own", brand_id=BRAND_ID)

    assert error.value.status_code == 422
    assert not any("INSERT INTO geo_client_topic_products" in sql for sql, _ in fake_db.calls)


@pytest.mark.parametrize(
    ("role", "brand", "peer", "brand_id", "peer_id"),
    [
        ("own", {"id": BRAND_ID, "is_shadow": True, "is_active": True}, None, BRAND_ID, None),
        ("shadow_brand_product", {"id": BRAND_ID, "is_shadow": False, "is_active": True}, None, BRAND_ID, None),
        ("peer", None, None, None, PEER_ID),
    ],
)
def test_candidate_product_rejects_foreign_or_wrong_role_owner(
    monkeypatch, role, brand, peer, brand_id, peer_id,
):
    fake_db = FakeDatabase(
        topic={"id": TOPIC_ID},
        brand=brand,
        peer=peer,
    )

    with pytest.raises(HTTPException) as error:
        _accept(
            monkeypatch,
            fake_db,
            role=role,
            brand_id=brand_id,
            peer_id=peer_id,
        )

    assert error.value.status_code == 422
    assert not any("INSERT INTO geo_client_topic_products" in sql for sql, _ in fake_db.calls)


@pytest.mark.parametrize(
    ("role", "brand", "peer", "brand_id", "peer_id"),
    [
        ("own", {"id": BRAND_ID, "is_shadow": False, "is_active": True}, None, BRAND_ID, None),
        ("shadow_brand_product", {"id": BRAND_ID, "is_shadow": True, "is_active": True}, None, BRAND_ID, None),
        ("peer", None, {"id": PEER_ID}, None, PEER_ID),
    ],
)
def test_candidate_product_accepts_only_tenant_scoped_role_owner(
    monkeypatch, role, brand, peer, brand_id, peer_id,
):
    fake_db = FakeDatabase(
        topic={"id": TOPIC_ID},
        brand=brand,
        peer=peer,
    )

    result = _accept(
        monkeypatch,
        fake_db,
        role=role,
        brand_id=brand_id,
        peer_id=peer_id,
    )

    assert result["action"] == "created"
    assert any("INSERT INTO geo_client_topic_products" in sql for sql, _ in fake_db.calls)
    topic_sql = next(sql for sql, _ in fake_db.calls if "FROM geo_client_topics" in sql)
    assert "is_active" not in topic_sql


def test_tracked_url_candidate_calls_acceptor_with_one_scoped_argument_set(monkeypatch):
    calls = []

    async def fake_get_candidate(candidate_id, client_id):
        assert (candidate_id, client_id) == (CANDIDATE_ID, CLIENT_ID)
        return {
            "status": "pending",
            "candidate_string": "https://example.com/product",
            "candidate_type": "tracked_url",
        }

    async def fake_accept_tracked_url(client_id, candidate_string, product_id, url_scope):
        calls.append((client_id, candidate_string, product_id, url_scope))
        return {"action": "created", "tracked_url": {}}

    async def fake_mark(*_args):
        return None

    monkeypatch.setattr(candidates, "_get_candidate_or_404", fake_get_candidate)
    monkeypatch.setattr(candidates, "_accept_tracked_url", fake_accept_tracked_url)
    monkeypatch.setattr(candidates, "_mark_candidate_status", fake_mark)

    result = asyncio.run(candidates.accept_candidate.__wrapped__(
        CLIENT_ID,
        CANDIDATE_ID,
        candidates.CandidateAcceptInput(
            target_product_id=TOPIC_ID,
            url_scope="exact",
        ),
    ))

    assert result.status == "accepted"
    assert calls == [
        (CLIENT_ID, "https://example.com/product", TOPIC_ID, "exact")
    ]
