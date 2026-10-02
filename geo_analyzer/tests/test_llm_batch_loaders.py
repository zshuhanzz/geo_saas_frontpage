from __future__ import annotations

import pytest

from src.jobs._llm_batch.loaders import all_known_lc, load_known_config


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._responses = [
            [
                {
                    "brand_name": "Dreamina",
                    "aliases": ["CapCut Dreamina", " dreamina ", ""],
                    "is_shadow": False,
                },
                {
                    "brand_name": "Amazon",
                    "aliases": ["Amazon Basics", " AMAZON "],
                    "is_shadow": True,
                },
            ],
            [],
            [],
        ]

    async def fetch(self, sql: str, *args: object) -> list[dict]:
        self.calls.append((sql, args))
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_load_known_config_includes_brand_aliases_in_own_and_shadow_sets() -> None:
    conn = _Connection()

    config = await load_known_config(conn, "client-1")

    brand_sql, brand_args = conn.calls[0]
    assert "aliases" in brand_sql
    assert brand_args == ("client-1",)
    assert config["own_brands"] == ["Dreamina", "CapCut Dreamina"]
    assert config["shadow_brands"] == ["Amazon", "Amazon Basics"]
    assert all_known_lc(config) >= {
        "dreamina",
        "capcut dreamina",
        "amazon",
        "amazon basics",
    }
