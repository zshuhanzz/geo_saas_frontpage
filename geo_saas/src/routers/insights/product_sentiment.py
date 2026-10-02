"""
Product sentiment by role (Spec §7.2 ``product_sentiment_by_role``).

Joins ``geo_sentiment_results`` with ``geo_product_mentions`` on ``result_id``
(+ ``client_id``) and buckets by ``product_role``/``shadow_sub_role``. Uses a
parameterised raw SQL string via the asyncpg-backed ``database`` adapter — the
string carries ``:name`` placeholders only, no user-input interpolation.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from db import database

from ._helpers import date_range_filter_expr, parse_date_range

router = APIRouter()


class ProductSentimentRow(BaseModel):
    product_role: Optional[str] = None
    shadow_sub_role: Optional[str] = None
    sentiment: Optional[str] = None
    count: int


class ProductSentimentFilters(BaseModel):
    date_from: str
    date_to: str


class ProductSentimentOut(BaseModel):
    data: List[ProductSentimentRow] = []
    reason: Optional[str] = None
    filters: Optional[ProductSentimentFilters] = None


_DATE_FILTER = date_range_filter_expr("pm.executed_at", "date_from", "date_to")

_SQL = f"""
SELECT pm.product_role,
       pm.shadow_sub_role,
       sr.sentiment,
       COUNT(DISTINCT sr.id) AS cnt
  FROM geo_sentiment_results sr
  JOIN geo_product_mentions pm
    ON pm.result_id = sr.result_id
   AND pm.client_id = sr.client_id
  JOIN geo_client_prompts cp
    ON cp.id = sr.client_prompt_id
   AND cp.client_id = sr.client_id
  JOIN geo_client_brands cb
    ON cb.id = pm.owner_brand_id
   AND cb.client_id = pm.client_id
   AND cb.is_active = TRUE
   AND (
        (pm.product_role = 'own' AND cb.is_shadow = FALSE)
     OR (pm.product_role = 'shadow_brand_product' AND cb.is_shadow = TRUE)
   )
  JOIN geo_global_intents gi
    ON gi.intent_name = cp.intent
 WHERE sr.client_id = :client_id
   AND pm.client_id = :client_id
   AND cp.client_id = :client_id
   AND pm.product_role IN ('own', 'shadow_brand_product')
   AND pm.owner_brand_id IS NOT NULL
   AND cp.is_active = TRUE
   AND gi.is_active = TRUE
   AND gi.categories @> '["Sentiment"]'::jsonb
   AND {_DATE_FILTER}
 GROUP BY pm.product_role, pm.shadow_sub_role, sr.sentiment
 ORDER BY COUNT(DISTINCT sr.id) DESC
"""


@router.get("/product-sentiment-by-role", response_model=ProductSentimentOut)
async def product_sentiment_by_role(
    client_id: UUID,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> ProductSentimentOut:
    start_date, end_date = parse_date_range(date_from, date_to)

    rows = await database.fetch_all(
        _SQL,
        {
            "client_id": str(client_id),
            "date_from": start_date,
            "date_to": end_date,
        },
    )
    if not rows:
        return ProductSentimentOut(data=[], reason="no_data")

    return ProductSentimentOut(
        data=[
            ProductSentimentRow(
                product_role=r["product_role"],
                shadow_sub_role=r["shadow_sub_role"],
                sentiment=r["sentiment"],
                count=r["cnt"],
            )
            for r in rows
        ],
        filters=ProductSentimentFilters(
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        ),
    )
