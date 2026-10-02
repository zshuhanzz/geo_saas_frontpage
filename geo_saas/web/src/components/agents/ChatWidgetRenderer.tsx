/**
 * ChatWidgetRenderer — interactive widget cards rendered inline in the chat
 * thread. The Agent emits an SSE `widget` event per slot and the renderer
 * collects one piece of structured user input per type. When all widgets in
 * a turn are resolved the parent batches the responses back into an
 * `widget_response` message.
 *
 * Supported widget_types (the union must stay in sync with the backend's
 * `WidgetEvent.widget_type` literal):
 *
 *   single_select              — radio-style card grid (inherits goal cards)
 *   multi_select               — chip group with min / max bounds
 *   date_range                 — start + end date pair
 *   text_input                 — single-line free text
 *   text_area                  — multi-line free text (rows configurable)
 *   number                     — numeric input with min / max
 *   structured_input           — legacy product facts form (kept for back-compat)
 *   product_facts_form         — schema-driven product fact card
 *   mode_gate                  — "I'll decide" / "Let AI find" two-card gate
 *   topic_ref_picker           — topic picker filtered by viz/citation/sentiment
 *   prompt_ref_picker          — prompt picker filtered by perf
 *   analyzer_import            — completed analyzer task picker (Opportunity Discovery)
 *   chart_config_builder       — list of NL Query + chart type rows
 *   methodology_snippet_picker — multi-select methodology snippets
 *   chat_text_prompt           — display-only prompt; next user chat reply becomes value
 *   prompt_editor              — minimal prompt textarea (no var-catalog, no expand dialog)
 *   boolean_toggle             — Switch + label for boolean field types
 *   task_confirm               — legacy summary card with Start CTA (kept for back-compat)
 *   confirmation_card          — Phase D rewrite: per-step rows with inline edit buttons
 *
 * Visual grammar follows the canonical wizard (`geo_saas/web/src/components/wizard`)
 * but compressed to chat-bubble width (max-w-2xl ≈ 672px). Iconography matches
 * lucide-react's wizard usage so users moving between Wizard UI and Chat see the
 * same vocabulary.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  CheckCircle2, ChevronRight, Calendar, ArrowRight, Play,
  Target, TrendingUp, Search, Shield, MessageSquare,
  Sparkles, Hand, Loader2, AlertTriangle, ArrowUpDown,
  Lock, SkipForward, Plus, X, Package, ChevronUp, ChevronDown,
  Pencil, BookOpen,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  getRankedTopics,
  getRankedPrompts,
  getOpportunityTasks,
  getAgentTask,
  type OpportunityTaskSummary,
} from "@/lib/api";
import { useSaaS } from "@/contexts/SaaSContext";

// ─── Types ──────────────────────────────────────────────────

export type WidgetType =
  | "single_select"
  | "multi_select"
  | "date_range"
  | "text_input"
  | "text_area"
  | "number"
  | "structured_input"
  | "product_facts_form"
  | "mode_gate"
  | "topic_ref_picker"
  | "prompt_ref_picker"
  | "analyzer_import"
  | "chart_config_builder"
  | "methodology_snippet_picker"
  | "chat_text_prompt"
  | "prompt_editor"
  | "boolean_toggle"
  | "task_confirm"
  | "confirmation_card";

export interface WidgetEvent {
  widget_id: string;
  widget_type: WidgetType;
  field: string;
  label?: string;
  description?: string;
  options?: WidgetOption[];
  default_value?: any;
  placeholder?: string;
  config?: Record<string, any>;
  summary?: Record<string, any>;
  /**
   * For confirmation_card: ordered list of step-level rows the agent has
   * already collected. Each row maps to one widget the user previously
   * resolved, with a stable `field` so the chat can ask the agent to re-emit
   * that step on edit.
   */
  steps?: ConfirmationStep[];
  /** Step grouping metadata — backend workflow_config builder attaches these
   *  to every widget. The chat AssistantMessage groups widgets sharing the
   *  same `step_key` under one step card with a single "下一步" button. */
  step_key?: string;
  step_num?: number;
  step_label?: string;
  step_description?: string;
  /** Whether this field must be filled before the step can advance. The
   *  step-level "下一步" button is disabled while any required field is empty,
   *  but "跳过剩余" can submit defaults for non-required fields. */
  required?: boolean;
}

export interface ConfirmationStep {
  /** Unique key — usually the workflow_step.key (e.g. "analysis_goal"). */
  step_key: string;
  /** Display label for the row ("分析目标"). */
  label: string;
  /** The value to render. Strings, arrays, or pre-rendered display strings. */
  value?: any;
  /** Optional pre-formatted display string (overrides automatic value->string). */
  display?: string;
  /**
   * The wizard `field` key that owns this step's data. The chat sends this
   * back to the agent on Edit so the agent knows which step to re-emit.
   * Falls back to step_key when not provided.
   */
  field?: string;
  /** Whether this row is editable. Confirmation rows for hidden defaults
   *  (required_metrics etc) should set editable=false. */
  editable?: boolean;
}

export interface WidgetOption {
  id: string;
  label: string;
  description?: string;
  icon?: string;
  color?: string;
  recommended?: boolean;
}

export interface WidgetResponse {
  widget_id: string;
  field: string;
  value: any;
  /**
   * Internal hint flags. The agent backend uses these to interpret the
   * response. `edit_request` triggers a re-emit of the named step.
   */
  meta?: {
    edit_request?: boolean;
    target_field?: string;
    target_step_key?: string;
  };
}

interface ChatWidgetRendererProps {
  widget: WidgetEvent;
  resolved?: boolean;
  resolvedValue?: any;
  onRespond: (response: WidgetResponse) => void;
  /**
   * Optional callback fired whenever the widget's draft value changes (any
   * click/type/toggle). Used by the step-level submit button in
   * AssistantMessage to collect "live values" without each widget needing to
   * fire its own onRespond. Pure observer — the widget keeps its own state.
   */
  onValueChange?: (value: any, opts?: { valid?: boolean }) => void;
  /**
   * When true, the per-widget primary confirm button is hidden so the
   * step-level「下一步 →」button at the bottom of the step group becomes the
   * single source of submission. Skip / clear / auto-prefill secondaries
   * stay visible because they don't advance the flow.
   */
  hideConfirm?: boolean;
}

// ─── Icon resolver (matches goal card icon names from DB) ───

const ICON_MAP: Record<string, typeof Target> = {
  Target, TrendingUp, Search, Shield, MessageSquare,
  Sparkles, Hand, BookOpen, Package,
};

function resolveIcon(name?: string) {
  if (!name) return null;
  return ICON_MAP[name] || null;
}

// ─── Main Renderer ──────────────────────────────────────────

export default function ChatWidgetRenderer(props: ChatWidgetRendererProps) {
  const { widget } = props;
  switch (widget.widget_type) {
    case "single_select":
      return <SingleSelect {...props} />;
    case "multi_select":
      return <MultiSelect {...props} />;
    case "date_range":
      return <DateRangeWidget {...props} />;
    case "text_input":
      return <TextInputWidget {...props} multiline={false} />;
    case "text_area":
      return <TextInputWidget {...props} multiline={true} />;
    case "number":
      return <NumberInputWidget {...props} />;
    case "structured_input":
    case "product_facts_form":
      return <ProductFactsWidget {...props} />;
    case "mode_gate":
      return <ModeGateWidget {...props} />;
    case "topic_ref_picker":
      return <TopicRefPickerWidget {...props} />;
    case "prompt_ref_picker":
      return <PromptRefPickerWidget {...props} />;
    case "analyzer_import":
      return <AnalyzerImportWidget {...props} />;
    case "chart_config_builder":
      return <ChartConfigBuilderWidget {...props} />;
    case "methodology_snippet_picker":
      return <MethodologySnippetPickerWidget {...props} />;
    case "chat_text_prompt":
      return <ChatTextPromptWidget {...props} />;
    case "prompt_editor":
      return <PromptEditorWidget {...props} />;
    case "boolean_toggle":
      return <BooleanToggleWidget {...props} />;
    case "task_confirm":
      return <TaskConfirmWidget {...props} />;
    case "confirmation_card":
      return <ConfirmationCardWidget {...props} />;
    default:
      return null;
  }
}

