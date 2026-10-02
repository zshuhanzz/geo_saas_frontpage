"""
Action Agent Sub-graph — DB-driven Content Pipeline Slot-Filling.

Step list comes from ``geo_workflow_config`` (config_type=workflow_step,
scope=content_generation) plus the per-template ``wizard_config`` JSONB.
There are no hardcoded step orders, labels or option lists — the same
single source of truth that drives the SaaS Wizard UI also drives this
chat sub-graph.

Canonical content scope steps (display order):
  num=0  mode_gate           生成模式 (我来定 / AI 帮我发现)
  num=1  content_type        内容类型
  num=2  data_scope          数据范围 (topics + prompts + analyzer ref)
  num=3  content_goal        内容目标 (RATF metrics + subgoals)
  num=4  content_strategy    内容策略 (auto-generated)
  num=5  generation_config   生成配置 (count, depth, platforms, language, product_facts)
  num=6  confirm_execute     确认执行
  num=10 analysis_import     (deprecated, disabled by default — never emitted)

Mode gate behavior:
  When the user picks ``ai_discover`` at step ``mode_gate``, downstream
  steps that have a default value will be auto-filled and skipped (the
  user only confirms). When the user picks ``manual``, every step shows
  for explicit selection.

Hidden defaults (Phase F) — ``required_metrics`` + ``required_subgoals``
from the template's ``wizard_config`` are injected into the final
``task_inputs`` as ``metrics_locked`` / ``subgoals_locked`` right before
``task_ready=True`` is emitted.
"""
import json
import logging
from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage, HumanMessage
from google.genai import types

from models.state import ActionState
from llm.client import get_genai_client, get_model_id, generate_content
from context.pruner import get_prune_max_turns, prune_messages
from services.workflow_config import (
    build_confirm_widget,
    build_summary_display,
    build_widget_from_step,
    load_template_required,
    load_workflow_steps,
)

logger = logging.getLogger(__name__)


DEFAULT_CONTENT_TEMPLATE_NAME = "自定义内容"


# ─────────────────────────────────────────────────────────────
# Slot-filling system prompt — DB-driven steps
# ─────────────────────────────────────────────────────────────

SLOT_FILL_SYSTEM = """You are Anthony, a GEO content strategy assistant for the AnswerX platform.

**重要 — 始终使用用户最近一条消息的语言回复**：如果用户用中文，你必须用中文；如果用户用英文，你必须用英文。Widget 选项的英文 ID（如 "manual"、"faq"）不算用户消息，不要被它们影响语言判断。
**Important — Always reply in the language of the user's MOST RECENT message.** If the user writes in Chinese, you must respond in Chinese. If the user writes in English, you must respond in English. Widget response payloads (English IDs like "manual", "faq") are NOT user messages — never let them flip your output language.

Your job is to help the user define a content generation task.

## Workflow Steps (DB-driven, {step_count} enabled)

Guide the user through these steps **one at a time**, in the listed order.
At the very first turn, briefly tell the user the step list, then begin with the first step.
If a step is OPTIONAL and the user says "跳过" / "skip", use the default value and move on.

{step_specs}

## Mode gate semantics

If the workflow includes a ``mode_gate`` step:
  * When the user picks ``manual`` ("我来定"), proceed step-by-step normally.
  * When the user picks ``ai_discover`` ("AI 帮我发现"), tell the user the
    AI will pre-fill the rest of the configuration based on existing GEO
    data, then jump straight to the confirm step. The user only reviews.

{brand_context}

## Handling widget responses
When the user sends a message that starts with '{{"type": "widget_response"', it is a structured widget response.
Extract the "field" and "value" fields. Use these to populate the corresponding task input directly.
Then immediately advance to the next step.

## Your behavior:
- Show the user the option list for the current step rather than just naming the step.
- Track which step you are on via "current_step_key" — must be one of: {step_keys_csv}.
- Collect ONE step per turn unless the user provides multiple values upfront.
- Be concise and friendly, use Chinese if the user writes in Chinese.
- NEVER ask the user to type a UUID manually. The widget handles selection.
- When the last step is reached and all required values are filled, set is_ready=true and stop asking.

## Output format (JSON):
{{
  "message": "Your response to the user (in their language)",
  "current_step_key": "<one of the step keys above>",
  "task_inputs": {{ ... arbitrary collected fields keyed by the step's field key ... }},
  "is_ready": true/false,
  "missing_fields": ["field_key", ...]
}}"""


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

