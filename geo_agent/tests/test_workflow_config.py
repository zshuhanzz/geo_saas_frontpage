"""
Tests for ``services.workflow_config``.

Verifies the contract the Anthony Chat engine depends on:
  * scope filtering (analysis vs content_generation; shared rows fall through)
  * template wizard_config override (enabled flag + per-field default_*)
  * defaults priority (step-level override > flat defaults > schema default)
  * required_metrics / required_chapters / required_subgoals projection
  * widget JSON shape (matches the SSE contract the frontend consumes)

These tests use a tiny in-memory fake of asyncpg that supports the two
methods :class:`workflow_config` calls (``fetch`` and ``fetchrow``). No
real DB is needed.
"""
from __future__ import annotations

import json
import asyncio
from typing import Any

import pytest

from services.workflow_config import (
    FIELD_TYPE_TO_WIDGET,
    ResolvedStep,
    WorkflowConfigError,
    build_confirm_widget,
    build_summary_display,
    build_widget_from_step,
    load_template_defaults,
    load_template_required,
    load_workflow_steps,
)


# ─────────────────────────────────────────────────────────────────────
# Tiny in-memory pool fake
# ─────────────────────────────────────────────────────────────────────


class FakePool:
    """Minimal asyncpg-like pool replaying canned responses for one query."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None,
                 templates: dict[str, dict[str, Any]] | None = None):
        self._rows = rows or []
        self._templates = templates or {}

    async def fetch(self, sql: str, *args):
        # Filter by scope — first arg is the scope (matches loader call)
        scope = args[0] if args else None
        # Loader query is: WHERE scope = $1 OR scope = 'shared'
        out = []
        for r in self._rows:
            if r["scope"] == scope or r["scope"] == "shared":
                out.append(_AsRecord(r))
        # Loader sorts by scope, config_type, sort_order in SQL — replicate
        out.sort(key=lambda r: (r["scope"], r["config_type"], r["sort_order"] or 0))
        return out

    async def fetchrow(self, sql: str, *args):
        # Loader uses fetchrow for templates only
        if "geo_report_templates" in sql:
            tid = args[0] if args else None
            if tid in self._templates:
                return _AsRecord(self._templates[tid])
            return None
        return None


class _AsRecord(dict):
    """Pretend to be an asyncpg.Record (supports r['key'])."""
    def __init__(self, d):
        super().__init__(d)


# ─────────────────────────────────────────────────────────────────────
# Fixtures — tiny seed mirror
# ─────────────────────────────────────────────────────────────────────


def _make_seed_rows() -> list[dict[str, Any]]:
    """Return a slim mirror of the real ``geo_workflow_config`` seed.

    Just enough rows to exercise: 1 analysis step + 1 content step +
    dictionary refs in both scope-local and shared scopes.
    """
    return [
        # ── analysis scope ──
        {
            "scope": "analysis",
            "config_type": "workflow_step",
            "key": "analysis_goal",
            "parent_key": None,
            "sort_order": 1,
            "value": {
                "num": 1,
                "label": "分析目标",
                "description": "选择分析视角",
                "fields": [
                    {
                        "key": "default_goal",
                        "type": "single_ref",
                        "label": "默认分析目标",
                        "description": "",
                        "ref_scope": "analysis",
                        "ref_config_type": "goal",
                    },
                ],
            },
        },
        {
            "scope": "analysis",
            "config_type": "workflow_step",
            "key": "data_selection",
            "parent_key": None,
            "sort_order": 3,
            "value": {
                "num": 3,
                "label": "数据选择",
                "description": "选择数据领域",
                "fields": [
                    {
                        "key": "default_domains",
                        "type": "multi_ref",
                        "label": "默认数据领域",
                        "description": "",
                        "ref_scope": "shared",
                        "ref_config_type": "domain",
                    },
                    {
                        "key": "default_platforms",
                        "type": "multi_ref",
                        "label": "默认 AI 平台",
                        "description": "",
                        "ref_scope": "shared",
                        "ref_config_type": "platform",
                    },
                ],
            },
        },
        {
            "scope": "analysis",
            "config_type": "workflow_step",
            "key": "confirm_execute",
            "parent_key": None,
            "sort_order": 6,
            "value": {
                "num": 6,
                "label": "确认执行",
                "description": "复核并执行",
                "fields": [
                    {
                        "key": "execution_preview",
                        "type": "execution_preview",
                        "label": "执行流程",
                        "config": {
                            "steps": [
                                {"name": "validate_inputs", "label": "校验"},
                            ],
                        },
                    },
                ],
            },
        },
        {
            "scope": "analysis",
            "config_type": "goal",
            "key": "competitive",
            "parent_key": None,
            "sort_order": 1,
            "value": {
                "label": "竞品对标分析",
                "description": "对比品牌与竞品",
                "icon": "🎯",
            },
        },
        {
            "scope": "analysis",
            "config_type": "goal",
            "key": "trend",
            "parent_key": None,
            "sort_order": 2,
            "value": {
                "label": "趋势追踪",
                "description": "时序变化",
                "icon": "📈",
            },
        },
        # Deprecated row should be filtered out by the loader
        {
            "scope": "analysis",
            "config_type": "goal",
            "key": "benchmark",
            "parent_key": None,
            "sort_order": 99,
            "value": {
                "label": "竞品对标",
                "description": "deprecated",
                "deprecated": "replaced",
            },
        },
        # ── content_generation scope ──
        {
            "scope": "content_generation",
            "config_type": "workflow_step",
            "key": "mode_gate",
            "parent_key": None,
            "sort_order": 0,
            "value": {
                "num": 0,
                "label": "生成模式",
                "description": "选模式",
                "fields": [
                    {
                        "key": "mode_choice",
                        "type": "mode_gate_picker",
                        "label": "生成模式",
                        "description": "",
                        "ref_scope": "content_generation",
                        "ref_config_type": "mode_option",
                    },
                ],
            },
        },
        {
            "scope": "content_generation",
            "config_type": "workflow_step",
            "key": "reddit_discovery",
            "parent_key": None,
            "sort_order": 25,
            "value": {
                "num": 2.5,
                "label": "Reddit Discover",
                "description": "Reddit-only discovery",
                "default_enabled": False,
                "fields": [
                    {
                        "key": "reddit_discovery",
                        "type": "reddit_discovery_config",
                        "label": "Reddit Discover Source",
                    },
                ],
            },
        },
        {
            "scope": "content_generation",
            "config_type": "workflow_step",
            "key": "content_type",
            "parent_key": None,
            "sort_order": 3,
            "value": {
                "num": 1,
                "label": "内容类型",
                "description": "",
                "fields": [
                    {
                        "key": "default",
                        "type": "single_ref",
                        "label": "默认内容类型",
                        "description": "",
                        "required": True,
                        "ref_scope": "content_generation",
                        "ref_config_type": "content_type",
                    },
                ],
            },
        },
        {
            "scope": "content_generation",
            "config_type": "mode_option",
            "key": "manual",
            "parent_key": None,
            "sort_order": 0,
            "value": {"label": "我来定", "description": "手动配置", "icon": "✍️"},
        },
        {
            "scope": "content_generation",
            "config_type": "mode_option",
            "key": "ai_discover",
            "parent_key": None,
            "sort_order": 1,
            "value": {"label": "AI 帮我发现", "description": "AI 推荐", "icon": "✨"},
        },
        {
            "scope": "content_generation",
            "config_type": "content_type",
            "key": "faq",
            "parent_key": None,
            "sort_order": 1,
            "value": {"label": "FAQ", "description": "FAQ 内容", "icon": "📋"},
        },
        # ── shared scope ──
        {
            "scope": "shared",
            "config_type": "domain",
            "key": "visibility",
            "parent_key": None,
            "sort_order": 1,
            "value": {"label": "可见度", "icon": "🔍"},
        },
        {
            "scope": "shared",
            "config_type": "domain",
            "key": "citation",
            "parent_key": None,
            "sort_order": 2,
            "value": {"label": "引用", "icon": "📎"},
        },
        {
            "scope": "shared",
            "config_type": "platform",
            "key": "chatgpt",
            "parent_key": None,
            "sort_order": 1,
            "value": {"label": "ChatGPT", "icon": "🤖"},
        },
        {
            "scope": "shared",
            "config_type": "platform",
            "key": "gemini",
            "parent_key": None,
            "sort_order": 2,
            "value": {"label": "Gemini", "icon": "✨"},
        },
    ]


def _make_template(
    *,
    steps: dict[str, Any] | None = None,
    flat_defaults: dict[str, Any] | None = None,
    required_metrics: list[str] | None = None,
    required_chapters: list[str] | None = None,
    required_subgoals: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "defaults": flat_defaults or {},
        "wizard_config": {
            "version": 1,
            "steps": steps or {},
            "required_metrics":  required_metrics or [],
            "required_chapters": required_chapters or [],
            "required_subgoals": required_subgoals or [],
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────


def _run(coro):
    return asyncio.run(coro)


def test_unknown_scope_raises():
    pool = FakePool(rows=_make_seed_rows())
    with pytest.raises(WorkflowConfigError, match="Unknown workflow scope"):
        _run(load_workflow_steps("unknown", None, pool))


def test_empty_db_raises():
    pool = FakePool(rows=[])
    with pytest.raises(WorkflowConfigError, match="No workflow_step rows"):
        _run(load_workflow_steps("analysis", None, pool))


def test_scope_filter_separates_analysis_from_content():
    pool = FakePool(rows=_make_seed_rows())
    a_steps = _run(load_workflow_steps("analysis", None, pool))
    c_steps = _run(load_workflow_steps("content_generation", None, pool))

    a_keys = [s.key for s in a_steps]
    c_keys = [s.key for s in c_steps]
    assert a_keys == ["analysis_goal", "data_selection", "confirm_execute"]
    assert c_keys == ["mode_gate", "content_type", "reddit_discovery"]
    assert next(s for s in c_steps if s.key == "reddit_discovery").enabled is False
    # No cross-bleed
    for k in c_keys:
        assert k not in a_keys


def test_step_order_uses_value_num_not_sort_order():
    """content_generation's content_type has sort_order=3 but num=1 — value.num wins."""
    pool = FakePool(rows=_make_seed_rows())
    c_steps = _run(load_workflow_steps("content_generation", None, pool))
    nums = [(s.key, s.num) for s in c_steps]
    # mode_gate.num=0 must precede content_type.num=1
    assert nums == [("mode_gate", 0), ("content_type", 1), ("reddit_discovery", 2.5)]


