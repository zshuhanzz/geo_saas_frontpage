import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Loader2,
  Play,
  CheckCircle,
  XCircle,
  SkipForward,
  RotateCcw,
  FileDown,
  Eye,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  createAgentTask,
  getAgentTaskProgress,
  exportAgentTaskHTML,
  getReportURL,
} from "@/lib/api";
import type { AgentsTFn } from "../types";
import { GOAL_LABEL_KEYS } from "../utils";

// ── ChatTaskCard: inline task execution card ─────────────────
//
// Two presentation modes for the inputs summary:
//
// 1. **Backend-translated** (preferred): when the `summaryDisplay` prop is
//    non-empty (shipped with the `task_ready` SSE event from
//    `geo_agent/src/services/workflow_config.py:build_summary_display`),
//    we render those rows directly. Each row already carries a
//    Chinese label + a translated display string, so the user sees
//    `分析目标: 品牌健康诊断` instead of `default_goal: health`. This is
//    the source of truth — no DB round-trip needed on the frontend.
//
// 2. **Fallback** (legacy): when `summaryDisplay` is undefined or empty
//    (e.g. older agent backend, or a code path that doesn't go through
//    workflow_config), we fall back to a small i18n map keyed by the raw
//    field name. The fallback is intentionally small — anything beyond the
//    most common analysis / content fields will simply show the raw key,
//    which is fine because that path is rare in production.

interface SummaryDisplayRow {
  step_key?: string;
  field?: string;
  label: string;
  value?: any;
  display: string;
}

