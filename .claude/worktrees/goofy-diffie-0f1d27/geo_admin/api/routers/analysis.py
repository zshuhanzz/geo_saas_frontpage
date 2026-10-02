"""
Analysis Router - Query geo_company_mentions and geo_citations

Provides endpoints for viewing analysis results with pagination and filtering.
"""
from fastapi import APIRouter, Query
from typing import Optional
from uuid import UUID
from sqlalchemy import select, func, and_

from database import (
    database,
    geo_results,
    geo_company_mentions,
    geo_citations
)

router = APIRouter(prefix="/analysis", tags=["Analysis"])


@router.get("/status/{report_id}")
async def get_analysis_status(report_id: UUID):
    """
    Get analysis status for a report.
    Returns counts of total, analyzed, and pending results.
    """
    # Total results
    total = await database.fetch_one(
        select(func.count()).select_from(geo_results).where(
            geo_results.c.report_id == report_id
        )
    )
    
    # Analyzed results
    analyzed = await database.fetch_one(
        select(func.count()).select_from(geo_results).where(
            and_(
                geo_results.c.report_id == report_id,
                geo_results.c.analyzed_at.isnot(None)
            )
        )
    )
    
    total_count = total[0] if total else 0
    analyzed_count = analyzed[0] if analyzed else 0
    pending_count = total_count - analyzed_count
    
    return {
        "report_id": str(report_id),
        "total_results": total_count,
        "analyzed_results": analyzed_count,
        "pending_results": pending_count,
        "can_analyze": pending_count > 0
    }


@router.get("/mentions")
async def get_mentions(
    report_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    platform: Optional[str] = None,
    intent: Optional[str] = None,
    topic: Optional[str] = None,
    product: Optional[str] = None,
    country: Optional[str] = None,
):
    """
    Get company mentions for a report with pagination and filtering.
    """
    # Build filters
    conditions = [geo_company_mentions.c.report_id == report_id]
    if platform:
        conditions.append(geo_company_mentions.c.platform == platform)
    if intent:
        conditions.append(geo_company_mentions.c.intent == intent)
    if topic:
        conditions.append(geo_company_mentions.c.topic == topic)
    if product:
        conditions.append(geo_company_mentions.c.product == product)
    if country:
        conditions.append(geo_company_mentions.c.country == country)
    
    where_clause = and_(*conditions)
    
    # Count total
    count_query = select(func.count()).select_from(geo_company_mentions).where(where_clause)
    total = await database.fetch_one(count_query)
    total_count = total[0] if total else 0
    
    # Fetch data with sorting
    offset = (page - 1) * limit
    query = (
        select(geo_company_mentions)
        .where(where_clause)
        .order_by(
            geo_company_mentions.c.request_id,
            geo_company_mentions.c.task_id,
            geo_company_mentions.c.result_id.asc(),
            geo_company_mentions.c.mention_position.asc()
        )
        .offset(offset)
        .limit(limit)
    )
    
    rows = await database.fetch_all(query)
    
    return {
        "data": [dict(row._mapping) for row in rows],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "pages": (total_count + limit - 1) // limit if total_count > 0 else 1
        }
    }


@router.get("/citations")
async def get_citations(
    report_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    platform: Optional[str] = None,
    intent: Optional[str] = None,
    topic: Optional[str] = None,
    product: Optional[str] = None,
    country: Optional[str] = None,
):
    """
    Get citations for a report with pagination and filtering.
    """
    # Build filters
    conditions = [geo_citations.c.report_id == report_id]
    if platform:
        conditions.append(geo_citations.c.platform == platform)
    if intent:
        conditions.append(geo_citations.c.intent == intent)
    if topic:
        conditions.append(geo_citations.c.topic == topic)
    if product:
        conditions.append(geo_citations.c.product == product)
    if country:
        conditions.append(geo_citations.c.country == country)
    
    where_clause = and_(*conditions)
    
    # Count total
    count_query = select(func.count()).select_from(geo_citations).where(where_clause)
    total = await database.fetch_one(count_query)
    total_count = total[0] if total else 0
    
    # Fetch data with sorting
    offset = (page - 1) * limit
    query = (
        select(geo_citations)
        .where(where_clause)
        .order_by(
            geo_citations.c.request_id,
            geo_citations.c.task_id,
            geo_citations.c.result_id.asc(),
            geo_citations.c.source_position.asc()
        )
        .offset(offset)
        .limit(limit)
    )
    
    rows = await database.fetch_all(query)
    
    return {
        "data": [dict(row._mapping) for row in rows],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "pages": (total_count + limit - 1) // limit if total_count > 0 else 1
        }
    }


@router.get("/filter-options/{report_id}")
async def get_filter_options(report_id: UUID):
    """
    Get distinct filter values for a report.
    Used to populate filter dropdowns.
    """
    # Get distinct platforms
    platforms = await database.fetch_all(
        select(geo_company_mentions.c.platform.distinct())
        .where(geo_company_mentions.c.report_id == report_id)
        .where(geo_company_mentions.c.platform.isnot(None))
    )
    
    # Get distinct intents
    intents = await database.fetch_all(
        select(geo_company_mentions.c.intent.distinct())
        .where(geo_company_mentions.c.report_id == report_id)
        .where(geo_company_mentions.c.intent.isnot(None))
    )
    
    # Get distinct topics
    topics = await database.fetch_all(
        select(geo_company_mentions.c.topic.distinct())
        .where(geo_company_mentions.c.report_id == report_id)
        .where(geo_company_mentions.c.topic.isnot(None))
    )
    
    # Get distinct products
    products = await database.fetch_all(
        select(geo_company_mentions.c.product.distinct())
        .where(geo_company_mentions.c.report_id == report_id)
        .where(geo_company_mentions.c.product.isnot(None))
    )
    
    # Get distinct countries
    countries = await database.fetch_all(
        select(geo_company_mentions.c.country.distinct())
        .where(geo_company_mentions.c.report_id == report_id)
        .where(geo_company_mentions.c.country.isnot(None))
    )
    
    return {
        "platforms": [row[0] for row in platforms],
        "intents": [row[0] for row in intents],
        "topics": [row[0] for row in topics],
        "products": [row[0] for row in products],
        "countries": [row[0] for row in countries],
    }
