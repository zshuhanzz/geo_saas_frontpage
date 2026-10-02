/**
 * TemplateConfigModal — Analyze wizard host (Round 2: schema-driven).
 *
 * The modal used to own 6 hand-coded Step components (Step1_Goal, Step2_Metrics,
 * Step2_Data, Step3_Charts, Step4_Prompt, Step5_Confirm) plus ~20 useState hooks
 * for the form fields. Round 2 migrates it to a thin shell around `<WizardShell>`:
 * the wizard fetches `/tasks/workflow-config?scope=analysis`, resolves it against
 * `template.wizard_config`, and hands back a plain FormState on submit.
 *
 * This file now only owns:
 *
 *   1. Dialog chrome + Anthony header + domain badges
 *   2. Runtime settings bar (model picker + cron expression) — these are
 *      genuinely host-level concerns (LLM routing + Cloud Scheduler) and do not
 *      belong in any schema-driven workflow step
 *   3. `runReport(formState)` + `saveTemplate(formState)` — submit handlers that
 *      map the schema FormState into the analysis_pipeline taskInputs contract
 *   4. Task polling + workflow/progress/SQL log plumbing
 *   5. ReportViewer + ChartCard (rendered in the "result" view)
 *
 * Everything else — step ordering, field labels, default values, visibility,
 * field types, custom component wiring — comes from the DB via the schema-driven
 * wizard layer. Adding a new analysis step now means inserting a workflow_step
 * row, not touching this file.
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { Trans, useTranslation } from "react-i18next";
import {
    Dialog, DialogContent, DialogTitle, DialogDescription
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

import {
    CheckCircle2, Loader2, ChevronLeft,
    Sparkles, BarChart3, X,
    Database, AlertCircle, FileDown, Eye, ZapIcon,
} from "lucide-react";

import { fetchJSON, exportAgentTaskHTML, getReportURL } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";

import { WizardShell } from "@/components/wizard";
import { addLocalDays, todayDateOnlyString } from "@/lib/dateOnly";
import type {
    WizardFormState,
    WizardTemplate,
    TemplateWizardConfig,
} from "@/components/wizard";

const AGENT_BASE = (import.meta.env.VITE_AGENT_API_URL || "") + "/api/agent";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface Template {
    id: string;
    run_id?: string;
    name: string;
    description?: string;
    icon: string;
    data_domains: string[];
    default_prompt: string;
    chart_requests?: ChartRequest[] | string;
    filters?: Record<string, unknown> & { dateFrom?: string; dateTo?: string };
    cron_expression?: string;
    /** Template × Wizard contract — drives default charts, required metrics,
     *  required chapters, and per-step overrides. May arrive from the backend
     *  as a JSONB object OR a JSON string; we normalize both shapes. */
    wizard_config?: TemplateWizardConfig | Record<string, unknown> | string | null;
    defaults?: Record<string, unknown>;
    // Run-state fields (present when modal is opened from All Tasks list)
    status?: "RUNNING" | "COMPLETED" | "FAILED" | "SAVED";
    status_logs?: Array<{ label?: string; step?: number; event?: string; ts?: string }>;
    report_output?: ReportOutput | string | null;
}

interface ChartRequest {
    nl_query: string;
    chart_type: string;
}

interface ChartResult {
    index: number;
    nl_query: string;
    chart_type: string;
    columns?: string[];
    rows?: unknown[][];
    error?: string;
    warning?: string;
    sql?: string;
}

interface ReportOutput {
    charts: ChartResult[];
    insights_markdown: string;
    variables: Record<string, string>;
    quality_score?: {
        data_accuracy_score?: number;
        consistency_score?: number;
        completeness_score?: number;
        overall_score?: number;
        issues?: string[];
        summary?: string;
    };
}

