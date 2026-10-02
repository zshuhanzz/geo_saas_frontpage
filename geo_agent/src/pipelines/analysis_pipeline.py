"""
Analysis Pipeline — 5-step background workflow.

Migrated from geo_saas/src/routers/insights/analysis.py.
Steps:
  1. 输入校验 (Validate Inputs) — Validate domains, date range, verify data exists
  2. 指标水合 (Hydrate Metrics) — Batch SQL generation per domain, parallel execution
  3. 图表生成 (Generate Charts)  — NL2SQL chart data generation
  4. 报告合成 (Synthesize Report) — Prompt hydration + LLM report generation
  5. 质量评审 (Quality Check)    — LLM audit for data accuracy + hallucination detection

Reuses the fire-and-forget pattern from pipelines.base.
"""
import re
import json
import asyncio
import logging
from typing import Any, Optional
from datetime import datetime, timezone
from decimal import Decimal
from collections import defaultdict

from google.genai import types

from llm.client import get_genai_client, get_model_id
from pipelines.base import WorkflowStep, run_pipeline, append_status_log
from database import get_pool
from routers.tasks import register_pipeline
from pipelines.template_contracts import (
    get_contract_for_task,
    build_metric_objects_from_contract_async,
    load_workflow_dictionary_rows,
    CHAPTER_HEADING_KEYWORDS,
)

logger = logging.getLogger(__name__)

# ─── SQL Safety ───────────────────────────────────────────────────────

# v1.2: geo_company_mentions renamed to geo_brand_mentions; new
# product-level mention + tracked-URL tables surfaced so visibility /
# citation NL2SQL prompts can reach them.
ALLOWED_TABLES = {
    "visibility": [
        "geo_brand_mentions", "geo_product_mentions",
        "geo_results", "geo_tasks", "geo_client_prompts",
        "geo_client_brands", "geo_client_peers", "geo_client_topic_products",
        "geo_global_intents",
    ],
    "citation": [
        "geo_citations", "geo_results", "geo_tasks", "geo_client_prompts",
        "geo_client_domains", "geo_product_tracked_urls",
        "geo_domain_categories", "geo_global_intents",
    ],
    "sentiment": [
        "geo_sentiment_results", "geo_sentiment_themes",
        "geo_results", "geo_tasks", "geo_client_prompts",
        # v1.2: sentiment SCHEMA_HINTS recommends joining against
        # geo_product_mentions for role-scoped product sentiment breakdowns.
        "geo_product_mentions", "geo_global_intents",
    ],
}

SAFE_SQL_RE = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b',
    re.IGNORECASE,
)


def validate_sql_safety(sql: str, allowed_domains: list[str]) -> tuple[bool, str]:
    """Check SQL for forbidden operations and table references."""
    if SAFE_SQL_RE.search(sql):
        return False, "SQL contains forbidden write/DDL operation"

    # Build allowed table set from selected domains
    allowed = set()
    for domain in allowed_domains:
        allowed.update(ALLOWED_TABLES.get(domain, []))
    # Always allow these reference tables (client config + brand metadata).
    # v1.2 adds geo_client_brands / geo_client_topic_products /
    # geo_product_sales_channels / geo_settings_candidates so joins against
    # brand / product / channel metadata don't get rejected.
    allowed.update({
        "geo_clients",
        "geo_client_brands",
        "geo_client_topics",
        "geo_client_topic_products",
        "geo_client_peers",
        "geo_client_domains",
        "geo_product_sales_channels",
        "geo_product_tracked_urls",
        "geo_settings_candidates",
        "geo_brand_profiles",
        "geo_global_intents",
    })

    # Check referenced tables
    referenced = set(re.findall(r'\b(geo_\w+)\b', sql))
    forbidden = referenced - allowed
    if forbidden:
        return False, f"Forbidden tables: {', '.join(forbidden)}"

    return True, ""


METRIC_DOMAIN_CATEGORIES = {
    "visibility": "Visibility",
    "citation": "Citation",
    "sentiment": "Sentiment",
}


def build_metric_category_scope_rules(domains: list[str]) -> str:
    """Return Global Config intent-category scope rules for SQL generation.

    Visibility/Citation/Sentiment are configured independently in
    geo_global_intents.categories. Analyzer raw tables intentionally keep all
    rows; report SQL chooses which prompt intents count for each metric.
    """
    active = []
    seen: set[str] = set()
    for domain in domains:
        category = METRIC_DOMAIN_CATEGORIES.get(domain)
        if category and category not in seen:
            active.append((domain, category))
            seen.add(category)

    if not active:
        return ""

    lines = [
        "MANDATORY GLOBAL CONFIG INTENT SCOPE (zero-tolerance, SQL missing this may overcount):",
        "- Raw analyzer tables keep ALL prompts. Report/Agent SQL must filter by the metric's configured Intent category.",
        "- Join `geo_client_prompts cp` using the primary fact table's `client_prompt_id` and `client_id`.",
        "- `geo_sentiment_themes` has `client_prompt_id`; join `geo_client_prompts` directly with `cp.id = geo_sentiment_themes.client_prompt_id` and matching `client_id`.",
        "- If another table lacks `client_prompt_id`, first join its parent fact table that carries the prompt relationship.",
        "- Join `geo_global_intents gi` with `gi.intent_name = cp.intent`.",
        "- Add `cp.client_id = $1`, `cp.is_active = true`, `gi.is_active = true`, and the matching `gi.categories @> ...::jsonb` predicate.",
        "- Apply the same category filter to every numerator, denominator, total CTE, and chart query. Never fall back to all intents when no intent is configured for that metric category.",
        "- Category mapping for this request:",
    ]
    for domain, category in active:
        lines.append(f"  - `{domain}` metrics: `gi.categories @> '[\"{category}\"]'::jsonb`")
    return "\n".join(lines) + "\n"


# Post-generation enum auto-fix (2026-04-20, B-5/themes bug fix).
#
# The NL2SQL LLM occasionally emits enum literals in the wrong case
# ('positive' vs 'Positive') or the wrong product_role keyword ('owned'
# vs 'own'), even when the prompt explicitly spells them out. These errors
# make the query return zero rows silently — the metric shows up as NULL
# in the final report and the user has no idea the SQL was wrong.
#
# This rewriter patches the known-good enum literals in place. It is
# intentionally scoped to literal strings inside quotes so it can't flip
# a column name or break a legitimate identifier.
_ENUM_LITERAL_FIXES: list[tuple[re.Pattern, str]] = [
    # Sentiment enums are case-sensitive. Insufficient Evidence is an overall
    # response state only; themes use the other three labels.
    (re.compile(r"'positive'", re.IGNORECASE), "'Positive'"),
    (re.compile(r"'mixed/neutral'", re.IGNORECASE), "'Mixed/Neutral'"),
    (re.compile(r"'negative'", re.IGNORECASE), "'Negative'"),
    (re.compile(r"'insufficient evidence'", re.IGNORECASE), "'Insufficient Evidence'"),
    # product_role: DB enum is 'own', NOT 'owned' / 'own_brand' / 'owner'.
    (re.compile(r"product_role\s*=\s*'owned'"), "product_role = 'own'"),
    (re.compile(r"product_role\s*=\s*'own_brand'"), "product_role = 'own'"),
    (re.compile(r"product_role\s*IN\s*\(\s*'owned'\s*\)"), "product_role IN ('own')"),
]


def normalize_enum_literals(sql: str) -> str:
    """Rewrite known LLM-hallucinated enum cases in generated metric SQL.

    Applied AFTER table-safety validation so we never rewrite a SQL that
    would have been rejected anyway. No-op when no bad literal is found.
    """
    out = sql
    for pat, repl in _ENUM_LITERAL_FIXES:
        # Leave the capitalized correct form alone.
        if pat.pattern.replace("'", "").lower() in repl.lower():
            pass
        out = pat.sub(repl, out)
    return out


# ─── Schema hints for Gemini prompts ──────────────────────────────────

SCHEMA_HINTS = {
    "visibility": """-- geo_brand_mentions (v1.2 renamed from geo_company_mentions):
--   id, client_prompt_id, task_id, result_id, client_id, brand_name,
--   brand_role TEXT CHECK IN ('own','shadow','peer'),
--   mention_position (1=top), executed_at.
--   NOTE: Peer SOV MUST use peer-list membership (EXISTS on
--   geo_client_peers by primary_name/aliases) rather than
--   brand_role='peer', since a brand that is both Shadow and Peer is
--   emitted as brand_role='shadow' by the parser.
-- geo_product_mentions (v1.2 new): id, client_prompt_id, task_id, result_id,
--   client_id, product_id, product_name,
--   product_role IN ('own','shadow_brand_product','peer'),
--   shadow_sub_role IN ('native','resale') OR NULL,
--   owner_brand_id/owner_brand_name (denormalized),
--   owner_peer_id/owner_peer_name (denormalized),
--   mention_position, executed_at.
-- geo_client_brands (v1.2 new): id, client_id, brand_name, aliases TEXT[],
--   is_shadow BOOL (true=Shadow/OEM channel, false=Own), is_active.
-- geo_client_peers: id, client_id, primary_name, aliases TEXT[].
--   (v1.2: is_own_brand column DROPPED — every row is a Peer by definition.)
-- geo_client_topic_products (v1.2 new): id, client_id, topic_id, product_name,
--   match_variants TEXT[], product_role, shadow_sub_role,
--   owner_brand_id, owner_peer_id, is_active.
-- geo_results: result_id, task_id, client_prompt_id, client_id, platform,
--   country, language, topic_name, product, ingested_at.
-- geo_client_prompts: id, client_id, topic_id, text, intent, product,
--   platform, country, language, is_active.
-- geo_global_intents: intent_name, categories JSONB, is_active.
--   Visibility metrics MUST filter prompts to categories containing
--   \"Visibility\" by joining geo_client_prompts.intent to
--   geo_global_intents.intent_name.""",
    "citation": """-- geo_citations: id, client_prompt_id, task_id, result_id, client_id,
--   source_url, source_domain, source_position (1=top), source_label,
--   is_citation_pill, domain_category,
--   citation_role TEXT (v1.2 new; 12 values: own_domain | own_product |
--     shadow_product_native | shadow_product_resale | shadow_product |
--     shadow_other | peer_product | peer_channel | earned | social |
--     agency | other),
--   matched_brand_id / matched_product_id / matched_peer_id (v1.2 new),
--   executed_at.
-- geo_client_domains: id, client_id, domain, is_primary,
--   domain_scope ('whole'|'path-prefix'),
--   brand_id (→geo_client_brands, NULL for Peer),
--   peer_id (→geo_client_peers, NULL for Own/Shadow).
-- geo_product_tracked_urls (v1.2 new): id, client_id, product_id, url,
--   url_scope ('exact'|'path-prefix'), brand_id, peer_id.
-- geo_results: result_id, task_id, client_prompt_id, client_id, platform,
--   country, language, topic_name, product, ingested_at.
-- geo_client_prompts: id, client_id, intent, is_active.
-- geo_global_intents: intent_name, categories JSONB, is_active.
--   Citation metrics MUST filter prompts to categories containing
--   \"Citation\" by joining geo_client_prompts.intent to
--   geo_global_intents.intent_name.""",
    "sentiment": """-- geo_sentiment_results: id, client_prompt_id, task_id, result_id, client_id,
--   sentiment ('Positive'|'Mixed/Neutral'|'Negative'|'Insufficient Evidence'),
--   confidence, classifier_version, model_id, reason_code, evidence, executed_at.
-- Overall percentages use a rated denominator containing Positive,
-- Mixed/Neutral, and Negative only; exclude Insufficient Evidence and report
-- its count separately.
-- geo_sentiment_themes: id, client_prompt_id, task_id, result_id, client_id,
--   theme_name, sentiment, excerpt, executed_at. Theme sentiment has exactly three values: Positive,
--   Mixed/Neutral, and Negative. It never uses Insufficient Evidence.
-- To break product sentiment out by role, JOIN geo_sentiment_results
-- against geo_product_mentions on (result_id, client_id) and GROUP BY
-- geo_product_mentions.product_role.
-- geo_client_prompts: id, client_id, intent, is_active.
-- geo_global_intents: intent_name, categories JSONB, is_active.
--   Sentiment metrics MUST filter prompts to categories containing
--   \"Sentiment\" by joining geo_client_prompts.intent to
--   geo_global_intents.intent_name.""",
}