async def _resolve_template_id(pool, task_inputs: dict) -> str:
    """Find the content-template id (priority: task_inputs._template_id,
    else the active builtin ``自定义内容`` row).
    """
    tid = task_inputs.get("_template_id")
    if isinstance(tid, str) and tid:
        return tid
    row = await pool.fetchrow(
        """
        SELECT id FROM geo_report_templates
        WHERE name = $1 AND task_type = 'content_generation' AND is_active = true
        ORDER BY is_builtin DESC, sort_order LIMIT 1
        """,
        DEFAULT_CONTENT_TEMPLATE_NAME,
    )
    if not row:
        raise RuntimeError(
            f"No active content_generation template named "
            f"{DEFAULT_CONTENT_TEMPLATE_NAME!r}; Anthony Chat needs at least "
            "the builtin fallback template seeded before it can render the "
            "content wizard."
        )
    return str(row["id"])


def _build_content_summary(task_inputs: dict, all_steps: list) -> dict:
    """Render the final confirmation card from collected inputs.

    Pulls option labels from the resolved step list (DB-sourced) so we
    never duplicate the option-label dictionary in this file.
    """
    summary: dict[str, str] = {}

    def _label_for(step_key: str, field_key: str, value):
        step = next((s for s in all_steps if s.key == step_key), None)
        if step is None:
            return None
        f = next((f for f in step.fields if f.key == field_key), None)
        if f is None:
            return None
        if isinstance(value, list):
            label_map = {o["key"]: o["label"] for o in f.options}
            return ", ".join(label_map.get(str(k), str(k)) for k in value)
        label_map = {o["key"]: o["label"] for o in f.options}
        return label_map.get(str(value), str(value))

    if task_inputs.get("mode_choice"):
        summary["生成模式"] = _label_for("mode_gate", "mode_choice", task_inputs["mode_choice"]) or task_inputs["mode_choice"]

    ct = task_inputs.get("default") or task_inputs.get("content_type")
    if ct:
        summary["内容类型"] = _label_for("content_type", "default", ct) or str(ct)

    metrics = task_inputs.get("default_metrics") or task_inputs.get("selected_metrics")
    if metrics:
        summary["质量维度"] = _label_for("content_goal", "default_metrics", metrics) or ", ".join(metrics)
    sub_goals = task_inputs.get("default_sub_goals") or task_inputs.get("selected_subgoals")
    if sub_goals:
        summary["子目标"] = _label_for("content_goal", "default_sub_goals", sub_goals) or ", ".join(sub_goals)

    plats = task_inputs.get("default_ai_platforms") or task_inputs.get("ai_platforms")
    if plats:
        summary["AI 平台"] = _label_for("generation_config", "default_ai_platforms", plats) or ", ".join(plats)
    if task_inputs.get("default_count") or task_inputs.get("count"):
        summary["生成数量"] = str(task_inputs.get("default_count") or task_inputs.get("count"))
    if task_inputs.get("default_depth") or task_inputs.get("depth"):
        d = task_inputs.get("default_depth") or task_inputs.get("depth")
        summary["生成深度"] = _label_for("generation_config", "default_depth", d) or str(d)
    lang = task_inputs.get("default_language") or task_inputs.get("language")
    if lang:
        summary["输出语言"] = str(lang)
    if task_inputs.get("default_publish_platform") or task_inputs.get("publish_platform"):
        summary["发布平台"] = str(task_inputs.get("default_publish_platform") or task_inputs.get("publish_platform"))

    pf = task_inputs.get("default_product_facts") or task_inputs.get("product_facts")
    if isinstance(pf, dict):
        filled = sum(1 for v in pf.values() if v and str(v).strip())
        summary["产品事实"] = f"{filled} 项已填写" if filled else "未填写"
    elif pf:
        summary["产品事实"] = "已填写"

    if task_inputs.get("topic_ids"):
        ids = task_inputs["topic_ids"]
        summary["目标话题"] = f"{len(ids)} 个" if isinstance(ids, list) else str(ids)
    if task_inputs.get("prompt_ids"):
        ids = task_inputs["prompt_ids"]
        summary["目标 Prompts"] = f"{len(ids)} 个" if isinstance(ids, list) else str(ids)
    if task_inputs.get("analyzer_task_id"):
        summary["参考报告"] = "已绑定 Analyzer 任务"

    return summary


