import { useState, useEffect, useRef } from "react";
import { Loader2, CheckCircle, XCircle, Clock, RotateCcw, FileDown, Eye, SkipForward } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAgentTaskProgress, exportAgentTaskHTML, getReportURL } from "@/lib/api";

interface WorkflowStep {
  step: number;
  name: string;
  label: string;
  status: "pending" | "running" | "done" | "failed" | "skipped";
}

interface TaskProgressProps {
  taskId: string;
  clientId?: string;
  initialStatus?: string;
  initialSteps?: WorkflowStep[];
  compact?: boolean;
  onCompleted?: (taskId: string) => void;
  onRerun?: (taskId: string) => void;
}

export default function TaskProgressCard({
  taskId,
  clientId,
  initialStatus,
  initialSteps,
  compact = false,
  onCompleted,
  onRerun,
}: TaskProgressProps) {
  const { t } = useTranslation("agents");
  const [status, setStatus] = useState(initialStatus || "RUNNING");
  const [steps, setSteps] = useState<WorkflowStep[]>(initialSteps || []);
  const [error, setError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [completedAt, setCompletedAt] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;

  useEffect(() => {
    if (status !== "RUNNING" || !clientId) return;

    const doPoll = async () => {
      try {
        const data = await getAgentTaskProgress(taskId, clientId);
        if (!data) return;
        setStatus(data.status);
        if (data.workflow_steps) setSteps(data.workflow_steps);
        if (data.error_message) setError(data.error_message);
        if (data.started_at) setStartedAt(data.started_at);
        if (data.completed_at) setCompletedAt(data.completed_at);

        if (data.status === "COMPLETED" || data.status === "FAILED") {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          if (data.status === "COMPLETED" && onCompletedRef.current) {
            onCompletedRef.current(taskId);
          }
        }
      } catch {
        // Network error — retry next tick
      }
    };

    doPoll();
    pollRef.current = setInterval(doPoll, 8000);

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [taskId, clientId, status]);

  const isRunning = status === "RUNNING";
  const elapsed =
    startedAt && completedAt
      ? Math.round((new Date(completedAt).getTime() - new Date(startedAt).getTime()) / 1000)
      : startedAt
        ? Math.round((Date.now() - new Date(startedAt).getTime()) / 1000)
        : null;

  return (
    <div className={`rounded-lg border ${compact ? "p-3" : "p-4"} space-y-2 ${
      status === "FAILED" ? "border-destructive/30 bg-destructive/5" :
      status === "COMPLETED" ? "border-emerald-500/20 bg-emerald-500/5" :
      "bg-muted/20"
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isRunning && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
          {status === "COMPLETED" && <CheckCircle className="h-4 w-4 text-emerald-500" />}
          {status === "FAILED" && <XCircle className="h-4 w-4 text-destructive" />}
          <Badge
            variant="outline"
            className={
              status === "COMPLETED" ? "text-emerald-500 border-emerald-500/30" :
              status === "FAILED" ? "text-destructive border-destructive/30" :
              "text-primary border-primary/30"
            }
          >
            {status === "COMPLETED" ? t("taskProgress.completed") : status === "FAILED" ? t("taskProgress.failed") : t("taskProgress.running")}
          </Badge>
          {elapsed !== null && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {elapsed}s
            </span>
          )}
        </div>
        {status === "FAILED" && onRerun && (
          <Button size="sm" variant="outline" className="h-7 gap-1" onClick={() => onRerun(taskId)}>
            <RotateCcw className="h-3 w-3" />
            {t("taskProgress.rerun")}
          </Button>
        )}
      </div>

      {/* Workflow steps */}
      {steps.length > 0 && (
        <div className="space-y-1.5">
          {steps.map((step) => (
            <div key={step.step} className="flex items-center gap-2 text-xs">
              {step.status === "done" && <CheckCircle className="h-3.5 w-3.5 text-emerald-500 shrink-0" />}
              {step.status === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary shrink-0" />}
              {step.status === "failed" && <XCircle className="h-3.5 w-3.5 text-destructive shrink-0" />}
              {step.status === "skipped" && <SkipForward className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />}
              {step.status === "pending" && <div className="h-3.5 w-3.5 rounded-full border border-muted-foreground/30 shrink-0" />}
              <span className={
                step.status === "done" ? "text-foreground" :
                step.status === "running" ? "text-primary font-medium" :
                step.status === "failed" ? "text-destructive" :
                "text-muted-foreground"
              }>
                {step.label}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="text-xs text-destructive mt-1 break-words">
          {error.length > 200 ? error.slice(0, 200) + "..." : error}
        </div>
      )}

      {/* Export action — proactive guidance on completion */}
      {status === "COMPLETED" && clientId && (
        <div className="flex items-center gap-2 pt-1.5 border-t border-emerald-500/10 mt-2">
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-1.5 text-xs text-primary border-primary/30 hover:bg-primary/5"
            onClick={() => window.open(getReportURL(taskId, clientId), "_blank")}
          >
            <Eye className="h-3 w-3" />
            {t("taskProgress.viewReportDetail")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-1.5 text-xs text-primary border-primary/30 hover:bg-primary/5"
            onClick={() => exportAgentTaskHTML(taskId, clientId)}
          >
            <FileDown className="h-3 w-3" />
            {t("taskProgress.exportHtml")}
          </Button>
        </div>
      )}
    </div>
  );
}