# ─── Gemini helpers ───────────────────────────────────────────────────

async def _call_gemini(prompt: str, model_id: str | None = None, timeout: float = 180.0, retries: int = 3) -> str:
    """Call Gemini for SQL/insight generation with retry + exponential backoff.

    For DEADLINE_EXCEEDED / 504 errors, uses longer backoff (5s, 10s, 20s)
    since these indicate server-side overload.
    """
    if not model_id:
        model_id = await get_model_id("pro")
    client = await get_genai_client(model_id, role="pro")

    prompt_len = len(prompt)
    last_err = None
    for attempt in range(1, retries + 1):
        logger.info(f"[GEMINI] Calling {model_id} (prompt: {prompt_len} chars, attempt {attempt}/{retries})")
        try:
            response = await client.aio.models.generate_content(
                model=model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=8192,
                ),
            )
            result = response.text or ""
            logger.info(f"[GEMINI] Response received: {len(result)} chars")
            return result
        except Exception as e:
            last_err = e
            err_str = str(e)
            is_deadline = "DEADLINE_EXCEEDED" in err_str or "504" in err_str or "timeout" in err_str.lower()
            logger.warning(f"[GEMINI] Error on attempt {attempt}/{retries} (deadline={is_deadline}): {e}")
            if attempt < retries:
                # Longer backoff for deadline errors (server overload)
                backoff = (5 * attempt) if is_deadline else (2 ** attempt)
                logger.info(f"[GEMINI] Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
    raise RuntimeError(f"Gemini call failed after {retries} attempts: {last_err}")


# ─── Metric SQL Generation ───────────────────────────────────────────

METRIC_SQL_HEADER = """You are a PostgreSQL expert. Generate a read-only SELECT query for EACH metric below.

General rules:
- Use asyncpg-style positional params ($1, $2, $3). NEVER use named params.
- $1 = client_id (UUID text).
- $2 = range_start, a TIMESTAMPTZ representing the start-of-day for the first date in the requested window.
- $3 = range_end, a TIMESTAMPTZ representing the end-of-day (23:59:59.999999 UTC) for the last date in the window.
  This means `executed_at BETWEEN $2 AND $3` IS SAFE — it correctly includes
  events from the last date's full 24 hours. Do NOT manually cast $3 to
  `::date + INTERVAL '1 day'` — the server already handles this.
- DOD metrics must NOT use $2/$3. Find the two most recent dates directly from the table.
- Each SQL must return exactly ONE scalar value (or a Markdown table string for table metrics).
- Each SQL must end with a semicolon.
- Do NOT wrap $1/$2/$3 in quotes.

MANDATORY TENANT ISOLATION (zero-tolerance, SQL missing this will be rejected):
- EVERY generated SQL MUST contain `WHERE client_id = $1` (or an equivalent `AND client_id = $1`) on the primary FROM table.
- When joining multiple tables that all carry a `client_id` column, you SHOULD add `client_id = $1` on each, or ensure the join is constrained so the filter propagates.
- NEVER hardcode a literal UUID for client_id — always use $1.

MANDATORY ENUM LITERALS (case-sensitive — DB CHECK constraints will reject lower-case):
- `geo_sentiment_results.sentiment` is EXACTLY one of:
    'Positive'  'Mixed/Neutral'  'Negative'  'Insufficient Evidence'
- `geo_sentiment_themes.sentiment` is EXACTLY one of:
    'Positive'  'Mixed/Neutral'  'Negative'
- For sentiment percentages, use the rated denominator:
    COUNT(*) FILTER (WHERE sentiment <> 'Insufficient Evidence')
  Report Insufficient Evidence separately; never fold it into Mixed/Neutral.
- `geo_brand_mentions.brand_role` is EXACTLY one of:
    'own'  'shadow'  'peer'   (all lower-case)
- `geo_product_mentions.product_role` is EXACTLY one of:
    'own'  'shadow_brand_product'  'peer'   (NEVER 'owned' / 'owner' / 'own_brand')
- `geo_product_mentions.shadow_sub_role` is EXACTLY one of:
    'native'  'resale'  NULL
- To filter own-product themes/sentiment, JOIN through geo_product_mentions with
  `product_role = 'own' AND owner_brand_id IS NOT NULL` — unbound products are
  not verified customer products. NEVER use peer_id + LIMIT 1.

{platform_clause}
Return a JSON object: keys = metric variable_name, values = SQL string."""


def _build_platform_sql_clause(allowed_platforms: list[str]) -> str:
    """Construct the platform whitelist clause that the SQL-generation LLM
    must respect. If no whitelist is configured, the clause is empty and
    the pipeline falls back to the old unrestricted behaviour.

    Each platform string is SQL-escaped defensively even though the values
    originate from server-side config (``geo_clients.config_platforms`` /
    task widget). Defense in depth: prevents a compromised config column
    from injecting into the prompt.
    """
    if not allowed_platforms:
        return ""
    safe = [p.replace("'", "''") for p in allowed_platforms if p]
    if not safe:
        return ""
    in_list = ", ".join(f"'{p}'" for p in safe)
    return (
        "MANDATORY AI-PLATFORM WHITELIST (zero-tolerance, SQL missing this will be rejected):\n"
        f"- This analysis run is scoped to EXACTLY these AI platforms: [{in_list}].\n"
        "- EVERY generated SQL that references `geo_results` (directly or via JOIN) "
        f"MUST include `AND geo_results.platform IN ({in_list})` "
        "(alias the table as needed — the column name is `platform`).\n"
        "- When the FROM/JOIN chain does NOT touch `geo_results` but the metric "
        "is scoped to an AI-platform concept (e.g. platform-specific visibility), "
        "add a subquery `EXISTS (SELECT 1 FROM geo_results gr WHERE gr.result_id = <alias>.result_id "
        f"AND gr.client_id = $1 AND gr.platform IN ({in_list}))`.\n"
        "- NEVER introduce `platform` values outside this whitelist "
        "(e.g. perplexity / bing / copilot / claude / zhihu / xiaohongshu / weibo are forbidden "
        "unless they appear in the whitelist above).\n\n"
    )


async def _generate_all_metric_sqls_from_schema(
    metrics: list[dict], schema_text: str, nl2sql_model_id: str,
    allowed_platforms: list[str] | None = None,
) -> dict[str, str | None]:
    """Batch-generate metric SQL using live schema context (Agent-ized).

    Groups metrics by domain and runs concurrent Gemini calls for each batch.
    Uses the live schema_text from information_schema instead of hardcoded SCHEMA_HINTS.

    ``allowed_platforms`` is injected into the SQL-generation prompt as a
    mandatory AI-platform whitelist — see ``_build_platform_sql_clause``.
    """
    sql_map: dict[str, str | None] = {}

    platform_clause = _build_platform_sql_clause(allowed_platforms or [])
    metric_scope_rules = build_metric_category_scope_rules(
        list({m.get("domain", "visibility") for m in metrics})
    )
    header = METRIC_SQL_HEADER.format(platform_clause=platform_clause + metric_scope_rules)

    # Group by domain for batching
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for m in metrics:
        by_domain[m.get("domain", "visibility")].append(m)

    def _build_metric_block(m: dict) -> str:
        vname = m["variable_name"]
        is_dod = "_dod_" in vname or vname.endswith("_dod")
        params_note = "Use $1 only (self-compute dates)" if is_dod else "Use $1, $2, $3"
        return f"""### {vname}
Description: {m.get('description', '')}
Params: {params_note}"""

    async def _gen_single_metric(m: dict) -> dict[str, str | None]:
        """Generate SQL for a single metric (fallback when batch fails)."""
        block = _build_metric_block(m)
        prompt = header + f"\n\nLive Database Schema:\n{schema_text}\n\n" + block
        try:
            raw = await _call_gemini(prompt, nl2sql_model_id)
            raw = raw.strip().strip("```json").strip("```").strip()
            parsed = json.loads(raw)
            return {k: v for k, v in parsed.items() if isinstance(v, str)}
        except Exception as e:
            logger.warning(f"[ANALYSIS] Single metric SQL gen failed for {m['variable_name']}: {e}")
            return {}

    async def _gen_domain_batch(domain: str, group: list[dict]) -> dict[str, str | None]:
        blocks = [_build_metric_block(m) for m in group]
        prompt = header + f"\n\nLive Database Schema:\n{schema_text}\n\n" + "\n\n".join(blocks)
        try:
            raw = await _call_gemini(prompt, nl2sql_model_id)
            raw = raw.strip().strip("```json").strip("```").strip()
            parsed = json.loads(raw)
            return {k: v for k, v in parsed.items() if isinstance(v, str)}
        except Exception as e:
            logger.warning(f"[ANALYSIS] Batch SQL gen failed for {domain}: {e}, retrying metrics individually...")
            # Fallback: generate SQL for each metric individually
            individual_tasks = [_gen_single_metric(m) for m in group]
            individual_results = await asyncio.gather(*individual_tasks, return_exceptions=True)
            combined: dict[str, str | None] = {}
            for r in individual_results:
                if isinstance(r, dict):
                    combined.update(r)
            logger.info(f"[ANALYSIS] Individual fallback recovered {len(combined)}/{len(group)} metrics for {domain}")
            return combined

    tasks = [_gen_domain_batch(d, g) for d, g in by_domain.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, dict):
            sql_map.update(result)

    return sql_map


async def _execute_metric_sql(pool, sql: str, client_id: str, start_date: str, end_date: str) -> Any:
    """Execute a metric SQL query with parameter substitution.

    $2 / $3 are passed as **TIMESTAMPTZ** values (start-of-day / end-of-day
    in UTC) — NOT bare `date`. This fixes the midnight-truncation bug where
    `executed_at BETWEEN $2::date AND $3::date` silently excluded all events
    that occurred on `date_to` after 00:00:00.

    Concretely:
      $2 = date_from at 00:00:00.000000+00:00
      $3 = date_to   at 23:59:59.999999+00:00

    With these params, LLM-generated SQL patterns like
    `executed_at BETWEEN $2 AND $3` (common and natural) now cover the full
    date_to day. The SQL-gen prompt documents this contract in
    METRIC_SQL_HEADER.
    """
    from datetime import date as _date, datetime as _dt, timezone as _tz, timedelta as _td

    # Sanitize: named → positional
    sql = sql.replace(":client_id", "$1").replace(":start_date", "$2").replace(":end_date", "$3")
    # Remove quoted positional params
    sql = re.sub(r"'(\$\d+)'", r"\1", sql)
    sql = sql.rstrip(";").strip()

    # Zero-trust: reject metric SQL without $1 (client_id)
    if "$1" not in sql:
        logger.warning(f"[ANALYSIS] Metric SQL missing $1 client_id filter, refusing: {sql[:200]}")
        return None

    # Detect which params are actually referenced
    param_nums = [int(m) for m in re.findall(r'\$(\d+)', sql)]
    max_param = max(param_nums) if param_nums else 0

    def _to_date(val):
        if isinstance(val, _date):
            return val
        return _date.fromisoformat(str(val))

    args: list[Any] = [client_id]
    if max_param >= 2:
        d_from = _to_date(start_date)
        args.append(_dt.combine(d_from, _dt.min.time(), tzinfo=_tz.utc))
    if max_param >= 3:
        d_to = _to_date(end_date)
        # End-of-day = next midnight minus 1 microsecond → inclusive BETWEEN.
        args.append(
            _dt.combine(d_to + _td(days=1), _dt.min.time(), tzinfo=_tz.utc)
            - _td(microseconds=1)
        )

    try:
        rows = await asyncio.wait_for(
            pool.fetch(sql, *args),
            timeout=15.0,
        )
        if not rows:
            return None
        if len(rows) == 1 and len(rows[0]) == 1:
            return rows[0][0]
        # Multiple rows/columns → markdown table
        cols = list(rows[0].keys())
        lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
        for r in rows[:20]:
            lines.append("| " + " | ".join(str(r[c] or "") for c in cols) + " |")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[ANALYSIS] Metric SQL exec failed: {e}")
        return None


# ─── Chart Generation ─────────────────────────────────────────────────

async def _generate_chart_sql(
    nl_query: str, domains: list[str], client_id: str, model_id: str,
    schema_text: str = "",
    allowed_platforms: list[str] | None = None,
    sql_hint: str = "",
) -> str | None:
    """Generate SQL for a chart from a natural language query.

    Uses $1 parameterized client_id (never hardcoded literal) for security.
    Uses live schema_text when available, falls back to SCHEMA_HINTS.

    ``allowed_platforms`` — optional whitelist of AI platforms; when set,
    an extra mandatory rule is appended so the generated SQL restricts
    ``geo_results.platform`` to those values only (e.g. no perplexity / bing
    bleed-through even if the underlying data contains them).
    """
    allowed_tables = set()
    for d in domains:
        allowed_tables.update(ALLOWED_TABLES.get(d, []))

    # Prefer live schema, fall back to hints
    if not schema_text:
        schema_parts = []
        for d in domains:
            if d in SCHEMA_HINTS:
                schema_parts.append(SCHEMA_HINTS[d])
        schema_text = chr(10).join(schema_parts)

    platform_rule = ""
    if allowed_platforms:
        safe = [p.replace("'", "''") for p in allowed_platforms if p]
        if safe:
            in_list = ", ".join(f"'{p}'" for p in safe)
            platform_rule = (
                f"- MANDATORY: if the query touches `geo_results`, it MUST include "
                f"`AND geo_results.platform IN ({in_list})` (or equivalent alias). "
                f"NEVER introduce `platform` values outside this whitelist "
                f"(e.g. perplexity/bing/copilot/claude/zhihu are forbidden unless explicitly listed).\n"
            )

    metric_scope_rules = build_metric_category_scope_rules(domains)

    hint_block = ""
    if sql_hint:
        hint_block = f"""
REFERENCE SQL (你生成的 SQL 必须严格遵循此公式，仅需适配参数规则 $1 + recent-dates CTE):
{sql_hint}
"""

    prompt = f"""Generate a single PostgreSQL SELECT query for this chart question:
Question: {nl_query}

Available tables: {', '.join(sorted(allowed_tables))}
Schema:
{schema_text}
{hint_block}
Rules:
- CRITICAL: Every table must include WHERE client_id = $1 for tenant isolation. $1 is a UUID string.
- Do NOT use positional params beyond $1 (no $2, $3).
- Do NOT hardcode client_id as a literal UUID — always use $1.
- Do NOT use CURRENT_DATE/NOW(). Derive dates from the data itself using subqueries.
- Use a recent-dates CTE pattern: WITH recent_dates AS (SELECT DISTINCT DATE(executed_at) AS d FROM <table> WHERE client_id = $1 ORDER BY d DESC LIMIT 2)
- Do NOT use correlated subqueries (subqueries that reference columns from the outer query). Use CTEs or JOINs instead. PostgreSQL rejects correlated subqueries that reference outer GROUP BY columns.
- geo_sentiment_results.sentiment values are exactly 'Positive', 'Mixed/Neutral', 'Negative', or 'Insufficient Evidence'. Use the rated denominator (exclude Insufficient Evidence) for the first three percentages.
- When JOINing geo_sentiment_results with geo_brand_mentions (v1.2 rename of geo_company_mentions) or geo_product_mentions, use result_id + client_id as join keys (NOT task_id, which can be NULL).
- Return multiple rows suitable for charting (name/label column + value columns)
- LIMIT 200 max
- End with a semicolon
{platform_rule}
{metric_scope_rules}
Return ONLY the SQL, no explanation."""

    logger.info(f"[ANALYSIS] Chart SQL prompt length: {len(prompt)} chars, hint_block: {len(hint_block)} chars")
    raw = await _call_gemini(prompt, model_id)
    sql = raw.strip().strip("```sql").strip("```").strip()
    logger.info(f"[ANALYSIS] Chart generated SQL:\n{sql}")
    if not sql.upper().startswith(("SELECT", "WITH")):
        return None
    return sql


def _validate_client_id_filter(sql: str) -> tuple[bool, str]:
    """Verify that LLM-generated SQL contains client_id filtering.

    Zero-trust: we NEVER execute SQL that doesn't filter by client_id.
    Returns (ok, reason).
    """
    sql_upper = sql.upper()
    # Check for $1 parameterized client_id (preferred)
    if "$1" in sql and "CLIENT_ID" in sql_upper:
        return True, ""
    # Reject — no client_id filtering detected
    return False, "SQL missing client_id = $1 tenant filter. Refusing to execute."


async def _execute_chart_sql(pool, sql: str, client_id: str, allowed_domains: list[str]) -> dict | None:
    """Validate and execute chart SQL with mandatory client_id parameterization."""
    ok, reason = validate_sql_safety(sql, allowed_domains)
    if not ok:
        logger.warning(f"[ANALYSIS] Chart SQL safety fail: {reason}")
        return {"error": reason, "rows": []}

    # Zero-trust: reject SQL without client_id filtering
    ok, reason = _validate_client_id_filter(sql)
    if not ok:
        logger.warning(f"[ANALYSIS] Chart SQL client_id check fail: {reason}")
        return {"error": reason, "rows": []}

    sql = sql.rstrip(";").strip()

    try:
        rows = await asyncio.wait_for(
            pool.fetch(sql, client_id),
            timeout=15.0,
        )
        if not rows:
            return {"sql": sql, "columns": [], "rows": []}
        cols = list(rows[0].keys())
        data = [[r[c] for c in cols] for r in rows[:100]]
        return {"sql": sql, "columns": cols, "rows": data}
    except Exception as e:
        logger.warning(f"[ANALYSIS] Chart SQL exec failed: {e}")
        return {"error": str(e), "rows": []}


# ─── Chart / Evidence Chain formatting (Phase 1 Hole A) ─────────────

def _format_chart_rows_as_markdown(
    columns: list[str],
    rows: list[list[Any]],
    head_rows: int = 200,
    tail_rows: int = 200,
) -> str:
    """Render chart rows as a Markdown table.

    If row count exceeds ``head_rows + tail_rows``, keep head + tail with
    an elided notice in the middle. Threshold and label are both derived
    from ``head_rows + tail_rows`` so they stay in sync.
    """
    if not columns or not rows:
        return "_(no rows)_"

    def _cell(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (float, Decimal)):
            return str(round(float(v), 4))
        return str(v).replace("|", "\\|").replace("\n", " ")

    def _row_to_line(r: list[Any]) -> str:
        return "| " + " | ".join(_cell(c) for c in r) + " |"

    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, sep]

    elision_threshold = head_rows + tail_rows
    if len(rows) <= elision_threshold:
        lines.extend(_row_to_line(r) for r in rows)
    else:
        lines.extend(_row_to_line(r) for r in rows[:head_rows])
        elided = len(rows) - head_rows - tail_rows
        lines.append(f"| ... | _(省略中间 {elided} 行)_ |")
        lines.extend(_row_to_line(r) for r in rows[-tail_rows:])

    return "\n".join(lines)


