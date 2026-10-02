import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { Loader2, FileDown, ChevronRight, SkipForward, CheckCircle2 } from "lucide-react";
import { PremiumChart } from "@/components/charts/PremiumChart";
import { Button } from "@/components/ui/button";
import { exportChatAnalysisHTML } from "@/lib/api";
import ChatWidgetRenderer from "@/components/agents/ChatWidgetRenderer";
import type { WidgetResponse, WidgetEvent } from "@/components/agents/ChatWidgetRenderer";
import type { ChatMessage, WidgetEntry } from "../types";
import { ThinkingPanel } from "./ThinkingPanel";

/**
 * Single-widget step types — these own their UX (one big card with its own
 * primary action) and never share a step group with other widgets. The
 * step-level「下一步 →」footer button is suppressed for these.
 */
const SINGLE_OWN_UX_TYPES = new Set([
  "task_confirm",
  "confirmation_card",
  "chat_text_prompt",
]);

/**
 * Returns a stable group key for a widget. Widgets sharing the same
 * group key render under one step card with a single「下一步」button at
 * the bottom. Single-own-UX widgets (confirmation, chat_text_prompt) get
 * a unique key per widget so they always render standalone.
 */
function groupKeyForWidget(w: WidgetEntry, idx: number): string {
  if (SINGLE_OWN_UX_TYPES.has(w.widget_type)) {
    return `__solo_${idx}_${w.widget_id}`;
  }
  return w.step_key || `__nostep_${idx}`;
}

/**
 * Collect contiguous widgets sharing the same group key into ordered
 * groups, preserving original index for onWidgetRespond addressing.
 */
interface WidgetGroup {
  groupKey: string;
  step_key?: string;
  step_num?: number;
  step_label?: string;
  step_description?: string;
  /** All widgets in this group, paired with their original index in
   *  `msg.widgets[]` so we can call onWidgetRespond(resp, msgIdx, idx). */
  items: { widget: WidgetEntry; index: number }[];
}

function buildGroups(widgets: WidgetEntry[]): WidgetGroup[] {
  const groups: WidgetGroup[] = [];
  let current: WidgetGroup | null = null;
  widgets.forEach((w, i) => {
    const key = groupKeyForWidget(w, i);
    if (!current || current.groupKey !== key) {
      current = {
        groupKey: key,
        step_key: w.step_key,
        step_num: w.step_num,
        step_label: w.step_label,
        step_description: w.step_description,
        items: [],
      };
      groups.push(current);
    }
    current.items.push({ widget: w, index: i });
  });
  return groups;
}