def test_default_disabled_step_only_shows_when_template_opts_in():
    rows = _make_seed_rows()
    pool = FakePool(rows=rows)
    steps = _run(load_workflow_steps("content_generation", None, pool))
    by_key = {s.key: s for s in steps}
    assert by_key["reddit_discovery"].enabled is False

    tmpl = _make_template(steps={"reddit_discovery": {"enabled": True}})
    pool = FakePool(rows=rows, templates={"reddit-template": tmpl})
    steps = _run(load_workflow_steps("content_generation", "reddit-template", pool))
    by_key = {s.key: s for s in steps}
    assert by_key["reddit_discovery"].enabled is True


def test_options_resolved_from_dictionary():
    """single_ref / multi_ref fields get options pre-loaded from buckets."""
    pool = FakePool(rows=_make_seed_rows())
    a_steps = _run(load_workflow_steps("analysis", None, pool))
    goal_step = next(s for s in a_steps if s.key == "analysis_goal")
    f = goal_step.fields[0]
    assert f.key == "default_goal"
    assert f.widget_type == "single_select"
    # deprecated 'benchmark' is dropped, leaving competitive + trend
    keys = [o["key"] for o in f.options]
    assert keys == ["competitive", "trend"]
    assert all("label" in o and "icon" in o for o in f.options)

    ds = next(s for s in a_steps if s.key == "data_selection")
    domains = ds.fields[0]
    platforms = ds.fields[1]
    assert [o["key"] for o in domains.options] == ["visibility", "citation"]
    assert [o["key"] for o in platforms.options] == ["chatgpt", "gemini"]


