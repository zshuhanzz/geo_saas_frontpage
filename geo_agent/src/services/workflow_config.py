"""
Workflow Config Loader (Anthony Chat ↔ DB-driven steps).

Single source of truth for the Anthony Chat slot-filler:
  * ``geo_workflow_config`` rows (workflow_step + dictionary refs)
  * ``geo_report_templates.wizard_config`` JSONB (per-template enable/disable
    + step-level defaults + required_metrics / required_chapters /
    required_subgoals)
  * ``geo_report_templates.defaults`` JSONB (flat per-template defaults —
    e.g. ``goal``, ``platforms``, ``depth``, ``count``, ``content_type``)

The chat engine (``graphs/analyze.py`` + ``graphs/action.py``) used to ship
hardcoded step orders, hardcoded Chinese labels and hardcoded option lists
that were always one migration behind the admin Wizard UI. This module
collapses those two surfaces into one DB read, so the chat engine and the
Wizard UI render the *same* steps in the *same* order with the *same*
defaults.

Public API
----------
* :func:`load_workflow_steps` — ordered list of resolved steps for a scope
  (``analysis`` / ``content_generation``) with per-template wizard_config
  overrides applied (``enabled`` flag, step-level ``default_*`` values) and
  every field's option list pre-resolved from its referenced dictionary
  config_type.
* :func:`load_template_defaults` — flat ``defaults`` JSONB for a template.
* :func:`load_template_required` — ``{required_metrics, required_chapters,
  required_subgoals}`` from a template's ``wizard_config``.
* :func:`build_widget_from_step` — convert a :class:`ResolvedStep` into one
  or more SSE widget JSON dicts ready for the frontend.

Hard rules
----------
* No hardcoded fallbacks. If the DB is empty / drifted, raise
  :class:`WorkflowConfigError` so the caller surfaces the failure loudly.
* Frontend ``ChatWidgetRenderer`` is the consumer of the widget JSON —
  every emitted widget MUST carry ``label``, ``description``,
  ``widget_type``, ``field`` (or ``fields[]`` for multi-field steps),
  ``options`` (already resolved from DB), and ``default_value``.
* Field type → widget type mapping is centralized in :data:`FIELD_TYPE_TO_WIDGET`.
* The Anthony Chat engine never invents options or labels — it reads the
  ResolvedStep and serializes it.
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────

class WorkflowConfigError(RuntimeError):
    """Raised when DB-backed workflow config is missing or malformed.

    The Anthony Chat engine fails loudly on these errors instead of
    silently rendering an empty wizard or hardcoded fallback list. That is
    deliberate: we want the operator to notice config drift the moment it
    happens, not three weeks later when a customer reports a missing step.
    """


# ─────────────────────────────────────────────────────────────────────
# Field type → widget type mapping
# ─────────────────────────────────────────────────────────────────────
# The workflow_step schema (geo_workflow_config.value.fields[].type) uses a
# small set of typed primitives. The frontend ChatWidgetRenderer maps each
# of those to a concrete React widget. This dict is the single place that
# decides "field of type X → widget of type Y" — both the chat engine and
# the admin WizardConfigEditor agree on the contract.
FIELD_TYPE_TO_WIDGET: dict[str, str] = {
    # Plain primitives
    "text":       "text_input",
    "textarea":   "text_input",
    "number":     "number_input",
    "boolean":    "boolean_toggle",
    # Reference-driven (resolved against geo_workflow_config dictionary rows)
    "single_ref": "single_select",
    "multi_ref":  "multi_select",
    # Composite / custom widgets — the frontend already knows how to render
    # these (admin editor falls back to JSON, chat passes-through).
    "list":              "list_input",
    "json":              "json_input",
    "chart_builder":     "chart_config_builder",
    "prompt_editor":     "prompt_editor",
    "peer_picker":       "peer_picker",
    "analyzer_import":   "analyzer_import",
    "strategy_generator":"strategy_generator",
    "product_facts_form":"product_facts_form",
    "reddit_discovery_config": "json_input",
    "official_website_discovery_config": "json_input",
    "subreddit_targeting_preflight": "json_input",
    "reddit_discovery_preflight": "json_input",
    "prompt_artifact_preparation_preflight": "json_input",
    "prompt_ref_picker": "prompt_ref_picker",
    "topic_ref_picker":  "topic_ref_picker",
    "metric_ref_multi":  "multi_select",
    "platform_picker":   "multi_select",
    "mode_gate_picker":  "mode_gate",
    "execution_preview": "execution_preview",
}


# ─────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ResolvedField:
    """One field within a workflow_step.

    Resolved means: every reference (``ref_config_type``) has been expanded
    into the actual list of options the user can pick, the widget_type has
    been mapped from the field's primitive type, and step-level / flat
    defaults from the template are already merged in.
    """
    key: str
    label: str
    description: str
    type: str                       # raw schema type ("single_ref", "text", ...)
    widget_type: str                # mapped concrete widget for the frontend
    required: bool
    ref_config_type: Optional[str]  # original dictionary config_type, if any
    options: list[dict[str, Any]]   # resolved {key, label, description, icon, ...}
    default_value: Any              # resolved default from template, may be None
    config: dict[str, Any]          # extra widget-specific config
    item_fields: list["ResolvedField"]  # populated for type == "list"


@dataclass
class ResolvedStep:
    """One workflow_step row, with template overrides applied.

    Created by :func:`load_workflow_steps`. The Anthony Chat engine consumes
    these in order and emits widget JSON via :func:`build_widget_from_step`.
    """
    key: str                        # e.g. "analysis_goal"
    num: float                      # display order (value.num)
    label: str                      # bilingual label ("分析目标 (Analysis Goal)")
    description: str                # one-line step description
    enabled: bool                   # template's wizard_config.steps[key].enabled
    fields: list[ResolvedField]
    step_defaults: dict[str, Any]   # raw template wizard_config.steps[key]


# ─────────────────────────────────────────────────────────────────────
# Loaders — public API
# ─────────────────────────────────────────────────────────────────────

async def load_workflow_steps(
    scope: str,
    template_id: Optional[str],
    pool,
) -> list[ResolvedStep]:
    """Load ordered, template-resolved workflow steps for a scope.

    Reads:
      1. Every ``geo_workflow_config`` row with ``config_type='workflow_step'``
         and matching ``scope`` (or ``scope='shared'`` falls through).
      2. Every dictionary row in the same scope plus all shared rows so
         reference fields can be resolved without a second round-trip.
      3. The template's ``wizard_config`` (if ``template_id`` is provided)
         to apply per-step ``enabled`` / ``default_*`` overrides, and the
         template's flat ``defaults`` JSONB for fall-through defaults.

    Raises:
      :class:`WorkflowConfigError` if no workflow_step rows are found for
      the requested scope, or if a step's ``value`` JSONB cannot be parsed.

    Returns:
      Steps in ``value.num`` order (with ``sort_order`` as tiebreaker).
      Disabled steps are NOT filtered here — the chat engine decides
      whether to skip or render them based on its UX rules. This keeps the
      loader pure and makes "show all steps but mark X disabled" possible
      from a single call site.
    """
    if scope not in ("analysis", "content_generation"):
        raise WorkflowConfigError(
            f"Unknown workflow scope: {scope!r} (expected 'analysis' or "
            "'content_generation')"
        )

    rows = await pool.fetch(
        """
        SELECT scope, config_type, key, parent_key, sort_order, value
        FROM geo_workflow_config
        WHERE is_active = true
          AND (scope = $1 OR scope = 'shared')
        ORDER BY scope, config_type, sort_order
        """,
        scope,
    )

    # Bucket: {(scope, config_type) -> [row]} for quick lookup. Within each
    # bucket rows are already sort_order-ordered by the SQL.
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        buckets.setdefault((r["scope"], r["config_type"]), []).append(dict(r))

    step_rows = [
        r for r in buckets.get((scope, "workflow_step"), [])
    ]
    if not step_rows:
        raise WorkflowConfigError(
            f"No workflow_step rows in geo_workflow_config for scope {scope!r}. "
            "Seed migration is missing or inactive — fix the DB before retrying."
        )

    # Load template overrides + flat defaults
    wizard_steps_override: dict[str, dict[str, Any]] = {}
    flat_defaults: dict[str, Any] = {}
    if template_id:
        tmpl = await pool.fetchrow(
            "SELECT defaults, wizard_config FROM geo_report_templates "
            "WHERE id = $1::uuid",
            template_id,
        )
        if not tmpl:
            raise WorkflowConfigError(
                f"Template {template_id!r} not found in geo_report_templates."
            )
        wc = _coerce_jsonb(tmpl["wizard_config"]) or {}
        flat_defaults = _coerce_jsonb(tmpl["defaults"]) or {}
        wizard_steps_override = wc.get("steps") if isinstance(wc.get("steps"), dict) else {}

    # Resolve each step. Note: we sort by value.num first, then by
    # sort_order — value.num is the user-facing display number (e.g. content
    # scope's mode_gate is num=0, content_type is num=1) while sort_order
    # is the DB row order (which is decoupled from display order in the
    # current seed for content_generation).
    resolved: list[ResolvedStep] = []
    for raw in step_rows:
        value = _coerce_jsonb(raw["value"])
        if not isinstance(value, dict):
            raise WorkflowConfigError(
                f"workflow_step {raw['key']!r} (scope={scope}) has malformed "
                f"value JSONB; expected an object, got {type(value).__name__}"
            )

        step_key = raw["key"]
        num_val = value.get("num")
        try:
            num = float(num_val) if num_val is not None else float(raw["sort_order"] or 0)
        except (TypeError, ValueError):
            num = float(raw["sort_order"] or 0)

        step_label = (value.get("label") or step_key).strip()
        step_desc = (value.get("description") or "").strip()

        step_override = wizard_steps_override.get(step_key) or {}
        # `enabled` defaults to the workflow_step's `default_enabled` flag
        # when present. This lets platform-specific steps remain globally
        # registered but hidden unless a template explicitly opts in.
        default_enabled = value.get("default_enabled")
        if not isinstance(default_enabled, bool):
            default_enabled = True
        enabled = step_override.get("enabled") if "enabled" in step_override else default_enabled
        enabled = bool(enabled)

        # Resolve each field
        raw_fields = value.get("fields")
        if not isinstance(raw_fields, list) or not raw_fields:
            # A step with zero fields is legal (e.g. confirm_execute has only
            # an execution_preview block). We still need ONE entry so the
            # chat engine can render a card. Synthesize a no-op field.
            raw_fields = [{
                "key":   f"_{step_key}_marker",
                "type":  "json",
                "label": step_label,
                "description": step_desc,
            }]

        fields: list[ResolvedField] = []
        for field_def in raw_fields:
            fields.append(_resolve_field(
                field_def=field_def,
                step_override=step_override,
                flat_defaults=flat_defaults,
                buckets=buckets,
                scope=scope,
            ))

        resolved.append(ResolvedStep(
            key=step_key,
            num=num,
            label=step_label,
            description=step_desc,
            enabled=enabled,
            fields=fields,
            step_defaults=step_override,
        ))

    resolved.sort(key=lambda s: (s.num, s.key))
    return resolved


async def load_template_defaults(template_id: str, pool) -> dict[str, Any]:
    """Return the flat ``defaults`` JSONB for a template.

    Raises :class:`WorkflowConfigError` if the template doesn't exist —
    this is a hard failure because the chat engine should never fall back
    to "imaginary defaults" silently.
    """
    row = await pool.fetchrow(
        "SELECT defaults FROM geo_report_templates WHERE id = $1::uuid",
        template_id,
    )
    if not row:
        raise WorkflowConfigError(
            f"Template {template_id!r} not found (load_template_defaults)."
        )
    return _coerce_jsonb(row["defaults"]) or {}


async def load_template_required(
    template_id: str,
    scope: str,
    pool,
) -> dict[str, list[Any]]:
    """Return the template's invisible contract.

    These fields never become widgets — the chat engine injects them into
    the final task_inputs right before emitting ``task_ready``. They live
    in ``wizard_config`` (NOT in flat ``defaults``).

    Returns a dict with stable keys::

        {
            "required_metrics":   [...],   # always present (both scopes)
            "required_chapters":  [...],   # analysis only; [] for content
            "required_subgoals":  [...],   # content only; [] for analysis
        }

    Empty lists when the template hasn't declared any contract — that's
    semantically equivalent to "no hard contract, run dynamic discovery".
    """
    row = await pool.fetchrow(
        "SELECT wizard_config FROM geo_report_templates WHERE id = $1::uuid",
        template_id,
    )
    if not row:
        raise WorkflowConfigError(
            f"Template {template_id!r} not found (load_template_required)."
        )
    wc = _coerce_jsonb(row["wizard_config"]) or {}

    return {
        "required_metrics":  list(wc.get("required_metrics") or []),
        "required_chapters": list(wc.get("required_chapters") or []) if scope == "analysis" else [],
        "required_subgoals": list(wc.get("required_subgoals") or []) if scope == "content_generation" else [],
    }


# ─────────────────────────────────────────────────────────────────────
# Widget builder — turn a ResolvedStep into SSE widget JSON
# ─────────────────────────────────────────────────────────────────────

def build_widget_from_step(
    step: ResolvedStep,
    *,
    widget_id_prefix: str = "ws",
) -> list[dict[str, Any]]:
    """Convert one resolved step into one widget per field.

    Multiple-field steps (e.g. ``data_selection`` has domains + date_range
    + platforms + peers) get one widget per field. The frontend groups
    them by ``step_key`` so they render under one "step card".

    Each emitted widget has this shape::

        {
            "widget_id": "ws_<step_key>_<field_key>_<rand>",
            "step_key": "<step_key>",
            "step_num": <int>,
            "step_label": "<bilingual label>",
            "step_description": "<step desc>",
            "widget_type": "single_select" | "multi_select" | ...,
            "field": "<field_key>",
            "label": "<field label>",
            "description": "<field desc>",
            "required": <bool>,
            "options": [...],          # resolved, may be []
            "default_value": <any>,    # may be None
            "config": {...}            # widget-specific extras
        }
    """
    widgets: list[dict[str, Any]] = []
    for f in step.fields:
        wid = f"{widget_id_prefix}_{step.key}_{f.key}_{_uuid.uuid4().hex[:8]}"
        widget: dict[str, Any] = {
            "widget_id":        wid,
            "step_key":         step.key,
            "step_num":         step.num,
            "step_label":       step.label,
            "step_description": step.description,
            "widget_type":      f.widget_type,
            "field":            f.key,
            "label":            f.label,
            "description":      f.description,
            "required":         f.required,
            "options":          f.options,
            "default_value":    f.default_value,
            "config":           f.config,
        }
        if f.item_fields:
            widget["item_fields"] = [_field_to_dict(sub) for sub in f.item_fields]
        widgets.append(widget)
    return widgets


def build_summary_display(
    task_inputs: dict[str, Any],
    all_steps: list[ResolvedStep],
) -> list[dict[str, Any]]:
    """Translate raw collected ``task_inputs`` into a list of display rows
    that ChatTaskCard / TaskConfirmWidget can render straight to screen.

    Each element of the returned list has the shape::

        {
            "step_key":   "<step that owns this field, or '' for top-level>",
            "field":      "<schema field key, e.g. default_goal>",
            "label":      "<step.fields[].label, e.g. 默认分析目标>",
            "value":      <raw value, kept for debugging / round-trip>,
            "display":    "<the user-facing string, e.g. 品牌健康诊断>",
        }

    Translation rules:
      * For ``single_ref`` / ``mode_gate_picker`` style fields: map the raw
        ``key`` value to the option's ``label`` from the resolved step.
      * For ``multi_ref`` / ``multi_select``: join each option label with
        commas; empty array → "(无)".
      * For arbitrary primitives (text / number / boolean / date_range /
        dict): coerce sensibly. Date dicts become ``from ~ to``; dicts with
        ``preset`` become "最近 N 天" via the option label if available.
      * Fields the loader doesn't know about are dropped — confirm display
        should never show ``_template_id`` / ``_flow`` / ``metrics_locked``
        and other internal bookkeeping keys.

    The list is ordered by step.num then by field declaration order, so the
    confirmation card reads top-to-bottom in the same direction the wizard
    asked the questions.
    """
    rows: list[dict[str, Any]] = []
    seen_field_keys: set[str] = set()

    # Walk steps + fields in display order so the summary reads naturally.
    for step in sorted(all_steps, key=lambda s: (s.num, s.key)):
        for f in step.fields:
            if f.key in seen_field_keys:
                continue
            # Skip pure rendering / preview fields and internal markers
            if f.type in ("execution_preview",) or f.key.startswith("_"):
                continue
            # Internal bookkeeping keys we definitely don't want surfaced
            if f.key in ("execution_preview",):
                continue
            value = _pick_input_value(task_inputs, f.key)
            if value is None or value == "" or value == []:
                continue
            display = _render_field_value(f, value)
            rows.append({
                "step_key": step.key,
                "field":    f.key,
                "label":    f.label,
                "value":    value,
                "display":  display,
            })
            seen_field_keys.add(f.key)
    return rows


def _pick_input_value(task_inputs: dict[str, Any], field_key: str) -> Any:
    """Look up the value the chat collected for a given field.

    The chat normalizes most fields by storing them under the schema field
    key (``default_goal``, ``default_domains``, etc.) but legacy code paths
    occasionally stash them under the alias key (``goal``, ``domains``).
    Try the canonical key first, fall back to the alias.
    """
    if field_key in task_inputs:
        return task_inputs[field_key]
    aliases = _DEFAULT_ALIASES.get(field_key, [])
    for a in aliases:
        if a in task_inputs:
            return task_inputs[a]
    return None


def _render_field_value(field: ResolvedField, value: Any) -> str:
    """Translate one raw value to the human-readable string we show on the
    confirmation card. Pure-Python; no DB calls.
    """
    if value is None:
        return ""
    # Reference-style fields: map keys to labels using the resolved options
    if field.options:
        label_map = {str(o.get("key", "")): o.get("label") or str(o.get("key", "")) for o in field.options}
        if isinstance(value, list):
            if not value:
                return "(无)"
            return ", ".join(label_map.get(str(v), str(v)) for v in value)
        return label_map.get(str(value), str(value))
    # date_range — schema field that doesn't expose options
    if field.type == "single_ref" and isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Common shapes: {from, to} / {start, end} / {preset}
        if value.get("from") and value.get("to"):
            return f"{value['from']} ~ {value['to']}"
        if value.get("start") and value.get("end"):
            return f"{value['start']} ~ {value['end']}"
        if value.get("preset"):
            return str(value["preset"])
        # product_facts_form etc. — count filled
        filled = sum(1 for v in value.values() if v and str(v).strip())
        return f"{filled} 项已填写" if filled else "(空)"
    if isinstance(value, list):
        if not value:
            return "(无)"
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def build_confirm_widget(
    step: ResolvedStep,
    *,
    summary: dict[str, Any],
    confirm_label: str,
    task_type: Optional[str] = None,
    task_name_template: Optional[str] = None,
    widget_id_prefix: str = "ws",
    summary_display: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Build the final ``task_confirm`` card for a confirm_execute step.

    The confirm step in the schema has an ``execution_preview`` field; we
    keep that data in ``config`` so the frontend can render the list of
    pipeline phases below the summary if it wants. The chat engine
    supplies the human-readable ``summary`` of all collected inputs.
    """
    extra_config: dict[str, Any] = {}
    for f in step.fields:
        if f.type == "execution_preview" and isinstance(f.config, dict):
            # Schema stores the preview steps under the field's nested
            # ``config`` key (i.e. field_def["config"]). Unwrap that one
            # level so the frontend gets ``{steps: [...]}`` directly.
            inner = f.config.get("config") if isinstance(f.config.get("config"), dict) else f.config
            extra_config["execution_preview"] = inner
            break

    widget: dict[str, Any] = {
        "widget_id":        f"{widget_id_prefix}_{step.key}_confirm_{_uuid.uuid4().hex[:8]}",
        "step_key":         step.key,
        "step_num":         step.num,
        "step_label":       step.label,
        "step_description": step.description,
        "widget_type":      "task_confirm",
        "field":            "confirm",
        "label":            step.label,
        "description":      step.description,
        "required":         True,
        "options":          [],
        "default_value":    None,
        "config":           extra_config,
        "summary":          summary,
        "confirm_label":    confirm_label,
    }
    if task_type is not None:
        widget["task_type"] = task_type
    if task_name_template is not None:
        widget["task_name_template"] = task_name_template
    if summary_display is not None:
        widget["summary_display"] = summary_display
    return widget