/**
 * Helper type for individual widget components — most widgets only need
 * `widget`, `resolved`, `resolvedValue`, `onRespond` (legacy single-confirm
 * mode). The new `onValueChange` + `hideConfirm` props let the step-level
 * footer button drive submission across multiple sibling widgets.
 */
type WidgetProps = ChatWidgetRendererProps;

// ─── WidgetHeader: shared label + description block ─────────

function WidgetHeader({ label, description, hint }: { label?: string; description?: string; hint?: string }) {
  if (!label && !description && !hint) return null;
  return (
    <div className="space-y-0.5">
      {label && (
        <p className="text-xs font-medium text-muted-foreground/80">
          {label}
          {hint && <span className="text-muted-foreground/50 ml-1">{hint}</span>}
        </p>
      )}
      {description && (
        <p className="text-[11px] text-muted-foreground/60 leading-relaxed">{description}</p>
      )}
    </div>
  );
}

// ─── SingleSelect: Goal-style card grid ─────────────────────

function SingleSelect({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const [selected, setSelected] = useState<string | null>(resolvedValue || widget.default_value || null);
  const options = widget.options || [];

  // Surface initial draft (default value) and any user change to the parent
  // so the step-level submit can read it without a per-widget Confirm click.
  useEffect(() => {
    onValueChange?.(selected, { valid: !!selected });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const handleConfirm = useCallback(() => {
    if (!selected) return;
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: selected });
  }, [selected, widget, onRespond]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <div className="grid grid-cols-2 gap-2">
        {options.map((opt) => {
          const isSelected = selected === opt.id;
          const isResolved = resolved && resolvedValue === opt.id;
          const IconComp = resolveIcon(opt.icon);
          return (
            <button
              key={opt.id}
              disabled={resolved}
              onClick={() => setSelected(opt.id)}
              className={`relative text-left p-3 rounded-xl border transition-all duration-200 ${
                isResolved
                  ? "border-primary/50 bg-primary/5"
                  : isSelected
                  ? "border-primary ring-1 ring-primary/30 bg-primary/5"
                  : "border-border/50 hover:border-border hover:bg-muted/30"
              } ${resolved && !isResolved ? "opacity-40" : ""}`}
            >
              <div className="flex items-center gap-2 mb-1">
                {IconComp && <IconComp className={`h-4 w-4 ${opt.color?.split(" ")[0] || "text-muted-foreground"}`} />}
                <span className="text-sm font-medium">{opt.label}</span>
                {opt.recommended && (
                  <span className="text-[10px] bg-amber-500/10 text-amber-500 px-1.5 py-0.5 rounded-full">{t("chatWidget.recommended")}</span>
                )}
              </div>
              {opt.description && (
                <p className="text-xs text-muted-foreground/70 line-clamp-2">{opt.description}</p>
              )}
              {(isSelected || isResolved) && (
                <div className="absolute top-2 right-2">
                  <CheckCircle2 className="h-4 w-4 text-primary" />
                </div>
              )}
            </button>
          );
        })}
      </div>
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" disabled={!selected} onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── MultiSelect: Chip-style multi-pick ─────────────────────

function MultiSelect({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const [selected, setSelected] = useState<string[]>(resolvedValue || widget.default_value || []);
  const options = widget.options || [];
  const min = widget.config?.min ?? 1;
  const max = widget.config?.max ?? options.length;

  useEffect(() => {
    onValueChange?.(selected, { valid: selected.length >= min });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= max) return prev;
      return [...prev, id];
    });
  }, [max]);

  const handleConfirm = useCallback(() => {
    if (selected.length < min) return;
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: selected });
  }, [selected, min, widget, onRespond]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader
        label={widget.label}
        description={widget.description}
        hint={max < options.length ? t("chatWidget.maxItems", { max }) : undefined}
      />
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const isOn = selected.includes(opt.id);
          const isResolvedItem = resolved && (resolvedValue || []).includes?.(opt.id);
          return (
            <button
              key={opt.id}
              disabled={resolved}
              onClick={() => toggle(opt.id)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm transition-all ${
                isResolvedItem
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : isOn
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border/50 text-muted-foreground hover:border-border hover:bg-muted/30"
              } ${resolved && !isResolvedItem ? "opacity-40" : ""}`}
            >
              {opt.icon && <span className="text-sm">{opt.icon}</span>}
              {opt.label}
              {isOn && <CheckCircle2 className="h-3.5 w-3.5" />}
            </button>
          );
        })}
      </div>
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" disabled={selected.length < min} onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── DateRange: Start + end date ─────────────────────────────

function DateRangeWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const defaults = widget.default_value || {};
  // Accept both {from, to} and {start, end} shapes from backend.
  const initialFrom = resolvedValue?.from ?? resolvedValue?.start ?? defaults.from ?? defaults.start ?? "";
  const initialTo = resolvedValue?.to ?? resolvedValue?.end ?? defaults.to ?? defaults.end ?? "";
  const [from, setFrom] = useState(initialFrom);
  const [to, setTo] = useState(initialTo);

  const handleConfirm = useCallback(() => {
    if (!from || !to) return;
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: { from, to, start: from, end: to } });
  }, [from, to, widget, onRespond]);

  useEffect(() => {
    const value = from && to ? { from, to, start: from, end: to } : null;
    onValueChange?.(value, { valid: !!(from && to) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 flex-1">
          <Calendar className="h-4 w-4 text-muted-foreground/50 shrink-0" />
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            disabled={resolved}
            className="flex-1 bg-background border border-border/50 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
        <ArrowRight className="h-4 w-4 text-muted-foreground/30 shrink-0" />
        <div className="flex items-center gap-1.5 flex-1">
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            disabled={resolved}
            className="flex-1 bg-background border border-border/50 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
      </div>
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" disabled={!from || !to} onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── TextInput / TextArea: free text (single or multi-line) ─

function TextInputWidget({
  widget,
  resolved,
  resolvedValue,
  onRespond,
  onValueChange,
  hideConfirm,
  multiline,
}: WidgetProps & { multiline: boolean }) {
  const { t } = useTranslation("agents");
  const [value, setValue] = useState(resolvedValue || widget.default_value || "");
  const rows = widget.config?.rows ?? (multiline ? 4 : 1);
  const minLen = Number(widget.config?.min_length ?? 0);
  const maxLen = Number(widget.config?.max_length ?? 0);

  useEffect(() => {
    const trimmed = value.trim();
    const valid = trimmed.length > 0 && (minLen === 0 || trimmed.length >= minLen);
    onValueChange?.(trimmed, { valid });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const handleConfirm = useCallback(() => {
    if (!value.trim()) return;
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: value.trim() });
  }, [value, widget, onRespond]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={widget.placeholder || ""}
          rows={rows}
          disabled={resolved}
          maxLength={maxLen > 0 ? maxLen : undefined}
          className="w-full bg-background border border-border/50 rounded-xl px-4 py-2.5 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/40"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={widget.placeholder || ""}
          disabled={resolved}
          maxLength={maxLen > 0 ? maxLen : undefined}
          className="w-full bg-background border border-border/50 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/40"
        />
      )}
      {maxLen > 0 && !resolved && (
        <div className="text-[10px] text-muted-foreground/50 text-right">
          {value.length}/{maxLen}
        </div>
      )}
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={!value.trim() || (minLen > 0 && value.trim().length < minLen)}
            onClick={handleConfirm}
            className="gap-1"
          >
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── NumberInput ────────────────────────────────────────────

function NumberInputWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const initial = resolvedValue ?? widget.default_value ?? "";
  const [value, setValue] = useState<string>(String(initial ?? ""));
  const min = widget.config?.min ?? widget.config?.min_value;
  const max = widget.config?.max ?? widget.config?.max_value;
  const step = widget.config?.step ?? 1;

  const numeric = useMemo(() => {
    if (value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }, [value]);

  const valid = useMemo(() => {
    if (numeric === null) return false;
    if (typeof min === "number" && numeric < min) return false;
    if (typeof max === "number" && numeric > max) return false;
    return true;
  }, [numeric, min, max]);

  const handleConfirm = useCallback(() => {
    if (!valid || numeric === null) return;
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: numeric });
  }, [valid, numeric, widget, onRespond]);

  useEffect(() => {
    onValueChange?.(numeric, { valid });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numeric, valid]);

  const hint = useMemo(() => {
    const parts: string[] = [];
    if (typeof min === "number") parts.push(`min ${min}`);
    if (typeof max === "number") parts.push(`max ${max}`);
    return parts.length > 0 ? `(${parts.join(" · ")})` : undefined;
  }, [min, max]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} hint={hint} />
      <input
        type="number"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        min={min}
        max={max}
        step={step}
        disabled={resolved}
        placeholder={widget.placeholder}
        className="w-40 bg-background border border-border/50 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
      />
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" disabled={!valid} onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── ProductFactsWidget (also handles legacy structured_input) ─

function ProductFactsWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const subFields = useMemo<string[]>(() => {
    const fromConfig = widget.config?.fields;
    if (Array.isArray(fromConfig) && fromConfig.length > 0) {
      return fromConfig.map((f: any) => (typeof f === "string" ? f : f.key)).filter(Boolean);
    }
    const fromSchema = widget.config?.schema?.key_features;
    if (Array.isArray(fromSchema) && fromSchema.length > 0) return fromSchema;
    return ["specs", "features", "differentiators"];
  }, [widget.config]);

  const [values, setValues] = useState<Record<string, string>>(() => {
    const init = (resolvedValue || widget.default_value || {}) as Record<string, string>;
    const out: Record<string, string> = {};
    for (const k of subFields) out[k] = typeof init[k] === "string" ? init[k] : "";
    return out;
  });
  const [expanded, setExpanded] = useState(true);

  const meta = useCallback(
    (key: string): { label: string; placeholder: string } => {
      const lbl = t(`chatWidget.productFacts.${key}Label`, { defaultValue: key });
      const ph = t(`chatWidget.productFacts.${key}Placeholder`, { defaultValue: "" });
      return { label: lbl, placeholder: ph };
    },
    [t],
  );

  const handleChange = useCallback((key: string, val: string) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  }, []);

  const filledCount = subFields.reduce((acc, k) => (values[k]?.trim() ? acc + 1 : acc), 0);

  const handleConfirm = useCallback(() => {
    const nonEmpty = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v.trim()),
    );
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: nonEmpty });
  }, [values, widget, onRespond]);

  useEffect(() => {
    const nonEmpty = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v.trim()),
    );
    // Product facts is always optional — any (even empty) submission counts as
    // valid. Step-level submit needs `valid: true` to not block "下一步".
    onValueChange?.(nonEmpty, { valid: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <div className="border border-border/50 rounded-xl bg-muted/10 overflow-hidden">
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="w-full flex items-center justify-between px-3 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          disabled={resolved}
        >
          <span className="flex items-center gap-2">
            <Package className="h-4 w-4 text-cyan-400" />
            <span className="font-medium">{t("chatWidget.productFacts.expand")}</span>
            {filledCount > 0 && (
              <span className="text-[10px] font-normal px-1.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                {t("chatWidget.productFacts.filledStatus", { filled: filledCount, total: subFields.length })}
              </span>
            )}
          </span>
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {expanded && (
          <div className="px-3 pb-3 space-y-3">
            {subFields.map((key) => {
              const { label, placeholder } = meta(key);
              return (
                <div key={key}>
                  <label className="text-[11px] font-medium text-muted-foreground/70 mb-1 block">{label}</label>
                  <textarea
                    value={values[key] || ""}
                    onChange={(e) => handleChange(key, e.target.value)}
                    placeholder={placeholder}
                    rows={2}
                    disabled={resolved}
                    className="w-full bg-background border border-border/30 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/40"
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── ModeGate: "I'll decide / Let AI find" two-card gate ────

function ModeGateWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const initial = resolvedValue ?? widget.default_value ?? null;
  const [selected, setSelected] = useState<string | null>(initial);

  // Default options match the canonical wizard ModeGatePicker. Backend may
  // override via widget.options if it wants different copy.
  const options = useMemo<WidgetOption[]>(() => {
    if (Array.isArray(widget.options) && widget.options.length > 0) return widget.options;
    return [
      {
        id: "manual",
        label: t("chatWidget.modeGate.manualLabel"),
        description: t("chatWidget.modeGate.manualDescription"),
        icon: "Hand",
      },
      {
        id: "ai_discover",
        label: t("chatWidget.modeGate.autoLabel"),
        description: t("chatWidget.modeGate.autoDescription"),
        icon: "Sparkles",
      },
    ];
  }, [widget.options, t]);

  const handleConfirm = useCallback(() => {
    if (!selected) return;
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: selected });
  }, [selected, widget, onRespond]);

  useEffect(() => {
    onValueChange?.(selected, { valid: !!selected });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {options.map((opt) => {
          const isSelected = selected === opt.id;
          const isResolved = resolved && resolvedValue === opt.id;
          // Map known icon strings (legacy emoji or lucide name) to a concrete
          // lucide component. Fall back to Hand vs Sparkles based on key.
          const iconName = opt.icon || (opt.id === "ai_discover" ? "Sparkles" : "Hand");
          const Icon = (ICON_MAP[iconName] ||
            (iconName === "✨" ? Sparkles : iconName === "✍️" ? Hand : opt.id === "ai_discover" ? Sparkles : Hand)) as typeof Sparkles;
          return (
            <button
              key={opt.id}
              type="button"
              disabled={resolved}
              onClick={() => setSelected(opt.id)}
              className={`group text-left p-4 rounded-xl border-2 transition-all duration-200 ${
                isResolved
                  ? "border-primary/50 bg-primary/5"
                  : isSelected
                  ? "border-primary bg-primary/5 shadow-sm shadow-primary/10"
                  : "border-border bg-card hover:border-primary/40"
              } ${resolved && !isResolved ? "opacity-40" : ""}`}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-colors ${
                    isSelected
                      ? "bg-primary/15 text-primary"
                      : "bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary"
                  }`}
                >
                  <Icon className="h-5 w-5" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{opt.label}</span>
                    <span
                      className={`text-[10px] shrink-0 w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center transition-colors ${
                        isSelected ? "border-primary bg-primary" : "border-muted-foreground/40"
                      }`}
                    >
                      {isSelected && <span className="w-1 h-1 rounded-full bg-primary-foreground" />}
                    </span>
                  </div>
                  {opt.description && (
                    <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">{opt.description}</p>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" disabled={!selected} onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── Topic Ref Picker ───────────────────────────────────────

interface TopicItem {
  id: string;
  topic_name: string;
  prompt_count: number;
  mention_count: number;
  citation_count: number;
  negative_count: number;
}

type SortMode = "visibility" | "citation" | "sentiment";
// Module-scope const can't call useTranslation; store the i18n key and call
// t(labelKey) at the render site (`agents.json` -> `chatWidget.sort.*`).
const SORT_OPTIONS = [
  { id: "visibility", labelKey: "chatWidget.sort.visibility" },
  { id: "citation", labelKey: "chatWidget.sort.citation" },
  { id: "sentiment", labelKey: "chatWidget.sort.sentiment" },
] as const satisfies readonly { id: SortMode; labelKey: `chatWidget.sort.${SortMode}` }[];

function classifyTier(index: number, total: number, criticalThreshold: number, attentionThreshold: number) {
  if (total < 6) {
    return index < Math.ceil(total / 3) ? "critical" : "attention";
  }
  if (index < criticalThreshold) return "critical";
  if (index < attentionThreshold) return "attention";
  return "healthy";
}

function TopicRefPickerWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const { clientId } = useSaaS();
  const isSingle = widget.config?.single === true;
  const allowEmpty = widget.config?.allow_empty === true;
  const autoPrefillCount = typeof widget.config?.auto_prefill_count === "number"
    ? widget.config.auto_prefill_count
    : 3;
  // Sort dimension can be hinted via config.sort_by — visibility by default.
  const sortByRaw: string = String(widget.config?.sort_by || "visibility");
  const sortBy: SortMode = useMemo(() => {
    const s = sortByRaw.toLowerCase();
    if (s.includes("citation")) return "citation";
    if (s.includes("sentiment") || s.includes("negative")) return "sentiment";
    return "visibility";
  }, [sortByRaw]);

  const initial = useMemo<string[]>(() => {
    const v = resolvedValue ?? widget.default_value;
    if (isSingle) {
      return typeof v === "string" && v ? [v] : [];
    }
    return Array.isArray(v) ? v : [];
  }, [resolvedValue, widget.default_value, isSingle]);

  const [selected, setSelected] = useState<string[]>(initial);
  const [topics, setTopics] = useState<TopicItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Prefer options provided by backend (already filtered) — fall back to fetch.
  useEffect(() => {
    const provided = widget.options;
    if (Array.isArray(provided) && provided.length > 0) {
      // Each option is expected to carry topic perf metadata (mention_count, etc.)
      setTopics(
        provided.map((o: any) => ({
          id: o.id ?? o.topic_id ?? o.key ?? "",
          topic_name: o.label ?? o.topic_name ?? o.name ?? "",
          prompt_count: Number(o.prompt_count ?? 0),
          mention_count: Number(o.mention_count ?? o.viz_score ?? 0),
          citation_count: Number(o.citation_count ?? 0),
          negative_count: Number(o.negative_count ?? 0),
        })),
      );
      setLoading(false);
      return;
    }
    if (!clientId) return;
    let cancelled = false;
    setLoading(true);
    getRankedTopics(clientId, sortBy, 30)
      .then((data: TopicItem[]) => { if (!cancelled) setTopics(data || []); })
      .catch((e: Error) => { if (!cancelled) setError(e.message || "failed to load topics"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [clientId, sortBy, widget.options]);

  function toggle(id: string) {
    if (resolved) return;
    if (isSingle) {
      setSelected(selected[0] === id ? [] : [id]);
      return;
    }
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function autoPrefill() {
    if (resolved || topics.length === 0) return;
    const n = Math.min(autoPrefillCount, topics.length);
    const top = topics.slice(0, n).map((tp) => tp.id);
    setSelected(isSingle ? [top[0]] : top);
  }

  function handleConfirm() {
    if (!allowEmpty && selected.length === 0) return;
    const value = isSingle ? selected[0] || "" : selected;
    onRespond({ widget_id: widget.widget_id, field: widget.field, value });
  }

  useEffect(() => {
    const value = isSingle ? selected[0] || "" : selected;
    const valid = allowEmpty || selected.length > 0;
    onValueChange?.(value, { valid });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, isSingle, allowEmpty]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-1.5">
            <ArrowUpDown className="h-3 w-3 text-muted-foreground" />
            {SORT_OPTIONS.map((opt) => (
              <span
                key={opt.id}
                className={`text-[10px] px-2 py-0.5 rounded-md border ${
                  sortBy === opt.id
                    ? "border-primary/50 bg-primary/10 text-primary font-medium"
                    : "border-border text-muted-foreground"
                }`}
              >
                {t(opt.labelKey)}
              </span>
            ))}
          </div>
          {!resolved && topics.length > 0 && (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 text-xs"
                onClick={autoPrefill}
              >
                <Sparkles className="h-3 w-3 text-amber-500" />
                {isSingle
                  ? t("chatWidget.topicPicker.autoSelectOne")
                  : t("chatWidget.topicPicker.autoSelectN", { count: Math.min(autoPrefillCount, topics.length) })}
              </Button>
              {selected.length > 0 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs text-muted-foreground"
                  onClick={() => setSelected([])}
                >
                  {t("chatWidget.topicPicker.clear")}
                </Button>
              )}
            </div>
          )}
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("chatWidget.topicPicker.loading")}
          </div>
        ) : error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        ) : topics.length === 0 ? (
          <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-3 text-center text-xs text-muted-foreground">
            {t("chatWidget.topicPicker.empty")}
          </div>
        ) : (
          <div className="space-y-1 max-h-[280px] overflow-y-auto">
            {topics.map((tp, idx) => {
              const on = selected.includes(tp.id);
              const tier = classifyTier(idx, topics.length, 3, 8);
              return (
                <button
                  key={tp.id}
                  type="button"
                  onClick={() => toggle(tp.id)}
                  disabled={resolved}
                  className={`w-full text-left p-2.5 rounded-lg border text-sm transition-colors ${
                    on
                      ? "border-primary/40 bg-primary/5 text-foreground"
                      : "border-border text-muted-foreground hover:border-primary/30"
                  } ${resolved ? "cursor-default" : "cursor-pointer"}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate flex-1 text-sm font-medium">{tp.topic_name}</span>
                    <div className="flex items-center gap-1 shrink-0">
                      {tier === "critical" && (
                        <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/30 inline-flex items-center gap-0.5">
                          <AlertTriangle className="h-2.5 w-2.5" />
                          {t("chatWidget.topicPicker.tierBad")}
                        </span>
                      )}
                      {tier === "attention" && (
                        <span className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                          {t("chatWidget.topicPicker.tierOptimize")}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded ${
                        sortBy === "visibility" ? "bg-blue-500/10 text-blue-400 font-medium" : "text-muted-foreground"
                      }`}
                    >
                      {t("chatWidget.topicPicker.mentions")} {tp.mention_count}
                    </span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded ${
                        sortBy === "citation" ? "bg-green-500/10 text-green-400 font-medium" : "text-muted-foreground"
                      }`}
                    >
                      {t("chatWidget.topicPicker.citations")} {tp.citation_count}
                    </span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded ${
                        sortBy === "sentiment" ? "bg-red-500/10 text-red-400 font-medium" : "text-muted-foreground"
                      }`}
                    >
                      {t("chatWidget.topicPicker.negative")} {tp.negative_count}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded text-muted-foreground">
                      {t("chatWidget.topicPicker.promptCount", { count: tp.prompt_count })}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {selected.length > 0 && (
          <p className="text-[11px] text-muted-foreground">
            {t("chatWidget.topicPicker.selectedCount", { count: selected.length })}
          </p>
        )}
      </div>

      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={!allowEmpty && selected.length === 0}
            onClick={handleConfirm}
            className="gap-1"
          >
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── Prompt Ref Picker ──────────────────────────────────────

interface PromptItem {
  id: string;
  prompt_text: string;
  platform: string;
  topic_name?: string;
  mention_count?: number;
  citation_count?: number;
  negative_count?: number;
}

function PromptRefPickerWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const { clientId } = useSaaS();
  const minCount = Number(widget.config?.min_count ?? 0);
  const maxCount = Number(widget.config?.max_count ?? 0);
  const allowEmpty = widget.config?.allow_empty === true || minCount === 0;
  const autoPrefillCount = Number(widget.config?.auto_prefill_count ?? 5);
  const lockedFromConfig: string[] = Array.isArray(widget.config?.locked_prompt_ids)
    ? widget.config!.locked_prompt_ids
    : [];

  const sortByRaw: string = String(widget.config?.sort_by || "visibility");
  const sortBy: SortMode = useMemo(() => {
    const s = sortByRaw.toLowerCase();
    if (s.includes("citation")) return "citation";
    if (s.includes("sentiment") || s.includes("negative")) return "sentiment";
    return "visibility";
  }, [sortByRaw]);

  const isLocked = lockedFromConfig.length > 0;
  const initial: string[] = useMemo(() => {
    if (isLocked) return lockedFromConfig;
    const v = resolvedValue ?? widget.default_value;
    return Array.isArray(v) ? v : [];
  }, [resolvedValue, widget.default_value, isLocked, lockedFromConfig]);

  const [selected, setSelected] = useState<string[]>(initial);
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const provided = widget.options;
    if (Array.isArray(provided) && provided.length > 0) {
      setPrompts(
        provided.map((o: any) => ({
          id: o.id ?? o.prompt_id ?? o.key ?? "",
          prompt_text: o.label ?? o.prompt_text ?? "",
          platform: o.platform ?? "",
          topic_name: o.topic_name,
          mention_count: Number(o.mention_count ?? 0),
          citation_count: Number(o.citation_count ?? 0),
          negative_count: Number(o.negative_count ?? 0),
        })),
      );
      setLoading(false);
      return;
    }
    if (!clientId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRankedPrompts(clientId, sortBy, isLocked ? 200 : 50)
      .then((data: PromptItem[]) => {
        if (cancelled) return;
        if (isLocked) {
          const ids = new Set(lockedFromConfig);
          setPrompts((data || []).filter((p) => ids.has(p.id)));
        } else {
          setPrompts(data || []);
        }
      })
      .catch((e: Error) => { if (!cancelled) setError(e.message || "failed to load prompts"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, sortBy, isLocked, widget.options, lockedFromConfig.join(",")]);

  function toggle(id: string) {
    if (isLocked || resolved) return;
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((p) => p !== id);
      if (maxCount > 0 && prev.length >= maxCount) return prev;
      return [...prev, id];
    });
  }

  function autoPrefill() {
    if (isLocked || resolved || prompts.length === 0) return;
    const n = Math.min(autoPrefillCount, prompts.length);
    setSelected(prompts.slice(0, n).map((p) => p.id));
  }

  function handleConfirm() {
    if (!allowEmpty && selected.length < Math.max(1, minCount)) return;
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: selected });
  }

  const canConfirm = isLocked || (allowEmpty || selected.length >= Math.max(1, minCount));

  useEffect(() => {
    onValueChange?.(selected, { valid: canConfirm });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, canConfirm]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      {isLocked && (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-amber-500/30 text-amber-400">
            <Lock className="w-2.5 h-2.5" />
            {t("chatWidget.promptPicker.locked")}
          </span>
          <span className="text-[11px] text-amber-400/80">
            {t("chatWidget.promptPicker.lockedHint", { count: lockedFromConfig.length })}
          </span>
        </div>
      )}
      <div className="space-y-2">
        {!isLocked && (
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-1.5">
              <ArrowUpDown className="h-3 w-3 text-muted-foreground" />
              {SORT_OPTIONS.map((opt) => (
                <span
                  key={opt.id}
                  className={`text-[10px] px-2 py-0.5 rounded-md border ${
                    sortBy === opt.id
                      ? "border-primary/50 bg-primary/10 text-primary font-medium"
                      : "border-border text-muted-foreground"
                  }`}
                >
                  {t(opt.labelKey)}
                </span>
              ))}
            </div>
            {!resolved && prompts.length > 0 && (
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 text-xs"
                  onClick={autoPrefill}
                >
                  <Sparkles className="h-3 w-3 text-amber-500" />
                  {t("chatWidget.promptPicker.autoSelectN", { count: Math.min(autoPrefillCount, prompts.length) })}
                </Button>
                {selected.length > 0 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs text-muted-foreground"
                    onClick={() => setSelected([])}
                  >
                    {t("chatWidget.promptPicker.clear")}
                  </Button>
                )}
              </div>
            )}
          </div>
        )}

        {loading ? (
          <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("chatWidget.promptPicker.loading")}
          </div>
        ) : error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        ) : prompts.length === 0 ? (
          <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-3 text-center text-xs text-muted-foreground">
            {t("chatWidget.promptPicker.empty")}
          </div>
        ) : (
          <div className="space-y-1 max-h-[280px] overflow-y-auto">
            {prompts.map((p, idx) => {
              const on = selected.includes(p.id);
              const tier = classifyTier(idx, prompts.length, 5, 15);
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => toggle(p.id)}
                  disabled={isLocked || resolved}
                  className={`w-full text-left p-2.5 rounded-lg border text-sm transition-colors ${
                    on
                      ? "border-orange-500/40 bg-orange-500/5 text-foreground"
                      : "border-border text-muted-foreground hover:border-orange-500/30"
                  } ${isLocked || resolved ? "cursor-default opacity-85" : "cursor-pointer"}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate flex-1 text-xs">{p.prompt_text}</span>
                    <div className="flex items-center gap-1 shrink-0">
                      {!isLocked && tier === "critical" && (
                        <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/30 inline-flex items-center gap-0.5">
                          <AlertTriangle className="h-2.5 w-2.5" />
                          {t("chatWidget.promptPicker.tierBad")}
                        </span>
                      )}
                      {!isLocked && tier === "attention" && (
                        <span className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                          {t("chatWidget.promptPicker.tierOptimize")}
                        </span>
                      )}
                      {p.platform && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted-foreground">
                          {p.platform}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded ${
                        sortBy === "visibility" ? "bg-blue-500/10 text-blue-400 font-medium" : "text-muted-foreground"
                      }`}
                    >
                      {t("chatWidget.promptPicker.mentions")} {p.mention_count ?? 0}
                    </span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded ${
                        sortBy === "citation" ? "bg-green-500/10 text-green-400 font-medium" : "text-muted-foreground"
                      }`}
                    >
                      {t("chatWidget.promptPicker.citations")} {p.citation_count ?? 0}
                    </span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded ${
                        sortBy === "sentiment" ? "bg-red-500/10 text-red-400 font-medium" : "text-muted-foreground"
                      }`}
                    >
                      {t("chatWidget.promptPicker.negative")} {p.negative_count ?? 0}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {selected.length > 0 && !isLocked && (
          <p className="text-[11px] text-muted-foreground">
            {t("chatWidget.promptPicker.selectedCount", { count: selected.length })}
          </p>
        )}
      </div>

      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={!canConfirm}
            onClick={handleConfirm}
            className="gap-1"
          >
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── Analyzer Import ────────────────────────────────────────

function AnalyzerImportWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const { clientId } = useSaaS();
  const required = widget.config?.required === true;
  // Backend can pass options directly. Otherwise self-fetch.
  const initial = (resolvedValue ?? widget.default_value) as
    | { task_id?: string | null; context?: any }
    | string
    | null
    | undefined;
  const initialTaskId = typeof initial === "string"
    ? initial
    : (initial && typeof initial === "object" ? initial.task_id || null : null);

  const [tasks, setTasks] = useState<OpportunityTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(initialTaskId);
  const [contextCache, setContextCache] = useState<Record<string, unknown> | null>(
    typeof initial === "object" && initial && initial.context ? initial.context : null,
  );

  useEffect(() => {
    const provided = widget.options;
    if (Array.isArray(provided) && provided.length > 0) {
      setTasks(
        provided.map((o: any) => ({
          id: o.id ?? o.task_id,
          task_name: o.label ?? o.task_name ?? "Opportunity Discovery",
          status: o.status ?? "COMPLETED",
          completed_at: o.completed_at ?? null,
          topic_scope: o.topic_scope ?? null,
          summary: {
            topic_count: Number(o.topic_count ?? 0),
            opportunity_count: Number(o.opportunity_count ?? 0),
          },
        })) as unknown as OpportunityTaskSummary[],
      );
      setLoading(false);
      return;
    }
    if (!clientId) return;
    let cancelled = false;
    setLoading(true);
    getOpportunityTasks(clientId)
      .then((rows) => { if (!cancelled) setTasks(rows || []); })
      .catch(() => { if (!cancelled) setTasks([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [clientId, widget.options]);

  async function handleSelect(taskId: string) {
    if (selecting || resolved) return;
    setSelecting(true);
    setSelectedId(taskId);
    try {
      const task = await getAgentTask(taskId, clientId);
      const ctx = task.output || null;
      setContextCache(ctx);
    } catch {
      setContextCache(null);
    } finally {
      setSelecting(false);
    }
  }

  function handleSkip() {
    setSelectedId(null);
    setContextCache(null);
  }

  function handleConfirm() {
    if (required && !selectedId) return;
    onRespond({
      widget_id: widget.widget_id,
      field: widget.field,
      value: { task_id: selectedId, context: contextCache },
    });
  }

  useEffect(() => {
    const value = { task_id: selectedId, context: contextCache };
    const valid = !required || !!selectedId;
    onValueChange?.(value, { valid });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, contextCache, required]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      {loading ? (
        <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t("chatWidget.analyzerImport.loading")}
        </div>
      ) : tasks.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-3 text-center text-xs text-muted-foreground">
          {t("chatWidget.analyzerImport.empty")}
        </div>
      ) : (
        <div className="space-y-2 max-h-[280px] overflow-y-auto">
          {tasks.map((tk) => {
            const isSel = selectedId === tk.id;
            return (
              <button
                key={tk.id}
                type="button"
                disabled={resolved}
                onClick={() => handleSelect(tk.id)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  isSel
                    ? "border-amber-500/60 bg-amber-500/5"
                    : "border-border bg-muted/40 hover:border-amber-500/30"
                } ${resolved ? "cursor-default opacity-85" : "cursor-pointer"}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">
                      {tk.task_name || "Opportunity Discovery"}
                    </p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {tk.completed_at ? new Date(tk.completed_at).toLocaleDateString() : ""}
                      {tk.topic_scope ? ` · ${tk.topic_scope}` : ""}
                    </p>
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {t("chatWidget.analyzerImport.topicsCount", { count: tk.summary?.topic_count ?? 0 })}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {t("chatWidget.analyzerImport.opportunitiesCount", { count: tk.summary?.opportunity_count ?? 0 })}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
      {!resolved && (
        <div className="flex items-center justify-between gap-2 pt-1">
          {selecting ? (
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              ...
            </span>
          ) : selectedId ? (
            <span className="text-[11px] text-amber-500">{t("chatWidget.analyzerImport.selected")}</span>
          ) : (
            <span className="text-[11px] text-muted-foreground/70">&nbsp;</span>
          )}
          <div className="flex items-center gap-2">
            {!required && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleSkip}
                className="text-muted-foreground hover:text-foreground gap-1"
              >
                <SkipForward className="w-3.5 h-3.5" />
                {t("chatWidget.analyzerImport.skip")}
              </Button>
            )}
            {!hideConfirm && (
              <Button
                size="sm"
                disabled={required && !selectedId}
                onClick={handleConfirm}
                className="gap-1"
              >
                {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Chart Config Builder ───────────────────────────────────

interface ChartReq {
  query: string;
  chart_type: string;
  sql_hint?: string;
}

const CHART_TYPE_ORDER = ["auto", "line", "bar", "pie"] as const;

function ChartConfigBuilderWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const initial = (resolvedValue ?? widget.default_value) as ChartReq[] | undefined;
  // Backend may also use `nl_query` — accept both.
  const normalize = (rows: any[] | undefined): ChartReq[] => {
    if (!Array.isArray(rows)) return [];
    return rows.map((r) => ({
      query: String(r?.query ?? r?.nl_query ?? ""),
      chart_type: String(r?.chart_type ?? "auto"),
      ...(r?.sql_hint ? { sql_hint: String(r.sql_hint) } : {}),
    }));
  };
  const [charts, setCharts] = useState<ChartReq[]>(normalize(initial));

  const addChart = useCallback(() => {
    setCharts((prev) => [...prev, { query: "", chart_type: "auto" }]);
  }, []);
  const removeChart = useCallback((i: number) => {
    setCharts((prev) => prev.filter((_, idx) => idx !== i));
  }, []);
  const patchChart = useCallback((i: number, patch: Partial<ChartReq>) => {
    setCharts((prev) => prev.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  }, []);

  const labelFor = (k: string): string => {
    if (k === "auto") return t("chatWidget.chartConfig.typeAuto");
    if (k === "line") return t("chatWidget.chartConfig.typeLine");
    if (k === "bar") return t("chatWidget.chartConfig.typeBar");
    if (k === "pie") return t("chatWidget.chartConfig.typePie");
    return k;
  };

  function buildWireValue() {
    const cleaned = charts.filter((c) => c.query.trim().length > 0);
    return cleaned.map((c) => ({
      query: c.query.trim(),
      nl_query: c.query.trim(),
      chart_type: c.chart_type,
      ...(c.sql_hint ? { sql_hint: c.sql_hint } : {}),
    }));
  }

  function handleConfirm() {
    // Empty list is allowed — backend's confirm_execute step just produces a text-only report.
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: buildWireValue() });
  }

  useEffect(() => {
    // Charts can be empty (text-only report fallback) — always valid.
    onValueChange?.(buildWireValue(), { valid: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [charts]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <div className="space-y-2">
        {charts.map((req, i) => (
          <div key={i} className="flex gap-2 items-start p-3 rounded-lg border border-border/50 bg-muted/10">
            <div className="flex-1 space-y-2">
              <textarea
                value={req.query}
                onChange={(e) => patchChart(i, { query: e.target.value })}
                placeholder={t("chatWidget.chartConfig.queryPlaceholder")}
                rows={2}
                disabled={resolved}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs resize-none focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] text-muted-foreground">
                  {t("chatWidget.chartConfig.chartTypeLabel")}:
                </span>
                {CHART_TYPE_ORDER.map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => patchChart(i, { chart_type: k })}
                    disabled={resolved}
                    className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                      req.chart_type === k
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted hover:bg-muted/80"
                    }`}
                  >
                    {labelFor(k)}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              onClick={() => removeChart(i)}
              disabled={resolved}
              className="text-muted-foreground hover:text-destructive transition-colors mt-1"
              aria-label={t("chatWidget.chartConfig.removeChart")}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
        {!resolved && (
          <button
            type="button"
            onClick={addChart}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border-2 border-dashed border-border hover:border-primary/40 hover:bg-muted/20 text-xs text-muted-foreground hover:text-foreground transition-all"
          >
            <Plus className="h-3.5 w-3.5" />
            {t("chatWidget.chartConfig.addChart")}
          </button>
        )}
        {charts.length === 0 && (
          <p className="text-[11px] text-center text-muted-foreground">
            {t("chatWidget.chartConfig.emptyHint")}
          </p>
        )}
      </div>
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── Methodology Snippet Picker ─────────────────────────────

function MethodologySnippetPickerWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const options = widget.options || [];
  const initial = useMemo<string[]>(() => {
    const v = resolvedValue ?? widget.default_value;
    return Array.isArray(v) ? v : [];
  }, [resolvedValue, widget.default_value]);
  const [selected, setSelected] = useState<string[]>(initial);

  function toggle(id: string) {
    if (resolved) return;
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function handleConfirm() {
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: selected });
  }

  useEffect(() => {
    // Methodology snippets are always optional — empty list is valid.
    onValueChange?.(selected, { valid: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      {options.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-3 text-center text-xs text-muted-foreground">
          {t("chatWidget.methodology.empty")}
        </div>
      ) : (
        <div className="space-y-1.5 max-h-[280px] overflow-y-auto">
          {options.map((opt) => {
            const on = selected.includes(opt.id);
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => toggle(opt.id)}
                disabled={resolved}
                className={`w-full text-left p-2.5 rounded-lg border text-sm transition-colors ${
                  on
                    ? "border-primary/40 bg-primary/5 text-foreground"
                    : "border-border text-muted-foreground hover:border-primary/30"
                } ${resolved ? "cursor-default" : "cursor-pointer"}`}
              >
                <div className="flex items-start gap-2">
                  <BookOpen className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${on ? "text-primary" : "text-muted-foreground/50"}`} />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium">{opt.label}</div>
                    {opt.description && (
                      <p className="text-[11px] text-muted-foreground/70 mt-0.5 line-clamp-2">
                        {opt.description}
                      </p>
                    )}
                  </div>
                  {on && <CheckCircle2 className="h-3.5 w-3.5 text-primary shrink-0" />}
                </div>
              </button>
            );
          })}
        </div>
      )}
      {selected.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          {t("chatWidget.methodology.selectedCount", { count: selected.length })}
        </p>
      )}
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── Chat Text Prompt (display-only; next chat reply is the value) ─

function ChatTextPromptWidget({ widget, resolved }: WidgetProps) {
  const { t } = useTranslation("agents");

  // This widget renders ONLY a hint. The actual value comes from the user's
  // next chat message — AgentChat's text-input handler sees there's a pending
  // chat_text_prompt widget and forwards the next message as the response.
  // No confirm button; no input box.
  return (
    <div className="my-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      {!resolved && (
        <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-primary/80 bg-primary/5 border border-primary/20 rounded-full px-3 py-1">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
          {t("chatWidget.chatTextPrompt.waitingHint")}
        </div>
      )}
    </div>
  );
}

// ─── PromptEditor: chat-bubble version of the wizard prompt textarea ───
//
// Minimal-viable port of `geo_saas/web/src/components/wizard/customFields/
// PromptEditor.tsx` for the chat thread. Intentionally simpler than the
// wizard counterpart: no variable catalog, no methodology snippet picker,
// no expand-to-fullscreen dialog. Just a prefilled textarea bound to the
// current step's `default_prompt` (resolved by the backend's
// compute_default: prompt_template_with_metrics) and submit-via-step.
//
// The backend wires this up via geo_workflow_config field type
// "prompt_editor" → widget_type "prompt_editor" (see
// geo_agent/src/services/workflow_config.py FIELD_TYPE_TO_WIDGET).
//
// Limitation noted in WIZARD_ALIGNMENT_PLAN.md: the click-to-replace
// variable catalog is wizard-only for now. Chat users edit the resolved
// template as plain text.
function PromptEditorWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  // The widget arrives with `default_value` already populated by the
  // backend's prompt_template_with_metrics computer when a template is
  // bound to the chat session. If empty, fall back to a placeholder so
  // the user is never confused by a blank textarea.
  const initial = useMemo<string>(() => {
    if (typeof resolvedValue === "string" && resolvedValue.length > 0) return resolvedValue;
    if (typeof widget.default_value === "string" && widget.default_value.length > 0) return widget.default_value;
    return "";
  }, [resolvedValue, widget.default_value]);

  const [value, setValue] = useState<string>(initial);

  // Re-sync when the backend pushes a fresh default (e.g. on edit-row
  // re-emit). Cheap because edits are rare.
  useEffect(() => {
    setValue(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  // Always optional — empty string is a valid response (means "use
  // template default"). The trimmed value is what we submit.
  useEffect(() => {
    onValueChange?.(value, { valid: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const handleConfirm = useCallback(() => {
    onRespond({ widget_id: widget.widget_id, field: widget.field, value });
  }, [value, widget, onRespond]);

  const placeholder = widget.placeholder || t("chatWidget.promptEditor.placeholder");

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        rows={10}
        disabled={resolved}
        className="w-full bg-background border border-border/50 rounded-xl px-4 py-2.5 text-sm font-mono leading-relaxed resize-y focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/40 min-h-[160px]"
      />
      <p className="text-[10px] text-muted-foreground/60 leading-relaxed">
        {t("chatWidget.promptEditor.hint")}
      </p>
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── BooleanToggle: simple Switch + label ──────────────────────────
//
// Used for boolean fields in the workflow_step schema (e.g.
// `prompt_edit.disable_user_edit`, `prompt_edit.include_data_disclosure`).
// Backend maps field type "boolean" → widget_type "boolean_toggle" via
// FIELD_TYPE_TO_WIDGET.
function BooleanToggleWidget({ widget, resolved, resolvedValue, onRespond, onValueChange, hideConfirm }: WidgetProps) {
  const { t } = useTranslation("agents");
  const initial = useMemo<boolean>(() => {
    if (typeof resolvedValue === "boolean") return resolvedValue;
    if (typeof widget.default_value === "boolean") return widget.default_value;
    return false;
  }, [resolvedValue, widget.default_value]);
  const [checked, setChecked] = useState<boolean>(initial);

  useEffect(() => {
    onValueChange?.(checked, { valid: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checked]);

  const handleConfirm = useCallback(() => {
    onRespond({ widget_id: widget.widget_id, field: widget.field, value: checked });
  }, [checked, widget, onRespond]);

  return (
    <div className="my-3 space-y-2 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <div className="flex items-center justify-between gap-3 rounded-xl border border-border/50 bg-muted/10 px-4 py-3">
        <span className="text-sm text-foreground/85">
          {checked
            ? t("chatWidget.booleanToggle.on")
            : t("chatWidget.booleanToggle.off")}
        </span>
        <Switch
          checked={checked}
          onCheckedChange={setChecked}
          disabled={resolved}
          aria-label={widget.label || widget.field}
        />
      </div>
      {!resolved && !hideConfirm && (
        <div className="flex justify-end">
          <Button size="sm" onClick={handleConfirm} className="gap-1">
            {t("chatWidget.confirm")} <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ─── TaskConfirm: Legacy summary card with CTA ──────────────

function TaskConfirmWidget({ widget, resolved, resolvedValue: _resolvedValue, onRespond }: WidgetProps) {
  const { t } = useTranslation("agents");
  const summary = widget.summary || {};
  const taskType = widget.config?.task_type || "analysis";
  const [submitting, setSubmitting] = useState(false);

  const handleConfirm = useCallback(() => {
    if (submitting || resolved) return;
    setSubmitting(true);
    onRespond({
      widget_id: widget.widget_id,
      field: widget.field,
      value: { confirmed: true, task_type: taskType, inputs: summary },
    });
  }, [widget, taskType, summary, onRespond, submitting, resolved]);

  const labelFor = (key: string): string => {
    const FIELD_KEY = `chatWidget.confirmation.fieldLabel.${key}`;
    const fromConfirm = t(FIELD_KEY, { defaultValue: "" });
    if (fromConfirm) return fromConfirm;
    const CHAT_KEYS = new Set([
      "analysis_goal", "content_type", "domains", "platforms", "topic",
      "date_from", "date_to", "depth", "count", "language",
    ]);
    if (CHAT_KEYS.has(key)) return t(`chat.inputLabels.${key}`, { defaultValue: key });
    if (key === "content_goal") return t("chat.inputLabels.analysis_goal");
    return key;
  };

  if (resolved) {
    return (
      <div className="my-2 flex items-center gap-1.5 text-xs text-primary">
        <CheckCircle2 className="h-3.5 w-3.5" />
        <span>{t("chatWidget.executionConfirmed")}</span>
      </div>
    );
  }

  return (
    <div className="my-3 space-y-3 max-w-2xl">
      <WidgetHeader label={widget.label} description={widget.description} />
      <div className="border border-border/50 rounded-xl p-4 bg-gradient-to-br from-primary/5 to-transparent space-y-3">
        <div className="flex items-center gap-2 mb-2">
          <Play className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">{t("chatWidget.taskConfig")}</span>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
          {Object.entries(summary).map(([key, val]) => {
            if (val === null || val === undefined || val === "") return null;
            const display = Array.isArray(val) ? val.join(", ") : String(val);
            return (
              <div key={key} className="flex items-start gap-2 text-xs">
                <span className="text-muted-foreground/60 shrink-0 w-20 text-right">{labelFor(key)}</span>
                <span className="text-foreground/80">{display}</span>
              </div>
            );
          })}
        </div>
      </div>
      {!submitting ? (
        <div className="flex gap-2 justify-end">
          <Button size="sm" variant="default" onClick={handleConfirm} className="gap-1.5">
            <Play className="h-3.5 w-3.5" />
            {t("chatWidget.startExecution")}
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span>{t("chatWidget.submitting")}</span>
        </div>
      )}
    </div>
  );
}

// ─── ConfirmationCardWidget — Phase D rewrite ───────────────
//
// Renders a per-step summary table where every editable row has an inline
// pencil button. Clicking pencil sends a special widget response with
// `meta.edit_request: true` plus the target step's field/key — the backend
// then re-emits that step's widget so the user can change just that field
// without restarting the whole flow.
//
// The bottom CTA pair ("确认执行 →" / "修改 ←") submits a normal
// `confirmed: true` response or "modify" intent that the backend handles.

function ConfirmationCardWidget({ widget, resolved, onRespond }: WidgetProps) {
  const { t: tRaw } = useTranslation("agents");
  const t = tRaw as unknown as TFunc;
  const [submitting, setSubmitting] = useState(false);

  // Steps drive the rendering. If the backend forgot to send `steps`, fall
  // back to flattening `summary` into pseudo-rows so the UI degrades
  // gracefully (admin will see a visual reminder via the "noValue" copy).
  const steps: ConfirmationStep[] = useMemo(() => {
    if (Array.isArray(widget.steps) && widget.steps.length > 0) return widget.steps;
    const summary = widget.summary || {};
    return Object.entries(summary).map(([key, val]) => ({
      step_key: key,
      label: labelFromKey(key, t),
      value: val,
      field: key,
      editable: true,
    }));
  }, [widget.steps, widget.summary, t]);

  const labelFor = useCallback(
    (s: ConfirmationStep) => s.label || labelFromKey(s.step_key, t),
    [t],
  );

  function displayValue(s: ConfirmationStep): string {
    if (s.display) return s.display;
    return formatValueForDisplay(s.value, t);
  }

  function handleEdit(s: ConfirmationStep) {
    if (resolved || submitting) return;
    if (s.editable === false) return;
    onRespond({
      widget_id: widget.widget_id,
      field: widget.field,
      value: {
        action: "edit",
        target_step_key: s.step_key,
        target_field: s.field || s.step_key,
      },
      meta: {
        edit_request: true,
        target_step_key: s.step_key,
        target_field: s.field || s.step_key,
      },
    });
  }

  function handleConfirm() {
    if (resolved || submitting) return;
    setSubmitting(true);
    const taskType = widget.config?.task_type;
    const inputs = widget.summary || {};
    onRespond({
      widget_id: widget.widget_id,
      field: widget.field,
      value: { confirmed: true, action: "confirm", task_type: taskType, inputs },
    });
  }

  function handleModify() {
    if (resolved || submitting) return;
    onRespond({
      widget_id: widget.widget_id,
      field: widget.field,
      value: { action: "modify" },
      meta: { edit_request: true },
    });
  }

  if (resolved) {
    return (
      <div className="my-2 flex items-center gap-1.5 text-xs text-primary">
        <CheckCircle2 className="h-3.5 w-3.5" />
        <span>{t("chatWidget.executionConfirmed")}</span>
      </div>
    );
  }

  return (
    <div className="my-3 space-y-3 max-w-2xl">
      <div className="border border-border/50 rounded-xl bg-gradient-to-br from-primary/[0.04] to-transparent overflow-hidden">
        <div className="px-4 py-3 border-b border-border/40 bg-background/40">
          <div className="flex items-center gap-2">
            <Play className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">{widget.label || t("chatWidget.confirmation.title")}</span>
          </div>
          <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">
            {widget.description || t("chatWidget.confirmation.subtitle")}
          </p>
        </div>

        <div className="divide-y divide-border/30">
          {steps.map((s) => {
            const editable = s.editable !== false;
            const display = displayValue(s);
            return (
              <div key={s.step_key} className="flex items-start gap-3 px-4 py-2.5">
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] font-medium text-muted-foreground/80">
                    {labelFor(s)}
                  </div>
                  <div className="text-sm text-foreground/90 mt-0.5 break-words">
                    {display || (
                      <span className="italic text-muted-foreground/50">
                        {t("chatWidget.confirmation.noValue")}
                      </span>
                    )}
                  </div>
                </div>
                {editable && (
                  <button
                    type="button"
                    onClick={() => handleEdit(s)}
                    disabled={submitting}
                    className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] text-muted-foreground hover:text-primary hover:bg-primary/5 border border-transparent hover:border-primary/30 transition-colors"
                  >
                    <Pencil className="h-3 w-3" />
                    {t("chatWidget.confirmation.edit")}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <div className="px-4 py-3 flex items-center justify-end gap-2 bg-background/40 border-t border-border/40">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleModify}
            disabled={submitting}
            className="gap-1.5"
          >
            <ArrowRight className="h-3.5 w-3.5 rotate-180" />
            {t("chatWidget.confirmation.modify")}
          </Button>
          {submitting ? (
            <Button size="sm" disabled className="gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("chatWidget.submitting")}
            </Button>
          ) : (
            <Button size="sm" onClick={handleConfirm} className="gap-1.5">
              <Play className="h-3.5 w-3.5" />
              {t("chatWidget.confirmation.execute")}
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Helpers (label + value formatting for confirmation rows) ─

// Simplified t-callback signature to avoid the deep type instantiation that
// the i18next strict generics produce when chained through helpers.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TFunc = (key: string, opts?: any) => string;

function labelFromKey(key: string, t: TFunc): string {
  const fromConfirm = t(`chatWidget.confirmation.fieldLabel.${key}`, { defaultValue: "" });
  if (fromConfirm) return fromConfirm;
  const fromChat = t(`chat.inputLabels.${key}`, { defaultValue: "" });
  if (fromChat) return fromChat;
  return key;
}

function formatValueForDisplay(value: unknown, t: TFunc): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "";
    // Array of strings → join. Array of objects → describe count.
    if (value.every((v) => typeof v === "string" || typeof v === "number")) {
      return value.join(", ");
    }
    return t("chatWidget.confirmation.noValue", { defaultValue: `${value.length} items` });
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    // Date range shapes
    if ("from" in obj && "to" in obj) return `${obj.from} → ${obj.to}`;
    if ("start" in obj && "end" in obj) return `${obj.start} → ${obj.end}`;
    // Analyzer import shape
    if ("task_id" in obj) return obj.task_id ? String(obj.task_id) : "";
    // Product facts shape — show first non-empty key or "filled"
    const filled = Object.entries(obj).filter(([, v]) => typeof v === "string" && v.trim());
    if (filled.length > 0) {
      return filled.map(([k, v]) => `${k}: ${String(v).slice(0, 60)}`).join(" · ");
    }
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