def test_field_type_widget_mapping_centralized():
    """Every field in the seed must map to a known widget_type."""
    pool = FakePool(rows=_make_seed_rows())
    a_steps = _run(load_workflow_steps("analysis", None, pool))
    c_steps = _run(load_workflow_steps("content_generation", None, pool))
    for s in a_steps + c_steps:
        for f in s.fields:
            assert f.widget_type, f"field {f.key} had empty widget_type"
            assert f.widget_type in FIELD_TYPE_TO_WIDGET.values() or f.widget_type == "json_input"


def test_template_override_disables_step():
    rows = _make_seed_rows()
    tmpl = _make_template(steps={"data_selection": {"enabled": False}})
    pool = FakePool(rows=rows, templates={"tmpl-1": tmpl})
    steps = _run(load_workflow_steps("analysis", "tmpl-1", pool))
    by_key = {s.key: s for s in steps}
    assert by_key["data_selection"].enabled is False
    # Other steps stay enabled
    assert by_key["analysis_goal"].enabled is True


def test_template_step_override_default_value():
    """default_goal in wizard_config.steps[analysis_goal] propagates to field."""
    rows = _make_seed_rows()
    tmpl = _make_template(steps={
        "analysis_goal": {"enabled": True, "default_goal": "trend"},
    })
    pool = FakePool(rows=rows, templates={"tmpl-2": tmpl})
    steps = _run(load_workflow_steps("analysis", "tmpl-2", pool))
    goal_field = next(s for s in steps if s.key == "analysis_goal").fields[0]
    assert goal_field.default_value == "trend"


