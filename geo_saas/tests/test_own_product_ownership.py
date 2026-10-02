import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from routers.settings import topics


CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
TOPIC_ID = UUID("22222222-2222-2222-2222-222222222222")
PRODUCT_ID = UUID("33333333-3333-3333-3333-333333333333")
BRAND_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeTopicRepository:
    async def get_by_id(self, client_id, topic_id):
        assert (client_id, topic_id) == (str(CLIENT_ID), str(TOPIC_ID))
        return {"id": topic_id}


class FakeBrandRepository:
    def __init__(self, brand):
        self.brand = brand

    async def get_by_id(self, client_id, brand_id):
        assert client_id == str(CLIENT_ID)
        assert brand_id == str(BRAND_ID)
        return self.brand


class FakeProductRepository:
    def __init__(self):
        self.owner_brand_id = None

    async def add_own_product(self, client_id, **kwargs):
        self.owner_brand_id = kwargs["owner_brand_id"]
        return {
            "id": PRODUCT_ID,
            "topic_id": TOPIC_ID,
            "client_id": CLIENT_ID,
            "product_name": kwargs["product_name"],
            "match_variants": kwargs["match_variants"],
            "product_role": "own",
            "shadow_sub_role": None,
            "owner_brand_id": kwargs["owner_brand_id"],
            "owner_peer_id": None,
            "is_active": kwargs["is_active"],
        }


def _wire_repositories(monkeypatch, brand):
    products = FakeProductRepository()
    monkeypatch.setattr(topics, "TopicRepository", lambda _pool: FakeTopicRepository())
    monkeypatch.setattr(topics, "BrandRepository", lambda _pool: FakeBrandRepository(brand))
    monkeypatch.setattr(topics, "TopicProductRepository", lambda _pool: products)
    return products


def test_create_own_product_requires_tenant_scoped_non_shadow_brand(monkeypatch):
    products = _wire_repositories(
        monkeypatch,
        {"id": BRAND_ID, "is_shadow": False, "is_active": True},
    )

    result = asyncio.run(topics.create_own_product(
        CLIENT_ID,
        TOPIC_ID,
        topics.OwnProductCreateInput(
            product_name="Studio Pro",
            owner_brand_id=BRAND_ID,
        ),
        pool=object(),
    ))

    assert result.owner_brand_id == str(BRAND_ID)
    assert products.owner_brand_id == str(BRAND_ID)


@pytest.mark.parametrize("brand", [None, {"id": BRAND_ID, "is_shadow": True, "is_active": True}])
def test_create_own_product_rejects_foreign_or_shadow_brand(monkeypatch, brand):
    _wire_repositories(monkeypatch, brand)

    with pytest.raises(HTTPException) as error:
        asyncio.run(topics.create_own_product(
            CLIENT_ID,
            TOPIC_ID,
            topics.OwnProductCreateInput(
                product_name="Studio Pro",
                owner_brand_id=BRAND_ID,
            ),
            pool=object(),
        ))

    assert error.value.status_code == 422
