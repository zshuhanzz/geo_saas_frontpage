"""
Tier 1 Atomic Data Tools for geo_agent.

NL2SQL architecture:
  1. Schema introspection tools (list_tables, list_columns) give LLM context
  2. LLM generates SQL from user's natural language + schema
  3. execute_sql runs the query with tenant isolation + safety checks

All tools are @tenant_scoped: client_id is enforced on every invocation.
SQL uses asyncpg positional params ($1, $2, ...) — never string interpolation.
"""
import re
import logging
from typing import Optional
from langchain_core.tools import tool
from middleware.tenant import tenant_scoped
from database import get_pool

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Safety: allowed tables and forbidden operations
# ─────────────────────────────────────────────────────────────

# Tables that the agent is allowed to query (all geo_ analytics tables).
# v1.2 dual-mode tracking: geo_company_mentions renamed to geo_brand_mentions,
# plus 6 new product / brand / candidate / tracked-url / sales-channel tables.
ALLOWED_TABLES = {
    # Analyzer output
    "geo_brand_mentions",
    "geo_product_mentions",
    "geo_citations",
    "geo_domain_categories",
    "geo_sentiment_results",
    "geo_sentiment_themes",
    "geo_sentiment_theme_dictionary",
    # Execution
    "geo_results",
    "geo_tasks",
    "geo_client_prompts",
    # Client config
    "geo_clients",
    "geo_client_brands",
    "geo_client_peers",
    "geo_client_domains",
    "geo_client_topics",
    "geo_client_topic_products",
    "geo_product_sales_channels",
    "geo_product_tracked_urls",
    "geo_settings_candidates",
    "geo_brand_profiles",
    "geo_global_intents",
}

# Regex to detect forbidden DDL/DML operations
FORBIDDEN_SQL_RE = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b',
    re.IGNORECASE,
)

# Max rows returned to prevent memory issues
MAX_ROWS = 500

# Query timeout (milliseconds)
QUERY_TIMEOUT_MS = 15_000


def validate_sql(sql: str) -> tuple[bool, str]:
    """Validate that SQL is safe to execute.

    Checks:
    1. Must be a SELECT statement (no DDL/DML)
    2. Only references allowed tables
    3. Must contain client_id filter (tenant isolation)

    Returns (is_safe, error_reason).
    """
    if not sql or not sql.strip():
        return False, "Empty SQL"

    # Check for forbidden operations
    if FORBIDDEN_SQL_RE.search(sql):
        return False, "SQL contains forbidden write/admin operations"

    # Check it starts with SELECT or WITH (CTE)
    stripped = sql.strip().lstrip(";").strip()
    if not re.match(r'^(SELECT|WITH)\b', stripped, re.IGNORECASE):
        return False, "SQL must start with SELECT or WITH"

    # Check only allowed tables are referenced (extract from FROM/JOIN clauses)
    # 1. Catch geo_ tables explicitly
    geo_tables = set(re.findall(r'\b(geo_\w+)\b', sql, re.IGNORECASE))
    forbidden_geo = geo_tables - ALLOWED_TABLES
    if forbidden_geo:
        return False, f"SQL references forbidden tables: {forbidden_geo}"

    # 2. Catch any non-geo table in FROM/JOIN clauses
    from_join_tables = set(re.findall(
        r'(?:FROM|JOIN)\s+(\w+)', sql, re.IGNORECASE
    ))
    # Filter out subquery aliases, CTEs, and allowed tables
    suspicious = {t for t in from_join_tables if not t.startswith("geo_") and t.lower() not in (
        "select", "with", "lateral", "unnest", "generate_series",
    )}
    if suspicious:
        return False, f"SQL references non-geo tables: {suspicious}"

    return True, ""


# ─────────────────────────────────────────────────────────────
# 1. List Tables
# ─────────────────────────────────────────────────────────────

@tool
async def list_tables(client_id: str) -> dict:
    """List all available analytics tables in the database.

    Returns table names and their descriptions. Use this to understand
    what data is available before generating SQL queries.

    Args:
        client_id: The tenant's client UUID (required for access control).
    """
    return await _list_tables_impl(client_id)