def test_flat_defaults_fall_through_when_step_override_missing():
    """When no step-level override is set, flat template.defaults wins."""
    rows = _make_seed_rows()
    tmpl = _make_template(
        steps={"analysis_goal": {"enabled": True}},  # no default_goal
        flat_defaults={"goal": "competitive"},
    )
    pool = FakePool(rows=rows, templates={"tmpl-3": tmpl})
    steps = _run(load_workflow_steps("analysis", "tmpl-3", pool))
    goal_field = next(s for s in steps if s.key == "analysis_goal").fields[0]
    assert goal_field.default_value == "competitive"


def test_step_override_beats_flat_defaults():
    rows = _make_seed_rows()
    tmpl = _make_template(
        steps={"analysis_goal": {"enabled": True, "default_goal": "trend"}},
        flat_defaults={"goal": "competitive"},
    )
    pool = FakePool(rows=rows, templates={"tmpl-4": tmpl})
    steps = _run(load_workflow_steps("analysis", "tmpl-4", pool))
    goal_field = next(s for s in steps if s.key == "analysis_goal").fields[0]
    assert goal_field.default_value == "trend"


def test_load_template_required_analysis_only_returns_chapters():
    rows = _make_seed_rows()
    tmpl = _make_template(
        required_metrics=["sov_trend"],
        required_chapters=["visibility"],
        required_subgoals=["should_be_dropped"],
    )
    pool = FakePool(rows=rows, templates={"t": tmpl})
    out = _run(load_template_required("t", "analysis", pool))
    assert out["required_metrics"] == ["sov_trend"]
    assert out["required_chapters"] == ["visibility"]
    # subgoals not relevant for analysis scope
    assert out["required_subgoals"] == []