def _format_chart_data_section(chart_results: list[dict]) -> str:
    """Phase 1 Hole A fix — render every chart's computed data as Markdown
    tables so the synthesis LLM can actually SEE the numbers instead of
    only receiving them in a separate frontend response.
    """
    if not chart_results:
        return ""

    parts: list[str] = ["", "## Chart Data (ground truth — every chart's full result set)", ""]
    for i, cr in enumerate(chart_results, start=1):
        title = cr.get("nl_query") or f"Chart {i}"
        chart_type = cr.get("chart_type", "auto")
        parts.append(f"### Chart {i}: {title}  _(type: {chart_type})_")

        if cr.get("error"):
            parts.append(f"_Error computing this chart:_ {cr['error']}")
            parts.append("")
            continue

        columns = cr.get("columns") or []
        rows = cr.get("rows") or []
        if not columns or not rows:
            parts.append("_(no rows returned)_")
            parts.append("")
            continue

        parts.append(_format_chart_rows_as_markdown(columns, rows))
        parts.append("")

    return "\n".join(parts)


def _format_evidence_chain_section(
    metric_sqls: dict[str, str],
    chart_results: list[dict],
    variable_values: dict[str, Any],
    date_from: str,
    date_to: str,
    contract_template_name: Optional[str],
) -> str:
    """Phase 1 Evidence Chain — a provenance preamble injected at the TOP of
    the synthesis prompt so the LLM explicitly sees which SQL queries
    produced the numbers it is about to reason over.

    The same text is shown to end users at the top of the report as a
    "数据依据" disclosure.
    """
    lines: list[str] = []
    lines.append("## 本次分析报告依赖的真实数据")
    lines.append("")
    if contract_template_name:
        lines.append(f"- 模板：{contract_template_name}（契约模式，指标列表由模板锁定）")
    lines.append(f"- 查询时间窗口：{date_from or '?'} ~ {date_to or '?'}（实际数据范围以各指标首行日期为准）")
    lines.append(f"- Metric SQL 数量：{len(metric_sqls)}")
    lines.append(f"- Chart SQL 数量：{sum(1 for c in chart_results if c.get('sql'))}")
    lines.append("")

    if metric_sqls:
        lines.append("### Metric 查询")
        lines.append("")
        for i, (vname, sql) in enumerate(metric_sqls.items(), start=1):
            val = variable_values.get(vname)
            if val is None:
                lines.append(f"**{i}. {vname}** — NULL")
                lines.append("")
            elif isinstance(val, (float, Decimal)):
                lines.append(f"**{i}. {vname}** — {round(float(val), 2)}")
                lines.append("")
            elif isinstance(val, str) and "|" in val and "\n" in val:
                # Markdown table — render as standalone block (tables can't nest in list items).
                table_lines = [ln for ln in val.splitlines() if "|" in ln.strip()]
                row_count = max(len(table_lines) - 2, 0)
                lines.append(f"**{i}. {vname}** — {row_count} 行数据")
                lines.append("")
                lines.append(val)
                lines.append("")
            else:
                lines.append(f"**{i}. {vname}** — {str(val)[:300]}")
                lines.append("")

    if chart_results:
        lines.append("### Chart 查询")
        for i, cr in enumerate(chart_results, start=1):
            title = cr.get("nl_query") or f"Chart {i}"
            row_count = len(cr.get("rows") or [])
            lines.append(f"{i}. {title} — 返回 {row_count} 行")
        lines.append("")

    lines.append(
        "以上指标数据来自真实数据库查询结果，报告中所有数字、百分比、排名均基于上述数据。"
    )
    lines.append("")
    return "\n".join(lines)


