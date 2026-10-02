"""
Chart generation tool for geo_agent.

Transforms raw query results into Recharts-compatible JSON configs.
This is a pure transformation — no LLM call, no DB call.
"""
import logging
from typing import Any, Optional
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def chart_generator(
    data: dict,
    chart_type: str = "auto",
    title: Optional[str] = None,
) -> dict:
    """Generate a Recharts-compatible chart config from query results.

    Takes the output of a data tool (visibility_query, citations_query,
    sentiment_query) and transforms it into a chart specification that
    the frontend can render directly with Recharts.

    Args:
        data: Output dict from a data tool (must have a "metric" key).
        chart_type: "bar", "line", "pie", or "auto" (inferred from data).
        title: Optional chart title override.
    """
    metric = data.get("metric", "")

    if metric == "visibility":
        return _visibility_chart(data, chart_type, title)
    elif metric == "visibility_trend":
        return _visibility_trend_chart(data, chart_type, title)
    elif metric == "citations":
        return _citations_chart(data, chart_type, title)
    elif metric == "sentiment":
        return _sentiment_chart(data, chart_type, title)
    else:
        return {"error": f"Unknown metric type: {metric}"}


def _visibility_chart(data: dict, chart_type: str, title: Optional[str]) -> dict:
    """Visibility chart: type determined by LLM planner (bar for comparison, line for trends)."""
    companies = data.get("companies", [])
    if not companies:
        return {"error": "No visibility data to chart"}

    # LLM planner decides chart_type; fallback to bar only if truly unspecified
    effective_type = chart_type if chart_type != "auto" else "bar"
    # v1.2: brand_name replaces company_name; brand_role replaces is_own_brand
    # (brand_role enum: 'own' | 'shadow' | 'peer'). The "isOwn" shape is
    # preserved for frontend consumers; derive it from brand_role == 'own'.
    chart_data = []
    for c in companies[:10]:
        name = c.get("brand_name", c.get("company_name"))
        if "brand_role" in c:
            is_own = c["brand_role"] == "own"
        elif "is_own_brand" in c:
            # Transitional fallback: some callers may still emit the legacy key
            # during the phased rollout. Remove once all producers are v1.2.
            is_own = bool(c["is_own_brand"])
        else:
            is_own = False
        chart_data.append({
            "name": name,
            "mentions": c["mention_count"],
            "sov": c["sov_pct"],
            "isOwn": is_own,
        })

    platform_label = f" ({data['platform']})" if data.get("platform") else ""
    return {
        "type": effective_type,
        "title": title or f"Brand Visibility — Past {data['days']} Days{platform_label}",
        "data": chart_data,
        "xKey": "name",
        "yKeys": ["mentions"],
        "meta": {"total_mentions": data["total_mentions"]},
    }


def _visibility_trend_chart(data: dict, chart_type: str, title: Optional[str]) -> dict:
    """Visibility trend line chart: date on X, own_brand / competitors on Y."""
    points = data.get("data_points", [])
    if not points:
        return {"error": "No trend data to chart"}

    platform_label = f" ({data['platform']})" if data.get("platform") else ""
    return {
        "type": "line",
        "title": title or f"Visibility Trend — Past {data['days']} Days{platform_label}",
        "data": points,
        "xKey": "date",
        "yKeys": ["own_brand", "competitors"],
        "meta": {"days": data["days"]},
    }


def _citations_chart(data: dict, chart_type: str, title: Optional[str]) -> dict:
    """Top domains bar chart + own domain rate."""
    domains = data.get("top_domains", [])
    if not domains:
        return {"error": "No citation data to chart"}

    effective_type = chart_type if chart_type != "auto" else "bar"
    chart_data = [
        {
            "name": d["domain"],
            "citations": d["count"],
            "category": d["category"] or "Unknown",
        }
        for d in domains[:10]
    ]

    return {
        "type": effective_type,
        "title": title or f"Top Citation Sources — Past {data['days']} Days",
        "data": chart_data,
        "xKey": "name",
        "yKeys": ["citations"],
        "meta": {
            "total_citations": data["total_citations"],
            "own_domain_rate_pct": data["own_domain_rate_pct"],
        },
    }


def _sentiment_chart(data: dict, chart_type: str, title: Optional[str]) -> dict:
    """Sentiment distribution pie chart."""
    dist = data.get("distribution", {})
    if not dist:
        return {"error": "No sentiment data to chart"}

    effective_type = chart_type if chart_type != "auto" else "pie"
    chart_data = [
        {
            "name": sentiment,
            "value": info["count"],
            "pct": info["pct"],
        }
        for sentiment, info in dist.items()
    ]

    return {
        "type": effective_type,
        "title": title or f"Sentiment Distribution — Past {data['days']} Days",
        "data": chart_data,
        "nameKey": "name",
        "valueKey": "value",
        "meta": {"total_analyzed": data["total_analyzed"]},
    }