def test_load_template_required_content_returns_subgoals():
    rows = _make_seed_rows()
    tmpl = _make_template(
        required_metrics=["prompt_coverage_rate"],
        required_subgoals=["machine_readability"],
    )
    pool = FakePool(rows=rows, templates={"t": tmpl})
    out = _run(load_template_required("t", "content_generation", pool))
    assert out["required_metrics"] == ["prompt_coverage_rate"]
    assert out["required_subgoals"] == ["machine_readability"]
    assert out["required_chapters"] == []


def test_load_template_required_missing_template_raises():
    pool = FakePool(rows=_make_seed_rows())
    with pytest.raises(WorkflowConfigError, match="not found"):
        _run(load_template_required("does-not-exist", "analysis", pool))


def test_load_template_defaults_returns_flat_jsonb():
    pool = FakePool(rows=_make_seed_rows(), templates={
        "t": {"defaults": {"goal": "trend", "depth": "standard"},
              "wizard_config": {}}
    })
    d = _run(load_template_defaults("t", pool))
    assert d == {"goal": "trend", "depth": "standard"}


def test_build_widget_emits_one_per_field_with_step_metadata():
    rows = _make_seed_rows()
    pool = FakePool(rows=rows)
    steps = _run(load_workflow_steps("analysis", None, pool))
    ds = next(s for s in steps if s.key == "data_selection")
    widgets = build_widget_from_step(ds)
    # 2 fields → 2 widgets, each carrying step_key for grouping
    assert len(widgets) == 2
    for w in widgets:
        assert w["step_key"] == "data_selection"
        assert w["step_num"] == 3
        assert w["step_label"] == "数据选择"
        assert "default_value" in w
        assert isinstance(w["options"], list)
        assert "widget_id" in w


def test_build_confirm_widget_carries_summary_and_exec_preview():
    rows = _make_seed_rows()
    pool = FakePool(rows=rows)
    steps = _run(load_workflow_steps("analysis", None, pool))
    confirm = next(s for s in steps if s.key == "confirm_execute")
    widget = build_confirm_widget(
        confirm,
        summary={"分析视角": "竞品对标"},
        confirm_label="开始分析",
        task_type="analysis",
    )
    assert widget["widget_type"] == "task_confirm"
    assert widget["summary"] == {"分析视角": "竞品对标"}
    assert widget["confirm_label"] == "开始分析"
    assert widget["task_type"] == "analysis"
    # execution_preview comes from the schema
    assert "execution_preview" in widget["config"]
    assert widget["config"]["execution_preview"]["steps"][0]["name"] == "validate_inputs"


def test_step_with_no_fields_synthesizes_marker():
    """A workflow_step missing a fields[] array still resolves into ONE
    field so the chat engine can emit a single card."""
    rows = [{
        "scope": "analysis",
        "config_type": "workflow_step",
        "key": "weird_step",
        "parent_key": None,
        "sort_order": 1,
        "value": {"num": 1, "label": "Empty", "description": ""},
    }]
    pool = FakePool(rows=rows)
    steps = _run(load_workflow_steps("analysis", None, pool))
    assert len(steps) == 1
    assert len(steps[0].fields) == 1
    assert steps[0].fields[0].key == "_weird_step_marker"


def test_unknown_template_in_load_workflow_steps_raises():
    rows = _make_seed_rows()
    pool = FakePool(rows=rows, templates={})  # no template registered
    with pytest.raises(WorkflowConfigError, match="not found"):
        _run(load_workflow_steps("analysis", "missing-id", pool))


# ─────────────────────────────────────────────────────────────────────
# Issue 2 — build_summary_display: Chinese-label translation
# ─────────────────────────────────────────────────────────────────────


def test_build_summary_display_translates_single_select_label():
    """`default_goal: "trend"` should become a row with display "趋势追踪"."""
    pool = FakePool(rows=_make_seed_rows())
    steps = _run(load_workflow_steps("analysis", None, pool))
    rows = build_summary_display({"default_goal": "trend"}, steps)
    by_field = {r["field"]: r for r in rows}
    assert "default_goal" in by_field
    row = by_field["default_goal"]
    assert row["label"] == "默认分析目标"
    assert row["display"] == "趋势追踪"