_H2_RE = re.compile(r"^##(?!#)\s+(.+)$", re.MULTILINE)
_FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _check_required_chapters(markdown: str, required_chapters: list[str]) -> tuple[list[str], list[str]]:
    """Scan the synthesized report for H2 headings matching the required
    chapter slugs. Returns (found, missing) — both lists of slug strings.

    Hardened against two false-positive sources:
      1. Fenced code blocks (```...```) that echo `## ...` inside are
         stripped before scanning so quoted headings don't count.
      2. Exactly-H2 discrimination — `### Foo` and `#### Foo` do NOT
         match (uses a regex with negative look-ahead on `#`).
    """
    if not required_chapters:
        return [], []

    scanned = _FENCED_BLOCK_RE.sub("", markdown or "")
    h2_titles = _H2_RE.findall(scanned)
    h2_blob = "\n".join(h2_titles).lower()

    found: list[str] = []
    missing: list[str] = []
    for slug in required_chapters:
        keywords = CHAPTER_HEADING_KEYWORDS.get(slug, [slug])
        hit = any(kw.lower() in h2_blob for kw in keywords)
        (found if hit else missing).append(slug)
    return found, missing


# ─── Prompt Hydration ─────────────────────────────────────────────────

def _hydrate_prompt(prompt: str, variables: dict[str, Any]) -> str:
    """Replace {{variable_name}} placeholders with computed values."""
    def replacer(match):
        vname = match.group(1)
        val = variables.get(vname)
        if val is None:
            return "N/A"
        if isinstance(val, (float, Decimal)):
            return str(round(float(val), 2))
        if isinstance(val, int):
            return str(val)
        return str(val)

    result = re.sub(r'\{\{(\w+)\}\}', replacer, prompt)
    result = result.replace("[Current Date]", datetime.now().strftime("%Y-%m-%d"))
    return result


# ─── Pipeline Steps ──────────────────────────────────────────────────

async def _resolve_allowed_platforms(pool, inputs: dict, client_id: str) -> list[str]:
    """Return the whitelist of AI platforms this analysis task is allowed to
    reference. Resolution order:

    1. ``inputs["platforms"]`` — explicitly selected in the Analyze wizard widget
    2. ``geo_clients.config_platforms`` — client-level configuration (fallback)
    3. Empty list — NO whitelist (legacy behaviour for ad-hoc chat entry)

    The returned list drives both SQL-level filtering (``geo_results.platform IN (...)``)
    and synthesis-level guardrails (the final report narrative may only mention
    these platform names).
    """
    raw = inputs.get("platforms")
    if isinstance(raw, list) and raw:
        return [str(p).strip() for p in raw if p and str(p).strip()]
    try:
        row = await pool.fetchrow(
            "SELECT config_platforms FROM geo_clients WHERE id = $1::uuid",
            client_id,
        )
        if row and row["config_platforms"]:
            return [str(p).strip() for p in row["config_platforms"] if p and str(p).strip()]
    except Exception as e:
        logger.warning(f"[ANALYSIS] Could not resolve client platforms: {e}")
    return []


