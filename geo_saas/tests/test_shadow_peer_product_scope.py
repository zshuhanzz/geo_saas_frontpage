import asyncio
import inspect
from uuid import UUID

import pytest
from fastapi import HTTPException

from routers.settings import brands, peers, topics


CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
TOPIC_ID = UUID("22222222-2222-2222-2222-222222222222")
BRAND_ID = UUID("33333333-3333-3333-3333-333333333333")
PEER_ID = UUID("44444444-4444-4444-4444-444444444444")
PRODUCT_ID = UUID("55555555-5555-5555-5555-555555555555")


class FakeBrandRepository:
    async def get_by_id(self, client_id, brand_id):
        assert (client_id, brand_id) == (str(CLIENT_ID), str(BRAND_ID))
        return {"id": BRAND_ID, "is_shadow": True, "is_active": True}


class FakePeerRepository:
    def __init__(self, row):
        self.row = row

    async def get_by_id(self, client_id, peer_id):
        assert client_id == str(CLIENT_ID)
        assert peer_id == str(PEER_ID)
        return self.row


class FakeTopicRepository:
    def __init__(self, row):
        self.row = row

    async def get_by_id(self, client_id, topic_id):
        assert client_id == str(CLIENT_ID)
        assert topic_id == str(TOPIC_ID)
        return self.row


class RejectProductRepository:
    async def add_shadow_brand_product(self, *_args, **_kwargs):
        raise AssertionError("invalid scope must be rejected before insert")

    async def add_peer_product(self, *_args, **_kwargs):
        raise AssertionError("invalid scope must be rejected before insert")

    async def update(self, *_args, **_kwargs):
        raise AssertionError("invalid scope must be rejected before update")


class CaptureProductRepository:
    def __init__(self):
        self.updates = None

    async def update(self, _client_id, product_id, *, updates, scope):
        self.updates = updates
        return {
            "id": product_id,
            "client_id": CLIENT_ID,
            "topic_id": TOPIC_ID,
            "product_name": "Product",
            "match_variants": [],
            "product_role": scope.get("product_role", "shadow_brand_product"),
            "shadow_sub_role": updates.get("shadow_sub_role"),
            "owner_brand_id": BRAND_ID,
            "owner_peer_id": updates.get("owner_peer_id"),
            "is_active": True,
        }


def test_shadow_product_rejects_topic_outside_workspace(monkeypatch):
    monkeypatch.setattr(brands, "BrandRepository", lambda _pool: FakeBrandRepository())
    monkeypatch.setattr(brands, "TopicRepository", lambda _pool: FakeTopicRepository(None))
    monkeypatch.setattr(brands, "PeerRepository", lambda _pool: FakePeerRepository({"id": PEER_ID}))
    monkeypatch.setattr(brands, "TopicProductRepository", lambda _pool: RejectProductRepository())

    with pytest.raises(HTTPException) as error:
        asyncio.run(brands.create_shadow_brand_product(
            CLIENT_ID,
            BRAND_ID,
            brands.ShadowProductCreateInput(
                topic_id=TOPIC_ID,
                product_name="Resale Product",
            ),
            pool=object(),
        ))

    assert error.value.status_code == 422


def test_shadow_resale_product_rejects_peer_outside_workspace(monkeypatch):
    monkeypatch.setattr(brands, "BrandRepository", lambda _pool: FakeBrandRepository())
    monkeypatch.setattr(brands, "TopicRepository", lambda _pool: FakeTopicRepository({"id": TOPIC_ID}))
    monkeypatch.setattr(brands, "PeerRepository", lambda _pool: FakePeerRepository(None))
    monkeypatch.setattr(brands, "TopicProductRepository", lambda _pool: RejectProductRepository())

    with pytest.raises(HTTPException) as error:
        asyncio.run(brands.create_shadow_brand_product(
            CLIENT_ID,
            BRAND_ID,
            brands.ShadowProductCreateInput(
                topic_id=TOPIC_ID,
                product_name="Resale Product",
                shadow_sub_role="resale",
                owner_peer_id=PEER_ID,
            ),
            pool=object(),
        ))

    assert error.value.status_code == 422


def test_peer_product_rejects_topic_outside_workspace(monkeypatch):
    monkeypatch.setattr(peers, "PeerRepository", lambda _pool: FakePeerRepository({"id": PEER_ID}))
    monkeypatch.setattr(peers, "TopicRepository", lambda _pool: FakeTopicRepository(None))
    monkeypatch.setattr(peers, "TopicProductRepository", lambda _pool: RejectProductRepository())

    with pytest.raises(HTTPException) as error:
        asyncio.run(peers.create_peer_product(
            CLIENT_ID,
            PEER_ID,
            peers.PeerProductCreateInput(
                topic_id=TOPIC_ID,
                product_name="Peer Product",
            ),
            pool=object(),
        ))

    assert error.value.status_code == 422


def test_own_product_can_be_marked_unverified_without_entering_sentiment_scope(monkeypatch):
    repo = CaptureProductRepository()
    monkeypatch.setattr(topics, "TopicProductRepository", lambda _pool: repo)

    asyncio.run(topics.update_own_product(
        CLIENT_ID,
        TOPIC_ID,
        PRODUCT_ID,
        topics.OwnProductUpdateInput(owner_brand_id=None),
        pool=object(),
    ))

    assert repo.updates == {"owner_brand_id": None}


def test_shadow_product_update_preserves_explicit_peer_clear(monkeypatch):
    repo = CaptureProductRepository()
    monkeypatch.setattr(brands, "TopicProductRepository", lambda _pool: repo)

    asyncio.run(brands.update_shadow_brand_product(
        CLIENT_ID,
        BRAND_ID,
        PRODUCT_ID,
        brands.ShadowProductUpdateInput(
            shadow_sub_role="native",
            owner_peer_id=None,
        ),
        pool=object(),
    ))

    assert repo.updates == {
        "shadow_sub_role": "native",
        "owner_peer_id": None,
    }


def test_brand_delete_removes_shadow_products_before_brand_fk_action():
    source = inspect.getsource(brands.delete_brand)

    product_delete = source.index("DELETE FROM geo_client_topic_products")
    brand_delete = source.index("DELETE FROM geo_client_brands")
    assert product_delete < brand_delete
    assert "conn.transaction()" in source


def test_brand_deactivation_reconciles_active_products_before_brand_update():
    source = inspect.getsource(brands.update_brand)

    own_unbind = source.index("SET owner_brand_id = NULL")
    shadow_deactivate = source.index("SET is_active = FALSE")
    brand_update = source.index("UPDATE geo_client_brands")
    assert own_unbind < brand_update
    assert shadow_deactivate < brand_update
    assert "conn.transaction()" in source
    assert "FOR UPDATE" in source
