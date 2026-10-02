"""
Template Contract Resolution (v1.2)
===================================

Resolves analysis / content template contracts from the DB-first source
of truth (``geo_report_templates.wizard_config`` JSONB + the rewritten
``geo_analysis_metrics`` registry seeded by migration 046).

History
-------
In Phase 1 (before dual-mode tracking) this logic lived in an in-memory
stub (``_template_contracts_stub.py``) that mirrored the DB shape so the
pipelines could run before migrations 026/029 landed. The stub hard-coded
legacy schema (``geo_company_mentions`` / ``is_own_brand`` / ``company_name``)
in its reference SQL. Phase 4 of the v1.2 rollout deletes that stub; the
DB is now the single source of truth for metric metadata and template
wizard_config.

Public API
----------
* ``get_contract_for_task(pool, task_id)`` — resolves contract from a
  running task's ``template_id`` by reading
  ``geo_report_templates.wizard_config``.
* ``build_metric_objects_from_contract_async(pool, contract)`` — batch
  loads metric metadata from ``geo_analysis_metrics`` for the contract's
  ``required_metrics`` list.
* ``load_workflow_dictionary_rows(pool, config_type, scope, keys)`` —
  fetches ``geo_workflow_config`` dictionary rows (analysis lenses,
  content metrics, sub-goals) preserving input key order.
* ``CHAPTER_HEADING_KEYWORDS`` — fuzzy-match keywords used by the
  analysis pipeline chapter check.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Chapter slug → canonical H2 heading keyword (used by the chapter check).
# The check is fuzzy: the regex ".*keyword.*" must match an H2 line.
CHAPTER_HEADING_KEYWORDS: dict[str, list[str]] = {
    "visibility": ["可见度", "Visibility", "visibility"],
    "citation":   ["引用", "Citation", "citation"],
    "sentiment":  ["情感", "Sentiment", "sentiment"],
}


async def get_contract_for_task(pool, task_id: str) -> tuple[Optional[dict], Optional[str]]:
    """Look up the contract for a running analysis/content task.

    v1.2 DB-only resolution (the Phase 1 in-memory stub was removed):

    1. Query ``geo_agent_tasks.template_id`` by task_id.
    2. Query ``geo_report_templates`` for both ``name`` and
       ``wizard_config``.
    3. If ``wizard_config`` is a non-empty dict containing
       ``required_metrics`` and/or ``required_chapters``, project those
       fields into the standard contract shape and return them.
    4. Otherwise, return ``(None, template_name)`` — the caller falls
       back to its own "dynamic discovery" path (no hard contract).

    Returns ``(contract_dict_or_None, template_name_or_None)``.
    """
    row = await pool.fetchrow(
        "SELECT template_id FROM geo_agent_tasks WHERE id = $1::uuid",
        task_id,
    )
    if not row or not row["template_id"]:
        return None, None

    template_id = row["template_id"]
    tmpl_row = await pool.fetchrow(
        "SELECT name, wizard_config FROM geo_report_templates WHERE id = $1::uuid",
        template_id,
    )
    if not tmpl_row:
        return None, None

    template_name = tmpl_row["name"]
    wc = tmpl_row["wizard_config"]

    # asyncpg decodes JSONB as a dict automatically, but if the column is
    # declared NULL or server-decoded into a string, be defensive.
    if isinstance(wc, str):
        try:
            import json as _json
            wc = _json.loads(wc)
        except Exception:
            wc = None

    if not (isinstance(wc, dict) and wc):
        logger.info(
            "[CONTRACT] Template %r has empty wizard_config; caller falls back "
            "to dynamic discovery.",
            template_name,
        )
        return None, template_name

    required_metrics = wc.get("required_metrics") or []
    required_chapters = wc.get("required_chapters") or []

    if not (required_metrics or required_chapters):
        logger.info(
            "[CONTRACT] Template %r wizard_config has no required_metrics or "
            "required_chapters; caller falls back to dynamic discovery.",
            template_name,
        )
        return None, template_name

    # Migration 029 additions — schema-driven wizard step defaults.
    steps = wc.get("steps") or {}
    analysis_framework_cfg = (steps.get("analysis_framework") or {})
    prompt_edit_cfg = (steps.get("prompt_edit") or {})
    content_framework_cfg = (steps.get("content_framework") or {})
    output_cfg = (steps.get("output_config") or {})
    content_goal_cfg = (steps.get("content_goal") or {})
    generation_cfg = (steps.get("generation_config") or {})

    default_lenses = list(analysis_framework_cfg.get("default_lenses") or [])
    default_content_metrics = list(
        content_goal_cfg.get("default_metrics")
        or content_framework_cfg.get("default_metrics")
        or []
    )
    default_content_subgoals = list(
        content_goal_cfg.get("default_sub_goals")
        or content_framework_cfg.get("default_sub_goals")
        or []
    )
    # Data disclosure flag — analysis templates store it under prompt_edit,
    # content templates under generation_config (current) or output_config
    # (legacy). Default to TRUE so the data-accuracy guardrail is safe.
    include_data_disclosure = bool(
        prompt_edit_cfg.get("include_data_disclosure")
        if "include_data_disclosure" in prompt_edit_cfg
        else generation_cfg.get(
            "include_data_disclosure",
            output_cfg.get("include_data_disclosure", True),
        )
    )
    disable_user_edit = bool(prompt_edit_cfg.get("disable_user_edit", False))

    logger.info(
        "[CONTRACT] Resolved contract from DB wizard_config: "
        "template=%r metrics=%d chapters=%d lenses=%s disclosure=%s",
        template_name, len(required_metrics), len(required_chapters),
        default_lenses, include_data_disclosure,
    )
    return (
        {
            "required_metrics": list(required_metrics),
            "required_chapters": list(required_chapters),
            "required_subgoals": list(wc.get("required_subgoals") or []),
            "default_lenses": default_lenses,
            "default_content_metrics": default_content_metrics,
            "default_content_subgoals": default_content_subgoals,
            "include_data_disclosure": include_data_disclosure,
            "disable_user_edit": disable_user_edit,
            "_source": "db_wizard_config",
        },
        template_name,
    )


async def build_metric_objects_from_contract_async(
    pool, contract: dict,
) -> list[dict[str, Any]]:
    """Batch-load metric metadata from ``geo_analysis_metrics`` for every
    ``metric_name`` in the contract's ``required_metrics`` list.

    Shape of each returned dict is consumed by
    ``_generate_all_metric_sqls_from_schema`` in analysis_pipeline.py::

        {
            "variable_name":   <metric_name>,
            "display_name":    <display_name_zh>,
            "domain":          <visibility|citation|sentiment|custom>,
            "description":     <calculation_hint>,  # fed as NL2SQL description
            "relevant_tables": [...],
            "null_behavior":   <return_null|return_zero|raise>,
        }

    Unknown metric names (not active in ``geo_analysis_metrics``) are
    silently dropped but logged at WARNING so template authors notice
    registry drift.
    """
    metric_names = list(contract.get("required_metrics") or [])
    if not metric_names:
        return []

    try:
        rows = await pool.fetch(
            """
            SELECT metric_name, display_name_zh, domain, description,
                   calculation_hint, relevant_tables, null_behavior
            FROM geo_analysis_metrics
            WHERE metric_name = ANY($1::text[])
              AND is_active = true
            """,
            metric_names,
        )
    except Exception as e:
        # geo_analysis_metrics table missing or transient DB error: this is
        # unrecoverable post-v1.2 (no stub fallback). Log + return empty so
        # the caller's dynamic-discovery path runs and produces *something*
        # rather than crashing the whole analysis task.
        logger.error(
            "[CONTRACT] DB metric lookup failed (%s); returning empty metric "
            "list so dynamic discovery can take over.",
            e,
        )
        return []

    by_name: dict[str, dict[str, Any]] = {r["metric_name"]: dict(r) for r in rows}

    out: list[dict[str, Any]] = []
    dropped: list[str] = []
    for metric_name in metric_names:
        db_row = by_name.get(metric_name)
        if not db_row:
            dropped.append(metric_name)
            continue
        out.append({
            "variable_name":    metric_name,
            "display_name":     db_row["display_name_zh"],
            "domain":           db_row["domain"],
            "description":      db_row["calculation_hint"],
            "relevant_tables":  list(db_row.get("relevant_tables") or []),
            "null_behavior":    db_row.get("null_behavior") or "return_null",
        })

    if dropped:
        logger.warning(
            "[CONTRACT] Unknown metric names silently dropped (not in "
            "geo_analysis_metrics or inactive): %s. Either seed them or "
            "update the template wizard_config.",
            dropped,
        )
    return out


async def load_workflow_dictionary_rows(
    pool,
    config_type: str,
    scope: str,
    keys: list[str],
) -> list[dict[str, Any]]:
    """Fetch dictionary rows (``analysis_lens`` / ``content_metric`` /
    ``content_sub_goal`` etc.) from ``geo_workflow_config`` for the given
    keys, preserving the input key order and dropping unknown keys.

    Each returned dict has the shape::

        {
            "key":         "descriptive",
            "label":       "描述性分析 (Descriptive)",
            "description": "现状梳理 — 呈现 Visibility ...",
            "parent_key":  "",  # empty for terminal rows
        }

    ``label`` and ``description`` come from the row's JSONB ``value``
    column (not ``key``). This is the single source of truth for the
    bilingual text the pipelines inject into LLM prompts as hard
    constraints.
    """
    if not keys:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT key, parent_key, value
            FROM geo_workflow_config
            WHERE config_type = $1
              AND scope = $2
              AND key = ANY($3::text[])
              AND is_active = true
            """,
            config_type, scope, keys,
        )
    except Exception as e:
        logger.warning(
            "[DICT] load_workflow_dictionary_rows failed "
            "(config_type=%s scope=%s keys=%s): %s",
            config_type, scope, keys, e,
        )
        return []

    by_key: dict[str, dict[str, Any]] = {}
    for r in rows:
        val = r["value"]
        if isinstance(val, str):
            try:
                import json as _json
                val = _json.loads(val)
            except Exception:
                val = {}
        if not isinstance(val, dict):
            val = {}
        by_key[r["key"]] = {
            "key":         r["key"],
            "parent_key":  r["parent_key"] or "",
            "label":       val.get("label") or r["key"],
            "description": val.get("description") or "",
        }

    # Preserve input order, drop unknowns (log a warning so drift is visible).
    out: list[dict[str, Any]] = []
    dropped: list[str] = []
    for k in keys:
        if k in by_key:
            out.append(by_key[k])
        else:
            dropped.append(k)
    if dropped:
        logger.warning(
            "[DICT] Unknown %s keys in %s scope (silently dropped): %s. "
            "Check geo_workflow_config seeds vs. template wizard_config.",
            config_type, scope, dropped,
        )
    return out
