import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from routers.settings import products


CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
BRAND_ID = UUID("22222222-2222-2222-2222-222222222222")
PEER_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeBrandRepository:
    def __init__(self, row):
        self.row = row

    async def get_by_id(self, client_id, brand_id):
        assert (client_id, brand_id) == (str(CLIENT_ID), str(BRAND_ID))
        return self.row


class FakePeerRepository:
    def __init__(self, row):
        self.row = row

    async def get_by_id(self, client_id, peer_id):
        assert (client_id, peer_id) == (str(CLIENT_ID), str(PEER_ID))
        return self.row


def test_tracked_url_owner_rejects_brand_outside_workspace(monkeypatch):
    monkeypatch.setattr(products, "BrandRepository", lambda _pool: FakeBrandRepository(None))
    monkeypatch.setattr(products, "PeerRepository", lambda _pool: FakePeerRepository({"id": PEER_ID}))

    with pytest.raises(HTTPException) as error:
        asyncio.run(products._require_workspace_owner(
            object(), CLIENT_ID, brand_id=BRAND_ID, peer_id=None
        ))

    assert error.value.status_code == 422


def test_tracked_url_owner_rejects_peer_outside_workspace(monkeypatch):
    monkeypatch.setattr(products, "BrandRepository", lambda _pool: FakeBrandRepository({"id": BRAND_ID}))
    monkeypatch.setattr(products, "PeerRepository", lambda _pool: FakePeerRepository(None))

    with pytest.raises(HTTPException) as error:
        asyncio.run(products._require_workspace_owner(
            object(), CLIENT_ID, brand_id=None, peer_id=PEER_ID
        ))

    assert error.value.status_code == 422