def _is_step_auto_fillable(step, task_inputs: dict) -> bool:
    """In ``ai_discover`` mode, a step is auto-skipped if every field has a
    default value resolved (either from the template or already collected).

    Steps that are skipped this way contribute their default values straight
    into ``task_inputs`` without ever showing a widget.
    """
    if step.key in ("mode_gate", "confirm_execute"):
        return False
    for f in step.fields:
        if f.type == "execution_preview":
            continue
        already = task_inputs.get(f.key)
        has_default = f.default_value is not None
        if (already is None or already == "" or already == []) and not has_default:
            # Required field without default → can't auto-fill
            if f.required:
                return False
    return True


# ─────────────────────────────────────────────────────────────
# Action planner node — DB-driven slot-fill
# ─────────────────────────────────────────────────────────────

async def action_planner_node(state: ActionState) -> dict:
    """Parse user's request, extract slots, advance through DB-driven steps."""
    from database import get_pool
    pool = await get_pool()

    model_id = await get_model_id("flash")
    client = await get_genai_client(model_id, role="flash")

    user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    existing_inputs = dict(state.get("task_inputs") or {})
    existing_inputs["_flow"] = "content"

    # ── Parse widget responses (single or batch) ───────────
    try:
        parsed = json.loads(user_message)
        if parsed.get("type") == "widget_response":
            if "responses" in parsed:
                for r in parsed["responses"]:
                    if r.get("field") and r.get("value") is not None:
                        existing_inputs[r["field"]] = r["value"]
            elif parsed.get("field") and parsed.get("value") is not None:
                existing_inputs[parsed["field"]] = parsed["value"]
    except (json.JSONDecodeError, TypeError):
        pass

    # ── Resolve template + load workflow ──────────────────
    template_id = await _resolve_template_id(pool, existing_inputs)
    existing_inputs["_template_id"] = template_id

    all_steps = await load_workflow_steps(scope="content_generation", template_id=template_id, pool=pool)
    enabled_steps = [s for s in all_steps if s.enabled]
    if not enabled_steps:
        raise RuntimeError(
            f"content_generation template {template_id!r} has no enabled "
            "wizard steps. Check wizard_config.steps in the DB."
        )
    step_keys = [s.key for s in enabled_steps]

    persisted_key = existing_inputs.pop("_current_step_key", step_keys[0])
    if persisted_key not in step_keys:
        persisted_key = step_keys[0]

    # ── Auto-fill default values for enabled steps the user hasn't touched.
    # Do this AFTER widget-response merge so user choices always win, but
    # BEFORE we ask the LLM "what should we do next" — that lets the LLM
    # see a populated state and skip already-answered steps.
    for step in enabled_steps:
        for f in step.fields:
            if f.type == "execution_preview":
                continue
            if f.key in existing_inputs:
                continue
            if f.default_value is not None:
                existing_inputs[f.key] = f.default_value

    # ── Build brand context ───────────────────────────────
    brand_profile = state.get("brand_profile")
    brand_parts = []
    if brand_profile:
        if brand_profile.get("brand_name"):
            brand_parts.append(f"Brand: {brand_profile['brand_name']}")
        if brand_profile.get("tone_of_voice"):
            brand_parts.append(f"Tone: {brand_profile['tone_of_voice']}")
    brand_context = "Brand context: " + ", ".join(brand_parts) if brand_parts else ""
    if brand_profile and brand_profile.get("_memory_context"):
        brand_context += f"\n{brand_profile['_memory_context']}"

    # ── Render step specs from DB (no hardcoded labels) ─────
    step_specs_lines = []
    for s in enabled_steps:
        field_lines = []
        for f in s.fields:
            field_lines.append(
                f"  - field={f.key} type={f.type} required={f.required} "
                f"options={[o['key'] for o in f.options][:8]} "
                f"default={f.default_value!r}"
            )
        spec = (
            f"### Step #{s.num}: {s.label} (key={s.key})\n"
            f"{s.description}\n"
            + "\n".join(field_lines)
        )
        step_specs_lines.append(spec)
    step_specs = "\n\n".join(step_specs_lines)

    system = SLOT_FILL_SYSTEM.format(
        brand_context=brand_context,
        step_count=len(enabled_steps),
        step_specs=step_specs,
        step_keys_csv=", ".join(step_keys),
    )

    # ── Build conversation history (pruned) ────────────────
    pruned = prune_messages(state["messages"], max_turns=await get_prune_max_turns())
    contents = []
    for msg in pruned:
        if isinstance(msg, HumanMessage):
            contents.append(types.Content(role="user", parts=[types.Part(text=msg.content)]))
        elif isinstance(msg, AIMessage) and msg.content:
            contents.append(types.Content(role="model", parts=[types.Part(text=msg.content)]))

    state_hint = (
        f"\n[SYSTEM STATE] current_step_key={persisted_key}, "
        f"collected_inputs={json.dumps({k: v for k, v in existing_inputs.items() if not k.startswith('_')}, ensure_ascii=False)}"
    )
    if contents and contents[-1].role == "user":
        last_text = contents[-1].parts[0].text
        contents[-1] = types.Content(role="user", parts=[types.Part(text=last_text + state_hint)])
    else:
        contents.append(types.Content(role="user", parts=[types.Part(text=state_hint)]))

    response = await generate_content(
        client, model_id,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=2048,
        ),
    )

    try:
        result = json.loads(response.text)
        if isinstance(result, list):
            result = result[0] if result and isinstance(result[0], dict) else {}
        if not isinstance(result, dict):
            result = {}
    except (json.JSONDecodeError, TypeError):
        result = {}

    # ── Cold-start fallback message ─────────────────────────
    if not result.get("message"):
        first = enabled_steps[0]
        intro_lines = "\n".join(
            f"{idx + 1}. **{s.label}** — {s.description}"
            for idx, s in enumerate(enabled_steps)
        )
        result = {
            "message": (
                f"让我帮您创建内容生成任务！我们将分 {len(enabled_steps)} 步完成：\n"
                f"{intro_lines}\n\n"
                f"首先，{first.description or first.label}："
            ),
            "current_step_key": first.key,
            "task_inputs": {},
            "is_ready": False,
            "missing_fields": [f.key for f in first.fields if f.required],
            **result,
        }

    message_text = result.get("message", "")
    new_inputs = result.get("task_inputs", {}) or {}
    is_ready = bool(result.get("is_ready", False))
    current_step_key = result.get("current_step_key") or persisted_key
    if current_step_key not in step_keys:
        current_step_key = persisted_key

    # ── Merge collected inputs (user choices win) ──────────
    merged_inputs = dict(existing_inputs)
    for k, v in new_inputs.items():
        if v is None or v == "" or v == []:
            continue
        merged_inputs[k] = v

    # NB: Keep `default_*` keys in LangGraph state — they match the
    # widget.field names the LLM sees in step_specs, so the slot-fill
    # prompt stays in sync across turns. The chat→pipeline rename
    # happens at the SSE `task_ready` emit boundary in main.py
    # (`normalize_chat_inputs_to_pipeline_shape`), so DB inputs and
    # pipelines see plain keys without breaking the LLM's view.

    # ── Mode gate: if user picked ai_discover, skip optional steps ─
    mode = merged_inputs.get("mode_choice")
    if mode == "ai_discover" and not is_ready:
        # Pre-fill every auto-fillable step's defaults (already injected
        # above) and jump straight to confirm if the only remaining step
        # is confirm_execute.
        remaining = [s for s in enabled_steps if s.key not in {"mode_gate"}]
        all_filled = all(_is_step_auto_fillable(s, merged_inputs) or s.key == "confirm_execute" for s in remaining)
        if all_filled:
            confirm = next((s for s in enabled_steps if s.key == "confirm_execute"), None)
            if confirm is not None:
                current_step_key = confirm.key

    merged_inputs["_flow"] = "content"
    merged_inputs["_current_step_key"] = current_step_key
    merged_inputs["_template_id"] = template_id

    # ── Hidden defaults injection (Phase F) ────────────────
    if is_ready:
        required = await load_template_required(template_id, "content_generation", pool)
        merged_inputs["metrics_locked"] = required["required_metrics"]
        merged_inputs["subgoals_locked"] = required["required_subgoals"]

    # ── Render widgets for current step ────────────────────
    # When ``is_ready=True`` we used to emit a TaskConfirmWidget here too
    # (with its own 「开始生成」 button). The chat frontend then turned the
    # subsequent ``task_ready`` SSE event into a SECOND ChatTaskCard with
    # ANOTHER 「开始执行」 button — duplicate confirmation cards. Fix: when
    # ready, emit ZERO widgets and let main.py's ``task_ready`` SSE event
    # be the single confirmation surface. ``_summary_display`` carries the
    # translated Chinese-label rows for ChatTaskCard to render.
    cur_step = next((s for s in enabled_steps if s.key == current_step_key), enabled_steps[0])
    is_confirm = cur_step.key == "confirm_execute" or any(
        f.type == "execution_preview" for f in cur_step.fields
    )
    if is_ready:
        merged_inputs["_summary_display"] = build_summary_display(merged_inputs, all_steps)
        widgets = []
    elif is_confirm:
        summary = _build_content_summary(merged_inputs, all_steps)
        summary_display = build_summary_display(merged_inputs, all_steps)
        widgets = [build_confirm_widget(
            cur_step,
            summary=summary,
            summary_display=summary_display,
            confirm_label="开始生成",
            task_type="content_generation",
        )]
    else:
        widgets = build_widget_from_step(cur_step)

    logger.info(
        "[ACTION] Slot-fill: step=%s ready=%s widgets=%d "
        "inputs=%s",
        current_step_key, is_ready, len(widgets),
        json.dumps({k: v for k, v in merged_inputs.items() if not k.startswith('_')}, ensure_ascii=False)[:200],
    )

    return {
        "content_type": merged_inputs.get("default") or merged_inputs.get("content_type", ""),
        "task_inputs": merged_inputs,
        "task_ready": is_ready,
        "messages": [AIMessage(content=message_text)],
        "widgets": widgets,
    }


def build_action_graph() -> StateGraph:
    """Build the Action Agent sub-graph.

    Single planner node — the multi-turn slot-filling is driven by the
    LangGraph checkpointer. ``main.py`` watches for ``task_ready=True``
    in the planner's output and emits the SSE ``task_ready`` event.
    """
    graph = StateGraph(ActionState)
    graph.add_node("action_planner", action_planner_node)
    graph.set_entry_point("action_planner")
    graph.add_edge("action_planner", END)
    return graph