/* AI message — flat Gemini-style (no bubble) */
export function AssistantMessage({
  msg,
  msgIdx,
  clientId,
  onWidgetRespond,
}: {
  msg: ChatMessage;
  msgIdx: number;
  clientId: string | null | undefined;
  onWidgetRespond: (resp: WidgetResponse, msgIdx: number, widgetIdx: number) => void;
}) {
  const { t } = useTranslation("agents");

  const groups = useMemo(() => buildGroups(msg.widgets || []), [msg.widgets]);
  // Total step count across this message — used to render "步骤 X/Y" badges
  // when multiple step groups land in one assistant turn (rare but possible
  // when the agent emits the next step's first widget alongside leftover
  // markers from the prior step).
  const totalSteps = useMemo(() => {
    const nums = new Set<number>();
    for (const g of groups) {
      if (typeof g.step_num === "number") nums.add(g.step_num);
    }
    return nums.size;
  }, [groups]);

  return (
    <div className="flex gap-4 items-start">
      <div className="w-8 h-8 rounded-xl overflow-hidden bg-gradient-to-br from-primary/20 to-primary/5 shrink-0 mt-0.5">
        <img src="/Anthony_Chat_Online.png" alt="Anthony" className="w-full h-full object-contain" />
      </div>
      <div className="flex-1 min-w-0 max-w-3xl space-y-1">
        {/* Thinking / Chain-of-Thought */}
        {msg.thinking && msg.thinking.length > 0 && (
          <ThinkingPanel steps={msg.thinking} streaming={msg.streaming && !msg.content} />
        )}
        {/* Main answer — flat, no background bubble */}
        {msg.content ? (
          <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-2 prose-headings:my-3 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-pre:my-3 prose-table:my-3 prose-pre:bg-slate-50 prose-pre:dark:bg-slate-900/80 prose-pre:border prose-pre:border-slate-200 prose-pre:dark:border-slate-700/50 prose-pre:rounded-xl prose-code:text-[13px] prose-code:font-mono text-foreground leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
              {msg.content}
            </ReactMarkdown>
            {msg.streaming && (
              <span className="inline-block w-0.5 h-5 bg-primary animate-pulse ml-0.5 align-text-bottom rounded-full" />
            )}
          </div>
        ) : msg.streaming ? (
          <div className="flex items-center gap-2 text-muted-foreground text-sm py-2">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span>{t("chat.generating")}</span>
          </div>
        ) : null}
        {/* Charts */}
        {msg.charts?.map((chart: any, ci: number) => (
          <PremiumChart
            key={ci}
            data={chart.data}
            xKey={chart.xKey}
            yKeys={chart.yKeys}
            type={chart.type}
            title={chart.title}
            nameKey={chart.nameKey}
            valueKey={chart.valueKey}
            meta={chart.meta}
            columns={chart.columns}
            rows={chart.rows}
            chart_type={chart.chart_type}
            nl_query={chart.nl_query}
          />
        ))}
        {/* Widgets — grouped by step_key with a step-level「下一步 →」button */}
        {groups.map((g) =>
          // Single-own-UX widgets render standalone (no step header / no batch button)
          g.items.length === 1 && SINGLE_OWN_UX_TYPES.has(g.items[0].widget.widget_type) ? (
            <ChatWidgetRenderer
              key={g.groupKey}
              widget={g.items[0].widget as WidgetEvent}
              resolved={g.items[0].widget.resolved}
              resolvedValue={g.items[0].widget.resolvedValue}
              onRespond={(resp) => onWidgetRespond(resp, msgIdx, g.items[0].index)}
            />
          ) : (
            <StepGroup
              key={g.groupKey}
              group={g}
              msgIdx={msgIdx}
              totalSteps={totalSteps}
              onWidgetRespond={onWidgetRespond}
            />
          ),
        )}
        {/* Export download button */}
        {msg.exportReady && clientId && (
          <div className="mt-3">
            <Button
              size="sm"
              className="bg-emerald-600 hover:bg-emerald-700 text-white gap-2"
              onClick={() => exportChatAnalysisHTML(msg.exportReady!.threadId, clientId)}
            >
              <FileDown className="w-4 h-4" />
              {t("chat.downloadReport")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * StepGroup — renders one logical workflow step that may contain multiple
 * widgets (e.g. data_selection step with domains + date_range + platforms +
 * peers). Children widgets share a single「下一步 →」footer button which
 * batches all draft values back to the agent in one go (the existing
 * useAgentChatStream handler already accumulates and ships them as a
 * single widget_response when every widget in the message is resolved).
 *
 * Visual grammar:
 *   ┌─ Step badge "步骤 3/6"  +  step label  ─────────────┐
 *   │ Step description                                    │
 *   ├─────────────────────────────────────────────────────┤
 *   │  [ widget 1 — confirm button hidden ]               │
 *   │  [ widget 2 — confirm button hidden ]               │
 *   │  [ widget 3 — confirm button hidden ]               │
 *   ├─────────────────────────────────────────────────────┤
 *   │              [跳过剩余]  [下一步 →]                  │
 *   └─────────────────────────────────────────────────────┘
 */
function StepGroup({
  group,
  msgIdx,
  totalSteps,
  onWidgetRespond,
}: {
  group: WidgetGroup;
  msgIdx: number;
  totalSteps: number;
  onWidgetRespond: (resp: WidgetResponse, msgIdx: number, widgetIdx: number) => void;
}) {
  const { t } = useTranslation("agents");

  // Per-widget draft state. Keyed by widget_id for stability across re-orders.
  // Each entry is a tuple of (current draft value, whether it satisfies the
  // widget's required-field rule). Children populate this via onValueChange.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const draftsRef = useRef<Map<string, { value: any; valid: boolean }>>(new Map());
  const [, forceRender] = useState(0);

  // True once any widget has been touched (draft committed). The "下一步" /
  // "跳过剩余" buttons stay enabled even pre-touch so users can fast-forward
  // with defaults — but we use `touched` to gate the visual ✓ marks.
  const [touchedSet, setTouchedSet] = useState<Set<string>>(new Set());

  const allResolved = group.items.every(({ widget }) => widget.resolved);
  const submittingRef = useRef(false);

  /**
   * "Touched" means the widget has a meaningful (non-empty) draft value.
   * We use this strictly for the visual ✓ mark — required-field gating
   * uses the `valid` flag straight from the widget. A widget with a
   * pre-filled default value WILL show ✓ on mount because we want users
   * to see at a glance "this field is already filled".
   */
  function isMeaningful(value: unknown): boolean {
    if (value === null || value === undefined || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "object") {
      // Objects: treat empty-object / all-empty-string-fields as not meaningful.
      const obj = value as Record<string, unknown>;
      const keys = Object.keys(obj);
      if (keys.length === 0) return false;
      // analyzer_import emits {task_id, context} — only meaningful when task_id set.
      if ("task_id" in obj) return !!obj.task_id;
      return keys.some((k) => {
        const v = obj[k];
        return v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);
      });
    }
    return true;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleValueChange = useCallback((widgetId: string, value: any, opts?: { valid?: boolean }) => {
    const valid = opts?.valid ?? true;
    draftsRef.current.set(widgetId, { value, valid });
    setTouchedSet((prev) => {
      const meaningful = isMeaningful(value);
      const has = prev.has(widgetId);
      if (meaningful && has) return prev;
      if (!meaningful && !has) return prev;
      const next = new Set(prev);
      if (meaningful) next.add(widgetId);
      else next.delete(widgetId);
      return next;
    });
    // Force a re-render so the「下一步」button's disabled state stays in sync
    // with the live valid flags.
    forceRender((n) => n + 1);
  }, []);

  /**
   * Required-field gate. We treat widget.required as the source of truth —
   * if the backend marks a widget as required, the user MUST fill it before
   * we let「下一步」fire. Optional widgets don't block. The default value (if
   * present) counts as filled, since onValueChange runs once on mount with
   * the initial draft.
   */
  const allRequiredValid = useMemo(() => {
    return group.items.every(({ widget }) => {
      if (widget.required !== true) return true;
      const draft = draftsRef.current.get(widget.widget_id);
      return draft?.valid === true;
      // forceRender bumps via touchedSet — re-run on every draft change.
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group.items, touchedSet]);

  // 「跳过剩余」 should only appear when EVERY widget in the group is
  // optional. If even one widget is required, skipping isn't actually
  // skippable — the user would bypass a hard gate. (Earlier UX showed Skip
  // when at least one optional existed, which let users walk past required
  // fields like `default_domains` in the data_selection step.)
  const allOptional = group.items.every(({ widget }) => widget.required !== true);

  const handleSubmitAll = useCallback(
    (mode: "next" | "skip") => {
      if (submittingRef.current || allResolved) return;
      submittingRef.current = true;
      // Snapshot drafts up-front so we don't race with React's render cycle.
      const snapshot = group.items.map(({ widget, index }) => {
        const draft = draftsRef.current.get(widget.widget_id);
        const value = draft?.value !== undefined ? draft.value : (widget.default_value ?? null);
        return { widget, index, value, valid: draft?.valid ?? false };
      });
      // In "next" mode any required widget must be valid. "skip" relaxes
      // that for optional widgets — it just sends whatever drafts exist.
      if (mode === "next") {
        const missingRequired = snapshot.find((s) => s.widget.required === true && !s.valid);
        if (missingRequired) {
          submittingRef.current = false;
          return;
        }
      }
      // Fire onWidgetRespond for each widget in original index order. The
      // useAgentChatStream handler will accumulate them via flushSync and
      // send the final batched widget_response on the LAST call (when every
      // widget in msg.widgets is resolved).
      for (const s of snapshot) {
        onWidgetRespond(
          { widget_id: s.widget.widget_id, field: s.widget.field, value: s.value },
          msgIdx,
          s.index,
        );
      }
      // submittingRef stays true — the next render will see allResolved=true
      // once the SSE chain resolves and the widgets remount.
    },
    [allResolved, group.items, msgIdx, onWidgetRespond],
  );

  // Reset submittingRef whenever the group's resolution flips. This keeps
  // the button responsive if the backend re-emits the same step (e.g. via
  // edit-request from the confirmation card).
  useEffect(() => {
    if (!allResolved) submittingRef.current = false;
  }, [allResolved]);

  // Step header copy: "步骤 3/6 · Data Selection". When totalSteps is
  // unknown (e.g. agent didn't emit step_num), fall back to a clean header
  // without the "X/Y" badge.
  const showProgress = typeof group.step_num === "number" && totalSteps > 0;
  const headerLabel = group.step_label || group.step_key || "";

  return (
    <div className="my-3 max-w-2xl border border-border/50 rounded-2xl bg-gradient-to-br from-primary/[0.03] to-transparent overflow-hidden">
      {/* Step header */}
      {(headerLabel || showProgress || group.step_description) && (
        <div className="px-4 py-2.5 border-b border-border/40 bg-background/40">
          <div className="flex items-center gap-2 flex-wrap">
            {showProgress && (
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                {t("chat.stepBadge", { current: group.step_num, total: totalSteps })}
              </span>
            )}
            {headerLabel && (
              <span className="text-sm font-semibold text-foreground">{headerLabel}</span>
            )}
          </div>
          {group.step_description && (
            <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">
              {group.step_description}
            </p>
          )}
        </div>
      )}

      {/* Children widgets — confirm buttons hidden because the step-level
          footer below batches every draft in one shot. */}
      <div className="px-3 py-1 divide-y divide-border/20">
        {group.items.map(({ widget, index }) => {
          const filled = touchedSet.has(widget.widget_id);
          return (
            <div key={widget.widget_id} className="relative pl-5 py-1">
              {/* ✓ mark when value has been touched/filled */}
              {filled && !allResolved && (
                <CheckCircle2 className="absolute left-0 top-3.5 h-3.5 w-3.5 text-primary/60" />
              )}
              <ChatWidgetRenderer
                widget={widget as WidgetEvent}
                resolved={widget.resolved}
                resolvedValue={widget.resolvedValue}
                onRespond={(resp) => onWidgetRespond(resp, msgIdx, index)}
                onValueChange={(value, opts) => handleValueChange(widget.widget_id, value, opts)}
                hideConfirm
              />
            </div>
          );
        })}
      </div>

      {/* Step-level footer — single "下一步 →" submission */}
      {!allResolved && (
        <div className="px-4 py-2.5 flex items-center justify-end gap-2 bg-background/40 border-t border-border/40">
          {allOptional && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleSubmitAll("skip")}
              className="text-muted-foreground hover:text-foreground gap-1.5"
            >
              <SkipForward className="h-3.5 w-3.5" />
              {t("chat.stepSkipRemaining")}
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            onClick={() => handleSubmitAll("next")}
            disabled={!allRequiredValid}
            className="gap-1.5"
          >
            {t("chat.stepNext")}
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}