interface TemplateConfigModalProps {
    open: boolean;
    template: Template | null;
    clientId: string;
    userId?: string;
    modelIds: string[];
    onClose: () => void;
    onTaskCreated?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Domain helpers — used by the header badge strip
// ─────────────────────────────────────────────────────────────────────────────
const DOMAIN_META: Record<string, { labelKey: "visibility" | "citation" | "sentiment"; color: string; icon: string }> = {
    visibility: { labelKey: "visibility", color: "bg-blue-500/10 text-blue-400 border-blue-500/20", icon: "🔍" },
    citation:   { labelKey: "citation",   color: "bg-purple-500/10 text-purple-400 border-purple-500/20", icon: "📎" },
    sentiment:  { labelKey: "sentiment",  color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", icon: "💬" },
};

// ─────────────────────────────────────────────────────────────────────────────
// wizard_config normalization — the backend sometimes serializes jsonb as a
// string. Convert both shapes to a plain object so the WizardShell can always
// read `template.wizard_config.steps[...]` without defensive null checks.
// ─────────────────────────────────────────────────────────────────────────────
function normalizeWizardConfig(
    raw: TemplateWizardConfig | Record<string, unknown> | string | null | undefined,
): TemplateWizardConfig {
    if (!raw) return {};
    if (typeof raw === "string") {
        try {
            return JSON.parse(raw) as TemplateWizardConfig;
        } catch {
            return {};
        }
    }
    return raw as TemplateWizardConfig;
}

// ─────────────────────────────────────────────────────────────────────────────
// date_range resolution — the data_selection step stores a key like "last_30d"
// via single_ref; at submit time we need a concrete (date_from, date_to) pair.
// Keys come from migration 028 section 3 (date_range dictionary).
// ─────────────────────────────────────────────────────────────────────────────
const DATE_RANGE_DAYS: Record<string, number> = {
    last_7d: 7,
    last_30d: 30,
    last_90d: 90,
    last_180d: 180,
    last_365d: 365,
};

function resolveDateRange(
    key: string | undefined,
    template: Template | null,
): { dateFrom: string; dateTo: string } {
    // Template filter override takes precedence over the wizard key — useful
    // for "edit a saved task" flows where the task already has a frozen range.
    if (template?.filters?.dateFrom && template?.filters?.dateTo) {
        return { dateFrom: template.filters.dateFrom, dateTo: template.filters.dateTo };
    }

    const to = todayDateOnlyString();
    const days = DATE_RANGE_DAYS[key || ""] ?? 7;
    const from = addLocalDays(to, -days + 1);
    return { dateFrom: from, dateTo: to };
}

// ─────────────────────────────────────────────────────────────────────────────
// FormState → analysis_pipeline taskInputs mapping. Keeping this in one place
// makes it easy to audit the contract whenever migrations change a field key.
// ─────────────────────────────────────────────────────────────────────────────
interface AnalysisTaskInputs {
    domains: string[];
    date_from: string;
    date_to: string;
    chart_requests: ChartRequest[];
    prompt: string;
    model_id: string;
    cron_expression: string | null;
    analysis_goal: string | null;
    platforms: string[] | null;
    peer_ids: string[] | null;
    thresholds: Record<string, string> | null;
    include_data_disclosure: boolean;
    selected_lenses: string[] | null;
    disable_user_edit: boolean;
}

function buildTaskInputs(
    formState: WizardFormState,
    template: Template,
    modelId: string,
    cronExpression: string,
): AnalysisTaskInputs {
    const dateRangeKey = formState.default_date_range as string | undefined;
    const { dateFrom, dateTo } = resolveDateRange(dateRangeKey, template);

    const rawCharts = Array.isArray(formState.default_charts)
        ? (formState.default_charts as ChartRequest[])
        : [];
    const chartRequests = rawCharts.filter(
        (c) => c && typeof c.nl_query === "string" && c.nl_query.trim().length > 0,
    );

    const domains =
        (formState.default_domains as string[] | undefined) ||
        template.data_domains ||
        [];

    const platforms = formState.default_platforms as string[] | undefined;
    const peers = formState.default_peers as string[] | undefined;
    const lenses = formState.default_lenses as string[] | undefined;

    const thresholdVal = formState.default_threshold;
    const thresholds: Record<string, string> | null =
        thresholdVal != null && String(thresholdVal).trim() !== ""
            ? { sov_min: String(thresholdVal) }
            : null;

    const customPrompt = (formState.custom_prompt as string | undefined) || "";
    const prompt = customPrompt.trim() || template.default_prompt || "";

    return {
        domains,
        date_from: dateFrom,
        date_to: dateTo,
        chart_requests: chartRequests,
        prompt,
        model_id: modelId,
        cron_expression: cronExpression || null,
        analysis_goal: (formState.default_goal as string | null) || null,
        platforms: platforms && platforms.length > 0 ? platforms : null,
        peer_ids: peers && peers.length > 0 ? peers : null,
        thresholds,
        include_data_disclosure: formState.include_data_disclosure !== false,
        selected_lenses: lenses && lenses.length > 0 ? lenses : null,
        disable_user_edit: formState.disable_user_edit === true,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Premium ChartCard — delegates to shared PremiumChart component
// ─────────────────────────────────────────────────────────────────────────────
import { PremiumChart } from "@/components/charts/PremiumChart";

export function ChartCard({ chart }: { chart: ChartResult }) {
    return (
        <PremiumChart
            columns={chart.columns}
            rows={chart.rows}
            chart_type={chart.chart_type || (chart as { type?: string }).type}
            nl_query={chart.nl_query}
            error={chart.error}
            warning={chart.warning}
            height={200}
        />
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Lightweight SQL formatter for the progress log tooltip
// ─────────────────────────────────────────────────────────────────────────────
function formatSql(sql: string): string {
    return sql
        .replace(/\s+/g, " ")
        .replace(
            /\b(SELECT|FROM|WHERE|LEFT JOIN|INNER JOIN|JOIN|GROUP BY|ORDER BY|HAVING|LIMIT|AND|OR|ON|UNION|WITH|AS \()\b/gi,
            (m) => "\n" + m.toUpperCase(),
        )
        .trim();
}

// ─────────────────────────────────────────────────────────────────────────────
// Execution / Result View
// ─────────────────────────────────────────────────────────────────────────────
function ReportViewer({
    report,
    progress,
    isRunning,
    workflowSteps = [],
    sqlLogs = {},
}: {
    report: ReportOutput | null;
    progress: string[];
    isRunning: boolean;
    workflowSteps?: Array<{ step: number; name: string; label: string; status: string }>;
    sqlLogs?: Record<string, string>;
}) {
    const { t } = useTranslation("insights");
    return (
        <div className="space-y-6">
            {/* Workflow Steps Visualization */}
            {workflowSteps.length > 0 && (
                <div className="rounded-xl border bg-primary/[0.02] p-5 space-y-3">
                    <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        <Sparkles className="h-3.5 w-3.5 text-primary" />
                        {t("templateModal.analysisPipeline")}
                        {isRunning && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
                    </div>
                    <div className="flex items-center gap-1">
                        {workflowSteps.map((ws, i) => (
                            <div key={ws.step} className="flex items-center gap-1">
                                <div className="flex items-center gap-2">
                                    <div className={`w-7 h-7 rounded-full flex items-center justify-center border-2 transition-all ${
                                        ws.status === "done"
                                            ? "bg-primary border-primary text-primary-foreground"
                                            : ws.status === "running"
                                            ? "border-primary text-primary"
                                            : ws.status === "failed"
                                            ? "border-destructive text-destructive bg-destructive/10"
                                            : "border-muted-foreground/30 text-muted-foreground/50"
                                    }`}>
                                        {ws.status === "done"
                                            ? <CheckCircle2 className="h-3.5 w-3.5" />
                                            : ws.status === "running"
                                            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                            : ws.status === "failed"
                                            ? <AlertCircle className="h-3.5 w-3.5" />
                                            : <span className="text-[10px] font-semibold">{ws.step}</span>
                                        }
                                    </div>
                                    <span className={`text-xs font-medium whitespace-nowrap ${
                                        ws.status === "done" ? "text-primary" :
                                        ws.status === "running" ? "text-foreground" :
                                        ws.status === "failed" ? "text-destructive" :
                                        "text-muted-foreground/60"
                                    }`}>{ws.label}</span>
                                </div>
                                {i < workflowSteps.length - 1 && (
                                    <div className={`h-px w-6 mx-1 transition-colors ${
                                        ws.status === "done" ? "bg-primary" : "bg-border"
                                    }`} />
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Detailed Progress log */}
            {progress.length > 0 && (
                <div className="rounded-lg border bg-muted/5 p-4 space-y-2">
                    <div className="flex items-center gap-2 text-sm font-medium mb-3">
                        <img src="/Anthony_Chat.png" alt="Anthony" className="w-7 h-7 rounded-full object-contain" />
                        {t("templateModal.anthonyWorkLog")}
                        {isRunning && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
                    </div>
                    {progress.map((msg, i) => {
                        const isSqlEntry = msg.includes("Generated") && msg.includes("SQL") && Object.keys(sqlLogs).length > 0;
                        return (
                            <div key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                                {i < progress.length - 1 || !isRunning
                                    ? <CheckCircle2 className="h-3.5 w-3.5 text-primary flex-shrink-0 mt-0.5" />
                                    : <Loader2 className="h-3.5 w-3.5 animate-spin text-primary flex-shrink-0 mt-0.5" />
                                }
                                <div className="flex-1 min-w-0">
                                    <span>{msg}</span>
                                    {isSqlEntry && (
                                        <details className="mt-1.5">
                                            <summary className="cursor-pointer text-primary/70 hover:text-primary text-[11px] select-none">
                                                {t("templateModal.viewGeneratedSql", { count: Object.keys(sqlLogs).length })}
                                            </summary>
                                            <div className="mt-1 space-y-1.5 max-h-48 overflow-y-auto">
                                                {Object.entries(sqlLogs).map(([name, sql]) => (
                                                    <div key={name} className="rounded border bg-background/50 p-2">
                                                        <div className="font-mono text-[10px] text-primary/80 mb-0.5">{name}</div>
                                                        <pre className="font-mono text-[10px] text-muted-foreground whitespace-pre-wrap break-all leading-relaxed">{formatSql(String(sql))}</pre>
                                                    </div>
                                                ))}
                                            </div>
                                        </details>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Charts */}
            {report && (report.charts?.length ?? 0) > 0 && (
                <div>
                    <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                        <BarChart3 className="h-4 w-4 text-primary" />
                        {t("templateModal.dataCharts")}
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {report.charts.map((chart, i) => (
                            <ChartCard key={i} chart={chart} />
                        ))}
                    </div>
                </div>
            )}

            {/* Insights markdown */}
            {report?.insights_markdown && (
                <div>
                    <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                        <Sparkles className="h-4 w-4 text-primary" />
                        {t("templateModal.insightReport")}
                    </h3>
                    <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:font-semibold prose-a:text-primary prose-table:w-full prose-table:border prose-th:bg-muted/50 prose-th:p-2 prose-td:p-2 prose-td:border-t mt-4 border-t pt-4">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{report.insights_markdown}</ReactMarkdown>
                    </div>
                </div>
            )}

            {/* Quality Score */}
            {report?.quality_score && report.quality_score.overall_score != null && (
                <div className="rounded-xl border p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">{t("templateModal.qualityReview")}</h4>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        {[
                            { key: "data_accuracy_score", labelKey: "qualityDataAccuracy" as const },
                            { key: "consistency_score", labelKey: "qualityConsistency" as const },
                            { key: "completeness_score", labelKey: "qualityCompleteness" as const },
                            { key: "overall_score", labelKey: "qualityOverall" as const },
                        ].map(({ key, labelKey }) => {
                            const val = (report.quality_score as Record<string, unknown>)?.[key] as number | undefined;
                            if (val == null) return null;
                            return (
                                <div key={key} className="flex items-center justify-between rounded-lg bg-muted/30 px-3 py-2">
                                    <span className="text-xs font-medium">{t(`templateModal.${labelKey}`)}</span>
                                    <span className={`text-sm font-bold ${val >= 4 ? "text-primary" : val >= 3 ? "text-amber-500" : "text-destructive"}`}>{val}/5</span>
                                </div>
                            );
                        })}
                    </div>
                    {report.quality_score.summary && (
                        <p className="text-xs text-muted-foreground mt-2">{report.quality_score.summary}</p>
                    )}
                    {report.quality_score.issues && report.quality_score.issues.length > 0 && (
                        <div className="mt-2 pt-2 border-t">
                            <p className="text-xs font-medium text-muted-foreground mb-1">{t("templateModal.issuesFound")}</p>
                            <ul className="text-xs text-muted-foreground space-y-0.5">
                                {report.quality_score.issues.map((issue, i) => (
                                    <li key={i}>- {issue}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Modal
// ─────────────────────────────────────────────────────────────────────────────
export default function TemplateConfigModal({
    open,
    template,
    clientId,
    userId = "",
    modelIds,
    onClose,
    onTaskCreated,
}: TemplateConfigModalProps) {
    const { t } = useTranslation("insights");
    // ── Host-level runtime settings (not owned by any workflow step) ────────
    const [modelId, setModelId] = useState(modelIds[0] || "");
    const [cronExpression, setCronExpression] = useState("");

    // ── Execution state ──────────────────────────────────────────────────────
    const [isRunning, setIsRunning] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [progress, setProgress] = useState<string[]>([]);
    const [sqlLogs, setSqlLogs] = useState<Record<string, string>>({});
    const [workflowSteps, setWorkflowSteps] = useState<
        Array<{ step: number; name: string; label: string; status: string }>
    >([]);
    const [report, setReport] = useState<ReportOutput | null>(null);
    const [runId, setRunId] = useState<string | null>(null);
    const [view, setView] = useState<"config" | "result">("config");

    // Stable ref so polling can be cleared even if runReport re-runs
    const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Normalize template.wizard_config once per template change so the shell
    // always receives a plain object (the backend sometimes returns it as a
    // JSON string depending on the serializer path).
    const wizardTemplate: WizardTemplate | null = template
        ? {
              id: template.id,
              name: template.name,
              description: template.description,
              icon: template.icon,
              data_domains: template.data_domains,
              default_prompt: template.default_prompt,
              task_type: "analysis",
              wizard_config: normalizeWizardConfig(template.wizard_config),
              filters: template.filters,
              chart_requests: Array.isArray(template.chart_requests)
                  ? template.chart_requests
                  : undefined,
              defaults: template.defaults,
          }
        : null;

    // ── Initialize / resume state when a new template is opened ──────────────
    useEffect(() => {
        if (!(template && open)) return;

        setModelId((prev) => prev || modelIds[0] || "");
        setCronExpression(template.cron_expression || "");

        // ── Resume a RUNNING task opened from All Tasks ──────────────────
        if (template.status === "RUNNING" && template.run_id) {
            const resumeRunId = template.run_id;
            setIsRunning(true);
            setView("result");
            setReport(null);
            const existingLogs: Array<{ label?: string }> = Array.isArray(template.status_logs)
                ? template.status_logs
                : [];
            setProgress(
                existingLogs.length > 0
                    ? existingLogs.map((l) => l.label || "").filter(Boolean)
                    : [t("templateModal.loadingProgress")],
            );
            setRunId(resumeRunId);

            if (pollTimerRef.current !== null) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
            }
            startPolling(resumeRunId);
            return;
        }

        if (template.status === "COMPLETED") {
            // ── Restore a COMPLETED task's report ───────────────────────
            setIsRunning(false);
            setView("result");
            const existingLogs: Array<{ label?: string }> = Array.isArray(template.status_logs)
                ? template.status_logs
                : [];
            setProgress(
                existingLogs.length > 0
                    ? existingLogs.map((l) => l.label || "").filter(Boolean)
                    : [t("templateModal.restoreComplete")],
            );
            let reportOut = template.report_output;
            if (typeof reportOut === "string") {
                try { reportOut = JSON.parse(reportOut); } catch { reportOut = null; }
            }
            if (reportOut && typeof reportOut === "object") {
                const ro = reportOut as ReportOutput;
                if (!Array.isArray(ro.charts)) ro.charts = [];
                setReport(ro);
            } else {
                setReport(null);
            }
            return;
        }

        // ── Fresh / SAVED task: reset to config mode ─────────────────────
        setReport(null);
        setProgress([]);
        setWorkflowSteps([]);
        setIsRunning(false);
        setIsSaving(false);
        setView("config");
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [template, open]);

    // ── Clean up polling interval when modal closes ──────────────────────────
    useEffect(() => {
        if (!open) {
            if (pollTimerRef.current !== null) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
            }
        }
        return () => {
            if (pollTimerRef.current !== null) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
            }
        };
    }, [open]);

    // ── Default model picker if not yet set ──────────────────────────────────
    useEffect(() => {
        if (modelIds.length > 0 && !modelId) setModelId(modelIds[0]);
    }, [modelIds, modelId]);

    // ── Polling helper (shared by runReport + resume flow) ───────────────────
    const stopPolling = useCallback(() => {
        if (pollTimerRef.current !== null) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
        }
    }, []);

    const startPolling = useCallback((runIdToPoll: string) => {
        const doPoll = async () => {
            try {
                const data = await fetchJSON(
                    `${AGENT_BASE}/tasks/${runIdToPoll}/progress`,
                ).catch(() => null);
                if (!data) return;

                if (data.workflow_steps && data.workflow_steps.length > 0) {
                    setWorkflowSteps(data.workflow_steps);
                }

                const dbLogs: Array<{
                    label?: string;
                    event?: string;
                    sqls?: Record<string, string>;
                }> = data.status_logs || [];
                if (dbLogs.length > 0) {
                    setProgress((prev) => {
                        const dbLabels = dbLogs.map((l) => l.label || "").filter(Boolean);
                        const prefix = prev.filter(
                            (msg) => !dbLabels.some((dl) => dl.startsWith(msg.slice(0, 8))),
                        );
                        return [...prefix, ...dbLabels];
                    });
                    const sqlEntry = dbLogs.find((l) => l.event === "sql_generated" && l.sqls);
                    if (sqlEntry?.sqls) setSqlLogs(sqlEntry.sqls);
                }

                if (data.status === "COMPLETED") {
                    stopPolling();
                    let reportOut = data.output || data.report_output;
                    if (typeof reportOut === "string") {
                        try { reportOut = JSON.parse(reportOut); } catch { reportOut = null; }
                    }
                    if (reportOut && typeof reportOut === "object") {
                        if (!Array.isArray(reportOut.charts)) reportOut.charts = [];
                        setReport(reportOut);
                    }
                    setIsRunning(false);
                    setProgress((p) => {
                        const last = p[p.length - 1] || "";
                        return last.includes("✓")
                            ? p
                            : [...p, t("templateModal.reportCompleteMsg")];
                    });
                } else if (data.status === "FAILED") {
                    stopPolling();
                    setProgress((p) => [
                        ...p,
                        t("templateModal.errorMsg", { message: data.error_message || t("templateModal.unknownError") }),
                    ]);
                    setIsRunning(false);
                }
            } catch {
                // Network error — retry next tick
            }
        };

        doPoll();
        pollTimerRef.current = setInterval(doPoll, 8000);
    }, [stopPolling, t]);

    // ── Submit handlers — receive the schema-driven FormState ────────────────
    const saveTemplate = useCallback(
        async (formState: WizardFormState) => {
            if (!template || !clientId) return;
            setIsSaving(true);
            try {
                const taskInputs = buildTaskInputs(
                    formState,
                    template,
                    modelId,
                    cronExpression,
                );
                await fetchJSON(`${AGENT_BASE}/tasks`, {
                    method: "POST",
                    body: JSON.stringify({
                        client_id: clientId,
                        user_id: userId,
                        task_type: "analysis",
                        task_name:
                            template.name +
                            (cronExpression ? t("templateModal.taskNameSuffixCron") : t("templateModal.taskNameSuffixSaved")),
                        template_id: template.id === "blank" ? null : template.id,
                        inputs: taskInputs,
                        save_only: true,
                    }),
                });
                toast.success(t("templateModal.toast.saveSuccess"));
                onTaskCreated?.();
                onClose();
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                console.error(e);
                toast.error(t("templateModal.toast.saveFailed", { message: msg }));
            } finally {
                setIsSaving(false);
            }
        },
        [template, clientId, userId, modelId, cronExpression, onTaskCreated, onClose, t],
    );

    const runReport = useCallback(
        async (formState: WizardFormState) => {
            if (!template || !clientId) return;
            setIsRunning(true);
            setProgress([t("templateModal.initMsg")]);
            setSqlLogs({});
            setWorkflowSteps([]);
            setView("result");
            setReport(null);

            try {
                const taskInputs = buildTaskInputs(
                    formState,
                    template,
                    modelId,
                    cronExpression,
                );

                const isEdit = !!template.run_id;
                const result = await fetchJSON(
                    isEdit
                        ? `${AGENT_BASE}/tasks/${template.run_id}`
                        : `${AGENT_BASE}/tasks`,
                    {
                        method: isEdit ? "PUT" : "POST",
                        body: JSON.stringify(
                            isEdit
                                ? {
                                      client_id: clientId,
                                      user_id: userId,
                                      task_name: template.name,
                                      inputs: taskInputs,
                                      save_only: false,
                                  }
                                : {
                                      client_id: clientId,
                                      user_id: userId,
                                      task_type: "analysis",
                                      task_name: template.name,
                                      template_id:
                                          template.id === "blank" ? null : template.id,
                                      inputs: taskInputs,
                                  },
                        ),
                    },
                );

                const newRunId = result.id;
                setRunId(newRunId);
                onTaskCreated?.();

                startPolling(newRunId);
            } catch (e) {
                stopPolling();
                const msg = e instanceof Error ? e.message : String(e);
                setProgress((p) => [...p, t("templateModal.launchFailedMsg", { message: msg })]);
                setIsRunning(false);
            }
        },
        [template, clientId, userId, modelId, cronExpression, onTaskCreated, startPolling, stopPolling, t],
    );

    const handleWizardSubmit = useCallback(
        async (formState: WizardFormState, actionKey: string) => {
            if (actionKey === "save") {
                await saveTemplate(formState);
            } else if (actionKey === "run") {
                await runReport(formState);
            }
        },
        [saveTemplate, runReport],
    );

    if (!template) return null;

    // ── Runtime settings bar — model picker + cron expression.
    // Rendered via the WizardShell `footerExtras` slot so it sits below every
    // step and is always visible right above the wizard nav buttons.
    const runtimeSettingsBar = (
        <div className="border border-border/60 rounded-lg p-4 bg-muted/10 space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
                <span className="text-xs font-medium text-muted-foreground shrink-0">
                    {t("templateModal.runtimeSettings.modelLabel")}
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                    {modelIds.map((m) => (
                        <button
                            key={m}
                            type="button"
                            onClick={() => setModelId(m)}
                            className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-all ${
                                modelId === m
                                    ? "bg-primary/10 border-primary/40 text-primary"
                                    : "bg-muted/30 border-border text-muted-foreground hover:border-primary/20"
                            }`}
                        >
                            {m.replace("gemini-", "Gemini ").replace("-preview", "")}
                        </button>
                    ))}
                </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
                <input
                    type="checkbox"
                    id="enable-cron"
                    className="rounded"
                    checked={!!cronExpression}
                    onChange={(e) =>
                        setCronExpression(e.target.checked ? "0 9 * * 1" : "")
                    }
                />
                <label
                    htmlFor="enable-cron"
                    className="text-xs font-medium cursor-pointer select-none"
                >
                    {t("templateModal.runtimeSettings.enableCron")}
                </label>
                {!!cronExpression && (
                    <input
                        type="text"
                        value={cronExpression}
                        onChange={(e) => setCronExpression(e.target.value)}
                        placeholder={t("templateModal.runtimeSettings.cronPlaceholder")}
                        className="flex-1 min-w-[180px] max-w-sm rounded-md border border-input bg-background px-3 py-1.5 text-xs font-mono h-8 focus:outline-none focus:ring-2 focus:ring-ring/30"
                    />
                )}
            </div>
            {!!cronExpression && (
                <p className="text-[11px] text-muted-foreground pl-6">
                    <Trans
                        i18nKey="templateModal.runtimeSettings.cronHint"
                        ns="insights"
                        components={{ 1: <code /> }}
                    />
                </p>
            )}
        </div>
    );

    return (
        <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
            <DialogContent
                className="max-w-5xl w-[90vw] max-h-[90vh] flex flex-col overflow-hidden p-0"
                hideCloseButton
            >
                <DialogTitle className="sr-only">
                    Anthony GEO Analyst - {template.name}
                </DialogTitle>
                <DialogDescription className="hidden">
                    Configure analysis task and run.
                </DialogDescription>

                {/* Anthony header */}
                <div className="flex items-center gap-4 px-6 pt-6 pb-4 border-b border-border bg-muted/20 shrink-0">
                    <div className="relative">
                        <img
                            src="/Anthony_Chat.png"
                            alt="Anthony"
                            className="w-14 h-14 rounded-full object-contain bg-gradient-to-br from-primary/20 to-muted ring-2 ring-primary/30"
                        />
                        <span className="absolute bottom-0 right-0 w-3.5 h-3.5 bg-emerald-400 rounded-full border-2 border-background" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                            <h2 className="text-base font-semibold">Anthony</h2>
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                                {t("templateModal.header.agentRole")}
                            </span>
                            <span className="text-xl ml-1">{template.icon}</span>
                            <span className="text-sm font-medium text-foreground">
                                {template.name}
                            </span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                            {t("templateModal.header.agentGreeting")}
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Domain badges below header */}
                {template.data_domains.length > 0 && (
                    <div className="flex gap-1.5 px-6 py-2 border-b border-border/50 shrink-0 flex-wrap">
                        {template.data_domains.map((d) => {
                            const meta = DOMAIN_META[d];
                            return meta ? (
                                <Badge
                                    key={d}
                                    variant="outline"
                                    className={`text-[11px] ${meta.color}`}
                                >
                                    {meta.icon} {t(`templateModal.domains.${meta.labelKey}`)}
                                </Badge>
                            ) : null;
                        })}
                    </div>
                )}

                {view === "config" ? (
                    <div className="flex-1 overflow-y-auto px-6 py-4">
                        <WizardShell
                            scope="analysis"
                            template={wizardTemplate}
                            clientId={clientId}
                            userId={userId}
                            disabled={isRunning || isSaving}
                            actions={[
                                {
                                    key: "save",
                                    label: isSaving ? t("templateModal.actions.saving") : t("templateModal.actions.save"),
                                    variant: "secondary",
                                    icon: (
                                        <Database className="h-3.5 w-3.5 mr-1.5 text-primary" />
                                    ),
                                    loading: isSaving,
                                    disabled: isRunning,
                                },
                                {
                                    key: "run",
                                    label: t("templateModal.actions.run"),
                                    variant: "primary",
                                    icon: <ZapIcon className="h-4 w-4 mr-1.5" />,
                                    loading: isRunning,
                                    disabled: isSaving,
                                },
                            ]}
                            onSubmit={handleWizardSubmit}
                            footerExtras={runtimeSettingsBar}
                        />
                    </div>
                ) : (
                    <>
                        <div className="flex-1 overflow-y-auto px-6 py-4">
                            <ReportViewer
                                report={report}
                                progress={progress}
                                isRunning={isRunning}
                                workflowSteps={workflowSteps}
                                sqlLogs={sqlLogs}
                            />
                        </div>
                        <div className="flex-shrink-0 flex items-center justify-between px-6 pb-5 pt-4 border-t">
                            {!isRunning && (
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setView("config")}
                                >
                                    <ChevronLeft className="h-4 w-4 mr-1.5" />
                                    {t("templateModal.actions.reconfigure")}
                                </Button>
                            )}
                            <div className="flex items-center gap-2 ml-auto">
                                {!isRunning && report && runId && (
                                    <>
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            onClick={() =>
                                                window.open(
                                                    getReportURL(runId, clientId),
                                                    "_blank",
                                                )
                                            }
                                            className="gap-1.5"
                                        >
                                            <Eye className="h-3.5 w-3.5" />
                                            {t("templateModal.actions.viewReportDetails")}
                                        </Button>
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            onClick={() => exportAgentTaskHTML(runId, clientId)}
                                            className="gap-1.5"
                                        >
                                            <FileDown className="h-3.5 w-3.5" />
                                            {t("templateModal.actions.exportHtml")}
                                        </Button>
                                    </>
                                )}
                                <Button size="sm" onClick={onClose}>
                                    {isRunning ? (
                                        <>
                                            <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                                            {t("templateModal.actions.runInBackgroundClose")}
                                        </>
                                    ) : (
                                        t("templateModal.actions.close")
                                    )}
                                </Button>
                            </div>
                        </div>
                    </>
                )}
            </DialogContent>
        </Dialog>
    );
}