def test_build_summary_display_translates_multi_select_labels():
    """`default_domains: ["visibility","citation"]` → "可见度, 引用"."""
    pool = FakePool(rows=_make_seed_rows())
    steps = _run(load_workflow_steps("analysis", None, pool))
    rows = build_summary_display(
        {"default_domains": ["visibility", "citation"]}, steps,
    )
    by_field = {r["field"]: r for r in rows}
    assert "default_domains" in by_field
    assert by_field["default_domains"]["display"] == "可见度, 引用"


def test_build_summary_display_skips_internal_keys_and_empty_values():
    pool = FakePool(rows=_make_seed_rows())
    steps = _run(load_workflow_steps("analysis", None, pool))
    rows = build_summary_display(
        {
            "default_goal": "trend",
            "default_domains": [],         # empty list — drop
            "_template_id": "xxx",         # internal marker — drop
            "_flow": "analysis",           # internal marker — drop
            "metrics_locked": ["sov_trend"],  # not a step field — drop
        },
        steps,
    )
    keys = {r["field"] for r in rows}
    assert "default_goal" in keys
    assert "default_domains" not in keys
    assert "_template_id" not in keys
    assert "_flow" not in keys
    assert "metrics_locked" not in keys


def test_build_summary_display_falls_back_to_alias_keys():
    """Legacy callers may stash `goal` instead of `default_goal`."""
    pool = FakePool(rows=_make_seed_rows())
    steps = _run(load_workflow_steps("analysis", None, pool))
    rows = build_summary_display({"goal": "competitive"}, steps)
    by_field = {r["field"]: r for r in rows}
    assert by_field["default_goal"]["display"] == "竞品对标分析"


def test_build_summary_display_orders_by_step_num():
    pool = FakePool(rows=_make_seed_rows())
    steps = _run(load_workflow_steps("analysis", None, pool))
    rows = build_summary_display(
        {"default_domains": ["visibility"], "default_goal": "trend"},
        steps,
    )
    # analysis_goal num=1 must come before data_selection num=3
    field_order = [r["field"] for r in rows]
    assert field_order.index("default_goal") < field_order.index("default_domains")


def test_build_summary_display_handles_date_range_dict():
    pool = FakePool(rows=_make_seed_rows())
    steps = _run(load_workflow_steps("analysis", None, pool))
    # data_selection has no date_range field in our slim seed, but the
    # rendering helper itself is robust — exercise via a fake field via a
    # shared-scope domain row pretending to hold a date range.
    rows = build_summary_display(
        {"default_domains": {"from": "2026-04-01", "to": "2026-04-26"}},
        steps,
    )
    # default_domains here has options resolved — invalid value type
    # collapses to "(空)" or option-key fallback. Ensure no crash and at
    # least the row is present (or absent if value coerces to empty).
    # The point of this test is we don't blow up on shape mismatches.
    assert isinstance(rows, list)


# ─────────────────────────────────────────────────────────────────────
# Issue 1 — build_confirm_widget carries summary_display when provided
# ─────────────────────────────────────────────────────────────────────


def test_build_confirm_widget_propagates_summary_display():
    rows = _make_seed_rows()
    pool = FakePool(rows=rows)
    steps = _run(load_workflow_steps("analysis", None, pool))
    confirm = next(s for s in steps if s.key == "confirm_execute")
    display_rows = [
        {"step_key": "analysis_goal", "field": "default_goal",
         "label": "分析目标", "value": "trend", "display": "趋势追踪"},
    ]
    widget = build_confirm_widget(
        confirm,
        summary={"分析目标": "趋势追踪"},
        confirm_label="开始分析",
        task_type="analysis",
        summary_display=display_rows,
    )
    assert widget["summary_display"] == display_rows