@tenant_scoped
async def _list_tables_impl(client_id: str) -> dict:
    pool = await get_pool()

    sql = """
        SELECT
            t.table_name,
            pg_catalog.obj_description(c.oid, 'pg_class') AS table_comment
        FROM information_schema.tables t
        LEFT JOIN pg_catalog.pg_class c ON c.relname = t.table_name
        WHERE t.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND t.table_name LIKE 'geo_%'
        ORDER BY t.table_name
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    # Only return allowed tables, with human-readable descriptions
    TABLE_DESCRIPTIONS = {
        # ─── Analyzer output ─────────────────────────────────────────────
        "geo_brand_mentions": "Brand mentions extracted from AI engine responses (v1.2 renamed from geo_company_mentions). Has brand_name, brand_role ('own' | 'shadow' | 'peer'), mention_position, executed_at.",
        "geo_product_mentions": "Product-level mentions extracted from AI engine responses (v1.2). Has product_id, product_name, product_role ('own' | 'shadow_brand_product' | 'peer'), shadow_sub_role ('native' | 'resale' | NULL), owner_brand_id, owner_brand_name, owner_peer_id, owner_peer_name, mention_position, executed_at.",
        "geo_citations": "Citation sources (URLs/domains) found in AI engine responses. Has source_url, source_domain, source_position, domain_category, citation_role ('own_domain' | 'own_product' | 'shadow_product_native' | 'shadow_product_resale' | 'shadow_product' | 'shadow_other' | 'peer_product' | 'peer_channel' | 'earned' | 'social' | 'agency' | 'other'), matched_brand_id, matched_product_id, matched_peer_id, executed_at.",
        "geo_sentiment_results": "Sentiment analysis results per response. Overall labels are Positive, Mixed/Neutral, Negative, or Insufficient Evidence. Has sentiment, confidence, classifier_version, model_id, reason_code, evidence, executed_at. Exclude Insufficient Evidence from Positive/Mixed/Negative percentage denominators.",
        "geo_sentiment_themes": "Sentiment themes extracted from rated responses. Theme labels are Positive, Mixed/Neutral, or Negative. Has theme_name, sentiment, excerpt, executed_at.",
        "geo_sentiment_theme_dictionary": "Dictionary of known sentiment themes. Has theme_name, industry, description.",
        "geo_domain_categories": "Domain categorization (e.g. 'Official', 'Review Site'). Has domain, category.",
        # ─── Execution ───────────────────────────────────────────────────
        "geo_results": "Raw AI engine responses. Has result_id, task_id, client_id, platform, topic_name, text, ingested_at.",
        "geo_tasks": "Data collection tasks. Has task_id, client_id, platform, topic_name, country, language, intent, status, created_at.",
        "geo_client_prompts": "Prompt templates sent to AI engines. Has text, intent, product, platform, country, language.",
        # ─── Client config ───────────────────────────────────────────────
        "geo_clients": "Client/tenant info. Has name, aliases, config_platforms, config_countries, onboarding_wizard_completed.",
        "geo_client_brands": "Own + Shadow brands (v1.2). Has brand_name, aliases, is_shadow (bool — true for Shadow Brand / OEM distributor, false for Own), is_active.",
        "geo_client_peers": "Competitor definitions. Has primary_name, aliases. (v1.2: is_own_brand column dropped — a peer that is also a Shadow Brand is recorded in geo_client_brands with is_shadow=true; use that table to distinguish.)",
        "geo_client_domains": "Client-scoped domains (Own / Shadow / Peer) with attribution metadata. Has domain, is_primary, domain_scope ('whole' | 'path-prefix'), brand_id (FK→geo_client_brands.id, NULL for Peer), peer_id (FK→geo_client_peers.id, NULL for Own/Shadow).",
        "geo_client_topics": "Client topics — SEMANTIC themes / topic clusters (not product lines) that a client monitors across AI search engines. Each topic groups related products, queries, and analyses under one monitoring umbrella. Has topic_name, topic_type ('semantic_topic' default, 'product_line' legacy). (v1.2: products TEXT[] column dropped — products now live in geo_client_topic_products.)",
        "geo_client_topic_products": "Product rows under a topic (v1.2). Has topic_id, product_name, match_variants TEXT[], product_role ('own' | 'shadow_brand_product' | 'peer'), shadow_sub_role ('native' | 'resale' | NULL, only set when product_role='shadow_brand_product'), owner_brand_id (FK→geo_client_brands.id; required for shadow_brand_product and marks a reviewed own product), owner_peer_id (FK→geo_client_peers.id, required for peer). Unbound own products are not verified sentiment targets.",
        "geo_product_sales_channels": "Composite-key table declaring which Shadow Brand sells which product (v1.2). Has product_id, brand_id, notes. No surrogate PK — PRIMARY KEY (product_id, brand_id).",
        "geo_product_tracked_urls": "Product-level tracked URLs for attribution (v1.2). Has product_id, url, url_scope ('exact' | 'path-prefix'), brand_id (FK→geo_client_brands.id, NULL for Peer), peer_id (FK→geo_client_peers.id, NULL for Own/Shadow).",
        "geo_settings_candidates": "AI-discovered candidate Brand / Product / URL rows pending admin review (v1.2). Has candidate_string, candidate_type ('brand' | 'shadow_brand' | 'peer' | 'own_product' | 'shadow_product' | 'peer_product' | 'tracked_url'), source ('n_gram' | 'llm_batch' | 'auto_discovery'), frequency, status ('pending' | 'accepted' | 'rejected' | 'ignored'), sample_response_ids INT[].",
        "geo_brand_profiles": "Brand voice profiles. Has brand_name, tone_of_voice, target_audience, key_messages.",
        "geo_global_intents": "Global Intent Prompt configuration. Join geo_client_prompts.intent to geo_global_intents.intent_name and filter categories JSONB by metric scope: Visibility, Citation, or Sentiment.",
    }

    tables = []
    for row in rows:
        name = row["table_name"]
        if name in ALLOWED_TABLES:
            tables.append({
                "table_name": name,
                "description": TABLE_DESCRIPTIONS.get(name, row["table_comment"] or ""),
            })

    return {"tables": tables}


# ─────────────────────────────────────────────────────────────
# 2. List Columns
# ─────────────────────────────────────────────────────────────

@tool
async def list_columns(client_id: str, table_name: str) -> dict:
    """List all columns for a specific table, including data types.

    Use this to understand the schema of a table before writing SQL.

    Args:
        client_id: The tenant's client UUID (required for access control).
        table_name: The table to inspect (must be a geo_ table).
    """
    return await _list_columns_impl(client_id, table_name)


@tenant_scoped
async def _list_columns_impl(client_id: str, table_name: str) -> dict:
    # Safety: only allow inspecting geo_ tables
    if table_name not in ALLOWED_TABLES:
        return {"error": f"Table '{table_name}' is not accessible. Allowed: {sorted(ALLOWED_TABLES)}"}

    pool = await get_pool()

    sql = """
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
        ORDER BY ordinal_position
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, table_name)

    columns = [
        {
            "name": r["column_name"],
            "type": r["data_type"],
            "nullable": r["is_nullable"] == "YES",
        }
        for r in rows
    ]

    # Also provide sample values for key columns to help LLM write accurate SQL
    sample_info = {}
    if table_name == "geo_brand_mentions":
        sample_info["note"] = (
            "v1.2: use brand_role column. 'own' = the client's own brand; "
            "'shadow' = an OEM/distributor brand the client sells through; "
            "'peer' = a competitor. NOTE for Peer SOV queries: a brand that "
            "is both Shadow and Peer is only emitted as brand_role='shadow' "
            "by the parser, so filtering by brand_role='peer' alone under-"
            "counts Peer SOV. Prefer an EXISTS check against geo_client_peers "
            "by name/alias (see Peer SOV calculation_hint in geo_analysis_metrics)."
        )
    elif table_name == "geo_product_mentions":
        sample_info["note"] = (
            "product_role: 'own' (own product), 'shadow_brand_product' (product "
            "sold on a Shadow Brand channel; shadow_sub_role distinguishes "
            "'native' vs 'resale'), 'peer' (a competitor's product). "
            "owner_brand_name / owner_peer_name are denormalized from the "
            "owning brand/peer at analyzer write time for fast GROUP BY."
        )
    elif table_name == "geo_citations":
        sample_info["note"] = (
            "domain_category examples: 'Official', 'Review', 'News', 'Forum', "
            "'E-commerce'. v1.2: use citation_role for attribution semantics "
            "(own_domain, own_product, shadow_product_native, shadow_product_"
            "resale, shadow_product, shadow_other, peer_product, peer_channel, "
            "earned, social, agency, other). matched_brand_id / matched_"
            "product_id / matched_peer_id point at the attributed owner."
        )
    elif table_name == "geo_client_brands":
        sample_info["note"] = "is_shadow=false for Own brand, true for Shadow (OEM/distributor) brand."
    elif table_name == "geo_client_domains":
        sample_info["note"] = (
            "domain_scope='whole' matches the entire host, 'path-prefix' "
            "matches a URL prefix. Exactly one of brand_id (→geo_client_brands) "
            "or peer_id (→geo_client_peers) is set; both NULL means client-"
            "level domain not yet attributed to a specific brand/peer."
        )
    elif table_name == "geo_client_topic_products":
        sample_info["note"] = (
            "product_role='own' means the client's own product; owner_brand_id "
            "must be non-NULL before treating it as a verified sentiment target, "
            "and owner_peer_id stays NULL. 'shadow_brand_product' requires "
            "owner_brand_id (→geo_client_brands with is_shadow=true) and may "
            "optionally set shadow_sub_role ('native' = first-party SKU on "
            "that channel; 'resale' = the client's own SKU resold on that "
            "channel; NULL = not yet classified). 'peer' requires owner_peer_id."
        )
    elif table_name == "geo_product_tracked_urls":
        sample_info["note"] = (
            "url_scope='exact' matches the canonical URL; 'path-prefix' matches "
            "any URL starting with this prefix. Exactly one of brand_id or "
            "peer_id is set."
        )
    elif table_name == "geo_sentiment_results":
        sample_info["note"] = (
            "overall sentiment is 'Positive', 'Mixed/Neutral', 'Negative', or "
            "'Insufficient Evidence'; theme sentiment excludes Insufficient Evidence. "
            "Use only non-Insufficient rows as the Positive/Mixed/Negative rate "
            "denominator and report Insufficient Evidence separately. For Sentiment reports, "
            "join geo_client_prompts on client_prompt_id/client_id and "
            "geo_global_intents on intent_name = cp.intent, then require "
            "gi.is_active = true AND gi.categories @> '[\"Sentiment\"]'::jsonb."
        )
    elif table_name == "geo_global_intents":
        sample_info["note"] = (
            "categories is JSONB containing enabled metric scopes. Use "
            "gi.categories @> '[\"Visibility\"]'::jsonb for Visibility, "
            "@> '[\"Citation\"]'::jsonb for Citation, and "
            "@> '[\"Sentiment\"]'::jsonb for Sentiment."
        )
    elif table_name == "geo_tasks":
        sample_info["note"] = "platform examples: 'chatgpt', 'gemini', 'aimode'. status: 'PENDING', 'COMPLETED'"
    elif table_name == "geo_results":
        sample_info["note"] = "Join via result_id to geo_brand_mentions, geo_product_mentions, geo_citations, geo_sentiment_results"

    return {
        "table_name": table_name,
        "columns": columns,
        **sample_info,
    }


