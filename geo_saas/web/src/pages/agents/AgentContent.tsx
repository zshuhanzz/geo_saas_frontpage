import { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";

/** Strip HTML/Schema Markup artifacts from LLM-generated content */
function stripContentArtifacts(text: string): string {
  if (!text) return text;
  return text
    .replace(/```html\s*\n[\s\S]*?```/g, '')                              // ```html blocks
    .replace(/<!--\s*Schema\s*Markup\s*-->[\s\S]*?<\/script>/gi, '')       // Schema Markup blocks
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')                      // <script> blocks
    .replace(/<(?!br\s*\/?>)\/?[a-zA-Z][^>]*>/g, '')                       // HTML tags (keep <br>)
    .replace(/\n{3,}/g, '\n\n')                                            // excessive blank lines
    .trim();
}
import {
  Loader2,
  Database,
  Clock,
  CheckCircle,
  XCircle,
  SkipForward,
  RotateCcw,
  Trash2,
  Eye,
  Sparkles,
  Pencil,
  FileDown,
  Type,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import { useSaaS } from "@/contexts/SaaSContext";
import { useAuth } from "@/contexts/AuthContext";
import {
  listAgentTasks,
  getAgentTask,
  getAgentTaskProgress,
  deleteAgentTask,
  runAgentTask,
  getClientPlatforms,
  listAgentTaskTemplates,
  exportAgentTaskHTML,
  getReportURL,
  renameAgentTask,
  getAvailability,
  type AvailabilityFlags,
} from "@/lib/api";
import ContentPipelineModal, { type ContentTemplate as ModalContentTemplate } from "@/components/agents/ContentPipelineModal";

// ── Types ────────────────────────────────────────────────────

type ContentTemplate = ModalContentTemplate & {
  icon: string;
  /** Data-driven visibility gate (same pattern as AgentAnalysis). */
  wizard_config?: { visibility_condition?: Record<string, boolean> } & Record<string, any>;
};

type ContentTemplateGroup = "generate_by_template" | "discover_then_generate";

/** Hide template if its wizard_config.visibility_condition isn't satisfied
 *  by the current client's availability flags. */
function contentTemplateMatchesAvailability(
  t: ContentTemplate,
  avail: AvailabilityFlags | null,
): boolean {
  const cond = t.wizard_config?.visibility_condition;
  if (!cond || Object.keys(cond).length === 0) return true;
  if (!avail) return true;
  for (const [k, required] of Object.entries(cond)) {
    if (required && !(avail as any)[k]) return false;
  }
  return true;
}

function getContentTemplateGroup(t: ContentTemplate): ContentTemplateGroup {
  const group =
    t.wizard_config?.template_group ||
    t.wizard_config?.product_mode ||
    (t.defaults as Record<string, unknown> | undefined)?.template_group;
  return group === "discover_then_generate" || group === "discover"
    ? "discover_then_generate"
    : "generate_by_template";
}

interface TaskRecord {
  id: string;
  task_type: string;
  task_name: string;
  status: string;
  workflow_steps?: any[];
  status_logs?: any[];
  inputs?: Record<string, any>;
  template_id?: string;
  triggered_by?: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  created_at: string;
  quality_gate_status?: string | null;
  quality_overall_score?: string | number | null;
}

interface PaginationMeta {
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

const TASK_PAGE_SIZE = 20;

function getOutputQualityStatus(output: any): string | null {
  const gateStatus = output?.quality_review?.quality_gate?.status;
  return typeof gateStatus === "string" && gateStatus ? gateStatus : null;
}

type QualityStatusLabelKey =
  | "content.qualityStatus.pass"
  | "content.qualityStatus.passWithWarnings"
  | "content.qualityStatus.revised"
  | "content.qualityStatus.failed"
  | "content.qualityStatus.needsHumanReview";

function qualityStatusMeta(status?: string | null) {
  switch (status) {
    case "needs_human_review":
      return { labelKey: "content.qualityStatus.needsHumanReview" as QualityStatusLabelKey, className: "text-amber-500 border-amber-500/30 bg-amber-500/5" };
    case "failed":
      return { labelKey: "content.qualityStatus.failed" as QualityStatusLabelKey, className: "text-destructive border-destructive/30 bg-destructive/5" };
    case "revised":
      return { labelKey: "content.qualityStatus.revised" as QualityStatusLabelKey, className: "text-blue-400 border-blue-400/30 bg-blue-400/5" };
    case "pass_with_warnings":
      return { labelKey: "content.qualityStatus.passWithWarnings" as QualityStatusLabelKey, className: "text-amber-500 border-amber-500/30 bg-amber-500/5" };
    case "pass":
      return { labelKey: "content.qualityStatus.pass" as QualityStatusLabelKey, className: "text-emerald-500 border-emerald-500/30 bg-emerald-500/5" };
    default:
      return null;
  }
}


// ── Step Output Helpers ────────────────────────────────────

/** Extract per-step outputs from status_logs */
function getStepOutputs(statusLogs: any): Record<number, any> {
  const outputs: Record<number, any> = {};
  const logs = typeof statusLogs === "string" ? JSON.parse(statusLogs) : statusLogs;
  if (!Array.isArray(logs)) return outputs;
  for (const log of logs) {
    if (log.event === "step_output" && log.step && log.data) {
      outputs[log.step] = log.data;
    }
  }
  return outputs;
}

/** Generic renderer for step output data */
function StepOutputDisplay({ data }: { data: any }) {
  if (!data || typeof data !== "object") return null;
  const entries = Object.entries(data).filter(([, v]) => v != null && v !== "");
  if (entries.length === 0) return null;

  return (
    <div className="mt-1.5 space-y-1 max-h-60 overflow-y-auto">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded border bg-background/50 p-2">
          <div className="font-mono text-[10px] text-primary/80 mb-0.5">{key}</div>
          {typeof value === "string" ? (
            value.length > 200 ? (
              <details>
                <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">
                  {value.slice(0, 150)}...
                </summary>
                <pre className="mt-1 text-[10px] text-muted-foreground whitespace-pre-wrap break-all max-h-40 overflow-y-auto font-mono">
                  {value}
                </pre>
              </details>
            ) : (
              <p className="text-[11px] text-muted-foreground whitespace-pre-wrap">{value}</p>
            )
          ) : (
            <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap break-all font-mono">
              {JSON.stringify(value, null, 2)}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Task Detail Sheet (right-side drawer) ─────────────────

function TaskDetailModal({
  task: initialTask,
  clientId,
  onClose,
  onRerun,
  onDelete,
  onEdit,
  readOnly = false,
}: {
  task: TaskRecord | null;
  clientId: string;
  onClose: () => void;
  onRerun: (id: string) => void;
  onDelete: (id: string) => void;
  onEdit: (task: TaskRecord) => void;
  readOnly?: boolean;
}) {
  const { t } = useTranslation("agents");
  const [task, setTask] = useState<TaskRecord | null>(initialTask);
  const [output, setOutput] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Sync when parent passes new task
  useEffect(() => { setTask(initialTask); setOutput(null); }, [initialTask]);

  // Initial fetch
  useEffect(() => {
    if (!task) return;
    setLoading(true);
    getAgentTask(task.id, clientId)
      .then((d) => {
        if (d) {
          const o = d.output ? (typeof d.output === "string" ? JSON.parse(d.output) : d.output) : null;
          setTask(prev => prev ? { ...prev, ...d, quality_gate_status: getOutputQualityStatus(o) || d.quality_gate_status } : prev);
          setOutput(o);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [task?.id]);

  // Auto-poll while RUNNING
  useEffect(() => {
    const stopPolling = () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
    if (!task || task.status !== "RUNNING") { stopPolling(); return; }

    const doPoll = async () => {
      try {
        const data = await getAgentTaskProgress(task.id, clientId);
        if (!data) return;
        setTask(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            status: data.status,
            workflow_steps: data.workflow_steps || prev.workflow_steps,
            status_logs: data.status_logs || prev.status_logs,
            error_message: data.error_message || prev.error_message,
            completed_at: data.completed_at || prev.completed_at,
          };
        });
        if (data.status === "COMPLETED" || data.status === "FAILED") {
          stopPolling();
          if (data.status === "COMPLETED") {
            try {
              const detail = await getAgentTask(task.id, clientId);
              const o = detail?.output ? (typeof detail.output === "string" ? JSON.parse(detail.output) : detail.output) : null;
              if (o) setOutput(o);
              // Also update workflow_steps & status_logs from full detail
              setTask(prev => {
                if (!prev) return prev;
                return {
                  ...prev,
                  workflow_steps: detail?.workflow_steps || prev.workflow_steps,
                  status_logs: detail?.status_logs || prev.status_logs,
                  status: detail?.status || prev.status,
                  completed_at: detail?.completed_at || prev.completed_at,
                  quality_gate_status: getOutputQualityStatus(o) || detail?.quality_gate_status || prev.quality_gate_status,
                  quality_overall_score: detail?.quality_overall_score || prev.quality_overall_score,
                };
              });
            } catch {}
          }
        }
      } catch {}
    };

    doPoll();
    pollRef.current = setInterval(doPoll, 8000);
    return () => stopPolling();
  }, [task?.id, task?.status, clientId]);

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  if (!task) return null;

  const isRunning = task.status === "RUNNING";
  const isDraft = task.status === "DRAFT";
  const qualityStatus = getOutputQualityStatus(output) || task.quality_gate_status || null;
  const qualityMeta = qualityStatusMeta(qualityStatus);

  // Parse workflow_steps for progress visualization
  const steps: Array<{ step: number; name: string; label: string; status: string }> = (() => {
    if (!task.workflow_steps) return [];
    const ws = typeof task.workflow_steps === "string" ? JSON.parse(task.workflow_steps) : task.workflow_steps;
    return Array.isArray(ws) ? ws : [];
  })();

  // Extract per-step outputs from status_logs
  const stepOutputs = getStepOutputs(task.status_logs);

  return (
    <Sheet open={!!task} onOpenChange={o => { if (!o) onClose(); }}>
      <SheetContent side="right" className="sm:max-w-[75vw] w-[75vw] p-0 flex flex-col overflow-hidden [&>button:first-child]:hidden">
        <SheetTitle className="sr-only">Task Details: {task.task_name}</SheetTitle>
        <SheetDescription className="hidden">Details for {task.task_name}</SheetDescription>

        {/* Header */}
        <div className="flex items-center gap-3 px-6 pt-5 pb-4 border-b shrink-0">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center shrink-0">
            <Sparkles className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm">{task.task_name}</span>
              <Badge variant="outline" className={cn("text-[11px]",
                task.status === "COMPLETED" ? "text-emerald-500 border-emerald-500/30 bg-emerald-500/5" :
                task.status === "FAILED" ? "text-destructive border-destructive/30 bg-destructive/5" :
                isRunning ? "text-primary border-primary/30 bg-primary/5" :
                "text-muted-foreground border-border"
              )}>
                {task.status === "COMPLETED" ? t("common.statusCompleted") : task.status === "FAILED" ? t("common.statusFailed") : isDraft ? t("common.statusDraft") : t("common.statusRunning")}
                {isRunning && <Loader2 className="h-3 w-3 ml-1 animate-spin" />}
              </Badge>
              {qualityMeta && (
                <Badge variant="outline" className={cn("text-[11px]", qualityMeta.className)}>
                  {t(qualityMeta.labelKey)}
                </Badge>
              )}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {new Date(task.created_at).toLocaleString("zh-CN")}
              {task.completed_at && task.started_at &&
                ` · ${Math.round((new Date(task.completed_at).getTime() - new Date(task.started_at).getTime()) / 1000)}s elapsed`}
            </div>
          </div>
          {!readOnly && <div className="flex items-center gap-2 shrink-0">
            <Button size="sm" variant="outline" onClick={() => { onEdit(task); onClose(); }} className="gap-1.5 h-8 rounded-lg" disabled={isRunning}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            {(isDraft || task.status === "FAILED") && (
              <Button size="sm" variant="outline" onClick={() => { onRerun(task.id); onClose(); }} className="gap-1.5 h-8 rounded-lg" disabled={isRunning}>
                <RotateCcw className="h-3.5 w-3.5" />
                {isDraft ? t("common.execute") : t("common.rerun")}
              </Button>
            )}
            <Button size="sm" variant="outline" className="gap-1.5 h-8 rounded-lg text-destructive border-destructive/30 hover:bg-destructive/5"
              onClick={() => { onDelete(task.id); onClose(); }} disabled={isRunning}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {loading ? (
            <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div>
          ) : (
            <>
              {/* Workflow Steps Progress */}
              {steps.length > 0 && (
                <div className="rounded-xl border bg-primary/[0.02] p-5 space-y-2.5">
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                    <Sparkles className="h-3.5 w-3.5 text-primary" />
                    {t("content.progress")}
                    {isRunning && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
                  </div>
                  {steps.map((s, i) => (
                    <div key={i} className="ml-1">
                      <div className="flex items-center gap-2.5 text-xs">
                        {s.status === "done" ? (
                          <CheckCircle className="h-4 w-4 text-emerald-500 flex-shrink-0" />
                        ) : s.status === "running" ? (
                          <Loader2 className="h-4 w-4 animate-spin text-primary flex-shrink-0" />
                        ) : s.status === "failed" ? (
                          <XCircle className="h-4 w-4 text-destructive flex-shrink-0" />
                        ) : s.status === "skipped" ? (
                          <SkipForward className="h-4 w-4 text-muted-foreground/60 flex-shrink-0" />
                        ) : (
                          <div className="h-4 w-4 rounded-full border border-border flex-shrink-0" />
                        )}
                        <span className={cn(
                          s.status === "done" ? "text-foreground/80" :
                          s.status === "running" ? "text-primary font-medium" :
                          s.status === "failed" ? "text-destructive" :
                          "text-muted-foreground"
                        )}>
                          {t("common.stepLabel", { step: s.step, label: s.label })}
                        </span>
                      </div>
                      {s.status === "done" && stepOutputs[s.step] && (
                        <div className="ml-6 mt-0.5">
                          <details>
                            <summary className="cursor-pointer text-primary/70 hover:text-primary text-[11px] select-none">
                              {t("common.viewOutput")}
                            </summary>
                            <StepOutputDisplay data={stepOutputs[s.step]} />
                          </details>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Error */}
              {task.status === "FAILED" && task.error_message && (
                <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4">
                  <div className="text-sm font-medium text-destructive mb-1">{t("common.executionFailed")}</div>
                  <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-words">{task.error_message}</pre>
                </div>
              )}

              {/* RAFT Scores */}
              {output?.raft_scores && (
                <div className="rounded-xl border p-5 bg-card">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">{t("content.raftQuality")}</h4>
                  <div className="grid grid-cols-2 gap-3">
                    {["readability", "answerability", "trustworthiness", "timeliness"].map((dim) => {
                      const s = output.raft_scores[dim];
                      if (!s) return null;
                      return (
                        <div key={dim} className="flex items-center justify-between rounded-lg bg-muted/30 px-3 py-2">
                          <span className="text-xs font-medium capitalize text-foreground">{dim}</span>
                          <span className="text-sm font-bold text-primary">{s.score}/5</span>
                        </div>
                      );
                    })}
                  </div>
                  {output.raft_scores.overall && (
                    <div className="mt-3 pt-3 border-t text-center">
                      <span className="text-sm text-muted-foreground">{t("content.overallScore")}</span>
                      <span className="text-lg font-bold text-primary ml-2">{output.raft_scores.overall}/5</span>
                    </div>
                  )}
                </div>
              )}

              {/* FAQ */}
              {output?.faqs?.length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("content.generatedContent")}</h4>
                  {output.faqs.map((faq: any, i: number) => (
                    <div key={i} className="rounded-xl border p-4 bg-card">
                      <p className="text-sm font-semibold mb-1.5">Q{i + 1}: {faq.question}</p>
                      <p className="text-sm text-muted-foreground leading-relaxed">{faq.answer}</p>
                    </div>
                  ))}
                </div>
              )}

              {output?.citation_analysis_summary_markdown && (
                <div className="rounded-xl border p-6 bg-card space-y-3">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("content.citationAnalysis")}
                  </h4>
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                      {stripContentArtifacts(output.citation_analysis_summary_markdown)}
                    </ReactMarkdown>
                  </div>
                </div>
              )}

              {/* Article / Brief — title + meta + content */}
              {(output?.content_markdown || output?.title) && (
                <div className="rounded-xl border p-6 bg-card space-y-3">
                  {output.title && (
                    <h3 className="text-lg font-bold text-foreground">{output.title}</h3>
                  )}
                  {output.meta_description && (
                    <p className="text-xs text-muted-foreground italic border-l-2 border-primary/20 pl-3">{output.meta_description}</p>
                  )}
                  {output.content_markdown && (
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{stripContentArtifacts(output.content_markdown)}</ReactMarkdown>
                    </div>
                  )}
                </div>
              )}

              {/* Recommendations */}
              {output?.recommendations?.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("content.recommendations")}</h4>
                  {output.recommendations.map((rec: any, i: number) => (
                    <div key={i} className="rounded-xl border p-4 bg-card flex items-start gap-3">
                      <Badge variant="outline" className={cn("shrink-0 mt-0.5",
                        rec.priority === "high" ? "text-red-500 border-red-500/30" :
                        rec.priority === "medium" ? "text-amber-500 border-amber-500/30" :
                        "text-green-500 border-green-500/30"
                      )}>{rec.priority}</Badge>
                      <div>
                        <p className="text-sm font-medium">{rec.title}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{rec.description}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {!output && !isRunning && task.status !== "DRAFT" && task.status !== "FAILED" && (
                <div className="text-center text-sm text-muted-foreground py-6">{t("common.emptyOutput")}</div>
              )}

              {isDraft && (
                <div className="text-center py-6">
                  <p className="text-sm text-muted-foreground mb-3">{t("common.savedHint")}</p>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 flex items-center justify-between px-6 pb-5 pt-3 border-t">
          <div>
            {task && task.status === "COMPLETED" && (
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-lg gap-1.5 text-primary border-primary/30 hover:bg-primary/5"
                  onClick={() => window.open(getReportURL(task.id, clientId), "_blank")}
                >
                  <Eye className="h-3.5 w-3.5" />
                  {t("common.viewFullReport")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-lg gap-1.5 text-primary border-primary/30 hover:bg-primary/5"
                  onClick={() => exportAgentTaskHTML(task.id, clientId)}
                >
                  <FileDown className="h-3.5 w-3.5" />
                  {t("common.exportHtml")}
                </Button>
              </div>
            )}
          </div>
          <Button size="sm" variant="outline" onClick={onClose} className="rounded-lg">{t("common.close")}</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── Status Icon ────────────────────────────────────────────

function StatusIcon({ status }: { status: string }) {
  if (status === "RUNNING") return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  if (status === "COMPLETED") return <CheckCircle className="h-4 w-4 text-emerald-500" />;
  if (status === "DRAFT") return <Database className="h-4 w-4 text-muted-foreground" />;
  return <XCircle className="h-4 w-4 text-destructive" />;
}

// ── Main Component ──────────────────────────────────────────

export default function AgentContent() {
  const { t } = useTranslation("agents");
  const { clientId, clients, can } = useSaaS();
  const canExecute = can("actions.content", "execute");
  const { user } = useAuth();
  const userId = user?.sub ? `google:${user.sub}` : "";

  const [activeTab, setActiveTab] = useState<"new" | "all">("new");

  // ── Templates & platforms from DB ──
  const [templates, setTemplates] = useState<ContentTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [clientPlatforms, setClientPlatforms] = useState<string[]>([]);
  const [availability, setAvailability] = useState<AvailabilityFlags | null>(null);

  // ── Modal state ──
  const [taskModalOpen, setTaskModalOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<ContentTemplate | null>(null);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [preselectedAnalyzerTaskId, setPreselectedAnalyzerTaskId] = useState<string | null>(null);

  // ── All Tasks state ──
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [taskPage, setTaskPage] = useState(1);
  const [taskPagination, setTaskPagination] = useState<PaginationMeta | null>(null);
  const [selectedTask, setSelectedTask] = useState<TaskRecord | null>(null);
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<TaskRecord | null>(null);
  const [renameValue, setRenameValue] = useState("");

  useEffect(() => {
    if (!canExecute) setActiveTab("all");
  }, [canExecute]);

  // ── Fetch templates and platforms on mount ──
  useEffect(() => {
    if (!clientId) return;
    setLoadingTemplates(true);
    listAgentTaskTemplates("content_generation", clientId)
      .then((data) => setTemplates((data || []).map((t: any) => ({
        id: t.id,
        name: t.name,
        icon: t.icon || "📝",
        description: t.description,
        data_domains: t.data_domains || [],
        default_prompt: t.default_prompt || "",
        defaults: t.defaults,
        wizard_config: t.wizard_config,
      }))))
      .catch(() => setTemplates([]))
      .finally(() => setLoadingTemplates(false));

    getClientPlatforms(clientId)
      .then((p) => setClientPlatforms(p || []))
      .catch(() => {
        // Fallback: read from SaaSContext
        const client = clients.find((c) => c.id === clientId);
        setClientPlatforms(client?.config_platforms || []);
      });

    // Availability flags for data-driven template visibility gating.
    getAvailability(clientId)
      .then(setAvailability)
      .catch(() => setAvailability(null));
  }, [clientId]);

  // ── Read analyzer_task_id from URL (CTA from Analyzer page) ──
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const analyzerTaskId = params.get("analyzer_task_id");
    if (analyzerTaskId && canExecute) {
      setPreselectedAnalyzerTaskId(analyzerTaskId);
      setTaskModalOpen(true);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [canExecute]);

  // ── Fetch tasks ──
  const initialLoadDone = useRef(false);

  const fetchTasks = useCallback((showSpinner = false, page = taskPage) => {
    if (!clientId) return;
    if (showSpinner) setLoadingTasks(true);
    listAgentTasks(clientId, "content_generation", { page, pageSize: TASK_PAGE_SIZE })
      .then((d) => {
        setTasks(d?.data || []);
        setTaskPagination(d?.pagination || null);
      })
      .catch(() => {
        setTasks([]);
        setTaskPagination(null);
      })
      .finally(() => setLoadingTasks(false));
  }, [clientId, taskPage]);

  useEffect(() => {
    if (activeTab === "all") {
      const needSpinner = !initialLoadDone.current;
      fetchTasks(needSpinner, taskPage);
      initialLoadDone.current = true;
    }
  }, [activeTab, clientId, taskPage, fetchTasks]);

  useEffect(() => {
    initialLoadDone.current = false;
    setTaskPage(1);
  }, [clientId]);

  // Background list refresh every 10s while on All Tasks tab — only if any task is RUNNING
  const hasRunningTask = tasks.some((t: any) => t.status === "RUNNING");
  useEffect(() => {
    if (activeTab !== "all" || !hasRunningTask) return;
    const timer = setInterval(() => fetchTasks(false), 10000);
    return () => clearInterval(timer);
  }, [activeTab, clientId, hasRunningTask]);

  // ── Chat Send ──
  // ── Task actions ──
  const handleDeleteTask = useCallback(async (taskId: string) => {
    if (!clientId) return;
    try {
      await deleteAgentTask(taskId, clientId);
      if (tasks.length === 1 && taskPage > 1) {
        setTaskPage((prev) => Math.max(1, prev - 1));
      } else {
        fetchTasks(false, taskPage);
      }
    } catch { /* silent */ }
  }, [clientId, fetchTasks, taskPage, tasks.length]);

  const handleRerunTask = useCallback(async (taskId: string) => {
    if (!clientId) return;
    try {
      await runAgentTask(taskId, clientId, userId);
      fetchTasks();
    } catch { /* silent */ }
  }, [clientId, userId]);

  const handleRenameTask = useCallback((task: TaskRecord) => {
    setRenameTarget(task);
    setRenameValue(task.task_name);
    setRenameDialogOpen(true);
  }, []);

  const submitRename = useCallback(async () => {
    if (!renameTarget || !renameValue.trim() || renameValue === renameTarget.task_name || !clientId) return;
    try {
      await renameAgentTask(renameTarget.id, clientId, renameValue.trim());
      setTasks(prev => prev.map(t => t.id === renameTarget.id ? { ...t, task_name: renameValue.trim() } : t));
    } catch { /* silent */ }
    setRenameDialogOpen(false);
  }, [renameTarget, renameValue, clientId]);

  const handleEditTask = useCallback(async (task: TaskRecord) => {
    // Reconstruct a template from the task's inputs to reopen the wizard
    const inputs = typeof task.inputs === "string" ? JSON.parse(task.inputs) : (task.inputs || {});
    const editTemplate: ContentTemplate = {
      id: task.template_id || "",
      name: task.task_name,
      icon: "✏️",
      description: "Edit task",
      data_domains: inputs.data_domains || [],
      default_prompt: inputs.strategy_prompt || "",
      defaults: { content_type: inputs.content_type },
    };
    setSelectedTask(null);
    setEditingTaskId(task.id);
    setSelectedTemplate(editTemplate);
    setTaskModalOpen(true);
  }, []);

  // ── Render ──

  const visibleTemplates = templates.filter((t) => contentTemplateMatchesAvailability(t, availability));
  const generateTemplates = visibleTemplates.filter((t) => getContentTemplateGroup(t) === "generate_by_template");
  const discoverTemplates = visibleTemplates.filter((t) => getContentTemplateGroup(t) === "discover_then_generate");

  const renderTemplateGrid = (items: ContentTemplate[]) => (
    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
      {items.map((t) => {
        const isCustom = !t.data_domains || t.data_domains.length === 0;
        return (
          <button
            key={t.id}
            className={cn(
              "group text-left p-4 rounded-2xl transition-all duration-300",
              isCustom
                ? "border-2 border-dashed border-border hover:border-primary/30 hover:bg-primary/[0.02]"
                : "border bg-card hover:bg-primary/[0.03] hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5"
            )}
            onClick={() => { setSelectedTemplate(t); setTaskModalOpen(true); }}
          >
            <div className="flex items-center gap-2 mb-2.5">
              <div className={cn(
                "w-10 h-10 rounded-xl flex items-center justify-center text-xl transition-colors",
                isCustom ? "bg-muted group-hover:bg-primary/10" : "bg-primary/10 group-hover:bg-primary/15"
              )}>
                {isCustom ? "+" : t.icon}
              </div>
            </div>
            <p className={cn(
              "text-sm font-semibold leading-snug group-hover:text-primary transition-colors mb-1.5",
              isCustom ? "text-muted-foreground" : "text-foreground"
            )}>
              {t.name}
            </p>
            {t.description && (
              <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">{t.description}</p>
            )}
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="h-full flex flex-col">
      {/* Header with tabs */}
      <div className="shrink-0 px-6">
        <h1 className="text-2xl font-bold tracking-tight pt-2 pb-4">{t("content.pageTitle")}</h1>
        <div className="flex border-b">
          {(canExecute ? (["new", "all"] as const) : (["all"] as const)).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "pb-3 px-1 mr-8 text-sm font-medium border-b-2 transition-colors",
                activeTab === tab
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              {tab === "new" ? t("content.tabNew") : t("content.tabAll")}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "new" ? (
        <div className="flex-1 flex flex-col overflow-auto">
          <div className="max-w-5xl mx-auto w-full px-6 py-8 space-y-8">
            <p className="text-sm font-medium text-muted-foreground mb-4">{t("content.templateGallery")}</p>
            {loadingTemplates ? (
              <div className="flex items-center justify-center py-10">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="space-y-8">
                <section className="space-y-3">
                  <div className="space-y-1">
                    <h2 className="text-sm font-semibold text-foreground">{t("content.templateSections.generateTitle")}</h2>
                    <p className="text-xs text-muted-foreground">{t("content.templateSections.generateDescription")}</p>
                  </div>
                  {renderTemplateGrid(generateTemplates)}
                </section>

                <section className="space-y-3">
                  <div className="space-y-1">
                    <h2 className="text-sm font-semibold text-foreground">{t("content.templateSections.discoverTitle")}</h2>
                    <p className="text-xs text-muted-foreground">{t("content.templateSections.discoverDescription")}</p>
                  </div>
                  {discoverTemplates.length > 0 ? (
                    renderTemplateGrid(discoverTemplates)
                  ) : (
                    <div className="rounded-xl border border-dashed border-border bg-muted/20 px-4 py-5 text-xs text-muted-foreground">
                      {t("content.templateSections.discoverEmpty")}
                    </div>
                  )}
                </section>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* ── All Tasks tab ── */
        <div className="flex-1 overflow-auto p-6">
          {loadingTasks ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-3">
              <div className="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center">
                <Clock className="h-7 w-7 text-muted-foreground/50" />
              </div>
              <p className="text-sm">{t("content.emptyTasks")}</p>
              {canExecute && <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setActiveTab("new")}>
                <Sparkles className="h-3.5 w-3.5" />
                {t("content.createFirstTask")}
              </Button>}
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-3">
              {tasks.map((task) => (
                (() => {
                  const qualityMeta = qualityStatusMeta(task.quality_gate_status);
                  return (
                    <Card
                      key={task.id}
                      className="p-4 hover:border-primary/20 hover:shadow-md transition-all duration-200 cursor-pointer group rounded-xl"
                      onClick={() => setSelectedTask(task)}
                    >
                      <div className="flex items-start gap-3">
                        <StatusIcon status={task.status} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-medium text-sm text-foreground">{task.task_name}</span>
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {new Date(task.created_at).toLocaleString("en-US")}
                            {task.completed_at && task.started_at &&
                              ` · ${Math.round((new Date(task.completed_at).getTime() - new Date(task.started_at).getTime()) / 1000)}s elapsed`}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <Badge variant="outline" className={cn("text-[11px]",
                            task.status === "COMPLETED" ? "text-emerald-500 border-emerald-500/30 bg-emerald-500/5" :
                            task.status === "FAILED" ? "text-destructive border-destructive/30 bg-destructive/5" :
                            task.status === "RUNNING" ? "text-primary border-primary/30 bg-primary/5" :
                            "text-muted-foreground border-border"
                          )}>
                            {task.status === "COMPLETED" ? t("common.statusCompleted") : task.status === "FAILED" ? t("common.statusFailed") : task.status === "DRAFT" ? t("common.statusDraft") : t("common.statusRunning")}
                            {task.status === "RUNNING" && <Loader2 className="h-3 w-3 ml-1 animate-spin" />}
                          </Badge>
                          {qualityMeta && (
                            <Badge variant="outline" className={cn("text-[11px]", qualityMeta.className)}>
                              {t(qualityMeta.labelKey)}
                            </Badge>
                          )}
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                            <Button size="icon" variant="ghost" className="h-7 w-7" title={t("content.actionTitles.view")} onClick={() => setSelectedTask(task)}>
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                            {canExecute && <Button size="icon" variant="ghost" className="h-7 w-7" title={t("content.actionTitles.rename")} onClick={() => handleRenameTask(task)}>
                              <Type className="h-3.5 w-3.5" />
                            </Button>}
                            {canExecute && <Button size="icon" variant="ghost" className="h-7 w-7" title={t("content.actionTitles.edit")} onClick={() => handleEditTask(task)}>
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>}
                            {canExecute && (task.status === "FAILED" || task.status === "DRAFT") && (
                              <Button size="icon" variant="ghost" className="h-7 w-7" title={task.status === "DRAFT" ? t("common.execute") : t("common.rerun")} onClick={() => handleRerunTask(task.id)}>
                                <RotateCcw className="h-3.5 w-3.5" />
                              </Button>
                            )}
                            {canExecute && <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive" title={t("content.actionTitles.delete")} onClick={() => handleDeleteTask(task.id)}>
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>}
                          </div>
                        </div>
                      </div>
                    </Card>
                  );
                })()
              ))}
              {taskPagination && taskPagination.total > TASK_PAGE_SIZE && (
                <div className="flex items-center justify-between rounded-xl border border-border bg-card/60 px-4 py-3 text-xs text-muted-foreground">
                  <span>
                    {t("pagination.summary", {
                      page: taskPagination.page,
                      pages: taskPagination.pages,
                      total: taskPagination.total,
                    })}
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-8 rounded-lg"
                      disabled={taskPagination.page <= 1 || loadingTasks}
                      onClick={() => setTaskPage((prev) => Math.max(1, prev - 1))}
                    >
                      {t("pagination.previous")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-8 rounded-lg"
                      disabled={taskPagination.page >= taskPagination.pages || loadingTasks}
                      onClick={() => setTaskPage((prev) => prev + 1)}
                    >
                      {t("pagination.next")}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Content Pipeline Modal */}
      {canExecute && <ContentPipelineModal
        open={taskModalOpen}
        clientId={clientId || ""}
        userId={userId}
        clientPlatforms={clientPlatforms}
        preselectedAnalyzerTaskId={preselectedAnalyzerTaskId}
        existingTaskId={editingTaskId}
        template={selectedTemplate}
        onClose={() => { setTaskModalOpen(false); setPreselectedAnalyzerTaskId(null); setEditingTaskId(null); setSelectedTemplate(null); }}
        onTaskCreated={fetchTasks}
      />}

      {/* Task Detail Modal */}
      {selectedTask && (
        <TaskDetailModal
          task={selectedTask}
          clientId={clientId}
          onClose={() => setSelectedTask(null)}
          onRerun={handleRerunTask}
          onDelete={handleDeleteTask}
          onEdit={handleEditTask}
          readOnly={!canExecute}
        />
      )}

      {/* Rename Dialog */}
      {canExecute && <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("content.renameDialog.title")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="rename-input">{t("content.renameDialog.nameLabel")}</Label>
              <Input id="rename-input" value={renameValue} onChange={e => setRenameValue(e.target.value)} placeholder={t("content.renameDialog.placeholder")} autoFocus />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button disabled={!renameValue.trim() || renameValue === renameTarget?.task_name} onClick={submitRename}>{t("common.confirm")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>}
    </div>
  );
}