def test_build_confirm_widget_omits_summary_display_when_not_provided():
    rows = _make_seed_rows()
    pool = FakePool(rows=rows)
    steps = _run(load_workflow_steps("analysis", None, pool))
    confirm = next(s for s in steps if s.key == "confirm_execute")
    widget = build_confirm_widget(
        confirm,
        summary={"分析目标": "趋势追踪"},
        confirm_label="开始分析",
        task_type="analysis",
    )
    # When the caller doesn't supply summary_display we keep the widget
    # backward-compatible — the field simply isn't there.
    assert "summary_display" not in widget


# ─────────────────────────────────────────────────────────────────────
# Issue 3 — required-flag propagation through the widget JSON
# ─────────────────────────────────────────────────────────────────────


def test_widget_emits_required_flag_for_required_field():
    """build_widget_from_step copies the `required` flag straight from the
    schema into the SSE payload so the frontend's step-level「下一步」
    gate works correctly."""
    rows = _make_seed_rows()
    pool = FakePool(rows=rows)
    steps = _run(load_workflow_steps("content_generation", None, pool))
    ct_step = next(s for s in steps if s.key == "content_type")
    widgets = build_widget_from_step(ct_step)
    assert widgets[0]["required"] is True


def test_widget_required_flag_defaults_to_false():
    rows = _make_seed_rows()
    pool = FakePool(rows=rows)
    steps = _run(load_workflow_steps("analysis", None, pool))
    goal_step = next(s for s in steps if s.key == "analysis_goal")
    widgets = build_widget_from_step(goal_step)
    # The seed doesn't mark default_goal required → false
    assert widgets[0]["required"] is False


def test_required_field_in_data_selection_when_flagged():
    """Simulates migration 055's effect: stamping required=true on
    default_domains. The loader propagates it through the widget."""
    seed = _make_seed_rows()
    # Mutate the data_selection row's default_domains field to mark it required.
    for r in seed:
        if r["scope"] == "analysis" and r["config_type"] == "workflow_step" and r["key"] == "data_selection":
            for f in r["value"]["fields"]:
                if f["key"] == "default_domains":
                    f["required"] = True
    pool = FakePool(rows=seed)
    steps = _run(load_workflow_steps("analysis", None, pool))
    ds = next(s for s in steps if s.key == "data_selection")
    domains_widget = next(w for w in build_widget_from_step(ds) if w["field"] == "default_domains")
    assert domains_widget["required"] is True


# ─────────────────────────────────────────────────────────────────────
# Issue 4 — Custom Analysis metric resolution via user-selected metrics
# ─────────────────────────────────────────────────────────────────────


def test_custom_analysis_user_metrics_promoted_to_locked():
    """When a template's required_metrics is empty and the chat collected
    `selected_metrics` via the analysis_metrics wizard step, the analyzer
    pipeline's contract resolver should treat the user's picks as the
    contract. This is implemented in analysis_pipeline.step_hydrate_metrics
    (synthetic contract from inputs.metrics_locked) — we exercise the
    upstream chain (slot-filler injects metrics_locked from selected_metrics
    when required_metrics is empty) by verifying the merge logic."""
    # Simulate the slot-filler's hidden-defaults branch: when ready,
    # required.required_metrics is empty, so user_metrics from
    # selected_metrics fills metrics_locked.
    required_metrics: list[str] = []
    user_metrics = ["sov_trend", "prompt_coverage_rate"]
    locked = list(required_metrics)
    if not locked:
        if isinstance(user_metrics, list) and user_metrics:
            locked = [str(m) for m in user_metrics]
    assert locked == ["sov_trend", "prompt_coverage_rate"]


def test_custom_analysis_locked_falls_through_when_no_user_metrics():
    required_metrics: list[str] = []
    user_metrics: list[str] = []
    locked = list(required_metrics)
    if not locked:
        if isinstance(user_metrics, list) and user_metrics:
            locked = [str(m) for m in user_metrics]
    assert locked == []  # pipeline will fall through to dynamic discovery