# ─────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────

def _humanize_field_key(fkey: str) -> str:
    """Fallback when a field schema row has no ``label`` set.

    Snake-case keys like ``default_goal`` would otherwise leak into the
    confirmation card verbatim — UX-hostile and obviously not localized.
    Strip the ``default_`` prefix (chat slot-fill convention) and title-case
    the remainder so a missing label degrades to ``Goal`` rather than
    ``default_goal``. Real localization should populate label in the DB; this
    is the safety net for legacy / partially-migrated rows.
    """
    base = fkey[len("default_"):] if fkey.startswith("default_") else fkey
    return base.replace("_", " ").strip().title() or fkey


def _coerce_jsonb(raw: Any) -> Any:
    """asyncpg usually decodes jsonb to a dict/list, but defensive parsing
    keeps the loader robust against legacy rows that were saved as TEXT or
    nullable JSONB columns that come back as ``None``.
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _resolve_field(
    field_def: dict[str, Any],
    step_override: dict[str, Any],
    flat_defaults: dict[str, Any],
    buckets: dict[tuple[str, str], list[dict[str, Any]]],
    scope: str,
) -> ResolvedField:
    """Resolve one field schema entry into a :class:`ResolvedField`.

    Defaults priority (highest wins, last write wins on tie):
      1. step_override[field.key]            (template wizard_config.steps[step].default_*)
      2. flat_defaults[<aliased_key>]        (template top-level defaults JSONB)
      3. field_def["default"]                 (schema-declared default)
    """
    fkey = field_def.get("key")
    if not fkey or not isinstance(fkey, str):
        raise WorkflowConfigError(
            f"Field schema is missing 'key': {field_def!r}"
        )
    ftype = field_def.get("type") or "text"
    raw_label = (field_def.get("label") or "").strip()
    flabel = raw_label or _humanize_field_key(fkey)
    fdesc = (field_def.get("description") or "").strip()
    required = bool(field_def.get("required", False))
    ref_config_type = field_def.get("ref_config_type")
    ref_scope = field_def.get("ref_scope")
    config = {
        k: v for k, v in field_def.items()
        if k not in {"key", "type", "label", "description", "required",
                     "ref_config_type", "ref_scope", "default", "item_fields"}
    }

    widget_type = FIELD_TYPE_TO_WIDGET.get(ftype, "json_input")

    # Resolve options for ref types (single_ref / multi_ref / mode_gate_picker).
    options: list[dict[str, Any]] = []
    if ref_config_type:
        # Pick the right scope: explicit ref_scope on the field overrides
        # everything else; otherwise prefer the step's own scope, falling
        # back to "shared" if the dictionary lives there.
        candidate_scopes: list[str] = []
        if ref_scope:
            candidate_scopes.append(ref_scope)
        candidate_scopes += [scope, "shared"]
        seen_scope: Optional[str] = None
        for cs in candidate_scopes:
            if (cs, ref_config_type) in buckets:
                seen_scope = cs
                break
        if seen_scope is None:
            # No options found — surface this loudly via empty list +
            # config flag. The frontend already shows a "seed it first"
            # alert; the chat engine will skip the step gracefully.
            logger.warning(
                "[WORKFLOW_CONFIG] Field %s.%s references config_type=%r "
                "but no rows found in scopes %s. Frontend will render an "
                "empty option list.",
                ref_config_type, fkey, ref_config_type, candidate_scopes,
            )
        else:
            for r in buckets[(seen_scope, ref_config_type)]:
                v = _coerce_jsonb(r["value"]) or {}
                # Skip rows the seed has flagged as deprecated so chat doesn't
                # show stale options. Admin UI shows them with a warning, but
                # for a guided slot-filler we only want active choices.
                if isinstance(v, dict) and v.get("deprecated"):
                    continue
                options.append({
                    "id":          r["key"],
                    "key":         r["key"],
                    "label":       (v.get("label") if isinstance(v, dict) else None) or r["key"],
                    "description": (v.get("description") if isinstance(v, dict) else "") or "",
                    "icon":        (v.get("icon") if isinstance(v, dict) else None),
                    "color":       (v.get("color") if isinstance(v, dict) else None),
                    "_meta":       v if isinstance(v, dict) else {},
                })

    # ─── Default resolution ─────────────────────────────────────
    # 1) step-level override — keyed by the field's own key
    default_value: Any = None
    has_default = False
    if isinstance(step_override, dict) and fkey in step_override:
        default_value = step_override[fkey]
        has_default = True

    # 2) Flat template.defaults — apply alias map for cross-cutting fields.
    # The flat defaults JSONB uses semantic names (goal, depth, platforms,
    # count, content_type) that don't always match the schema field key
    # (default_goal, default_depth, default_platforms, default_count,
    # default — for content_type). Only use them if the step-level
    # override didn't already provide a value.
    if not has_default and isinstance(flat_defaults, dict):
        aliases = _DEFAULT_ALIASES.get(fkey, [])
        for alias in [fkey] + aliases:
            if alias in flat_defaults:
                default_value = flat_defaults[alias]
                has_default = True
                break

    # 3) schema-declared default
    if not has_default and "default" in field_def:
        default_value = field_def["default"]

    # ─── List sub-fields ────────────────────────────────────────
    item_fields: list[ResolvedField] = []
    raw_items = field_def.get("item_fields")
    if isinstance(raw_items, list):
        for sub in raw_items:
            item_fields.append(_resolve_field(
                field_def=sub,
                step_override={},     # nested fields don't get step-level overrides
                flat_defaults={},
                buckets=buckets,
                scope=scope,
            ))

    return ResolvedField(
        key=fkey,
        label=flabel,
        description=fdesc,
        type=ftype,
        widget_type=widget_type,
        required=required,
        ref_config_type=ref_config_type,
        options=options,
        default_value=default_value,
        config=config,
        item_fields=item_fields,
    )


def _field_to_dict(f: ResolvedField) -> dict[str, Any]:
    """Serialize a :class:`ResolvedField` (used for nested item_fields).

    Top-level fields are serialized inline by :func:`build_widget_from_step`
    — this helper is only for recursive list-item children.
    """
    return {
        "field":         f.key,
        "label":         f.label,
        "description":   f.description,
        "type":          f.type,
        "widget_type":   f.widget_type,
        "required":      f.required,
        "options":       f.options,
        "default_value": f.default_value,
        "config":        f.config,
        "item_fields":   [_field_to_dict(sub) for sub in f.item_fields],
    }


# Map from schema field-key → list of aliases that may appear in the
# template's flat ``defaults`` JSONB. Keep this small — every entry here is
# essentially "the wizard step says default_goal but the legacy flat
# defaults blob calls it goal". Add to it only when a template's flat
# defaults uses a different key than the schema's field key.
_DEFAULT_ALIASES: dict[str, list[str]] = {
    "default_goal":            ["goal"],
    "default_depth":           ["depth"],
    "default_platforms":       ["platforms"],
    "default_ai_platforms":    ["platforms", "ai_platforms"],
    "default_count":           ["count"],
    "default_language":        ["language"],
    "default_publish_platform":["publish_platform"],
    "default_date_range":      ["date_range"],
    "default_domains":         ["domains"],
    "default_lenses":          ["lenses", "analysis_lenses"],
    "default_metrics":         ["metrics", "selected_metrics"],
    "default_sub_goals":       ["sub_goals", "subgoals", "selected_subgoals"],
    "default_sort":            ["sort"],
    "default_peers":           ["peers"],
    "default":                 ["content_type"],  # workflow_step content_type uses field "default"
    "mode_choice":             ["mode_choice", "mode"],
}


# ─────────────────────────────────────────────────────────────────────
# Chat slot-filler ⇄ pipeline key naming bridge
# ─────────────────────────────────────────────────────────────────────
#
# The wizard schema names fields like ``default_goal``, ``default_domains``,
# ``default_count`` (because admin UI uses `default_*` to mean "pre-fill
# this on the wizard"). The chat slot-filler accumulates user picks under
# those same keys. But pipelines (``analysis_pipeline.py`` /
# ``content_pipeline.py``) read PLAIN keys (``goal``, ``domains``,
# ``count``) — that's the wizard-UI naming convention because the wizard
# strips the prefix when posting to ``/api/agent/tasks``.
#
# Without translation at the chat boundary, every pipeline silently uses
# its hardcoded fallback default (``count=5``, ``language="zh-CN"``,
# etc) instead of the user's actual chat selection. The bug looks like
# "task succeeded" but the real input is silently ignored.
#
# Fix at the SOURCE — apply this strip in each slot-filler node so the
# value lands in `task_inputs` already under the plain key. That way:
#   - LangGraph state has plain keys
#   - DB ``geo_agent_tasks.inputs`` has plain keys
#   - Pipelines read plain keys directly, no fallback alias needed

# Plain pipeline key → list of chat schema keys that may carry the
# semantic value. Plain key wins if both are present.
_CHAT_TO_PIPELINE_KEYS: dict[str, list[str]] = {
    # analysis
    "domains":            ["default_domains"],
    "platforms":          ["default_platforms"],
    "lenses":             ["default_lenses"],
    "peers":              ["default_peers"],
    "charts":             ["default_charts"],
    "baseline":           ["default_baseline"],
    "date_range":         ["default_date_range"],
    "goal":               ["default_goal"],
    # content
    "selected_metrics":   ["default_metrics"],
    "selected_subgoals":  ["default_sub_goals"],
    "ai_platforms":       ["default_ai_platforms"],
    "publish_platform":   ["default_publish_platform"],
    "language":           ["default_language"],
    "count":              ["default_count"],
    "depth":              ["default_depth"],
    "product_facts":      ["default_product_facts"],
    "sort":               ["default_sort"],
    # `default` is the wizard schema's odd-one-out for content_type:
    # workflow_step content_type's only field is keyed `default`.
    "content_type":       ["default"],
}


def normalize_chat_inputs_to_pipeline_shape(inputs: dict) -> dict:
    """Project chat schema field keys onto the plain pipeline keys.

    Idempotent: if a plain key is already present, leave it alone.
    Removes the chat-only ``default_*`` aliases after projecting so that
    ``geo_agent_tasks.inputs`` doesn't store both shapes (DB stays clean).

    Also resolves the ``date_range`` token (e.g. ``last_30d``) into
    concrete ``date_from`` / ``date_to`` strings — pipeline reads
    ``date_from`` / ``date_to`` directly and the wizard UI sends those,
    but chat collects only the windowed token.

    Call once per slot-filler return (BEFORE the SSE emit boundary in
    main.py). The main.py emit point used to do this strip, but that
    leaves DB ``inputs`` carrying both ``default_*`` and plain keys —
    confusing for ops. Doing it here means DB has only plain keys.
    """
    out = dict(inputs)
    for plain, chat_keys in _CHAT_TO_PIPELINE_KEYS.items():
        if plain in out:
            # plain key already present — drop chat aliases (keep DB clean)
            for ck in chat_keys:
                out.pop(ck, None)
            continue
        for ck in chat_keys:
            if ck in out:
                out[plain] = out.pop(ck)  # rename, don't duplicate
                break

    # Expand date_range token into date_from / date_to if missing
    if not out.get("date_from") or not out.get("date_to"):
        token = out.get("date_range")
        if token:
            from datetime import date as _date, timedelta as _td
            today = _date.today()
            window_days = {
                "last_7d": 7, "last_30d": 30, "last_90d": 90,
                "last_180d": 180, "last_365d": 365,
            }.get(str(token), 30)
            out.setdefault("date_to", today.strftime("%Y-%m-%d"))
            out.setdefault(
                "date_from",
                (today - _td(days=window_days)).strftime("%Y-%m-%d"),
            )
    return out