export function ChatTaskCard({
  inputs,
  summaryDisplay,
  clientId,
  userId,
  threadId,
}: {
  inputs: Record<string, any>;
  summaryDisplay?: SummaryDisplayRow[];
  clientId: string;
  userId: string;
  threadId: string | null;
}) {
  const { t } = useTranslation("agents");
  const [status, setStatus] = useState<"idle" | "creating" | "running" | "done" | "error">("idle");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Array<{ step: number; name: string; label: string; status: string }>>([]);
  const [errorMsg, setErrorMsg] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // Determine task type from inputs — prefer explicit task_type injected from SSE event
  const taskType = inputs.task_type || (inputs.content_type ? "content_generation" : "analysis");
  const goalKey = inputs.goal || inputs.content_type || "";
  const goalLabel = (GOAL_LABEL_KEYS as readonly string[]).includes(goalKey)
    ? (t as AgentsTFn)(`chat.goalLabels.${goalKey}`)
    : goalKey || t("chat.goalLabels.custom");

  const handleRun = async () => {
    setStatus("creating");
    try {
      const result = await createAgentTask({
        client_id: clientId,
        user_id: userId,
        task_type: taskType,
        task_name: `Chat Task: ${goalLabel}`,
        inputs,
        thread_id: threadId || undefined,
        triggered_by: "chat",
      });

      const newTaskId = result?.id;
      if (!newTaskId) throw new Error("Task creation failed");

      setTaskId(newTaskId);
      setStatus("running");

      const doPoll = async () => {
        try {
          const data = await getAgentTaskProgress(newTaskId, clientId);
          if (data?.workflow_steps) setProgress(data.workflow_steps);
          if (data?.status === "COMPLETED" || data?.status === "FAILED") {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setStatus(data.status === "COMPLETED" ? "done" : "error");
            if (data.status === "FAILED") setErrorMsg(data.error_message || "Execution failed");
          }
        } catch { /* ignore poll errors */ }
      };
      doPoll();
      pollRef.current = setInterval(doPoll, 5000);
    } catch (err: any) {
      setStatus("error");
      setErrorMsg(err.message || "Task creation failed");
    }
  };

  // Internal bookkeeping keys we never want to surface in the summary
  // (these are present in `inputs` only because the agent forwards them
  // verbatim; they're not user-facing config).
  const SUPPRESSED_FALLBACK_KEYS = new Set([
    "_template_id", "_flow", "_current_step_key", "_current_node",
    "_summary_display", "metrics_locked", "chapters_locked",
    "subgoals_locked", "task_type",
  ]);

  // Last-resort fallback i18n keys for raw field names. Backend-translated
  // `summaryDisplay` rows bypass this entirely.
  const LABEL_KEYS = [
    "goal", "analysis_goal", "content_type", "domains", "platforms", "topic",
    "date_from", "date_to", "depth", "count", "language", "task_type",
  ] as const;

  // Choose which summary source to render. Backend-translated rows win.
  const useBackendRows = Array.isArray(summaryDisplay) && summaryDisplay.length > 0;

  // Fallback rows from raw inputs, paired with their best-effort label
  type FallbackRow = { key: string; label: string; display: string };
  const fallbackRows: FallbackRow[] = useBackendRows
    ? []
    : Object.entries(inputs)
        .filter(([k, v]) => v !== null && v !== undefined && v !== "" && !SUPPRESSED_FALLBACK_KEYS.has(k))
        .map(([key, val]) => ({
          key,
          label: (LABEL_KEYS as readonly string[]).includes(key)
            ? (t as AgentsTFn)(`chat.inputLabels.${key}`)
            : key,
          display: Array.isArray(val) ? val.join(", ") : String(val),
        }));

  return (
    <div className="flex gap-4 items-start">
      <div className="w-8 h-8 rounded-xl overflow-hidden bg-gradient-to-br from-primary/20 to-primary/5 shrink-0 mt-0.5">
        <img src="/Anthony_Chat_Online.png" alt="Anthony" className="w-full h-full object-contain" />
      </div>
      <div className="flex-1 min-w-0 max-w-3xl">
        <div className="border border-border/50 rounded-xl p-4 bg-gradient-to-br from-primary/5 to-transparent space-y-3">
          <div className="flex items-center gap-2">
            <Play className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">{t("chat.taskConfig")}</span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            {useBackendRows
              ? summaryDisplay!.map((row, i) => (
                  <div key={`${row.field || row.label}_${i}`} className="flex items-start gap-2 text-xs">
                    <span className="text-muted-foreground/60 shrink-0 w-24 text-right">{row.label}</span>
                    <span className="text-foreground/80 break-all">{row.display}</span>
                  </div>
                ))
              : fallbackRows.map((row) => (
                  <div key={row.key} className="flex items-start gap-2 text-xs">
                    <span className="text-muted-foreground/60 shrink-0 w-16 text-right">{row.label}</span>
                    <span className="text-foreground/80">{row.display}</span>
                  </div>
                ))}
          </div>

          {/* Action buttons / Progress / Result */}
          {status === "idle" && (
            <div className="flex gap-2 justify-end pt-1">
              <Button size="sm" variant="default" onClick={handleRun} className="gap-1.5">
                <Play className="h-3.5 w-3.5" /> {t("chat.startExecution")}
              </Button>
            </div>
          )}

          {status === "creating" && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground pt-1">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t("chat.creatingTask")}
            </div>
          )}

          {(status === "running" || status === "done") && progress.length > 0 && (
            <div className="space-y-1.5 pt-1">
              {progress.map((step) => (
                <div key={step.step} className="flex items-center gap-2 text-xs">
                  {step.status === "done" ? (
                    <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />
                  ) : step.status === "running" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                  ) : step.status === "skipped" ? (
                    <SkipForward className="h-3.5 w-3.5 text-muted-foreground/60" />
                  ) : (
                    <div className="h-3.5 w-3.5 rounded-full border border-muted-foreground/30" />
                  )}
                  <span className={step.status === "done" ? "text-foreground" : step.status === "running" ? "text-primary font-medium" : "text-muted-foreground"}>
                    {step.label}
                  </span>
                </div>
              ))}
            </div>
          )}

          {status === "done" && (
            <div className="flex items-center gap-2 pt-1">
              <div className="flex items-center gap-1.5 text-xs text-emerald-600">
                <CheckCircle className="h-3.5 w-3.5" /> {t("chat.taskFinished")}
              </div>
              {taskId && (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 gap-1.5 text-xs text-primary border-primary/30 hover:bg-primary/5"
                    onClick={() => window.open(getReportURL(taskId, clientId), "_blank")}
                  >
                    <Eye className="h-3 w-3" />
                    {t("chat.viewReportDetail")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 gap-1.5 text-xs text-primary border-primary/30 hover:bg-primary/5"
                    onClick={() => exportAgentTaskHTML(taskId, clientId)}
                  >
                    <FileDown className="h-3 w-3" />
                    {t("chat.exportHtml")}
                  </Button>
                </>
              )}
            </div>
          )}

          {status === "error" && (
            <div className="space-y-2 pt-1">
              <div className="flex items-center gap-1.5 text-xs text-destructive">
                <XCircle className="h-3.5 w-3.5" /> {errorMsg}
              </div>
              <Button size="sm" variant="outline" onClick={handleRun} className="gap-1.5 text-xs">
                <RotateCcw className="h-3 w-3" /> {t("chat.retry")}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