async def step_validate_inputs(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Step 1: Validate inputs and check data availability.

    Dynamic date-anchor behavior (2026-04-20): if the requested
    ``date_to`` is today but the client has no data on today yet, we
    re-anchor the window to end on the latest date that DOES have data,
    preserving the requested window length. This means:

      - If cron runs at 6am before today's ingest → use yesterday as
        anchor, window = (anchor - N days, anchor).
      - If data already arrived at 10pm today → use today as anchor.

    Without this, any client viewing a "Last 7 Days" report after midnight
    but before the day's ingest would see an empty current-day column
    and confusing "No data" metrics.

    The input `date_from`/`date_to` are mutated in-place (stored back on
    the task's inputs downstream) so every subsequent step and the final
    report render reflect the actual data window used.
    """
    from datetime import date as _date, timedelta as _td

    domains = inputs.get("domains", [])
    date_from_str = inputs.get("date_from", "")
    date_to_str = inputs.get("date_to", "")

    if not domains:
        raise ValueError("至少需要选择一个数据领域")

    if not date_from_str or not date_to_str:
        raise ValueError("日期范围不能为空")

    date_from = _date.fromisoformat(date_from_str)
    date_to = _date.fromisoformat(date_to_str)

    # ── Dynamic anchor: if date_to == today and today has no data, shift
    # the window to end on the latest data date. Preserves window length.
    today = _date.today()
    if date_to >= today:
        latest_row = await pool.fetchrow(
            """
            SELECT GREATEST(
                COALESCE((SELECT MAX(executed_at)::date FROM geo_brand_mentions    WHERE client_id = $1::uuid), NULL),
                COALESCE((SELECT MAX(executed_at)::date FROM geo_citations         WHERE client_id = $1::uuid), NULL),
                COALESCE((SELECT MAX(executed_at)::date FROM geo_sentiment_results WHERE client_id = $1::uuid), NULL)
            ) AS latest
            """,
            client_id,
        )
        latest = latest_row["latest"] if latest_row else None
        if latest and latest < today:
            window_len = (date_to - date_from).days
            new_date_to = latest
            new_date_from = new_date_to - _td(days=window_len)
            await append_status_log(pool, task_id, {
                "step": 1, "event": "detail",
                "label": (
                    f"ℹ 日期锚点调整: 今日暂无数据, 自动将窗口移到最新可用日期 "
                    f"{date_from}~{date_to} → {new_date_from}~{new_date_to}"
                ),
            })
            date_from, date_to = new_date_from, new_date_to
            inputs["date_from"] = date_from.isoformat()
            inputs["date_to"] = date_to.isoformat()

    # Check each domain has data in the date range.
    # v1.2: visibility availability is anchored on geo_brand_mentions
    # (renamed from geo_company_mentions); product-only SKUs still emit
    # brand_mentions too, so this single table remains the right gate.
    domain_table_map = {
        "visibility": "geo_brand_mentions",
        "citation": "geo_citations",
        "sentiment": "geo_sentiment_results",
    }

    data_counts = {}
    for domain in domains:
        table = domain_table_map.get(domain)
        if not table:
            continue
        row = await pool.fetchrow(
            f"SELECT COUNT(*) AS cnt FROM {table} WHERE client_id = $1 AND executed_at >= $2::date AND executed_at <= ($3::date + INTERVAL '1 day')",
            client_id, date_from, date_to,
        )
        cnt = row["cnt"] if row else 0
        data_counts[domain] = cnt

        await append_status_log(pool, task_id, {
            "step": 1, "event": "detail",
            "label": f"{'✓' if cnt > 0 else '⚠'} {domain}: {cnt} 条数据记录",
        })

    # Warn (but don't fail) if some domains have no data
    empty_domains = [d for d, c in data_counts.items() if c == 0]
    if len(empty_domains) == len(domains):
        # Stale-range fallback (2026-04-21): when the entire requested window
        # has 0 data but newer data exists in DB (classic case: wizard default
        # end_date=yesterday ran right after midnight, but today's data is
        # already there), shift the window forward to cover the latest N days
        # ending at the latest available date. We only do this if the user's
        # date_to is strictly less than latest_data — otherwise keep the
        # original ValueError so we don't hide a genuinely-empty client.
        latest_row = await pool.fetchrow(
            """
            SELECT GREATEST(
                COALESCE((SELECT MAX(executed_at)::date FROM geo_brand_mentions    WHERE client_id = $1::uuid), NULL),
                COALESCE((SELECT MAX(executed_at)::date FROM geo_citations         WHERE client_id = $1::uuid), NULL),
                COALESCE((SELECT MAX(executed_at)::date FROM geo_sentiment_results WHERE client_id = $1::uuid), NULL)
            ) AS latest
            """,
            client_id,
        )
        latest = latest_row["latest"] if latest_row else None
        if latest and latest > date_to:
            window_len = (date_to - date_from).days
            new_date_to = latest
            new_date_from = new_date_to - _td(days=window_len)
            await append_status_log(pool, task_id, {
                "step": 1, "event": "detail",
                "label": (
                    f"ℹ 原窗口无数据，自动前移到最新可用日期 "
                    f"{date_from}~{date_to} → {new_date_from}~{new_date_to}"
                ),
            })
            date_from, date_to = new_date_from, new_date_to
            inputs["date_from"] = date_from.isoformat()
            inputs["date_to"] = date_to.isoformat()
            # Recount with shifted window.
            data_counts = {}
            for domain in domains:
                table = domain_table_map.get(domain)
                if not table:
                    continue
                row = await pool.fetchrow(
                    f"SELECT COUNT(*) AS cnt FROM {table} WHERE client_id = $1 AND executed_at >= $2::date AND executed_at <= ($3::date + INTERVAL '1 day')",
                    client_id, date_from, date_to,
                )
                data_counts[domain] = row["cnt"] if row else 0
            empty_domains = [d for d, c in data_counts.items() if c == 0]
        if len(empty_domains) == len(domains):
            raise ValueError(f"所有数据领域在 {date_from} ~ {date_to} 范围内均无数据，请调整日期范围")

    if empty_domains:
        await append_status_log(pool, task_id, {
            "step": 1, "event": "warning",
            "label": f"注意: {', '.join(empty_domains)} 在所选日期范围内无数据",
        })

    # Resolve the AI-platform whitelist once, propagate to all downstream steps.
    allowed_platforms = await _resolve_allowed_platforms(pool, inputs, client_id)
    if allowed_platforms:
        await append_status_log(pool, task_id, {
            "step": 1, "event": "detail",
            "label": f"✓ AI 平台范围锁定: {', '.join(allowed_platforms)}",
        })
        logger.info(f"[ANALYSIS] Allowed platforms whitelist: {allowed_platforms}")
    else:
        logger.info("[ANALYSIS] No platform whitelist (unrestricted mode)")

    return {
        "data_counts": data_counts,
        "allowed_platforms": allowed_platforms,
    }


async def _read_live_schema(pool, domains: list[str]) -> str:
    """Read live table schemas from information_schema for the requested domains."""
    tables = set()
    for d in domains:
        tables.update(ALLOWED_TABLES.get(d, []))
    # Always include reference tables
    tables.update({"geo_clients", "geo_client_peers", "geo_client_topics"})

    schema_parts = []
    for table_name in sorted(tables):
        rows = await pool.fetch(
            """SELECT column_name, data_type
               FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = $1
               ORDER BY ordinal_position""",
            table_name,
        )
        if rows:
            cols = ", ".join(f"{r['column_name']} ({r['data_type']})" for r in rows)
            schema_parts.append(f"-- {table_name}: {cols}")

    return "\n".join(schema_parts)


async def _discover_metrics_for_prompt(
    pool, prompt_text: str, domains: list[str], model_id: str,
) -> list[dict]:
    """Use Gemini to discover which metrics are needed for a prompt, given live schema.

    Returns a list of metric dicts: [{variable_name, display_name, domain, description}]
    """
    schema_text = await _read_live_schema(pool, domains)

    discover_prompt = f"""You are a GEO analytics expert. Given an analysis prompt and database schema,
identify the specific metrics that need to be computed to answer this prompt.

## Analysis Prompt
{prompt_text}

## Database Schema
{schema_text}

## Rules
1. Each metric must be computable from the tables above using a SELECT query.
2. Every query must join through geo_results/geo_tasks for client_id isolation.
3. Generate 5-15 metrics that directly address the analysis prompt.
4. variable_name must be unique snake_case identifiers.

## Output (JSON array):
[
  {{
    "variable_name": "brand_mention_rate",
    "display_name": "品牌提及率",
    "domain": "visibility",
    "description": "品牌在AI回答中被提及的比例"
  }}
]

Return ONLY the JSON array."""

    raw = await _call_gemini(discover_prompt, model_id)
    raw = raw.strip().strip("```json").strip("```").strip()
    return json.loads(raw)


async def step_hydrate_metrics(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Step 2: Resolve metrics and execute their SQL.

    Contract-mode dispatch:

    1. Try to load the template contract (via task_id → template_id →
       ``geo_report_templates.wizard_config``). If found and
       ``required_metrics`` is non-empty, look each metric up in
       ``geo_analysis_metrics`` and hand the resulting metric-dicts to
       the existing NL2SQL batch generator. This ensures every run of
       the same template computes the same locked-in set of metrics —
       no LLM free-styling variable names.

    2. Fall back to the legacy "dynamic schema discovery" path for the
       Custom Analysis template (empty contract) and for ad-hoc Chat
       entry points that never pass a template_id.
    """
    domains = inputs.get("domains", ["visibility", "citation", "sentiment"])
    prompt_text = inputs.get("prompt", "")
    date_from = inputs.get("date_from", "")
    date_to = inputs.get("date_to", "")
    model_id = inputs.get("model_id") or await get_model_id("pro")
    allowed_platforms = inputs.get("allowed_platforms") or []

    # Step 2a: Read live schema
    await append_status_log(pool, task_id, {
        "step": 2, "event": "detail",
        "label": "正在读取数据库 Schema...",
    })
    schema_text = await _read_live_schema(pool, domains)

    # Step 2b: Resolve metric list — contract mode first, dynamic fallback second
    contract, contract_template_name = await get_contract_for_task(pool, task_id)

    # NOTE: 自定义分析 (Custom Analysis) intentionally has empty `required_metrics`.
    # Metrics in geo_analysis_metrics are bound 1:N to `domain`, so once the
    # user picks `default_domains` in the data_selection step, the dynamic
    # discovery fallback below picks up exactly the metrics relevant to
    # those domains. There is NO separate metrics-selection step — an
    # earlier draft of migration 055 added one, then we walked it back
    # because metrics flow naturally from domains.
    used_contract = False
    metrics: list[dict[str, Any]] = []

    if contract and contract.get("required_metrics"):
        # DB-first: consult geo_analysis_metrics (Phase 2 table). Falls back
        # to the in-memory stub registry for any names the DB doesn't have
        # yet, so the pipeline runs correctly regardless of whether
        # migration 026 has executed.
        metrics = await build_metric_objects_from_contract_async(pool, contract)
        used_contract = len(metrics) > 0
        if used_contract:
            await append_status_log(pool, task_id, {
                "step": 2, "event": "detail",
                "label": (
                    f"✓ 契约模式：模板 《{contract_template_name}》 锁定 "
                    f"{len(metrics)} 个指标（{', '.join(m['variable_name'] for m in metrics)}）"
                ),
            })
            logger.info(
                f"[ANALYSIS] Contract mode active: template={contract_template_name} "
                f"metrics={[m['variable_name'] for m in metrics]}"
            )

    if not used_contract:
        # Fallback: dynamic discovery (Custom Analysis / Chat entry)
        await append_status_log(pool, task_id, {
            "step": 2, "event": "detail",
            "label": "无契约或自定义分析，走动态指标发现...",
        })
        if prompt_text:
            try:
                metrics = await _discover_metrics_for_prompt(pool, prompt_text, domains, model_id)
            except Exception as e:
                logger.warning(f"[ANALYSIS] Metric discovery failed: {e}, falling back to domain defaults")
                metrics = []
        else:
            metrics = []

        # If no metrics discovered (no prompt or discovery failed), generate domain defaults
        if not metrics:
            metrics = [
                {"variable_name": f"{d}_default", "display_name": d, "domain": d,
                 "description": f"Default metrics for {d}"}
                for d in domains
            ]

    await append_status_log(pool, task_id, {
        "step": 2, "event": "detail",
        "label": f"正在计算 {len(metrics)} 个指标...",
    })

    # Step 2c: Batch generate SQL for all discovered metrics (with live schema context)
    sql_map = await _generate_all_metric_sqls_from_schema(
        metrics, schema_text, model_id, allowed_platforms=allowed_platforms,
    )

    # Step 2d: Execute all metric SQLs in parallel
    variable_values: dict[str, Any] = {}

    # Collect generated SQLs for status log visibility
    generated_sqls: dict[str, str] = {}

    async def _compute_one(m: dict):
        vname = m["variable_name"]
        sql = sql_map.get(vname)
        if not sql:
            variable_values[vname] = None
            return
        # Patch LLM-hallucinated enum literal cases before validation /
        # execution. Lives here (not in _execute_metric_sql) so the fix
        # is visible in the generated_sqls audit log.
        sql = normalize_enum_literals(sql)
        generated_sqls[vname] = sql
        ok, reason = validate_sql_safety(sql, domains)
        if not ok:
            logger.warning(f"[ANALYSIS] Metric SQL unsafe ({vname}): {reason}")
            variable_values[vname] = None
            return
        val = await _execute_metric_sql(pool, sql, client_id, date_from, date_to)
        variable_values[vname] = val

    await asyncio.gather(*[_compute_one(m) for m in metrics])

    computed = sum(1 for v in variable_values.values() if v is not None)
    logger.info(f"[ANALYSIS] Hydrated {computed}/{len(variable_values)} metrics from live schema")

    # Detailed per-metric status log for debugging
    for m in metrics:
        vname = m["variable_name"]
        sql = sql_map.get(vname)
        val = variable_values.get(vname)
        if sql is None:
            logger.warning(f"[ANALYSIS]   metric {vname}: NO SQL generated by NL2SQL")
        elif val is None:
            logger.warning(f"[ANALYSIS]   metric {vname}: SQL generated but returned NULL")
            logger.info(f"[ANALYSIS]   metric {vname} SQL: {sql}")
        else:
            val_type = type(val).__name__
            val_preview = str(val)[:150]
            logger.info(f"[ANALYSIS]   metric {vname}: OK ({val_type}) {val_preview}")
            logger.info(f"[ANALYSIS]   metric {vname} SQL: {sql}")

    # Log generated SQLs so frontend can show them (tooltip/expandable)
    await append_status_log(pool, task_id, {
        "step": 2, "event": "sql_generated",
        "label": f"✓ 已生成 {len(generated_sqls)} 条 SQL，成功计算 {computed} 个指标",
        "sqls": {k: v for k, v in generated_sqls.items()},
    })

    # ─── Resolve DDPP analysis lenses (migration 029) ─────────────────
    # Priority: explicit user selection (wizard override) > contract default.
    user_selected_lenses = list(inputs.get("selected_lenses") or [])
    contract_default_lenses = list((contract or {}).get("default_lenses") or [])
    active_lens_keys = user_selected_lenses or contract_default_lenses

    analysis_lens_definitions: list[dict[str, Any]] = []
    if active_lens_keys:
        analysis_lens_definitions = await load_workflow_dictionary_rows(
            pool, "analysis_lens", "analysis", active_lens_keys,
        )
        if analysis_lens_definitions:
            lens_labels = ", ".join(d["label"] for d in analysis_lens_definitions)
            source_tag = "用户选择" if user_selected_lenses else "模板默认"
            await append_status_log(pool, task_id, {
                "step": 2, "event": "detail",
                "label": f"✓ 分析框架（{source_tag}）：{lens_labels}",
            })
            logger.info(
                "[ANALYSIS] Analysis framework locked: source=%s lenses=%s",
                "user" if user_selected_lenses else "template",
                [d["key"] for d in analysis_lens_definitions],
            )

    include_data_disclosure = bool(
        (contract or {}).get("include_data_disclosure", True)
    )

    return {
        "variable_values": variable_values,
        "model_used": model_id,
        # Phase 1: surface generated SQLs + contract info to downstream
        # steps so Evidence Chain (Step 4) and chapter check (Step 5)
        # can consume them without re-querying.
        "metric_sqls": dict(generated_sqls),
        "contract_template_name": contract_template_name if used_contract else None,
        "contract_required_chapters": (contract.get("required_chapters") if contract else []) or [],
        # Migration 029: DDPP lens definitions + data disclosure flag,
        # consumed by step_synthesize_report to build the hard-constraint
        # Analytical Framework block.
        "analysis_lens_definitions": analysis_lens_definitions,
        "include_data_disclosure": include_data_disclosure,
    }


async def step_generate_charts(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Step 3: Generate chart data from NL chart requests."""
    chart_requests = inputs.get("chart_requests", [])
    domains = inputs.get("domains", ["visibility", "citation", "sentiment"])
    model_id = inputs.get("model_id") or await get_model_id("pro")
    allowed_platforms = inputs.get("allowed_platforms") or []

    if not chart_requests:
        return {"chart_results": []}

    # Read live schema for chart SQL generation
    schema_text = await _read_live_schema(pool, domains)

    chart_results = []
    for i, req in enumerate(chart_requests):
        nl_query = req.get("nl_query", "")
        chart_type = req.get("chart_type", "auto")
        sql_hint = req.get("sql_hint", "")

        if not nl_query:
            continue

        logger.info(f"[ANALYSIS] Chart {i}: sql_hint={'YES (' + str(len(sql_hint)) + ' chars)' if sql_hint else 'EMPTY'}")

        await append_status_log(pool, task_id, {
            "step": 3, "event": "chart_progress",
            "label": f"生成图表 {i + 1}/{len(chart_requests)}: {nl_query[:50]}...",
        })

        sql = await _generate_chart_sql(
            nl_query, domains, client_id, model_id,
            schema_text=schema_text, allowed_platforms=allowed_platforms,
            sql_hint=sql_hint,
        )
        if not sql:
            chart_results.append({
                "index": i,
                "nl_query": nl_query,
                "chart_type": chart_type,
                "error": "Failed to generate SQL",
                "rows": [],
            })
            continue

        result = await _execute_chart_sql(pool, sql, client_id, domains)
        if not result or result.get("error"):
            chart_results.append({
                "index": i,
                "nl_query": nl_query,
                "chart_type": chart_type,
                "error": result.get("error", "Execution failed") if result else "No result",
                "sql": sql,
                "rows": [],
            })
            continue

        chart_results.append({
            "index": i,
            "nl_query": nl_query,
            "chart_type": chart_type,
            "sql": result.get("sql", ""),
            "columns": result.get("columns", []),
            "rows": result.get("rows", []),
        })

    # Log chart SQLs for frontend expandable display (like Step 2)
    chart_sqls = {}
    for cr in chart_results:
        if cr.get("sql"):
            label = cr.get("nl_query", f"chart_{cr.get('index', 0)}")[:60]
            chart_sqls[label] = cr["sql"]

    if chart_sqls:
        await append_status_log(pool, task_id, {
            "step": 3, "event": "sql_generated",
            "label": f"✓ 已生成 {len(chart_sqls)} 条图表 SQL",
            "sqls": chart_sqls,
        })

    logger.info(f"[ANALYSIS] Generated {len(chart_results)} charts")
    return {"chart_results": chart_results}


SYNTHESIS_SYSTEM_GUARDRAILS_TEMPLATE = """严格规则（必须遵守）：
1. 所有数字、百分比、排名、趋势方向必须来自 "## Computed Data" 或 "## Chart Data" 章节的真实数据表格。
2. 不允许引用这两个章节之外的任何数字或趋势方向。
3. 引用来源 (citation source) 只能使用 "## Chart Data" 表格中某一列的值，例如 source_domain 列里真实出现过的 domain 字符串。不允许引用诸如 "知乎"、"微博"、"小红书" 等未在表格数据行中出现的平台。
4. 特别注意：`### Chart N: <标题>` 中的标题是用户提出的自然语言问题，**不是数据**。不得从 chart 标题中抽取平台名或来源名作为事实。
{platform_rule}6. 若某个本应有数据的维度 (visibility / citation / sentiment) 在 "## Computed Data" 和 "## Chart Data" 的数据行中均无任何数字，必须明确声明 "该维度本次采样内无数据"，不得基于训练知识补全。
7. **不要**自行撰写 "## 本次分析报告依赖的真实数据" 或 "## 数据依据" 章节 — 系统会在最终输出时自动注入该部分。直接从正文分析章节开始。
8. 如果上下文中存在 "## 分析框架 (Analytical Framework) — 硬约束" 章节，必须严格按照该章节列出的每一条 DDPP Lens，为其生成一个 H2 章节（标题必须同时包含中文名与英文名），并且每一节的结论都只能由 "## Computed Data" 与 "## Chart Data" 的真实数据推导得出。不得省略任何 Lens，也不得额外新增 Lens 之外的大章节。
9. **禁止交叉维度推算**：如果 "## Computed Data" 中没有某个交叉维度的数据（例如只有整体情感分布，没有按品牌拆分的情感数据），不得自行拆分、推算或编造该交叉维度的具体数字。只能引用数据表格中真实存在的行和列。如果需要但缺少某个维度的数据，应声明 "本次采样未包含该维度的细分数据"。
10. **禁止编造评分或打分**：不得生成任何 "xx/100"、"xx 分"、"Score: xx" 等量化评分。数据中没有评分模型就不能创造评分。可以使用定性评价词（如"优秀"、"良好"、"需改善"），但不得附加具体数值分数。
11. **Computed Data 优先于 Chart Data**：当 "## Computed Data" 和 "## Chart Data" 对同一指标（如 SOV、引用率）给出数值时，以 Computed Data 为准。Chart Data 的时间范围可能与本次分析的采样窗口不一致（chart 查询自动取最近可用数据，可能超出采样窗口）。引用 Chart Data 中的数字时，必须注明是 "趋势数据" 或 "图表数据"，且不得与 Computed Data 中的汇总数字混淆或矛盾。
12. **禁止无依据的绝对量词**：不得使用 "所有"、"全部"、"100%"、"唯一"、"没有任何" 等绝对量词，除非数据表格中 **字面上** 只有单一条目或数值为 0/100%。例如：若品牌 A 有 11 条负面、品牌 B 有 2 条负面，不得说 "品牌 A 承受了所有负面评价"。应说 "品牌 A 占负面评价的大多数（11/14，78.6%）"。
"""


def _build_analysis_framework_block(
    lens_definitions: list[dict[str, Any]],
) -> str:
    """Build the HARD-CONSTRAINT Analytical Framework section that locks
    the report's top-level structure to the selected Gartner DDPP lenses.

    Returns an empty string when no lenses are configured (Custom Analysis
    / legacy chat entry), in which case the existing guardrails (rules 1-7)
    remain the only constraints.

    The block:
      - Lists every active lens with its bilingual label + description.
      - Requires one H2 section per lens, in the order given.
      - Maps each DDPP level to its intended narrative job (what / why /
        what's next / what to do) so the LLM cannot collapse two lenses
        into one section.
      - Explicitly forbids fabricated metrics and reiterates the evidence
        discipline — redundant with rules 1-7, but GEO reports regress
        easily, so we repeat it where the LLM is most likely to look.
    """
    if not lens_definitions:
        return ""

    # Narrative job per DDPP level — pinned by lens key so renaming a
    # label in the DB does not break the hint map.
    _LENS_JOB = {
        "descriptive":  "回答「现状是什么」 — 用真实数据呈现当前 Visibility / Citation / Sentiment 的水位与基线",
        "diagnostic":   "回答「为什么会这样」 — 用数据差异解释平台 / 竞品 / 时间维度上的差距与根因",
        "predictive":   "回答「接下来会怎样」 — 只基于 Computed Data 与 Chart Data 中的时序信号做前瞻判断，不得引入训练知识",
        "prescriptive": "回答「我们应该做什么」 — 输出可执行的优化动作与下一步优先级，每条建议必须绑定到前面章节里真实出现过的数据点",
    }

    lines: list[str] = [
        "## 分析框架 (Analytical Framework) — 硬约束",
        "",
        (
            "本次分析报告必须严格遵循 Gartner DDPP 四级分析法中 **本次模板勾选的以下 Lens**，"
            "为每一个 Lens 生成恰好一个 H2 章节。章节顺序、数量、标题、叙述职责均由本框架锁定："
        ),
        "",
    ]
    for idx, d in enumerate(lens_definitions, start=1):
        key = d.get("key", "")
        label = d.get("label", key)
        desc = d.get("description", "")
        job = _LENS_JOB.get(key, "按该 Lens 的定义展开分析")
        lines.append(f"{idx}. **H2 章节 `## {label}`**")
        lines.append(f"   - Lens 定义：{desc}")
        lines.append(f"   - 叙述职责：{job}")
        lines.append(
            "   - 数据约束：本节引用的所有数字、比例、排名、方向必须来自 "
            "\"## Computed Data\" 或 \"## Chart Data\"；找不到数据时必须明说 "
            "\"该维度本次采样内无数据\"，不得编造。"
        )
    lines += [
        "",
        (
            "**结构硬性要求（禁止偏离）：**"
        ),
        (
            "- 上述 H2 章节必须完整出现，一节不少、一节不多（报告最开头的 "
            "\"## 本次分析报告依赖的真实数据\" 披露章节与末尾可选的 \"## 附录\" 除外）。"
        ),
        (
            "- 每个 H2 章节的标题必须完整照抄中文名与英文名（例如 "
            "`## 描述性分析 (Descriptive)`），不得改写、翻译或省略括号中的英文。"
        ),
        (
            "- 严禁把两个 Lens 合并进同一节，严禁新增本框架之外的大章节"
            "（可以在一个 Lens 下面加 H3 子节）。"
        ),
        (
            "- 如果本次数据不足以支撑某个 Lens（例如只勾了 Predictive 但时序不足），"
            "在该节明确声明 \"本次采样不支持此 Lens 的数据推断\"，并点到为止，不得凭训练知识补全。"
        ),
        "",
    ]
    return "\n".join(lines)


def _build_data_disclosure_directive(include: bool) -> str:
    """Return the runtime directive that toggles the data disclosure
    chapter at the top of the report.

    When ``include`` is True (default), reinforce rule 7. When False, allow
    the LLM to skip the disclosure chapter — used for template previews or
    client-facing polished reports that strip provenance sections.
    """
    if include:
        return (
            "**数据依据披露：** 系统会在报告最终输出时自动注入「## 本次分析报告依赖的真实数据」章节，"
            "你**不需要**自己撰写数据依据/数据来源章节。直接从分析 Lens 或正文章节开始即可。"
            "所有数字仍必须来自 \"## Computed Data\" / \"## Chart Data\"，不得自行编造。\n"
        )
    return (
        "**数据依据披露：** 本次模板已关闭数据依据披露章节。报告可以直接从分析 "
        "Lens 章节开始，但所有数字仍必须来自 \"## Computed Data\" / "
        "\"## Chart Data\"，不得自行编造。\n"
    )


def _build_platform_narrative_rule(allowed_platforms: list[str]) -> str:
    """Construct guardrail rule #5 — the platform whitelist that bounds the
    final report narrative.

    CONTRACT: the returned string MUST start with "5." and end with "\\n".
    SYNTHESIS_SYSTEM_GUARDRAILS_TEMPLATE relies on this contract to preserve
    the numbering of rules 6 and 7. Both branches below are asserted at the
    end of the function so the pipeline fails loudly if a future edit breaks
    the contract.

    When the caller provides an explicit whitelist (task widget or client
    config), the rule names exactly those platforms and explicitly forbids
    everything else. When no whitelist is available (legacy unrestricted
    ad-hoc chat entry), fall back to a conservative generic rule.
    """
    if allowed_platforms:
        listed = "、".join(allowed_platforms)
        rule = (
            f"5. **AI 平台白名单（强约束）**：本次分析只覆盖以下 AI 平台：[{listed}]。\n"
            f"   - 报告正文中一切关于 \"AI 平台\"、\"AI engine\"、\"AI 搜索\" 的描述、对比、结论、"
            f"建议，都只能使用白名单里的名字（{listed}）。\n"
            f"   - **严禁** 引入白名单之外的任何 AI 平台，例如 perplexity、bing、copilot、claude、"
            f"you.com、kimi、metaso、秘塔、doubao、豆包、文心一言、通义 等都必须视为 \"非本次范围\"。\n"
            f"   - **严禁** 把非 AI 搜索类内容平台（例如 知乎、微博、小红书、抖音、B 站、今日头条、"
            f"百度、Google Search、Bing Search）错误地归类为 \"AI 平台\" 或 \"AI mode\"。它们可以作为"
            f" citation source 在 \"## Chart Data\" 真实列值里出现，但**绝不能**被描述成本次分析的 AI 平台。\n"
            f"   - 若 \"## Computed Data\" / \"## Chart Data\" 里的数据恰好包含白名单之外的 platform 值"
            f"（理论上不应该发生——SQL 已经过滤），必须忽略那些行，不得纳入分析结论。\n"
        )
    else:
        rule = (
            "5. **AI 平台白名单**：本次分析未显式指定 AI 平台白名单，请只基于 \"## Computed Data\" "
            "与 \"## Chart Data\" 表格中 platform 列真实出现过的值进行叙述，不得凭训练知识补充其他 AI 平台。\n"
        )

    # Contract enforcement — see docstring.
    assert rule.startswith("5."), (
        "platform_rule must start with '5.' to keep SYNTHESIS_SYSTEM_GUARDRAILS_TEMPLATE "
        "numbering (rules 6 and 7) consistent."
    )
    assert rule.endswith("\n"), (
        "platform_rule must end with a newline so rule 6 starts on its own line in "
        "SYNTHESIS_SYSTEM_GUARDRAILS_TEMPLATE."
    )
    return rule


async def step_synthesize_report(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Step 4: Hydrate prompt with metrics and generate insights via LLM.

    Phase 1 Hole A fix — the hydrated prompt now contains THREE injected
    sections in this order:
      1. Evidence Chain preamble (provenance disclosure + anti-fabrication)
      2. Computed Data (metric values)
      3. Chart Data (full chart rows as Markdown tables)

    Supports two prompt styles (unchanged):
    - Legacy: prompts with {{variable_name}} placeholders → replaced inline
    - Agent-ized: prompts with descriptive hints → computed data appended as section
    """
    prompt_text = inputs.get("prompt", "")
    variable_values = inputs.get("variable_values", {})
    model_id = inputs.get("model_id") or await get_model_id("pro")
    chart_results = inputs.get("chart_results", [])
    metric_sqls = inputs.get("metric_sqls", {}) or {}
    contract_template_name = inputs.get("contract_template_name")
    date_from = inputs.get("date_from", "")
    date_to = inputs.get("date_to", "")
    allowed_platforms = inputs.get("allowed_platforms") or []
    # Migration 029 — DDPP analytical framework + data disclosure toggle
    # surfaced from step_hydrate_metrics (read from template wizard_config
    # or overridden by the user in the wizard).
    lens_definitions = inputs.get("analysis_lens_definitions") or []
    include_data_disclosure = bool(inputs.get("include_data_disclosure", True))

    # Assemble guardrails with DYNAMIC rule 5 based on the per-task AI
    # platform whitelist. See _build_platform_narrative_rule for the
    # fallback behaviour when no whitelist is configured.
    platform_rule = _build_platform_narrative_rule(allowed_platforms)
    synthesis_guardrails = SYNTHESIS_SYSTEM_GUARDRAILS_TEMPLATE.format(
        platform_rule=platform_rule,
    )

    # Build the Analytical Framework hard-constraint block (empty string
    # when no lenses are locked, e.g. Custom Analysis or ad-hoc chat).
    framework_block = _build_analysis_framework_block(lens_definitions)
    disclosure_directive = _build_data_disclosure_directive(include_data_disclosure)

    if not prompt_text:
        prompt_text = "Based on the data provided, generate a comprehensive GEO analysis report."

    # Evidence Chain preamble (placed at the FRONT of the hydrated prompt)
    evidence_chain = _format_evidence_chain_section(
        metric_sqls=metric_sqls,
        chart_results=chart_results,
        variable_values=variable_values,
        date_from=date_from,
        date_to=date_to,
        contract_template_name=contract_template_name,
    )

    # Check if prompt has {{variable_name}} placeholders (legacy style)
    has_placeholders = bool(re.findall(r'\{\{(\w+)\}\}', prompt_text))

    if has_placeholders:
        # Legacy path: replace placeholders inline, then append structured sections
        user_prompt = _hydrate_prompt(prompt_text, variable_values)
    else:
        user_prompt = prompt_text

    # Computed Data section (metric values)
    # Tables get their own ### subsection so the LLM can parse them as
    # proper markdown tables; scalar values stay as bullet points.
    data_lines: list[str] = []
    for vname, val in variable_values.items():
        if val is None:
            data_lines.append(f"- **{vname}**: NULL (数据缺失，不得在报告中编造)")
        elif isinstance(val, (float, Decimal)):
            data_lines.append(f"- **{vname}**: {round(float(val), 2)}")
        elif isinstance(val, str) and "|" in val and "\n" in val:
            # Markdown table — render as a subsection, not a bullet point
            data_lines.append(f"\n### {vname}\n{val}\n")
        else:
            data_lines.append(f"- **{vname}**: {val}")
    computed_data_section = "\n".join(data_lines) if data_lines else "(no metric data computed)"

    # Chart Data section (full rows)
    chart_data_section = _format_chart_data_section(chart_results)

    # Assemble the final hydrated prompt.
    # Order is load-bearing for the LLM:
    #   1. Evidence chain (where the data came from)
    #   2. Guardrails (what the LLM must not do)
    #   3. Analytical Framework block (what H2 sections must exist)
    #   4. Data disclosure directive (whether to echo the disclosure chapter)
    #   5. User prompt (template-specific narrative instructions)
    #   6. Ground-truth data tables
    framework_section = f"{framework_block}\n" if framework_block else ""
    hydrated = (
        f"{evidence_chain}\n"
        f"{synthesis_guardrails}\n"
        f"{framework_section}"
        f"{disclosure_directive}\n"
        f"---\n\n"
        f"{user_prompt}\n\n"
        f"## Computed Data (ground truth — do not fabricate)\n"
        f"{computed_data_section}\n"
        f"{chart_data_section}"
    )

    logger.info(
        f"[ANALYSIS] Synthesize: hydrated prompt {len(hydrated)} chars, "
        f"{len(variable_values)} variables, {len(chart_results)} charts, "
        f"placeholders={has_placeholders}, contract={bool(contract_template_name)}, "
        f"lenses={len(lens_definitions)}, disclosure={include_data_disclosure}, model={model_id}"
    )

    # Detailed variable-level log for debugging data injection
    for vname, val in variable_values.items():
        val_preview = str(val)[:200] if val is not None else "NULL"
        val_type = type(val).__name__
        logger.info(f"[ANALYSIS]   var {vname} ({val_type}): {val_preview}")
    for i, cr in enumerate(chart_results):
        row_count = len(cr.get("rows") or [])
        logger.info(
            f"[ANALYSIS]   chart[{i}] {cr.get('nl_query','?')}: "
            f"{row_count} rows, cols={cr.get('columns', [])}"
        )

    await append_status_log(pool, task_id, {
        "step": 4, "event": "detail",
        "label": "Anthony 正在合成洞察报告...",
    })

    # Log the final hydrated prompt so frontend can show it
    await append_status_log(pool, task_id, {
        "step": 4, "event": "hydrated_prompt",
        "label": f"✓ 已组装最终 Prompt（{len(hydrated)} 字符）",
        "prompt": hydrated,
    })

    insights_markdown = await _call_gemini(hydrated, model_id, timeout=180.0)

    logger.info(f"[ANALYSIS] Report synthesized: {len(insights_markdown)} chars")
    return {
        "insights_markdown": insights_markdown,
        "chart_results_final": chart_results,
        "variable_values_final": variable_values,
        "prompt_used": prompt_text,
        "evidence_chain_preamble": evidence_chain,
    }


async def step_quality_check(pool, task_id: str, inputs: dict, client_id: str) -> dict:
    """Step 5: LLM audit for data accuracy and hallucination detection.

    Phase 1 Hole C addition — also validates that the report contains
    all H2 chapters listed in the template contract's ``required_chapters``.
    Missing chapters do not fail the task; instead a prominent warning is
    prepended to the report and recorded in ``quality_score.chapter_coverage``.
    """
    insights_markdown = inputs.get("insights_markdown", "")
    variable_values = inputs.get("variable_values_final", inputs.get("variable_values", {}))
    chart_results = inputs.get("chart_results_final", inputs.get("chart_results", []))
    required_chapters = inputs.get("contract_required_chapters") or []
    lens_definitions = inputs.get("analysis_lens_definitions") or []
    model_id = inputs.get("model_id") or await get_model_id("pro")

    if not insights_markdown:
        return {"_output": {
            "charts": chart_results,
            "insights_markdown": "",
            "variables": variable_values,
            "prompt_used": inputs.get("prompt_used", ""),
            "quality_score": None,
        }}

    # Phase 1 Hole C — chapter coverage check
    # When DDPP lenses are active, rule 8 of the guardrails overrides the
    # report structure to use lens-named H2 sections (描述分析 / 诊断分析 /
    # 预测分析 / 处方分析) instead of domain-named chapters (可见度 / 引用 /
    # 情感).  Skip the domain-chapter check in that case — the DDPP block
    # already enforces structural completeness.
    if lens_definitions:
        chapters_found, chapters_missing = list(required_chapters), []
    else:
        chapters_found, chapters_missing = _check_required_chapters(insights_markdown, required_chapters)
    if required_chapters:
        logger.info(
            f"[ANALYSIS] Chapter check: required={required_chapters} "
            f"found={chapters_found} missing={chapters_missing}"
        )
        await append_status_log(pool, task_id, {
            "step": 5, "event": "detail",
            "label": (
                f"✓ 章节完整" if not chapters_missing
                else f"⚠ 缺失章节: {', '.join(chapters_missing)}"
            ),
        })
        if chapters_missing:
            warning_block = (
                "> ⚠️ **数据完整性警告**：本模板要求报告覆盖章节 "
                f"`{', '.join(required_chapters)}`，但合成结果仅出现了 "
                f"`{', '.join(chapters_found) or '无'}`，缺失 "
                f"`{', '.join(chapters_missing)}`。上游数据或模型输出可能不完整，"
                "请结合原始数据核对后再做结论。\n\n"
            )
            insights_markdown = warning_block + insights_markdown

    # Build a concise data reference for the auditor — include BOTH metric
    # values AND chart data so the auditor does not flag chart-derived claims
    # as hallucinated.
    data_ref_lines = []
    for vname, val in variable_values.items():
        if val is not None:
            data_ref_lines.append(f"- {vname}: {val}")
    metric_ref = "\n".join(data_ref_lines[:50]) if data_ref_lines else "(no metric data)"

    chart_ref_lines = []
    for cr in chart_results:
        if not cr.get("rows"):
            continue
        title = cr.get("nl_query") or cr.get("chart_type", "chart")
        cols = cr.get("columns", [])
        rows = cr.get("rows", [])
        chart_ref_lines.append(f"\n### Chart: {title}")
        if cols:
            chart_ref_lines.append("| " + " | ".join(str(c) for c in cols) + " |")
            chart_ref_lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for row in rows[:20]:  # cap to avoid bloating the audit prompt
            chart_ref_lines.append("| " + " | ".join(str(v) for v in row) + " |")
        if len(rows) > 20:
            chart_ref_lines.append(f"... ({len(rows)} rows total)")
    chart_ref = "\n".join(chart_ref_lines) if chart_ref_lines else ""

    audit_prompt = f"""You are a data quality auditor. Review the following analysis report and verify its claims against the source data.

## Source Data — Metrics (ground truth)
{metric_ref}

## Source Data — Charts (ground truth)
{chart_ref or "(no chart data)"}

## Report to Audit
{insights_markdown[:6000]}

## Instructions
1. Check each numerical claim in the report against the source data values above.
2. Identify any hallucinated numbers (values not found in or derivable from source data).
3. Check for logical consistency (e.g., percentages that don't add up, contradictory statements).
4. Rate the overall data accuracy on a 1-5 scale.

Return a JSON object with this exact structure:
{{
  "data_accuracy_score": <1-5>,
  "consistency_score": <1-5>,
  "completeness_score": <1-5>,
  "overall_score": <1-5>,
  "issues": ["issue1", "issue2"],
  "summary": "One sentence summary of quality assessment"
}}

Return ONLY the JSON, no markdown fences."""

    await append_status_log(pool, task_id, {
        "step": 5, "event": "detail",
        "label": "正在进行报告质量评审...",
    })

    try:
        raw = await _call_gemini(audit_prompt, model_id)
        raw = raw.strip().strip("```json").strip("```").strip()
        quality_result = json.loads(raw)
    except Exception as e:
        logger.warning(f"[ANALYSIS] Quality check parse failed: {e}")
        quality_result = {
            "data_accuracy_score": None,
            "overall_score": None,
            "summary": "质量评审解析失败",
            "issues": [],
        }

    # Phase 1 — attach chapter coverage result so frontend + audit trail
    # know whether the contract's required_chapters were satisfied.
    quality_result["chapter_coverage"] = {
        "required": list(required_chapters),
        "found": chapters_found,
        "missing": chapters_missing,
        "ok": not chapters_missing,
    }
    if chapters_missing and quality_result.get("issues") is not None:
        quality_result["issues"].insert(
            0, f"缺失模板必需章节: {', '.join(chapters_missing)}"
        )

    # Migration 029 — Analytical Framework lens coverage check.
    # The framework block forces one H2 per Gartner DDPP lens, and every
    # H2 title must contain the lens's full bilingual label (e.g.
    # "描述性分析 (Descriptive)"). We verify coverage on a lowercased
    # substring match so incidental whitespace / punctuation drift
    # doesn't produce false misses. Missing lenses trigger a warning
    # block but do not fail the task.
    lens_found: list[str] = []
    lens_missing: list[str] = []
    if lens_definitions:
        lowered = insights_markdown.lower()
        for d in lens_definitions:
            key = d.get("key", "")
            label = (d.get("label") or "").strip()
            # Match on either the full bilingual label or — as a fallback —
            # the English token alone (in case the LLM dropped the Chinese).
            english_hint = ""
            if "(" in label and ")" in label:
                english_hint = label[label.find("(") + 1 : label.find(")")].strip().lower()
            matched = (
                (label and label.lower() in lowered)
                or (english_hint and english_hint in lowered)
            )
            (lens_found if matched else lens_missing).append(key)

        logger.info(
            "[ANALYSIS] Framework lens check: required=%s found=%s missing=%s",
            [d.get("key") for d in lens_definitions], lens_found, lens_missing,
        )
        await append_status_log(pool, task_id, {
            "step": 5, "event": "detail",
            "label": (
                f"✓ Analytical Framework 覆盖完整 "
                f"({len(lens_found)}/{len(lens_definitions)} Lens)"
                if not lens_missing
                else f"⚠ 缺失 Analytical Framework Lens: {', '.join(lens_missing)}"
            ),
        })
        if lens_missing:
            lens_warning = (
                "> ⚠️ **Analytical Framework 警告**：本模板锁定了 "
                f"`{', '.join(d.get('key','') for d in lens_definitions)}` "
                f"共 {len(lens_definitions)} 个 DDPP 分析视角，"
                f"但报告中缺失 `{', '.join(lens_missing)}` 对应的 H2 章节。"
                "可能是上游数据不足或模型未遵循框架约束，请结合原始数据复核。\n\n"
            )
            insights_markdown = lens_warning + insights_markdown
            if quality_result.get("issues") is not None:
                quality_result["issues"].insert(
                    0, f"缺失 Analytical Framework Lens: {', '.join(lens_missing)}"
                )

    quality_result["framework_coverage"] = {
        "required": [d.get("key") for d in lens_definitions],
        "found": lens_found,
        "missing": lens_missing,
        "ok": not lens_missing,
    }

    # Programmatically prepend the evidence chain (provenance disclosure)
    # so full data tables are always shown — never relying on LLM to copy.
    include_data_disclosure = bool(inputs.get("include_data_disclosure", True))
    evidence_chain = inputs.get("evidence_chain_preamble", "")
    if include_data_disclosure and evidence_chain:
        # Strip any LLM-generated disclosure section (in case it ignored rule 7).
        # Match with or without ## heading, at any position in the text.
        insights_markdown = re.sub(
            r"(?:^|\n)#{0,3}\s*(?:本次分析报告依赖的真实数据|数据依据)\s*\n[\s\S]*?(?=\n##\s|\Z)",
            "",
            insights_markdown,
        ).strip()
        insights_markdown = evidence_chain + "\n---\n\n" + insights_markdown

    # Build final output
    final_output = {
        "charts": chart_results,
        "insights_markdown": insights_markdown,
        "variables": variable_values,
        "prompt_used": inputs.get("prompt_used", ""),
        "quality_score": quality_result,
    }

    logger.info(f"[ANALYSIS] Quality check complete: {quality_result.get('overall_score')}/5")
    return {"_output": final_output}


# ─── Pipeline definition & registration ──────────────────────────────

ANALYSIS_STEPS = [
    WorkflowStep(1, "validate_inputs", "输入校验", step_validate_inputs),
    WorkflowStep(2, "hydrate_metrics", "指标水合", step_hydrate_metrics),
    WorkflowStep(3, "generate_charts", "图表生成", step_generate_charts),
    WorkflowStep(4, "synthesize_report", "报告合成", step_synthesize_report),
    WorkflowStep(5, "quality_check", "质量评审", step_quality_check),
]


async def run_analysis_pipeline(task_id: str, inputs: dict, client_id: str):
    """Entry point for analysis background task."""
    await run_pipeline(task_id, ANALYSIS_STEPS, inputs, client_id)


# Register with task router
register_pipeline("analysis", run_analysis_pipeline)