# ─────────────────────────────────────────────────────────────
# 3. Execute SQL
# ─────────────────────────────────────────────────────────────

@tool
async def execute_sql(client_id: str, sql: str, params: Optional[list] = None) -> dict:
    """Execute a read-only SQL query against the analytics database.

    IMPORTANT: The SQL MUST include a WHERE client_id = $1 filter for
    tenant isolation. The client_id parameter ($1) is always injected
    automatically as the first positional parameter.

    Args:
        client_id: The tenant's client UUID (auto-injected as $1).
        sql: The SELECT query to execute. Must reference $1 for client_id.
        params: Optional additional positional parameters ($2, $3, ...).
    """
    return await _execute_sql_impl(client_id, sql, params)


@tenant_scoped
async def _execute_sql_impl(client_id: str, sql: str, params: Optional[list] = None) -> dict:
    # Validate SQL safety
    is_safe, reason = validate_sql(sql)
    if not is_safe:
        return {"error": f"SQL validation failed: {reason}", "sql": sql}

    # Enforce tenant isolation: SQL must reference $1 (client_id)
    if "$1" not in sql:
        return {
            "error": "SQL must include $1 placeholder for client_id (tenant isolation)",
            "sql": sql,
        }

    # Build params: $1 is always client_id
    all_params = [client_id] + (params or [])

    # Add LIMIT if not present
    if not re.search(r'\bLIMIT\b', sql, re.IGNORECASE):
        sql = sql.rstrip().rstrip(";") + f" LIMIT {MAX_ROWS}"

    pool = await get_pool()

    try:
        async with pool.acquire() as conn:
            # Set statement timeout for safety
            await conn.execute(f"SET statement_timeout = {QUERY_TIMEOUT_MS}")
            rows = await conn.fetch(sql, *all_params)
            # Reset timeout
            await conn.execute("RESET statement_timeout")

        # Convert to list of dicts
        results = [dict(r) for r in rows]

        # Serialize non-JSON-friendly types
        from decimal import Decimal
        for row in results:
            for k, v in row.items():
                if isinstance(v, Decimal):
                    row[k] = float(v)
                elif hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
                elif isinstance(v, (bytes, memoryview)):
                    row[k] = str(v)

        return {
            "row_count": len(results),
            "columns": list(results[0].keys()) if results else [],
            "rows": results,
            "sql": sql.strip(),
        }

    except Exception as e:
        logger.error(f"[SQL] Execution error: {e}")
        return {"error": str(e), "sql": sql}
