from __future__ import annotations

from dataclasses import dataclass, field

from .models import ReportDates


@dataclass
class ReadinessResult:
    reasons: list[str] = field(default_factory=list)
    data_completeness: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return len(self.reasons) == 0


async def has_sentiment_scope(conn, client_id: str) -> bool:
    value = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM geo_client_prompts cp
            JOIN geo_global_intents gi
              ON gi.intent_name = cp.intent
             AND gi.is_active = true
            WHERE cp.client_id = $1::uuid
              AND cp.is_active = true
              AND gi.categories @> '["Sentiment"]'::jsonb
        )
        """,
        client_id,
    )
    return bool(value)


async def check_report_readiness(pool, client_id: str, dates: ReportDates) -> ReadinessResult:
    reasons: list[str] = []
    async with pool.acquire() as conn:
        raw_results = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_results
            WHERE client_id = $1::uuid
              AND (ingested_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

        analyzed_results = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_results
            WHERE client_id = $1::uuid
              AND analyzed_at IS NOT NULL
              AND (ingested_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

        same_day_analyzed = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_results
            WHERE client_id = $1::uuid
              AND analyzed_at IS NOT NULL
              AND (ingested_at AT TIME ZONE $3)::date = $2
            """,
            client_id,
            dates.report_date,
            dates.timezone,
        ) or 0)

        visibility_rows = int(await conn.fetchval(
            """
            SELECT COUNT(*) FROM (
                SELECT result_id
                FROM geo_brand_mentions
                WHERE client_id = $1::uuid
                  AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
                UNION
                SELECT result_id
                FROM geo_product_mentions
                WHERE client_id = $1::uuid
                  AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            ) visibility
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

        citation_rows = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_citations
            WHERE client_id = $1::uuid
              AND (executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

        sentiment_expected = await has_sentiment_scope(conn, client_id)
        sentiment_rows = int(await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM geo_sentiment_results sr
            JOIN geo_client_prompts cp
              ON cp.id = sr.client_prompt_id
             AND cp.client_id = sr.client_id
            JOIN geo_global_intents gi
              ON gi.intent_name = cp.intent
             AND gi.is_active = true
            WHERE sr.client_id = $1::uuid
              AND cp.is_active = true
              AND gi.categories @> '["Sentiment"]'::jsonb
              AND (sr.executed_at AT TIME ZONE $4)::date BETWEEN $2 AND $3
            """,
            client_id,
            dates.window_start,
            dates.window_end,
            dates.timezone,
        ) or 0)

    if raw_results == 0:
        reasons.append("raw_results_missing")
    if analyzed_results == 0:
        reasons.append("analyzed_results_missing")
    if same_day_analyzed == 0:
        reasons.append("same_day_analyzed_results_missing")
    if visibility_rows == 0:
        reasons.append("visibility_missing")
    if citation_rows == 0:
        reasons.append("citation_missing")
    if sentiment_expected and sentiment_rows == 0:
        reasons.append("sentiment_missing")

    analyzed_pct = round((analyzed_results / raw_results) * 100, 1) if raw_results else 0
    return ReadinessResult(
        reasons=reasons,
        data_completeness={
            "raw_results": raw_results,
            "analyzed_results": analyzed_results,
            "same_day_analyzed_results": same_day_analyzed,
            "analyzed_pct": analyzed_pct,
            "visibility_rows": visibility_rows,
            "citation_rows": citation_rows,
            "sentiment_expected": sentiment_expected,
            "sentiment_rows": sentiment_rows,
        },
    )
